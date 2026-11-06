import os
import re
from pathlib import Path

from orch import term


def test_null_device_is_not_a_terminal():
    """Windows says isatty() for NUL (a scheduled task's or CI's stdin): orch init then waited forever."""
    with open(os.devnull) as f:
        assert not term.is_terminal(f)


def test_none_and_stand_ins():
    assert not term.is_terminal(None)

    class Fake:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    assert term.is_terminal(Fake(True)) and not term.is_terminal(Fake(False))


def test_no_other_isatty_in_orch():
    """One place decides (see term.py); a bare isatty() is wrong on Windows."""
    src = Path(term.__file__).parent
    bad = [
        f"{p.relative_to(src)}:{i}"
        for p in src.rglob("*.py")
        if p.name != "term.py"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.isatty\(\)", line)
    ]
    assert bad == []


def test_a_failing_isatty_is_not_a_terminal():
    class S:
        def isatty(self):
            raise OSError

    assert term.is_terminal(S()) is False


def test_hook_input_without_stdin(monkeypatch):
    """pythonw or a process started without std handles: sys.stdin is None (security review)."""
    import argparse
    import sys

    from orch import cli_run

    monkeypatch.setattr(sys, "stdin", None)
    assert cli_run._hook_input(argparse.Namespace(kind="session")) == {}


def test_require_human_refuses_without_a_terminal(monkeypatch):
    import io
    import sys

    import pytest

    from orch import tickets
    from orch.errors import Refused

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    with pytest.raises(Refused):
        tickets.require_human("ok?", "approve")
