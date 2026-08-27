#!/usr/bin/env python3
"""Dub a foreign-language audio track into English and mux it back into the
original file alongside the original tracks.

Pipeline (all local, no cloud services):
  1. ffprobe finds the foreign audio track (first track not tagged eng/en).
  2. ffmpeg extracts it to wav.
  3. faster-whisper transcribes AND translates to English in one pass
     (task="translate"), producing timestamped English segments.
  4. Kokoro TTS speaks each segment; each clip is placed at its original
     timestamp. Clips that run longer than their slot are sped up (atempo,
     capped at 1.5x) so the dub stays in sync.
  5. The original track is ducked under the English speech (sidechain
     compression) so music and effects survive, then the mix is muxed into
     a copy of the original file as a new "eng" track. Original tracks are
     copied untouched.

Usage:
  python dub.py movie.mkv                 # -> movie.eng-dub.mkv
  python dub.py movie.mkv --plain         # dub voice only, no music bed
  python dub.py /path/to/folder           # batch: every video missing an eng track
  python dub.py movie.mkv --track 2       # dub a specific audio stream index
  python dub.py movie.mkv --model medium --voice af_heart
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts"}
ENGLISH_TAGS = {"eng", "en"}
TTS_SR = 24000  # Kokoro output sample rate
MAX_SPEEDUP = 1.5  # never chipmunk a segment more than this to fit its slot


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


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


def translate_to_english(wav_path, model_size):
    from faster_whisper import WhisperModel
    print(f"  loading whisper '{model_size}' ...")
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    print("  transcribing + translating to English ...")
    segments, info = model.transcribe(
        str(wav_path), task="translate", vad_filter=True)
    segs = [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
    print(f"  detected language: {info.language} "
          f"({info.language_probability:.0%}), {len(segs)} segments")
    return segs


def tts_segment(pipeline, text, voice):
    import numpy as np
    chunks = []
    for _, _, audio in pipeline(text, voice=voice):
        a = audio.numpy() if hasattr(audio, "numpy") else audio
        chunks.append(a)
    if not chunks:
        return np.zeros(0, dtype="float32")
    return np.concatenate(chunks).astype("float32")


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


def build_dub_track(segments, total_duration, voice, tmpdir, out_wav):
    """Speak every segment and place it on the original timeline."""
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    print(f"  loading Kokoro TTS (voice {voice}) ...")
    pipeline = KPipeline(lang_code="a")  # American English

    buf = np.zeros(int((total_duration + 2) * TTS_SR), dtype="float32")
    for i, (start, end, text) in enumerate(segments):
        clip = tts_segment(pipeline, text, voice)
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
    """Duck the original track under the English speech, keep music/effects."""
    fc = (
        "[1:a]asplit=2[sc][voice];"
        "[0:a][sc]sidechaincompress="
        "threshold=0.015:ratio=10:attack=25:release=400[duck];"
        "[duck][voice]amix=inputs=2:duration=longest:normalize=0[out]"
    )
    run(["ffmpeg", "-y", "-v", "error", "-i", str(orig_wav), "-i", str(dub_wav),
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
    print(f"{src.name}: dubbing stream {track['index']} "
          f"({stream_lang(track)}) -> {dst.name}")

    with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
        tmp = Path(tmp)
        asr_wav = tmp / "asr.wav"
        full_wav = tmp / "orig.wav"
        dub_wav = tmp / "dub.wav"
        mix_wav = tmp / "mix.wav"

        extract_audio(src, track["index"], asr_wav, mono16k=True)
        segments = translate_to_english(asr_wav, args.model)
        if not segments:
            print(f"skip {src.name}: no speech found")
            return

        build_dub_track(segments, duration, args.voice, tmp, dub_wav)

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
    ap.add_argument("--model", default="small",
                    help="faster-whisper model size (tiny/base/small/medium/"
                         "large-v3, default: small)")
    ap.add_argument("--voice", default="af_heart",
                    help="Kokoro voice (default: af_heart)")
    ap.add_argument("--track", type=int,
                    help="ffmpeg stream index of the audio track to dub "
                         "(default: first non-English track)")
    ap.add_argument("--plain", action="store_true",
                    help="dub voice only; skip mixing over the ducked original")
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
