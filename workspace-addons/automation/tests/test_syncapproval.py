import hashlib
import json
from types import SimpleNamespace

import pytest

from orch_automation import orchcli, syncapproval

TID = "t_abc123"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A workspace with sync on, in a private test home."""
    from orch import addons

    (tmp_path / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: tmp_path / "home")
    root = tmp_path / "ws"
    (root / ".orch/run/sync").mkdir(parents=True)  # sync is on here
    return root


def digest(block):
    return hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def write_ext(root, tickets, **extra):
    """What the sync add-on writes (orch_sync.approval.write_local_ext): a plain record."""
    path = root / ".orch/run/sync/local-ext.json"
    path.write_text(json.dumps({"schema": "orch.sync-local-ext/1", "tickets": tickets, **extra}))
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


@pytest.mark.parametrize("damage", ["delete", "corrupt", "no-schema"])
def test_a_missing_or_unverified_record_allows_nothing(root, monkeypatch, damage):
    """Fail closed: once sync is on, no readable record means no synced value is approved, not that
    every ticket is this machine's own."""
    block = {"enabled": True}
    hashed = digest(block)
    path = write_ext(root, {TID: {"automation": hashed}, "t_other1": {}})
    synced = {"id": TID, "ext": {"automation": block}}
    unknown = {"id": "t_new001", "ext": {"automation": block}}  # not in the record: would read as local
    assert syncapproval.allowed(root, synced) and syncapproval.allowed(root, unknown)
    if damage == "delete":
        path.unlink()
    elif damage == "corrupt":
        path.write_text('{"schema": "orch.sync-local-ext/1", "tickets": {')
    else:  # the old shape an agent can write: no schema
        path.write_text(json.dumps({TID: {"automation": hashed}}))
    for t in (synced, unknown):
        assert not syncapproval.allowed(root, t)
    no_start(monkeypatch, synced)
    assert orchcli.run_start(root, TID)["result"] == "failed"
    # a local edit cannot bless anything while the record is broken
    syncapproval.record_local(root, synced, block)
    assert not syncapproval.allowed(root, synced)


def test_a_local_blocks_record_of_the_old_shape_blesses_nothing(root):
    write_ext(root, {TID: {}})
    block = {"enabled": True}
    ticket = {"id": TID, "ext": {"automation": block}}
    path = root / ".orch/addons/automation/local-blocks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({TID: digest(block)}))  # the old, unsigned shape
    assert not syncapproval.allowed(root, ticket)
    path.write_text(
        json.dumps(
            {
                "schema": "orch.automation-local-blocks/1",
                "tickets": {TID: digest(block)},
                "counter": 3,
                "mac": "A" * 43,
            }
        )
    )
    assert syncapproval.allowed(root, ticket)  # an old record with mac and counter fields still loads


def test_the_record_works_with_old_fields(root):
    block = {"enabled": True}
    write_ext(root, {TID: {"automation": digest(block)}}, counter=2, mac="A" * 43)  # old fields are ignored
    assert syncapproval.allowed(root, {"id": TID, "ext": {"automation": block}})
    assert syncapproval.allowed(root, {"id": "t_new001", "ext": {"automation": block}})  # created here


def test_a_ticket_showing_sync_traces_is_never_local(root):
    block = {"enabled": True}
    write_ext(root, {})
    by_sync = {"id": "t_new001", "ext": {"automation": block}, "history": [{"by": "agent:sync", "text": "x"}]}
    with_ext = {"id": "t_new002", "ext": {"automation": block, "sync": {}}}
    assert not syncapproval.allowed(root, by_sync)
    assert not syncapproval.allowed(root, with_ext)


def test_a_schedule_made_here_runs_even_though_the_sync_folder_exists(root, monkeypatch):
    """The sync folder is there but sync never recorded anything (no local-ext.json): a schedule this computer
    wrote is approved by this machine's own record, so Run now is not refused."""
    block = {"enabled": True, "recurring": True}
    assert not (root / ".orch/run/sync/local-ext.json").exists()
    syncapproval.record_local(root, {"id": TID, "ext": {}}, block)  # what set_ext does at creation
    ticket = {"id": TID, "ext": {"automation": block}}
    assert syncapproval.allowed(root, ticket)
    # started: the guard does not stop it (the fake run answers ok)
    monkeypatch.setattr(orchcli, "ticket", lambda *a: ticket)
    ran = SimpleNamespace(returncode=0, stdout='{"run": "r1", "log": "l"}', stderr="")
    monkeypatch.setattr(
        orchcli, "subprocess", SimpleNamespace(run=lambda *a, **k: ran, TimeoutExpired=TimeoutError)
    )
    assert orchcli.run_start(root, TID)["result"] == "started"
    # a different block on the same ticket (arrived by sync) is not covered by that record
    other = {"id": TID, "ext": {"automation": {"enabled": True, "recurring": False}}}
    assert not syncapproval.allowed(root, other)
    # another ticket is not covered either
    assert not syncapproval.allowed(root, {"id": "t_other9", "ext": {"automation": block}})


def test_a_synced_schedule_is_refused_until_it_is_allowed_here(root, monkeypatch):
    block = {"enabled": True, "recurring": True}
    ticket = {"id": TID, "ext": {"automation": block}}
    write_ext(root, {TID: {}})  # sync received it; nobody allowed it here
    no_start(monkeypatch, ticket)
    assert orchcli.run_start(root, TID)["result"] == "failed"
    write_ext(root, {TID: {"automation": digest(block)}})  # the person's Allow (sync records it)
    assert syncapproval.allowed(root, ticket)


def test_without_any_record_a_synced_schedule_stays_refused(root, monkeypatch):
    ticket = {"id": TID, "ext": {"automation": {"enabled": True}}}
    no_start(monkeypatch, ticket)  # no local-ext.json, no local-blocks.json
    assert orchcli.run_start(root, TID)["result"] == "failed"
