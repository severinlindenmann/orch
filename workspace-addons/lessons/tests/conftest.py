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


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


@pytest.fixture(autouse=True)
def stored_keys(monkeypatch):
    """The key store of a test workspace is refused by the core (test install); tests give the scanner their own."""
    from orch import hider, phone_results

    needles: dict = {}
    monkeypatch.setattr(phone_results, "value_hider", lambda root: hider.Hider(dict(needles)))
    return needles


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / "harness" / "blocks").mkdir(parents=True)
    (root / ".orch" / "harness" / "blocks" / "addon-lessons.md").write_text(
        "## orch-lessons\nWrite lessons.\n", encoding="utf-8"
    )
    (root / ".orch" / "tickets" / "t_abc123.json").write_text(
        json.dumps({"id": "t_abc123", "key": "DM1-12"}), encoding="utf-8"
    )
    monkeypatch.setenv("ORCH_ROOT", str(root))
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    return root


@pytest.fixture
def cli(ws, capsys):
    from orch_lessons.cli import main

    def run(*argv):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def jrun(cli, *argv):
    code, out, _ = cli(*argv, "--json")
    return code, json.loads(out)


def validator(schema_path, ref=None):
    import jsonschema

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    if ref:
        schema = {
            "$ref": ref,
            "$defs": schema.get("$defs", {}),
            **{k: v for k, v in schema.items() if k == "$schema"},
        }
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
