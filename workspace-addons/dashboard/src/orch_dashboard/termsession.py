"""The live helper session in the browser: read its screen, type into it (fb17).

A live run is the agent in its own tmux session on orch's own tmux server (core `runs_live`). The run claim
(`orch run status <ticket> --json`) names it: claim.tmux = {socket, session}. The names are read from that claim,
never from the request, and checked against the shapes core makes. tmux is called with an argument list (no shell)
and without TMUX in its environment. Reading is open to the dashboard's own page; typing is for the person's
dashboard session only (the server checks that before it calls `keys`)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .data import run_orch

SOCKET = re.compile(r"orch-[0-9a-f]{8}")
SESSION = re.compile(r"t_[a-z0-9]{6,16}")
TID = SESSION
KEYS = frozenset(
    {
        "Enter",
        "Tab",
        "BSpace",
        "Escape",
        "Up",
        "Down",
        "Left",
        "Right",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "C-c",
        "C-d",
    }
)
MAX_ITEMS, MAX_TEXT, TIMEOUT = 40, 2000, 3.0
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # no raw control/escape bytes in text; \t and \n allowed
_MARK = "@@orch "
QUIET = 20.0  # seconds the screen must stay the same before it counts as "waiting"
_ASK = re.compile(r"(do you want|\(y/n\)|\[y/n\]|allow|press enter|\bconfirm\b|proceed\?)", re.IGNORECASE)
_SEEN: dict[tuple[str, str], tuple[str, float]] = {}


def _literal(t: str) -> str:
    """tmux ends a command at an argument that ends in an unescaped ';' (and drops it): keep it literal."""
    return t[:-1] + "\\;" if t.endswith(";") else t


def waiting_input(key: tuple[str, str], screen: str, now: float | None = None) -> bool:
    """The screen has not changed for QUIET seconds and its last lines look like a question or a confirm prompt."""
    import time

    now = time.monotonic() if now is None else now
    old = _SEEN.get(key)
    if old is None or old[0] != screen:
        _SEEN[key] = (screen, now)
        return False
    tail = "\n".join([ln for ln in screen.split("\n") if ln.strip()][-4:])
    return now - old[1] >= QUIET and bool(_ASK.search(tail))


def _tmux(socket: str, *args: str, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    import os

    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    return subprocess.run(
        ["tmux", "-L", socket, *args], capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


def ref(root: Path, orch_bin: str | None, tid: str) -> tuple[str, str] | str:
    """(socket, session) of the ticket's live session, or the plain reason there is none: 'oneshot' (a run that
    works one step at a time), 'none' (nothing runs), 'notmux' (this machine cannot show it)."""
    if not TID.fullmatch(tid or ""):
        return "none"
    status = run_orch(orch_bin, ["run", "status", tid, "--json"], root)
    claim = (status or {}).get("claim") if isinstance(status, dict) else None
    if not isinstance(claim, dict) or not (status or {}).get("running"):
        return "none"
    t = claim.get("tmux")
    if not isinstance(t, dict):
        return "oneshot"
    sock, sess = t.get("socket"), t.get("session")
    if not (isinstance(sock, str) and SOCKET.fullmatch(sock) and isinstance(sess, str) and sess == tid):
        return "none"
    return (sock, sess) if shutil.which("tmux") else "notmux"


def snapshot(root: Path, orch_bin: str | None, tid: str) -> dict:
    """The screen as the person would see it: ANSI text, size, cursor. Never raises."""
    r = ref(root, orch_bin, tid)
    if isinstance(r, str):
        return {"state": r}
    sock, sess = r
    try:
        p = _tmux(
            sock, "capture-pane", "-e", "-p", "-t", f"={sess}:", ";",
            "display-message", "-p", "-t", f"={sess}:",
            _MARK + "#{pane_in_mode} #{cursor_x} #{cursor_y} #{pane_width} #{pane_height} #{cursor_flag}",
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "none"}
    body, _, meta = p.stdout.rpartition(_MARK)
    f = meta.split()
    if p.returncode != 0 or len(f) < 6:
        return {"state": "none"}
    try:
        mode, cx, cy, cols, rows, cur = (int(x) for x in f[:6])
    except ValueError:
        return {"state": "none"}
    screen = body.removesuffix("\n")
    return {
        "state": "live",
        "screen": screen,
        "cx": cx,
        "cy": cy,
        "cols": cols,
        "rows": rows,
        "scrolled": mode != 0,
        "cursor": cur == 1,
        "waiting_input": waiting_input((sock, sess), screen),
    }


def keys(root: Path, orch_bin: str | None, tid: str, items) -> tuple[int, str]:
    """Type the items into the session: {t: text} literally, {k: name} from the allow-list. (status, message)."""
    if not isinstance(items, list) or not 0 < len(items) <= MAX_ITEMS:
        return 400, "That request could not be read."
    plan: list[list[str]] = []
    for it in items:
        if not isinstance(it, dict) or len(it) != 1:
            return 400, "That request could not be read."
        if isinstance(it.get("t"), str) and 0 < len(it["t"]) <= MAX_TEXT and not CTRL.search(it["t"]):
            plan.append(["-l", "--", _literal(it["t"])])
        elif isinstance(it.get("k"), str) and it["k"] in KEYS:
            plan.append([it["k"]])
        else:
            return 400, "That request could not be read."
    r = ref(root, orch_bin, tid)
    if isinstance(r, str):
        return 409, "There is no live session to type into."
    sock, sess = r
    try:
        for args in plan:
            if _tmux(sock, "send-keys", "-t", f"={sess}:", *args).returncode != 0:
                return 502, "The session did not take that."
    except (OSError, subprocess.TimeoutExpired):
        return 502, "The session did not answer."
    return 200, "{}"
