#!/usr/bin/env bash
# migrate-local.sh — stand up the 21-day self-interview on a local machine.
# Idempotent. Does not touch the network. Verifies before it claims success.
set -euo pipefail

: "${SI_HOME:?Set SI_HOME to a folder your cloud client syncs, e.g.
  export SI_HOME=\"\$HOME/Library/CloudStorage/GoogleDrive-you@example.com/My Drive/Self-Interview (Private)/state\"}"
: "${TZ:=America/New_York}"; export TZ SI_HOME

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1. State directory"
mkdir -p "$SI_HOME"
case "$SI_HOME" in
  *Drive*|*Dropbox*|*CloudStorage*|*"Mobile Documents"*|*OneDrive*|*iCloud*)
    echo "   ok  $SI_HOME (inside a synced folder — the OS moves the bytes, not a model)" ;;
  *)
    echo "   WARN $SI_HOME is not obviously inside a synced folder."
    echo "        Local files alone are one disk failure from gone." ;;
esac

say "2. Restore from snapshot text, if any was supplied"
if [ "$#" -gt 0 ]; then
  args=(); for f in "$@"; do args+=(--file "$f"); done
  python3 si_snapshot.py unpack "${args[@]}"
else
  echo "   skipped (no snapshot files given)"
  echo "   usage: SI_HOME=... bash migrate-local.sh day10.txt day11.txt day12.txt"
fi

say "3. Verify — this is the only thing that counts as 'restored'"
if [ "$#" -gt 0 ]; then
  args=(); for f in "$@"; do args+=(--file "$f"); done
  if python3 si_snapshot.py verify "${args[@]}"; then
    echo "   ok  every local night is present in the snapshots"
  else
    echo "   STOP: verification failed. Do not start a new night until this is clean." >&2
    exit 1
  fi
else
  echo "   skipped (nothing restored to verify)"
fi

say "4. Local safety net (no remote)"
if [ -d .git ]; then
  git config core.hooksPath scripts/hooks && echo "   ok  pre-commit privacy guard enabled"
  if git remote | grep -q .; then
    echo "   WARN a git remote is configured: $(git remote -v | head -1)"
    echo "        This project does not need one. Answers must never leave the machine."
  else
    echo "   ok  no git remote configured"
  fi
  if [ -d .github/workflows ] && [ "${SI_DROP_CI:-0}" = "1" ]; then
    rm -rf .github/workflows && echo "   ok  removed CI workflows (set SI_DROP_CI=1 to opt in)"
  elif [ -d .github/workflows ]; then
    echo "   note .github/workflows still present; re-run with SI_DROP_CI=1 to remove it"
  fi
fi
bash scripts/privacy-guard.sh || true

say "5. Where things stand"
python3 si.py status
