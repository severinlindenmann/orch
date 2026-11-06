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
