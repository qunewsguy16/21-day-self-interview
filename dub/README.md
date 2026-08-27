# Local English dubbing for foreign audio tracks

One script that takes a video with a foreign-language audio track (Japanese,
French, anything Whisper knows), generates a spoken English dub **entirely on
your own machine**, and muxes that dub back into a copy of the original file
as an extra `eng` track. All original video, audio, and subtitle tracks are
copied through untouched — the output just has one more audio track you can
select in your player.

No cloud services, no API keys, no gated models. Everything downloads once
from Hugging Face on first run, then runs offline.

## Default mode: every speaker gets their own cloned voice

The goal is a realistic dub that keeps each original speaker's voice
identity and tone — every character consistently voiced by a clone of
themselves:

| Step | Tool | What it does |
|---|---|---|
| Demix | [Demucs](https://github.com/facebookresearch/demucs) (htdemucs, two-stem) | Splits the track into **vocals** and **music/effects**. The clean background stem goes straight into the final mix; the clean vocal stem feeds everything downstream. |
| Translate | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Transcribes **and** translates to English in a single pass (`task="translate"`) with timestamps — no separate translation model or LLM |
| Separate speakers | [SpeechBrain ECAPA](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) + clustering | A speaker embedding is computed for every segment of the vocal stem and the segments are clustered into distinct speakers. Short interjections that are too brief to cluster reliably are assigned to whichever speaker's voice they're acoustically closest to. |
| Clone + speak | [XTTS-v2](https://github.com/idiap/coqui-ai-TTS) | One **voice profile per speaker**, built from up to ~25 s of that speaker's longest, cleanest lines. Its cloning latents are computed once and reused for every line the speaker has — consistent voices, and much faster than re-cloning per segment. |
| Assemble | script + ffmpeg | Clips placed at original timestamps; long ones sped up (pitch-preserving, ≤1.5×) to stay in sync |
| Mix + mux | ffmpeg | Cloned English vocals over the untouched background stem, muxed in as an AAC track tagged `language=eng`, titled "English (AI dub)" |

`--speakers N` pins the speaker count when you know it (recommended for best
results); otherwise it's detected automatically.

## `--narrator` mode — fast and simple

One stock voice (Kokoro) reads the translation over the original track,
which is ducked under the speech so music and effects survive. Like a
classic lector dub. Runs fine on CPU; good for a quick first pass before
committing to a full clone run.

## VRAM: fits in 8 GB

The pipeline never holds two models at once. Demucs runs as a subprocess and
releases everything when it exits; Whisper and the speaker encoder are each
freed before the next model loads. Peak usage is one model at a time —
Demucs ~3 GB, Whisper `small`/`medium` ~1–3 GB, ECAPA <1 GB, XTTS-v2
~2.5 GB — comfortable on an 8 GB card like an RTX 4070 Laptop. CPU fallback
works everywhere, just slower.

## Install

```bash
# system deps
#   Windows:  winget install ffmpeg    (espeak-ng only needed for --narrator:
#             installer from https://github.com/espeak-ng/espeak-ng/releases)
#   Linux:    sudo apt install ffmpeg espeak-ng
#   macOS:    brew install ffmpeg espeak-ng

# GPU torch first (CUDA 12.x):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt          # base (narrator mode + shared deps)
pip install -r requirements-clone.txt    # default per-speaker clone mode
```

## Use

```bash
# per-speaker voice-cloned dub -> movie.eng-dub.mkv next to the original
python dub.py movie.mkv --lang ja --model medium

# pin the cast size when you know it
python dub.py movie.mkv --speakers 4

# batch: scan a folder, dub every video that has no English track yet
python dub.py /media/foreign-films/

# fast stock-voice pass
python dub.py movie.mkv --narrator

# other options
python dub.py movie.mkv --voice am_adam    # narrator voice
python dub.py movie.mkv --track 2          # dub a specific stream index
python dub.py movie.mkv --narrator --plain # narrator only, no music bed
python dub.py movie.mkv --force            # dub even if an eng track exists
```

By default the script picks the first audio track not tagged `eng`, and skips
files that already have an English track, so it's safe to point at a whole
library.

## Notes and knobs

- **Translation quality**: `--model small` is a fine default; `medium` or
  `large-v3` are noticeably better for Japanese and worth it on GPU. Pass
  `--lang ja` to skip autodetection on known-language libraries.
- **Speaker detection**: automatic detection errs toward merging similar
  voices. If two characters share a voice in the output or one character
  flips between voices, re-run with `--speakers N` set to the real cast
  size.
- **Cloning quality** depends on the reference audio: clean, close-mic'd
  dialogue clones well; shouting over explosions less so. Each speaker's
  profile is pooled from their longest lines, which smooths this out.
- **Sync**: English is often longer than the source, so long segments get
  compressed up to 1.5×; beyond that they run into the next gap, which is
  how commercial dubs behave too.
- **Licensing**: XTTS-v2's model weights are under Coqui's non-commercial
  CPML license — fine for personal use, check before anything commercial.
- **Originals are never modified.** Output is always a new file; `mv` it over
  the original yourself once you've checked the result.
- Works with `.mkv`, `.mp4`, `.mov`, `.webm`, etc. MKV is the most forgiving
  container for unusual subtitle tracks.
