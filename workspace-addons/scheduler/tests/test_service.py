import time

from orch_scheduler import service
from orch_scheduler.cli import describe, main


def test_start_status_stop(ws):
    pid = service.start(ws)
    assert service.running_pid(ws) == pid
    assert service.start(ws) == pid  # no second one
    assert main(["--dir", str(ws), "status"]) == 0
    assert service.stop(ws)
    for _ in range(30):
        if service.running_pid(ws) is None:
            break
        time.sleep(0.1)
    assert main(["--dir", str(ws), "status"]) == 1
    assert not service.stop(ws)


def test_list(ws):
    from conftest import add_ticket
    add_ticket(ws, "t_wake009", wake_at="2026-11-05T08:00:00Z")
    assert "t_wake009" in describe(ws)[0]
