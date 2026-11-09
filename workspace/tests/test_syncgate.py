"""The sync write gate (.orch/run/sync.gate): writers wait for a live gate, a dead holder's gate is ignored,
readers retry invalid JSON and never rewrite."""

import json
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
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield p
    p.kill()
    p.wait()


def _write_gate(root, pid, start):
    g = syncgate.gate_path(root)
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text(json.dumps({"pid": pid, "start_time": start, "step_id": "s1"}), encoding="utf-8")


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
        assert json.loads(syncgate.gate_path(proj).read_text())["step_id"] == "x"


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
