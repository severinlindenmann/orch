import json
import os
import stat
import sys
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))
sys.path.insert(0, str(HERE.parent / "src"))
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
    (root / ".orch" / "tickets" / "t_abc123.json").write_text(
        json.dumps({"id": "t_abc123", "key": "DM1-12", "title": "Offerte Helvetia v2", "status": "active"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCH_ROOT", str(root))
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET", "ORCH_BIN", "CLAUDECODE", "CODEX_SANDBOX"):
        monkeypatch.delenv(k, raising=False)
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: os.environ.get("ORCH_AGENT") or None)
    monkeypatch.setattr(
        tickets, "resolve", lambda root, ref: "t_abc123" if ref in ("DM1-12", "t_abc123") else ref
    )
    return root


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Vault Severin"
    (v / "Projects").mkdir(parents=True)
    (v / "People").mkdir()
    (v / ".obsidian").mkdir()
    (v / "Projects" / "Helvetia Logistik.md").write_text(
        "Kunde seit 2024. Ansprechperson ist [[Petra Zingg]]. Siehe [[Preismodell 2027|Preise]].\n",
        encoding="utf-8",
    )
    (v / "Projects" / "Preismodell 2027.md").write_text(
        "Fixpreis. Gilt für [[Helvetia Logistik]].\n", encoding="utf-8"
    )
    (v / "People" / "Petra Zingg.md").write_text("Kundin bei Helvetia.\n", encoding="utf-8")
    return v


@pytest.fixture
def fake_orch(tmp_path, monkeypatch):
    """A fake `orch` for `ticket attach`: stores stdin under the ticket's artifacts and prints JSON."""
    log = tmp_path / "attach.log"
    script = tmp_path / "fake-orch"
    script.write_text(
        "#!" + sys.executable + "\n"
        "import json, sys, pathlib\n"
        "a = sys.argv[1:]\n"
        "data = sys.stdin.read()\n"
        f"pathlib.Path({str(log)!r}).write_text(json.dumps({{'argv': a, 'data': data}}), encoding='utf-8')\n"
        "print(json.dumps({'name': a[a.index('--name') + 1]}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ORCH_BIN", str(script))
    return log


@pytest.fixture
def cli(ws, capsys):
    from orch_personal.cli import main

    def run(*argv, stdin=None, monkeypatch=None):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def jrun(cli, *argv):
    code, out, _ = cli(*argv, "--json")
    return code, json.loads(out)


def as_helper(monkeypatch, ticket="t_abc123"):
    monkeypatch.setenv("ORCH_RUN", "r_test")
    monkeypatch.setenv("ORCH_AGENT", "claude")
    if ticket:
        monkeypatch.setenv("ORCH_TICKET", ticket)
