import signal
import subprocess
from unittest.mock import Mock

import pytest

from orch import procs


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("verified", [False, True])
def test_stop_tree_checks_identity_before_signalling(monkeypatch, platform, verified):
    events = []
    monkeypatch.setattr(procs.sys, "platform", platform)
    run = Mock(side_effect=lambda *a, **kw: events.append("taskkill"))
    kill = Mock(side_effect=lambda *a: events.append("kill"))
    monkeypatch.setattr(procs, "_run", run)
    monkeypatch.setattr(procs.os, "kill", kill)

    def check():
        events.append("identity")
        return verified

    assert procs.stop_tree(4242, verified=check) is verified
    if not verified:
        assert events == ["identity"]
        run.assert_not_called()
        kill.assert_not_called()
    elif platform == "win32":
        assert events == ["identity", "taskkill"]
        run.assert_called_once_with(
            ["taskkill", "/PID", "4242", "/T", "/F"],
            capture_output=True,
            timeout=5,
            check=True,
            creationflags=0x08000000,
        )
        kill.assert_not_called()
    else:
        assert events == ["identity", "kill"]
        kill.assert_called_once_with(4242, signal.SIGTERM)
        run.assert_not_called()


@pytest.mark.parametrize(
    "error", [subprocess.TimeoutExpired("taskkill", 5), subprocess.CalledProcessError(1, "taskkill")]
)
def test_stop_tree_surfaces_taskkill_failure(monkeypatch, error):
    monkeypatch.setattr(procs.sys, "platform", "win32")
    monkeypatch.setattr(procs, "_run", Mock(side_effect=error))
    with pytest.raises(RuntimeError, match="could not be stopped"):
        procs.stop_tree(4242, verified=lambda: True)


def test_port_wait_is_bounded(monkeypatch):
    from unittest.mock import MagicMock

    now = [0.0]
    monkeypatch.setattr(procs.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(procs.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(procs.socket, "create_connection", MagicMock())
    assert not procs.wait_port_free(8430)
    assert now[0] == pytest.approx(5)
