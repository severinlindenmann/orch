import os
import sys
from types import SimpleNamespace

from orch import adapters, config, worktrees


def test_windows_copy_setup_unquotes_program_and_arguments(proj, monkeypatch):
    copy = proj / "copy with spaces"
    copy.mkdir()
    script = copy / "setup step.py"
    script.write_text("import sys\nfrom pathlib import Path\nPath(sys.argv[1]).touch()\n", encoding="utf-8")
    config.set_copy_setup(proj, f'"{sys.executable}" "setup step.py" "prepared copy"')
    # Exercise the Windows tokenization on POSIX too, without changing pathlib or the subprocess host.
    windows = SimpleNamespace(**(vars(os) | {"name": "nt"}))
    monkeypatch.setattr(worktrees, "os", windows)
    monkeypatch.setattr(adapters, "os", windows)
    assert worktrees._setup(proj, "t_abcdef", {"path": str(copy)}) == []
    assert (copy / "prepared copy").is_file()
