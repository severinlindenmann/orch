import json
import os
from pathlib import Path

import pytest

from orch import cli

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.delenv("ORCH_AGENT", raising=False)
    for k in list(os.environ):
        if k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("ORCH_HOME", str(tmp_path / "_orchhome"))
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


@pytest.fixture
def pub(proj, run):
    from fakes import make_publish

    srv = make_publish()
    yield srv
    srv.stop()


@pytest.fixture
def rel(proj, run):
    from fakes import make_relay

    srv = make_relay()
    yield srv
    srv.stop()
