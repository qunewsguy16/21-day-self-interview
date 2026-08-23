# CLAUDE.md

## Privacy contract — read before anything else

This is a **public** repository. It contains the 21-day self-interview
*engine* (code + question banks) and nothing personal. The user's answers are
private and must never enter this repo or any outward-facing surface:

- Never commit, push, or stage `state.json`, `journal.json`,
  `.self-interview/`, `si-snapshot*`, `snapshot.txt`, `answers*`, or any file
  containing interview answers. They are gitignored on purpose.
- Never quote or paraphrase the user's answers in commit messages, PR or
  issue text, code comments, published artifacts, or any external service.
  The only durable home for answers is the user's own private Google Drive
  folder (`Self-Interview (Private)`).
- Run `bash scripts/privacy-guard.sh --staged` before every commit; CI runs
  the same guard on every push. Enable the local hook once per clone with:
  `git config core.hooksPath scripts/hooks`

## What's here

- `si.py` — stdlib-only state machine (init/prompt/status/record/recap/reset).
  State lives in `$SI_HOME` or `~/.self-interview/`, outside the repo.
- `si_snapshot.py` — packs local state into a private snapshot doc for the
  user's own Drive, and restores from it. See `PRIVATE-DEPLOY.md`.
- `questions.en.json` / `questions.zh.json` — the classic 21-night banks.
  `questions.healing.en.json` — the healing track (trauma-informed variant;
  conduct rules in `references/healing.md`). `si.py init --track healing`
  selects it.
- `SKILL.md` — the counselor character and conversation rules (source of
  truth for behavior). `.claude/skills/self-interview/SKILL.md` — the Claude
  Code / Cowork deployment of it (persistence + privacy mechanics).
- `PRIVATE-DEPLOY.md` — the private deployment architecture and runbook.

## Conventions

- Run `si.py` / `si_snapshot.py` with the user's timezone, e.g.
  `TZ=America/New_York python3 si.py prompt` — day rollover must follow the
  user's midnight, not UTC.
- Python: 3.8+, stdlib only. No new dependencies.
- Question-bank edits must keep each track's three-phase arc (classic:
  See → Understand → Choose; healing: Ground → Witness → Reclaim), stay at
  21 days × 3 questions, and remain parseable by `si.py`. Healing-track
  edits must also respect the conduct rules in `references/healing.md`
  (consent gates, gentle_alt, grounding closings).
