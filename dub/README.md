# Local English dubbing for foreign audio tracks

One script that takes a video with a foreign-language audio track (Japanese,
French, anything Whisper knows), generates a spoken English dub **entirely on
your own machine**, and muxes that dub back into a copy of the original file
as an extra `eng` track. All original video, audio, and subtitle tracks are
copied through untouched — the output just has one more audio track you can
select in your player.

No cloud services, no API keys. Models download once from Hugging Face on
first run, then everything is offline.

## Two modes

### Narrator mode (default) — fast, simple

One stock voice reads the English translation over the original track, which
is ducked (sidechain compression) under the speech so music and effects
survive. Like a classic lector dub. Runs fine on CPU.

### `--clone` mode — keeps the original voices

The goal here is retaining the original speakers' voice identity and tone:

| Step | Tool | What it does |
|---|---|---|
| Demix | [Demucs](https://github.com/facebookresearch/demucs) (htdemucs, two-stem) | Splits the track into **vocals** and **music/effects**. The clean background stem goes straight into the final mix; the clean vocal stem feeds the next two steps. |
| Translate | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Transcribes **and** translates to English in a single pass (`task="translate"`) with timestamps — no separate translation model or LLM needed |
| Clone + speak | [XTTS-v2](https://github.com/idiap/coqui-ai-TTS) | Zero-shot voice cloning: **each segment's own original audio is the voice reference for its English line**, so whoever is speaking at that moment is (approximately) the voice that speaks the translation — per-speaker voice and much of the emotional tone carry over with no diarization step |
| Assemble | script + ffmpeg | Clips placed at original timestamps; long ones sped up (pitch-preserving, ≤1.5×) to stay in sync |
| Mix + mux | ffmpeg | Cloned English vocals over the untouched background stem, muxed in as an AAC track tagged `language=eng`, titled "English (AI dub)" |

## VRAM: fits in 8 GB

The pipeline never holds two models at once. Demucs runs as a subprocess and
releases everything when it exits; Whisper is deleted and the CUDA cache
flushed before XTTS loads. Peak usage is one model at a time — Demucs ~3 GB,
Whisper `small`/`medium` ~1–3 GB, XTTS-v2 ~2.5 GB — comfortable on an 8 GB
card like an RTX 4070 Laptop. CPU fallback works everywhere, just slower.

## Install

```bash
# system deps
#   Windows:  winget install ffmpeg    (espeak-ng only needed for narrator mode:
#             installer from https://github.com/espeak-ng/espeak-ng/releases)
#   Linux:    sudo apt install ffmpeg espeak-ng
#   macOS:    brew install ffmpeg espeak-ng

# GPU torch first (CUDA 12.x):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt          # base: narrator mode
pip install -r requirements-clone.txt    # extra: --clone mode
```

## Use

```bash
# fast narrator dub -> movie.eng-dub.mkv next to the original
python dub.py movie.mkv

# voice-preserving dub (e.g. Japanese source)
python dub.py movie.mkv --clone --lang ja --model medium

# batch: scan a folder, dub every video that has no English track yet
python dub.py /media/foreign-films/ --clone

# other options
python dub.py movie.mkv --voice am_adam    # narrator voice
python dub.py movie.mkv --track 2          # dub a specific stream index
python dub.py movie.mkv --plain            # narrator only, no music bed
python dub.py movie.mkv --force            # dub even if an eng track exists
```

By default the script picks the first audio track not tagged `eng`, and skips
files that already have an English track, so it's safe to point at a whole
library.

## Notes and knobs

- **Translation quality**: `--model small` is a fine default; `medium` or
  `large-v3` are noticeably better for Japanese and worth it on GPU. Pass
  `--lang ja` to skip autodetection on known-language libraries.
- **Sync**: English is often longer than the source, so long segments get
  compressed up to 1.5×; beyond that they run into the next gap, which is
  how commercial dubs behave too.
- **Cloning quality** depends on the reference audio: clean, close-mic'd
  dialogue clones well; shouting over explosions less so. Segments shorter
  than ~3 s automatically borrow surrounding vocal audio for the reference.
- **Licensing**: XTTS-v2's model weights are under Coqui's non-commercial
  CPML license — fine for personal use, check before anything commercial.
- **Originals are never modified.** Output is always a new file; `mv` it over
  the original yourself once you've checked the result.
- Works with `.mkv`, `.mp4`, `.mov`, `.webm`, etc. MKV is the most forgiving
  container for unusual subtitle tracks.
