"""Input into a live session: orch types ONE fixed ASCII notice line (never a person's text), then Enter as
its own key; the agent reads the input with `orch run input`, which marks it delivered. The pane's wrapper
checks the notice was taken (Enter again while it still sits in the prompt box, never at a dialog), and a
session that never takes it is ended with the input kept for a one-step run.

P1.7 (8 Nov): a resumed session got the paste but not the Enter; the text sat unsent in the prompt box."""

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time

import pytest

from orch import config, runs, runs_live, tickets

_tmux = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("tmux"), reason="needs tmux (not on Windows, not installed here)"
)

# A prompt box drawn like Claude Code's: transcript, a border, the box, a border, a status line; the cursor
# is left after the status line. It turns bracketed paste on and records any paste (orch must never paste),
# shows typed keys in the box and submits only on Enter. For its first `deaf` seconds it drops Enter.
FAKE_TUI = r"""
import json, os, sys, time, tty
out, deaf = sys.argv[1], float(sys.argv[2])
t0 = time.monotonic()
tty.setraw(0)
START, END = b"\x1b[200~", b"\x1b[201~"
box, pasting, buf, said = "", False, b"", []
BORDER = "─" * 60

def record(kind, text):
    with open(out, "a") as f:
        f.write(json.dumps({"kind": kind, "text": text}) + "\n")

def draw():
    rows = ["ready"] + ["> " + s for s in said[-5:]] + [BORDER, "> " + box, BORDER, "  auto mode on"]
    os.write(1, b"\x1b[2J\x1b[H" + "\r\n".join(rows).encode())

os.write(1, b"\x1b[?2004h")
draw()
while True:
    data = os.read(0, 4096)
    if not data:
        break
    buf += data
    while buf:
        if pasting:
            j = buf.find(END)
            if j < 0:
                break
            record("paste", buf[:j].decode("utf-8", "replace"))
            buf, pasting = buf[j + len(END) :], False
        elif buf.startswith(START):
            buf, pasting = buf[len(START) :], True
        elif START.startswith(buf):
            break
        elif buf[:1] == b"\r":
            buf = buf[1:]
            if time.monotonic() - t0 < deaf:
                continue  # dropped, like a tool that is not ready yet
            if box:
                record("submit", box)
                said.append(box)
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
    out = tmp_path / "tui.jsonl"

    def start(tid: str, agent: str = "claude", deaf: float = 0.0) -> dict:
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


def _got(out, kind=None):
    rows = [json.loads(ln) for ln in out.read_text().splitlines()] if out.exists() else []
    return [r["text"] for r in rows if kind is None or r["kind"] == kind]


def _ticket(run):
    return json.loads(run("ticket", "new", "Plan the fair", "--json", "--by", "human:t")[1])["id"]


def _later(proj, tid, seconds):
    return runs._parse(runs.read(proj, tid)["submit"]["at"]) + seconds


# long, multi-line, with an escape that would end a bracketed paste and a CR that would submit
EVIL = "Please add a rain plan.\n" + "Second line. " * 200 + "\x1b[201~\rrm -rf ~\r\x1b[200~ end"


@_tmux
@pytest.mark.slow
def test_the_tool_gets_only_the_notice_and_the_agent_reads_the_input(proj, run, tui):
    start, out = tui
    tid = _ticket(run)
    start(tid)
    item = runs.pending_add(proj, tid, "human:lume", "message", EVIL)
    assert runs_live.deliver(proj, tid) == 1
    _until(lambda: _got(out, "submit"), "submitted")
    assert _got(out) == [runs_live.notice_line(tid, False)]  # exactly once, typed, never pasted
    assert [i["id"] for i in runs.undelivered(proj, tid)] == [item["id"]]  # not delivered until read
    code, text, _ = run("run", "input", tid)
    assert code == 0 and "Please add a rain plan." in text and "Second line." in text
    assert runs.undelivered(proj, tid) == [] and "submit" not in runs.read(proj, tid)
    assert run("run", "input", tid)[1].strip() == f"Nothing new on {tickets.load(proj, tid)['key']}."
    time.sleep(0.3)
    assert len(_got(out)) == 1 and "rain" not in _pane(proj, tid)


@_tmux
@pytest.mark.slow
def test_an_enter_the_tool_dropped_is_sent_again_and_submits_once(proj, run, tui):
    """The P1.7 case: the line lands, the Enter is lost, the line sits in the prompt box."""
    start, out = tui
    tid = _ticket(run)
    rec = start(tid, deaf=1.0)
    runs.pending_add(proj, tid, "human:lume", "message", EVIL)
    assert runs_live.deliver(proj, tid) == 1
    time.sleep(1.2)  # the tool is ready now; its first Enter was dropped
    assert _got(out) == [] and "orch run input" in _pane(proj, tid)
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 3)) == "enter"
    _until(lambda: _got(out, "submit"), "submitted after the second Enter")
    # the echo above the box is not the box: nothing more is sent
    assert runs_live.check_submit(proj, tid, rec["run"], now=_later(proj, tid, 61)) is None
    time.sleep(0.3)
    assert _got(out) == [runs_live.notice_line(tid, False)]
    assert "Enter again (2)" in (runs.run_dir(proj) / "live-submit.log").read_text()


# ---------------------------------------------------------------- the check (fake tmux)

B = "─" * 40


def _screen(box="", above="", below="  auto mode on"):
    return "\n".join([above, B, f"> {box}", B, below, ""])


def _stuck(proj, run, monkeypatch, pane=None, mode="0", text="Please add a rain plan.", agent="claude"):
    """A live run whose notice was typed and not taken; returns (ticket, run, item, keys sent, screen).
    screen["pane"]: what capture-pane shows (a callable: a new screen per call)."""
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", agent, "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": tickets.now()}
    runs._write(proj, rec)
    line = runs_live.notice_line(tid, False)
    sent = []
    screen = {"pane": pane if pane is not None else _screen(line), "mode": mode}

    def fake(root, *a, **k):
        if a[0] == "send-keys":
            sent.append(a[-1])
        if a[0] in ("load-buffer", "paste-buffer"):
            raise AssertionError("orch never pastes")
        if a[0] == "capture-pane":
            pn = screen["pane"]
            return subprocess.CompletedProcess(a, 0, pn() if callable(pn) else pn, "")
        if a[0] == "display-message":
            return subprocess.CompletedProcess(a, 0, f"{screen['mode']} 49\n", "")
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake)
    monkeypatch.setattr(runs_live, "PASTE_DELAY", 0)
    item = runs.pending_add(proj, tid, "human:lume", "message", text)
    assert runs_live.deliver(proj, tid) == 1 and sent == [line, "Enter"]
    return tid, rec["run"], item, sent, screen


def _at(proj, tid, rn, sec, **k):
    return runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, sec), **k)


def test_a_persons_text_is_never_typed(proj, run, monkeypatch):
    tid, _, _, sent, _ = _stuck(proj, run, monkeypatch, text=EVIL)
    assert sent == [runs_live.notice_line(tid, False), "Enter"]
    assert all(k.isascii() and "\x1b" not in k and "\r" not in k and "\n" not in k for k in sent)
    assert "rain" not in "".join(sent)


def test_notice_still_in_the_box_enter_again_then_end_with_the_input_kept(proj, run, monkeypatch):
    tid, rn, item, sent, _ = _stuck(proj, run, monkeypatch)
    ended = []
    assert _at(proj, tid, rn, 1) is None
    assert _at(proj, tid, rn, 3) == "enter" and sent[2:] == ["Enter"]
    assert _at(proj, tid, rn, 5) is None  # once
    assert _at(proj, tid, rn, 61) == "enter" and sent[2:] == ["Enter"] * 2  # the watchdog's last Enter
    assert _at(proj, tid, rn, 70) is None
    assert _at(proj, tid, rn, 91, end=lambda: ended.append(1)) == "gave_up"
    assert ended == [1] and sent[2:] == ["Enter"] * 2
    (back,) = runs.undelivered(proj, tid)
    assert back["id"] == item["id"] and back["live_retry"] is True  # never lost
    rec = runs.read(proj, tid)
    assert "submit" not in rec and rec["stop_requested"] and rec["pending"] is True and rec["live_retry"]
    assert "did not take the new input" in json.dumps(tickets.load(proj, tid)["history"])
    assert runs_live.check_submit(proj, tid, rn, now=time.time() + 300) is None  # once per item


def test_no_enter_when_the_box_is_empty_even_if_the_echo_shows_above_it(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, pane="")
    screen["pane"] = _screen("", above="> " + runs_live.notice_line(tid, False))
    for sec in (3, 61, 91, 300):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert sent[2:] == []


@pytest.mark.parametrize(
    "dialog",
    ["Do you want to proceed?\n❯ 1. Yes\n  2. No", "❯ 1. Yes, allow once", "Esc to cancel"],
)
def test_an_enter_never_answers_a_dialog(proj, run, monkeypatch, dialog):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, pane="")
    screen["pane"] = _screen(runs_live.notice_line(tid, False), below=dialog)
    for sec in (3, 61):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert sent[2:] == []


def test_a_dialog_anywhere_on_the_pane_blocks_the_enter(proj, run, monkeypatch):
    """Borders may come from the agent's own output: the dialog check never relies on the box rows."""
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, pane="")
    line = runs_live.notice_line(tid, False)
    screen["pane"] = "\n".join([B, "Do you want to proceed?", "❯ 1. Yes", B, _screen(line)])
    assert _at(proj, tid, rn, 3) is None and _at(proj, tid, rn, 61) is None and sent[2:] == []


def test_plain_words_in_the_agents_output_do_not_block(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, pane="")
    screen["pane"] = _screen(runs_live.notice_line(tid, False), above="Allow pets? (y/n) Do you want cake")
    assert _at(proj, tid, rn, 3) == "enter"


def test_the_screen_is_checked_again_right_before_the_key(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch, pane="")
    shots = iter([_screen(runs_live.notice_line(tid, False)), _screen("", below="Do you want to proceed?")])
    screen["pane"] = lambda: next(shots)
    assert _at(proj, tid, rn, 3) is None and sent[2:] == []


def test_no_enter_while_the_pane_is_in_copy_mode(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, mode="1")
    assert _at(proj, tid, rn, 3) is None and _at(proj, tid, rn, 61) is None and sent[2:] == []


def test_checks_that_cannot_tell_count_towards_the_give_up(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch, mode="1")  # copy mode, quiet
    assert _at(proj, tid, rn, 3) is None  # 1
    got = [_at(proj, tid, rn, 91 + i, end=lambda: None) for i in range(runs_live.NONE_POLLS - 1)]
    assert got[:-1] == [None] * (runs_live.NONE_POLLS - 2) and got[-1] == "gave_up" and sent[2:] == []


def test_never_give_up_while_the_pane_changes(proj, run, monkeypatch):
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch)
    assert _at(proj, tid, rn, 3) == "enter" and _at(proj, tid, rn, 61) == "enter"
    tick = iter(range(10_000))
    line = runs_live.notice_line(tid, False)
    screen["pane"] = lambda: _screen(line, above=f"spinner {next(tick)}")  # something still works
    for sec in (91, 95, 130, 200):
        assert _at(proj, tid, rn, sec, end=lambda: pytest.fail("ended")) is None
    assert runs.read(proj, tid)["submit"]
    assert "never goes quiet" in (runs.run_dir(proj) / "live-submit.log").read_text()


def test_reading_the_input_ends_the_check(proj, run, monkeypatch):
    tid, rn, item, sent, _ = _stuck(proj, run, monkeypatch)
    text, n = runs_live.read_input(proj, tid, rn)
    assert n == 1 and "- human:lume: Please add a rain plan." in text
    assert "submit" not in runs.read(proj, tid) and runs.undelivered(proj, tid) == []
    assert runs_live.check_submit(proj, tid, rn, now=time.time() + 200) is None and sent[2:] == []
    with pytest.raises(Exception, match="Another run"):
        runs_live.read_input(proj, tid, "r_someoneelse")


def test_a_prompt_hook_alone_does_not_count_as_read(proj, run, monkeypatch):
    tid, rn, _, _, _ = _stuck(proj, run, monkeypatch)
    runs_live.event(proj, "working", rn, tid, None)
    assert runs.read(proj, tid)["submit"] and len(runs.undelivered(proj, tid)) == 1


def test_a_notice_taken_but_never_read_ends_in_a_one_step_run(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch)
    runs_live._set_state(proj, tid, rn, "idle")  # it went idle without reading
    assert runs_live.deliver(proj, tid) == 1  # one more notice
    runs_live._set_state(proj, tid, rn, "idle")
    assert runs_live.deliver(proj, tid) == 0 and runs.read(proj, tid)["submit"]["stale"]
    assert sent.count(runs_live.notice_line(tid, False)) == 2
    assert runs_live.check_submit(proj, tid, rn, end=lambda: None) == "gave_up"
    (back,) = runs.undelivered(proj, tid)
    assert back["live_retry"] is True


@pytest.mark.slow
def test_the_agents_read_waits_for_a_running_check(proj, run, monkeypatch):
    """Decide and Enter happen under the run lock: `orch run input` (another process) goes after."""
    tid, rn, _, sent, screen = _stuck(proj, run, monkeypatch)
    line = runs_live.notice_line(tid, False)
    reader = []

    def pane():
        if not reader:
            reader.append(
                subprocess.Popen(
                    [sys.executable, "-m", "orch", "run", "input", tid],
                    cwd=proj, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                )
            )  # fmt: skip
            end = time.monotonic() + 3
            while reader[0].poll() is None and time.monotonic() < end:
                time.sleep(0.05)
            assert reader[0].poll() is None, "the read did not wait for the run lock"
        return _screen(line)

    screen["pane"] = pane
    assert _at(proj, tid, rn, 3) == "enter"
    out, _ = reader[0].communicate(timeout=20)
    assert "rain plan" in out and "submit" not in runs.read(proj, tid)


def test_after_stop_the_watcher_writes_nothing(proj, run, monkeypatch):
    tid, rn, _, sent, _ = _stuck(proj, run, monkeypatch)
    guard, stop = threading.Lock(), threading.Event()
    stop.set()
    before = runs.read(proj, tid)
    assert runs_live.check_submit(proj, tid, rn, now=_later(proj, tid, 3), guard=guard, stop=stop) is None
    assert runs.read(proj, tid) == before and sent[2:] == []


def test_the_sigterm_path_waits_for_the_watchers_check(proj, run, monkeypatch):
    tid, rn, _, _, _ = _stuck(proj, run, monkeypatch)
    current = {"guard": threading.Lock(), "stop": threading.Event()}
    current["guard"].acquire()  # a check is under way
    t = threading.Thread(target=runs.term_release, args=(proj, tid, rn, current))
    t.start()
    time.sleep(0.2)
    assert current["stop"].is_set() and t.is_alive()  # waits for the check before it releases the claim
    assert runs.read(proj, tid) is not None
    current["guard"].release()
    t.join(10)
    assert runs.read(proj, tid) is None
    runs._terminating = False


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
    tid, rn, _, _, _ = _stuck(proj, run, monkeypatch)
    items = runs._pending_read(proj, tid)
    for i in items:
        i["via"] = "start"  # the session's only input was its start prompt
    runs._pending_write(proj, tid, items)
    _give_up(proj, tid, rn)
    (note,) = runs.undelivered(proj, tid)
    assert note["live_retry"] is True and note["kind"] == "event"
    assert _start_modes(proj, tid, monkeypatch) == ["oneshot"]
