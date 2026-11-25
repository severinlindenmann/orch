"""`orch shot`: the browser always starts with the keychain-safe options; widths, files and cleanup."""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from orch import cli_shot
from orch.errors import Refused

# Read before the test fixtures fake the home: on Windows the browser hangs at start when USERPROFILE points
# at an empty made-up folder (seen with Edge 157), so the real-browser test gives it the real one back.
_REAL_USERPROFILE = os.environ.get("USERPROFILE")


def test_command_has_keychain_safe_flags():
    cmd = cli_shot.command("/b", "/p", 1280, 800)
    assert "--use-mock-keychain" in cmd and "--password-store=basic" in cmd
    assert "--remote-debugging-pipe" in cmd and "--user-data-dir=/p" in cmd
    # The picture is taken over the protocol now, never with --screenshot (that cut narrow widths).
    assert not any(a.startswith("--screenshot") for a in cmd)


def test_widths():
    assert cli_shot.parse_widths("1280, 390") == [1280, 390]
    for bad in ("", "abc", "50"):
        with pytest.raises(Refused):
            cli_shot.parse_widths(bad)


def test_target_url(tmp_path):
    f = tmp_path / "m.html"
    f.write_text("<p>x</p>")
    assert cli_shot.target_url(str(f)).startswith("file://")
    assert cli_shot.target_url("http://127.0.0.1:1/") == "http://127.0.0.1:1/"
    with pytest.raises(Refused):
        cli_shot.target_url(str(tmp_path / "none.html"))


class FakePipe:
    """Answers the protocol calls `capture` makes and remembers them."""

    def __init__(self):
        self.calls = []
        self.w = self.r = -1

    def call(self, method, params=None, session=None, timeout=30):
        self.calls.append((method, params or {}, session))
        return {
            "Target.createTarget": {"targetId": "T"},
            "Target.attachToTarget": {"sessionId": "S"},
            "Page.captureScreenshot": {"data": base64.b64encode(b"png").decode()},
        }.get(method, {})

    def wait_event(self, method, session, timeout):
        self.calls.append((method, {}, session))
        return True

    def settle(self, session, quiet, deadline):
        pass


def fake_browser(monkeypatch):
    pipes = []
    monkeypatch.setattr(cli_shot, "find_browser", lambda: "/b")

    def launch(cmd):
        pipes.append((cmd, FakePipe()))
        return None, pipes[-1][1]

    monkeypatch.setattr(cli_shot, "_launch", launch)
    return pipes


def test_viewport_is_set_by_the_protocol_before_the_page_loads():
    pipe = FakePipe()
    assert cli_shot.capture(pipe, "http://x/", 390, 844, 1) == b"png"
    names = [m for m, _, _ in pipe.calls]
    metrics = next(p for m, p, _ in pipe.calls if m == "Emulation.setDeviceMetricsOverride")
    assert metrics["width"] == 390 and metrics["height"] == 844
    assert names.index("Emulation.setDeviceMetricsOverride") < names.index("Page.navigate")
    assert names[-1] == "Target.closeTarget"


def test_shoot_writes_files_and_removes_profile(tmp_path, monkeypatch):
    f = tmp_path / "m.html"
    f.write_text("<p>x</p>")
    pipes = fake_browser(monkeypatch)
    out = cli_shot.shoot(str(f), [1280, 390], tmp_path / "o", "n", None, 1)
    assert [p.name for p in out] == ["n-1280.png", "n-390.png"]
    assert all(p.read_bytes() == b"png" for p in out)
    assert len(pipes) == 1  # one browser, one profile for every width
    cmd, pipe = pipes[0]
    profile = next(a for a in cmd if a.startswith("--user-data-dir=")).split("=", 1)[1]
    assert not Path(profile).exists()
    widths = [p["width"] for m, p, _ in pipe.calls if m == "Emulation.setDeviceMetricsOverride"]
    assert widths == [1280, 390]
    assert pipe.calls[-1][0] == "Browser.close"


def test_launch_link_only_on_first_width(tmp_path, monkeypatch):
    pipes = fake_browser(monkeypatch)
    cli_shot.shoot("http://h/#launch=tok", [1280, 390], tmp_path, "n", None, 1)
    urls = [p["url"] for m, p, _ in pipes[0][1].calls if m == "Page.navigate"]
    assert urls == ["http://h/#launch=tok", "http://h/"]


def _hanging_browser(monkeypatch, hangs):
    """A browser whose first `hangs` page loads never answer (a slow CI machine, ORCH-796)."""
    pipes = fake_browser(monkeypatch)
    left = [hangs]

    def launch(cmd):
        pipe = FakePipe()
        plain = pipe.call

        def call(method, params=None, session=None, timeout=30):
            if method == "Page.navigate" and left[0] > 0:
                left[0] -= 1
                pipe.calls.append((method, params or {}, session))
                raise TimeoutError("the browser did not answer in time")
            return plain(method, params, session, timeout)

        pipe.call = call
        pipes.append((cmd, pipe))
        return None, pipe

    monkeypatch.setattr(cli_shot, "_launch", launch)
    return pipes


def test_one_unanswered_browser_call_is_tried_once_more(tmp_path, monkeypatch):
    pipes = _hanging_browser(monkeypatch, 1)
    out = cli_shot.shoot("http://h/", [390], tmp_path, "n", None, 1)
    assert out[0].read_bytes() == b"png"
    assert [m for m, _, _ in pipes[0][1].calls].count("Page.navigate") == 2


def test_a_second_unanswered_call_says_why_no_picture(tmp_path, monkeypatch):
    _hanging_browser(monkeypatch, 2)
    with pytest.raises(Refused, match="did not answer in time"):
        cli_shot.shoot("http://h/", [390], tmp_path, "n", None, 1)


def test_a_sign_in_link_is_never_tried_twice(tmp_path, monkeypatch):
    pipes = _hanging_browser(monkeypatch, 1)
    with pytest.raises(Refused):
        cli_shot.shoot("http://h/#launch=tok", [390], tmp_path, "n", None, 1)
    assert [m for m, _, _ in pipes[0][1].calls].count("Page.navigate") == 1


def test_a_whole_sign_in_text_as_target_never_prints_the_token(tmp_path):
    with pytest.raises(Refused) as e:
        cli_shot.target_url("Sign-in link (one use): http://127.0.0.1:28704/#launch=SECRETTOK")
    assert "SECRETTOK" not in str(e.value) and "#launch=" not in str(e.value)
    assert "only the address" in str(e.value)


def test_a_page_still_loading_without_sign_in_names_the_sign_in_link(tmp_path, monkeypatch):
    fake_browser(monkeypatch)
    monkeypatch.setattr(cli_shot, "_busy", lambda pipe, s: True)
    with pytest.raises(Refused, match="orch dashboard open --print"):
        cli_shot.shoot("http://h/", [390], tmp_path, "n", None, 0)
    with pytest.raises(Refused) as e:
        cli_shot.shoot("http://h/#launch=tok", [390], tmp_path, "n", None, 0)
    assert "dashboard open" not in str(e.value) and "tok" not in str(e.value)


def _has_browser():
    try:
        cli_shot.find_browser()
        return True
    except Refused:
        return False


@pytest.mark.skipif(not _has_browser(), reason="no Chrome or Chromium here")
def test_narrow_width_lays_out_that_wide(tmp_path, monkeypatch):
    if os.name == "nt" and _REAL_USERPROFILE:
        monkeypatch.setenv("USERPROFILE", _REAL_USERPROFILE)
    # ORCH-219: headless Chrome keeps windows at least 500 wide; a 390 picture must still show a
    # 390 wide page, not a 500 wide one cut at the right. The page paints its width as a bar.
    f = tmp_path / "w.html"
    f.write_text(
        "<!doctype html><body style='margin:0'><div id=b style='height:40px;background:#000'></div>"
        "<script>b.style.width=(innerWidth/2)+'px'</script>"
    )
    png = cli_shot.shoot(str(f), [390], tmp_path, "w", 200, 5)[0].read_bytes()
    assert struct.unpack(">II", png[16:24]) == (390, 200)
    assert _bar_width(png) == 195


def _bar_width(png: bytes) -> int:
    """Black pixels in the first row of a PNG (no image library needed)."""
    w, _ = struct.unpack(">II", png[16:24])
    depth, ctype = png[24], png[25]
    assert depth == 8 and ctype in (2, 6)
    bpp = 3 if ctype == 2 else 4
    data, i = b"", 8
    while i < len(png):
        n = struct.unpack(">I", png[i : i + 4])[0]
        if png[i + 4 : i + 8] == b"IDAT":
            data += png[i + 8 : i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(data)
    row = raw[1 : 1 + w * bpp]
    kind = raw[0]  # first row, nothing above: Up = None, Paeth = Sub, Average = half the left pixel
    px, prev = [], [0] * bpp
    for x in range(w):
        p = list(row[x * bpp : x * bpp + bpp])
        if kind in (1, 4):
            p = [(p[k] + prev[k]) & 0xFF for k in range(bpp)]
        elif kind == 3:
            p = [(p[k] + prev[k] // 2) & 0xFF for k in range(bpp)]
        prev = p
        px.append(p)
    return sum(1 for p in px if p[0] < 30 and p[1] < 30 and p[2] < 30)


def _windows(monkeypatch, tmp_path):
    """A Windows machine with its three program folders under tmp_path and nothing on PATH."""
    roots = {}
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        roots[var] = tmp_path / var.replace("(", "_").replace(")", "")
        roots[var].mkdir()
        monkeypatch.setenv(var, str(roots[var]))
    monkeypatch.delenv("ORCH_SHOT_BROWSER", raising=False)
    monkeypatch.setattr(cli_shot.os, "name", "nt")
    monkeypatch.setattr(cli_shot.shutil, "which", lambda n: str(tmp_path / f"{n}.exe"))  # never asked
    return roots


def _exe(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return str(path)


def test_windows_finds_chrome_in_program_files(tmp_path, monkeypatch):
    roots = _windows(monkeypatch, tmp_path)
    chrome = _exe(roots["ProgramFiles"] / "Google" / "Chrome" / "Application" / "chrome.exe")
    _exe(roots["ProgramFiles(x86)"] / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    assert cli_shot.find_browser() == chrome  # Chrome before Edge


def test_windows_finds_chrome_in_program_files_x86_and_per_user(tmp_path, monkeypatch):
    roots = _windows(monkeypatch, tmp_path)
    user = _exe(roots["LOCALAPPDATA"] / "Google" / "Chrome" / "Application" / "chrome.exe")
    assert cli_shot.find_browser() == user
    x86 = _exe(roots["ProgramFiles(x86)"] / "Google" / "Chrome" / "Application" / "chrome.exe")
    assert cli_shot.find_browser() == x86


def test_windows_falls_back_to_edge(tmp_path, monkeypatch):
    roots = _windows(monkeypatch, tmp_path)
    edge = _exe(roots["ProgramFiles(x86)"] / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    assert cli_shot.find_browser() == edge


def test_windows_without_a_browser_names_edge(tmp_path, monkeypatch):
    _windows(monkeypatch, tmp_path)
    with pytest.raises(Refused, match="No Chrome or Edge found"):
        cli_shot.find_browser()


def test_windows_never_takes_a_browser_from_the_current_folder(tmp_path, monkeypatch):
    # Windows' PATH search looks in the current folder first: a chrome.exe in a downloaded project must
    # not be started. Only the install folders count.
    _windows(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    _exe(tmp_path / "chrome.exe")
    _exe(tmp_path / "msedge.exe")
    with pytest.raises(Refused, match="No Chrome or Edge found"):
        cli_shot.find_browser()


class _FakeStartupInfo:
    lpAttributeList: dict = {}


def _fake_windows_launch(monkeypatch, popen):
    """The Windows calls _launch_windows makes, faked so the test runs anywhere: a pipe end's handle is its
    fd + 1000."""
    import sys
    import types

    inherited = []
    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(get_osfhandle=lambda fd: fd + 1000))
    monkeypatch.setattr(
        cli_shot.os, "set_handle_inheritable", lambda h, v: inherited.append((h, v)), raising=False
    )
    monkeypatch.setattr(cli_shot.subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
    monkeypatch.setattr(cli_shot.subprocess, "Popen", popen)
    monkeypatch.setattr(cli_shot.os, "name", "nt")
    # no reader thread in a test: the pipe is just its two fds here
    monkeypatch.setattr(cli_shot, "_Pipe", lambda w, r: types.SimpleNamespace(w=w, r=r))
    return inherited


def test_windows_launch_hands_over_two_inherited_handles(monkeypatch):
    # The fd 3/4 pipe does not exist on Windows: the browser gets two inherited handles, named on its
    # command line, and only those two are inherited.
    seen = {}

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return "proc"

    inherited = _fake_windows_launch(monkeypatch, popen)
    proc, pipe = cli_shot._launch(cli_shot.command("chrome.exe", "p", 1280, 800))
    try:
        assert proc == "proc"
        flag = next(a for a in seen["cmd"] if a.startswith("--remote-debugging-io-pipes="))
        h_in, h_out = (int(h) for h in flag.split("=", 1)[1].split(","))
        assert seen["cmd"].index(flag) == seen["cmd"].index("--remote-debugging-pipe") + 1
        assert sorted(inherited) == sorted([(h_in, True), (h_out, True)])
        assert seen["startupinfo"].lpAttributeList == {"handle_list": [h_in, h_out]}
        assert seen["close_fds"] is True
        # The browser's ends are closed here; ours stay open and are the other ends of the same pipes.
        for h in (h_in, h_out):
            with pytest.raises(OSError):
                os.fstat(h - 1000)
        os.fstat(pipe.w)
        os.fstat(pipe.r)
    finally:
        os.close(pipe.w)
        os.close(pipe.r)


def test_windows_launch_failure_closes_every_pipe_end(monkeypatch):
    def popen(cmd, **kw):
        raise OSError("cannot start")

    _fake_windows_launch(monkeypatch, popen)
    before = os.pipe()
    os.close(before[0])
    os.close(before[1])
    with pytest.raises(OSError, match="cannot start"):
        cli_shot._launch(cli_shot.command("chrome.exe", "p", 1280, 800))
    after = os.pipe()  # the lowest free fds again: nothing was left open
    os.close(after[0])
    os.close(after[1])
    assert after == before


@pytest.fixture
def no_browser(tmp_path, monkeypatch):
    """A computer with no browser at all: empty HOME, empty apps folder, nothing on the PATH."""
    if os.name == "nt":
        pytest.skip("macOS and Linux browser folders (Windows has its own tests above)")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # what expanduser reads on Windows
    monkeypatch.delenv("ORCH_SHOT_BROWSER", raising=False)
    monkeypatch.setattr(cli_shot, "_APPS", str(tmp_path / "Applications"))
    monkeypatch.setattr(cli_shot.shutil, "which", lambda n: None)
    return tmp_path


def test_no_browser_is_refused(no_browser):
    with pytest.raises(Refused, match="Edge or Brave"):
        cli_shot.find_browser()


@pytest.mark.parametrize(
    "where",
    [
        # report r-1119-1255-ws-8: newer Playwright unpacks Chrome for Testing, not Chromium.app
        "home/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/"
        "Contents/MacOS/Google Chrome for Testing",
        "home/Library/Caches/ms-playwright/chromium-1187/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        "home/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome",
        "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ],
)
def test_finds_each_kind_of_browser(no_browser, where):
    exe = _exe(no_browser / where)
    assert cli_shot.find_browser() == exe


def test_newest_playwright_first(no_browser):
    base = no_browser / "home/Library/Caches/ms-playwright"
    _exe(base / "chromium-999/chrome-mac/Chromium.app/Contents/MacOS/Chromium")
    new = _exe(base / "chromium-1248/chrome-mac/Chromium.app/Contents/MacOS/Chromium")
    assert cli_shot.find_browser() == new


def test_chrome_before_edge(no_browser):
    chrome = _exe(no_browser / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    _exe(no_browser / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    assert cli_shot.find_browser() == chrome


def test_edge_or_brave_on_the_path(no_browser, monkeypatch):
    brave = "/usr/bin/brave-browser"
    monkeypatch.setattr(cli_shot.shutil, "which", lambda n: brave if n == "brave-browser" else None)
    assert cli_shot.find_browser() == "/usr/bin/brave-browser"


_FAKE_DOM = """
const doc = (busy, frames = []) => ({
  querySelector: q => (q === '[aria-busy="true"]' && busy ? {} : null),
  querySelectorAll: q => (q === 'iframe, frame' ? frames : []),
});
const frame = d => ({ contentDocument: d });
const foreign = { get contentDocument() { throw new Error('cross-origin'); } };
const cases = {
  idle: doc(false, [frame(doc(false)), frame(null)]),
  top: doc(true),
  iframe: doc(false, [frame(doc(true))]),
  nested: doc(false, [frame(doc(false, [frame(doc(true))]))]),
  foreign: doc(false, [foreign]),
};
const out = {};
for (const [name, document] of Object.entries(cases)) out[name] = eval(BUSY_JS);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="no node here")
def test_busy_check_looks_into_same_origin_iframes():
    # ORCH-2021: add-on pages run in an iframe and say aria-busy there; the top page alone looked done.
    src = f"const BUSY_JS = {json.dumps(cli_shot.BUSY_JS)};\n{_FAKE_DOM}"
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == {"idle": False, "top": True, "iframe": True, "nested": True, "foreign": False}
