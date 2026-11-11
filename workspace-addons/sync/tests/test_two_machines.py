import contextlib
import json
import subprocess

import pytest
from test_step import ART, NOW, TICKET, configure, run, save, success, ticket, tracked

from orch_sync import repo, step


@pytest.fixture
def machines(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    roots = [tmp_path / name for name in ("A", "B")]
    for root in roots:
        (root / ".orch").mkdir(parents=True)
        configure(root, bare)
    return *roots, bare


def load(root):
    return json.loads((root / ".orch" / TICKET).read_text())


def edit(root, **values):
    save(root, value=load(root) | values)


def both(machines):
    a, b, bare = machines
    save(a)
    success(a)
    success(b)
    success(a)
    return a, b, bare


def remote_sha(bare):
    return subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "orch-state"], capture_output=True, check=True
    ).stdout.strip()


def test_two_fields_status_counter(machines):
    a, b, _ = both(machines)
    edit(a, title="A title", updated_at="2026-11-11T13:00:00Z")
    edit(b, note="B note", updated_at="2026-11-11T14:00:00Z")
    save(a, "ticket-counter.json", {"last": 10})
    save(b, "ticket-counter.json", {"last": 20})
    success(a)
    success(b)
    success(a)
    assert load(a)["title"] == "A title" and load(a)["note"] == "B note"
    assert json.loads((a / ".orch/ticket-counter.json").read_text())["last"] == 20
    edit(a, status="done", updated_at="2026-11-11T15:00:00Z")
    edit(b, status="active", updated_at="2026-11-11T16:00:00Z")
    success(a)
    success(b)
    success(a)
    assert load(a)["status"] == load(b)["status"] == "done"
    assert any(h["at"] == NOW and "status" in h["text"] for h in load(b)["history"])


def test_tracked_turned_general(machines):
    a, b, bare = both(machines)
    save(a, ART, b"original artifact")
    success(a)
    before = step.entries(a, "HEAD")
    edit(a, general=True)
    save(a, ART, b"local artifact change")
    chat = "tickets/t_abc123/artifacts/chat.txt"
    save(a, chat, b"private chat text")
    other = "tickets/t_second.json"
    save(a, other, ticket() | {"id": "t_second"})
    state = success(a)
    assert "Ticket t_abc123 has a problem and was not synced" in str(state["skipped"])
    assert load(a)["general"] is True
    for path in (TICKET, ART):
        assert step.entries(a, "HEAD")[path] == before[path]
        remote_blob = subprocess.run(
            ["git", "--git-dir", str(bare), "show", "orch-state:" + path], capture_output=True, check=True
        ).stdout
        assert remote_blob == step.blob(a, before[path])
    reachable = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-list", "--objects", "orch-state"],
        capture_output=True,
        check=True,
    ).stdout
    assert chat.encode() not in reachable
    success(b)
    assert tracked(b) == {TICKET, ART, other}
    assert load(b).get("general") is not True
    assert (b / ".orch" / ART).read_bytes() == b"original artifact"


def test_offline_then_online(machines):
    a, b, bare = both(machines)
    moved = bare.with_name("offline.git")
    bare.rename(moved)
    edit(b, title="Offline edit")
    assert run(b)["last_error"] == "offline"
    assert b"Offline edit" in repo.git(b, "show", "HEAD:" + TICKET).stdout
    moved.rename(bare)
    success(b)
    success(a)
    assert load(a)["title"] == "Offline edit"


def hostile(a, bare, args):
    repo.git(a, "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args)
    repo.git(a, "push", "--force", "origin", "HEAD:orch-state")
    return remote_sha(bare)


def test_force_push_closed(machines):
    a, b, bare = both(machines)
    tree = step.oid(a, "HEAD^{tree}")
    # Use a different timestamp: an idle sync now retains the initial root commit.
    new = step.commit(a, tree, [], "2026-11-11T13:00:00Z")
    repo.git(a, "update-ref", "refs/heads/orch-state", new)
    repo.git(a, "push", "--force", "origin", "HEAD:orch-state")
    before, content, tip = step.oid(b, "HEAD"), load(b), remote_sha(bare)
    assert "rewritten" in run(b)["last_error"]
    assert step.oid(b, "HEAD") == before and load(b) == content and remote_sha(bare) == tip


@pytest.mark.parametrize("path", [TICKET, ART])
def test_incoming_deletion_closed(machines, path):
    a, b, bare = both(machines)
    if path == ART:
        save(a, ART, b"artifact")
        success(a)
        success(b)
        success(a)
    repo.git(a, "rm", "--", path)
    tip = hostile(a, bare, ["commit", "-m", "delete"])
    head = step.oid(b, "HEAD")
    before = (b / ".orch" / path).read_bytes()
    assert run(b)["last_error"]
    assert step.oid(b, "HEAD") == head
    assert (b / ".orch" / path).read_bytes() == before and remote_sha(bare) == tip


def test_ext_held_sessions_local(machines):
    a, b, _ = both(machines)
    edit(b, ext={"automation": {"enabled": False}})
    success(b)
    success(a)
    # Inject a remote block even though this machine would hold it on receipt.
    edit(
        a,
        ext={"automation": {"enabled": True}},
        sessions=[{"agent": "codex", "host": "same-host", "id": "resume-me", "last_used": NOW}],
    )
    repo.git(a, "add", "--", TICKET)
    hostile(a, machines[2], ["commit", "-m", "incoming automation and session"])
    success(b)
    assert load(b)["ext"]["automation"] == {"enabled": False}
    assert not load(b).get("sessions")
    held = list((b / ".orch/run/sync/held").glob("*.json"))
    assert any(json.loads(p.read_text())["value"] == {"enabled": True} for p in held)


def test_artifact_conflict_closed(machines):
    a, b, bare = both(machines)
    save(a, ART, b"base\n")
    success(a)
    success(b)
    success(a)
    save(a, ART, b"A\n")
    save(b, ART, b"B\n")
    success(a)
    tip = remote_sha(bare)
    assert "Conflicting artifact" in run(b)["last_error"]
    assert (b / ".orch" / ART).read_bytes() == b"B\n"
    assert remote_sha(bare) == tip


def test_agent_write_between_commit_apply(machines, monkeypatch):
    a, b, bare = both(machines)
    save(a, ART, b"original")
    success(a)
    success(b)
    success(a)
    save(a, ART, b"remote edit")
    success(a)
    apply = step.apply

    def agent_write(root, old, new, state, merges=None):
        save(root, ART, b"agent edit")
        return apply(root, old, new, state, merges)

    monkeypatch.setattr(step, "apply", agent_write)
    tip = remote_sha(bare)
    assert "busy" in run(b)["last_error"]
    assert (b / ".orch" / ART).read_bytes() == b"agent edit"
    assert remote_sha(bare) == tip


def test_crash_before_apply_recovers(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title="After crash")
    success(a)

    def crash(*args):
        raise RuntimeError("crash")

    with monkeypatch.context() as m:
        m.setattr(step, "apply", crash)
        with pytest.raises(RuntimeError, match="crash"):
            run(b)
    assert (b / ".orch/run/sync/pending.json").exists()
    success(b)
    assert load(b)["title"] == "After crash"
    success(b)
    assert load(b)["title"] == "After crash"
    assert not (b / ".orch/run/sync/pending.json").exists()


def test_forged_pending_missing_merges_refuses_before_writes(machines, monkeypatch):
    a, b, bare = both(machines)
    edit(a, title="Forged recovery")
    save(a, "ticket-counter.json", {"last": 20})
    success(a)

    def crash(*args):
        raise RuntimeError("crash")

    with monkeypatch.context() as m:
        m.setattr(step, "apply", crash)
        with pytest.raises(RuntimeError, match="crash"):
            run(b)
    pending_path = b / ".orch/run/sync/pending.json"
    pending = json.loads(pending_path.read_text())
    assert TICKET in pending["merges"]
    pending["merges"] = {}
    pending_path.write_bytes(step.encoded(pending))
    before = {
        path: (b / ".orch" / path).read_bytes() if (b / ".orch" / path).exists() else None
        for path in (TICKET, "ticket-counter.json")
    }
    head, tip = step.oid(b, "HEAD"), remote_sha(bare)
    git, write = repo.git, step.write

    def checked_git(root, *args, **kwargs):
        assert args[0] not in ("update-ref", "push")
        return git(root, *args, **kwargs)

    def no_write(root, path, data):
        assert path == "run/sync/state.json"  # Recording the refusal is allowed.
        return write(root, path, data)

    monkeypatch.setattr(repo, "git", checked_git)
    monkeypatch.setattr(step, "write", no_write)
    assert "busy" in run(b)["last_error"]
    for path, data in before.items():
        p = b / ".orch" / path
        assert (p.read_bytes() if p.exists() else None) == data
    assert step.oid(b, "HEAD") == head and remote_sha(bare) == tip


def test_first_push_excludes_old_history(machines):
    a, _, bare = machines
    save(a, "me/old-secret", b"orp_" + b"x" * 30)
    repo.git(a, "add", "-f", "--", "me/old-secret")
    repo.git(
        a, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "private history"
    )
    old = step.oid(a, "HEAD")
    save(a)
    success(a)
    reachable = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-list", "--objects", "orch-state"],
        capture_output=True,
        check=True,
    ).stdout
    assert old.encode() not in reachable and b"old-secret" not in reachable
    assert repo.git(a, "cat-file", "-t", old).stdout == b"commit\n"


def test_synced_files_cannot_enable_remote(machines):
    a, b, bare = both(machines)
    before = (b / ".orch/run/sync/settings.json").read_bytes()
    save(a, "run/sync/settings.json", {"mode": "remote", "kind": "team", "remote": "/evil"})
    repo.git(a, "add", "-f", "--", "run/sync/settings.json")
    hostile(a, bare, ["commit", "-m", "settings injection"])
    assert run(b)["last_error"]
    assert (b / ".orch/run/sync/settings.json").read_bytes() == before


@pytest.mark.parametrize("payload", [b"orp_" + b"a" * 30, b"PK\x03\x04archive"])
def test_incoming_scan_blocks_before_commit(machines, payload):
    a, b, bare = both(machines)
    save(a, ART, payload)
    repo.git(a, "add", "--", ART)
    tip = hostile(a, bare, ["commit", "-m", "hostile bytes"])
    edit(b, title="Uncommitted local edit")
    head = step.oid(b, "HEAD")
    assert run(b)["last_error"]
    assert step.oid(b, "HEAD") == head
    assert load(b)["title"] == "Uncommitted local edit"
    assert not (b / ".orch" / ART).exists() and remote_sha(bare) == tip


def test_new_ticket_ext_and_session_held(machines):
    a, b, _ = machines
    from test_step import ticket

    save(
        a,
        value=ticket(
            ext={"scheduler": {"command": "never-run"}},
            sessions=[{"agent": "codex", "host": "localhost", "id": "remote", "last_used": NOW}],
        ),
    )
    success(a)
    success(b)
    assert not load(b).get("ext") and not load(b).get("sessions")
    assert list((b / ".orch/run/sync/held").glob("*.json"))


def test_non_ff_retries_once_from_fetch(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title="A concurrent edit")
    edit(b, note="B concurrent edit")
    git = repo.git
    pushes = []

    def racing_git(root, *args, **kwargs):
        if root == b and args[0] == "push":
            pushes.append(args)
            if len(pushes) == 1:
                success(a)
        return git(root, *args, **kwargs)

    monkeypatch.setattr(repo, "git", racing_git)
    success(b)
    assert len(pushes) == 2
    assert load(b)["title"] == "A concurrent edit" and load(b)["note"] == "B concurrent edit"


def test_remote_url_change_orphans_again(machines, tmp_path):
    a, _, _ = both(machines)
    edit(a, title="Give the old remote real history")
    success(a)
    old = step.oid(a, "HEAD")
    bare = tmp_path / "second.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    configure(a, bare)
    success(a)
    parents = repo.git(a, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(parents) == 1 and parents[0] != old.encode()


def test_partial_apply_crash_is_idempotent(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title="New title")
    save(a, ART, b"new artifact")
    success(a)
    write = step.write
    replaced = []

    def crash_after_write(root, path, data):
        write(root, path, data)
        if path.startswith("tickets/"):
            replaced.append(path)
            raise RuntimeError("crash after replace")

    with monkeypatch.context() as m:
        m.setattr(step, "write", crash_after_write)
        with pytest.raises(RuntimeError):
            run(b)
    assert len(replaced) == 1
    success(b)
    assert load(b)["title"] == "New title" and (b / ".orch" / ART).read_bytes() == b"new artifact"


def test_key_clash_waits_for_pr5(machines):
    a, b, bare = both(machines)
    edit(a, key="AB1-1")
    success(a)
    success(b)
    from test_step import ticket

    save(b, "tickets/t_second.json", dict(ticket(), id="t_second", key="AB1-1"))
    head, tip = step.oid(b, "HEAD"), remote_sha(bare)
    assert "key clash" in run(b)["last_error"]
    assert step.oid(b, "HEAD") == head and remote_sha(bare) == tip


def test_push_timeout_is_offline(machines, monkeypatch):
    a, _, _ = both(machines)
    edit(a, title="Pending push")
    git = repo.git

    def timeout(root, *args, **kwargs):
        if args[0] == "push":
            raise repo.Refused("Git operation failed")
        return git(root, *args, **kwargs)

    monkeypatch.setattr(repo, "git", timeout)
    assert run(a)["last_error"] == "offline"
    assert b"Pending push" in repo.git(a, "show", "HEAD:" + TICKET).stdout


@pytest.mark.parametrize("new_checked_commit", [False, True])
def test_merge_uses_checked_commit_when_remote_ref_moves(machines, monkeypatch, new_checked_commit):
    a, b, _ = both(machines)
    edit(a, title="Checked update")
    success(a)
    check, merged_tree = step.incoming.check, step.merged_tree
    checked, merged = [], []

    def racing_check(root, ref, **kwargs):
        if new_checked_commit:
            # Also enforce the Result API: the returned commit is authoritative.
            tree = step.oid(root, ref + "^{tree}")
            ref = step.commit(root, tree, [ref], NOW)
        result = check(root, ref, **kwargs)
        assert not result.problems
        checked.append(result.commit)
        tree = step.oid(root, result.commit + "^{tree}")
        moved = step.commit(root, tree, [result.commit], NOW)
        repo.git(root, "update-ref", "refs/remotes/origin/orch-state", moved)
        assert moved != result.commit
        return result

    def checked_merge(root, head, remote, index, now):
        merged.append(remote)
        assert remote == checked[-1]
        return merged_tree(root, head, remote, index, now)

    monkeypatch.setattr(step.incoming, "check", racing_check)
    monkeypatch.setattr(step, "merged_tree", checked_merge)
    success(b)
    assert merged == checked and merged
    assert load(b)["title"] == "Checked update"


@pytest.mark.parametrize("gate", ["environment", "helper"])
def test_remote_settings_require_preview_on_every_run(machines, monkeypatch, gate):
    a, _, bare = both(machines)
    settings = json.loads(repo.safe(a, "run/sync/settings.json").read_text())
    assert settings["mode"] == "remote"
    head, tip = step.oid(a, "HEAD"), remote_sha(bare)
    git, remote_allowed = repo.git, step.cli.remote_allowed
    calls, network = [], []
    if gate == "environment":
        monkeypatch.delenv("ORCH_SYNC_REMOTE_PREVIEW")

    def allowed():
        calls.append(True)
        return remote_allowed() if gate == "environment" else False

    def no_network(root, *args, **kwargs):
        if args[0] in ("fetch", "push"):
            network.append(args)
            pytest.fail("Remote operation without preview permission")
        return git(root, *args, **kwargs)

    monkeypatch.setattr(step.cli, "remote_allowed", allowed)
    monkeypatch.setattr(repo, "git", no_network)
    for _ in range(2):
        assert "preview" in run(a)["last_error"]
    assert len(calls) == 2 and not network
    assert step.oid(a, "HEAD") == head and remote_sha(bare) == tip


@pytest.mark.parametrize(
    "value",
    [
        b'{"general": true,',
        ticket(general=True, unknownfield="x"),
        ticket(general=True),
        ticket(general=True, note="x" * 1_100_000),
    ],
)
def test_general_artifacts_never_committed_or_pushed(machines, value):
    a, _, bare = machines
    save(a)
    if isinstance(value, dict):
        value = value | {"id": "t_genchat"}
    save(a, "tickets/t_genchat.json", value)
    artifact = "tickets/t_genchat/artifacts/chat.txt"
    save(a, artifact, b"private chat text")
    success(a)
    assert tracked(a) == {TICKET}
    reachable = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-list", "--objects", "orch-state"],
        capture_output=True,
        check=True,
    ).stdout
    assert b"t_genchat" not in reachable
    assert artifact not in repo.git(a, "ls-files").stdout.decode()


@pytest.mark.parametrize(
    ("path", "payload", "remove"),
    [
        ("me/private.txt", b"orp_" + b"z" * 30, True),
        ("me/notes.txt", b"just private notes", False),
        (ART, b"prefix\n" + b"x" * 20_000 + b"\norp_" + b"z" * 30, True),
    ],
)
def test_outgoing_history_scanned_before_push(machines, monkeypatch, path, payload, remove):
    a, _, bare = both(machines)
    tip = remote_sha(bare)
    save(a, path, payload)
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]
    repo.git(a, "add", "-f", "--", path)
    repo.git(a, *identity, "commit", "-m", "unsafe history")
    if remove:
        repo.git(a, "rm", "--", path)
        repo.git(a, *identity, "commit", "-m", "remove unsafe file")
    edit(a, title="next")
    git = repo.git

    def no_push(root, *args, **kwargs):
        assert args[0] != "push", "Unsafe history reached push"
        return git(root, *args, **kwargs)

    monkeypatch.setattr(repo, "git", no_push)
    state = run(a)
    assert state["last_error"]
    assert payload.decode() not in state["last_error"]
    assert json.loads(repo.safe(a, "run/sync/state.json").read_text())["last_error"] == state["last_error"]
    assert remote_sha(bare) == tip
    reachable = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-list", "--objects", "orch-state"],
        capture_output=True,
        check=True,
    ).stdout
    assert path.encode() not in reachable


@pytest.mark.parametrize(
    "broken",
    [
        None,
        b'{"general": true,',
        b'{"id":"t_abc123"}',
        step.encoded(ticket(note="x" * 1_000_000)),
        b"x" * 25_000_001,
    ],
)
@pytest.mark.parametrize("artifact_change", ["edit", "delete"])
def test_broken_tracked_ticket_kept_on_remote(machines, broken, artifact_change):
    a, b, bare = both(machines)
    save(a, ART, b"original artifact")
    success(a)
    before = step.entries(a, "HEAD")
    original = (a / ".orch" / TICKET).read_bytes()
    if broken is None:
        (a / ".orch" / TICKET).unlink()
    else:
        save(a, value=broken)
    if artifact_change == "delete":
        (a / ".orch" / ART).unlink()
    else:
        save(a, ART, b"local artifact change")
    new_artifact = "tickets/t_abc123/artifacts/new.txt"
    save(a, new_artifact, b"not synced this round")
    # Force a new pushed tree so preservation is checked alongside real progress.
    other = "tickets/t_second.json"
    save(a, other, ticket() | {"id": "t_second"})
    state = success(a)
    assert "Ticket t_abc123 has a problem and was not synced" in str(state["skipped"])
    assert (a / ".orch" / TICKET).read_bytes() == (original if broken is None else broken)
    for path in (TICKET, ART):
        assert step.entries(a, "HEAD")[path] == before[path]
        remote_blob = subprocess.run(
            ["git", "--git-dir", str(bare), "show", "orch-state:" + path], capture_output=True, check=True
        ).stdout
        assert remote_blob == step.blob(a, before[path])
    assert new_artifact not in tracked(a)
    success(b)
    assert tracked(b) == {TICKET, ART, other}
    assert (b / ".orch" / TICKET).read_bytes() == original
    assert (b / ".orch" / ART).read_bytes() == b"original artifact"


def signed_wont(root, monkeypatch):
    from orch import humanproof

    # Use the real key, MAC and current-ledger helpers in an isolated guarded home.
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: root.parent / "proof-home")
    humanproof.human_key(root)
    check = {
        "id": "c1",
        "text": "Email finance",
        "done": False,
        "evidence": [],
        "wont_do": True,
        "reason": "Not needed",
        "wont_nonce": "test-decision",
        "by": "human:Pat",
    }
    check["wont_mac"] = humanproof.wont_sign(root, "t_abc123", check)
    assert check["wont_mac"]
    assert humanproof.wont_verifier(root)(check, "t_abc123")
    return check


@pytest.mark.parametrize("mac", ["valid", "forged", "absent"])
@pytest.mark.parametrize("side", ["local", "remote"])
def test_synced_wont_do_requires_receivers_current_mac(machines, monkeypatch, mac, side):
    a, b, _ = both(machines)
    check = signed_wont(b, monkeypatch)
    if mac == "forged":
        check["wont_mac"] = "forged"
    elif mac == "absent":
        check.pop("wont_mac")
    edit(a, title="Remote change")
    edit(b, note="Local change")
    edit(b if side == "local" else a, checklist=[check])
    success(a)
    sync_apply, merge_document, write = step.tickets.sync_apply, step.merge_document, step.write
    active, checked = {}, {}

    @contextlib.contextmanager
    def locked(root, tid):
        with sync_apply(root, tid):
            token = object()
            active[tid] = token
            try:
                yield
            finally:
                active.pop(tid)

    def merged(root, path, *args):
        doc = merge_document(root, path, *args)
        if path == TICKET and "t_abc123" in active:
            checked["lock"] = active["t_abc123"]
            checked["data"] = step.encoded(doc)
        return doc

    def written(root, path, data):
        if root == b and path == TICKET:
            assert checked["lock"] is active["t_abc123"]
            assert checked["data"] == data
            checked["written"] = True
        return write(root, path, data)

    monkeypatch.setattr(step.tickets, "sync_apply", locked)
    monkeypatch.setattr(step, "merge_document", merged)
    monkeypatch.setattr(step, "write", written)
    success(b)
    assert checked["written"]
    result = load(b)
    assert bool(result["checklist"][0].get("wont_do")) == (mac == "valid")
    assert result["title"] == "Remote change" and result["note"] == "Local change"
    assert (b / ".orch" / TICKET).read_bytes() == repo.git(b, "show", "HEAD:" + TICKET).stdout


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("decision", ["wont", "verdict"])
def test_ledger_changes_before_apply_fail_closed(machines, monkeypatch, recover, decision):
    from orch import humanproof

    a, b, bare = both(machines)
    check = signed_wont(b, monkeypatch)
    if decision == "wont":
        edit(a, checklist=[check], title="Remote change")
        text = "Marked c1 as won't do"
    else:
        doc = load(a) | {"status": "done"}
        entry = humanproof.verdict_sign(b, doc, "person")
        edit(a, status="done", verdicts=[entry], title="Remote change")
        text = "Status review -> done"
    edit(a, history=[{"at": NOW, "by": "human:Pat", "text": text}])
    success(a)
    before, head, tip = (b / ".orch" / TICKET).read_bytes(), step.oid(b, "HEAD"), remote_sha(bare)
    apply = step.apply

    def revoke(root, old, new, state, merges=None):
        if decision == "wont":
            assert humanproof._ledger_set(root, "t_abc123", "c1", None)
        else:
            assert humanproof._verdict_ledger_put(root, "t_abc123", None)
        if recover:
            raise RuntimeError("crash")
        return apply(root, old, new, state, merges)

    with monkeypatch.context() as m:
        m.setattr(step, "apply", revoke)
        if recover:
            with pytest.raises(RuntimeError, match="crash"):
                run(b)
        else:
            assert "busy" in run(b)["last_error"]
    if recover:
        assert "busy" in run(b)["last_error"]
    assert (b / ".orch" / TICKET).read_bytes() == before
    assert step.oid(b, "HEAD") == head and remote_sha(bare) == tip
    assert not (b / ".orch/run/sync/pending.json").exists()


def test_idle_syncs_and_one_edit_converge_without_churn(machines, monkeypatch):
    a, b, bare = machines
    save(a, value=ticket(revision=7))
    success(a)
    success(b)
    success(a)
    tip = remote_sha(bare)
    content = (a / ".orch" / TICKET).read_bytes()
    assert (b / ".orch" / TICKET).read_bytes() == content
    assert step.oid(a, "HEAD") == step.oid(b, "HEAD") == tip.decode()
    git, write = repo.git, step.write
    with monkeypatch.context() as m:

        def no_commit_or_push(root, *args, **kwargs):
            assert "commit-tree" not in args and args[0] != "push"
            return git(root, *args, **kwargs)

        def no_ticket_write(root, path, data):
            assert path != TICKET
            return write(root, path, data)

        m.setattr(repo, "git", no_commit_or_push)
        m.setattr(step, "write", no_ticket_write)
        for root in (a, b, a, b, a, b):
            success(root)
            assert remote_sha(bare) == tip
            assert step.oid(root, "HEAD") == tip.decode()
            assert (root / ".orch" / TICKET).read_bytes() == content
            assert load(root)["revision"] == 7
    edit(a, title="One real edit", revision=8)
    success(a)
    edited = remote_sha(bare)
    assert edited != tip
    assert repo.git(a, "rev-list", "--count", f"{tip.decode()}..{edited.decode()}").stdout.strip() == b"1"
    assert repo.git(a, "rev-parse", "HEAD^").stdout.strip() == tip
    for root in (b, a, b):
        success(root)
        assert remote_sha(bare) == edited
        assert step.oid(root, "HEAD") == edited.decode()
        assert load(root)["revision"] == 8
    assert (a / ".orch" / TICKET).read_bytes() == (b / ".orch" / TICKET).read_bytes()


@pytest.mark.parametrize("decision", ["wont", "verdict"])
@pytest.mark.parametrize("proof", ["forged", "valid", "foreign"])
def test_remote_human_history_is_demoted_even_with_verified_decision(machines, monkeypatch, decision, proof):
    from orch import cli, humanproof, tickets

    a, b, _ = both(machines)
    valid = proof == "valid"
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: root.parent / "proof-homes" / root.name)
    humanproof.human_key(b)
    if valid:
        # Fixture only: give A the same guarded authority as B. Real independent
        # machines cannot verify each other's MACs merely by syncing ticket files.
        (a / ".orch/.local-id").write_bytes((b / ".orch/.local-id").read_bytes())
    check = {
        "id": "c2", "text": "Order dessert (B)", "done": False, "evidence": [],
        "wont_do": True, "wont_nonce": "test-decision",
    }
    if decision == "wont":
        text = "Marked as won't do: Order dessert (B)"
        if proof == "forged":
            check["wont_mac"] = "fake"
            edit(b, checklist=[check])
        else:
            edit(b, checklist=[{"id": "c2", "text": check["text"], "done": False, "evidence": []}])
            tickets.check_wont_do(b, "t_abc123", "c2", "human:lindenmann")
    else:
        text = "Looks good"
        if proof == "forged":
            entry = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
            edit(b, status="done", verdicts=[entry])
        else:
            edit(b, status="review")
            tickets.accept_review(b, "t_abc123", "human:lindenmann", proven=True)
    if proof == "forged":
        line = {"at": NOW, "by": "human:lindenmann", "text": text}
        edit(b, history=[line])
    else:
        line = load(b)["history"][-1]
        text = line["text"]
    if valid:
        import shutil

        # Copy only test authority, preserving private modes and A's own path binding.
        humanproof.human_key(a)
        for name in ("human.key", humanproof.LEDGER, humanproof.VERDICT_LEDGER):
            source = humanproof.key_dir(b) / name
            if source.exists():
                shutil.copy2(source, humanproof.key_dir(a) / name)
        doc = load(b)
        if decision == "wont":
            assert humanproof.wont_verifier(a)(doc["checklist"][0], "t_abc123")
        else:
            assert humanproof.verdict_ok(a, doc)
    success(b)

    sync_apply = tickets.sync_apply
    verifier = humanproof.wont_verifier if decision == "wont" else humanproof.verdict_verifier
    locked, verified = [], []

    @contextlib.contextmanager
    def lock(root, tid):
        with sync_apply(root, tid):
            locked.append(tid)
            try:
                yield
            finally:
                locked.pop()

    def checking(root):
        verify = verifier(root)

        def call(*args):
            if root == a and locked:
                verified.append(True)
            return verify(*args)

        return call

    monkeypatch.setattr(tickets, "sync_apply", lock)
    monkeypatch.setattr(humanproof, "wont_verifier" if decision == "wont" else "verdict_verifier", checking)
    success(a)
    assert verified  # The receiving core rechecks under the ticket lock before writing.
    result = load(a)
    expected = {
        **line, "by": "agent:sync", "text": "(synced, not verified here) " + text
    }
    assert result["history"] == [expected]
    if decision == "wont":
        assert bool(result["checklist"][0].get("wont_do")) is valid
    else:
        assert humanproof.verdict_ok(a, result) is valid
    # The CLI's shared ticket formatter must expose the stored attribution and warning.
    rendered = cli._show(result, a)
    assert expected["by"] in rendered
    assert tickets.history_line(expected["text"], result["checklist"]) in rendered
    assert "human:lindenmann:" not in rendered
    success(b)
    success(a)
    assert load(a)["history"] == [expected]
    # B owns the original locally; A retains its demotion on subsequent syncs.
    assert line in load(b)["history"] and expected in load(b)["history"]
    success(b)
    success(a)
    assert load(a)["history"] == [expected]
    assert line in load(b)["history"]


def test_new_remote_ticket_history_is_not_shared_history(machines):
    a, b, _ = machines
    line = {"at": NOW, "by": "human:lindenmann", "text": "Looks good"}
    save(b, value=ticket() | {"history": [line], "status": "done"})
    success(b)
    success(a)
    expected = {**line, "by": "agent:sync", "text": "(synced, not verified here) Looks good"}
    assert load(a)["history"] == [expected]
    success(b)
    success(a)
    assert load(a)["history"] == [expected]
    assert line in load(b)["history"] and expected in load(b)["history"]


def test_first_sync_marks_ownership_before_import(machines, monkeypatch):
    from orch import runs, tickets

    a, b, _ = machines
    value = ticket() | {
        "sessions": [{"id": "peer-session", "agent": "claude", "host": runs.host(), "last_used": NOW}]
    }
    save(a, value=value)
    success(a)
    marker = b / ".orch/run/own-sessions.adopted"
    assert json.loads(marker.read_text()) == {"adopted": True}
    assert not (b / ".orch" / TICKET).exists()
    original = repo.git

    def git(root, *args, **kwargs):
        if root == b and args[0] == "fetch":
            assert json.loads(marker.read_text()) == {"adopted": True}
            assert not (b / ".orch" / TICKET).exists()
        return original(root, *args, **kwargs)

    monkeypatch.setattr(repo, "git", git)
    success(b)
    assert json.loads(marker.read_text()) == {"adopted": True}
    assert "sessions" not in load(b)  # normal sync also strips peer session metadata
    # Even if peer session metadata later arrives on disk, it cannot be adopted.
    save(b, value=load(b) | {"sessions": value["sessions"]})
    assert tickets.sessions_for(b, value["id"], load(b), "claude", runs.host()) is None
