import json
import os
from pathlib import Path

import pytest

from orch import addons, cli, winfinish

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


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
    # An answer starts the asking agent again (fb9). Only the tests that set up a fake agent let that happen
    # (fixture `auto_resume`); anywhere else it would start the real agent tool found on this machine.
    from orch import runs_live

    monkeypatch.setattr(runs_live, "resume_after_answer", lambda *a, **k: None)
    return tmp_path


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
