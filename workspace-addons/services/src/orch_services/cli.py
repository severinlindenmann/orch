"""orch services list|add|start|stop|restart|auto|remove|log|act|view (contract: contracts/addons/services/README.md)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import drivers, store
from .store import Refused

MASK = "••••••"
ACT_VERBS = ("start", "stop", "restart", "auto-on", "auto-off", "remove")


def _root(start: str) -> Path:
    p = Path(start).absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _workspace_id(root: Path) -> str:
    """The core's random id of this workspace (.orch/.local-id); names the platform entries."""
    try:
        from orch import addons
    except ImportError:
        raise Refused("Could not read this workspace's id. Update orch and try again.") from None
    wid = addons.read_local_id(root)
    if not wid or not re.fullmatch(r"[A-Za-z0-9]{8,64}", wid):
        raise Refused("This workspace has no id yet. Turn the add-on on again: orch addon add services")
    return wid.lower()


def _ticket_key(root: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    tid = ref.strip()
    try:
        from orch import tickets

        tid = tickets.resolve(root, tid)
    except Exception as e:  # noqa: BLE001 - Refused from the core already says what to do
        if e.__class__.__name__ == "Refused":
            raise Refused(str(e)) from None
    f = root / ".orch" / "tickets" / f"{tid}.json"
    if not isinstance(tid, str) or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid) or not f.is_file():
        raise Refused(f"Ticket {ref} doesn't exist. Run `orch ticket list` to see your tickets.")
    try:
        key = json.loads(f.read_text(encoding="utf-8")).get("key")
    except (OSError, ValueError):
        key = None
    return key if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key) else tid


def _program(root: Path, rec: dict, strict: bool = True) -> str:
    """Full path of the command's program: launchd and systemd do not search the person's PATH.
    Not strict (state, stop, remove): a program that is gone since must not keep a service from being removed."""
    prog = rec["command"][0]
    cwd = root / rec.get("cwd", ".")
    if os.sep in prog or "/" in prog:
        p = Path(prog) if Path(prog).is_absolute() else (cwd / prog)
        found = str(p.resolve()) if p.is_file() and os.access(p, os.X_OK) else None
    else:
        found = shutil.which(prog)
    if not found and not strict:
        return prog
    if not found:
        raise Refused(f"Could not find the program {prog}. Give its full path after --, then try again.")
    return found


def _spec(root: Path, rec: dict, wid: str | None = None, strict: bool = True) -> drivers.Spec:
    cwd = (root / rec.get("cwd", ".")).resolve()
    log = store.log_path(root, rec["id"]).absolute()
    argv = [_program(root, rec, strict), *rec["command"][1:]]
    for s in (str(cwd), str(log), *argv):
        if "\n" in s or "\r" in s or "\x00" in s:
            raise Refused("A path or word of this service has a line break in it. Fix it and try again.")
    env = {"PATH": os.environ.get("PATH") or "/usr/bin:/bin"}
    return drivers.Spec(
        sid=rec["id"],
        name=rec["name"],
        workspace_id=wid or _workspace_id(root),
        argv=argv,
        cwd=cwd,
        log=log,
        auto=bool(rec.get("auto")),
        env=env,
    )


def _driver() -> drivers.Driver:
    d = drivers.get()
    d.check()
    return d


def _row(root: Path, rec: dict, st: drivers.Status | None) -> dict:
    running = bool(st and st.running)
    since = (st.since if st else None) or store.last_change(root, rec["id"]) or rec.get("created_at")
    row = {
        "id": rec["id"],
        "name": rec["name"],
        "state": "running" if running else "stopped",
        "since": since,
        "auto": bool(rec.get("auto")),
        "made_by": rec.get("made_by"),
        "port": rec.get("port"),
        "command": rec["command"],
        "cwd": rec.get("cwd", "."),
    }
    if running and st and st.pid:
        row["pid"] = st.pid
    return row


def _rows(root: Path) -> tuple[list[dict], int, str | None]:
    recs, bad = store.load_all(root)
    note = None
    try:
        drv = _driver()
        wid = _workspace_id(root)
    except Refused as e:
        drv, wid, note = None, None, str(e)
    rows = []
    for r in recs:
        st = None
        if drv and wid:
            try:
                st = drv.status(_spec(root, r, wid, strict=False))
            except Refused:
                st = None
        rows.append(_row(root, r, st))
    return rows, bad, note


# ---------------------------------------------------------------- log lines


def _mask_line(line: str, root: Path) -> str:
    """The line with the secret value replaced by ••••••; the whole line when the value cannot be told apart."""
    from orch import secretscan

    out = line
    for _kind, rx in secretscan.PATTERNS:
        out = rx.sub(MASK, out)
    # key=value, key: value, --flag value: keep the name, hide what follows it
    out = re.sub(r"(?i)([\w.-]*(?:[=:]\s*|\s+--?[\w-]+\s+))(\S+)", lambda m: m.group(1) + MASK, out)
    try:
        still = secretscan.find(out, root)
    except Exception:  # noqa: BLE001 - never a pass
        still = [{"line": 1}]
    return out if not still else MASK


def tail_masked(root: Path, path: Path, lines: int) -> list[str]:
    try:
        from orch import secretscan
    except ImportError:  # the core is always there (python -m under orch); never a silent pass
        raise Refused("Could not check the log for secrets. Update orch and try again.") from None
    if not path.is_file():
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 256 * 1024))
        raw = f.read().decode("utf-8", errors="replace")
    got = raw.replace("\r\n", "\n").split("\n")
    if size > 256 * 1024:
        got = got[1:]  # the first line may be cut
    if got and got[-1] == "":
        got = got[:-1]
    got = [re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", ln) for ln in got[-lines:]]
    text = "\n".join(got)
    try:
        hits = {h["line"] for h in secretscan.find(text, root)}
    except Exception:  # noqa: BLE001 - never a pass: hide everything
        return [MASK for _ in got]
    return [_mask_line(ln, root) if (i + 1) in hits else ln for i, ln in enumerate(got)]


# ---------------------------------------------------------------- commands


def _emit(args, data: dict, text: str) -> int:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)
    return 0


def _fail(args, msg: str) -> int:
    if args.json:
        print(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        print(f"Refused: {msg}", file=sys.stderr)
    return 2


def _list_text(rows: list[dict], bad: int, note: str | None) -> str:
    lines = []
    for r in rows:
        bits = [r["state"].capitalize()]
        if r["auto"]:
            bits.append("starts by itself")
        if r.get("port"):
            bits.append(f"port {r['port']}")
        lines.append(f"{r['id']}  {r['name']}  ({', '.join(bits)})")
    if not lines:
        lines.append("No services yet.")
    if bad:
        lines.append(f"{bad} file(s) in .orch/addons/services/services could not be read and are skipped.")
    if note:
        lines.append(note)
    lines.append('Next: orch services add "<name>" --id <id> -- <command>  (or start / stop / log <id>)')
    return "\n".join(lines)


def _state(root: Path, drv: drivers.Driver, rec: dict, wid: str) -> dict:
    return _row(root, rec, drv.status(_spec(root, rec, wid, strict=False)))


def cmd_add(args, root: Path) -> int:
    sid = store.check_id(args.id)
    if store.exists(root, sid):
        raise Refused(f"There is already a service {sid}. Pick another id, or remove it first.")
    rec: dict = {
        "schema": store.SCHEMA,
        "id": sid,
        "name": store.clean_name(args.name),
        "command": store.clean_command(args.command),
        "cwd": store.clean_cwd(root, args.cwd),
        "auto": bool(args.auto),
        "created_at": store.now(),
    }
    port = store.check_port(args.port)
    if port is not None:
        rec["port"] = port
    if args.ticket:
        rec["made_by"] = {"ticket": _ticket_key(root, args.ticket)}
    elif args.addon:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", args.addon):
            raise Refused(f"'{args.addon}' is not an add-on name. Use the name orch addon list shows.")
        rec["made_by"] = {"addon": args.addon}
    drv = _driver()
    wid = _workspace_id(root)
    spec = _spec(root, rec, wid)
    store.save(root, rec)
    store.logs_dir(root).mkdir(parents=True, exist_ok=True)
    try:
        drv.install(spec)
    except Refused:
        store.delete(root, sid)
        raise
    store.mark(root, sid, False)
    if args.start:
        drv.start(spec)
        store.mark(root, sid, True)
    row = _state(root, drv, rec, wid)
    nxt = (
        f"Added {rec['name']}; it is running."
        if row["state"] == "running"
        else f"Added {rec['name']}. Start it: orch services start {sid}"
    )
    return _emit(args, {"service": row, "next": nxt}, nxt)


def cmd_simple(args, root: Path, verb: str, sid: str) -> int:
    rec = store.get(root, sid)
    drv = _driver()
    wid = _workspace_id(root)
    if verb in ("auto-on", "auto-off"):
        want = verb == "auto-on"
        if bool(rec.get("auto")) != want:
            rec["auto"] = want
            drv.set_auto(_spec(root, rec, wid))
            store.save(root, rec)
        else:
            drv.set_auto(_spec(root, rec, wid))  # make the entry match the record (cheap, idempotent)
        nxt = (
            f"{rec['name']} starts by itself after this computer restarts."
            if want
            else f"{rec['name']} no longer starts by itself; you start it by hand."
        )
        return _emit(args, {"service": _state(root, drv, rec, wid), "next": nxt}, nxt)
    if verb == "remove":
        spec = _spec(root, rec, wid, strict=False)
        drv.uninstall(spec)
        store.delete(root, sid)
        nxt = f"Removed {rec['name']}. Its log stays in .orch/addons/services/logs/{sid}.log."
        return _emit(args, {"removed": sid, "next": nxt}, nxt)
    spec = _spec(root, rec, wid, strict=verb != "stop")
    getattr(drv, verb)(spec)
    store.mark(root, sid, verb != "stop")
    row = _state(root, drv, rec, wid)
    words = {"start": "Started", "stop": "Stopped", "restart": "Restarted"}[verb]
    nxt = f"{words} {rec['name']}."
    if verb != "stop" and row["state"] != "running":
        nxt = f"{rec['name']} did not stay running. Read its log: orch services log {sid}"
    return _emit(args, {"service": row, "next": nxt}, nxt)


def cmd_log(args, root: Path) -> int:
    rec = store.get(root, args.id)
    n = args.lines
    if not 1 <= n <= 1000:
        raise Refused("Give a number of lines from 1 to 1000.")
    lines = tail_masked(root, store.log_path(root, rec["id"]), n)
    if args.json:
        print(json.dumps({"id": rec["id"], "lines": lines}, ensure_ascii=False))
        return 0
    print("\n".join(lines) if lines else f"{rec['name']} has not written anything yet.")
    return 0


def run(args) -> int:
    root = _root(args.dir)
    cmd = args.cmd
    if cmd == "list":
        rows, bad, note = _rows(root)
        data = {"services": rows, "unreadable": bad}
        if note:
            data["note"] = note
        return _emit(args, data, _list_text(rows, bad, note))
    if cmd == "add":
        return cmd_add(args, root)
    if cmd in ("start", "stop", "restart", "remove"):
        return cmd_simple(args, root, cmd, args.id)
    if cmd == "auto":
        return cmd_simple(args, root, f"auto-{args.value}", args.id)
    if cmd == "act":
        if len(args.target) != 1:
            raise Refused("Say which service: orch services act <verb> -- <id>")
        return cmd_simple(args, root, args.verb, args.target[0])
    if cmd == "log":
        return cmd_log(args, root)
    if cmd == "view":
        from .view import build

        print(json.dumps(build(root, _rows(root)), ensure_ascii=False))
        return 0
    raise Refused(f"Unknown command {cmd}.")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in argv:  # everything after -- is the service's command (add) or the target (act), word by word
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    ap = argparse.ArgumentParser(prog="orch services")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true")
        return s

    p("list")
    s = p("add")
    s.add_argument("name")
    s.add_argument("--id", required=True)
    s.add_argument("--port", type=int)
    s.add_argument("--ticket")
    s.add_argument("--addon")
    s.add_argument("--cwd")
    s.add_argument("--auto", action="store_true")
    s.add_argument("--start", action="store_true")
    for verb in ("start", "stop", "restart", "remove"):
        p(verb).add_argument("id")
    s = p("auto")
    s.add_argument("id")
    s.add_argument("value", choices=("on", "off"))
    s = p("log")
    s.add_argument("id")
    s.add_argument("--lines", type=int, default=20)
    s = p("act")
    s.add_argument("verb", choices=ACT_VERBS)
    s.add_argument("--by")
    p("view")
    want_json = "--json" in argv
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        if want_json and e.code:
            print(json.dumps({"error": "That command is not complete. See: orch services --help"}))
            return 2
        raise
    args.json = bool(getattr(args, "json", False)) or want_json
    args.command = command
    args.target = command
    if args.cmd not in ("add", "act") and command:
        return _fail(args, "Nothing goes after -- for this command. Leave it out and try again.")
    try:
        return run(args)
    except Refused as e:
        return _fail(args, str(e))
