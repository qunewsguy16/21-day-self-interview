---
name: self-interview
description: Run the nightly 21-day self-interview in Claude Code / Cowork with private persistence. Use when a nightly routine fires for the self-interview, when the user says "start my self-interview" / "tonight's questions" / asks about interview progress, or when restoring or saving self-interview state. Supports the classic track and the healing track (references/healing.md). The user's answers are private — they persist ONLY to the user's own storage (Google Drive snapshot doc), never to git.
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

- **Canonical:** Google Drive folder **`Self-Interview (Private)`** (or a
  per-run subfolder the user designates), one snapshot Google Doc per night.
  Titles come from `si_snapshot.py pack` and are track-specific —
  `si-snapshot day-NN YYYY-MM-DD` for the classic track,
  `si-<track>-snapshot night-NN YYYY-MM-DD` for others (e.g.
  `si-healing-snapshot night-03 ...`) — so two runs never mix on restore.
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

1. **Restore.** Drive-search by the run's title prefix — `si-snapshot` for a
   classic run, `si-<track>-snapshot` for others — scoped to the folder via
   `parentId` when known; newest `modifiedTime` wins. Read the doc, save its
   text to a temp file, then:
   `TZ=America/New_York python3 si_snapshot.py unpack --file <tmp>`.
   (Per-night prose docs restore together: repeat `--file` for each.)
   Unpack merges by day and keeps the latest recording on conflict, so
   restoring over an existing cache is safe. No snapshot found AND no local
   state → ask the user whether to `si.py init` (which language, track,
   start date) — unless the routine's own prompt already specifies the init.
2. **Prompt.** `TZ=America/New_York python3 si.py prompt` — never invent day
   numbers or questions. On reflection days (7/14/21) run `si.py recap` first
   and open by reflecting the user's own words (root SKILL.md, Principle 3).
3. **Converse** as the root SKILL.md prescribes: one question at a time,
   gentle follow-ups, the user's language, no diagnosis, no advice.
4. **Record.** Write the user's substantive answers with
   `TZ=America/New_York python3 si.py record --day N --file <tmpfile>`
   (their words, lightly organized — not your interpretation). Prefer
   `--file` over `--text` to avoid shell-quoting damage.
5. **Snapshot.** `TZ=America/New_York python3 si_snapshot.py pack --readable`
   → prose only, no base64. Create a Google Doc in `Self-Interview (Private)`
   with the returned `title` and that text. Create the folder if needed.

   **Never hand-copy a base64 machine-state block into a tool call.** You
   cannot reproduce high-entropy text reliably; a single wrong character
   destroys the entire payload, and the failure looks like success. The
   readable format exists precisely so that a slip costs one character
   instead of the whole journal. If you catch yourself typing base64, stop.

   Nightly docs may carry only that night's entry (`unpack` merges readable
   files by day, so pass every night's doc when restoring). On recap nights
   (7/14/21) also write one consolidated `pack --readable` doc containing all
   nights, so a single document can always restore everything.
6. **Verify — mechanically, never by eye.** Read the new doc back, save the
   text, and run:
   `TZ=America/New_York python3 si_snapshot.py verify --file <readback>`
   (repeat `--file` for every doc needed to make the journal whole). It exits
   non-zero and names the missing or differing days. **Only an `ok: true`
   from `verify` means the night is saved.** Do not tell the user it saved
   because the upload call returned success — it returns success for
   truncated and even fabricated content. If verify fails, say so plainly,
   say the night is not yet backed up, and fix it before moving on.
   Then show the `si.py status` progress bar.

## Healing track — additional rules

When `si.py prompt` reports `"track": "healing"`, the run follows
`references/healing.md` in full. The short version, mechanically:

- **Read `references/healing.md` before conversing.** Its conduct rules
  (capacity check, titration, no excavation, no guilt levers) override any
  general instinct to dig deeper.
- The prompt JSON may carry `consent_gate`, `gentle_alt`, and `closing`.
  Deliver the consent gate *before* the theme; the gentle_alt **counts as the
  full night**; always end on the closing's grounding, in the present.
- Pacing is `nights`: the day number is the next unrecorded night, so a
  skipped evening creates no debt. `already_answered_today` means a night was
  already recorded *this evening* — check in warmly and stop; never push a
  second night in one sitting, and never run a consent-gated night as a
  same-evening second night even if asked (offer it for tomorrow).
- Reflection nights are 7, 14, 21, as ever: `recap` first, reflect the
  user's own words back, and write a consolidated `pack --readable` doc.
- Real distress → `references/safety.md`, immediately and without weighing it.

## If things look wrong

- Local state missing or behind Drive → restore (step 1); unpack merges safely.
- Snapshot doc unparseable → try the next-newest snapshot; report what happened.
- Repo missing in a fresh container → clone the public repo again; state
  comes from Drive, the repo carries only code and questions.
- Real distress in conversation → drop everything else and follow
  `references/safety.md`.
