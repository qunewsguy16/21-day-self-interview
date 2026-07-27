---
name: self-interview
description: Run the nightly 21-day self-interview in Claude Code / Cowork with private persistence. Use when a nightly routine fires for the self-interview, when the user says "start my self-interview" / "tonight's questions" / asks about interview progress, or when restoring or saving self-interview state. The user's answers are private — they persist ONLY to the user's own storage (Google Drive snapshot doc), never to git.
---

# Self-Interview — Claude Code / Cowork deployment

This adapts the repo's Hermes skill (root `SKILL.md`) to Claude Code and
Cowork sessions. **Read the root `SKILL.md` first** — it defines the
counselor character, the six principles, the nightly conversation flow, and
the safety boundaries (`references/safety.md`). This file adds only what is
different here: **private persistence and session mechanics.**

## Privacy contract (absolute — overrides convenience, always)

This repository is a PUBLIC git repo. The user's answers must never reach it,
or any other outward-facing surface.

1. **Never** `git add`, commit, or push `state.json`, `journal.json`,
   `.self-interview/`, snapshot files, or any text containing the user's
   answers. They are gitignored; do not fight the gitignore.
2. **Never** quote or paraphrase the user's answers in: commit messages, PR
   titles/bodies/comments, GitHub issues, published artifacts, web requests,
   or any tool call that leaves the user's own accounts.
3. The **only** durable store for answers is the user's own private Google
   Drive folder (below). Local `$SI_HOME` (default `~/.self-interview/`) is a
   per-session cache — remote session containers are ephemeral.
4. Before any commit in this repo, run `bash scripts/privacy-guard.sh --staged`.
5. If the user asks to share/export their journal, that is their call — but
   confirm the destination out loud before sending anything anywhere.

## Where state lives

- **Canonical:** Google Drive folder **`Self-Interview (Private)`**, one
  snapshot Google Doc per night, named `si-snapshot day-NN YYYY-MM-DD`.
  Append-only: the newest doc always contains the complete state (readable
  journal on top, machine-state block underneath). Older snapshots are
  automatic history; never delete them on your own.
- **Cache:** `$SI_HOME` (default `~/.self-interview/`) — `state.json`,
  `journal.json`. Rebuilt from Drive at the start of each session.

## Timezone rule

Run every `si.py` / `si_snapshot.py` command with the user's timezone so the
"day" rolls over at the user's midnight, not UTC's:

```bash
TZ=America/New_York python3 si.py prompt
```

## Nightly flow

1. **Restore.** Drive-search `title contains 'si-snapshot'` (scope to the
   folder via `parentId` when known; newest `modifiedTime` wins). Read the
   doc, save its text to a temp file, then:
   `TZ=America/New_York python3 si_snapshot.py unpack --file <tmp>`.
   Unpack merges by day and keeps the latest recording on conflict, so
   restoring over an existing cache is safe. No snapshot found AND no local
   state → ask the user whether to `si.py init` (which language, start date).
2. **Prompt.** `TZ=America/New_York python3 si.py prompt` — never invent day
   numbers or questions. On reflection days (7/14/21) run `si.py recap` first
   and open by reflecting the user's own words (root SKILL.md, Principle 3).
3. **Converse** as the root SKILL.md prescribes: one question at a time,
   gentle follow-ups, the user's language, no diagnosis, no advice.
4. **Record.** Write the user's substantive answers with
   `TZ=America/New_York python3 si.py record --day N --file <tmpfile>`
   (their words, lightly organized — not your interpretation). Prefer
   `--file` over `--text` to avoid shell-quoting damage.
5. **Snapshot.** `TZ=America/New_York python3 si_snapshot.py pack` → returns
   a suggested `title` and the snapshot file path. Create a Google Doc in
   `Self-Interview (Private)` with that title and the file's text (allow the
   default conversion to a Google Doc so it stays searchable and readable).
   Create the folder first if it doesn't exist.
6. **Verify.** Read the new doc back and confirm `si_snapshot.py info`
   parses it (round-trip check). Only then tell the user the night is saved —
   show them the `si.py status` progress bar.

## If things look wrong

- Local state missing or behind Drive → restore (step 1); unpack merges safely.
- Snapshot doc unparseable → try the next-newest snapshot; report what happened.
- Repo missing in a fresh container → clone the public repo again; state
  comes from Drive, the repo carries only code and questions.
- Real distress in conversation → drop everything else and follow
  `references/safety.md`.
