"""`orch shot`: screenshots of a page or file at one or more widths, with a browser that never touches the
keychain. Helpers use this instead of writing their own script, so no "Chromium Safe Storage" password
window appears on the person's screen."""

from __future__ import annotations

import base64
import glob
import json
import os
import queue
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from orch.errors import Refused

# The two options that keep the macOS keychain (and its password window) out of it, plus a clean headless run.
SAFE_FLAGS = (
    "--headless=new",
    "--use-mock-keychain",
    "--password-store=basic",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--hide-scrollbars",
)
DEFAULT_WIDTHS = (1280, 1920, 390)
QUIET_SEC = 0.7  # no new network event for this long = the page has settled
_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
)
# Windows: Chrome first, then Edge (every Windows 11 has it), each under Program Files, Program Files (x86)
# and the person's own LocalAppData (a per-user install).
_WIN_ROOTS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
_WIN_APPS = (
    ("Google", "Chrome", "Application", "chrome.exe"),
    ("Microsoft", "Edge", "Application", "msedge.exe"),
    ("Chromium", "Application", "chrome.exe"),
)


def _windows_candidates() -> list[str]:
    roots = [os.environ.get(r) for r in _WIN_ROOTS]
    found = [os.path.join(root, *app) for app in _WIN_APPS for root in roots if root]
    if local := os.environ.get("LOCALAPPDATA"):
        found.append(os.path.join(local, "ms-playwright", "chromium-*", "chrome-win*", "chrome.exe"))
    return found


def add_parsers(sub, common) -> None:
    x = sub.add_parser(
        "shot", parents=[common], help="screenshots of a page or file, with no keychain window"
    )
    x.add_argument("target", help="an address (http://...) or an HTML file")
    x.add_argument("--width", default=",".join(map(str, DEFAULT_WIDTHS)), metavar="W[,W...]")
    x.add_argument("--height", type=int, metavar="PX", help="default 800 (1080 at 1920, 844 under 500 wide)")
    x.add_argument("--out", default=".", metavar="FOLDER", help="folder for the pictures")
    x.add_argument("--name", default="shot", help="start of each file name")
    x.add_argument("--wait", type=int, default=8, metavar="SEC", help="longest wait for the page to settle")
    x.add_argument(
        "--page",
        metavar="NAME[=PART][,...]",
        help="several pages of one site in one run, after the address's # (e.g. home,tickets,"
        "ticket=ticket/DM1-2); files are named <name>-<page>-<width>.png",
    )


def find_browser() -> str:
    env = os.environ.get("ORCH_SHOT_BROWSER")
    if env and os.access(env, os.X_OK):
        return env
    windows = os.name == "nt"
    for c in _windows_candidates() if windows else _CANDIDATES:
        for p in sorted(glob.glob(os.path.expanduser(c))):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    if windows:
        # No PATH search here: on Windows it looks in the current folder first, so a chrome.exe inside a
        # downloaded project would be started. Chrome and Edge install into the folders above.
        raise Refused("No Chrome or Edge found. Set ORCH_SHOT_BROWSER to its path.")
    for n in ("google-chrome", "chromium", "chromium-browser"):
        if w := shutil.which(n):
            return w
    raise Refused("No Chrome or Chromium found. Set ORCH_SHOT_BROWSER to its path.")


def parse_widths(text: str) -> list[int]:
    try:
        w = [int(p) for p in text.split(",") if p.strip()]
    except ValueError:
        raise Refused(f"'{text}' is not a list of widths like 1280,390.") from None
    if not w or any(not 200 <= n <= 4000 for n in w):
        raise Refused("Widths must be between 200 and 4000.")
    return w


def target_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    p = Path(target).expanduser()
    if not p.is_file():
        raise Refused(f"No such file: {target}")
    return p.resolve().as_uri()


def command(browser: str, profile: str, width: int, height: int) -> list[str]:
    """The browser start: keychain-safe, driven over a pipe (fd 3 in, fd 4 out; on Windows two inherited
    handles named by --remote-debugging-io-pipes, added by _launch), no page yet."""
    return [
        browser,
        *SAFE_FLAGS,
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--remote-debugging-pipe",
        "about:blank",
    ]


class _Pipe:
    """The DevTools protocol over --remote-debugging-pipe: JSON messages ended by a NUL byte."""

    def __init__(self, write_fd: int, read_fd: int):
        self.w, self.r = write_fd, read_fd
        self.buf = b""
        self.next_id = 0
        self.events: list[dict] = []
        # select() works only on sockets on Windows: there one thread reads the pipe into a queue.
        self.chunks: queue.Queue[bytes] | None = None
        if os.name == "nt":
            self.chunks = queue.Queue()
            threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.chunks is not None
        try:
            while chunk := os.read(self.r, 1 << 20):
                self.chunks.put(chunk)
        except OSError:
            pass
        self.chunks.put(b"")  # the browser closed its end

    def _chunk(self, left: float) -> bytes:
        if self.chunks is not None:
            try:
                return self.chunks.get(timeout=left)
            except queue.Empty:
                raise TimeoutError("the browser did not answer in time") from None
        if not select.select([self.r], [], [], left)[0]:
            raise TimeoutError("the browser did not answer in time")
        return os.read(self.r, 1 << 20)

    def _read(self, deadline: float) -> dict:
        while b"\0" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("the browser did not answer in time")
            chunk = self._chunk(left)
            if not chunk:
                if self.chunks is not None:
                    self.chunks.put(b"")  # stay at the end for the next read
                raise EOFError
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 30):
        self.next_id += 1
        msg: dict = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.w, json.dumps(msg).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            m = self._read(deadline)
            if m.get("id") == self.next_id:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})
            if "method" in m:
                self.events.append(m)

    def wait_event(self, method: str, session: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            for i, m in enumerate(self.events):
                if m.get("method") == method and m.get("sessionId") == session:
                    del self.events[i]
                    return True
            try:
                m = self._read(deadline)
            except TimeoutError:
                return False
            if "method" in m:
                self.events.append(m)

    def settle(self, session: str, quiet: float, deadline: float) -> None:
        """Return once no network event came for `quiet` seconds, or at the deadline."""
        self.events = [m for m in self.events if m.get("sessionId") != session]
        last = time.monotonic()
        while True:
            now = time.monotonic()
            if now - last >= quiet or now >= deadline:
                return
            try:
                m = self._read(min(deadline, last + quiet))
            except TimeoutError:
                continue
            if m.get("sessionId") == session and str(m.get("method", "")).startswith("Network."):
                last = time.monotonic()


PAGE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
PAGE_PART = re.compile(r"[A-Za-z0-9/_.~-]{1,120}")


def parse_pages(text: str | None) -> list[tuple[str, str]]:
    """--page home,ticket=ticket/DM1-2 -> [(home, home), (ticket, ticket/DM1-2)]: a file name part and what
    goes after the address's #."""
    if not text:
        return []
    pages = []
    for item in (p.strip() for p in text.split(",")):
        if not item:
            continue
        name, _, part = item.partition("=")
        part = part or name
        if not PAGE_NAME.fullmatch(name) or not PAGE_PART.fullmatch(part):
            raise Refused(f"'{item[:60]}' is not a page like home or ticket=ticket/DM1-2.")
        if any(n == name for n, _ in pages):
            raise Refused(f"The page name '{name}' is given twice.")
        pages.append((name, part))
    return pages


def page_url(url: str, part: str) -> str:
    """The site's address with the page after its #; a sign-in link (#launch=...) is spent by then."""
    return url.split("#", 1)[0] + "#" + part


STILL_LOADING = "the page was still loading"
BUSY_JS = "!!document.querySelector('[aria-busy=\"true\"]')"


def _busy(pipe, session: str) -> bool:
    r = pipe.call("Runtime.evaluate", {"expression": BUSY_JS, "returnByValue": True}, session=session)
    return bool((r.get("result") or {}).get("value"))


def capture(pipe: _Pipe, url: str, width: int, height: int, wait: int) -> bytes:
    """One picture in a fresh tab. The viewport is set through the protocol, not the window: new
    headless Chrome never makes a window narrower than 500, so a 390 window was laid out 500 wide
    and cut at the right (ORCH-219)."""
    target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
    s = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
    try:
        pipe.call("Page.enable", session=s)
        pipe.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
            session=s,
        )
        pipe.call("Network.enable", session=s)
        pipe.call("Page.navigate", {"url": url}, session=s)
        # Wait for the load, then until the page has fetched nothing new for a moment (it renders
        # after its own requests), never longer than --wait in all.
        deadline = time.monotonic() + wait
        pipe.wait_event("Page.loadEventFired", s, wait)
        pipe.settle(s, QUIET_SEC, deadline)
        # A page that says it is still loading (aria-busy) is waited for; still busy at the end of --wait:
        # no picture, never one of a loading shape (CI pictures on a slow runner, ORCH-312).
        while _busy(pipe, s):
            if time.monotonic() >= deadline:
                raise TimeoutError(STILL_LOADING)
            time.sleep(0.2)
            pipe.settle(s, QUIET_SEC, min(deadline, time.monotonic() + QUIET_SEC))
        shot = pipe.call("Page.captureScreenshot", {"format": "png"}, session=s, timeout=60)
        return base64.b64decode(shot["data"])
    finally:
        try:
            pipe.call("Target.closeTarget", {"targetId": target}, timeout=10)
        except Exception:
            pass


def _height(width: int, height: int | None) -> int:
    return height or (844 if width < 500 else 1080 if width >= 1900 else 800)


def _launch_windows(cmd: list[str]) -> tuple[subprocess.Popen, _Pipe]:
    """Windows has no fds 3 and 4 for a child: hand the browser the two pipe ends as inherited handles and
    name them with --remote-debugging-io-pipes. Only these two handles are inherited (handle_list)."""
    import msvcrt

    to_browser_r, to_browser_w = os.pipe()
    from_browser_r, from_browser_w = os.pipe()
    h_in, h_out = msvcrt.get_osfhandle(to_browser_r), msvcrt.get_osfhandle(from_browser_w)
    os.set_handle_inheritable(h_in, True)
    os.set_handle_inheritable(h_out, True)
    info = subprocess.STARTUPINFO()
    info.lpAttributeList = {"handle_list": [h_in, h_out]}
    at = cmd.index("--remote-debugging-pipe") + 1
    cmd = [*cmd[:at], f"--remote-debugging-io-pipes={h_in},{h_out}", *cmd[at:]]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=info,
            close_fds=True,
        )
    except BaseException:
        _close(to_browser_w)
        _close(from_browser_r)
        raise
    finally:
        _close(to_browser_r)
        _close(from_browser_w)
    return proc, _Pipe(to_browser_w, from_browser_r)


def _launch(cmd: list[str]) -> tuple[subprocess.Popen, _Pipe]:
    if os.name == "nt":
        return _launch_windows(cmd)
    to_browser_r, to_browser_w = os.pipe()
    from_browser_r, from_browser_w = os.pipe()

    def fds():  # in the child: the browser reads commands on fd 3 and answers on fd 4
        # Copy both out of the way first: os.pipe() may itself have returned 3 or 4.
        a, b = os.dup(to_browser_r), os.dup(from_browser_w)
        os.dup2(a, 3)  # dup2 makes the new fd inherited by the browser
        os.dup2(b, 4)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=fds,
        close_fds=False,  # os.pipe() fds are not inherited; dup2 makes only 3 and 4 inherited
    )
    os.close(to_browser_r)
    os.close(from_browser_w)
    return proc, _Pipe(to_browser_w, from_browser_r)


def shoot(
    target: str,
    widths: list[int],
    out_dir: Path,
    name: str,
    height: int | None,
    wait: int,
    pages: list[tuple[str, str]] | None = None,
) -> list[Path]:
    url = target_url(target)
    if pages and not url.startswith(("http://", "https://")):
        raise Refused("--page goes with an address (http://...), not a file.")
    browser = find_browser()
    out_dir.mkdir(parents=True, exist_ok=True)
    # One profile and one browser for the whole run (a sign-in link in the address is spent once; the
    # cookie it sets then carries the later widths); the profile is removed by its exact path at the end.
    profile = tempfile.mkdtemp(prefix="orch-shot-")
    done: list[Path] = []
    proc = None
    pipe = None
    try:
        proc, pipe = _launch(command(browser, profile, max(widths), _height(max(widths), height)))
        if pages and "#launch=" in url:  # sign in once; the cookie carries every page after it
            try:
                capture(pipe, url, widths[0], _height(widths[0], height), wait)
            except (TimeoutError, EOFError, RuntimeError, KeyError, ValueError) as e:
                raise Refused(f"The sign-in link did not open ({e}).") from None
        shown = re.sub(r"#launch=.*$", "", url)  # never print a sign-in token
        for pname, part in pages or [("", "")]:
            for w in widths:
                stem = f"{name}-{pname}-{w}" if pname else f"{name}-{w}"
                out = (out_dir / f"{stem}.png").resolve()
                if pname:
                    page = page_url(url, part)
                else:
                    page = url if not done else shown
                where = page_url(shown, part) if pname else shown
                try:
                    try:
                        data = capture(pipe, page, w, _height(w, height), wait)
                    except TimeoutError as e:
                        # A slow machine can leave one browser call unanswered (CI, ORCH-796): try that
                        # picture once more. Never for a page still loading, never with a sign-in link.
                        if str(e) == STILL_LOADING or "#launch=" in page:
                            raise
                        data = capture(pipe, page, w, _height(w, height), wait)
                except (TimeoutError, EOFError, RuntimeError, KeyError, ValueError) as e:
                    raise Refused(f"No picture was made for {where} at {w} wide ({e}).") from None
                if not data:
                    raise Refused(f"No picture was made for {where} at {w} wide.")
                out.write_bytes(data)
                done.append(out)
    finally:
        if pipe is not None:
            try:
                pipe.call("Browser.close", timeout=10)
            except Exception:
                pass
            _close(pipe.w)
        if proc is not None:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()  # only the browser this run started
                proc.wait(timeout=5)
        # The read end only after the browser is gone: on Windows a close waits for the reader thread's read.
        if pipe is not None:
            _close(pipe.r)
        _remove_profile(profile)
    return done


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _remove_profile(profile: str) -> None:
    """Remove the run's own profile. On Windows the browser's helpers can hold a file a moment after it
    closed, so try a few times before leaving it to the system's temp cleanup."""
    for _ in range(10):
        shutil.rmtree(profile, ignore_errors=True)
        if not os.path.exists(profile) or os.name != "nt":
            return
        time.sleep(0.3)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "shot":
        return False
    files = shoot(
        args.target,
        parse_widths(args.width),
        Path(args.out),
        args.name,
        args.height,
        args.wait,
        parse_pages(getattr(args, "page", None)),
    )
    if getattr(args, "json", False):
        print(json.dumps({"files": [str(f) for f in files]}))
    else:
        print("\n".join(str(f) for f in files))
    return True
