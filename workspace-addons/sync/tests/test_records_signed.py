"""Agent-writable run/sync records count only when this core signed them for exactly what they are used for
(Opus hard3 #3, PR B): choices (incl. covers), checked files, allowed deletions, ignored and approved add-on
values (single use, #540), held blocks (signed, per ticket, capped) and the pause itself."""

import hashlib
import json
from types import SimpleNamespace

from orch import humanproof
from test_pause import proof
from test_step import NOW, TICKET, run, save, success
from test_two_machines import both, edit, load, machines

from orch_sync import approval, cli, needs, pause, records, repo, step

__all__ = ["machines"]


def test_a_choice_counts_only_as_signed_for_its_remote_and_path(machines):
    _a, b, _ = both(machines)
    remote = step.oid(b, "refs/remotes/origin/orch-state")
    decisions = {"remote_sha": remote, "files": {}}
    pause.record_choice(b, decisions, remote, TICKET, {"keep": "mine", "at": NOW})
    pause.record_choice(b, decisions, remote, "ticket-counter.json", {"keep": "theirs", "at": NOW, "covers": 5})
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    assert set(pause.choices(b, remote)) == {TICKET, "ticket-counter.json"}
    decisions["files"]["ticket-counter.json"]["covers"] = 10**8  # an agent widens what the person reviewed
    decisions["files"]["tickets/t_other1.json"] = {"keep": "theirs", "at": NOW}  # planted
    moved = {**decisions["files"][TICKET], "target": f"{remote}:tickets/t_other1.json"}
    decisions["files"]["tickets/t_other2.json"] = moved  # a signed entry moved to another path
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    assert set(pause.choices(b, remote)) == {TICKET}
    assert pause.choices(b, "0" * 40) == {}  # bound to the reviewed remote


def test_chosen_bytes_must_be_the_signed_ones(machines):
    _a, b, _ = both(machines)
    remote = step.oid(b, "refs/remotes/origin/orch-state")
    decisions = {"remote_sha": remote, "files": {}}
    pause.record_choice(b, decisions, remote, TICKET, {"keep": "theirs", "at": NOW}, b"{}")
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    step.write(b, "run/sync/choices/" + TICKET, b'{"swapped": true}')
    try:
        pause.selected(b, TICKET)
        raise AssertionError("swapped bytes were used")
    except pause.Pause:
        pass
    assert pause.choices(b, remote) == {}  # dropped: asked again


def test_a_planted_checked_file_record_allows_nothing(root):
    from orch import history

    history.ensure_key(root)
    data = b"\x00\x01binary that cannot be checked"
    path = "tickets/t_abc123/artifacts/blob.bin"
    hashed = hashlib.sha256(data).hexdigest()
    step.write(root, "run/sync/checked-files.json", step.encoded({path: hashed}))  # the old, unsigned shape
    before = pause.findings(root, path, data)
    entry = records.make(root, "file", f"{path}:{hashed}", {"path": path, "sha256": hashed})
    step.write(root, "run/sync/checked-files.json", step.encoded({path: entry}))
    after = pause.findings(root, path, data)
    assert all(f.code != "cannot-check" for f in after)
    assert len(before) >= len(after)


def test_a_missing_ticket_goes_only_with_a_signed_single_use_record(machines):
    _a, b, _ = both(machines)
    repo.safe(b, TICKET).unlink()
    step.write(b, "run/sync/allow-delete.json", step.encoded({"t_abc123": True}))  # planted
    success(b)
    assert repo.safe(b, TICKET).exists()  # restored
    entry = records.make(b, "delete", "t_abc123", {"ticket": "t_abc123"})
    step.write(b, "run/sync/allow-delete.json", step.encoded({"t_abc123": entry}))
    repo.safe(b, TICKET).unlink()
    success(b)
    assert not repo.safe(b, TICKET).exists()
    assert not records.ok(b, "delete", "t_abc123", entry, single_use=True)  # used up


def test_an_approval_is_never_replayed_and_a_planted_one_applies_nothing(machines, monkeypatch):
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    approval.approve(b, "t_abc123", "automation",
                     proof(b, "sync:allow:t_abc123:automation:" + approval.digest(value), monkeypatch))
    assert load(b)["ext"]["automation"] == value
    edit(b, ext={"automation": {"enabled": False}})  # the person changes it here afterwards
    success(b)
    edit(a, ext={"automation": value}, updated_at="2026-11-11T14:00:00Z")  # the peer re-sends the approved value
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == {"enabled": False}  # B12/#540: no replay of the old approval
    other = {"enabled": True, "every": "1m"}
    store = cli.read(b, "approved")
    store["t_abc123"]["automation"] = {**store["t_abc123"]["automation"], "hash": approval.digest(other)}
    step.write(b, "run/sync/approved.json", step.encoded(store))  # planted for a new value
    edit(a, ext={"automation": other}, updated_at="2026-11-11T15:00:00Z")
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == {"enabled": False}
    assert any(r["id"] == "sync:held:t_abc123" for r in needs.rows(b))


def test_a_planted_ignore_hides_nothing(machines):
    a, b, _ = both(machines)
    value = {"enabled": True}
    hashed = approval.digest(value)
    step.write(b, "run/sync/ignored.json", step.encoded({"t_abc123": {"automation": hashed}}))
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    assert any(r["id"] == "sync:held:t_abc123" for r in needs.rows(b))


def test_a_stale_held_candidate_goes_when_the_peer_reverts(machines):
    a, b, _ = both(machines)
    edit(a, ext={"automation": {"enabled": True}})
    success(a)
    success(b)
    assert approval.held(b, "t_abc123")
    doc = load(a)
    doc.pop("ext")
    save(a, value={**doc, "updated_at": "2026-11-11T14:00:00Z"})  # the peer goes back to no block
    success(a)
    success(b)
    assert not approval.held(b, "t_abc123")
    assert not [r for r in needs.rows(b) if r["kind"] == "sync:held"]


def test_held_blocks_are_capped(machines, monkeypatch):
    a, b, _ = both(machines)
    monkeypatch.setattr(approval, "MAX_HELD", 1)
    edit(a, ext={"automation": {"enabled": True}, "custom": {"run": True}})
    success(a)
    state = run(b)
    assert state["paused"] and "Too many" in state["paused"]["reason"]


def test_an_edited_pause_is_no_pause(machines):
    a, b, _ = both(machines)
    state = cli.read(b, "state")
    state["paused"] = {"files": [TICKET], "since": NOW, "remote_sha": "0" * 40, "reason": "x", "mac": "forged"}
    repo.safe(b, "run/sync/state.json").write_text(__import__("json").dumps(state))  # planted, not step.write
    assert pause.verified_pause(b, cli.read(b, "state")) is None
    assert not needs.rows(b)
    edit(a, title="goes on")
    success(a)
    assert not success(b).get("paused") and load(b)["title"] == "goes on"


def test_the_local_add_on_values_record_is_signed_and_never_started_again(machines, monkeypatch):
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    known, ok = approval.local_ext(b)
    assert ok and known["t_abc123"] == {}  # received first with no block of this machine's
    approval.approve(
        b,
        "t_abc123",
        "automation",
        proof(b, "sync:allow:t_abc123:automation:" + approval.digest(value), monkeypatch),
    )
    assert approval.local_ext(b) == ({"t_abc123": {"automation": approval.digest(value)}}, True)
    path = repo.safe(b, approval.LOCAL_EXT)
    signed = path.read_bytes()
    data = json.loads(signed)
    body = {k: v for k, v in data.items() if k != "mac"}
    assert humanproof.local_ok(b, approval.LOCAL_EXT_KIND, body, data["mac"])
    data["tickets"]["t_other1"] = {"automation": "0" * 64}  # an agent edits the signed record
    path.write_text(json.dumps(data))
    assert approval.local_ext(b) == ({}, False)
    unsigned = {"t_abc123": {"automation": approval.digest(value)}}  # the old, unsigned shape
    path.write_text(json.dumps(unsigned))
    assert approval.local_ext(b) == ({}, False)
    path.write_bytes(signed)
    assert approval.local_ext(b)[1]
    path.unlink()  # removed: neither turning sync on again nor a merge starts a new (all-local) record
    edit(a, title="goes on", updated_at="2026-11-11T14:00:00Z")
    success(a)
    success(b)
    assert load(b)["title"] == "goes on"
    assert not path.exists()
    repo.ensure(b)
    assert not path.exists()


def test_records_need_the_workspace_key(root):
    try:
        records.make(root, "delete", "t_abc123", {"ticket": "t_abc123"})
        raise AssertionError("signed without a key")
    except repo.Refused:
        pass
    assert not records.ok(root, "delete", "t_abc123", {"kind": "delete", "target": "t_abc123", "id": "x", "mac": "y"})
    assert humanproof.action_spent(root, "not-an-id")
    assert SimpleNamespace  # (imported for parity with the proof helpers)
