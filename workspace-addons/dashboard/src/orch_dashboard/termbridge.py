"""The terminal bridge (ORCH-743): a live session's real screen in the browser, on this computer only.

Watching: ONE tmux control-mode client per session, shared by every page that watches it:
  tmux -L <socket> -C attach-session -f ignore-size -t =<session>:
- `ignore-size`: the client never changes the helper's window size (a page is sized to the pane instead).
- Nothing is ever written to its stdin, so it runs no tmux command. It is not attached read-only on purpose: tmux
  takes an outside `send-keys` as coming from a read-only client and refuses it, which would stop orch's own typing.
- A page that joins gets the screen as it is now (capture-pane with colours and the last HISTORY lines, then the
  cursor), then every byte the pane's program writes (`%output`), and the size again whenever the window changes.
  The client ends when the session ends (`%exit` or end of file) or a while after the last page left (LINGER).

Typing: text goes to the pane with `send-keys -l` (literal: every character is a key, no key names, no tmux
command), in parts small enough for one tmux message; a NUL byte (Ctrl+Space) is the key C-@. Resizing: one
`resize-window`, then the window's size follows tmux's own rule again (the option is unset), so a person's own
terminal joined later still fits. Both only reach a session a page watches right now (its names were checked when
the watch began), never a name from the request.

Who may: the server (server.py) serves all of this only on the loopback port with a name of this computer in Host
(never on the port for other computers), the stream to the dashboard's own page, typing and resizing only to the
person's dashboard session with the typing setting on (watching only by default)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from . import termsession

HISTORY = 1000  # lines of scrollback a page gets when it joins
LINGER = 5.0  # seconds a watch stays open after its last page left (a reload rejoins it)
MAX_PAGES = 8  # pages watching at once, all sessions together (each holds one server thread)
MAX_BUFFER = 512 * 1024  # bytes kept for pages that fall behind; older ones get the screen again
MAX_INPUT = 64 * 1024  # characters in one typing request (a long paste)
PART = 1500  # characters per send-keys call: well inside one tmux message (16 KB) even when all are 4 bytes
COLS, ROWS = (10, 500), (3, 300)  # the sizes a resize may ask for
_OCTAL = re.compile(rb"\\([0-7]{3})")
_LOCK = threading.Lock()
_WATCHES: dict[tuple[str, str], Watch] = {}
_PAGES = [0]


def _unescape(data: bytes) -> bytes:
    """%output escapes every byte below 32 and the backslash as \\ooo; the rest comes as is."""
    return _OCTAL.sub(lambda m: bytes([int(m.group(1), 8)]), data)


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}  # never nest in the person's own tmux
    env.setdefault(
        "LANG", "en_US.UTF-8"
    )  # the control client must say UTF-8, else tmux sends `_` for wide chars
    return env


def _tmux(sock: str, *args: str, timeout: float = termsession.TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", sock, *args], capture_output=True, text=True, timeout=timeout, env=_env(), check=False
    )


class Watch:
    """One session's control client and what it wrote, for every page that watches it."""

    def __init__(self, sock: str, sess: str):
        self.sock, self.sess = sock, sess
        self.cond = threading.Condition()
        self.chunks: deque[tuple[int, str, bytes]] = deque()  # (seq, kind "out" | "size", payload)
        self.kept = 0
        self.seq = 0
        self.pages = 0
        self.ended = False
        self.left_at: float | None = None
        self.pane = ""
        self.size = (0, 0)
        self.proc: subprocess.Popen | None = None

    def start(self) -> bool:
        """Attach the control client; False when the session is gone or tmux cannot."""
        try:
            r = _tmux(
                self.sock,
                "display-message",
                "-p",
                "-t",
                f"={self.sess}:",
                "#{pane_id} #{pane_width} #{pane_height}",
            )
            pane, cols, rows = r.stdout.split()
            self.pane, self.size = pane, (int(cols), int(rows))
            self.proc = subprocess.Popen(
                [
                    "tmux",
                    "-L",
                    self.sock,
                    "-C",
                    "attach-session",
                    "-f",
                    "ignore-size",
                    "-t",
                    f"={self.sess}:",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=_env(),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        threading.Thread(target=self._read, name=f"term-{self.sess}", daemon=True).start()
        return True

    def _push(self, kind: str, payload: bytes) -> None:
        with self.cond:
            self.seq += 1
            self.chunks.append((self.seq, kind, payload))
            self.kept += len(payload)
            while self.kept > MAX_BUFFER and len(self.chunks) > 1:
                self.kept -= len(self.chunks.popleft()[2])
            self.cond.notify_all()

    def _read(self) -> None:
        out = self.proc.stdout if self.proc else None
        try:
            for line in iter(out.readline, b"") if out else ():
                line = line.rstrip(b"\n")
                if line.startswith(b"%output "):
                    _, pane, data = (line.split(b" ", 2) + [b""])[:3]
                    if pane.decode(errors="replace") == self.pane:
                        self._push("out", _unescape(data))
                elif line.startswith(
                    (b"%layout-change", b"%window-pane-changed", b"%session-window-changed")
                ):
                    self.resized()
                elif line.startswith(b"%exit"):
                    break
        except (OSError, ValueError):
            pass
        self.close()

    def resized(self) -> None:
        """Read the pane's size again; tell the pages when it changed."""
        try:
            r = _tmux(
                self.sock, "display-message", "-p", "-t", f"={self.sess}:", "#{pane_width} #{pane_height}"
            )
            size = tuple(int(x) for x in r.stdout.split())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        if len(size) == 2 and size != self.size:
            self.size = size  # type: ignore[assignment]
            self._push("size", json.dumps({"cols": size[0], "rows": size[1]}).encode())

    def screen(self) -> dict | None:
        """The screen as it is now, as bytes a terminal draws: scrollback, visible lines, cursor. None: gone."""
        try:
            r = _tmux(
                self.sock, "capture-pane", "-e", "-N", "-p", "-S", f"-{HISTORY}", "-t", f"={self.sess}:", ";",
                "display-message", "-p", "-t", f"={self.sess}:",
                "@@orch #{cursor_x} #{cursor_y} #{pane_width} #{pane_height} #{alternate_on} #{cursor_flag}",
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return None
        body, _, meta = r.stdout.rpartition("@@orch ")
        try:
            cx, cy, cols, rows, alt, cur = (int(x) for x in meta.split()[:6])
        except ValueError:
            return None
        if r.returncode != 0:
            return None
        lines = body.removesuffix("\n").split("\n")
        if alt:
            lines = lines[-rows:]  # an alternate screen has no scrollback of its own
        draw = "\x1b[0m\x1b[H\x1b[2J\x1b[3J" + ("\x1b[?1049h\x1b[H" if alt else "")
        draw += "\r\n".join(ln + "\x1b[0m" for ln in lines)
        draw += f"\x1b[{cy + 1};{cx + 1}H" + ("\x1b[?25h" if cur else "\x1b[?25l")
        self.size = (cols, rows)
        return {"cols": cols, "rows": rows, "data": base64.b64encode(draw.encode()).decode()}

    def since(self, seq: int) -> tuple[list[tuple[int, str, bytes]], bool]:
        """What came after seq, and whether the page fell so far behind that it needs the screen again."""
        with self.cond:
            if self.chunks and self.chunks[0][0] > seq + 1:
                return [], True
            return [c for c in self.chunks if c[0] > seq], False

    def close(self) -> None:
        with self.cond:
            if self.ended:
                return
            self.ended = True
            self.cond.notify_all()
        p = self.proc
        if p is not None:
            try:
                if p.stdin:
                    p.stdin.close()  # the control client detaches when its input ends
                p.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                p.kill()  # only the client this watch started
        with _LOCK:
            if _WATCHES.get((self.sock, self.sess)) is self:
                del _WATCHES[(self.sock, self.sess)]


def _reap() -> None:
    """Close the watches no page has looked at for LINGER seconds (called on every join and leave)."""
    now = time.monotonic()
    with _LOCK:
        idle = [w for w in _WATCHES.values() if w.pages == 0 and w.left_at and now - w.left_at >= LINGER]
    for w in idle:
        w.close()


def join(root: Path, orch_bin: str | None, tid: str) -> Watch | str:
    """Start watching the ticket's live session (or join the watch that is on). The reason when there is none:
    'none', 'oneshot', 'notmux' (as termsession.ref), 'busy' (too many pages watch already)."""
    _reap()
    r = termsession.ref(root, orch_bin, tid)
    if isinstance(r, str):
        return r
    if not shutil.which("tmux"):
        return "notmux"
    with _LOCK:
        if _PAGES[0] >= MAX_PAGES:
            return "busy"
        w = _WATCHES.get(r)
        fresh = w is None or w.ended
        if fresh:
            w = Watch(*r)
            _WATCHES[r] = w
        w.pages += 1
        _PAGES[0] += 1
    if fresh and not w.start():
        leave(w)
        w.close()
        return "none"
    return w


def leave(w: Watch) -> None:
    with _LOCK:
        w.pages = max(0, w.pages - 1)
        _PAGES[0] = max(0, _PAGES[0] - 1)
        if w.pages == 0:
            w.left_at = time.monotonic()
    threading.Timer(LINGER + 0.1, _reap).start()


def watching(tid: str) -> Watch | None:
    """The open watch of this ticket's session, if a page watches it now."""
    with _LOCK:
        for w in _WATCHES.values():
            if w.sess == tid and not w.ended and w.pages > 0:
                return w
    return None


def type_text(tid: str, data) -> tuple[int, str]:
    """Send what the page typed (raw terminal input: text, control keys, escape sequences, a bracketed paste)."""
    if not isinstance(data, str) or not 0 < len(data) <= MAX_INPUT:
        return 400, "That request could not be read."
    w = watching(tid)
    if w is None:
        return 409, "There is no live session to type into."
    calls: list[list[str]] = []
    for i, piece in enumerate(data.split("\x00")):
        if i:
            calls.append(["C-@"])
        for at in range(0, len(piece), PART):
            calls.append(["-l", "--", termsession._literal(piece[at : at + PART])])
    try:
        for args in calls:
            if _tmux(w.sock, "send-keys", "-t", f"={w.sess}:", *args).returncode != 0:
                return 502, "The session did not take that."
    except (OSError, subprocess.TimeoutExpired):
        return 502, "The session did not answer."
    return 200, "{}"


def resize(tid: str, cols, rows) -> tuple[int, str]:
    """Give the helper's window this size (a page that was made bigger or smaller)."""
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in (cols, rows)):
        return 400, "That request could not be read."
    if not (COLS[0] <= cols <= COLS[1] and ROWS[0] <= rows <= ROWS[1]):
        return 400, "That size is out of range."
    w = watching(tid)
    if w is None:
        return 409, "There is no live session to resize."
    t = f"={w.sess}:"
    try:
        r = _tmux(
            w.sock, "resize-window", "-t", t, "-x", str(cols), "-y", str(rows), ";",
            "set-window-option", "-u", "-t", t, "window-size",
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return 502, "The session did not answer."
    if r.returncode != 0:
        return 502, "The session did not take that."
    w.resized()
    return 200, "{}"


def stream(w: Watch, write, gone, ping: float = 15.0) -> None:
    """Server-sent events to one page until the session ends or the page leaves: `screen` (the whole screen,
    first and after falling behind), `out` (bytes, base64), `size`, then `end`. write(bytes) sends;
    gone() says the page closed. Raises what write raises (the server ends the request then)."""

    def ev(name: str, data: str) -> None:
        write(f"event: {name}\ndata: {data}\n\n".encode())

    with w.cond:
        seq = w.seq
    snap = w.screen()
    if snap is None:
        ev("end", json.dumps({"state": "none"}))
        return
    ev("screen", json.dumps(snap))
    last = time.monotonic()
    while True:
        with w.cond:
            if w.seq == seq and not w.ended:
                w.cond.wait(timeout=1.0)
            ended = w.ended and w.seq == seq
        if ended:
            ev("end", json.dumps({"state": "none"}))
            return
        got, behind = w.since(seq)
        if behind:
            with w.cond:
                seq = w.seq
            snap = w.screen()
            if snap is None:
                ev("end", json.dumps({"state": "none"}))
                return
            ev("screen", json.dumps(snap))
            last = time.monotonic()
            continue
        for s, kind, payload in got:
            seq = s
            if kind == "size":
                ev("size", payload.decode())
            else:
                ev("out", base64.b64encode(payload).decode())
            last = time.monotonic()
        if not got:
            if gone():
                return
            if time.monotonic() - last >= ping:
                write(b": ping\n\n")
                last = time.monotonic()
