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
    runs.pending_add(proj, tid, "human:lume", "message", "Use CHF for every price")
    assert runs_live.deliver(proj, tid) == 1
    _until(lambda: _submitted(out), "submitted")
    # gone from the prompt box in two checks in a row (one could be a redraw)
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 3)) is None
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 4)) == "sent"
    assert "submit" not in runs.read(proj, tid)
    assert _submitted(out) == ["From human:lume: Use CHF for every price"]


# ---------------------------------------------------------------- watchdog (fake tmux)

RAIN = "Please add a rain plan."
BOX = "Earlier output\n\n> From human:lume: Please add a rain plan.\n\n  auto mode on\n"  # cursor on line 2


def _stuck(proj, run, monkeypatch, pane=BOX, cursor=2, mode="0", text=RAIN, agent="claude"):
    """A live run whose pasted input never goes in; returns (ticket, run, item, keys sent, screen).
    screen["pane"] is what capture-pane shows (a callable: a new screen each time)."""
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", agent, "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": tickets.now()}
    runs._write(proj, rec)
    sent, screen = [], {"pane": pane, "cursor": cursor, "mode": mode, "pasted": []}

    def fake(root, *a, **k):
        if a[0] == "send-keys":
            sent.append(a[-1])
        if a[0] == "load-buffer":
            screen["pasted"].append(k.get("input"))
        if a[0] == "capture-pane":
            pn = screen["pane"]
            return subprocess.CompletedProcess(a, 0, pn() if callable(pn) else pn, "")
        if a[0] == "display-message":
            return subprocess.CompletedProcess(a, 0, f"{screen['mode']} {screen['cursor']}\n", "")
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake)
    monkeypatch.setattr(runs_live, "PASTE_DELAY", 0)
    item = runs.pending_add(proj, tid, "human:lume", "message", text)
    assert runs_live.deliver(proj, tid) == 1 and sent == ["Enter"]
    return tid, rec["run"], item, sent, screen


def _at(proj, tid, rn, sec, **k):
    return runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, sec), **k)


def test_text_still_in_the_prompt_box_enter_again_then_end_with_the_input_kept(proj, run, monkeypatch):
    tid, rn, item, sent, _ = _stuck(proj, run, monkeypatch)
    ended = []
    assert _at(proj, tid, rn, 1) is None
    assert _at(proj, tid, rn, 3) == "enter" and sent == ["Enter", "Enter"]
    assert _at(proj, tid, rn, 5) is None  # once
    assert _at(proj, tid, rn, 61) == "enter" and sent == ["Enter"] * 3  # the watchdog's last Enter
    assert _at(proj, tid, rn, 70) is None
    assert _at(proj, tid, rn, 91, end=lambda: ended.append(1)) == "gave_up"
    assert ended == [1] and sent == ["Enter"] * 3
    (back,) = runs.undelivered(proj, tid)
    assert back["id"] == item["id"] and back["live_retry"] is True  # never lost
    rec = runs.read(proj, tid)
    assert "submit" not in rec and rec["stop_requested"] and rec["pending"] is True and rec["live_retry"]
    assert "did not take the input" in json.dumps(tickets.load(proj, tid)["history"])
    assert runs_live.check_submit(proj, tid, rn, now=time.time() + 300) is None  # once per item
    assert "Enter again (2)" in (runs.run_dir(proj) / "live-submit.log").read_text()


def test_no_blind_enter_when_the_text_is_not_in_the_prompt_box(proj, run, monkeypatch):
    """A collapsed paste or an agent already working: the text is not in the box, so no Enter, ever."""
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, pane="Working...\n\n> \n")
    for sec in (3, 61, 91, 300):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert sent == ["Enter"] and runs.read(proj, tid)["submit"]


def test_the_text_echoed_in_the_transcript_is_not_the_prompt_box(proj, run, monkeypatch):
    pane = "> From human:lume: Please add a rain plan.\n\nI'll add it.\n\n> \n"
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, pane=pane, cursor=4)
    assert _at(proj, tid, rn, 3) is None and _at(proj, tid, rn, 61) is None and sent == ["Enter"]


@pytest.mark.parametrize(
    "dialog",
    ["Do you want to proceed?\n❯ 1. Yes\n  2. No\n", "Allow this command?\n", "Overwrite it? (y/n)\n"],
)
def test_an_enter_never_answers_a_dialog(proj, run, monkeypatch, dialog):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, pane=BOX + dialog)
    for sec in (3, 61, 91):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert sent == ["Enter"]


def test_no_enter_while_the_pane_is_in_copy_mode(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, mode="1")
    assert _at(proj, tid, rn, 3) is None and _at(proj, tid, rn, 61) is None and sent == ["Enter"]


def test_a_short_input_is_never_matched_on_screen(proj, run, monkeypatch):
    pane = "ok\n\n> ok\n"
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, pane=pane, text="ok", agent="claude")
    # the tail is "From human:lume: ok" (long enough); a bare short tail is refused by _look itself
    assert runs_live._look(proj, tid, "ok") == (None, runs_live._look(proj, tid, "x" * 20)[1])


def test_never_give_up_while_the_pane_changes(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch)
    assert _at(proj, tid, rn, 3) == "enter" and _at(proj, tid, rn, 61) == "enter"
    tick = iter(range(10_000))
    screen["pane"] = lambda: f"spinner {next(tick)}\n" + BOX.split("\n", 1)[1]  # something still works
    for sec in (91, 95, 130, 200):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert runs.read(proj, tid)["submit"]


def test_the_prompt_hook_clears_the_check(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch)
    runs_live.event(proj, "working", rn, tid, None)
    assert "submit" not in runs.read(proj, tid)
    assert runs_live.check_submit(proj, tid, rn, now=time.time() + 200) is None and sent == ["Enter"]


@pytest.mark.slow
def test_a_prompt_hook_landing_during_the_check_waits_for_it(proj, run, monkeypatch):
    """Decide and Enter happen under the run lock: a hook (another process) goes after, never between."""
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch)
    hook = []

    def pane():
        if not hook:
            hook.append(
                subprocess.Popen(
                    [sys.executable, "-m", "orch", "run", "event", "--kind", "working", "--run", rn, tid],
                    cwd=proj, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            )  # fmt: skip
            end = time.monotonic() + 3
            while hook[0].poll() is None and time.monotonic() < end:
                time.sleep(0.05)
            assert hook[0].poll() is None, "the hook did not wait for the run lock"
        return BOX

    screen["pane"] = pane
    assert _at(proj, tid, rn, 3) == "enter" and sent == ["Enter", "Enter"]
    assert hook[0].wait(20) == 0
    assert "submit" not in runs.read(proj, tid)  # applied after the check, not lost


def test_paste_is_recorded_even_when_enter_fails_and_never_pasted_twice(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch)
    rec = runs.read(proj, tid)
    assert rec["submit"] and runs.undelivered(proj, tid) == []
    # a failed Enter at delivery: same outcome (delivered, checked later)
    tid2 = _ticket(run)
    r2 = runs.claim(proj, tid2, "human:t", "claude", "live", pid=os.getpid())
    r2["live"] = {"state": "idle", "since": tickets.now()}
    runs._write(proj, r2)
    monkeypatch.setattr(runs_live, "_enter", lambda root, t: False)
    runs.pending_add(proj, tid2, "human:lume", "message", "Please add a rain plan.")
    n_before = len(screen["pasted"])
    assert runs_live.deliver(proj, tid2) == 1
    assert runs.undelivered(proj, tid2) == [] and runs.read(proj, tid2)["submit"]
    runs_live._set_state(proj, tid2, r2["run"], "idle")
    assert runs_live.deliver(proj, tid2) == 0 and len(screen["pasted"]) == n_before + 1


def test_escape_sequences_cannot_end_the_bracketed_paste(proj, run, monkeypatch):
    evil = "Nice plan.\x1b[201~\rrm -rf ~\r\x1b[200~ and more\x07\x00"
    for flat in (False, True):
        out = runs_live._format([{"by": "human:x", "text": evil}], flat)
        assert "\x1b" not in out and "\r" not in out and "\x07" not in out and "\x00" not in out
        assert "[201~" in out  # harmless text now, no ESC in front
    tid, rn, _, _, screen = _stuck(proj, run, monkeypatch, text=evil)
    assert "\x1b" not in screen["pasted"][-1] and "\r" not in screen["pasted"][-1]


def test_a_tool_without_hooks_needs_the_text_gone_twice(proj, run, monkeypatch):
    config.add_agent(proj, "fake", "true {prompt}", "true --interactive")
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, agent="fake", pane="> \n", cursor=0)
    assert _at(proj, tid, rn, 3) is None  # gone once: maybe a redraw
    screen["pane"] = "> From human:lume: Please add a rain plan.\n"  # back: it was a redraw
    assert _at(proj, tid, rn, 4) == "enter"
    screen["pane"] = "> \n"
    assert _at(proj, tid, rn, 5) is None and runs.read(proj, tid)["submit"]
    assert _at(proj, tid, rn, 6) == "sent" and "submit" not in runs.read(proj, tid)


def _start_modes(proj, tid, monkeypatch):
    modes = []

    class Stop(Exception):
        pass

    def claim(root, t, by, name, mode, **k):
        modes.append(mode)
        raise Stop

    def live(*a, **k):
        modes.append("live")
        raise Stop

    monkeypatch.setattr(runs_live, "available", lambda a: True)
    monkeypatch.setattr(runs_live, "start_live", live)
    monkeypatch.setattr(runs, "claim", claim)
    config.set_key(proj, "workspace", "agent", "claude")
    with pytest.raises(Stop):
        runs.start(proj, tid, "agent:automation")
    return modes


def _give_up(proj, tid, rn):
    for sec in (3, 61, 91):
        _at(proj, tid, rn, sec, end=lambda: None)
    runs.release(proj, tid, rn)


def test_input_a_live_session_did_not_take_starts_a_one_step_run(proj, run, monkeypatch):
    tid, rn, _, _, _ = _stuck(proj, run, monkeypatch)
    _give_up(proj, tid, rn)
    assert _start_modes(proj, tid, monkeypatch) == ["oneshot"]


def test_a_start_prompt_that_never_went_in_does_not_loop_live(proj, run, monkeypatch):
    tid, rn, item, _, _ = _stuck(proj, run, monkeypatch)
    items = runs._pending_read(proj, tid)
    for i in items:
        i["via"] = "start"  # the session's only input was its start prompt
    runs._pending_write(proj, tid, items)
    _give_up(proj, tid, rn)
    (note,) = runs.undelivered(proj, tid)
    assert note["live_retry"] is True and note["kind"] == "event"
    assert _start_modes(proj, tid, monkeypatch) == ["oneshot"]
