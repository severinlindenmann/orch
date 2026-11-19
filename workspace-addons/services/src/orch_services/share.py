"""`orch services share <folder> --ticket <id>`: share a folder by link with one command (ORCH-684).

Picks a port of the shared range that nothing else holds for 127.0.0.1 (a server that listens on every address
counts as holding it, report r-1118-2103-ws), serves the folder as a service on the ticket (share_server.py),
checks the link through the address the owner's request takes, and prints the link.

Settings, the [services] table of .orch/config.toml (like [dashboard] listen*):

    [services]
    share_ports = "8780-8799"           # the ports other computers can reach (required)
    share_name = "my-server.example"    # the name other computers use for this one (required, in the link)
    share_skip = [8786, 8787]           # ports kept for something else, never used even when free right now
    share_check = "192.168.64.4"        # the address the check goes through (default 127.0.0.1)

The workspace's own dashboard port for other computers ([dashboard] listen_port) is skipped by itself.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import share_server, store, watch
from .store import Refused

TABLE = "services"
TRIES = 3  # ports tried when the server lost its port to another one between the pick and its start
CHECK_SECONDS = 10.0
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
SET_LINE = 'Set it once in .orch/config.toml: [services] share_ports = "8780-8799" and share_name = "<this computer\'s name>".'


# ---- settings


def _host(v: object, what: str) -> str:
    s = str(v).strip().lower()
    try:
        ip = ipaddress.ip_address(s.strip("[]"))
        return f"[{ip}]" if ip.version == 6 else str(ip)
    except ValueError:
        pass
    if not _HOST_RE.fullmatch(s):
        raise Refused(f"{what} '{v}' is not a computer name or address. Fix it in .orch/config.toml.")
    return s


def _port(v: object, what: str) -> int:
    if isinstance(v, bool) or not str(v).strip().isdigit() or not 1024 <= int(str(v).strip()) <= 65535:
        raise Refused(f"{what} '{v}' is not a port between 1024 and 65535. Fix it in .orch/config.toml.")
    return int(str(v).strip())


def _range(v: object) -> list[int]:
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(v)) if isinstance(v, str) else None
    if not m:
        raise Refused(f"share_ports '{v}' is not a range such as \"8780-8799\". Fix it in .orch/config.toml.")
    lo, hi = _port(m[1], "share_ports"), _port(m[2], "share_ports")
    if lo > hi or hi - lo > 1000:
        raise Refused(
            f"share_ports '{v}' must go from low to high, at most 1000 ports. Fix it in .orch/config.toml."
        )
    return list(range(lo, hi + 1))


def settings(root: Path) -> dict:
    try:
        from orch import config
    except ImportError:
        raise Refused("Could not read this workspace's settings. Update orch and try again.") from None
    doc = config.read(root)
    t = doc.get(TABLE) if isinstance(doc.get(TABLE), dict) else {}
    if t.get("share_ports") in (None, "") or t.get("share_name") in (None, ""):
        raise Refused(f"Sharing a folder is not set up here. {SET_LINE}")
    skip = t.get("share_skip", [])
    if not isinstance(skip, list):
        raise Refused("share_skip must be a list of ports such as [8786, 8787]. Fix it in .orch/config.toml.")
    kept = {_port(p, "share_skip") for p in skip}
    dash = doc.get("dashboard") if isinstance(doc.get("dashboard"), dict) else {}
    if dash.get("listen_port") not in (None, ""):
        try:
            kept.add(_port(dash["listen_port"], "listen_port"))
        except Refused:
            pass  # the dashboard says why itself; nothing to skip
    check = t.get("share_check")
    return {
        "ports": _range(t["share_ports"]),
        "skip": kept,
        "name": _host(t["share_name"], "share_name"),
        "check": _host(check, "share_check") if check not in (None, "") else "127.0.0.1",
        "check_set": check not in (None, ""),
    }


# ---- the port


def port_free(port: int) -> bool:
    """Nothing holds 127.0.0.1:<port>: a test bind without address sharing works. It fails for a listener on
    127.0.0.1 and for one on every address (0.0.0.0, a dual-stack [::]); a listener on another single address
    (such as a forwarder on the private network address) does not hold it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        share_server.exclusive(s)
        s.bind((share_server.HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(cfg: dict, taken: set[int]) -> int | None:
    for p in cfg["ports"]:
        if p not in cfg["skip"] and p not in taken and port_free(p):
            return p
    return None


# ---- the folder


def check_folder(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_dir():
        raise Refused(f"The folder {raw} does not exist. Give a folder that does.")
    real = p.resolve()
    home = Path.home().resolve()
    if real == home or real.parent == real or real in home.parents:
        raise Refused(
            "That folder is too wide to share (the home folder or above it). Give the folder to share."
        )
    if (real / ".orch").exists() or any(q.name == ".orch" for q in (real, *real.parents)):
        raise Refused(
            "A workspace's .orch folder holds private files and is never shared. Give another folder."
        )
    if any(q.name == ".ssh" or q.name == ".gnupg" for q in (real, *real.parents)):
        raise Refused("That folder holds keys and is never shared. Give another folder.")
    return real


# ---- the link check


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def check_link(
    host: str, port: int, mark: str, running=None, seconds: float = CHECK_SECONDS
) -> tuple[bool, str]:
    """(True, "") when http://<host>:<port>/ answers 200 with this share's mark; else (False, what answered).
    `running()` says whether the server still runs (a server that stopped will not come)."""
    url = f"http://{host}:{port}/"
    end = time.monotonic() + seconds
    why = "nothing answered"
    foreign = 0
    while True:
        try:
            with _opener().open(url, timeout=2) as r:
                got, status, server = (
                    r.headers.get(share_server.HEADER),
                    r.status,
                    r.headers.get("Server", ""),
                )
        except urllib.error.HTTPError as e:
            got, status, server = e.headers.get(share_server.HEADER), e.code, e.headers.get("Server", "")
        except (OSError, ValueError):
            got, status, server = None, None, ""
        if status is not None and got == mark and status == 200:
            return True, ""
        if status is not None and got == mark:
            why = f"the folder's server answered {status}"
        elif status is not None:
            foreign += 1
            why = f"another server answered ({server[:60] or 'no name'}, {status})"
            if foreign >= 3:
                return False, why
        if running is not None and not running():
            return False, why if status is not None else "the server stopped (the port was taken)"
        if time.monotonic() >= end:
            return False, why
        time.sleep(0.3)


# ---- the command


def _taken_by_services(root: Path) -> set[int]:
    recs, _ = store.load_all(root)
    return {r["port"] for r in recs if isinstance(r.get("port"), int)}


def _existing(root: Path, folder: Path) -> dict | None:
    recs, _ = store.load_all(root)
    for r in recs:
        s = r.get("share")
        if isinstance(s, dict) and s.get("dir") == str(folder) and isinstance(r.get("port"), int):
            return r
    return None


def _argv(folder: Path, port: int, mark: str) -> list[str]:
    # this Python (it has the add-on), -I: no folder, PYTHON* variable or user site can plant a module
    return [
        sys.executable,
        "-I",
        "-m",
        "orch_services.share_server",
        "--dir",
        str(folder),
        "--port",
        str(port),
        "--mark",
        mark,
    ]


def _drop(root: Path, drv, spec, sid: str) -> bool:
    """Undo only what this call made. False (and the record kept, so `remove` can still end it) when the
    computer's service tool refused to stop or remove it."""
    try:
        drv.stop(spec)
        drv.uninstall(spec)
    except (Refused, OSError):
        return False
    store.delete(root, sid)
    return True


def _undo_failed(sid: str) -> Refused:
    return Refused(
        f"The link did not work and the share could not be stopped. End it with: orch services remove {sid}"
    )


def cmd_share(args, root: Path) -> int:
    from . import cli  # the shared helpers of the service commands

    cfg = settings(root)
    folder = check_folder(args.folder)
    ticket = cli._ticket_key(root, args.ticket)
    if args.port is not None and args.port not in cfg["ports"]:
        raise Refused(
            f"Port {args.port} is not in share_ports ({cfg['ports'][0]}-{cfg['ports'][-1]}). Leave out --port."
        )
    if args.port is not None and args.port in cfg["skip"]:
        raise Refused(f"Port {args.port} is kept for something else (share_skip). Leave out --port.")
    drv = cli._driver()
    wid = cli._workspace_id(root)

    old = _existing(root, folder)
    if old is not None:
        spec = cli._spec(root, old, wid, strict=False)
        mark = old["share"].get("mark", "")
        if drv.status(spec).running:
            ok, _ = check_link(cfg["check"], old["port"], mark, seconds=3)
            if ok:
                return _done(args, cli, root, drv, wid, old, cfg, again=True)
        raise Refused(
            f"This folder already has a share, {old['id']}, but its link does not answer. "
            f"Start it (orch services start {old['id']}) or remove it (orch services remove {old['id']})."
        )

    tried: set[int] = set()
    last = ""
    for _ in range(1 if args.port is not None else TRIES):
        taken = _taken_by_services(root) | tried
        if args.port is not None:
            if args.port in taken or not port_free(args.port):
                raise Refused(f"Port {args.port} is taken. Leave out --port and orch picks a free one.")
            port = args.port
        else:
            port = pick_port(cfg, taken)
            if port is None:
                raise Refused(
                    f"Every port of share_ports ({cfg['ports'][0]}-{cfg['ports'][-1]}) is taken. "
                    "Stop a share you no longer need (orch services list), then try again."
                )
        tried.add(port)
        mark = secrets.token_hex(16)
        sid = cli._free_id(root, args.id, f"share-{folder.name}")
        rec: dict = {
            "schema": store.SCHEMA,
            "id": sid,
            "name": store.clean_name(f"Share {folder.name}"[:80]),
            "command": _argv(folder, port, mark),
            "cwd": ".",
            "auto": False,
            "created_at": store.now(),
            "port": port,
            "share": {"dir": str(folder), "mark": mark},
        }
        if ticket:
            rec["made_by"] = {"ticket": ticket}
        cli._no_secret(root, rec)
        spec = cli._spec(root, rec, wid)
        store.save(root, rec)
        store.logs_dir(root).mkdir(parents=True, exist_ok=True)
        try:
            drv.install(spec)
            drv.start(spec)
            store.mark(root, sid, True)
            watch.note_own_start(root, drv, spec)
            cli._settle(drv, spec)
            ok, last = check_link(
                cfg["check"], port, mark, running=lambda spec=spec: drv.status(spec).running
            )
        except BaseException:
            _drop(root, drv, spec, sid)
            raise
        if ok:
            return _done(args, cli, root, drv, wid, rec, cfg)
        if not _drop(root, drv, spec, sid):
            raise _undo_failed(sid)
    where = f"{cfg['check']}:{max(tried)}" if tried else cfg["check"]
    raise Refused(
        f"The link did not work: on {where} {last}. Nothing was left running. Try again, or pick --port."
    )


def _done(args, cli, root: Path, drv, wid: str, rec: dict, cfg: dict, again: bool = False) -> int:
    url = f"http://{cfg['name']}:{rec['port']}/"
    row = cli._state(root, drv, rec, wid)
    checked = "through " + cfg["check"] if cfg["check_set"] else "on this computer only (no share_check set)"
    first = "Already shared" if again else "Shared"
    text = (
        f"{first} {rec['share']['dir']}\n{url}\n"
        f"Link checked {checked}. Stop it when done: orch services remove {rec['id']}"
    )
    data = {
        "url": url,
        "port": rec["port"],
        "folder": rec["share"]["dir"],
        "checked": cfg["check"],
        "checked_outside": cfg["check_set"],
        "again": again,
        "service": row,
        "next": f"Give the link. Stop it when done: orch services remove {rec['id']}",
    }
    return cli._emit(args, data, text)
