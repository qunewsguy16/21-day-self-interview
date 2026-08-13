#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
si_snapshot.py — private snapshot packer/unpacker for 21 Days of Self-Interview.

Purpose: let an agent persist the (private, gitignored) local state to the
user's OWN private storage (e.g. a Google Drive doc) and restore it later —
without the answers ever touching the git repository or any public surface.

A snapshot is a single text document with two parts:
  1. A human-readable journal (so the user can open and read it in Drive).
  2. A machine-state block: gzipped, base64-encoded JSON between BEGIN/END
     markers. Base64 survives rich-text conversion (smart quotes, reflowed
     whitespace, and the markdown escaping a Doc adds to line-leading
     characters), so the snapshot can round-trip through a Google Doc safely;
     gzip keeps the block small as the journal grows across 21 nights.

Format versions: v2 blocks are gzipped, v1 blocks are plain JSON. Unpacking
accepts either, so snapshots written by earlier versions still restore.

Usage:
  python3 si_snapshot.py pack [--out FILE]     # local state -> snapshot text
  python3 si_snapshot.py unpack --file FILE    # snapshot text -> local state
  python3 si_snapshot.py info --file FILE      # inspect a snapshot (no writes)

State lives in $SI_HOME or ~/.self-interview/ (same as si.py).
Pure stdlib, no dependencies.
"""
import argparse, base64, binascii, datetime, gzip, json, os, pathlib, re, sys, zlib

FORMAT = 2
SI_VERSION = "1.0.0"                     # must track si.py's VERSION
MARK_BEGIN = "-----BEGIN SI STATE (base64+gzip) v%d-----" % FORMAT
MARK_END = "-----END SI STATE-----"
PART_BEGIN = "-----BEGIN SI STATE PART %d/%d (base64+gzip) v%d-----"
PART_END = "-----END SI STATE PART %d/%d-----"
PART_RE = re.compile(r"BEGIN SI STATE PART (\d+)/(\d+)")
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
    payload = {
        "format": FORMAT,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "journal": journal,
    }
    out = pathlib.Path(args.out) if args.out else home() / "snapshot.txt"
    if args.readable:
        # Prose-only snapshot: no machine-state block at all. `unpack` restores
        # from the day headers and answer text directly. Nothing here is
        # all-or-nothing — a mangled character costs one character, not the
        # whole journal — which is what makes this the safe format to move by
        # hand, through a rich-text editor, or via an agent's tool call.
        lines.append("No machine-state block: this snapshot restores from the text above.")
        lines.append("Restore with: si_snapshot.py unpack --file <this file>")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "title": _title(state, journal),
            "out": str(out),
            "format": "readable",
            "days_recorded": sorted(int(k) for k in journal.keys()),
        }, ensure_ascii=False))
        return
    lines.append("Machine state below — needed to restore progress. Do not edit.")
    blob = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 9)
    raw = base64.b64encode(blob).decode("ascii")
    b64_lines = [raw[i:i + 76] for i in range(0, len(raw), 76)]
    n = max(1, int(args.parts or 1))
    if n == 1:
        lines.append(MARK_BEGIN)
        lines.extend(b64_lines)
        lines.append(MARK_END)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written = [str(out)]
    else:
        # Split the machine state across N files. Parts carry state ONLY — no
        # readable journal — so every part stays small. That matters when the
        # parts are transferred by hand or by an agent: a slip in prose is
        # harmless, a slip inside base64 destroys the whole payload, so the
        # fragile content is kept small, uniform, and separately checkable.
        # Use `pack` without --parts for the single readable+state document.
        per = -(-len(b64_lines) // n)
        written = []
        for i in range(n):
            chunk = b64_lines[i * per:(i + 1) * per]
            head = [
                "21 Days of Self-Interview — machine state part %d of %d" % (i + 1, n),
                "%d night(s) recorded · saved %s" % (len(journal), payload["saved_at"]),
                "This document is private. Do not share it or commit it to any repository.",
                "Restore needs every part:",
                "  si_snapshot.py unpack" + "".join(" --file part%d" % (k + 1) for k in range(n)),
                "",
            ]
            body = head + [PART_BEGIN % (i + 1, n, FORMAT)] + chunk + [PART_END % (i + 1, n)]
            p = out.with_name("%s.part%dof%d%s" % (out.stem, i + 1, n, out.suffix))
            p.write_text("\n".join(body) + "\n", encoding="utf-8")
            written.append(str(p))
    print(json.dumps({
        "ok": True,
        "title": _title(state, journal),
        "out": written if len(written) > 1 else written[0],
        "parts": n,
        "b64_lines": len(b64_lines),
        "days_recorded": sorted(int(k) for k in journal.keys()),
    }, ensure_ascii=False))


def _normalize(line: str) -> str:
    """Strip a line and undo markdown escaping added by rich-text renderers.

    Google Docs (read back as markdown) escapes line-leading markdown
    characters — a base64 line starting with '+' comes back as '\\+...' — and an
    escaped line would otherwise fail the base64 match and be dropped silently,
    corrupting the payload. Backslash is not in the base64 alphabet, so removing
    it is always safe.
    """
    return line.strip().replace("\\", "")


HEADER_RE = re.compile(r"Started\s+(\d{4}-\d{2}-\d{2})\s*[·.]\s*language\s+(\w+)")
# Every ASCII punctuation mark is escapable in markdown, and renderers escape
# whichever ones they please: Google Docs leaves '=' alone mid-line but writes
# '\=' when a line starts with it, which used to survive decoding as a stray
# backslash and fail `verify` by one character. Match the full CommonMark set
# so no future line-leading punctuation can reopen this.
MD_ESCAPE = re.compile(r"""\\([!"\#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""")
DAY_RE = re.compile(r"^\\?-{2,}\s*Day\s+(\d+)\s*[·.]\s*(.+?)\s*\((\d{4}-\d{2}-\d{2})\)\s*-{2,}\s*$")


def _decode_readable(text: str) -> dict:
    """Rebuild state+journal from the human-readable half of a snapshot.

    Used when a snapshot carries no machine-state block. Every field needed to
    restore is already present in the prose, so a snapshot can survive being
    retyped or round-tripped through a rich-text editor: damage stays local to
    the characters that were damaged instead of invalidating the whole payload.
    """
    m = HEADER_RE.search(text)
    if not m:
        _fail("No machine-state block and no readable 'Started ... language ...' header.")
    start_date, lang = m.group(1), m.group(2)
    journal, day, buf = {}, None, []

    def flush():
        if day is None:
            return
        body = "\n".join(buf)
        body = MD_ESCAPE.sub(r"\1", body)          # \[ \< \_ … from markdown rendering
        body = re.sub(r"[ \t ]+$", "", body, flags=re.M)
        body = re.sub(r"\n{3,}", "\n\n", body)     # Docs doubles every newline
        journal[str(day["day"])] = dict(day, answers=body.strip())

    for raw in text.splitlines():
        line = raw.rstrip()
        d = DAY_RE.match(line.strip())
        if d:
            flush()
            day = {"day": int(d.group(1)), "theme": d.group(2), "date": d.group(3),
                   "recorded_at": d.group(3) + "T00:00:00"}
            buf = []
        elif day is not None:
            if line.strip().startswith("No machine-state block") or \
               line.strip().startswith("Restore with:"):
                continue
            buf.append(line)
    flush()
    if not journal:
        _fail("Readable snapshot contained no '--- Day N · Theme (date) ---' entries.")
    return {
        "format": "readable",
        "saved_at": max(e["date"] for e in journal.values()) + "T00:00:00",
        # Carry every key si.py expects. A prose restore is a real restore, not
        # a degraded one — state rebuilt this way must behave identically, or
        # the fallback path only fails once you are already relying on it.
        "state": {"version": SI_VERSION, "lang": lang, "start_date": start_date,
                  "created_at": start_date + "T00:00:00",
                  "completed_days": sorted(int(k) for k in journal)},
        "journal": journal,
    }


def _merge_payloads(payloads) -> dict:
    """Union the journals of several payloads; newest recording of a day wins."""
    journal = {}
    for p in payloads:
        for k, e in p["journal"].items():
            cur = journal.get(k)
            if cur is None or (e.get("recorded_at") or e.get("date", "")) > \
                              (cur.get("recorded_at") or cur.get("date", "")):
                journal[k] = e
    state = dict(payloads[0]["state"])
    state["completed_days"] = sorted(int(k) for k in journal)
    return {"format": payloads[0].get("format", FORMAT), "state": state,
            "journal": journal,
            "saved_at": max(p.get("saved_at", "") for p in payloads)}


def _block(text: str):
    """Return (part_index, part_total, base64) for one snapshot text."""
    begin = text.find("BEGIN SI STATE")
    end = text.find("END SI STATE")
    if begin < 0 or end < 0 or end <= begin:
        _fail("No machine-state block found in the snapshot text.")
    m = PART_RE.search(text, begin)
    idx, total = (int(m.group(1)), int(m.group(2))) if m else (1, 1)
    body = text[text.find("\n", begin):end]
    b64 = "".join(ln for ln in map(_normalize, body.splitlines())
                  if ln and B64_LINE.match(ln) and "-" not in ln)
    return idx, total, b64


def _decode(texts) -> dict:
    if isinstance(texts, str):
        texts = [texts]
    # A folder of snapshots can hold both kinds at once — older base64 docs and
    # newer prose ones — so decode each kind on its own terms and merge by day.
    prose = [t for t in texts if "BEGIN SI STATE" not in t]
    texts = [t for t in texts if "BEGIN SI STATE" in t]
    payloads = [_decode_readable(t) for t in prose]
    if not texts:
        if not payloads:
            _fail("No snapshot text supplied.")
        return _merge_payloads(payloads)
    blocks = [_block(t) for t in texts]
    total = blocks[0][1]
    if any(b[1] != total for b in blocks):
        _fail("Snapshot parts disagree on how many parts there are.")
    if total == 1:
        # Each is a complete snapshot in its own right; decode and merge them.
        b64s = [b[2] for b in blocks]
    else:
        seen = {}
        for idx, _, chunk in blocks:
            if idx in seen:
                _fail("Snapshot part %d was supplied more than once." % idx)
            seen[idx] = chunk
        missing = [i for i in range(1, total + 1) if i not in seen]
        if missing:
            _fail("Missing snapshot part(s) %s of %d — restore needs all of them."
                  % (", ".join(map(str, missing)), total))
        b64s = ["".join(seen[i] for i in range(1, total + 1))]
    for b64 in b64s:
        try:
            blob = base64.b64decode(b64, validate=False)
            if blob[:2] == b"\x1f\x8b":      # gzip magic (v2); v1 blocks are plain JSON
                blob = gzip.decompress(blob)
            payload = json.loads(blob.decode("utf-8"))
        except (ValueError, OSError, binascii.Error, zlib.error) as e:
            _fail("Machine-state block is corrupt: %s" % e)
        if "state" not in payload or "journal" not in payload:
            _fail("Snapshot payload missing state/journal keys.")
        payloads.append(payload)
    return payloads[0] if len(payloads) == 1 else _merge_payloads(payloads)


def _read_input(args):
    if args.file:
        return [pathlib.Path(f).read_text(encoding="utf-8") for f in args.file]
    return [sys.stdin.read()]


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


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def cmd_verify(args):
    """Compare a snapshot (usually just read back out of storage) to local state.

    The point is to make "did the save actually work?" a mechanical check with
    an exit code, not a judgement call. Whoever wrote the snapshot — a human
    copying text, an agent emitting it into a tool call — cannot be trusted to
    confirm their own transfer, because the failure mode is producing something
    that *looks* right. So diff it against the source and let the machine say.
    """
    payload = _decode(_read_input(args))
    remote = payload["journal"]
    local = _load(home() / "journal.json") or {}
    if not local:
        _fail("No local journal to verify against.")
    missing, differs, ok = [], [], []
    for k in sorted(local, key=int):
        if k not in remote:
            missing.append(int(k))
        elif _squash(local[k].get("answers")) != _squash(remote[k].get("answers")):
            a, b = _squash(local[k].get("answers")), _squash(remote[k].get("answers"))
            differs.append({"day": int(k), "local_chars": len(a), "snapshot_chars": len(b)})
        else:
            ok.append(int(k))
    extra = sorted(int(k) for k in remote if k not in local)
    good = not missing and not differs
    print(json.dumps({
        "ok": good,
        "msg": "Snapshot matches local state." if good
               else "SNAPSHOT DOES NOT MATCH LOCAL STATE — do not rely on it.",
        "verified_days": ok,
        "missing_days": missing,
        "differing_days": differs,
        "extra_days_in_snapshot": extra,
    }, ensure_ascii=False))
    if not good:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(prog="si_snapshot.py",
                                 description="Pack/unpack private snapshots of self-interview state")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="write snapshot text from local state")
    p.add_argument("--out", help="output file (default: $SI_HOME/snapshot.txt)")
    p.add_argument("--parts", type=int, default=1,
                   help="split the machine state across N files (default: 1)")
    p.add_argument("--readable", action="store_true",
                   help="prose only, no base64 block; unpack restores from the text")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("unpack", help="restore local state from snapshot text")
    p.add_argument("--file", action="append",
                   help="snapshot text file; repeat once per part (default: stdin)")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("info", help="inspect a snapshot without writing anything")
    p.add_argument("--file", action="append",
                   help="snapshot text file; repeat once per part (default: stdin)")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("verify", help="check a saved snapshot against local state (exit 1 on loss)")
    p.add_argument("--file", action="append",
                   help="snapshot text file; repeat once per part (default: stdin)")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
