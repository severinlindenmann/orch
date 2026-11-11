import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orch_automation import orchcli, syncapproval

TID = "t_abc123"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A workspace whose core key exists (the records are local1-signed with it), in a private test home."""
    from orch import addons, history, humanproof

    monkeypatch.setattr(humanproof, "install_kind", lambda: "test")
    monkeypatch.setattr(humanproof, "guarded_home", lambda r: Path(r).parent / "proof-home")
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: tmp_path / "home")
    root = tmp_path / "ws"
    (root / ".orch/run/sync").mkdir(parents=True)  # sync is on here
    history.ensure_key(root)
    return root


def digest(block):
    return hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def signed(root, kind, schema, tickets):
    from orch import humanproof

    body = {"schema": schema, "tickets": tickets}
    return json.dumps({**body, "mac": humanproof.local_sign(root, kind, body)})


def write_ext(root, tickets):
    """What the sync add-on writes (orch_sync.approval.write_local_ext)."""
    path = root / ".orch/run/sync/local-ext.json"
    path.write_text(signed(root, "sync-local-ext", "orch.sync-local-ext/1", tickets))
    return path


def no_start(monkeypatch, ticket):
    monkeypatch.setattr(orchcli, "ticket", lambda *a: ticket)
    monkeypatch.setattr(
        orchcli,
        "subprocess",
        SimpleNamespace(
            run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")), TimeoutExpired=TimeoutError
        ),
    )


def test_synced_block_cannot_start_without_local_consent(root, monkeypatch):
    block = {"enabled": True}
    ticket = {"id": TID, "ext": {"automation": block}}
    write_ext(root, {TID: {}})
    no_start(monkeypatch, ticket)
    assert orchcli.run_start(root, TID)["result"] == "failed"
    # A remote self-approval claim has no authority.
    block["approved_by_here"] = True
    assert not syncapproval.allowed(root, ticket)
    hashed = digest(block)
    # A hash in approved.json is no approval (agent-writable; sync signs its records, PR B).
    (root / ".orch/run/sync/approved.json").write_text(json.dumps({TID: {"automation": hashed}}))
    assert not syncapproval.allowed(root, ticket)
    # A person's approval (orch sync approve) records the value as this machine's own.
    write_ext(root, {TID: {"automation": hashed}})
    assert syncapproval.allowed(root, ticket)
    block["enabled"] = False
    assert orchcli.run_start(root, TID)["result"] == "failed"
    (root / ".orch/run/sync/local-ext.json").write_text("broken")
    assert orchcli.run_start(root, TID)["result"] == "failed"


def test_locally_created_block_remains_allowed(tmp_path):
    assert syncapproval.allowed(tmp_path, {"id": "t_abc123", "ext": {"automation": {"enabled": True}}})


def test_local_edit_record_cannot_bless_unapproved_block(root):
    write_ext(root, {TID: {}})
    ticket = {"id": TID, "ext": {}}
    block = {"enabled": True}
    syncapproval.record_local(root, ticket, block)
    ticket["ext"]["automation"] = block
    assert syncapproval.allowed(root, ticket)
    ticket["ext"]["automation"] = {"enabled": False}
    syncapproval.record_local(root, ticket, {"enabled": False, "recurring": True})
    assert not syncapproval.allowed(root, ticket)


@pytest.mark.parametrize("damage", ["delete", "corrupt", "unsigned", "forged-mac", "edited", "another-kind"])
def test_a_missing_or_unverified_record_allows_nothing(root, monkeypatch, damage):
    """Fail closed: once sync is on, no record this core signed means no synced value is approved, not that
    every ticket is this machine's own."""
    block = {"enabled": True}
    hashed = digest(block)
    path = write_ext(root, {TID: {"automation": hashed}, "t_other1": {}})
    synced = {"id": TID, "ext": {"automation": block}}
    unknown = {"id": "t_new001", "ext": {"automation": block}}  # not in the record: would read as local
    assert syncapproval.allowed(root, synced) and syncapproval.allowed(root, unknown)
    data = json.loads(path.read_text())
    if damage == "delete":
        path.unlink()
    elif damage == "corrupt":
        path.write_text('{"schema": "orch.sync-local-ext/1", "tickets": {')
    elif damage == "unsigned":  # the old shape an agent can write
        path.write_text(json.dumps({TID: {"automation": hashed}}))
    elif damage == "forged-mac":
        path.write_text(json.dumps({**data, "tickets": {}, "mac": "A" * 43}))
    elif damage == "edited":  # a signed record with a ticket taken out (it would then read as local)
        path.write_text(json.dumps({**data, "tickets": {"t_other1": {}}}))
    else:  # a MAC this core made for another record kind
        path.write_text(signed(root, "automation-local-blocks", "orch.sync-local-ext/1", {}))
    for t in (synced, unknown):
        assert not syncapproval.allowed(root, t)
    no_start(monkeypatch, synced)
    assert orchcli.run_start(root, TID)["result"] == "failed"
    # a local edit cannot bless anything while the record is broken
    syncapproval.record_local(root, synced, block)
    assert not syncapproval.allowed(root, synced)


def test_a_forged_local_blocks_record_blesses_nothing(root):
    write_ext(root, {TID: {}})
    block = {"enabled": True}
    ticket = {"id": TID, "ext": {"automation": block}}
    path = root / ".orch/addons/automation/local-blocks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({TID: digest(block)}))  # the old, unsigned shape
    assert not syncapproval.allowed(root, ticket)
    path.write_text(json.dumps({"schema": "orch.automation-local-blocks/1", "tickets": {TID: digest(block)}}))
    assert not syncapproval.allowed(root, ticket)
    path.write_text(signed(root, "sync-local-ext", "orch.automation-local-blocks/1", {TID: digest(block)}))
    assert not syncapproval.allowed(root, ticket)  # another kind's MAC
    path.write_text(
        signed(root, "automation-local-blocks", "orch.automation-local-blocks/1", {TID: digest(block)})
    )
    assert syncapproval.allowed(root, ticket)


def test_without_a_key_nothing_is_approved(tmp_path, root):
    from orch import addons

    other = tmp_path / "other"
    (other / ".orch/run/sync").mkdir(parents=True)
    # a record signed in another workspace, copied here (this one has no key)
    write_ext(root, {})
    (other / ".orch/run/sync/local-ext.json").write_text((root / ".orch/run/sync/local-ext.json").read_text())
    assert addons.workspace_id(other, create=False) is None
    assert not syncapproval.allowed(other, {"id": "t_new001", "ext": {"automation": {"enabled": True}}})
