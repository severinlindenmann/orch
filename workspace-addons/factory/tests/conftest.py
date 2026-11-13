import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ORCH_HOME", str(home / ".orch-tool"))
    root = tmp_path / "workspace"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.setenv("ORCH_ROOT", str(root))
    script = tmp_path / "orch"
    script.write_text(f"#!{sys.executable}\n" + Path(__file__).with_name("fake_orch.py").read_text())
    script.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(script))
    return root


@pytest.fixture
def proposal():
    return (CONTRACTS / "examples/factory-proposal/valid-run.json").read_bytes()


@pytest.fixture
def run(ws):
    def invoke(*args, data=None, code=0):
        result = subprocess.run(
            [sys.executable, "-m", "orch_factory", *args, "--json"],
            cwd=ws,
            input=data,
            capture_output=True,
            check=False,
            env=os.environ,
            timeout=30,
        )
        assert result.returncode == code, result.stderr.decode()
        value = json.loads(result.stdout)
        if code == 2:
            assert result.stderr.startswith(b"Refused: ") and value["error"] and value["code"]
        return value

    return invoke
