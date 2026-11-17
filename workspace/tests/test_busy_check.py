"""ORCH-266: the start check calls the computer busy only for real work, not for a stream of short
commands."""

import pytest

from orch import runs_live


@pytest.fixture
def cores(monkeypatch):
    monkeypatch.setattr(runs_live.os, "cpu_count", lambda: 12)


def _ps(monkeypatch, procs):
    monkeypatch.setattr(runs_live, "_processes", lambda: procs)


TAIL = "/opt/homebrew/bin/python3 /Users/x/.orch-tool/bin/orch record tail --run r_{:06d} --follow --json"
STORM = [(0.5, TAIL.format(i)) for i in range(54)]


def test_a_low_load_holds_nothing(monkeypatch, cores):
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (12.0, 10.0, 8.0))
    _ps(monkeypatch, [(1200.0, "work")])
    assert runs_live._load_words() is None


def test_a_high_load_from_a_stream_of_short_commands_is_not_work(monkeypatch, cores):
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (31.0, 28.0, 22.0))
    _ps(monkeypatch, [*STORM, (40.0, "Claude")])
    assert runs_live._load_words() is None


def test_a_high_load_with_real_work_holds_and_names_a_storm(monkeypatch, cores):
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (40.0, 35.0, 30.0))
    _ps(monkeypatch, [*STORM, (900.0, "cargo")])
    assert runs_live._load_words() == "the computer is very busy (54 'orch record tail' at once)"
    _ps(monkeypatch, [(900.0, "cargo"), (100.0, "rustc")])
    assert runs_live._load_words() == "the computer is very busy"


def test_unknown_cpu_use_falls_back_to_the_load(monkeypatch, cores):
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (40.0, 35.0, 30.0))
    _ps(monkeypatch, None)
    assert runs_live._load_words() == "the computer is very busy"


def test_a_big_machine_takes_more_load(monkeypatch):
    monkeypatch.setattr(runs_live.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (60.0, 50.0, 40.0))
    _ps(monkeypatch, [(3200.0, "work")])
    assert runs_live._load_words() is None  # 2.5 per core = 80


def test_command_names_never_carry_arguments():
    assert runs_live._command_name("/x/python3 /y/orch relay inbox --since 4 --wait 30") == "orch relay inbox"
    assert runs_live._command_name("/usr/bin/ssh -i key host") == "ssh"
    assert runs_live._command_name("/y/orch --json") == "orch"


def test_processes_reads_ps():
    procs = runs_live._processes()
    assert procs is None or all(isinstance(c, float) and isinstance(cmd, str) for c, cmd in procs)
