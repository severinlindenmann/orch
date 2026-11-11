"""Isolated home, contract answers, and a CLI-only fake workspace reader."""

import json
import sys
import threading
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
sys.path.insert(0, str(CONTRACTS.parent / "workspace" / "src"))


@pytest.fixture(autouse=True)
def test_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ORCH_HOME", str(home / ".orch-tool"))


@pytest.fixture
def answer():
    return json.loads((CONTRACTS / "examples/counts/valid-answer.json").read_text())


@pytest.fixture
def nothing():
    return json.loads((CONTRACTS / "examples/counts/valid-nothing-yet.json").read_text())


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    (root / ".orch").mkdir(parents=True)
    return root


@pytest.fixture
def fake_orch(tmp_path, answer):
    folder = tmp_path / "fake"
    folder.mkdir()
    (folder / "answer.json").write_text(json.dumps(answer))
    script = folder / "orch"
    script.write_text(
        f"""#!{sys.executable}
import json
import os
from pathlib import Path
import sys
folder = Path(__file__).parent
args = sys.argv[1:]
(folder / "call.json").write_text(json.dumps({{
    "args": args, "cwd": str(Path.cwd()), "root": os.environ.get("ORCH_ROOT"),
    "stdin": sys.stdin.read(),
}}))
assert args == ["record", "counts", "--days", "30", "--json"]
if (folder / "exit").exists():
    sys.exit(1)
print((folder / "answer.json").read_text())
"""
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def server(ws, fake_orch):
    from orch_insights.server import make_server

    srv = make_server(ws, 0, orch_bin=fake_orch)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
