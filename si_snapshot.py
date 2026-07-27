#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
si_snapshot.py — private snapshot packer/unpacker for 21 Days of Self-Interview.

Purpose: let an agent persist the (private, gitignored) local state to the
user's OWN private storage (e.g. a Google Drive doc) and restore it later —
without the answers ever touching the git repository or any public surface.

A snapshot is a single text document with two parts:
  1. A human-readable journal (so the user can open and read it in Drive).
  2. A machine-state block: base64-encoded JSON between BEGIN/END markers.
     Base64 survives rich-text conversion (smart quotes, reflowed whitespace),
     so the snapshot can round-trip through a Google Doc safely.

Usage:
  python3 si_snapshot.py pack [--out FILE]     # local state -> snapshot text
  python3 si_snapshot.py unpack --file FILE    # snapshot text -> local state
  python3 si_snapshot.py info --file FILE      # inspect a snapshot (no writes)

State lives in $SI_HOME or ~/.self-interview/ (same as si.py).
Pure stdlib, no dependencies.
"""
import argparse, base64, binascii, datetime, json, os, pathlib, re, sys

FORMAT = 1
MARK_BEGIN = "-----BEGIN SI STATE (base64) v%d-----" % FORMAT
MARK_END = "-----END SI STATE-----"
B64_LINE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def home() -> pathlib.Path:
    env = os.environ.get("SI_HOME")
    base = pathlib.Path(env) if env else pathlib.Path.home() / ".self-interview"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load(path: pathlib.Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(msg: str):
    print(json.dumps({"ok": False, "msg": msg}, ensure_ascii=False))
    sys.exit(1)


def _title(state: dict, journal: dict) -> str:
    last = max((int(k) for k in journal.keys()), default=0)
    stamp = datetime.date.today().isoformat()
    return "si-snapshot day-%02d %s" % (last, stamp)


def cmd_pack(args):
    state = _load(home() / "state.json")
    journal = _load(home() / "journal.json") or {}
    if not state:
        _fail("No local state to pack. Run `si.py init` (or unpack a snapshot) first.")
    lines = []
    lines.append("21 Days of Self-Interview — private journal snapshot")
    lines.append("Started %s · language %s · %d night(s) recorded"
                 % (state.get("start_date"), state.get("lang"), len(journal)))
    lines.append("This document is private. Do not share it or commit it to any repository.")
    lines.append("")
    for k in sorted(journal, key=int):
        e = journal[k]
        lines.append("--- Day %s · %s (%s) ---" % (e.get("day"), e.get("theme"), e.get("date")))
        lines.append(e.get("answers", "").strip())
        lines.append("")
    lines.append("Machine state below — needed to restore progress. Do not edit.")
    payload = {
        "format": FORMAT,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "journal": journal,
    }
    raw = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    lines.append(MARK_BEGIN)
    lines.extend(raw[i:i + 76] for i in range(0, len(raw), 76))
    lines.append(MARK_END)
    text = "\n".join(lines) + "\n"
    out = pathlib.Path(args.out) if args.out else home() / "snapshot.txt"
    out.write_text(text, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "title": _title(state, journal),
        "out": str(out),
        "days_recorded": sorted(int(k) for k in journal.keys()),
    }, ensure_ascii=False))


def _decode(text: str) -> dict:
    begin = text.find("BEGIN SI STATE")
    end = text.find("END SI STATE")
    if begin < 0 or end < 0 or end <= begin:
        _fail("No machine-state block found in the snapshot text.")
    begin = text.find("\n", begin)
    blob = text[begin:end]
    b64 = "".join(ln.strip() for ln in blob.splitlines()
                  if ln.strip() and B64_LINE.match(ln) and "-" not in ln)
    try:
        payload = json.loads(base64.b64decode(b64, validate=False).decode("utf-8"))
    except (ValueError, binascii.Error) as e:
        _fail("Machine-state block is corrupt: %s" % e)
    if "state" not in payload or "journal" not in payload:
        _fail("Snapshot payload missing state/journal keys.")
    return payload


def _read_input(args) -> str:
    if args.file:
        return pathlib.Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def cmd_unpack(args):
    payload = _decode(_read_input(args))
    snap_state, snap_journal = payload["state"], payload["journal"]
    local_journal = _load(home() / "journal.json") or {}
    # Merge: union of days; on conflict, the entry recorded latest wins.
    merged = dict(snap_journal)
    for k, e in local_journal.items():
        if k not in merged or e.get("recorded_at", "") > merged[k].get("recorded_at", ""):
            merged[k] = e
    snap_state["completed_days"] = sorted(int(k) for k in merged.keys())
    (home() / "state.json").write_text(
        json.dumps(snap_state, ensure_ascii=False, indent=2), encoding="utf-8")
    (home() / "journal.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "msg": "State restored.",
        "start_date": snap_state.get("start_date"),
        "lang": snap_state.get("lang"),
        "days_recorded": snap_state["completed_days"],
        "saved_at": payload.get("saved_at"),
    }, ensure_ascii=False))


def cmd_info(args):
    payload = _decode(_read_input(args))
    st, j = payload["state"], payload["journal"]
    print(json.dumps({
        "ok": True,
        "start_date": st.get("start_date"),
        "lang": st.get("lang"),
        "days_recorded": sorted(int(k) for k in j.keys()),
        "saved_at": payload.get("saved_at"),
    }, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(prog="si_snapshot.py",
                                 description="Pack/unpack private snapshots of self-interview state")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="write snapshot text from local state")
    p.add_argument("--out", help="output file (default: $SI_HOME/snapshot.txt)")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("unpack", help="restore local state from snapshot text")
    p.add_argument("--file", help="snapshot text file (default: stdin)")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("info", help="inspect a snapshot without writing anything")
    p.add_argument("--file", help="snapshot text file (default: stdin)")
    p.set_defaults(func=cmd_info)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
