"""ORCH-634: no process per read. With ten helpers working, the dashboard, the Factory watcher and Focus
started several hundred `orch ... --json` reads a minute (the watcher alone about 200 `orch record query`),
each a new Python that loads about 400 modules and reads every ticket or run file; the machine's load stayed
at 35-45. Now a long-running caller answers reads in its own process (orch.reads) or through its one read
worker (orch.readworker), started once. These tests count every process this Python starts during one
dashboard poll and one Factory watcher round: none."""

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from orch import addons, cli, readworker

ADDONS = Path(__file__).resolve().parents[2] / "workspace-addons"
for name in ("dashboard", "factory"):
    sys.path.insert(0, str(ADDONS / name / "src"))
pytest.importorskip("orch_dashboard.data")
pytest.importorskip("orch_factory.watch")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="same_orch reads a POSIX console script")


@pytest.fixture
def starts(monkeypatch):
    """Every process this Python starts through subprocess (run, Popen and check_output all end here)."""
    seen = []
    real = subprocess.Popen._execute_child

    def counting(self, args, *rest, **kw):
        seen.append(args if isinstance(args, str) else " ".join(map(str, args)))
        return real(self, args, *rest, **kw)

    monkeypatch.setattr(subprocess.Popen, "_execute_child", counting)
    return seen


@pytest.fixture
def child_env(proj, subprocess_home, monkeypatch, capsys):
    """A workspace whose child orch processes (the read worker, a write) trust the same test home."""
    for k in ("ORCH_ROOT", "ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["init", "--json"]) == 0, capsys.readouterr()
    capsys.readouterr()
    monkeypatch.setenv("ORCH_ROOT", str(proj))
    readworker.stop_all()
    yield proj
    readworker.stop_all()


def _new(title):
    code = cli.main(["ticket", "new", title, "--json", "--by", "agent:x"])
    assert code == 0


def test_one_dashboard_poll_starts_no_process(child_env, starts, capsys):
    from orch_dashboard import data
    from orch_dashboard.data import SELF

    root = child_env
    for title in ("Write the offer", "Call the printer", "Plan the summer party"):
        _new(title)
    capsys.readouterr()
    data.load_state(root, SELF, with_settings=True, fresh=True)  # the first poll starts the read worker(s)
    assert any("orch.readworker" in s for s in starts), starts
    starts.clear()
    before = dict(data.READS)
    state = data.load_state(root, SELF, with_settings=True, fresh=True)
    assert starts == [], starts  # the next poll: not one process
    assert data.READS["process"] == before["process"]
    assert data.READS["here"] + data.READS["worker"] > before["here"] + before["worker"]
    assert {"Write the offer", "Call the printer"} <= {t["title"] for t in state["tickets"]}


@pytest.fixture
def factory_ws(child_env, tmp_path, monkeypatch, capsys):
    """A real workspace with the real core as ORCH_BIN and a started Factory order with one crew task done,
    so a
    watcher round derives the order and measures its active time from the record (the read it made ~200 times
    a minute)."""
    from orch_factory import cli as fcli

    root = child_env
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    orch = bin_dir / "orch"
    orch.write_text(f"#!{sys.executable}\nimport sys\nfrom orch_entry import main\nsys.exit(main())\n")
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ORCH_BIN", str(orch))
    real_active = addons.active
    monkeypatch.setattr(addons, "active", lambda r, *a, **k: [*real_active(r, *a, **k), "factory"])
    contracts = Path(__file__).resolve().parents[2] / "contracts"
    p = json.loads((contracts / "examples/factory-proposal/valid-run.json").read_text())
    p["line"] = [
        {"stage": "build", "stop": True, "why": "You judge the look."},
        {"stage": "ship", "stop": True, "why": "You decide whether it goes live."},
    ]
    p["tasks"] = [
        {"slug": "booking-form", "title": "Booking form", "role": "builder", "stage": "build", "proves": [0]},
        {"slug": "release", "title": "Prepare the release", "role": "builder", "stage": "ship"},
    ]
    (tmp_path / "proposal.json").write_text(json.dumps(p))

    def factory(*argv):
        capsys.readouterr()
        code = fcli.main([*argv, "--json"])
        out = capsys.readouterr().out
        assert code in (0, None), out
        return json.loads(out)

    order = factory("idea", "Booking page")["order"]
    q = factory("propose", order, "--file", str(tmp_path / "proposal.json"))["question"]
    assert cli.main(["answer", order, q, "Start", "--json", "--by", "human:anna"]) == 0
    factory("next", order)  # the manager took the answer: a watcher round has nothing to wake
    capsys.readouterr()
    return root, order


def test_one_factory_watcher_round_starts_no_process(factory_ws, starts, capsys):
    from orch_factory import measure, orchcli, watch

    root, order = factory_ws
    real_measure = measure.active_minutes
    measured = []
    watch.MEASURE_EVERY = 0  # every round measures (the read that cost most)

    def counting(*a, **k):
        measured.append(a[1])
        return real_measure(*a, **k)

    measure.active_minutes = counting
    try:
        watch.once(root)  # a first round may start the read worker; it wakes the manager (a write: a process)
        starts.clear()
        before = dict(orchcli.READS)
        assert watch.once(root) == []  # nothing new: no wake, no write
        assert starts == [], starts
        assert orchcli.READS["process"] == before["process"]
        assert orchcli.READS["here"] > before["here"]
        assert measured and order in measured[-1]
    finally:
        measure.active_minutes = real_measure
