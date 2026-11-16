"""Agent-writable run/sync records count only when they name exactly what they are used for: choices (incl.
covers), checked files, allowed deletions, ignored and approved add-on values (used once, #540), held blocks
(per ticket, capped) and the pause itself. They are plain files: no mac, no pin. Old files that still carry
those fields load as before."""

import hashlib
import json
from types import SimpleNamespace

from test_step import NOW, TICKET, at, run, save, success
from test_two_machines import both, edit, load, machines

from orch_sync import approval, cli, needs, pause, records, repo, step

__all__ = ["machines"]


def test_a_choice_counts_only_for_its_remote_and_path(machines):
    _a, b, _ = both(machines)
    remote = step.oid(b, "refs/remotes/origin/orch-state")
    decisions = {"remote_sha": remote, "files": {}}
    pause.record_choice(b, decisions, remote, TICKET, {"keep": "mine", "at": NOW})
    pause.record_choice(
        b, decisions, remote, "ticket-counter.json", {"keep": "theirs", "at": NOW, "covers": 5}
    )
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    assert set(pause.choices(b, remote)) == {TICKET, "ticket-counter.json"}
    decisions["files"]["tickets/t_other1.json"] = {"keep": "theirs", "at": NOW}  # planted
    moved = {**decisions["files"][TICKET], "target": f"{remote}:tickets/t_other1.json"}
    decisions["files"]["tickets/t_other2.json"] = moved  # an entry moved to another path
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    assert set(pause.choices(b, remote)) == {TICKET, "ticket-counter.json"}  # the planted and moved ones: no
    assert pause.choices(b, "0" * 40) == {}  # bound to the reviewed remote


def test_chosen_bytes_must_be_the_chosen_ones(machines):
    _a, b, _ = both(machines)
    remote = step.oid(b, "refs/remotes/origin/orch-state")
    decisions = {"remote_sha": remote, "files": {}}
    pause.record_choice(b, decisions, remote, TICKET, {"keep": "theirs", "at": NOW}, b"{}")
    step.write(b, "run/sync/choices.json", step.encoded(decisions))
    step.write(b, "run/sync/choices/" + TICKET, b'{"swapped": true}')
    try:
        pause.selected(b, TICKET, pause.choices(b, remote)[TICKET])
        raise AssertionError("swapped bytes were used")
    except pause.Pause:
        pass
    assert pause.choices(b, remote) == {}  # dropped: asked again


def test_a_planted_checked_file_record_allows_nothing(root):
    data = b"\x00\x01binary that cannot be checked"
    path = "tickets/t_abc123/artifacts/blob.bin"
    hashed = hashlib.sha256(data).hexdigest()
    step.write(root, "run/sync/checked-files.json", step.encoded({path: hashed}))  # the old shape of the file
    before = pause.findings(root, path, data)
    assert any(f.code == "cannot-check" for f in before)  # the old shape vouches for nothing
    entry = records.make(root, "file", f"{path}:{hashed}", {"path": path, "sha256": hashed})
    step.write(root, "run/sync/checked-files.json", step.encoded({path: entry}))
    after = pause.findings(root, path, data)
    assert all(f.code != "cannot-check" for f in after)  # only a record for exactly these bytes does


def _blob(b):
    return step.entries(b, "HEAD")[TICKET][1]


def test_a_missing_ticket_goes_only_with_the_persons_record_used_once(machines):
    _a, b, _ = both(machines)
    repo.safe(b, TICKET).unlink()
    step.write(b, "run/sync/allow-delete.json", step.encoded({"t_abc123": True}))  # planted
    success(b)
    assert repo.safe(b, TICKET).exists()  # restored
    target = f"t_abc123:{_blob(b)}"
    entry = records.make(b, "delete", target, {"ticket": "t_abc123", "blob": _blob(b)})
    step.write(b, "run/sync/allow-delete.json", step.encoded({"t_abc123": entry}))
    repo.safe(b, TICKET).unlink()
    success(b)
    assert not repo.safe(b, TICKET).exists()
    assert cli.read(b, "allow-delete") == {}  # used up: the record is gone


def test_an_allowed_deletion_is_bound_to_the_copy_the_person_saw(machines):
    """Opus PR B part 1 LOW 2: the ticket comes back and changes before the next step: the unspent record
    no longer lets a deletion of the NEW copy go."""
    _a, b, _ = both(machines)
    entry = records.make(b, "delete", f"t_abc123:{_blob(b)}", {"ticket": "t_abc123", "blob": _blob(b)})
    step.write(b, "run/sync/allow-delete.json", step.encoded({"t_abc123": entry}))
    edit(b, title="changed here after the decision")
    success(b)  # the changed copy is committed (the file was there: nothing spent)
    repo.safe(b, TICKET).unlink()
    success(b)
    assert repo.safe(b, TICKET).exists() and load(b)["title"] == "changed here after the decision"  # restored
    assert cli.read(b, "state")["deleted"].get("t_abc123")


def test_an_allowed_value_is_never_replayed_and_a_planted_one_applies_nothing(machines):
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    approval.approve(
        b,
        "t_abc123",
        "automation",
        SimpleNamespace(by=None),
    )
    assert load(b)["ext"]["automation"] == value
    edit(b, ext={"automation": {"enabled": False}})  # the person changes it here afterwards
    success(b)
    edit(a, ext={"automation": value}, updated_at=at(14))  # the peer re-sends the approved value
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == {"enabled": False}  # B12/#540: no replay of the old choice
    other = {"enabled": True, "every": "1m"}
    store = cli.read(b, "approved")
    store["t_abc123"]["automation"] = {**store["t_abc123"]["automation"], "hash": approval.digest(other)}
    step.write(b, "run/sync/approved.json", step.encoded(store))  # planted for a new value
    edit(a, ext={"automation": other}, updated_at=at(15))
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
    save(a, value={**doc, "updated_at": at(14)})  # the peer goes back to no block
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


def test_an_approved_removal_leaves_no_own_value(machines):
    """Opus PR B part 1 LOW 11: approving a peer's removal removes the add-on's key from local-ext (absent,
    as automation reads it), not a digest of None."""
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    approval.approve(
        b,
        "t_abc123",
        "automation",
        SimpleNamespace(by=None),
    )
    assert approval.local_ext(b)[0]["t_abc123"] == {"automation": approval.digest(value)}
    doc = load(a)
    doc.pop("ext")
    save(a, value={**doc, "updated_at": at(14)})  # the peer removes the block
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == value  # held until a person decides
    approval.approve(
        b,
        "t_abc123",
        "automation",
        SimpleNamespace(by=None),
    )
    assert "automation" not in (load(b).get("ext") or {})
    known, ok = approval.local_ext(b)
    assert ok and known["t_abc123"] == {}  # automation: no own value, as for a ticket that never had one


def test_the_missing_ticket_notice_names_the_ticket_by_its_title(machines):
    """The dashboard hides ticket ids, so the notice used to read "A ticket file is missing: . Restored it."."""
    _a, b, _ = both(machines)
    state = cli.read(b, "state")
    state["deleted"] = {"t_abc123": NOW}
    step.write(b, step.STATE, step.encoded(state))
    row = next(r for r in needs.rows(b) if r["kind"] == "sync:deleted")
    title = load(b)["title"]
    assert f"A ticket file is missing: {title}. Restored it." == row["text"]
    assert "t_abc123" not in row["text"]


def test_a_choice_written_as_a_plain_file_is_accepted_and_old_fields_are_ignored(machines):
    """A held change, an allowed value and the records are plain files: no mac, no pin. A file from before that
    still carries those fields loads as before (the fields are ignored)."""
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    (held,) = approval.held(b, "t_abc123")
    path, block = held
    assert "mac" not in json.loads(path.read_text())  # written plain
    old = {**json.loads(path.read_text()), "mac": "A" * 43}  # a file from before
    path.write_text(json.dumps(old))
    (again,) = approval.held(b, "t_abc123")
    assert again[1] == block  # loads; the old field is ignored
    approval.approve(b, "t_abc123", "automation", SimpleNamespace(by=None))
    assert load(b)["ext"]["automation"] == value
    approved = cli.read(b, "approved")["t_abc123"]["automation"]
    assert "mac" not in approved and approved["kind"] == "allow"


def test_the_records_are_plain_and_an_old_entry_with_a_mac_still_counts():
    root = None
    entry = records.make(root, "delete", "t_abc123:b", {"ticket": "t_abc123"})
    assert set(entry) == {"ticket", "kind", "target", "id"}
    assert records.ok(root, "delete", "t_abc123:b", entry)
    assert records.ok(root, "delete", "t_abc123:b", {**entry, "mac": "y", "pin": 3})  # old fields ignored
    assert not records.ok(root, "delete", "t_abc123:other", entry)  # another target
    assert not records.ok(root, "ignore", "t_abc123:b", entry)  # another kind
    assert not records.ok(root, "delete", "t_abc123:b", {"kind": "delete", "target": "t_abc123:b"})  # no id
    assert not records.ok(root, "delete", "t_abc123:b", True)


def test_a_pause_is_a_plain_entry_and_an_old_mac_is_dropped(machines):
    _a, b, _ = both(machines)
    state = cli.read(b, "state")
    paused = {"files": [TICKET], "since": NOW, "remote_sha": "0" * 40, "reason": "x"}
    state["paused"] = {**paused, "mac": "A" * 43}  # an old pause
    assert pause.verified_pause(b, state) == paused
    state["paused"] = {**paused, "files": "no"}  # not the shape of a pause
    assert pause.verified_pause(b, state) is None
    step.write(b, step.STATE, step.encoded({**state, "paused": paused}))
    assert pause.verified_pause(b, cli.read(b, "state")) == paused


def test_the_add_on_values_record_is_plain(machines):
    a, b, _ = both(machines)
    known, ok = approval.local_ext(b)
    assert ok and known == {"t_abc123": {}}
    path = repo.safe(b, approval.LOCAL_EXT)
    data = json.loads(path.read_text())
    assert set(data) == {"schema", "tickets"}  # no mac, no counter
    path.write_text(json.dumps({**data, "mac": "A" * 43, "counter": 4}))  # an old record
    assert approval.local_ext(b) == (known, True)
    path.write_text(json.dumps({"t_abc123": {"automation": "x"}}))  # not a record of this schema
    assert approval.local_ext(b) == ({}, False)
    path.unlink()  # removed: neither a merge nor turning sync on again starts a new (all-local) record
    edit(a, title="goes on", updated_at=at(14))
    success(a)
    success(b)
    assert load(b)["title"] == "goes on" and not path.exists()
    repo.ensure(b)
    assert not path.exists()
