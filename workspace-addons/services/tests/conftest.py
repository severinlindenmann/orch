import json
import sys
from datetime import UTC, timedelta
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent

# The shared test clock (workspace/tests/testclock.py, ORCH-451; first made here for issue 1421): the page sees 12:00
# today in this computer's time and the fake service started at 10:00 the same day, so "Running since today 10:00"
# holds whatever hour CI runs.
sys.path.append(str(HERE.parents[2] / "workspace" / "tests"))
from testclock import Clock, at, real_today

NOW = at(12, day=real_today())
STARTED = (NOW - timedelta(hours=2)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))
CONTRACTS = HERE.parents[2] / "contracts"
WID = "0123456789abcdef0123456789abcdef"


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


@pytest.fixture(autouse=True)
def stored_keys(monkeypatch):
    """The key store of a test workspace is refused by the core (test install); tests give the scanner their own."""
    from orch import hider, phone_results

    needles: dict = {}
    monkeypatch.setattr(phone_results, "value_hider", lambda root: hider.Hider(dict(needles)))
    return needles


@pytest.fixture(autouse=True)
def quick_settle(request, monkeypatch):
    """A start counts as running at once, so tests do not wait for real; with the `clock` fixture (no real waits) the
    real hold applies (ORCH-1634)."""
    from orch_services import cli

    if "clock" not in request.fixturenames:
        monkeypatch.setattr(cli, "SETTLE_HOLD", 0.0)


@pytest.fixture(autouse=True)
def neutral_platform(monkeypatch):
    """Logs stay in the workspace unless a test pretends to be a Mac (the tests run on macOS, Linux and Windows)."""
    from orch_services import store

    monkeypatch.setattr(store, "_platform", lambda: "linux")


@pytest.fixture(autouse=True)
def no_port_owner(monkeypatch):
    """Who listens on a port is read with lsof; tests say it themselves (the fake service's pid 4242 is no process)."""
    from orch_services import watch

    monkeypatch.setattr(watch, "listeners", lambda port: None)


class FakeDriver:
    """Keeps the platform entries in memory and writes the entry file under HOME like a real driver would."""

    name = "fake"

    def __init__(self):
        self.entries: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.unavailable: str | None = None
        self.run_counts: dict[
            str, int
        ] = {}  # sid -> starts so far (launchd `runs`); none = the tool cannot say
        self.start_polls = 0  # a slow start: status says "starting" this many times, then running
        self.start_dies = False  # a job that never comes up and is not launching either

    def check(self):
        from orch_services.drivers import Unavailable

        if self.unavailable:
            raise Unavailable(self.unavailable)

    def entry_path(self, spec):
        return Path.home() / "fake-services" / f"{spec.workspace_id}.{spec.sid}"

    def install(self, spec):
        self.calls.append(("install", spec.sid))
        p = self.entry_path(spec)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(spec.argv), encoding="utf-8")
        self.entries[spec.sid] = {"running": False, "auto": spec.auto, "spec": spec}

    def start(self, spec):
        self.calls.append(("start", spec.sid))
        self.entries[spec.sid]["running"] = not self.start_dies
        self.entries[spec.sid]["polls"] = self.start_polls

    def stop(self, spec):
        self.calls.append(("stop", spec.sid))
        self.entries[spec.sid]["running"] = False

    def restart(self, spec):
        self.calls.append(("restart", spec.sid))
        self.entries[spec.sid]["running"] = True

    def set_auto(self, spec):
        self.calls.append(("auto", spec.sid))
        self.entries[spec.sid]["auto"] = spec.auto

    def status(self, spec):
        from orch_services.drivers import Status

        e = self.entries.get(spec.sid)
        if e and e.get("polls"):
            e["polls"] -= 1
            return Status(running=False, starting=True)
        on = bool(e and e["running"])
        return Status(running=on, pid=4242 if on else None, since=STARTED if on else None)

    def runs(self, spec):
        return self.run_counts.get(spec.sid)

    def uninstall(self, spec):
        self.calls.append(("uninstall", spec.sid))
        self.entries.pop(spec.sid, None)
        self.entry_path(spec).unlink(missing_ok=True)


@pytest.fixture
def fake(monkeypatch):
    from orch_services import drivers, view

    d = FakeDriver()
    monkeypatch.setattr(drivers, "get", lambda: d)
    Clock(NOW).patch(monkeypatch, view)  # the page's "today" comes from the shared test clock
    return d


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "wörk space"  # R1.6: spaces and umlauts in every path
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / ".local-id").write_text(WID + "\n", encoding="utf-8")
    (root / ".orch" / "tickets" / "t_abc123.json").write_text(
        json.dumps({"id": "t_abc123", "key": "DM1-12"}), encoding="utf-8"
    )
    monkeypatch.setenv("ORCH_ROOT", str(root))
    return root


@pytest.fixture
def cli(ws, fake, capsys):
    from orch_services.cli import main

    def run(*argv):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def jrun(cli, *argv):
    if "--" in argv:
        i = argv.index("--")
        argv = (*argv[:i], "--json", *argv[i:])
    else:
        argv = (*argv, "--json")
    code, out, _ = cli(*argv)
    return code, json.loads(out)


def validator(schema_path):
    import jsonschema

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
