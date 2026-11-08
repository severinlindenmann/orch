"""Input pasted into a live session is submitted: bracketed paste, then Enter as its own key; the pane's
wrapper checks it went in (Enter again), and a session that never takes it is ended with the input kept for a
one-step run.

P1.7 (8 Nov): a resumed session got the paste but not the Enter; the text sat unsent in the prompt box."""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time

import pytest

from orch import config, runs, runs_live, tickets

_tmux = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("tmux"), reason="needs tmux (not on Windows, not installed here)"
)

# A prompt box like a real TUI: turns bracketed paste on, keeps pasted text in the box, submits only on a
# separate Enter outside the paste. For its first `deaf` seconds it drops Enter (a tool still drawing).
FAKE_TUI = r"""
import json, os, sys, time, tty
out, deaf = sys.argv[1], float(sys.argv[2])
t0 = time.monotonic()
tty.setraw(0)
START, END = b"\x1b[200~", b"\x1b[201~"
box, pasting, buf = "", False, b""

def draw(note=""):
    os.write(1, b"\x1b[2J\x1b[H" + note.encode() + b"\r\n> " + box.replace("\n", "\r\n  ").encode() + b"\r\n")

os.write(1, b"\x1b[?2004h")
draw("ready")
while True:
    data = os.read(0, 4096)
    if not data:
        break
    buf += data
    while buf:
        if pasting:
            j = buf.find(END)
            if j < 0:
                keep = next((k for k in range(len(END) - 1, 0, -1) if buf.endswith(END[:k])), 0)
                box += buf[: len(buf) - keep].decode("utf-8", "replace").replace("\r", "\n")
                buf = buf[len(buf) - keep :]
                break
            box += buf[:j].decode("utf-8", "replace").replace("\r", "\n")
            buf, pasting = buf[j + len(END) :], False
        elif buf.startswith(START):
            buf, pasting = buf[len(START) :], True
        elif START.startswith(buf):
            break  # a start sequence cut in two: wait for the rest
        elif buf[:1] == b"\r":
            buf = buf[1:]
            if time.monotonic() - t0 < deaf:
                continue  # dropped, like a tool that is not ready yet
            if box:
                with open(out, "a") as f:
                    f.write(json.dumps(box) + "\n")
                box = ""
        else:
            box += buf[:1].decode("utf-8", "replace")
            buf = buf[1:]
    draw()
"""


@pytest.fixture
def tui(proj, tmp_path, monkeypatch):
    """A private tmux server (own socket name, killed by that exact name) running the fake TUI per ticket."""
    sock = "orch-test-" + secrets.token_hex(4)
    monkeypatch.setattr(runs_live, "socket_name", lambda root: sock)
    script = tmp_path / "fake_tui.py"
    script.write_text(FAKE_TUI, encoding="utf-8")
    out = tmp_path / "submitted.jsonl"

    def start(tid: str, agent: str, deaf: float = 0.0) -> dict:
        r = runs_live.tmux(
            proj, "new-session", "-d", "-x", "200", "-y", "50", "-s", tid,
            "--", sys.executable, str(script), str(out), str(deaf),
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        _until(lambda: "ready" in _pane(proj, tid), "fake TUI up")
        rec = runs.claim(proj, tid, "human:t", agent, "live", pid=os.getpid())
        rec["live"] = {"state": "idle", "since": tickets.now()}
        runs._write(proj, rec)
        return rec

    yield start, out
    subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=20)


def _until(fn, what, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out: {what}")


def _pane(proj, tid):
    return runs_live.tmux(proj, "capture-pane", "-p", "-t", runs_live.target(tid)).stdout


def _submitted(out):
    return [json.loads(ln) for ln in out.read_text().splitlines()] if out.exists() else []


def _ticket(run):
    return json.loads(run("ticket", "new", "Plan the fair", "--json", "--by", "human:t")[1])["id"]


def _later(proj, tid, seconds):
    return runs._parse(runs.read(proj, tid)["submit"]["at"]) + seconds


INPUT = "Please add a rain plan.\nAnd a second line, like a change request."


@_tmux
@pytest.mark.slow
def test_pasted_input_is_submitted_exactly_once(proj, run, tui):
    start, out = tui
    tid = _ticket(run)
    rec = start(tid, "claude")
    runs.pending_add(proj, tid, "human:lume", "message", INPUT)
    assert runs_live.deliver(proj, tid) == 1
    _until(lambda: _submitted(out), "submitted")
    assert _submitted(out) == [f"From human:lume: {INPUT}"]
    # the tool's prompt hook says it took a prompt: nothing more is sent
    runs_live.event(proj, "working", rec["run"], tid, None)
    assert "submit" not in runs.read(proj, tid)
    assert runs_live.check_submit(proj, tid, rec["run"], now=time.time() + 120) is None
    time.sleep(0.3)
    assert len(_submitted(out)) == 1


@_tmux
@pytest.mark.slow
def test_an_enter_the_tool_dropped_is_sent_again_and_submits_once(proj, run, tui):
    """The P1.7 case: the paste lands, the Enter is lost, the text sits in the prompt box."""
    start, out = tui
    tid = _ticket(run)
    rec = start(tid, "claude", deaf=1.0)
    runs.pending_add(proj, tid, "human:lume", "message", INPUT)
    assert runs_live.deliver(proj, tid) == 1
    time.sleep(1.2)  # the tool is ready now; its first Enter was dropped
    assert _submitted(out) == [] and "a second line, like a change request." in _pane(proj, tid)
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 3)) == "enter"
    _until(lambda: _submitted(out), "submitted after the second Enter")
    runs_live.event(proj, "working", rec["run"], tid, None)  # its prompt hook
    assert runs_live.check_submit(proj, tid, rec["run"], now=time.time() + 120) is None
    time.sleep(0.3)
    assert _submitted(out) == [f"From human:lume: {INPUT}"]
    assert "Enter again (2)" in (runs.run_dir(proj) / "live-submit.log").read_text()


@_tmux
@pytest.mark.slow
def test_a_tool_without_hooks_counts_as_submitted_when_its_prompt_box_is_empty(proj, run, tui):
    config.add_agent(proj, "fake", "true {prompt}", "true --interactive")
    start, out = tui
    tid = _ticket(run)
    rec = start(tid, "fake")
    runs.pending_add(proj, tid, "human:lume", "message", "Use CHF")
    assert runs_live.deliver(proj, tid) == 1
    _until(lambda: _submitted(out), "submitted")
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 3)) == "sent"
    assert "submit" not in runs.read(proj, tid)
    assert _submitted(out) == ["From human:lume: Use CHF"]


# ---------------------------------------------------------------- watchdog (fake tmux)


def _stuck(proj, run, monkeypatch, pane="> "):
    """A claude live run whose pasted input never goes in; returns (ticket, run, item, keys sent)."""
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": tickets.now()}
    runs._write(proj, rec)
    sent = []

    def fake(root, *a, **k):
        if a[0] == "send-keys":
            sent.append(a[-1])
        if a[0] == "capture-pane":
            return subprocess.CompletedProcess(a, 0, pane, "")
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake)
    monkeypatch.setattr(runs_live, "PASTE_DELAY", 0)
    item = runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    assert runs_live.deliver(proj, tid) == 1 and sent == ["Enter"]
    return tid, rec["run"], item, sent


def test_no_sign_of_the_input_enter_once_more_then_end_with_the_input_kept(proj, run, monkeypatch):
    tid, rn, item, sent = _stuck(proj, run, monkeypatch)  # a collapsed paste: the text is not on screen
    ended = []
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 5)) is None  # hook may be slow
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 61)) == "enter"
    assert sent == ["Enter", "Enter"]
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 70)) is None  # once
    got = runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 91), end=lambda: ended.append(1))
    assert got == "gave_up" and ended == [1] and sent == ["Enter", "Enter"]
    (back,) = runs.undelivered(proj, tid)
    assert back["id"] == item["id"] and back["live_retry"] is True  # never lost
    rec = runs.read(proj, tid)
    assert "submit" not in rec and rec["stop_requested"] and rec["pending"] is True
    hist = json.dumps(tickets.load(proj, tid)["history"])
    assert "did not take the input" in hist
    # once: nothing more happens for this item in this run
    assert runs_live.check_submit(proj, tid, rn, now=_later_any(200)) is None


def _later_any(seconds):
    return time.time() + seconds


def test_text_still_in_the_prompt_box_gets_enter_after_two_seconds(proj, run, monkeypatch):
    tid, rn, _, sent = _stuck(proj, run, monkeypatch, pane="> From human:lume: Please add a rain plan.\n")
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 1)) is None
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 3)) == "enter"
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 4)) is None
    assert sent == ["Enter", "Enter"]


def test_the_prompt_hook_clears_the_check(proj, run, monkeypatch):
    tid, rn, _, sent = _stuck(proj, run, monkeypatch)
    runs_live.event(proj, "working", rn, tid, None)
    assert "submit" not in runs.read(proj, tid)
    assert runs_live.check_submit(proj, tid, rn, now=time.time() + 200) is None and sent == ["Enter"]


def test_input_a_live_session_did_not_take_starts_a_one_step_run(proj, run, monkeypatch):
    tid, rn, _, _ = _stuck(proj, run, monkeypatch)
    runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 61))
    runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 91))
    runs.release(proj, tid, rn)
    modes = []

    class Stop(Exception):
        pass

    def claim(root, t, by, name, mode, **k):
        modes.append(mode)
        raise Stop

    monkeypatch.setattr(runs_live, "available", lambda a: True)
    monkeypatch.setattr(
        runs_live, "start_live", lambda *a, **k: modes.append("live") or (_ for _ in ()).throw(Stop)
    )
    monkeypatch.setattr(runs, "claim", claim)
    config.set_key(proj, "workspace", "agent", "claude")
    with pytest.raises(Stop):
        runs.start(proj, tid, "agent:automation")
    assert modes == ["oneshot"]
