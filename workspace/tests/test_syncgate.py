"""The sync write gate (.orch/run/sync.gate): writers wait for a live gate, a dead holder's gate is ignored,
readers retry invalid JSON and never rewrite."""

import contextlib
import errno
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from orch import procs, syncgate, tickets
from orch.errors import Refused


@pytest.fixture
def other():
    """A live process that is not us (its pid and start time go into the gate)."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "orch"])  # looks like orch
    yield p
    p.kill()
    p.wait()


def _write_gate(root, pid, start, step=True):
    g = syncgate.gate_path(root)
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text(json.dumps({"pid": pid, "start_time": start, "step_id": "s1"}), encoding="utf-8")
    sp = syncgate.step_path(root, "s1")
    sp.parent.mkdir(parents=True, exist_ok=True)
    if step:
        sp.write_text(json.dumps({"pid": pid, "step_id": "s1"}), encoding="utf-8")
    else:
        sp.unlink(missing_ok=True)


def _live_gate(root, p):
    _write_gate(root, p.pid, procs.pid_started(p.pid))


@pytest.fixture(autouse=True)
def fast_wait(monkeypatch):
    monkeypatch.setattr(syncgate, "WAIT_SECONDS", 0.3)


def _ticket(proj):
    return tickets.create(proj, "T", "human:t")["id"]


def _writers(proj, tid):
    """Every writer the gate covers, each a callable."""
    (proj / "f.txt").write_text("x")
    return {
        "apply_op": lambda: tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "hi")),
        "save": lambda: tickets.save(proj, tickets.load(proj, tid)),
        "create": lambda: tickets.create(proj, "N", "human:t"),
        "next_key": lambda: tickets.next_key(proj),
        "ensure_general": lambda: tickets.ensure_general(proj, "human:t"),
        "attach_file": lambda: tickets.attach_file(proj, tid, str(proj / "f.txt"), None, None),
        "files_dir": lambda: tickets.files_dir(proj, tid),
        "artifacts_dir": lambda: tickets.artifacts_dir(proj, tid),
        "attach": lambda: tickets.attach(proj, tid, "a.md", b"hello", "human:t"),
    }


NAMES = [
    "apply_op",
    "save",
    "create",
    "next_key",
    "ensure_general",
    "attach_file",
    "files_dir",
    "artifacts_dir",
    "attach",
]


@pytest.mark.parametrize("name", NAMES)
def test_writer_blocks_while_live_gate_held_then_proceeds(proj, other, name):
    tid = _ticket(proj)
    w = _writers(proj, tid)[name]
    before = {p: p.read_bytes() for p in (proj / ".orch").rglob("*") if p.is_file() and "run" not in p.parts}
    _live_gate(proj, other)
    with pytest.raises(Refused, match="syncing"):
        w()
    after = {p: p.read_bytes() for p in (proj / ".orch").rglob("*") if p.is_file() and "run" not in p.parts}
    assert after == before  # nothing written past the gate
    syncgate.gate_path(proj).unlink()
    w()


@pytest.mark.parametrize("how", ["pid-gone", "pid-reused"])
def test_dead_holders_gate_is_ignored(proj, other, how):
    tid = _ticket(proj)
    if how == "pid-gone":
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        _write_gate(proj, dead.pid, "2020-01-01T00:00:00Z")
    else:  # the pid is alive, but it is another process than the one that took the gate
        _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    assert syncgate.live_holder(proj) is None
    tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "ok"))


def test_gate_released_while_writer_waits(proj, other):
    tid = _ticket(proj)
    _live_gate(proj, other)
    started = threading.Event()
    done = {}

    def writer():
        started.set()
        syncgate.WAIT_SECONDS = 20
        tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "late"))
        done["ok"] = True

    th = threading.Thread(target=writer)
    th.start()
    started.wait()
    assert th.is_alive() or "ok" not in done
    syncgate.gate_path(proj).unlink()
    th.join(10)
    assert done.get("ok") and tickets.load(proj, tid)["history"][-1]["text"] == "late"


def test_own_process_passes_its_own_gate(proj):
    tid = _ticket(proj)
    with syncgate.hold(proj, "step"):
        assert syncgate.live_holder(proj) is None
        tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "in step"))
        with pytest.raises(Refused):
            with syncgate.hold(proj, "again"):
                pass
    assert not syncgate.gate_path(proj).exists()


def test_hold_refused_by_live_holder_and_takes_over_stale(proj, other):
    _live_gate(proj, other)
    with pytest.raises(Refused, match="already syncing"):
        with syncgate.hold(proj, "x"):
            pass
    assert json.loads(syncgate.gate_path(proj).read_text())["pid"] == other.pid  # untouched
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    with syncgate.hold(proj, "x"):
        assert json.loads(syncgate.gate_path(proj).read_text())["step_id"].startswith("x-")


def test_gate_held_by_another_process_blocks_subprocess_writer(proj):
    """Real second process: it holds the gate (its pid + start time), our write waits, then proceeds."""
    tid = _ticket(proj)
    code = (
        "import sys, pathlib; from orch import syncgate\n"
        "r = pathlib.Path(sys.argv[1])\n"
        "with syncgate.hold(r, 'child'):\n"
        "    print('held', flush=True); sys.stdin.readline()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(proj)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(Refused, match="syncing"):
            tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "x"))
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(10)
        tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "after"))
    finally:
        child.kill()
        child.wait()


def test_reader_retries_invalid_json_and_never_rewrites(proj, other):
    tid = _ticket(proj)
    _live_gate(proj, other)  # retries happen only while a sync gate is live
    p = tickets.ticket_path(proj, tid)
    good = p.read_text()
    p.write_text("{ half")

    def fix():
        while not getattr(fix, "go", False):
            time.sleep(0.01)
        p.write_text(good)

    th = threading.Thread(target=fix)
    th.start()
    fix.go = True
    try:
        assert tickets.load(proj, tid)["id"] == tid  # retried until the swap landed
    finally:
        th.join()
    syncgate.gate_path(proj).unlink()
    p.write_text("{ still broken")
    t0 = time.monotonic()
    with pytest.raises(Refused, match="being updated"):
        tickets.load(proj, tid)
    assert time.monotonic() - t0 < 0.2  # no gate held: no retry delay
    assert p.read_text() == "{ still broken"  # read-only: not rewritten, quarantined or deleted
    assert tickets.list_all(proj) == []
    assert not list(p.parent.glob("*.bad*")) and p.exists()


def test_concurrent_writers_all_wait_for_gate_and_land(proj, other):
    tid = _ticket(proj)
    syncgate.WAIT_SECONDS = 20
    _live_gate(proj, other)
    n = 6
    errors, landed = [], []

    def w(i):
        try:
            tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", f"w{i}"))
            landed.append(i)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ths = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    for t in ths:
        t.start()
    # poll on state: while the gate is up, nothing lands
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        assert not landed
        time.sleep(0.02)
    syncgate.gate_path(proj).unlink()
    for t in ths:
        t.join(20)
    assert not errors and sorted(landed) == list(range(n))
    texts = [h["text"] for h in tickets.load(proj, tid)["history"]]
    assert sorted(x for x in texts if x.startswith("w")) == [f"w{i}" for i in range(n)]


def test_replace_retries_on_windows_only(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("1")
    syncgate.replace(a, b)
    assert b.read_text() == "1"
    calls = []

    def flaky(s, d):
        calls.append(1)
        raise PermissionError

    monkeypatch.setattr(syncgate.os, "replace", flaky)
    monkeypatch.setattr(syncgate, "REPLACE_DELAY", 0)
    with pytest.raises(PermissionError):
        syncgate.replace(a, b)
    assert len(calls) == 1  # not Windows: no retry
    monkeypatch.setattr(syncgate.os, "name", "nt")
    calls.clear()
    with pytest.raises(PermissionError):
        syncgate.replace(a, b)
    assert len(calls) == syncgate.REPLACE_TRIES


def test_list_all_with_many_invalid_files_returns_at_once(proj):
    good = _ticket(proj)
    for i in range(50):
        (tickets.tickets_dir(proj) / f"t_bad{i:04d}x.json").write_text("{ nope")
    t0 = time.monotonic()
    assert [t["id"] for t in tickets.list_all(proj)] == [good]
    assert time.monotonic() - t0 < 1.0


def test_fake_gates_are_ignored(proj, other):
    """No step record behind it, a holder that is not orch, or an unreadable file: stale, never a block."""
    tid = _ticket(proj)
    _write_gate(proj, other.pid, procs.pid_started(other.pid), step=False)  # fake: no step record
    assert syncgate.live_holder(proj) is None
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _write_gate(proj, sleeper.pid, procs.pid_started(sleeper.pid))  # live pid, but not an orch process
        assert syncgate.live_holder(proj) is None
    finally:
        sleeper.kill()
        sleeper.wait()
    for junk in ("", "{ half", "[1]"):
        syncgate.gate_path(proj).write_text(junk)
        old = time.time() - 60  # an unreadable file that is not fresh: nobody is mid-write
        os.utime(syncgate.gate_path(proj), (old, old))
        assert syncgate.live_holder(proj) is None
    tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "ok"))
    assert syncgate.clear_stale(proj) and not syncgate.gate_path(proj).exists()


def test_other_thread_of_the_holder_does_not_pass(proj, monkeypatch):
    monkeypatch.setattr(syncgate, "_looks_like_orch", lambda pid: True)  # the test runner is not `orch`
    tid = _ticket(proj)
    syncgate.WAIT_SECONDS = 0.2
    seen = {}
    with syncgate.hold(proj, "step"):
        # the sync step's own thread takes the ticket lock for the files it writes
        tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "merge"))

        def other_thread():
            try:
                tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "x"))
                seen["wrote"] = True
            except Refused as e:
                seen["err"] = str(e)

        th = threading.Thread(target=other_thread)
        th.start()
        th.join(10)
    assert "syncing" in seen.get("err", "") and "wrote" not in seen


def test_hold_finally_only_removes_its_own_gate(proj, other):
    with syncgate.hold(proj, "mine"):
        syncgate.gate_path(proj).unlink()
        _live_gate(proj, other)  # someone else's gate now sits there
    assert json.loads(syncgate.gate_path(proj).read_text())["pid"] == other.pid
    assert not syncgate.step_path(proj, "mine").exists()


def test_gate_taken_right_after_the_writers_check_is_refused(proj, other, monkeypatch):
    """TOCTOU: the gate appears after wait_clear passed: the re-check under the lock refuses the write."""
    tid = _ticket(proj)
    real = syncgate.wait_clear

    def check_then_gate(root, what="this", **kw):
        real(root, what, **kw)
        _live_gate(root, other)  # the sync step takes the gate right after our check

    monkeypatch.setattr(syncgate, "wait_clear", check_then_gate)
    before = tickets.ticket_path(proj, tid).read_bytes()
    with pytest.raises(Refused, match="syncing"):
        tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "late"))
    assert tickets.ticket_path(proj, tid).read_bytes() == before
    assert not (tickets.tickets_dir(proj) / f".lock-{tid}").exists()  # the lock was let go


def test_sync_step_waits_for_a_writer_inside_the_lock(proj):
    """The step takes the ticket lock under the gate: it cannot overlap a writer already inside."""
    tid = _ticket(proj)
    inside, release, order = threading.Event(), threading.Event(), []

    def writer():
        with tickets._locked(proj, tid):
            inside.set()
            release.wait(10)
            order.append("writer done")

    th = threading.Thread(target=writer)
    th.start()
    inside.wait(10)

    def step():
        with syncgate.hold(proj, "step"):
            with tickets._locked(proj, tid):
                order.append("step wrote")

    st = threading.Thread(target=step)
    st.start()
    deadline = time.monotonic() + 5
    while not syncgate.gate_path(proj).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert order == []  # gate held, but the step is waiting for the writer's lock
    release.set()
    th.join(10)
    st.join(10)
    assert order == ["writer done", "step wrote"]


def test_files_dir_locked_holds_the_lock_for_the_write(proj):
    tid = _ticket(proj)
    with tickets.files_dir_locked(proj, tid) as d:
        assert d.is_dir() and (tickets.tickets_dir(proj) / f".lock-{tid}").exists()
    assert not (tickets.tickets_dir(proj) / f".lock-{tid}").exists()


def test_refused_second_hold_leaves_the_live_step_alone(proj, monkeypatch):
    monkeypatch.setattr(syncgate, "_looks_like_orch", lambda pid: True)  # the test runner is not `orch`
    """A refused hold must not delete the live step's record: writers stay blocked."""
    tid = _ticket(proj)
    syncgate.WAIT_SECONDS = 0.2
    won = threading.Event()
    done = threading.Event()
    errs = []

    def first():
        with syncgate.hold(proj, "sync"):
            won.set()
            done.wait(20)

    th = threading.Thread(target=first)
    th.start()
    won.wait(10)
    try:
        # the winner is another thread of this process: a live gate for us, with its step record
        assert syncgate.live_holder(proj) is not None
        with pytest.raises(Refused, match="already syncing"):
            with syncgate.hold(proj, "sync"):
                pass
        steps = list(syncgate.step_path(proj, "x").parent.glob("step-*.json"))
        assert len(steps) == 1
        assert syncgate.live_holder(proj) is not None  # still live
        try:
            tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "x"))
        except Refused as e:
            errs.append(str(e))
        assert errs and "syncing" in errs[0]
    finally:
        done.set()
        th.join(10)
    assert not list(syncgate.step_path(proj, "x").parent.glob("step-*.json"))
    assert not syncgate.gate_path(proj).exists()


def test_fresh_empty_gate_counts_as_live_then_stale(proj):
    syncgate.gate_path(proj).parent.mkdir(parents=True, exist_ok=True)
    syncgate.gate_path(proj).write_text("")  # a no-links publisher between create and write
    assert syncgate.live_holder(proj) is not None
    with pytest.raises(Refused, match="already syncing"):
        with syncgate.hold(proj, "x"):
            pass
    old = time.time() - 60
    os.utime(syncgate.gate_path(proj), (old, old))
    assert syncgate.live_holder(proj) is None


@pytest.mark.parametrize(
    ("cmd", "want"),
    [
        ("/usr/bin/python -m orch ticket list", True),
        ("/Users/x/.local/bin/orch serve", True),
        ("python -P -m orch.__main__ x", True),
        ("C:\\x\\orch.exe run", True),
        ("python -m torch.distributed", False),
        ("/usr/bin/sleep 60", False),
    ],
)
def test_cmdline_matches_the_orch_program_not_a_substring(cmd, want):
    assert syncgate._cmd_is_orch(cmd) is want


@pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="Linux /proc only")
def test_identity_works_without_ps(proj, other, monkeypatch):
    """Minimal Linux containers have no `ps`: start time and command line come from /proc."""

    def no_ps(*a, **k):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(procs.subprocess, "run", no_ps)
    monkeypatch.setattr(syncgate.subprocess, "run", no_ps)
    assert procs.pid_started(other.pid) and syncgate._looks_like_orch(other.pid)
    _live_gate(proj, other)
    assert syncgate.live_holder(proj) is not None


def test_attach_works_without_dir_fds_and_never_self_deadlocks(proj, monkeypatch):
    """The fallback (Windows) and POSIX paths write inside the ticket lock without taking it twice."""
    tid = _ticket(proj)
    assert tickets.attach(proj, tid, "a.md", b"one", "human:t")["name"] == "a.md"
    monkeypatch.setattr(os, "supports_dir_fd", set())
    assert tickets.attach(proj, tid, "b.md", b"two", "human:t")["name"] == "b.md"
    assert (
        tickets.attach_file(proj, tid, str(proj / "a.md"), None, None) if (proj / "a.md").exists() else True
    )


def test_attach_history_line_is_not_lost_when_apply_op_was_busy(proj, other, monkeypatch):
    tid = _ticket(proj)
    syncgate.WAIT_SECONDS = 0.2
    real = tickets.apply_op
    state = {"n": 0}

    def flaky(root, t, fn, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise syncgate.busy("ticket")
        return real(root, t, fn, **kw)

    monkeypatch.setattr(tickets, "apply_op", flaky)
    with pytest.raises(Refused, match="syncing"):
        tickets.attach(proj, tid, "x.md", b"hi", "human:t", exact="x.md")
    assert (tickets.artifacts_dir(proj, tid) / "x.md").exists()
    r = tickets.attach(proj, tid, "x.md", b"hi", "human:t", exact="x.md")  # the retry
    assert r["existed"] is True
    assert [h["text"] for h in tickets.load(proj, tid)["history"]].count("Attached x.md") == 1
    tickets.attach(proj, tid, "x.md", b"hi", "human:t", exact="x.md")  # and not twice
    assert [h["text"] for h in tickets.load(proj, tid)["history"]].count("Attached x.md") == 1


def test_ps_comes_first_and_proc_is_the_fallback(monkeypatch):
    """ps values stay what they were; /proc only answers when ps is missing or empty."""

    class R:
        stdout = "Mon Nov  9 15:00:00 2026"

    monkeypatch.setattr(procs.os, "name", "posix")
    monkeypatch.setattr(procs, "_proc_started", lambda pid: "2026-01-01T00:00:00Z")
    monkeypatch.setattr(procs.subprocess, "run", lambda *a, **k: R())
    assert procs.pid_started(4242) not in (None, "2026-01-01T00:00:00Z")
    R.stdout = ""
    assert procs.pid_started(4242) == "2026-01-01T00:00:00Z"

    def no_ps(*a, **k):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(procs.subprocess, "run", no_ps)
    assert procs.pid_started(4242) == "2026-01-01T00:00:00Z"


def test_same_start_tolerates_two_seconds_for_all_values():
    a = "2026-11-09T15:00:00Z"
    assert procs.same_start(a, a)
    assert procs.same_start(a, "2026-11-09T15:00:02Z")
    assert not procs.same_start(a, "2026-11-09T15:00:03Z")
    assert not procs.same_start(a, "2026-11-09T14:59:56Z")
    assert not procs.same_start(a, None) and not procs.same_start(a, "garbage")


def test_takeover_never_removes_a_live_gate_published_meanwhile(proj, monkeypatch):
    """X judges gate G stale and pauses; Y takes G over and holds G2. X's takeover must not move G2 away:
    G2 stays in place the whole time, writers never see "no gate", and X is refused."""
    monkeypatch.setattr(syncgate, "_looks_like_orch", lambda pid: True)  # the test runner is not `orch`
    tid = _ticket(proj)
    _write_gate(proj, os.getpid(), "2020-01-01T00:00:00Z")  # our pid, another start time: stale
    gate = syncgate.gate_path(proj)
    moved = []
    real_replace = os.replace

    def spy_replace(src, dst, *a, **k):
        if os.path.abspath(src) == os.path.abspath(gate):
            with contextlib.suppress(OSError):
                moved.append(gate.read_text(encoding="utf-8"))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(syncgate.os, "replace", spy_replace)
    real_take = syncgate._take_stale
    x_judged, y_holds, go_x, y_release, stop = (threading.Event() for _ in range(5))
    state = {}

    def paused_take(*a, **k):
        if threading.current_thread().name == "X":
            x_judged.set()
            go_x.wait(10)  # Y takes over and publishes G2 while X sits between judging and renaming
        return real_take(*a, **k)

    monkeypatch.setattr(syncgate, "_take_stale", paused_take)

    def x():
        try:
            with syncgate.hold(proj, "x"):
                state["x"] = "held"
        except Refused as e:
            state["x"] = str(e)

    def y():
        with syncgate.hold(proj, "y"):
            state["g2"] = gate.read_text(encoding="utf-8")
            y_holds.set()
            y_release.wait(10)
            with tickets.sync_apply(proj, tid):  # its gate is still its own: the batch may write
                state["y_wrote"] = True

    gaps = []

    def watcher():
        while not stop.is_set():
            if syncgate.live_holder(proj) is None:
                gaps.append(1)
            time.sleep(0.001)

    tx = threading.Thread(target=x, name="X")
    tx.start()
    assert x_judged.wait(10)
    ty = threading.Thread(target=y, name="Y")
    ty.start()
    assert y_holds.wait(10)
    tw = threading.Thread(target=watcher)
    tw.start()
    try:
        time.sleep(0.02)  # the watcher is polling before X goes on
        go_x.set()
        tx.join(10)
        assert "already syncing" in state["x"]
        assert gate.read_text(encoding="utf-8") == state["g2"]  # Y's gate untouched
        with pytest.raises(Refused, match="syncing"):  # a writer still waits for Y
            tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, "human:t", "x"))
    finally:
        stop.set()
        tw.join(10)
        y_release.set()
        ty.join(10)
    assert not gaps  # writers never saw "no gate" while Y held it
    assert state["g2"] not in moved  # the live gate was never renamed away, not even for a moment
    assert state.get("y_wrote") and not gate.exists()


def test_takeover_gives_up_when_the_gate_changed_since_it_was_judged(proj, other):
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    seen, live = syncgate._judge(proj)
    assert seen is not None and not live
    _live_gate(proj, other)  # replaced by a live holder's gate meanwhile
    assert not syncgate._take_stale(proj, seen)
    assert syncgate.live_holder(proj)["pid"] == other.pid
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    seen, _ = syncgate._judge(proj)
    assert syncgate._take_stale(proj, seen) and not syncgate.gate_path(proj).exists()


def _lock_dir(root, token, name="owner-0123456789abcdef"):
    """A gate lock as another process leaves it: the directory with its one owner file."""
    lk = syncgate.lock_path(root)
    lk.mkdir(parents=True)
    (lk / name).write_text(token)
    return lk


def test_takeover_lock_of_a_gone_owner_is_broken_a_live_one_waited_for(proj, other, monkeypatch):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    lk = _lock_dir(proj, f"{dead.pid} 2020-01-01T00:00:00Z x 1")
    with syncgate.hold(proj, "x"):
        assert json.loads(syncgate.gate_path(proj).read_text())["step_id"].startswith("x-")
    assert not lk.exists()
    monkeypatch.setattr(syncgate, "TAKEOVER_WAIT", 0.1)
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    _lock_dir(proj, f"{other.pid} {procs.pid_started(other.pid)} x 1")  # a live takeover in progress
    with pytest.raises(Refused, match="could not take"):
        with syncgate.hold(proj, "x"):
            pass
    assert json.loads(syncgate.gate_path(proj).read_text())["pid"] == other.pid  # left alone
    assert [p.name for p in lk.iterdir()] == ["owner-0123456789abcdef"]


def test_holder_refuses_its_write_batch_once_the_gate_is_not_its_own(proj):
    tid = _ticket(proj)
    with syncgate.hold(proj, "step"):
        with tickets.sync_apply(proj, tid):
            pass
        syncgate.gate_path(proj).unlink()  # taken over / removed behind its back
        with pytest.raises(Refused, match="lost the sync gate"):
            with tickets.sync_apply(proj, tid):
                pytest.fail("wrote without the gate")
    with pytest.raises(Refused, match="not holding the sync gate"):  # holding no gate: fail closed
        with tickets.sync_apply(proj, tid):
            pytest.fail("wrote without holding the gate")


def test_leftover_step_records_of_gone_holders_are_cleaned(proj, other):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    d = syncgate.step_path(proj, "x").parent
    d.mkdir(parents=True, exist_ok=True)
    recs = {
        "step-dead.json": {"pid": dead.pid, "step_id": "dead"},
        "step-reused.json": {"pid": other.pid, "step_id": "reused", "start_time": "2020-01-01T00:00:00Z"},
        "step-live.json": {"pid": other.pid, "step_id": "live", "start_time": procs.pid_started(other.pid)},
        "step-old-live.json": {"pid": other.pid, "step_id": "old-live"},
    }
    for name, rec in recs.items():
        (d / name).write_text(json.dumps(rec))
    (d / "step-garbled.json").write_text("{ half")
    (d / "state.json").write_text(json.dumps({"pid": dead.pid}))
    with syncgate.hold(proj, "x"):
        pass
    left = sorted(p.name for p in d.iterdir())
    assert left == ["state.json", "step-garbled.json", "step-live.json", "step-old-live.json"]


def test_proc_boot_time_is_read_once(monkeypatch):
    if not os.path.exists("/proc/self/stat"):
        pytest.skip("Linux /proc only")
    monkeypatch.setattr(procs, "_btime", None)
    first = procs._proc_started(os.getpid())
    real_open = open

    def no_stat(path, *a, **k):
        if path == "/proc/stat":
            raise AssertionError("btime must be cached")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", no_stat)
    assert procs._proc_started(os.getpid()) == first and "~" not in first and first.endswith("Z")


@pytest.fixture
def no_links(monkeypatch):
    """A filesystem without hard links (FAT/exFAT, some SMB): every os.link fails."""

    def refuse(*a, **k):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", refuse)


def test_no_links_the_gate_is_never_seen_empty_or_half(proj, no_links, monkeypatch):
    monkeypatch.setattr(syncgate, "_looks_like_orch", lambda pid: True)  # the test runner is not `orch`
    gate = syncgate.gate_path(proj)
    stop, bad, seen = threading.Event(), [], []

    def watcher():
        while not stop.is_set():
            snap = syncgate._snapshot(gate)
            if snap is not None:
                seen.append(1)
                if syncgate._parse(snap[0]) is None:
                    bad.append(snap[0])

    tw = threading.Thread(target=watcher)
    tw.start()
    try:
        for i in range(30):
            with syncgate.hold(proj, f"h{i}"):
                assert json.loads(gate.read_text())["step_id"].startswith(f"h{i}-")
    finally:
        stop.set()
        tw.join(10)
    assert seen and not bad  # the watcher saw gates, never an empty or partial one
    assert not gate.exists() and not syncgate.lock_path(proj).exists()
    assert sorted(p.name for p in gate.parent.iterdir()) == ["sync"]  # no temp files or lock dirs left


def test_no_links_takeover_is_compare_and_swap(proj, other, no_links):
    """Without links: a stale gate is taken over, and a gate that changed since it was judged is left in
    place, the same file (nothing moved away and put back)."""
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    with syncgate.hold(proj, "x"):
        assert json.loads(syncgate.gate_path(proj).read_text())["step_id"].startswith("x-")
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")
    seen, live = syncgate._judge(proj)
    assert seen is not None and not live
    _live_gate(proj, other)  # a live holder's gate now
    before = syncgate._snapshot(syncgate.gate_path(proj))
    assert not syncgate._take_stale(proj, seen)
    assert syncgate._snapshot(syncgate.gate_path(proj)) == before  # same bytes, same inode
    assert syncgate.live_holder(proj)["pid"] == other.pid


def test_filesystem_without_directory_renames_fails_closed(proj, other, monkeypatch):
    """When the gate lock cannot be made the hold is refused: no gate, no sync, nothing left behind."""
    monkeypatch.setattr(syncgate, "TAKEOVER_WAIT", 0.1)
    real_rename = os.rename

    def no_dir_rename(src, dst, *a, **k):
        if os.path.isdir(src):
            raise OSError(errno.EPERM, "Operation not permitted")
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", no_dir_rename)
    with pytest.raises(Refused, match="could not take"):
        with syncgate.hold(proj, "x"):
            pytest.fail("held without a gate lock")
    assert not syncgate.gate_path(proj).exists()
    assert not list(syncgate.step_path(proj, "x").parent.glob("step-*.json"))
    assert sorted(p.name for p in syncgate.gate_path(proj).parent.iterdir()) == ["sync"]
    _write_gate(proj, other.pid, "2020-01-01T00:00:00Z")  # a stale gate is not taken over either
    with pytest.raises(Refused, match="could not take"):
        with syncgate.hold(proj, "x"):
            pytest.fail("took over without a gate lock")
    assert json.loads(syncgate.gate_path(proj).read_text())["pid"] == other.pid


def test_breaking_a_dead_lock_never_touches_a_newer_one(proj, other, no_links):
    """A lock judged dead and replaced meanwhile by a live one: the break removes only the judged owner file
    (by its unique name), so the live lock stays whole."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lk = _lock_dir(proj, f"{dead.pid} 2020-01-01T00:00:00Z ab 1", name="owner-1111111111111111")
    judged = syncgate._lock_owner(lk)
    assert judged == "owner-1111111111111111"
    (lk / judged).unlink()  # another breaker got there first, and a live lock was taken right after
    lk.rmdir()
    _lock_dir(proj, f"{other.pid} {procs.pid_started(other.pid)} ab 1", name="owner-2222222222222222")
    assert syncgate._lock_owner(lk) is None  # live: not to be broken
    syncgate._break(lk, judged)
    assert [p.name for p in lk.iterdir()] == ["owner-2222222222222222"]


def test_gate_lock_backs_off_when_a_break_keeps_failing(proj, monkeypatch):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _lock_dir(proj, f"{dead.pid} 2020-01-01T00:00:00Z ab 1")
    monkeypatch.setattr(syncgate, "TAKEOVER_WAIT", 0.3)
    monkeypatch.setattr(syncgate, "_break", lambda lk, name: None)  # e.g. Windows: the owner file is open
    tries = []
    real_try = syncgate._lock_try
    monkeypatch.setattr(syncgate, "_lock_try", lambda lk, token: tries.append(1) or real_try(lk, token))
    with syncgate._gate_lock(proj) as ok:
        assert not ok
    assert 2 <= len(tries) < 20  # retried with growing pauses, no busy spin


def test_ensure_held_matches_a_symlinked_root_and_refuses_a_thread_without_gate(proj):
    alias = proj.parent / f"{proj.name}_alias"
    try:
        alias.symlink_to(proj, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    tid = _ticket(proj)
    with syncgate.hold(proj, "step"):
        with tickets.sync_apply(alias, tid):  # the same gate under another spelling: checked, and ours
            pass
        syncgate.gate_path(proj).unlink()  # lost behind its back
        with pytest.raises(Refused, match="lost the sync gate"):
            with tickets.sync_apply(alias, tid):
                pytest.fail("wrote without the gate (alias not matched)")
    with syncgate.hold(alias, "step"):
        with tickets.sync_apply(proj, tid):
            pass
    with pytest.raises(Refused, match="not holding the sync gate"):
        syncgate.ensure_held(alias)


def test_release_never_races_a_takeover(proj, monkeypatch):
    """A takeover between its compare and its remove holds the gate lock: the holder's release waits for it,
    so the gate never vanishes under the takeover's feet and no third holder can slip into a gap."""
    monkeypatch.setattr(syncgate, "_looks_like_orch", lambda pid: True)  # the test runner is not `orch`
    gate = syncgate.gate_path(proj)
    h_in, h_go, t_in, t_go = (threading.Event() for _ in range(4))
    state = {}

    def holder():
        with syncgate.hold(proj, "h"):
            state["g1"] = gate.read_text(encoding="utf-8")
            h_in.set()
            h_go.wait(10)
        state["h_done"] = True

    th = threading.Thread(target=holder, name="H")
    th.start()
    assert h_in.wait(10)
    seen = syncgate._snapshot(gate)  # T judged G1 stale (wrongly, say)
    real_snap = syncgate._snapshot

    def paused(p):
        r = real_snap(p)
        if threading.current_thread().name == "T" and p == gate:
            t_in.set()
            t_go.wait(10)  # inside the gate lock, between compare and remove
        return r

    monkeypatch.setattr(syncgate, "_snapshot", paused)
    tt = threading.Thread(target=lambda: state.update(took=syncgate._take_stale(proj, seen)), name="T")
    tt.start()
    try:
        assert t_in.wait(10)
        h_go.set()  # the holder releases now
        time.sleep(0.3)
        assert th.is_alive() and "h_done" not in state  # the release waits for the gate lock
        assert gate.read_text(encoding="utf-8") == state["g1"]  # nothing removed past the takeover
        assert syncgate.lock_path(proj).is_dir()
    finally:
        t_go.set()
        tt.join(10)
        th.join(10)
    assert state["took"] is True and state["h_done"]
    assert not gate.exists() and not syncgate.lock_path(proj).exists()
    with syncgate.hold(proj, "n"):  # exactly one holder afterwards
        assert json.loads(gate.read_text())["step_id"].startswith("n-")
        assert not syncgate._take_stale(proj, seen)  # G1's snapshot never matches the new gate


def test_owner_dead_reads_the_lock_token_with_its_extra_fields(other):
    """The gate lock's token is own_token + nonce + thread: the extra fields never make a live owner dead."""
    mine = f"{procs.own_token()} {syncgate._NONCE} {threading.get_ident()}"
    assert len(mine.split()) == 4
    assert not procs.owner_dead(mine)
    assert not procs.owner_dead(f"{other.pid} {procs.pid_started(other.pid)} 0123456789abcdef 140000000")
    assert not procs.owner_dead(f"{other.pid} - 0123456789abcdef 1")  # start unknown: alive
    assert procs.owner_dead(f"{other.pid} 2020-01-01T00:00:00Z ab 1")  # pid reused by another process
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    assert procs.owner_dead(f"{dead.pid} 2020-01-01T00:00:00Z ab 1")
    assert not procs.owner_dead("garbage ab 1") and not procs.owner_dead("")
