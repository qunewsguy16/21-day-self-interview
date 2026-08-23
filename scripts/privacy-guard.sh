#!/usr/bin/env bash
# privacy-guard.sh — refuse to let private self-interview data enter git.
#
#   bash scripts/privacy-guard.sh            # scan all tracked files (CI)
#   bash scripts/privacy-guard.sh --staged   # scan the staged diff (pre-commit)
#
# Two checks:
#   1. Forbidden filenames: local state, journals, snapshots, answer dumps.
#   2. Forbidden content: the snapshot machine-state marker appearing in any
#      file other than the tools that legitimately define it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

MODE="${1:-tree}"
if [ "$MODE" = "--staged" ]; then
  FILES=$(git diff --cached --name-only --diff-filter=ACMR)
else
  FILES=$(git ls-files)
fi
[ -z "$FILES" ] && { echo "privacy-guard: nothing to check."; exit 0; }

FORBIDDEN_NAME='(^|/)(state\.json|journal\.json|journal\.backup\.[^/]*|snapshot\.txt)$|(^|/)\.self-interview(/|$)|si-([a-z]+-)?snapshot|(^|/)answers[^/]*$'
# Files allowed to mention the machine-state marker (they define/document it).
CONTENT_ALLOWLIST='^(si_snapshot\.py|scripts/privacy-guard\.sh)$'
MARKER='BEGIN SI STATE'

fail=0

bad_names=$(printf '%s\n' "$FILES" | grep -E "$FORBIDDEN_NAME" || true)
if [ -n "$bad_names" ]; then
  echo "privacy-guard: BLOCKED — private state files must never enter git:"
  printf '  %s\n' $bad_names
  fail=1
fi

while IFS= read -r f; do
  [ -f "$f" ] || continue
  printf '%s' "$f" | grep -qE "$CONTENT_ALLOWLIST" && continue
  if grep -qF "$MARKER" "$f" 2>/dev/null; then
    echo "privacy-guard: BLOCKED — '$f' contains snapshot machine-state content."
    fail=1
  fi
done <<< "$FILES"

if [ "$fail" -ne 0 ]; then
  echo "privacy-guard: commit refused. Private answers belong only in your own private storage."
  exit 1
fi
echo "privacy-guard: OK — no private data in ${MODE/--/}."
