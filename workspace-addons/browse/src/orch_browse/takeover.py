"""Take over and give back (ORCH-1495): who drives the ticket's browser, and the person's input.

The lock (Control) has four states:

- helper     the helper's commands run (the default)
- finishing  a person pressed Take over; the helper's running step ends and the page settles first (Cancel stops
             the step and reloads the page instead)
- person     one person drives: only the page that took over (its stream's page id) may send input
- paused     the person's page went away, its lease ran out or its sign-in ended: nobody types, the helper keeps
             waiting. Only Give back (or Stop) lets the helper go on; it never resumes by itself.

Every change of owner bumps the epoch. Input names the epoch it was made for and the broker checks it again right
before each event goes to the browser, so input made before a change is dropped, never replayed. Helper commands
that arrived before a change come back "look again" instead of running on a page a person changed.

The input part is pure: it checks one batch of events from the dashboard (fixed kinds, fixed key names, finite
numbers inside the picture, bounded text) and turns them into Chrome DevTools Input.* calls. Typed text is never
logged and never kept here: it goes straight to the browser.
"""

from __future__ import annotations

import math
import os
import threading
import time

LEASE_SECONDS = 300  # the holder's page renews it (every 20 s); a page that stops renewing loses control
ASK_SECONDS = int(os.environ.get("ORCH_BROWSE_ASK_SECONDS") or 30 * 60)  # ask-person: "Nobody took over"
WAIT_SECONDS = 30 * 60  # a helper command waits this long for the browser to be given back
MAX_EVENTS = 40  # events in one batch
TEXT_MAX = 2000  # characters of typed or pasted text in one batch
RATE = 60.0  # events per second (pressing and releasing always get through)
BURST = 60.0
COORD_MAX = 10_000
DELTA_MAX = 5_000

STATES = ("helper", "finishing", "person", "paused")

# Person-facing and helper-facing words (one place, the owner approves them later).
LOOK_AGAIN = "The browser changed while a person used it; look again (orch browse look)."
CANCELLED = (
    "A person took over and stopped this step (it may be half done). Look again once they give it back."
)
STILL_HELD = "A person still has the browser; nothing ran. Try again later."
NOBODY = "Nobody took over."
WAITS = "A person is using the browser; your step waits."
NOT_YOURS = "Another page has control of this browser."
GIVEN_BACK = (
    "Given back to the helper. Its browser starts again on a fresh page{where}. The helper can see what the site "
    "itself shows after you give back (for example your sign-in or recent searches); orch kept nothing you typed."
)
STALE = "The browser changed hands; that was not sent."


def not_picked(site: str) -> str:
    """The person's card when a send to a listed site stopped because the site is not picked (ORCH-1779)."""
    return (
        f"What you sent to {site} did not leave the browser: {site} is not picked under \u201cForms may go to\u201d. "
        "Allow it, then send again."
    )


def stopped_line(site: str, n: int) -> str:
    """The helper's next answer: sends of the person's hold that stopped because no site was picked (host only)."""
    what = "1 send" if n == 1 else f"{n} sends"
    return (
        f"While a person had the browser, {what} to {site} stopped: {site} was not picked under "
        "\u201cForms may go to\u201d. Ask the person to take over again, allow it and send again."
    )


def used_line(start: float, end: float) -> str:
    """The helper's next answer after a person gave the browser back (local clock times)."""
    a, b = time.strftime("%H:%M", time.localtime(start)), time.strftime("%H:%M", time.localtime(end))
    return f"A person used the browser from {a} to {b}; nothing typed was kept by orch."


def origin_of(url: str) -> tuple[str, str]:
    """(origin, host) the give back reopens: scheme://host[:port]/ from the host name only, never a user or password
    in the address, never a path, query or fragment. ('', '') for anything but http(s)."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url or "")
        host, port = parts.hostname, parts.port
    except ValueError:
        return "", ""
    if parts.scheme not in ("http", "https") or not host:
        return "", ""
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}{f':{port}' if port else ''}/", host


class Refused(Exception):
    """A plain-words refusal for the person's page."""


class Control:
    """The lock. Thread-safe; the broker makes every change on its event loop so input and changes are ordered."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.state = "helper"
        self.holder: str | None = None  # the page id of the one stream that took over
        self.epoch = 0
        self.lease_until = 0.0
        self.since = 0.0  # when the person got control (for the helper's "used" line)
        self.asking: dict | None = (
            None  # {"why", "at"}: the helper asked for a person (separate from control)
        )
        self.used: list[tuple[float, float]] = []  # person periods the helper has not been told about yet
        # Owner pick A on ORCH-1495 q1: the ONE site (an entry of the ticket's list) the person ticked; sends to it
        # leave the browser only while that person drives. Cleared on every change of owner but finishing -> person.
        self.send_site: str | None = None

    # -- reading

    def snapshot(self, page: str | None = None) -> dict:
        with self.lock:
            out = {"state": self.state, "epoch": self.epoch, "mine": bool(page) and page == self.holder}
            if self.since and self.state in ("person", "paused"):
                out["since"] = self.since
            if self.asking:
                out["asking"] = self.asking["why"]
            if self.send_site and self.state in ("finishing", "person"):
                out["send_site"] = self.send_site
            return out

    def may_send_to(self, host: str) -> str | None:
        """The ticked site when a send to host may leave now (a person drives and host is that site or a part of
        it), else None. The caller checks the site is still on the ticket's list."""
        h = (host or "").strip().lower().rstrip(".")
        with self.lock:
            s = self.send_site
            if self.state != "person" or not s or not h:
                return None
            return s if h == s or h.endswith("." + s) else None

    def helper_may_run(self) -> bool:
        with self.lock:
            return self.state == "helper"

    def take_used(self) -> list[str]:
        """The "a person used the browser" lines, once each."""
        with self.lock:
            out, self.used = [used_line(a, b) for a, b in self.used], []
            return out

    # -- changes (each returns the new snapshot or raises Refused)

    def _bump(self, state: str, holder: str | None) -> None:
        if not (self.state == "finishing" and state == "person" and holder == self.holder):
            self.send_site = None  # a new owner (or none) never inherits the permission
        self.state, self.holder = state, holder
        self.epoch += 1

    def _check(self, page, epoch) -> None:
        if not isinstance(page, str) or not 0 < len(page) <= 64:
            raise Refused("That page is not watching this browser.")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch != self.epoch:
            raise Refused(STALE)

    def take(self, page: str, epoch: int) -> str:
        """Take over (from helper or paused). Returns the new state: 'finishing' until the helper's step ended."""
        with self.lock:
            self._check(page, epoch)
            if self.state == "helper":
                self._bump("finishing", page)
                self.lease_until = self.clock() + LEASE_SECONDS
                return self.state
            if self.state == "paused":  # someone takes over again: straight to them (the helper still waits)
                self._bump("person", page)
                self.lease_until = self.clock() + LEASE_SECONDS
                return self.state
            if self.holder == page:
                return self.state
            raise Refused(NOT_YOURS)

    def allow_sends(self, page: str, epoch: int, site: str | None, sites: list[str]) -> None:
        """The holder ticks the one site sends may go to while they drive (None = no site). site must be an entry
        of the ticket's list exactly as stored (sites); the epoch does not change."""
        with self.lock:
            self._check(page, epoch)
            if self.holder != page or self.state not in ("finishing", "person"):
                raise Refused(NOT_YOURS)
            if site is not None and site not in sites:
                raise Refused("Pick a site from this ticket's list.")
            self.send_site = site

    def renew(self, page: str, epoch: int) -> str:
        with self.lock:
            self._check(page, epoch)
            if self.holder != page or self.state not in ("finishing", "person"):
                raise Refused(NOT_YOURS)
            if self.clock() > self.lease_until:  # too late: the lease is over, never brought back
                self.lost(page, "lease")
                raise Refused("Your time in control ran out. Take over again.")
            self.lease_until = self.clock() + LEASE_SECONDS
            return self.state

    def settled(self, epoch: int) -> bool:
        """The helper's step ended and the page settled: finishing -> person (only for the same take-over)."""
        with self.lock:
            if self.state != "finishing" or self.epoch != epoch:
                return False
            self._bump("person", self.holder)
            self.since = self.clock()
            return True

    def cancel(self, page: str, epoch: int) -> None:
        """The person's Cancel while finishing: the broker stops the step; then settled() as usual."""
        with self.lock:
            self._check(page, epoch)
            if self.state != "finishing" or self.holder != page:
                raise Refused("There is no step to cancel.")

    def give(self, page: str, epoch: int) -> bool:
        """Give back. The holder may (finishing or person); while paused any watching page may. True = changed."""
        with self.lock:
            self._check(page, epoch)
            if self.state == "helper":
                return False
            if self.state != "paused" and self.holder != page:
                raise Refused(NOT_YOURS)
            if self.since:
                self.used.append((self.since, self.clock()))
            self.since = 0.0
            self._bump("helper", None)
            self.lease_until = 0.0
            return True

    def lost(self, page: str | None = None, why: str = "") -> bool:
        """The holder's page went away (or its lease ran out, or its sign-in ended). person -> paused; a take-over
        that never got control (finishing) is simply dropped: the person never typed, the helper goes on."""
        with self.lock:
            if page is not None and page != self.holder:
                return False
            if self.state == "person":
                self._bump("paused", None)
                return True
            if self.state == "finishing":
                self._bump("helper", None)
                return True
            return False

    def expired(self) -> bool:
        with self.lock:
            if self.state in ("finishing", "person") and self.clock() > self.lease_until:
                return self.lost(self.holder, "lease")
            return False

    def ask(self, why: str) -> None:
        with self.lock:
            self.asking = {"why": " ".join(str(why).split())[:300], "at": self.clock()}

    def unask(self) -> None:
        with self.lock:
            self.asking = None


# ---------------------------------------------------------------------------------------------- the input


class Rate:
    """A token bucket: RATE events a second, bursts of BURST."""

    def __init__(self, clock=time.monotonic, rate: float = RATE, burst: float = BURST):
        self.clock, self.rate, self.burst = clock, rate, burst
        self.tokens, self.at = burst, clock()

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


# key name -> (code, windowsVirtualKeyCode, text sent with keyDown)
KEYS = {
    "Enter": ("Enter", 13, "\r"),
    "Tab": ("Tab", 9, ""),
    "Backspace": ("Backspace", 8, ""),
    "Delete": ("Delete", 46, ""),
    "Escape": ("Escape", 27, ""),
    "ArrowLeft": ("ArrowLeft", 37, ""),
    "ArrowUp": ("ArrowUp", 38, ""),
    "ArrowRight": ("ArrowRight", 39, ""),
    "ArrowDown": ("ArrowDown", 40, ""),
    "Home": ("Home", 36, ""),
    "End": ("End", 35, ""),
    "PageUp": ("PageUp", 33, ""),
    "PageDown": ("PageDown", 34, ""),
}
# Shortcuts with Ctrl or Cmd: letter -> editing command (no clipboard: nothing is read from the site)
SHORTCUTS = {"a": ["selectAll"], "z": ["undo"], "y": ["redo"]}
BUTTONS = {"left": 1, "right": 2, "middle": 4}
MOUSE = {"move": "mouseMoved", "down": "mousePressed", "up": "mouseReleased", "wheel": "mouseWheel"}
MOD_ALT, MOD_CTRL, MOD_META, MOD_SHIFT = 1, 2, 4, 8


def _num(v, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise Refused("That input could not be read.")
    return float(v)


def check_batch(events, fw: int, fh: int) -> list[dict]:
    """The batch as clean events, or Refused. Coordinates are picture pixels of a fw x fh picture; one outside it
    is refused (never moved to the edge, which could click something the person did not point at)."""
    if not isinstance(events, list) or not 0 < len(events) <= MAX_EVENTS:
        raise Refused("That input could not be read.")
    if not fw or not fh:
        raise Refused("There is no picture yet; wait a moment.")
    out, text = [], 0
    for ev in events:
        if not isinstance(ev, dict):
            raise Refused("That input could not be read.")
        t = ev.get("t")
        if t in MOUSE:
            want = {"t", "x", "y"} | ({"button"} if t in ("down", "up") else set())
            want |= {"count"} if t == "down" else set()
            want |= {"dx", "dy"} if t == "wheel" else set()
            if set(ev) - {"mod"} != want:
                raise Refused("That input could not be read.")
            x, y = _num(ev["x"], -COORD_MAX, COORD_MAX), _num(ev["y"], -COORD_MAX, COORD_MAX)
            if not (0 <= x < fw and 0 <= y < fh):
                raise Refused("That was outside the picture.")
            clean = {"t": t, "x": x, "y": y, "mod": int(_num(ev.get("mod", 0), 0, 15))}
            if t in ("down", "up"):
                if ev["button"] not in BUTTONS:
                    raise Refused("That input could not be read.")
                clean["button"] = ev["button"]
            if t == "down":
                clean["count"] = int(_num(ev["count"], 1, 3))
            if t == "wheel":
                clean["dx"], clean["dy"] = (
                    _num(ev["dx"], -DELTA_MAX, DELTA_MAX),
                    _num(ev["dy"], -DELTA_MAX, DELTA_MAX),
                )
            out.append(clean)
        elif t == "key":
            if set(ev) - {"mod"} != {"t", "type", "key"} or ev["type"] not in ("down", "up"):
                raise Refused("That input could not be read.")
            mod = int(_num(ev.get("mod", 0), 0, 15))
            key = ev["key"]
            if key in KEYS:
                pass
            elif isinstance(key, str) and key.lower() in SHORTCUTS and mod & (MOD_CTRL | MOD_META):
                key = key.lower()
            else:
                raise Refused("That key is not sent to the browser.")
            out.append({"t": "key", "type": ev["type"], "key": key, "mod": mod})
        elif t in ("text", "paste"):
            if set(ev) != {"t", "text"} or not isinstance(ev["text"], str) or not ev["text"]:
                raise Refused("That input could not be read.")
            s = "".join(ch for ch in ev["text"] if ch in "\n\t" or ord(ch) >= 32)
            text += len(s)
            if text > TEXT_MAX:
                raise Refused(f"At most {TEXT_MAX} characters at a time.")
            if s:
                out.append({"t": t, "text": s})
        else:
            raise Refused("That input could not be read.")
    return out


def to_cdp(ev: dict, fw: int, fh: int, vw: int, vh: int, buttons: int = 0) -> tuple[str, dict]:
    """One clean event -> (Chrome DevTools method, params). Picture pixels become page pixels (vw x vh)."""
    t = ev["t"]
    if t in MOUSE:
        p = {
            "type": MOUSE[t],
            "x": round(ev["x"] * vw / fw, 2),
            "y": round(ev["y"] * vh / fh, 2),
            "modifiers": ev["mod"],
        }
        if t == "wheel":
            p.update(button="none", deltaX=ev["dx"], deltaY=ev["dy"])
        elif t == "move":
            p.update(button="none", buttons=buttons)
        else:
            p.update(button=ev["button"], buttons=buttons, clickCount=ev.get("count", 1))
        return "Input.dispatchMouseEvent", p
    if t == "key":
        if ev["key"] in KEYS:
            code, vk, text = KEYS[ev["key"]]
            p = {"key": ev["key"], "code": code, "windowsVirtualKeyCode": vk, "modifiers": ev["mod"]}
            if ev["type"] == "down":
                p["type"] = "keyDown" if text else "rawKeyDown"
                if text and not ev["mod"] & (MOD_CTRL | MOD_META | MOD_ALT):
                    p["text"] = text
            else:
                p["type"] = "keyUp"
            return "Input.dispatchKeyEvent", p
        letter = ev["key"]
        p = {
            "key": letter,
            "code": "Key" + letter.upper(),
            "windowsVirtualKeyCode": ord(letter.upper()),
            "modifiers": ev["mod"],
            "type": "rawKeyDown" if ev["type"] == "down" else "keyUp",
        }
        if ev["type"] == "down":
            p["commands"] = SHORTCUTS[letter]
        return "Input.dispatchKeyEvent", p
    return "Input.insertText", {"text": ev["text"]}


class Pressed:
    """Buttons and keys a person holds down, so every way out (give back, lost page, Stop) releases them."""

    def __init__(self):
        self.buttons: dict[str, tuple[float, float]] = {}  # button -> last page position
        self.keys: dict[str, int] = {}  # key -> modifiers
        self.at = (0.0, 0.0)

    def mask(self) -> int:
        return sum(BUTTONS[b] for b in self.buttons)

    def note(self, ev: dict, method: str, params: dict) -> None:
        if method == "Input.dispatchMouseEvent":
            self.at = (params["x"], params["y"])
            if ev["t"] == "down":
                self.buttons[ev["button"]] = self.at
            elif ev["t"] == "up":
                self.buttons.pop(ev["button"], None)
        elif method == "Input.dispatchKeyEvent":
            if ev["type"] == "down":
                self.keys[ev["key"]] = ev["mod"]
            else:
                self.keys.pop(ev["key"], None)

    def releases(self) -> list[tuple[str, dict]]:
        """The calls that let go of everything held, then forgets it."""
        out = []
        for b in list(self.buttons):
            x, y = self.at
            out.append(
                (
                    "Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": x, "y": y, "button": b, "buttons": 0, "clickCount": 1},
                )
            )
        for k in list(self.keys):
            if k in KEYS:
                code, vk, _ = KEYS[k]
            else:
                code, vk = "Key" + k.upper(), ord(k.upper())
            out.append(
                (
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "key": k, "code": code, "windowsVirtualKeyCode": vk},
                )
            )
        self.buttons, self.keys = {}, {}
        return out
