import pytest

from orch import syncgate, tickets
from orch.errors import Refused


def test_sync_apply_holds_ticket_lock_on_gate_thread(proj):
    tid = tickets.create(proj, "Sync lock", "human:test")["id"]
    lock = proj / ".orch/tickets" / f".lock-{tid}"
    with syncgate.hold(proj), tickets.sync_apply(proj, tid):
        assert lock.exists()
        with pytest.raises(Refused, match="busy"):
            with tickets._locked(proj, tid, wait=0):
                pytest.fail("A second writer acquired the ticket lock")
    assert not lock.exists()


def test_sync_apply_validates_id(proj):
    with pytest.raises(Refused):
        with tickets.sync_apply(proj, "../outside"):
            pytest.fail("Unsafe id accepted")
