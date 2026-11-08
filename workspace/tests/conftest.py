import json
import os
import sys
from pathlib import Path

import pytest

from orch import addons, cli, winfinish

_REAL_HOME_FN = addons.real_home  # the true one, before any test fakes it
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def _snapshot_real_tool_home():
    base = _REAL_HOME_FN() / ".orch-tool"
    out = {}
    if base.exists():
        for p in (base, *base.rglob("*")):
            if p.name.startswith(".fallback-trace.log"):  # the one-line trace of a fallback: allowed
                continue
            try:
                out[str(p)] = p.stat().st_mtime_ns
            except OSError:
                out[str(p)] = None
    return out


_REAL_TOOL_HOME_AT_START = _snapshot_real_tool_home()


@pytest.fixture(autouse=True)
def _strict_orch_home(monkeypatch, tmp_path_factory):
    """Every test: a faked real home with its own ORCH_HOME (a test that never asked for `proj` used to write
    the real ~/.orch-tool/addons.json: ORCH_HOME unset = real folder); untrusted ORCH_HOME = error."""
    fake = tmp_path_factory.mktemp("realhome")
    monkeypatch.setattr(addons, "real_home", lambda: fake)
    monkeypatch.setenv("ORCH_HOME", str(fake / "toolhome"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workerinput"):  # xdist worker: the controller checks
        return
    """Read-only guard: the real ~/.orch-tool must look the same after the run as before it. (xdist workers
    check too; another process may touch it in the meantime, so a hit names the time, not a culprit.)"""
    now = _snapshot_real_tool_home()
    if now != _REAL_TOOL_HOME_AT_START:
        changed = sorted(
            k
            for k in set(now) | set(_REAL_TOOL_HOME_AT_START)
            if now.get(k) != _REAL_TOOL_HOME_AT_START.get(k)
        )
        print(f"\nREAL ~/.orch-tool CHANGED during the test session: {changed}", file=sys.stderr)
        session.exitstatus = 1


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    for k in list(os.environ):
        if k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    fake_home = tmp_path.parent / f"{tmp_path.name}_home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setattr(addons, "real_home", lambda: fake_home)
    monkeypatch.setenv("ORCH_HOME", str(fake_home / "orchhome"))
    # an agent tool's own settings (a live start marks the folder trusted there): never the real ones
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fake_home))
    # Windows finishes add-on installs and updates in a background process (winfinish), which tests can not
    # wait for: they run the same steps in the command itself, as on other systems. test_winfinish.py covers
    # the background path (it sets needed() itself), the Windows e2e flows cover it for real.
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    return tmp_path


@pytest.fixture
def subprocess_home(proj, monkeypatch):
    """For tests that start `orch` as a child process: it cannot see the faked real_home, so ORCH_HOME must
    be a folder the child trusts too: a fresh one under ~/.orch-test (never ~/.orch-tool), removed by path."""
    import shutil
    import tempfile

    base = _REAL_HOME_FN() / ".orch-test"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="pytest-", dir=base))
    monkeypatch.setattr(addons, "real_home", _REAL_HOME_FN)
    monkeypatch.setenv("ORCH_HOME", str(d))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def run(capsys):
    def _run(*argv):
        code = cli.main(list(argv))
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return _run


@pytest.fixture
def validate():
    import jsonschema

    schema = json.loads((CONTRACTS / "ticket.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())

    def _v(ticket):
        errs = sorted(v.iter_errors(ticket), key=lambda e: list(e.path))
        assert not errs, [f"{list(e.path)}: {e.message}" for e in errs]

    return _v


@pytest.fixture
def new_ticket(proj, run):
    def _n(title="Do the thing"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "human:tester")
        assert code == 0
        return json.loads(out)["id"]

    return _n


def turn_on(root, name):
    """`orch addon add <name> --yes` for the built-in publish/relay add-ons, output swallowed."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        addons.add(root, name, yes=True)


@pytest.fixture
def pub(proj, run):
    from fakes import make_publish

    turn_on(proj, "publish")
    srv = make_publish()
    yield srv
    srv.stop()


@pytest.fixture
def rel(proj, run):
    from fakes import make_relay

    turn_on(proj, "relay")
    srv = make_relay()
    yield srv
    srv.stop()
