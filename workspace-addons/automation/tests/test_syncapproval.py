import hashlib
import json
from types import SimpleNamespace

from orch_automation import orchcli, syncapproval


def test_synced_block_cannot_start_without_local_consent(tmp_path, monkeypatch):
    root = tmp_path
    folder = root / ".orch/run/sync"
    folder.mkdir(parents=True)
    tid = "t_abc123"
    block = {"enabled": True}
    ticket = {"id": tid, "ext": {"automation": block}}
    (folder / "local-ext.json").write_text(json.dumps({tid: {}}))
    monkeypatch.setattr(orchcli, "ticket", lambda *a: ticket)
    monkeypatch.setattr(
        orchcli,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")), TimeoutExpired=TimeoutError
        ),
    )
    assert orchcli.run_start(root, tid)["result"] == "failed"
    # A remote self-approval claim has no authority.
    block["approved_by_here"] = True
    assert not syncapproval.allowed(root, ticket)
    hashed = hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    (folder / "approved.json").write_text(json.dumps({tid: {"automation": hashed}}))
    assert syncapproval.allowed(root, ticket)
    block["enabled"] = False
    assert orchcli.run_start(root, tid)["result"] == "failed"
    (folder / "local-ext.json").write_text("broken")
    assert orchcli.run_start(root, tid)["result"] == "failed"


def test_locally_created_block_remains_allowed(tmp_path):
    assert syncapproval.allowed(tmp_path, {"id": "t_abc123", "ext": {"automation": {"enabled": True}}})


def test_local_edit_record_cannot_bless_unapproved_block(tmp_path):
    folder = tmp_path / ".orch/run/sync"
    folder.mkdir(parents=True)
    tid = "t_abc123"
    (folder / "local-ext.json").write_text(json.dumps({tid: {}}))
    ticket = {"id": tid, "ext": {}}
    block = {"enabled": True}
    syncapproval.record_local(tmp_path, ticket, block)
    ticket["ext"]["automation"] = block
    assert syncapproval.allowed(tmp_path, ticket)
    ticket["ext"]["automation"] = {"enabled": False}
    syncapproval.record_local(tmp_path, ticket, {"enabled": False, "recurring": True})
    assert not syncapproval.allowed(tmp_path, ticket)
