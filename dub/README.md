# Local English dubbing for foreign audio tracks

One script that takes a video with a foreign-language audio track, generates a
spoken English dub of it **entirely on your own machine**, and muxes that dub
back into a copy of the original file as an extra `eng` track. All original
video, audio, and subtitle tracks are copied through untouched — the output
just has one more audio track you can select in your player.

## How it works

The whole thing is three well-established local tools glued together:

| Step | Tool | What it does |
|---|---|---|
| Extract | ffmpeg | Pulls the foreign audio track out of the container |
| Translate | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Transcribes **and** translates to English in a single pass (`task="translate"`), with timestamps — no separate translation model needed |
| Speak | [Kokoro](https://github.com/hexgrad/kokoro) | Small (82M), fast, CPU-friendly local TTS reads each English segment |
| Assemble | script + ffmpeg | Each spoken clip is placed at its original timestamp; clips that run long are sped up slightly (pitch-preserving, capped at 1.5×) to stay in sync |
| Mix | ffmpeg | The original track is ducked under the English speech (sidechain compression) so music and sound effects survive under the dub |
| Mux | ffmpeg | Everything is stream-copied into `<name>.eng-dub.<ext>` with the dub appended as an AAC track tagged `language=eng`, titled "English (AI dub)" |

No cloud services, no API keys. Models download once from Hugging Face on
first run, then everything is offline.

## Install

```bash
# system deps
sudo apt install ffmpeg espeak-ng     # macOS: brew install ffmpeg espeak-ng

# python deps
pip install -r requirements.txt
```

## Use

```bash
# single file -> movie.eng-dub.mkv next to the original
python dub.py movie.mkv

# batch: scan a folder, dub every video that has no English track yet
python dub.py /media/foreign-films/

# options
python dub.py movie.mkv --model medium     # better translation (default: small)
python dub.py movie.mkv --voice am_adam    # different Kokoro voice
python dub.py movie.mkv --track 2          # dub a specific stream index
python dub.py movie.mkv --plain            # voice only, no music bed under it
python dub.py movie.mkv --force            # dub even if an eng track exists
```

By default the script picks the first audio track not tagged `eng`, and skips
files that already have an English track (so it's safe to point at a whole
library).

## Notes and knobs

- **Quality vs speed**: `--model small` is a good default. `medium` or
  `large-v3` translate noticeably better on fast machines or GPUs
  (faster-whisper uses CUDA automatically if available).
- **Sync**: dubs are aligned to Whisper's segment timestamps. English is often
  longer than the source language, so long segments get compressed up to 1.5×;
  beyond that they simply run into the next gap, which is how commercial dubs
  behave too.
- **Voices**: Kokoro ships many voices (`af_heart`, `af_bella`, `am_adam`,
  `bm_george`, ...). One voice reads everything — this is a "lector-style"
  dub, not per-character voice casting.
- **Originals are never modified.** Output is always a new file. If you want
  to replace the original afterwards, just `mv` it over once you've checked
  the result.
- Works with `.mkv`, `.mp4`, `.mov`, `.webm`, etc. MKV is the most forgiving
  container if your source has unusual subtitle tracks.
