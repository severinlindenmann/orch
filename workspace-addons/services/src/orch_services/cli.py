"""orch services list|check|found|add|adopt|start|stop|restart|auto|remove|log|act|view|status (contract: contracts/addons/services/README.md)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import drivers, service, store, watch
from .store import Refused

MASK = "••••••"
ACT_VERBS = ("start", "stop", "restart", "auto-on", "auto-off", "remove", "adopt")


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


def _key_from_files(root: Path, ref: str) -> str:
    """A ticket key (DM1-12, any case) to its id from the plain ticket files; anything else comes back as is."""
    want = ref.strip().upper()
    for p in sorted((root / ".orch" / "tickets").glob("t_*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(t, dict) and t.get("id") == p.stem and str(t.get("key", "")).upper() == want:
            return p.stem
    return ref


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
        tid = _key_from_files(root, tid)  # the core could not be asked: read the ticket files themselves
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
    if store.on_external_volume(root) and store.on_external_volume(cwd):
        cwd = Path.home()  # launchd jobs may not use a folder on an external disk
    # an adopted service runs from its own entry: its command words are only shown, never looked up
    argv = [_program(root, rec, strict and rec.get("adopted") is None), *rec["command"][1:]]
    for s in (str(cwd), str(log), *argv):
        if "\n" in s or "\r" in s or "\x00" in s:
            raise Refused("A path or word of this service has a line break in it. Fix it and try again.")
    env = {"PATH": os.environ.get("PATH") or "/usr/bin:/bin"}
    ext = _adopted(rec)
    return drivers.Spec(
        sid=rec["id"],
        name=rec["name"],
        workspace_id=wid or _workspace_id(root),
        argv=argv,
        cwd=cwd,
        log=log,
        auto=bool(rec.get("auto")),
        env=env,
        external=ext["entry"] if ext else None,
        external_path=Path(ext["path"]) if ext and ext.get("path") else None,
    )


def _adopted(rec: dict) -> dict | None:
    """The existing entry an adopted service points at, or None (orch made it)."""
    a = rec.get("adopted")
    if not isinstance(a, dict) or a.get("kind") not in ("launchd", "systemd"):
        return None
    if not isinstance(a.get("entry"), str) or not re.fullmatch(r"[A-Za-z0-9@._-]{1,200}", a["entry"]):
        return None
    if a.get("path") is not None and not (isinstance(a["path"], str) and a["path"].startswith("/")):
        return None
    return a


def _same_kind(drv: drivers.Driver, rec: dict) -> None:
    a = rec.get("adopted")
    if a is not None and (_adopted(rec) is None or a.get("kind") != drv.name):
        raise Refused(
            f"{rec['name']} was found on another kind of computer. Forget it: orch services remove {rec['id']}"
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
        "command": _masked_command(root, rec["command"]),
        "cwd": rec.get("cwd", "."),
    }
    if running and st and st.pid:
        row["pid"] = st.pid
    row.update(watch.row_extra(root, rec, st))
    if row["failing"]:
        row["state"] = "failing"
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
                _same_kind(drv, r)
                st = drv.status(_spec(root, r, wid, strict=False))
            except Refused:
                st = None
        rows.append(_row(root, r, st))
    return rows, bad, note


# ---------------------------------------------------------------- secrets


def _no_secret(root: Path, rec: dict) -> None:
    """A new service's name and command must not hold a secret (they are shown in list, log and the page)."""
    try:
        from orch import secretscan
    except ImportError:  # the core is always there (python -m under orch); never a silent pass
        raise Refused("Could not check the command for secrets. Update orch and try again.") from None
    hits = secretscan.find("\n".join([rec["name"], *rec["command"]]), root)
    unreadable = any(h.get("kind") == "keys-unreadable" for h in hits)
    if unreadable or (hits and all(h.get("kind") == "stored-key" for h in hits)):  # stored-key: an older core
        why = _stored_keys_unreadable(root)
        if why or unreadable:  # the comparison could not run: say why instead of blaming a harmless command
            why = why or "orch could not read them. Try again in a moment."
            raise Refused(f"Could not compare the command with this workspace's stored keys, because {why}")
    if hits:
        raise Refused(
            "The name or command holds a secret. Leave it out and read it inside the command with orch secret exec."
        )


def _stored_keys_unreadable(root: Path) -> str | None:
    """The core's own words when the stored keys cannot be read (then every check reports a stored key)."""
    try:
        from orch import keystore

        keystore.all_needles(root)
    except Exception as e:  # noqa: BLE001 - only to say why; the add stays refused either way
        return _plain_reason(e)
    return None


def _plain_reason(e: Exception) -> str:
    text = " ".join(str(e).split()).removeprefix("Refused: ")[:1000]
    return text if text else "orch could not read them. Try again in a moment."


def _masked_command(root: Path, argv: list[str]) -> list[str]:
    """The command words for output; a word with a secret (a record edited by hand) is shown as ••••••."""
    try:
        from orch import secretscan

        out = [MASK if "\n" in a or "\r" in a or secretscan.find(a, root) else a for a in argv]
        # a value split over several words: hide all but the program
        if any(secretscan.find(sep.join(out), root) for sep in ("\n", " ")):
            out = [out[0] if not secretscan.find(out[0], root) else MASK, *(MASK for _ in out[1:])]
    except Exception:  # noqa: BLE001 - never a pass: hide every word
        return [MASK for _ in argv]
    return out


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
    _scanner()
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
    return mask_lines(root, got[-lines:])


def _scanner():
    try:
        from orch import secretscan
    except ImportError:  # the core is always there (python -m under orch); never a silent pass
        raise Refused("Could not check the log for secrets. Update orch and try again.") from None
    return secretscan


def mask_lines(root: Path, got: list[str]) -> list[str]:
    """Each line through the core secret scan; a hit shows ••••••."""
    secretscan = _scanner()
    got = [re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", ln) for ln in got]
    text = "\n".join(got)
    try:
        hits = {h["line"] for h in secretscan.find(text, root)}
    except Exception:  # noqa: BLE001 - never a pass: hide everything
        return [MASK for _ in got]
    out = [_mask_line(ln, root) if (i + 1) in hits else ln for i, ln in enumerate(got)]
    try:
        if secretscan.find("\n".join(out), root):  # e.g. a stored value split over lines: hide everything
            return [MASK for _ in out]
    except Exception:  # noqa: BLE001 - never a pass
        return [MASK for _ in out]
    return out


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
        if r.get("health") and r["state"] != "stopped":
            bits.append(r["health"]["text"])
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


SETTLE_QUIET = 3.0  # seconds a job that is not even launching gets before it counts as stopped
SETTLE_LAUNCH = 90.0  # seconds a job the platform is still launching gets (slow start under load)


def _settle(drv, spec) -> drivers.Status | None:
    """After a start: wait until the job runs, or is clearly not coming (never launching, or launching too long)."""
    t0 = time.monotonic()
    while True:
        st = drv.status(spec)
        if st.running:
            return st
        limit = SETTLE_LAUNCH if st.starting else SETTLE_QUIET
        if time.monotonic() - t0 >= limit:
            return st
        time.sleep(0.5)


def _launching(drv, spec) -> bool:
    return bool(drv.status(spec).starting)


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
    _no_secret(root, rec)
    drv = _driver()
    wid = _workspace_id(root)
    spec = _spec(root, rec, wid)
    store.save(root, rec)
    store.log_path(root, sid).parent.mkdir(parents=True, exist_ok=True)
    try:
        drv.install(spec)
    except Refused:
        store.delete(root, sid)
        raise
    store.mark(root, sid, False)
    if args.start:
        drv.start(spec)
        store.mark(root, sid, True)
        watch.note_own_start(root, drv, spec)
        _settle(drv, spec)
    row = _state(root, drv, rec, wid)
    if row["state"] == "running":
        nxt = f"Added {rec['name']}; it is running."
    elif args.start and _launching(drv, spec):
        nxt = f"Added {rec['name']}; it was started and is still starting. Check later: orch services list"
    elif args.start:
        nxt = f"Added {rec['name']} and started it, but it did not stay running. Read its log: orch services log {sid}"
    else:
        nxt = f"Added {rec['name']}. Start it: orch services start {sid}"
    if store.on_external_volume(root):
        nxt += (
            "\nThis workspace is on an external disk: its log is kept in your Library/Logs/orch folder and the "
            "service runs from your home folder. A service that must reach another device on your network needs "
            "Local Network access (System Settings > Privacy & Security > Local Network)."
        )
    return _emit_kept(args, drv, {"service": row, "next": nxt}, nxt)


def _emit_kept(args, drv, data: dict, text: str) -> int:
    """Linux: services keep running after logout (owner 17 Nov, ORCH-328); the one line it says, if any."""
    keep = getattr(drv, "keep_running", None)
    line = keep() if keep else None
    if line:
        data["note"] = line
        text = f"{text}\n{line}"
    return _emit(args, data, text)


def cmd_simple(args, root: Path, verb: str, sid: str) -> int:
    if verb == "adopt":
        return cmd_adopt(args, root, sid)
    rec = store.get(root, sid)
    if verb == "remove" and rec.get("adopted") is not None:  # orch did not make its entry: only forget it
        store.delete(root, rec["id"])
        nxt = f"{rec['name']} is no longer managed by orch; the job itself is left as it is on this computer."
        return _emit(args, {"removed": rec["id"], "forgotten": True, "next": nxt}, nxt)
    drv = _driver()
    _same_kind(drv, rec)
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
    if verb != "stop":
        watch.note_own_start(root, drv, spec)
    if verb != "stop":
        _settle(drv, spec)
    row = _state(root, drv, rec, wid)
    words = {"start": "Started", "stop": "Stopped", "restart": "Restarted"}[verb]
    nxt = f"{words} {rec['name']}."
    if verb != "stop" and row["state"] != "running" and _launching(drv, spec):
        nxt = f"{rec['name']} is still starting. Check later: orch services list"
    elif verb != "stop" and row["state"] != "running":
        nxt = f"{rec['name']} did not stay running. Read its log: orch services log {sid}"
    return _emit(args, {"service": row, "next": nxt}, nxt)


def cmd_log(args, root: Path) -> int:
    rec = store.get(root, args.id)
    n = args.lines
    if not 1 <= n <= 1000:
        raise Refused("Give a number of lines from 1 to 1000.")
    lines = _log_lines(root, rec, n)
    if args.json:
        print(json.dumps({"id": rec["id"], "lines": lines}, ensure_ascii=False))
        return 0
    print("\n".join(lines) if lines else f"{rec['name']} has not written anything yet.")
    return 0


def _log_lines(root: Path, rec: dict, n: int) -> list[str]:
    a = _adopted(rec)
    if rec.get("adopted") is None:
        return tail_masked(root, store.log_path(root, rec["id"]), n)
    if a and a["kind"] == "launchd" and a.get("path"):
        from .found import launchd_log

        log = launchd_log(Path(a["path"]))
        return tail_masked(root, log, n) if log else []
    if a and a["kind"] == "systemd":
        tool = shutil.which("journalctl")
        if not tool:
            return []
        cp = drivers.run_tool([tool, "--user", "-u", a["entry"], "-n", str(n), "-o", "cat", "--no-pager"])
        return mask_lines(root, cp.stdout.splitlines()[-n:]) if cp.returncode == 0 else []
    return []


# ---------------------------------------------------------------- found and adopt


def _found_text(items: list[dict], others: int = 0) -> str:
    extra = f"{others} other program{'s' if others != 1 else ''} run{'' if others != 1 else 's'} here." if others else ""
    if not items:
        base = "Nothing found: orch sees no other background jobs of your account on this computer."
        return f"{base} {extra}" if extra else base
    lines = []
    for it in items:
        bits = ["Running" if it["running"] else "Stopped"]
        if it["auto"]:
            bits.append("starts by itself")
        lines.append(f"{it['id']}  {it['name']}  ({', '.join(bits)}) - {it['what']}")
    lines.append("Next: orch services adopt <id> to manage one with orch (nothing changes until then)")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s or "found"


def _free_id(root: Path, want: str | None, name: str) -> str:
    if want:
        sid = store.check_id(want)
        if store.exists(root, sid):
            raise Refused(f"There is already a service {sid}. Pick another id with --id.")
        return sid
    base = _slug(name)
    for i in range(1, 100):
        sid = base if i == 1 else f"{base[:36]}-{i}"
        if not store.exists(root, sid):
            return sid
    raise Refused("Could not pick an id for it. Give one with --id.")


def cmd_adopt(args, root: Path, fid: str) -> int:
    """Manage with orch: a record that points at the existing entry. The entry itself is not touched."""
    from . import found

    if isinstance(fid, str) and fid.startswith("process:"):
        it = found.get(root, fid)
        cmd = " ".join(it["command"])
        raise Refused(
            f"{it['name']} is a program without a service entry, so orch cannot take it over as it is: to keep it "
            f'running with orch, stop it yourself, then add it: orch services add "{it["name"]}" --id <id> -- {cmd}'
        )
    it = found.get(root, fid)
    drv = _driver()
    how = it["how"]
    if how.get("kind") != drv.name:
        raise Refused(f"{it['name']} cannot be managed on this computer. Run orch services found again.")
    name = store.clean_name(getattr(args, "name", None) or it["name"])
    _no_secret(
        root, {"name": name, "command": []}
    )  # the name shows in list, questions and the page, as with add
    sid = _free_id(root, getattr(args, "id", None), name)
    try:
        command = store.clean_command(it["command"])
    except Refused:
        command = [it["name"]]
    entry = how["label"] if how["kind"] == "launchd" else how["unit"]
    made_by: dict = {"found": True}
    if getattr(args, "ticket", None):
        made_by["ticket"] = _ticket_key(root, args.ticket)
    rec = {
        "schema": store.SCHEMA,
        "id": sid,
        "name": name,
        "command": command,
        "cwd": ".",
        "auto": bool(it["auto"]),
        "created_at": store.now(),
        "made_by": made_by,
        "adopted": {"kind": how["kind"], "entry": entry, "path": how.get("path")},
    }
    wid = _workspace_id(root)
    store.save(root, rec)
    row = _state(root, drv, rec, wid)
    nxt = f"{name} is now managed by orch (id {sid}); it was not moved, changed or restarted."
    return _emit_kept(args, drv, {"service": row, "next": nxt}, nxt)


def check_pass(root: Path) -> tuple[list[dict], list[str], int]:
    """One pass over every service: health, failing, the one question and acting on its answer (no loop).
    The caller holds the check lock (service.check_pass)."""
    recs, bad = store.load_all(root)
    drv = _driver()
    wid = _workspace_id(root)
    out, said = [], []
    for rec in recs:
        try:
            _same_kind(drv, rec)
            res = watch.check_one(root, drv, rec, _spec(root, rec, wid, strict=False))
        except Refused as e:
            res = {"id": rec["id"], "name": rec["name"], "error": str(e)}
            said.append(f"{rec['name']}: {e}")
        else:
            if res.get("did"):
                said.append(res["did"])
            elif res["failing"]:
                said.append(f"{rec['name']} keeps stopping; the question is open.")
        out.append(res)
    if not recs:
        said.append("No services yet.")
    elif not said:
        said.append(f"Checked {len(recs)} service(s); all as expected.")
    return out, said, bad


def cmd_check(args, root: Path) -> int:
    with service.check_pass(root, wait=service.CHECK_WAIT):
        out, said, bad = check_pass(root)
    data: dict = {"checked": out, "unreadable": bad}
    return _emit(args, data, "\n".join(said))


def cmd_checker(args, root: Path) -> int:
    """start | stop | status without a service id: the regular check (run by orch start and turning Services on)."""
    if args.cmd == "start":
        pid = service.start(root)
        text = f"The regular check runs: every {service.EVERY_SECS} seconds (pid {pid})."
        return _emit(args, {"running": True, "pid": pid}, text)
    if args.cmd == "stop":
        stopped = service.stop(root)
        text = "The regular check stopped." if stopped else "The regular check was not running."
        return _emit(args, {"stopped": stopped}, text)
    pid = service.running_pid(root)
    if pid:
        return _emit(args, {"running": True, "pid": pid}, f"The regular check runs (pid {pid}).")
    text = "The regular check is off. Start it: orch start (or orch services start)"
    _emit(args, {"running": False}, text)
    return 1


def _checker_round(root: Path) -> None:
    _out, said, _bad = check_pass(root)
    for line in said:
        if not line.startswith(("Checked ", "No services yet.")):
            print(f"{store.now()} {line}", flush=True)


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
    if cmd == "check":
        return cmd_check(args, root)
    if cmd == "found":
        from . import found

        items = found.scan(root)
        note = found.note()
        if note:
            return _emit(args, {"found": items, "note": note}, note)
        n = found.others(root)
        return _emit(args, {"found": items, **({"others": n} if n else {})}, _found_text(items, n))
    if cmd == "adopt":
        return cmd_adopt(args, root, args.found_id)
    if cmd in ("start", "stop") and args.id is None:
        return cmd_checker(args, root)
    if cmd == "status":
        return cmd_checker(args, root)
    if cmd == "watch":
        return service.watch(root, lambda: _checker_round(root), log=lambda m: print(m, flush=True))
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

        try:  # read-only; a computer that cannot list its jobs simply shows no Found group
            from . import found

            found_items = found.scan(root)
        except (OSError, ValueError, Refused, subprocess.SubprocessError):
            found_items = []
        print(json.dumps(build(root, _rows(root), found_items), ensure_ascii=False))
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
    p("check")
    p("found")
    s = p("adopt")
    s.add_argument("found_id")
    s.add_argument("--name")
    s.add_argument("--id")
    s.add_argument("--ticket")
    s = p("add")
    s.add_argument("name")
    s.add_argument("--id", required=True)
    s.add_argument("--port", type=int)
    s.add_argument("--ticket")
    s.add_argument("--addon")
    s.add_argument("--cwd")
    s.add_argument("--auto", action="store_true")
    s.add_argument("--start", action="store_true")
    for verb in ("start", "stop"):  # without an id: the regular check (orch start runs these)
        p(verb).add_argument("id", nargs="?")
    for verb in ("restart", "remove"):
        p(verb).add_argument("id")
    p("status")
    sub.add_parser("watch", help=argparse.SUPPRESS)
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
