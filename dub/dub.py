#!/usr/bin/env python3
"""Dub a foreign-language audio track into English and mux it back into the
original file alongside the original tracks. Fully local — no cloud services.

Two modes:

  default        Fast "lector-style" dub: one stock narrator voice (Kokoro)
                 spoken over the original track, which is ducked underneath
                 so music and effects survive.

  --clone        Voice-preserving dub: Demucs splits vocals from the
                 music/effects bed, XTTS-v2 clones each segment's original
                 speaker audio to speak the English line, and the dub is
                 mixed over the untouched background stem. Slower, needs a
                 GPU to be pleasant, keeps the original voices and much of
                 their tone.

Shared pipeline:
  1. ffprobe finds the foreign audio track (first track not tagged eng/en).
  2. faster-whisper transcribes AND translates to English in one pass
     (task="translate"), producing timestamped English segments.
  3. TTS clips are placed at their original timestamps; clips longer than
     their slot are sped up (pitch-preserving atempo, capped at 1.5x).
  4. ffmpeg muxes the mix into a copy of the original file as a new "eng"
     track. All original tracks are stream-copied untouched.

Models are loaded strictly one at a time (Demucs runs as a subprocess and
exits; Whisper is freed before TTS loads), so the whole thing fits in 8GB
of VRAM with headroom.

Usage:
  python dub.py movie.mkv                    # -> movie.eng-dub.mkv (narrator)
  python dub.py movie.mkv --clone            # voice-cloned dub
  python dub.py movie.mkv --clone --lang ja  # skip language autodetect
  python dub.py /path/to/folder              # batch: every file with no eng track
"""

import argparse
import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts"}
ENGLISH_TAGS = {"eng", "en"}
TTS_SR = 24000  # Kokoro and XTTS-v2 both output 24 kHz
MAX_SPEEDUP = 1.5  # never chipmunk a segment more than this to fit its slot
REF_MIN_S = 3.0    # XTTS wants at least a few seconds of reference audio
REF_MAX_S = 12.0


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def free_cuda():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def ffprobe_streams(path):
    out = run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]).stdout
    return json.loads(out)


def audio_streams(info):
    return [s for s in info["streams"] if s.get("codec_type") == "audio"]


def stream_lang(s):
    return (s.get("tags", {}).get("language") or "und").lower()


def pick_foreign_track(streams, forced_index=None):
    """Return the audio stream to dub, or None if nothing suitable."""
    if forced_index is not None:
        for s in streams:
            if s["index"] == forced_index:
                return s
        sys.exit(f"error: no audio stream with index {forced_index}")
    foreign = [s for s in streams if stream_lang(s) not in ENGLISH_TAGS]
    return foreign[0] if foreign else None


def has_english(streams):
    return any(stream_lang(s) in ENGLISH_TAGS for s in streams)


def extract_audio(src, stream_index, dst, mono16k=False):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src),
           "-map", f"0:{stream_index}", "-vn"]
    if mono16k:
        cmd += ["-ac", "1", "-ar", "16000"]
    cmd += [str(dst)]
    run(cmd)


def demucs_separate(wav_path, tmpdir):
    """Split audio into vocals + everything-else with Demucs (GPU if there).

    Runs as a subprocess so its VRAM is fully released when it exits.
    Returns (vocals_wav, background_wav).
    """
    print("  separating vocals from music/effects (Demucs) ...")
    run([sys.executable, "-m", "demucs", "--two-stems", "vocals",
         "-n", "htdemucs", "-o", str(tmpdir), str(wav_path)])
    stem_dir = Path(tmpdir) / "htdemucs" / Path(wav_path).stem
    vocals, background = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    if not vocals.exists() or not background.exists():
        raise RuntimeError(f"demucs did not produce stems in {stem_dir}")
    return vocals, background


def translate_to_english(wav_path, model_size, lang=None):
    from faster_whisper import WhisperModel
    print(f"  loading whisper '{model_size}' ...")
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    print("  transcribing + translating to English ...")
    segments, info = model.transcribe(
        str(wav_path), task="translate", language=lang, vad_filter=True)
    segs = [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
    print(f"  detected language: {info.language} "
          f"({info.language_probability:.0%}), {len(segs)} segments")
    del model
    free_cuda()  # make room for the TTS model
    return segs


class KokoroSynth:
    """Stock-voice narrator TTS (fast, CPU-friendly)."""

    def __init__(self, voice):
        from kokoro import KPipeline
        print(f"  loading Kokoro TTS (voice {voice}) ...")
        self.pipeline = KPipeline(lang_code="a")  # American English
        self.voice = voice

    def __call__(self, text, i, start, end):
        import numpy as np
        chunks = []
        for _, _, audio in self.pipeline(text, voice=self.voice):
            a = audio.numpy() if hasattr(audio, "numpy") else audio
            chunks.append(a)
        if not chunks:
            return np.zeros(0, dtype="float32")
        return np.concatenate(chunks).astype("float32")


class CloneSynth:
    """Zero-shot voice cloning via XTTS-v2: each segment's own original
    audio is the voice reference for its English line, so whoever is
    speaking at that moment is (approximately) the voice that speaks the
    translation — no diarization needed."""

    def __init__(self, vocals_wav, tmpdir):
        import numpy as np
        import soundfile as sf
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        from TTS.api import TTS
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        print(f"  loading XTTS-v2 voice-cloning TTS on {device} ...")
        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self.tmpdir = Path(tmpdir)
        audio, self.sr = sf.read(vocals_wav, dtype="float32")
        self.vocals = audio.mean(axis=1) if audio.ndim > 1 else audio
        self.np, self.sf = np, sf

    def _reference(self, i, start, end):
        """Write a REF_MIN_S..REF_MAX_S window of original vocals around
        the segment to use as the cloning reference."""
        dur = end - start
        if dur < REF_MIN_S:  # widen symmetrically to the minimum
            pad = (REF_MIN_S - dur) / 2
            start, end = start - pad, end + pad
        end = min(end, start + REF_MAX_S)
        total = self.vocals.size / self.sr
        # shift (not truncate) the window when it runs past either edge
        if start < 0:
            end, start = min(end - start, total), 0
        if end > total:
            start, end = max(start - (end - total), 0), total
        a, b = int(start * self.sr), int(end * self.sr)
        ref = self.tmpdir / f"ref-{i}.wav"
        self.sf.write(ref, self.vocals[a:b], self.sr)
        return ref

    def __call__(self, text, i, start, end):
        ref = self._reference(i, start, end)
        try:
            wav = self.tts.tts(text=text, speaker_wav=str(ref), language="en")
        finally:
            ref.unlink(missing_ok=True)
        return self.np.asarray(wav, dtype="float32")


def time_stretch(samples, speed, tmpdir, tag):
    """Speed up audio by `speed` (pitch-preserving) via ffmpeg atempo."""
    import soundfile as sf
    src = Path(tmpdir) / f"seg-{tag}-in.wav"
    dst = Path(tmpdir) / f"seg-{tag}-out.wav"
    sf.write(src, samples, TTS_SR)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-filter:a", f"atempo={speed:.4f}", str(dst)])
    out, _ = sf.read(dst, dtype="float32")
    src.unlink()
    dst.unlink()
    return out


def build_dub_track(segments, total_duration, synth, tmpdir, out_wav):
    """Speak every segment and place it on the original timeline."""
    import numpy as np
    import soundfile as sf

    buf = np.zeros(int((total_duration + 2) * TTS_SR), dtype="float32")
    for i, (start, end, text) in enumerate(segments):
        try:
            clip = synth(text, i, start, end)
        except Exception as e:
            print(f"  warning: TTS failed on segment {i} ({e}); skipping")
            continue
        if clip.size == 0:
            continue
        next_start = segments[i + 1][0] if i + 1 < len(segments) else total_duration
        slot = max(next_start - start, end - start, 0.3)
        clip_dur = clip.size / TTS_SR
        if clip_dur > slot:
            speed = min(clip_dur / slot, MAX_SPEEDUP)
            clip = time_stretch(clip, speed, tmpdir, i)
        pos = int(start * TTS_SR)
        room = buf.size - pos
        clip = clip[:room]
        buf[pos:pos + clip.size] += clip
        if (i + 1) % 25 == 0 or i + 1 == len(segments):
            print(f"  spoke {i + 1}/{len(segments)} segments")

    np.clip(buf, -1.0, 1.0, out=buf)
    sf.write(out_wav, buf, TTS_SR)


def mix_with_bed(orig_wav, dub_wav, out_wav):
    """Duck the original track under the English speech, keep music/effects.
    Used in narrator mode, where the original vocals are still in the bed."""
    fc = (
        "[1:a]asplit=2[sc][voice];"
        "[0:a][sc]sidechaincompress="
        "threshold=0.015:ratio=10:attack=25:release=400[duck];"
        "[duck][voice]amix=inputs=2:duration=longest:normalize=0[out]"
    )
    run(["ffmpeg", "-y", "-v", "error", "-i", str(orig_wav), "-i", str(dub_wav),
         "-filter_complex", fc, "-map", "[out]", str(out_wav)])


def mix_over_background(bg_wav, dub_wav, out_wav):
    """Lay the cloned English vocals over the clean instrumental/SFX stem.
    No ducking needed — Demucs already removed the original vocals."""
    fc = "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[out]"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(bg_wav), "-i", str(dub_wav),
         "-filter_complex", fc, "-map", "[out]", str(out_wav)])


def mux(src, dub_wav, dst, n_existing_audio):
    """Copy every original stream and append the dub as a new eng track."""
    n = n_existing_audio
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(dub_wav),
         "-map", "0", "-map", "1:a",
         "-c", "copy", f"-c:a:{n}", "aac", f"-b:a:{n}", "160k",
         f"-metadata:s:a:{n}", "language=eng",
         f"-metadata:s:a:{n}", "title=English (AI dub)",
         f"-disposition:a:{n}", "0",
         str(dst)])


def dub_file(src, args):
    src = Path(src)
    info = ffprobe_streams(src)
    streams = audio_streams(info)
    if not streams:
        print(f"skip {src.name}: no audio streams")
        return

    if has_english(streams) and args.track is None and not args.force:
        print(f"skip {src.name}: already has an English track (use --force)")
        return

    track = pick_foreign_track(streams, args.track)
    if track is None:
        print(f"skip {src.name}: no foreign-language track found")
        return

    dst = Path(args.output) if args.output else src.with_name(
        f"{src.stem}.eng-dub{src.suffix}")
    duration = float(info["format"]["duration"])
    mode = "clone" if args.clone else "narrator"
    print(f"{src.name}: dubbing stream {track['index']} "
          f"({stream_lang(track)}) -> {dst.name} [{mode}]")

    with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
        tmp = Path(tmp)
        full_wav = tmp / "orig.wav"
        dub_wav = tmp / "dub.wav"
        mix_wav = tmp / "mix.wav"

        if args.clone:
            extract_audio(src, track["index"], full_wav)
            vocals, background = demucs_separate(full_wav, tmp)
            segments = translate_to_english(vocals, args.model, args.lang)
            if not segments:
                print(f"skip {src.name}: no speech found")
                return
            synth = CloneSynth(vocals, tmp)
            build_dub_track(segments, duration, synth, tmp, dub_wav)
            del synth
            free_cuda()
            print("  mixing cloned vocals over the background stem ...")
            mix_over_background(background, dub_wav, mix_wav)
            final_wav = mix_wav
        else:
            asr_wav = tmp / "asr.wav"
            extract_audio(src, track["index"], asr_wav, mono16k=True)
            segments = translate_to_english(asr_wav, args.model, args.lang)
            if not segments:
                print(f"skip {src.name}: no speech found")
                return
            synth = KokoroSynth(args.voice)
            build_dub_track(segments, duration, synth, tmp, dub_wav)
            if args.plain:
                final_wav = dub_wav
            else:
                print("  mixing dub over ducked original ...")
                extract_audio(src, track["index"], full_wav)
                mix_with_bed(full_wav, dub_wav, mix_wav)
                final_wav = mix_wav

        print("  muxing into container ...")
        mux(src, final_wav, dst, len(streams))
    print(f"done: {dst}")


def main():
    ap = argparse.ArgumentParser(
        description="Dub foreign audio tracks into English, locally.")
    ap.add_argument("inputs", nargs="+",
                    help="video file(s) or a directory to scan")
    ap.add_argument("--clone", action="store_true",
                    help="voice-preserving mode: Demucs stem separation + "
                         "XTTS-v2 zero-shot cloning of the original speakers")
    ap.add_argument("--model", default="small",
                    help="faster-whisper model size (tiny/base/small/medium/"
                         "large-v3, default: small)")
    ap.add_argument("--lang",
                    help="source language hint, e.g. 'ja' (default: autodetect)")
    ap.add_argument("--voice", default="af_heart",
                    help="Kokoro voice for narrator mode (default: af_heart)")
    ap.add_argument("--track", type=int,
                    help="ffmpeg stream index of the audio track to dub "
                         "(default: first non-English track)")
    ap.add_argument("--plain", action="store_true",
                    help="narrator mode only: dub voice by itself, no music bed")
    ap.add_argument("--force", action="store_true",
                    help="dub even if the file already has an English track")
    ap.add_argument("-o", "--output",
                    help="output path (single input only; default: "
                         "<name>.eng-dub.<ext> next to the original)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("error: ffmpeg/ffprobe not found on PATH")

    files = []
    for item in args.inputs:
        p = Path(item)
        if p.is_dir():
            files += sorted(f for f in p.rglob("*")
                            if f.suffix.lower() in VIDEO_EXTS)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"error: {item} not found")

    if args.output and len(files) > 1:
        sys.exit("error: -o/--output only works with a single input file")

    for f in files:
        try:
            dub_file(f, args)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode(errors="replace")[-800:]
            print(f"failed on {f}: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
