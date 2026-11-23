"""The terminal bridge (ORCH-743): a live session's real screen in the browser, wherever the person is signed in.

Watching: ONE tmux control-mode client per session, shared by every page that watches it:
  tmux -L <socket> -C attach-session -f ignore-size -t =<session>:
- `ignore-size`: the client never changes the helper's window size (a page is sized to the pane instead).
- It is not attached read-only on purpose: tmux takes an outside `send-keys` as coming from a read-only client and
  refuses it, which would stop orch's own typing. The only commands it ever gets are the two fixed reads of
  screen_cmd (capture-pane, display-message) for the session's own pane id; nothing from a request reaches it.
- Everything is pinned to the pane the watch began with (`%<n>`), so a second pane can never get the typing
  while the page shows the first.
- A page that joins gets the screen as it is now: the capture (colours, the last HISTORY lines), the cursor and
  the terminal modes the program turned on (bracketed paste, cursor keys, keypad, mouse, wrap, insert). The capture
  runs through the control client itself, so it lands at an exact point of the output stream: the page then gets
  every byte the program wrote after it (`%output`), never one twice. The size again whenever the window changes.
  The client ends when the session ends (`%exit` or end of file) or a while after the last page left (LINGER).

Typing: text goes to the pane with `send-keys -l` (literal: every character is a key, no key names, no tmux
command), in parts small enough for one tmux message, one request at a time per session (a paste is never cut
by other keys); a NUL byte (Ctrl+Space) is the key C-@. Resizing: one `resize-window`, then the window's size
follows tmux's own rule again (the option is unset), so a person's own terminal joined later still fits. Both only
reach a session a page watches right now (its names were checked when the watch began), never a name from the
request.

Who may (server.py): the sign-in is the only check, from any computer (R4.1a; owner, on ORCH-743). The stream needs
the dashboard's sign-in (its cookie) or a frame pass, from the dashboard's own page; typing and resizing need the
person's own dashboard session with the typing setting on (watching only by default)."""

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
MAX_NUL = 32  # Ctrl+Space keys in one typing request: each is its own tmux call (ORCH-745)
PART = 1500  # characters per send-keys call: well inside one tmux message (16 KB) even when all are 4 bytes
COLS, ROWS = (10, 500), (3, 300)  # the sizes a resize may ask for
PANE = re.compile(r"%[0-9]{1,9}")
_FLAGS = (  # (tmux format flag, the sequence that turns the mode on in the page's terminal)
    ("bracket_paste_flag", "\x1b[?2004h"),
    ("keypad_cursor_flag", "\x1b[?1h"),
    ("keypad_flag", "\x1b="),
    ("mouse_standard_flag", "\x1b[?1000h"),
    ("mouse_button_flag", "\x1b[?1002h"),
    ("mouse_all_flag", "\x1b[?1003h"),
    ("mouse_sgr_flag", "\x1b[?1006h"),
    ("insert_flag", "\x1b[4h"),
)
_META = "@@orch #{cursor_x} #{cursor_y} #{pane_width} #{pane_height}"
# #{?flag,1,0}: a flag this tmux does not know reads 0 instead of nothing (bracket_paste_flag came in tmux 3.7;
# Ubuntu 24.04 ships 3.4)
_META += "".join(
    f" #{{?{f},1,0}}" for f in ("alternate_on", "cursor_flag", "wrap_flag", *(f for f, _ in _FLAGS))
)
_OCTAL = re.compile(rb"\\([0-7]{3})")
_LOCK = threading.Lock()
_WATCHES: dict[tuple[str, str], Watch] = {}
_PAGES = [0]


def screen_cmd(pane: str) -> bytes:
    """The two reads a joining page needs, as one line for the control client (two answer blocks)."""
    if not PANE.fullmatch(pane):
        raise ValueError(pane)
    return (
        f'capture-pane -e -N -p -S -{HISTORY} -t {pane} ; display-message -p -t {pane} "{_META}"\n'.encode()
    )


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


def draw(capture: bytes, meta: bytes) -> dict | None:
    """The bytes a terminal draws to show this capture (scrollback, visible lines), then the cursor and the modes
    the program turned on. None when the reads cannot be understood."""
    try:
        f = [int(x) for x in meta.decode().removeprefix("@@orch ").split()]
    except (UnicodeDecodeError, ValueError):
        return None
    if len(f) != 7 + len(_FLAGS):
        return None
    cx, cy, cols, rows, alt, cur, wrap = f[:7]
    lines = capture.decode(errors="replace").removesuffix("\n").split("\n")
    if alt:
        lines = lines[-rows:]  # an alternate screen has no scrollback of its own
    out = "\x1b[0m\x1b[H\x1b[2J\x1b[3J" + ("\x1b[?1049h\x1b[H" if alt else "")
    out += "\r\n".join(ln + "\x1b[0m" for ln in lines)
    out += "".join(on for (_, on), v in zip(_FLAGS, f[7:]) if v) + ("" if wrap else "\x1b[?7l")
    out += f"\x1b[{cy + 1};{cx + 1}H" + ("\x1b[?25h" if cur else "\x1b[?25l")
    return {"cols": cols, "rows": rows, "data": base64.b64encode(out.encode()).decode()}


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
        self.typing = (
            threading.Lock()
        )  # one typing, resize or claim at a time (who types is checked under it)
        self._asking = threading.Lock()  # one screen read written at a time
        self._owed: list[dict] = []  # screen reads waiting for their two answer blocks, oldest first
        self.typer: str | None = None  # the one page that types now (its stream's id), ORCH-883
        self.plain = False  # the plain terminal's shell: typing into it has its own switch (ORCH-261)
        self.ids: set[str] = set()  # the ids of the streams open now: only one of them may claim the typing
        self.own: tuple[int, int] | None = None  # the helper's own size before a page resized it, ORCH-881
        self.sized_by: str | None = None  # the page whose size the window has now (ORCH-1758)

    def start(self) -> bool:
        """Attach the control client; False when the session is gone or tmux cannot."""
        try:
            r = _tmux(self.sock, "display-message", "-p", "-t", f"={self.sess}:", "#{pane_id}")
            pane = r.stdout.strip()
            if r.returncode != 0 or not PANE.fullmatch(pane):
                return False
            self.pane = pane
            argv = [
                "tmux",
                "-L",
                self.sock,
                "-C",
                "attach-session",
                "-f",
                "ignore-size",
                "-t",
                f"={self.sess}:",
            ]
            self.proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_env()
            )
        except (OSError, subprocess.TimeoutExpired):
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
        block = None  # (begin's time and number, the request it answers or None, lines)
        try:
            for raw in iter(out.readline, b"") if out else ():
                line = raw.removesuffix(b"\n")
                if block is not None:
                    word = line.split(b" ")
                    if word[0] in (b"%end", b"%error") and word[1:3] == block[0]:
                        self._answered(block[1], word[0] == b"%end", b"\n".join(block[2]))
                        block = None
                    elif not self._notice(
                        line
                    ):  # tmux before 3.8 may send notices inside a block (issue 5458)
                        block[2].append(line)
                elif line.startswith(b"%begin "):
                    word = line.split(b" ")
                    # 1: a command this client sent (attach's own block says 0); tmux answers them in order
                    req = self._for_block() if word[3:4] == [b"1"] else None
                    block = (word[1:3], req, [])
                elif line.startswith(b"%exit"):
                    break
                else:
                    self._notice(line)
        except (OSError, ValueError):
            pass
        self.close()

    def _notice(self, line: bytes) -> bool:
        """Act on a pane's output or a size change; False when the line is neither."""
        if line.startswith(b"%output %"):
            _, pane, data = (line.split(b" ", 2) + [b""])[:3]
            if pane.decode(errors="replace") == self.pane:
                self._push("out", _unescape(data))
            return True
        if line.startswith((b"%window-pane-changed @", b"%session-window-changed $")):
            self.repane()  # another window or pane is shown now (a sign-in window opened or closed, ORCH-865)
            self.resized()
            return True
        if line.startswith(b"%layout-change @"):
            self.resized()
            return True
        return False

    def _for_block(self) -> dict | None:
        """The oldest screen read still owed an answer block; its first block marks where the capture stands."""
        with self.cond:
            req = next((r for r in self._owed if len(r["blocks"]) + r["open"] < 2), None)
            if req is not None:
                req["open"] += 1
                if req["at"] is None:
                    req["at"] = self.seq  # the capture sees everything up to here, nothing after
            return req

    def _answered(self, req: dict | None, ok: bool, text: bytes) -> None:
        if req is None:
            return
        with self.cond:
            req["open"] -= 1
            req["blocks"].append((ok, text))
            if len(req["blocks"]) == 2:
                if req in self._owed:
                    self._owed.remove(req)  # a read that timed out is still taken off here, by its own blocks
                req["done"].set()

    def repane(self) -> None:
        """Follow the session's current pane: the plain terminal shows a sign-in in a window of its own
        (ORCH-865) and its shell again once that window closed. The pages get the whole screen again."""
        try:
            r = _tmux(self.sock, "display-message", "-p", "-t", f"={self.sess}:", "#{pane_id}")
        except (OSError, subprocess.TimeoutExpired):
            return
        pane = r.stdout.strip()
        if r.returncode != 0 or not PANE.fullmatch(pane) or pane == self.pane:
            return
        self.pane, self.own = pane, None
        self._push("screen", b"")

    def resized(self) -> None:
        """Read the pane's size again; tell the pages when it changed."""
        try:
            r = _tmux(self.sock, "display-message", "-p", "-t", self.pane, "#{pane_width} #{pane_height}")
            size = tuple(int(x) for x in r.stdout.split())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        if len(size) == 2 and size != self.size:
            self.size = size  # type: ignore[assignment]
            self._push("size", json.dumps({"cols": size[0], "rows": size[1]}).encode())

    def screen(self) -> tuple[dict, int] | None:
        """(the screen to draw, the seq it shows everything up to). None: the session is gone or did not answer."""
        req = {"done": threading.Event(), "at": None, "blocks": [], "open": 0}
        with self._asking:  # one line written at a time, in the order of self._owed
            if self.ended or self.proc is None or self.proc.stdin is None:
                return None
            with self.cond:
                self._owed.append(req)
            try:
                self.proc.stdin.write(screen_cmd(self.pane))
                self.proc.stdin.flush()
            except (OSError, ValueError):
                with self.cond:
                    self._owed.remove(req)
                return None
        if not req["done"].wait(termsession.TIMEOUT):
            return None  # stays owed: its late blocks still go to it, never to the next read
        with self.cond:
            (ok1, capture), (ok2, meta), at = *req["blocks"], req["at"]
        snap = draw(capture, meta) if ok1 and ok2 and at is not None else None
        if snap is None:
            return None
        self.size = (snap["cols"], snap["rows"])
        return snap, at

    def since(self, seq: int) -> tuple[list[tuple[int, str, bytes]], bool]:
        """What came after seq, and whether the page fell so far behind that it needs the screen again."""
        with self.cond:
            if self.chunks and self.chunks[0][0] > seq + 1:
                return [], True
            return [c for c in self.chunks if c[0] > seq], False

    def give_back(self) -> None:
        """Typing ended: the helper's window goes back to the size it had before a page resized it (ORCH-881), so
        it does not keep drawing a cramped screen for every later viewer."""
        own, self.own = self.own, None
        self.sized_by = None
        if own is None or not self.pane:
            return
        try:
            _tmux(
                self.sock, "resize-window", "-t", self.pane, "-x", str(own[0]), "-y", str(own[1]), ";",
                "set-window-option", "-u", "-t", self.pane, "window-size",
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return
        self.resized()

    def release(self, page: str) -> None:
        """This page stops typing (its switch, or it left): nobody types. A page that left gives the window its own
        size back; a page that still watches keeps it, since a watching page sizes the window too (ORCH-1758)."""
        with self.typing:
            if self.typer != page:
                return
            self.typer = None
            self._push("typer", b"")
            with _LOCK:
                watches = page in self.ids
            if not watches:
                self.give_back()

    def close(self) -> None:
        with self.cond:
            if self.ended:
                return
            self.ended = True
            self.cond.notify_all()
        with self.typing:
            self.typer = None
            self.give_back()  # also when the last page left without turning typing off
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


def join(root: Path, orch_bin: str | None, tid: str, page: str = "") -> Watch | str:
    """Start watching the ticket's live session, or the plain terminal's shell (or join the watch that is on).
    The reason when there is none: 'none', 'oneshot', 'notmux' (as termsession.ref), 'busy' (too many pages)."""
    _reap()
    r, shell = termsession.ref_kind(root, orch_bin, tid, plain=True)
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
        w.plain = w.plain or shell  # once seen as the plain terminal, its own switch counts (never back)
        w.pages += 1
        _PAGES[0] += 1
        if page:
            w.ids.add(page)
    if fresh and not w.start():
        leave(w)
        w.close()
        return "none"
    return w


def leave(w: Watch, page: str | None = None) -> None:
    if page:
        with _LOCK:
            w.ids.discard(page)  # a late claim of this page is refused from now on
        w.release(page)  # the page that typed left: the next one may type, the window gets its own size
        # the page whose size the window has left: its own size back, and the pages hear nobody types, so a page
        # still watching sizes it again (ORCH-1758)
        with w.typing:
            if w.sized_by == page:
                w.give_back()
                w._push("typer", b"")
    with _LOCK:
        w.pages = max(0, w.pages - 1)
        _PAGES[0] = max(0, _PAGES[0] - 1)
        if w.pages == 0:
            w.left_at = time.monotonic()
    t = threading.Timer(LINGER + 0.1, _reap)
    t.daemon = True
    t.start()


def watching(tid: str) -> Watch | None:
    """The open watch of this ticket's session, if a page watches it now."""
    with _LOCK:
        for w in _WATCHES.values():
            if w.sess == tid and not w.ended and w.pages > 0:
                return w
    return None


OTHER = "Another page is typing into this screen now."


def _refused(w: Watch, may) -> str:
    """may(plain) -> '' or the refusal text: the typing setting, asked for THIS watch (the plain terminal has its
    own switch, ORCH-261), under its typing lock so it is the watch that takes the keys."""
    return may(w.plain) if may is not None else ""


def claim(tid: str, page, on, may=None) -> tuple[int, str]:
    """A page turns its typing on (it becomes the one page that types; the page that typed before hears it and goes
    back to watching) or off (ORCH-883)."""
    if not isinstance(page, str) or not 0 < len(page) <= 64 or not isinstance(on, bool):
        return 400, "That request could not be read."
    w = watching(tid)
    if w is None:
        return 409, "There is no live session to type into."
    if not on:
        w.release(page)
        return 200, "{}"
    with w.typing:
        no = _refused(w, may)
        if no:
            return 403, no
        with _LOCK:
            if (
                page not in w.ids
            ):  # only a page whose stream is open now (a claim after it left changes nothing)
                return 409, "There is no live session to type into."
        if w.typer != page:
            w.typer = page
            w._push("typer", page.encode())
    return 200, "{}"


def _typer_ok(w: Watch, page) -> bool:
    """Only the page that turned typing on last types or resizes; with nobody typing, any page of the person."""
    return w.typer is None or page == w.typer


def type_text(tid: str, data, page: str | None = None, may=None) -> tuple[int, str]:
    """Send what the page typed (raw terminal input: text, control keys, escape sequences, a bracketed paste)."""
    if not isinstance(data, str) or not 0 < len(data) <= MAX_INPUT or data.count("\x00") > MAX_NUL:
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
    with w.typing:
        no = _refused(w, may)
        if no:
            return 403, no
        if not _typer_ok(
            w, page
        ):  # checked under the lock: a claim cannot come between the check and the keys
            return 409, OTHER
        try:
            for args in calls:
                if _tmux(w.sock, "send-keys", "-t", w.pane, *args).returncode != 0:
                    return 502, "The session did not take that."
        except (OSError, subprocess.TimeoutExpired):
            return 502, "The session did not answer."
    return 200, "{}"


def resize(tid: str, cols, rows, page: str | None = None, may=None) -> tuple[int, str]:
    """Give the helper's window this size: the page that types, or with nobody typing any watching page (its box,
    ORCH-1758; the last one opened or resized wins, the others draw smaller). Its own size comes back when the last
    page left (close) or the page that typed left (release)."""
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in (cols, rows)):
        return 400, "That request could not be read."
    if not (COLS[0] <= cols <= COLS[1] and ROWS[0] <= rows <= ROWS[1]):
        return 400, "That size is out of range."
    w = watching(tid)
    if w is None:
        return 409, "There is no live session to resize."
    with w.typing:  # with the claim and give_back: the saved own size is never one a page made
        no = _refused(w, may)
        if no:
            return 403, no
        if not _typer_ok(w, page):
            return 409, OTHER
        if w.own is None and w.size != (0, 0):
            w.own = w.size  # given back when typing ends (give_back)
        try:
            r = _tmux(
                w.sock, "resize-window", "-t", w.pane, "-x", str(cols), "-y", str(rows), ";",
                "set-window-option", "-u", "-t", w.pane, "window-size",
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return 502, "The session did not answer."
        if r.returncode != 0:
            return 502, "The session did not take that."
        w.sized_by = page or None
        w.resized()
    return 200, "{}"


def stream(w: Watch, write, gone, ping: float = 15.0, page: str = "") -> None:
    """Server-sent events to one page until the session ends or the page leaves: `screen` (the whole screen,
    first and after falling behind), `out` (bytes, base64), `size`, `typing` {"by": "you" | "other" | "none"} (who
    types now, ORCH-883), then `end`. write(bytes) sends;
    gone() says the page closed or may no longer watch (asked about once a turn, also while output flows). Raises what write raises (the server ends the request then)."""

    def ev(name: str, data: str) -> None:
        write(f"event: {name}\ndata: {data}\n\n".encode())

    def screen() -> int | None:
        got = w.screen()
        if got is None:
            ev("end", json.dumps({"state": "none"}))
            return None
        ev("screen", json.dumps(got[0]))
        t = w.typer  # who types now, also for a page that joins (or catches up) after the claim
        if t:
            ev("typing", json.dumps({"by": "you" if t == page else "other"}))
        return got[1]

    seq = screen()
    if seq is None:
        return
    last = time.monotonic()
    while True:
        with w.cond:
            if w.seq == seq and not w.ended:
                w.cond.wait(timeout=1.0)
            ended = w.ended and w.seq == seq
        if ended:
            ev("end", json.dumps({"state": "none"}))
            return
        # asked on every turn, also while output flows: a revoked sign-in ends the stream (ORCH-745)
        if gone():
            return
        got, behind = w.since(seq)
        if behind:
            seq = screen()
            if seq is None:
                return
            last = time.monotonic()
            continue
        redraw = False
        for s, kind, payload in got:
            seq = s
            if kind == "screen":  # another pane is shown now: the whole screen again
                redraw = True
                break
            if kind == "size":
                ev("size", payload.decode())
            elif kind == "typer":
                by = "none" if not payload else "you" if payload.decode() == page else "other"
                ev("typing", json.dumps({"by": by}))
            else:
                ev("out", base64.b64encode(payload).decode())
            last = time.monotonic()
        if redraw:
            seq = screen()
            if seq is None:
                return
            last = time.monotonic()
            continue
        if not got and time.monotonic() - last >= ping:
            write(b": ping\n\n")
            last = time.monotonic()
