import io
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from orch import humanproof
from orch.errors import Refused
from test_step import ART, NOW, TICKET, run, save, success
from test_two_machines import both, edit, hostile, load, machines, remote_sha

from orch_sync import approval, cli, needs, pause, repo, step

__all__ = ["machines"]


@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_artifact_keep_both(machines, keep, monkeypatch):
    a, b, bare = both(machines)
    save(a, ART, b"base")
    success(a)
    success(b)
    save(a, ART, b"remote")
    save(b, ART, b"local")
    success(a)
    result = run(b)
    assert result["paused"]["files"] == [ART]
    assert result["paused"]["remote_sha"] == remote_sha(bare).decode()
    assert repo.safe(b, "run/sync/theirs/" + ART).read_bytes() == b"remote"
    tip = remote_sha(bare)
    with monkeypatch.context() as m:
        m.setattr(repo, "git", lambda *a, **k: pytest.fail("Paused tick called git"))
        assert run(b) == result
    assert repo.safe(b, ART).read_bytes() == b"local"
    rows = needs.rows(b)
    assert rows[0]["id"].startswith("sync:paused:")
    assert rows[0]["answer"]["options"] == ["Keep mine", "Keep theirs"]
    assert all(len(r["text"]) <= 500 and "git" not in r["text"].lower() for r in rows)
    assert remote_sha(bare) == tip
    result = pause.resolve(b, ART, keep, now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    assert repo.safe(b, ART).read_bytes() == (b"local" if keep == "mine" else b"remote")
    if keep == "theirs":
        assert repo.safe(b, ART).with_name("a (mine 2026-11-11).txt").read_bytes() == b"local"
    success(a)
    success(b)


def test_remote_moves_recompute_before_resolution(machines):
    a, b, _ = both(machines)
    save(a, ART, b"base")
    success(a)
    success(b)
    save(a, ART, b"remote one")
    save(b, ART, b"local")
    success(a)
    run(b)
    save(a, ART, b"remote two")
    success(a)
    result = pause.resolve(b, ART, "theirs", now=NOW)
    assert result["review_again"] and result["paused"]
    assert repo.safe(b, ART).read_bytes() == b"local"
    assert repo.safe(b, "run/sync/theirs/" + ART).read_bytes() == b"remote two"


@pytest.mark.parametrize("path", [TICKET, ART])
@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_deletion_pause_preserves_survivor(machines, path, keep):
    a, b, bare = both(machines)
    save(a, ART, b"keep this")
    success(a)
    success(b)
    repo.git(a, "rm", "--", path)
    hostile(a, bare, ["commit", "-m", "remove"])
    before = repo.safe(b, path).read_bytes()
    assert path in run(b)["paused"]["files"]
    result = pause.resolve(b, path, keep, now=NOW)
    assert not result.get("last_error"), result
    assert repo.safe(b, path).read_bytes() == before


def proof(root, target, monkeypatch):
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: root.parent / "proof-home")
    key = humanproof.human_key(root)
    token = humanproof.mint(key, humanproof.new_payload("addon.act", target, "human:Pat"))
    monkeypatch.setattr("sys.stdin", io.StringIO(token + "\n"))
    return SimpleNamespace(proof_stdin=True, by=None)


def test_held_approval_and_changed_hash(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, ext={"automation": {"enabled": True}})
    success(a)
    success(b)
    assert not load(b).get("ext", {}).get("automation")
    assert any(r["id"] == "sync:held:t_abc123" for r in needs.rows(b))
    with pytest.raises(Refused):
        approval.approve(b, "t_abc123", "automation", SimpleNamespace(proof_stdin=False, by="agent:test"))
    assert not cli.read(b, "approved")
    value = {"enabled": True}
    args = proof(b, "sync:t_abc123:automation:" + approval.digest(value), monkeypatch)
    approval.approve(b, "t_abc123", "automation", args)
    assert load(b)["ext"]["automation"] == value
    assert cli.read(b, "approved")["t_abc123"]["automation"] == approval.digest(value)
    success(b)
    success(a)
    edit(a, ext={"automation": {"enabled": False}})
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == value
    assert any(r["id"] == "sync:held:t_abc123" for r in needs.rows(b))


@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_rewritten_pause_resolves(machines, keep):
    a, b, _ = both(machines)
    tree = step.oid(a, "HEAD^{tree}")
    new = step.commit(a, tree, [], "2026-11-11T13:00:00Z")
    repo.git(a, "push", "--force", "origin", f"{new}:orch-state")
    assert run(b)["paused"]["reason"] == "The remote history was rewritten"
    result = pause.resolve(b, TICKET, keep, now=NOW)
    assert not result.get("last_error"), result
    success(b)


def test_invalid_incoming_keep_mine(machines):
    a, b, bare = both(machines)
    save(a, value=b'{"broken":')
    repo.git(a, "add", "--", TICKET)
    hostile(a, bare, ["commit", "-m", "broken"])
    before = load(b)
    assert run(b)["paused"]
    with pytest.raises(ValueError):
        pause.resolve(b, TICKET, "theirs", now=NOW)
    assert load(b) == before
    result = pause.resolve(b, TICKET, "mine", now=NOW)
    assert not result.get("last_error"), result
    assert load(b) == before


def test_needs_contract(machines):
    from pathlib import Path

    a, b, _ = both(machines)
    edit(a, ext={"automation": {"enabled": True}})
    success(a)
    success(b)
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts/needs.schema.json").read_text())
    Draft202012Validator(schema).validate(needs.rows(b))


@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_cannot_check_incoming_needs_person_for_theirs(machines, keep, monkeypatch):
    a, b, bare = both(machines)
    save(a, ART, b"readable")
    success(a)
    success(b)
    payload = b"PK\x03\x04uncheckable archive"
    save(a, ART, payload)
    repo.git(a, "add", "--", ART)
    hostile(a, bare, ["commit", "-m", "archive"])
    assert run(b)["paused"]["files"] == [ART]
    args = None
    if keep == "theirs":
        with pytest.raises(Refused):
            pause.resolve(b, ART, keep, SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)
        assert repo.safe(b, ART).read_bytes() == b"readable"
        import hashlib

        args = proof(b, "sync:file:" + hashlib.sha256(payload).hexdigest(), monkeypatch)
    result = pause.resolve(b, ART, keep, args, now=NOW)
    assert not result.get("last_error"), result
    assert repo.safe(b, ART).read_bytes() == (payload if keep == "theirs" else b"readable")
    success(b)


def test_ticket_theirs_preserves_history_and_sessions(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, title="Remote title")
    success(a)
    edit(b, title="Local title")
    original = step.merge.merge_ticket
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        assert run(b)["paused"]["files"] == [TICKET]
    assert step.merge.merge_ticket is original
    result = pause.resolve(b, TICKET, "theirs", now=NOW)
    assert not result.get("last_error"), result
    assert load(b)["title"] == "Remote title"
    assert any(
        "Local title" in h["text"] and "my version before sync" in h["text"] for h in load(b)["history"]
    )


def test_saved_copy_tamper_refused(machines):
    a, b, _ = both(machines)
    save(a, ART, b"base")
    success(a)
    success(b)
    save(a, ART, b"remote")
    save(b, ART, b"local")
    success(a)
    run(b)
    repo.safe(b, "run/sync/theirs/" + ART).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        pause.resolve(b, ART, "theirs", now=NOW)
    assert repo.safe(b, ART).read_bytes() == b"local"


def test_inert_manifest_is_local_authority(machines, monkeypatch):
    a, b, _ = both(machines)
    edit(a, ext={"example": {"data": 42}})
    success(a)
    monkeypatch.setattr(approval.addons, "discover", lambda: {"example": {"ticket_ext_inert": True}})
    success(b)
    assert load(b)["ext"]["example"] == {"data": 42}
    assert not approval.held(b)


@pytest.mark.parametrize("incoming_at", ["2001-01-01T00:00:00Z", "2026-11-11T13:00:00Z"])
def test_concurrent_keys_pause_identically_without_moving_local_keys(machines, incoming_at, tmp_path):
    from test_step import ticket

    a, b, _ = both(machines)
    first = "tickets/t_first1.json"
    second = "tickets/t_later1.json"
    save(
        a,
        first,
        ticket() | {"id": "t_first1", "key": "DM1-13", "title": "Incoming", "created_at": incoming_at},
    )
    save(b, second, ticket() | {"id": "t_later1", "key": "DM1-13", "title": "Local"})
    save(b, "ticket-counter.json", {"last": 14})
    success(a)
    before = repo.safe(b, second).read_bytes()
    result = run(b)
    assert result["paused"]["files"] == [first, second]
    assert repo.safe(b, second).read_bytes() == before
    assert not repo.safe(b, first).exists()
    assert json.loads(repo.safe(b, "ticket-counter.json").read_text())["last"] == 14
    b_need = needs.rows(b)[0]
    assert b_need["text"] == "Two tickets have the same number DM1-13. Which keeps it?"
    assert b_need["answer"]["options"] == ["Incoming (t_first1)", "Local (t_later1)"]

    # Exchange the offline heads in the opposite direction, before any resolution.
    repo.git(a, "fetch", str(repo.safe(b, ".git")), "refs/heads/orch-state")
    remote = step.oid(a, "FETCH_HEAD")
    before = repo.safe(a, first).read_bytes()
    with pytest.raises(pause.Pause) as caught:
        step.merged_tree(a, step.oid(a, "HEAD"), remote, tmp_path / "opposite-index", NOW)
    state = {}
    pause.capture(a, state, caught.value, remote, NOW)
    step.write(a, "run/sync/state.json", step.encoded(state))
    assert needs.rows(a)[0] == b_need
    assert repo.safe(a, first).read_bytes() == before
    assert not repo.safe(a, second).exists()


def test_missing_ticket_need_and_ack(machines):
    a, _, _ = both(machines)
    repo.safe(a, TICKET).unlink()
    success(a)
    assert any(r["id"] == "sync:deleted:t_abc123" for r in needs.rows(a))
    assert cli.main(["--dir", str(a), "deleted", "t_abc123", "--keep", "--json"]) == 0
    assert not any(r["id"] == "sync:deleted:t_abc123" for r in needs.rows(a))


def test_public_visibility_warns_once(root, monkeypatch, capsys):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    args = ["--dir", str(root), "set", "--mode", "remote", "--remote", "https://github.com/owner/repository"]
    assert cli.main(args) == 0
    assert "Anyone can read" in capsys.readouterr().err
    assert cli.main(args) == 0
    assert "Anyone can read" not in capsys.readouterr().err
    assert cli.main(args + ["--kind", "team"]) == 2


def test_artifact_both_changed_even_when_text_merge_is_clean(machines):
    a, b, _ = both(machines)
    save(a, ART, b"first\nsecond\nthird\nfourth\n")
    success(a)
    success(b)
    save(a, ART, b"remote\nsecond\nthird\nfourth\n")
    save(b, ART, b"first\nsecond\nthird\nlocal\n")
    success(a)
    assert run(b)["paused"]["files"] == [ART]
    assert repo.safe(b, ART).read_bytes().endswith(b"local\n")


def test_counter_reserves_old_keys_without_new_clash(machines):
    a, b, _ = both(machines)
    edit(a, ext={"sync": {"old_keys": ["DM1-99"]}})
    success(a)
    success(b)
    assert json.loads(repo.safe(b, "ticket-counter.json").read_text())["last"] == 99


@pytest.mark.parametrize("count", [2, 9])
def test_key_clash_need_respects_contract_with_long_titles(root, count):
    from pathlib import Path

    candidates = [{"id": f"t_test{i:03}", "title": "Long title " * 20} for i in range(count)]
    state = {
        "paused": {
            "files": [f"tickets/{t['id']}.json" for t in candidates],
            "key_clashes": {"DM1-13": candidates},
            "since": NOW,
            "reason": "Key clash",
        }
    }
    step.write(root, "run/sync/state.json", step.encoded(state))
    rows = needs.rows(root)
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts/needs.schema.json").read_text())
    Draft202012Validator(schema).validate(rows)
    assert len(rows) == 1
    assert len(rows[0]["answer"]["options"]) == (count if count <= 8 else 0)


@pytest.mark.parametrize("reverse", [False, True])
def test_remote_cannot_steal_known_key(machines, reverse):
    from test_step import ticket

    a, b, bare = both(machines)
    if reverse:
        a, b = b, a
    local = "tickets/t_local1.json"
    evil = "tickets/t_evil01.json"
    save(a, local, ticket() | {"id": "t_local1", "key": "DM1-5"})
    success(a)
    success(b)
    before = repo.safe(b, local).read_bytes()
    save(a, local, ticket() | {"id": "t_local1", "key": "DM1-99"})
    save(a, evil, ticket() | {"id": "t_evil01", "key": "DM1-5"})
    repo.git(a, "add", "--", local, evil)
    hostile(a, bare, ["commit", "-m", "steal key"])
    result = run(b)
    assert result["paused"]["key_clashes"]["DM1-5"]
    assert repo.safe(b, local).read_bytes() == before
    assert not repo.safe(b, evil).exists()
    assert needs.rows(b)[0]["cli"].startswith("orch sync keep-key DM1-5")


@pytest.mark.parametrize("winner", ["t_first1", "t_later1"])
def test_person_keeps_key_without_live_duplicates(machines, monkeypatch, winner):
    from test_step import ticket

    a, b, _ = both(machines)
    for root, tid in [(a, "t_first1"), (b, "t_later1")]:
        save(root, f"tickets/{tid}.json", ticket() | {"id": tid, "key": "DM1-13"})
    success(a)
    assert run(b)["paused"]
    for keep in ("mine", "theirs"):
        with pytest.raises(repo.Refused, match="keep-key"):
            pause.resolve(b, "tickets/t_first1.json", keep, now=NOW)
    with pytest.raises(Refused):
        pause.keep_key(b, "DM1-13", winner, SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)
    original_write = step.write

    def checked_write(root, path, data):
        original_write(root, path, data)
        keys = [json.loads(p.read_bytes()).get("key") for p in (root / ".orch" / "tickets").glob("*.json")]
        assert len(keys) == len(set(keys))

    monkeypatch.setattr(step, "write", checked_write)
    remote = cli.read(b, "state")["paused"]["remote_sha"]
    result = pause.keep_key(b, "DM1-13", winner, proof(b, f"sync:keep-key:DM1-13:{winner}:{remote}", monkeypatch), now=NOW)
    assert not result.get("last_error"), result
    assert not result.get("paused")
    loser = "t_later1" if winner == "t_first1" else "t_first1"
    moved = json.loads(repo.safe(b, f"tickets/{loser}.json").read_bytes())
    assert moved["key"] != "DM1-13"
    assert "DM1-13" in moved["ext"]["sync"]["old_keys"]
    assert any("key changed" in h["text"] for h in moved["history"])
    # A locally known number requires the other computer's own person decision too.
    result = run(a)
    if result.get("paused"):
        remote = result["paused"]["remote_sha"]
        pause.keep_key(a, "DM1-13", winner, proof(a, f"sync:keep-key:DM1-13:{winner}:{remote}", monkeypatch), now=NOW)
    success(a)
    success(b)
    success(a)
    for tid in (winner, loser):
        assert repo.safe(a, f"tickets/{tid}.json").read_bytes() == repo.safe(b, f"tickets/{tid}.json").read_bytes()


@pytest.mark.parametrize("current", [0, 40])
def test_keep_key_reserves_live_counter_when_resume_is_offline(machines, monkeypatch, current):
    from orch import config, tickets
    from test_step import ticket

    a, b, bare = both(machines)
    first, second = "tickets/t_first1.json", "tickets/t_later1.json"
    save(a, first, ticket() | {"id": "t_first1", "key": "DM1-5"})
    save(b, second, ticket() | {"id": "t_later1", "key": "DM1-5"})
    save(b, "ticket-counter.json", {"last": current})
    config.set_code(b, "DM1")
    success(a)
    remote = run(b)["paused"]["remote_sha"]
    offline = bare.with_name("offline.git")
    original_run = step._run

    def resume_offline(*args, **kwargs):
        bare.rename(offline)
        return original_run(*args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(step, "_run", resume_offline)
        result = pause.keep_key(
            b, "DM1-5", "t_later1",
            proof(b, f"sync:keep-key:DM1-5:t_later1:{remote}", m), now=NOW,
        )
    assert result["last_error"] and not result.get("paused")
    reserved = max(current, 5) + 1
    assert json.loads(repo.safe(b, "ticket-counter.json").read_bytes())["last"] == reserved
    assert not repo.safe(b, first).exists()
    created = tickets.create(b, "Created offline", "human:Pat")
    assert created["key"] == f"DM1-{reserved + 1}"
    offline.rename(bare)
    for _ in range(2):
        assert not success(b).get("paused")
    assert json.loads(repo.safe(b, first).read_bytes())["key"] == f"DM1-{reserved}"
    assert step.oid(b, "HEAD") == remote_sha(bare).decode()
    for path in (first, second, f"tickets/{created['id']}.json", "ticket-counter.json"):
        assert repo.safe(b, path).read_bytes() == repo.git(b, "show", "HEAD:" + path).stdout


def test_ignore_requires_person(machines):
    a, b, _ = both(machines)
    edit(a, ext={"automation": {"enabled": True}})
    success(a)
    success(b)
    with pytest.raises(Refused):
        approval.approve(b, "t_abc123", "automation", SimpleNamespace(ignore=True, proof_stdin=False, by="agent:test"))
    assert approval.held(b)
    assert not cli.read(b, "ignored")


@pytest.mark.parametrize("value", [{"command": "run"}, {"old_keys": ["bad"]}, {"old_keys": [f"DM1-{i}" for i in range(1, 102)]}])
def test_invalid_sync_extension_refused(machines, value):
    a, b, bare = both(machines)
    edit(a, ext={"sync": value})
    repo.git(a, "add", "--", TICKET)
    hostile(a, bare, ["commit", "-m", "invalid sync extension"])
    before = repo.safe(b, TICKET).read_bytes()
    assert run(b)["paused"]
    assert repo.safe(b, TICKET).read_bytes() == before


def test_visibility_never_persists_userinfo(root, monkeypatch):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    address = "https://person:credential@example.com/owner/repo"
    args = ["--dir", str(root), "set", "--mode", "remote", "--remote", address]
    assert cli.main(args) == 2
    assert not cli.read(root, "visibility")
    # Defense in depth: even if remote validation changes, visibility is sanitized.
    monkeypatch.setattr(repo, "validate_url", lambda url: None)
    monkeypatch.setattr(repo, "set_remote", lambda *a: None)
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "unknown")
    assert cli.main(args) == 0
    assert cli.read(root, "visibility") == {"https://example.com/owner/repo": "unknown"}


@pytest.mark.parametrize("winner", ["t_local1", "t_evil01"])
def test_keep_key_remote_only_uses_verified_merge(machines, monkeypatch, winner):
    from test_step import ticket

    a, b, bare = both(machines)
    local, evil = "tickets/t_local1.json", "tickets/t_evil01.json"
    save(a, local, ticket() | {"id": "t_local1", "key": "DM1-5"})
    success(a)
    success(b)
    original = json.loads(repo.safe(b, local).read_bytes())
    forged = {
        "id": "c1", "text": "Email finance", "done": False, "evidence": [],
        "wont_do": True, "reason": "forged", "by": "human:Ann", "at": NOW,
        "wont_nonce": "n1", "wont_mac": "garbage",
    }
    save(a, local, ticket() | {"id": "t_local1", "key": "DM1-99"})
    save(a, evil, ticket() | {"id": "t_evil01", "key": "DM1-5", "checklist": [forged]})
    repo.git(a, "add", "--", local, evil)
    hostile(a, bare, ["commit", "-m", "forged remote key clash"])
    result = run(b)
    remote = result["paused"]["remote_sha"]
    original_write, original_run = step.write, step._run

    def checked_write(root, path, data):
        if root == b and path == evil:
            assert "wont_do" not in json.loads(data)["checklist"][0]
        original_write(root, path, data)
        keys = [json.loads(p.read_bytes()).get("key") for p in (root / ".orch/tickets").glob("*.json")]
        assert len(keys) == len(set(keys))

    def resume(root, *args):
        if root == b:
            assert not repo.safe(b, evil).exists()
            changed = json.loads(repo.safe(b, local).read_bytes())
            for field in original.keys() | changed.keys():
                if field not in ("key", "ext", "history"):
                    assert changed.get(field) == original.get(field)
        return original_run(root, *args)

    monkeypatch.setattr(step, "write", checked_write)
    monkeypatch.setattr(step, "_run", resume)
    result = pause.keep_key(b, "DM1-5", winner, proof(b, f"sync:keep-key:DM1-5:{winner}:{remote}", monkeypatch), now=NOW)
    monkeypatch.setattr(step, "_run", original_run)
    assert not result.get("paused") and not result.get("last_error"), result
    success(b)
    for data in (repo.safe(b, evil).read_bytes(), repo.git(b, "show", "HEAD:" + evil).stdout):
        doc = json.loads(data)
        assert "wont_do" not in doc["checklist"][0]
        assert (doc["key"] == "DM1-5") == (winner == "t_evil01")
    # Convergence for two honest machines is covered by
    # test_person_keeps_key_without_live_duplicates; A here authored the forgery.


@pytest.mark.parametrize("problem", ["manifest", "commit", "path", "size", "private", "local-general"])
def test_keep_key_rechecks_incoming_before_reading_tickets(machines, monkeypatch, problem):
    from test_step import ticket

    from orch_sync import incoming

    a, b, _ = both(machines)
    for root, tid in [(a, "t_first1"), (b, "t_later1")]:
        save(root, f"tickets/{tid}.json", ticket() | {"id": tid, "key": "DM1-13"})
    success(a)
    result = run(b)
    remote = result["paused"]["remote_sha"]
    if problem == "manifest":
        step.write(b, "run/sync/theirs.json", step.encoded({"remote_sha": "stale"}))
    elif problem == "local-general":
        path = "tickets/t_later1.json"
        save(b, path, json.loads(repo.safe(b, path).read_bytes()) | {"general": True})
    else:
        checked = incoming.Result("wrong" if problem == "commit" else remote, [
            incoming.Problem("", problem, "refused")
        ])
        monkeypatch.setattr(incoming, "check", lambda *a, **kw: checked)
    before = repo.safe(b, "tickets/t_later1.json").read_bytes()
    args = proof(b, f"sync:keep-key:DM1-13:t_first1:{remote}", monkeypatch)
    with pytest.raises(repo.Refused):
        pause.keep_key(b, "DM1-13", "t_first1", args, now=NOW)
    assert repo.safe(b, "tickets/t_later1.json").read_bytes() == before
    assert not repo.safe(b, "tickets/t_first1.json").exists()
    assert not cli.read(b, "choices")
