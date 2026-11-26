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
    """The screen shows the tool's confirm prompt (read from the whole dialog, core runs_live.confirm_prompt; at once,
    ORCH-2197), or it has not changed for QUIET seconds and its last lines look like a question."""
    import time

    from orch import runs_live

    if runs_live.confirm_prompt(screen) is not None:
        return True
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


def ref(root: Path, orch_bin: str | None, tid: str, plain: bool = False) -> tuple[str, str] | str:
    """(socket, session) of the ticket's live session, or the plain reason there is none: 'oneshot' (a run that
    works one step at a time), 'none' (nothing runs), 'notmux' (this machine cannot show it). plain: the plain
    terminal's shell counts too (only the terminal bridge, ORCH-743; the screen and keys routes stay helpers')."""
    return ref_kind(root, orch_bin, tid, plain)[0]


def ref_kind(
    root: Path, orch_bin: str | None, tid: str, plain: bool = False
) -> tuple[tuple[str, str] | str, bool]:
    """ref(), and whether it is the plain terminal's shell (its typing has its own switch, ORCH-261). With plain,
    the plain terminal is looked for first: an id that is both counts as the shell (the stricter switch)."""
    if not TID.fullmatch(tid or ""):
        return "none", False
    claim = _plain_terminal(root, orch_bin, tid) if plain else None
    shell = claim is not None
    if claim is None:
        status = run_orch(orch_bin, ["run", "status", tid, "--json"], root)
        claim = (status or {}).get("claim") if isinstance(status, dict) else None
        if not isinstance(claim, dict) or not (status or {}).get("running"):
            return "none", shell
    t = claim.get("tmux")
    if not isinstance(t, dict):
        return "oneshot", shell
    sock, sess = t.get("socket"), t.get("session")
    if not (isinstance(sock, str) and SOCKET.fullmatch(sock) and isinstance(sess, str) and sess == tid):
        return "none", shell
    return ((sock, sess) if shutil.which("tmux") else "notmux"), shell


def _plain_terminal(root: Path, orch_bin: str | None, tid: str) -> dict | None:
    """{tmux: {socket, session}} of the plain terminal (a session without a ticket, ORCH-743) when tid is its
    hidden ticket and its shell runs; from `orch session list`, checked by ref() like a run's claim."""
    listed = run_orch(orch_bin, ["session", "list", "--json"], root)
    rows = listed.get("sessions") if isinstance(listed, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if (
            isinstance(row, dict)
            and row.get("kind") == "terminal"
            and row.get("id") == tid
            and row.get("open")
        ):
            return {"tmux": row["tmux"]} if isinstance(row.get("tmux"), dict) else None
    return None


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


def _plain_screen(root: Path, orch_bin: str | None, tid: str) -> tuple[tuple[str, str] | None, str | None]:
    """((socket, session), the visible screen as plain text) of the ticket's helper; the screen is None when it cannot
    be read or is scrolled up (a prompt may be below)."""
    r = ref(root, orch_bin, tid)
    if isinstance(r, str):
        return None, None
    sock, sess = r
    try:
        p = _tmux(
            sock, "capture-pane", "-p", "-t", f"={sess}:", ";",
            "display-message", "-p", "-t", f"={sess}:", _MARK + "#{pane_in_mode}",
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return r, None
    body, _, meta = p.stdout.rpartition(_MARK)
    if p.returncode != 0 or meta.strip() != "0":
        return r, None
    return r, body.removesuffix("\n")


def confirm(root: Path, orch_bin: str | None, tid: str) -> dict | None:
    """The confirm prompt the helper shows now (core runs_live.confirm_prompt), or None: what the OK card shows
    (ORCH-2197). Never raises."""
    from orch import runs_live

    _, screen = _plain_screen(root, orch_bin, tid)
    return runs_live.confirm_prompt(screen) if screen is not None else None


def answer(root: Path, orch_bin: str | None, tid: str, choice, digest) -> tuple[int, str]:
    """Allow once or Don't allow on the confirm prompt the person saw (ORCH-2197): only while the screen shows that
    same prompt (its digest), and only its plain Yes or its No option, as one key. (status, message)."""
    from orch import runs_live

    if choice not in ("yes", "no") or not isinstance(digest, str) or not digest:
        return 400, "That request could not be read."
    r, screen = _plain_screen(root, orch_bin, tid)
    if r is None:
        return 409, "There is no live session to answer."
    prompt = runs_live.confirm_prompt(screen) if screen is not None else None
    if prompt is None or prompt["digest"] != digest or prompt.get("unclear"):
        return 409, "The helper no longer asks this. Open the terminal to see what it shows now."
    sock, sess = r
    try:
        if _tmux(sock, "send-keys", "-t", f"={sess}:", "-l", "--", prompt[choice]).returncode != 0:
            return 502, "The session did not take that."
    except (OSError, subprocess.TimeoutExpired):
        return 502, "The session did not answer."
    return 200, "{}"


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
