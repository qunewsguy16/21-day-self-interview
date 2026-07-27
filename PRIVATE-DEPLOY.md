# Private deployment — Claude Code / Cowork

How to run the 21-day self-interview with Claude Code (web/remote sessions)
or Cowork, with a hard guarantee: **your answers never enter git, never
leave your own accounts, and survive ephemeral session containers.**

## The privacy model

| Data | Where it lives | Who can see it |
|---|---|---|
| Engine code + question banks | this public repo | everyone (that's fine — nothing personal) |
| Your answers (`journal.json`), progress (`state.json`) | `$SI_HOME` (default `~/.self-interview/`) — a per-session cache | the session only; wiped when a remote container is reclaimed |
| Canonical journal + progress | **your own Google Drive**, folder `Self-Interview (Private)`, one snapshot doc per night | only you (docs are created unshared; keep them that way) |
| The nightly conversation itself | your Claude session history | only your Claude account |

Nothing in this design ever writes answers to git, GitHub, or any public or
third-party surface. Three enforcement layers back that up:

1. `.gitignore` excludes all state/journal/snapshot files.
2. `scripts/privacy-guard.sh` blocks forbidden filenames *and* snapshot
   content — as a pre-commit hook (`git config core.hooksPath scripts/hooks`)
   and in CI (`.github/workflows/privacy-guard.yml`) on every push.
3. The agent-facing rules (`CLAUDE.md`, `.claude/skills/self-interview/SKILL.md`)
   forbid quoting answers in commits, PRs, issues, artifacts, or any external
   tool call.

## How persistence works (append-only snapshots)

Remote session containers are ephemeral, so local files can't be the store.
After each night's conversation the agent:

1. records your answers locally (`si.py record`),
2. packs the **complete** state into one text snapshot (`si_snapshot.py pack`)
   — a readable journal on top, a base64 machine-state block underneath
   (base64 survives Google-Doc rich-text conversion), and
3. creates a new Google Doc `si-snapshot day-NN YYYY-MM-DD` in
   `Self-Interview (Private)`, then reads it back to verify it parses.

At the start of any session, the *newest* snapshot is restored with
`si_snapshot.py unpack`, which merges by day (latest recording wins) — so a
stale cache or an out-of-order restore can't lose answers. Older snapshots
are your automatic backup history; delete them only by hand, only if you want to.

## Setup (once)

```bash
git config core.hooksPath scripts/hooks          # local pre-commit guard
TZ=America/New_York python3 si.py init --lang en # or --lang zh
TZ=America/New_York python3 si_snapshot.py pack  # then upload to Drive
```

Then schedule the nightly trigger. In Claude Code remote / Cowork, ask
Claude: *"Create a nightly routine at 10pm that runs my self-interview using
the self-interview skill."* The routine's prompt should be self-sufficient:
restore from Drive → `si.py prompt` → converse per `SKILL.md` → `record` →
`pack` → upload snapshot → verify.

**Timezone:** always run `si.py`/`si_snapshot.py` as
`TZ=<your zone> python3 ...` so the interview "day" rolls over at your
midnight, not UTC's. Routine crons are UTC — 22:00 US-Eastern is
`0 2 * * *` during daylight time and `0 3 * * *` after the clocks change.

## Recovery & housekeeping

- **New/blank container:** clone the repo, restore from the newest snapshot.
  Code is public; state is yours.
- **Corrupt snapshot:** `si_snapshot.py info --file <doc text>` to inspect;
  fall back to the next-newest doc.
- **Verify nothing leaked** (any time):
  `git log --all --name-only | grep -E 'journal|state|snapshot'` should show
  nothing, and `bash scripts/privacy-guard.sh` should pass on every branch.
- **Walk away completely:** delete the Drive folder, delete the nightly
  routine, `python3 si.py reset --yes`. The repo never held anything of yours.

## FAQ

**Why Google Drive and not a private repo?** The requirement was "not in git,
not outside my own accounts." Drive docs are private by default, readable as
a journal, searchable, and need no extra infrastructure. Any private store
the agent can read/write (Drive, a NAS, etc.) can play this role — the
snapshot format is just text.

**Can I read my journal without the tool?** Yes — open the newest snapshot
doc in Drive; the top half is your journal in plain language.

**Does the public repo benefit from this?** The mechanism is generic: any
Hermes/Claude agent user who wants remote sessions + private persistence can
use `si_snapshot.py` with their own storage.
