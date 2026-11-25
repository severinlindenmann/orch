"""The guard that keeps every test away from the real agent tools (agent_guard.py, wired in conftest)."""

import os
import shutil
import subprocess
import sys

import agent_guard
import pytest

from orch import adapters


def _exe(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text("#!/bin/sh\necho 1.0.0\n")
    p.chmod(0o755)
    return p


def test_no_test_finds_a_real_agent_program():
    for name in agent_guard.NAMES:
        for found in (adapters.find_binary(name), shutil.which(name)):
            assert found is None or os.path.realpath(found) not in agent_guard.BLOCKED, found


@pytest.mark.skipif(os.name == "nt", reason="Windows leaves the folder out instead of linking its programs")
def test_hidden_path_keeps_the_other_programs(tmp_path):
    tools = tmp_path / "bin"
    _exe(tools, "copilot")
    _exe(tools, "node")
    path = agent_guard.hidden_path(os.pathsep.join([str(tools), "/usr/bin"]), tmp_path / "shadow")
    assert shutil.which("node", path=path) and not shutil.which("copilot", path=path)
    assert path.split(os.pathsep)[1] == "/usr/bin"


@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for the agent program")
def test_starting_a_real_agent_program_fails_the_test(tmp_path, monkeypatch):
    real = _exe(tmp_path / "bin", "copilot")
    monkeypatch.setattr(agent_guard, "BLOCKED", {os.path.realpath(real)})
    with pytest.raises(agent_guard.AgentStarted, match="real agent program"):
        subprocess.run([str(real), "--version"], capture_output=True)
    with pytest.raises(agent_guard.AgentStarted):  # a bare name found on the child's PATH
        subprocess.run(["copilot"], env={**os.environ, "PATH": str(real.parent)}, capture_output=True)
    with pytest.raises(agent_guard.AgentStarted):
        subprocess.run(f"{real} --version", shell=True, capture_output=True)
    assert agent_guard.started  # even when the code swallows the error, the test fails afterwards
    assert agent_guard.check(tmp_path).startswith("started ")
    assert subprocess.run([sys.executable, "-c", "pass"]).returncode == 0  # anything else still runs


def test_a_copilot_package_in_the_home_fails_and_is_removed(tmp_path):
    pkg = tmp_path / "Library" / "Caches" / "copilot" / "pkg" / "universal"
    pkg.mkdir(parents=True)
    (pkg / "index.js").write_text("x")
    assert "left " in agent_guard.check(tmp_path)
    assert not (tmp_path / "Library" / "Caches" / "copilot").exists()
    (tmp_path / "a" / "b" / ".cache" / "copilot").mkdir(parents=True)
    assert agent_guard.sweep(tmp_path) == [tmp_path / "a" / "b" / ".cache" / "copilot"]
    assert agent_guard.check(tmp_path) is None
