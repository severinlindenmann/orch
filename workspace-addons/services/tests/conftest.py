import json
import sys
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
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
        self.entries[spec.sid]["running"] = True

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
        on = bool(e and e["running"])
        return Status(running=on, pid=4242 if on else None, since="2026-11-17T10:00:00Z" if on else None)

    def runs(self, spec):
        return self.run_counts.get(spec.sid)

    def uninstall(self, spec):
        self.calls.append(("uninstall", spec.sid))
        self.entries.pop(spec.sid, None)
        self.entry_path(spec).unlink(missing_ok=True)


@pytest.fixture
def fake(monkeypatch):
    from orch_services import drivers

    d = FakeDriver()
    monkeypatch.setattr(drivers, "get", lambda: d)
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
