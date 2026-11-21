"""A run that could not start says what is missing and where to fix it, never a command (report r-1118-0907)."""

import os
import stat
import sys

import pytest

from orch_automation import orchcli


@pytest.mark.skipif(sys.platform == "win32", reason="a shell script stands in for orch")
def test_no_helper_chosen_is_plain_words(tmp_path, monkeypatch):
    fake = tmp_path / "orch"
    fake.write_text(
        "#!/bin/sh\n"
        'echo \'{"error": "No agent found; set one later: orch config set workspace.agent <name>"}\'\n'
        "exit 2\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ORCH_BIN", os.fspath(fake))
    monkeypatch.setattr(orchcli, "sync_refusal", lambda root, tid: None)
    got = orchcli.run_start(tmp_path, "t_abc123")
    assert got["result"] == "failed"
    assert "Settings > Helper" in got["reason"] and "Try again" in got["reason"]
    assert "orch config" not in got["reason"] and "workspace.agent" not in got["reason"]
