import subprocess
import sys

import pytest

from orch_automation import service


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_background_start_is_detached_and_logged(ws, monkeypatch, platform):
    class SpawnCaptured(Exception):
        pass

    captured = {}

    def popen(argv, **kwargs):
        captured.update(kwargs)
        assert argv[0] == sys.executable
        out = kwargs["stdout"]
        assert not out.closed
        assert out.writable()
        assert out.fileno() >= 0
        out.write("background output\n")
        out.flush()
        assert (ws / ".orch/run/automation/automation.log").read_text() == "background output\n"
        assert kwargs["stderr"] == subprocess.STDOUT  # stderr goes to the same log file
        raise SpawnCaptured

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(service.subprocess, "Popen", popen)
    with pytest.raises(SpawnCaptured):
        service.start(ws)

    assert captured["stdin"] == subprocess.DEVNULL
    if platform == "win32":
        assert (
            captured["creationflags"] == 0x00000200 | 0x08000000
        )  # NO_WINDOW, never DETACHED (it would void NO_WINDOW)
        assert captured["close_fds"] is True
        assert "start_new_session" not in captured
    else:
        assert captured["start_new_session"] is True
        assert "creationflags" not in captured
