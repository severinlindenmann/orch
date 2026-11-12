import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from orch import humanproof
from orch.errors import Refused
from test_step import ART, NOW, TICKET, at, configure, run, save, success, ticket, tracked
from test_two_machines import both, edit, hostile, load, machines, remote_sha

from orch_sync import approval, cli, needs, pause, records, repo, step

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
        assert repo.safe(b, ART).with_name(f"a (mine {NOW[:10]}).txt").read_bytes() == b"local"
    success(a)
    success(b)


def test_changed_choice_asks_again_instead_of_busy_forever(machines):
    # Fable B7: a chosen file edited before the last choice made every later run "busy", unresolvable.
    a, b, _ = both(machines)
    other = "tickets/t_abc123/artifacts/b.txt"
    for path in (ART, other):
        save(a, path, b"base")
    success(a)
    success(b)
    for path in (ART, other):
        save(a, path, b"remote")
        save(b, path, b"local")
    success(a)
    assert sorted(run(b)["paused"]["files"]) == sorted([ART, other])
    assert pause.resolve(b, ART, "theirs", now=NOW)["paused"]
    save(b, ART, b"agent edit after the choice")
    result = pause.resolve(b, other, "theirs", now=NOW)
    assert result["paused"]["files"] == [ART] and "choose again" in result["paused"]["reason"]
    result = pause.resolve(b, ART, "mine", now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    assert repo.safe(b, ART).read_bytes() == b"agent edit after the choice"


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
    args = proof(b, "sync:allow:t_abc123:automation:" + approval.digest(value), monkeypatch)
    approval.approve(b, "t_abc123", "automation", args)
    assert load(b)["ext"]["automation"] == value
    entry = cli.read(b, "approved")["t_abc123"]["automation"]
    target = "t_abc123:automation:" + approval.digest(value)
    assert entry["hash"] == approval.digest(value) and records.ok(b, "allow", target, entry)
    assert not records.ok(b, "allow", target, entry, single_use=True)  # #540: used once, spent at once
    success(b)
    success(a)
    edit(a, ext={"automation": {"enabled": False}})
    success(a)
    success(b)
    assert load(b)["ext"]["automation"] == value
    assert any(r["id"] == "sync:held:t_abc123" for r in needs.rows(b))


@pytest.mark.parametrize("decision", ["allow", "ignore"])
def test_allow_and_ignore_need_distinct_proofs(machines, monkeypatch, decision):
    # Fable B12: the proof for Ignore was also a proof for Allow (and the other way round).
    a, b, _ = both(machines)
    value = {"enabled": True}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    other = "ignore" if decision == "allow" else "allow"
    target = f"sync:{decision}:t_abc123:automation:" + approval.digest(value)
    ignore = decision == "ignore"
    with pytest.raises(Refused):
        args = proof(b, target.replace(decision, other, 1), monkeypatch)
        approval.approve(b, "t_abc123", "automation", SimpleNamespace(**vars(args), ignore=ignore))
    assert approval.held(b) and not cli.read(b, "approved") and not cli.read(b, "ignored")
    args = proof(b, target, monkeypatch)
    approval.approve(b, "t_abc123", "automation", SimpleNamespace(**vars(args), ignore=ignore))
    assert not approval.held(b)
    if ignore:
        assert "automation" not in load(b).get("ext", {})
        entry = cli.read(b, "ignored")["t_abc123"]["automation"]
        assert records.ok(b, "ignore", "t_abc123:automation:" + approval.digest(value), entry)
    else:
        assert load(b)["ext"]["automation"] == value


@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_rewritten_pause_resolves(machines, keep):
    a, b, _ = both(machines)
    tree = step.oid(a, "HEAD^{tree}")
    new = step.commit(a, tree, [], at(13))
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
    shared = {"at": NOW, "by": "human:Pat", "text": "Already local"}
    remote = {"at": NOW, "by": "human:Pat", "text": "Remote claim"}
    edit(a, history=[shared])
    edit(b, history=[shared])
    success(a)
    success(b)
    edit(a, title="Remote title", history=[shared, remote])
    success(a)
    edit(b, title="Local title")
    original = step.merge.merge_ticket
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        assert run(b)["paused"]["files"] == [TICKET]
    assert step.merge.merge_ticket is original
    result = pause.resolve(b, TICKET, "theirs", keep_theirs_proof(b, monkeypatch), now=NOW)
    assert not result.get("last_error"), result
    assert load(b)["title"] == "Remote title"
    assert shared in load(b)["history"]
    assert remote not in load(b)["history"]
    assert {**remote, "by": "agent:sync", "text": "(synced, not verified here) Remote claim"} in load(b)[
        "history"
    ]
    assert any(
        "Local title" in h["text"] and "my version before sync" in h["text"] for h in load(b)["history"]
    )


def keep_theirs_proof(root, monkeypatch, path=TICKET):
    import hashlib

    theirs = repo.safe(root, "run/sync/theirs/" + path).read_bytes()
    digest = hashlib.sha256(path.encode() + b"\0" + theirs).hexdigest()
    return proof(root, "sync:keep-theirs:" + digest, monkeypatch)


def test_keep_theirs_needs_person_and_keeps_local_decisions(machines, monkeypatch):
    # Fable B2: keep-theirs installed the peer's decision fields as locally trusted, with no person involved.
    a, b, _ = both(machines)
    forged_verdict = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    forged_wont = {
        "id": "c1",
        "text": "Pay the invoice",
        "done": False,
        "evidence": [],
        "wont_do": True,
        "reason": "Not needed",
        "wont_nonce": "n1",
        "wont_mac": "forged",
    }
    edit(b, checklist=[{"id": "c1", "text": "Pay the invoice", "done": False, "evidence": []}])
    success(b)
    success(a)
    edit(a, title="Remote title", status="done", verdicts=[forged_verdict], checklist=[forged_wont])
    success(a)
    edit(b, title="Local title")
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        assert run(b)["paused"]["files"] == [TICKET]
    before = repo.safe(b, TICKET).read_bytes()
    with pytest.raises(Refused):
        pause.resolve(b, TICKET, "theirs", SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)
    assert repo.safe(b, TICKET).read_bytes() == before
    result = pause.resolve(b, TICKET, "theirs", keep_theirs_proof(b, monkeypatch), now=NOW)
    assert not result.get("last_error"), result
    doc = load(b)
    assert doc["title"] == "Remote title"
    # the peer's decision fields went through the receiving core's verifiers as the REMOTE side: none counts
    assert doc["status"] != "done" and not humanproof.verdict_ok(b, doc)
    assert all(
        v.get("mac") != forged_verdict["mac"] or humanproof.verdict_verifier(b)(v, doc) is None
        for v in doc.get("verdicts", [])
    )
    assert not doc["checklist"][0].get("wont_do") and "wont_mac" not in doc["checklist"][0]


def test_keep_theirs_keeps_a_remote_wont_do_this_core_verifies(machines, monkeypatch):
    # Fable B2: the chosen copy's decisions are judged by the receiving core's MAC, not dropped or trusted.
    import shutil

    from orch import tickets

    a, b, _ = both(machines)
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: root.parent / "proof-homes" / root.name)
    humanproof.human_key(b)
    # Fixture only: A signs with B's authority, so B's core can verify A's Won't do (real peers cannot).
    (a / ".orch/.local-id").write_bytes((b / ".orch/.local-id").read_bytes())
    humanproof.human_key(a)
    shutil.copy2(humanproof.key_dir(b) / "human.key", humanproof.key_dir(a) / "human.key")
    for root in (a, b):  # the fixture moved the authority: the person confirms the address again under it
        configure(root, machines[2])
    edit(b, checklist=[{"id": "c1", "text": "Pay the invoice", "done": False, "evidence": []}])
    success(b)
    success(a)
    tickets.check_wont_do(a, "t_abc123", "c1", "human:lindenmann")
    edit(a, title="Remote title")
    success(a)
    shutil.copy2(humanproof.key_dir(a) / humanproof.LEDGER, humanproof.key_dir(b) / humanproof.LEDGER)
    edit(b, title="Local title")
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        assert run(b)["paused"]["files"] == [TICKET]
    theirs = json.loads(repo.safe(b, "run/sync/theirs/" + TICKET).read_bytes())
    assert humanproof.wont_verifier(b)(theirs["checklist"][0], "t_abc123")
    import hashlib

    data = repo.safe(b, "run/sync/theirs/" + TICKET).read_bytes()
    target = "sync:keep-theirs:" + hashlib.sha256(TICKET.encode() + b"\0" + data).hexdigest()
    # (not `proof()`: that moves the guarded home, and B's core would no longer hold the ledger above)
    token = humanproof.mint(humanproof.human_key(b), humanproof.new_payload("addon.act", target, "human:Pat"))
    monkeypatch.setattr("sys.stdin", io.StringIO(token + "\n"))
    result = pause.resolve(b, TICKET, "theirs", SimpleNamespace(proof_stdin=True, by=None), now=NOW)
    assert not result.get("last_error"), result
    doc = load(b)
    assert doc["title"] == "Remote title"
    assert (
        doc["checklist"][0]["wont_do"] is True
        and doc["checklist"][0]["wont_mac"] == theirs["checklist"][0]["wont_mac"]
    )


def test_ext_name_count_is_capped(machines):
    a, b, bare = both(machines)
    edit(a, ext={f"addon-{i}": {} for i in range(65)})
    repo.git(a, "add", "--", TICKET)
    hostile(a, bare, ["commit", "-m", "many ext names"])
    assert run(b)["last_error"]
    assert not approval.held(b)


def test_needs_commands_cannot_be_injected(machines):
    # Fable B5: a peer-chosen ext name went unquoted into the suggested command.
    import shlex

    a, b, bare = both(machines)
    edit(a, ext={"x; touch PWNED #": {"run": True}})
    repo.git(a, "add", "--", TICKET)
    hostile(a, bare, ["commit", "-m", "evil ext name"])
    state = run(b)
    assert state["last_error"]
    assert "x; touch" not in json.dumps(load(b))
    assert not approval.held(b)
    for row in needs.rows(b):
        assert "touch" not in row["cli"] and "touch" not in row["text"]
    # A planted (unsigned) held file is no held change: no row at all.
    block = {"ticket": "t_abc123", "addon": "a b;c", "value": 1, "hash": "h", "since": NOW}
    step.write(b, "run/sync/held/t_abc123-x.json", step.encoded(block))
    assert not [r for r in needs.rows(b) if r["kind"] == "sync:held"]
    # A signed one whose name is no installed add-on's: the name never reaches the row (LOW-7); nothing to run.
    mac = humanproof.local_sign(b, approval.HELD_KIND, block)
    step.write(b, "run/sync/held/t_abc123-x.json", step.encoded({**block, "mac": mac}))
    held = [r for r in needs.rows(b) if r["kind"] == "sync:held"]
    assert "a b;c" not in held[0]["text"] and "an add-on not installed here" in held[0]["text"]
    assert shlex.split(held[0]["cli"]) == ["orch", "sync", "needs", "--json"] and "answer" not in held[0]


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


@pytest.mark.parametrize("incoming_at", ["2001-01-01T00:00:00Z", at(13)])
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

    # Exchange the offline heads in the opposite direction, before any resolution (through a clean bare
    # repository: sync only talks to an inspected bare local remote, never to another machine's .git).
    exchange = tmp_path / "exchange.git"
    subprocess.run(["git", "init", "--bare", str(exchange)], capture_output=True, check=True)
    repo.git(b, "push", str(exchange), "refs/heads/orch-state:refs/heads/orch-state")
    repo.git(a, "fetch", str(exchange), "refs/heads/orch-state")
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
    address = "https://github.com/owner/repository"
    args = ["--dir", str(root), "set", "--mode", "remote", "--remote", address, "--public", "--proof-stdin"]
    proof(
        root, cli.remote_target(address, public=True), monkeypatch
    )  # a public address: the person's own choice
    assert cli.main(args) == 0
    assert "Anyone can read" in capsys.readouterr().err
    proof(root, cli.remote_target(address, public=True), monkeypatch)
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

    from orch import history

    history.ensure_key(root)  # a pause is signed with the workspace key (sync on always makes it)
    candidates = [{"id": f"t_test{i:03}", "title": "Long title " * 20} for i in range(count)]
    state = {
        "paused": pause.sign(  # made as core makes it; step.write never signs a pause it is given
            root,
            {
                "files": [f"tickets/{t['id']}.json" for t in candidates],
                "key_clashes": {"DM1-13": candidates},
                "since": NOW,
                "reason": "Key clash",
            },
        )
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
    result = pause.keep_key(
        b, "DM1-13", winner, proof(b, f"sync:keep-key:DM1-13:{winner}:{remote}", monkeypatch), now=NOW
    )
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
        pause.keep_key(
            a, "DM1-13", winner, proof(a, f"sync:keep-key:DM1-13:{winner}:{remote}", monkeypatch), now=NOW
        )
    success(a)
    success(b)
    success(a)
    for tid in (winner, loser):
        docs = [json.loads(repo.safe(root, f"tickets/{tid}.json").read_bytes()) for root in (a, b)]
        # Keys and content converge; local human attribution and its remote demotion
        # intentionally differ, and that history difference can advance revisions.
        assert {k: v for k, v in docs[0].items() if k not in ("history", "revision")} == {
            k: v for k, v in docs[1].items() if k not in ("history", "revision")
        }
        histories = []
        for doc in docs:
            events = set()
            for line in doc["history"]:
                assert line["by"] in ("human:Pat", "agent:sync")
                text = line["text"].removeprefix("(synced, not verified here) ")
                assert "key changed" in text
                events.add((line["at"], text))
            histories.append(events)
        assert histories[0] == histories[1]


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
            b,
            "DM1-5",
            "t_later1",
            proof(b, f"sync:keep-key:DM1-5:t_later1:{remote}", m),
            now=NOW,
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
        approval.approve(
            b, "t_abc123", "automation", SimpleNamespace(ignore=True, proof_stdin=False, by="agent:test")
        )
    assert approval.held(b)
    assert not cli.read(b, "ignored")


@pytest.mark.parametrize(
    "value", [{"command": "run"}, {"old_keys": ["bad"]}, {"old_keys": [f"DM1-{i}" for i in range(1, 102)]}]
)
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
    proof(root, cli.remote_target(address), monkeypatch)
    assert cli.main([*args, "--proof-stdin"]) == 0
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
        "id": "c1",
        "text": "Email finance",
        "done": False,
        "evidence": [],
        "wont_do": True,
        "reason": "forged",
        "by": "human:Ann",
        "at": NOW,
        "wont_nonce": "n1",
        "wont_mac": "garbage",
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
    result = pause.keep_key(
        b, "DM1-5", winner, proof(b, f"sync:keep-key:DM1-5:{winner}:{remote}", monkeypatch), now=NOW
    )
    monkeypatch.setattr(step, "_run", original_run)
    assert not result.get("paused") and not result.get("last_error"), result
    success(b)
    for data in (repo.safe(b, evil).read_bytes(), repo.git(b, "show", "HEAD:" + evil).stdout):
        doc = json.loads(data)
        assert "wont_do" not in doc["checklist"][0]
        assert (doc["key"] == "DM1-5") == (winner == "t_evil01")
    # Convergence for two honest machines is covered by
    # test_person_keeps_key_without_live_duplicates; A here authored the forgery.


@pytest.mark.parametrize("current", [0, 140])
def test_keep_key_live_counter_only_reserves_selected_numbers(machines, monkeypatch, current):
    from test_step import ticket

    a, b, bare = both(machines)
    local, remote_only = "tickets/t_local1.json", "tickets/t_remote1.json"
    save(a, local, ticket() | {"id": "t_local1", "key": "DM1-5"})
    success(a)
    success(b)
    live_counter = {"last": current, "local_only": 7}  # Fable A9: counter fields are plain ints
    save(b, "ticket-counter.json", live_counter)
    save(
        a,
        local,
        ticket()
        | {
            "id": "t_local1",
            "key": "DM1-99",
            "ext": {"sync": {"old_keys": ["DM1-5"]}},
        },
    )
    save(a, remote_only, ticket() | {"id": "t_remote1", "key": "DM1-5"})
    save(
        a, "ticket-counter.json", {"last": 99_999, "remote_only": 1, "local_only": 999}
    )  # inside the jump cap
    repo.git(a, "add", "--", local, remote_only, "ticket-counter.json")
    hostile(a, bare, ["commit", "-m", "remote counter inflation"])
    remote = run(b)["paused"]["remote_sha"]
    # Inspect the reservation before the normal verified merge resumes.
    monkeypatch.setattr(step, "_run", lambda *args: cli.read(b, "state"))
    pause.keep_key(
        b,
        "DM1-5",
        "t_remote1",
        proof(b, f"sync:keep-key:DM1-5:t_remote1:{remote}", monkeypatch),
        now=NOW,
    )
    assert json.loads(repo.safe(b, local).read_bytes())["key"] == "DM1-99"
    assert json.loads(repo.safe(b, "ticket-counter.json").read_bytes()) == {
        **live_counter,
        "last": max(current, 99),
    }


@pytest.mark.parametrize("problem", ["invalid", "private", "secret", "ticket-deletion"])
@pytest.mark.parametrize("command", ["resolve", "keep-key"])
def test_any_unlisted_incoming_problem_blocks_choices(machines, monkeypatch, problem, command):
    # Fable B6: resolve only blocked "path"/"size", so an aborted check ("invalid") failed open.
    from test_step import ticket

    from orch_sync import incoming

    a, b, _ = both(machines)
    if command == "resolve":
        save(a, ART, b"base")
        success(a)
        success(b)
        save(a, ART, b"remote")
        save(b, ART, b"local")
    else:
        for root, tid in [(a, "t_first1"), (b, "t_later1")]:
            save(root, f"tickets/{tid}.json", ticket() | {"id": tid, "key": "DM1-13"})
    success(a)
    remote = run(b)["paused"]["remote_sha"]
    checked = incoming.Result(remote, [incoming.Problem("", problem, "refused")])
    monkeypatch.setattr(incoming, "check", lambda *a, **kw: checked)
    with pytest.raises(repo.Refused):
        if command == "resolve":
            pause.resolve(b, ART, "theirs", now=NOW)
        else:
            args = proof(b, f"sync:keep-key:DM1-13:t_first1:{remote}", monkeypatch)
            pause.keep_key(b, "DM1-13", "t_first1", args, now=NOW)
    assert not cli.read(b, "choices")
    if command == "resolve":
        assert repo.safe(b, ART).read_bytes() == b"local"


@pytest.mark.parametrize(
    "problem",
    ["manifest", "commit", "path", "size", "private", "local-general", "counter-schema", "counter-deletion"],
)
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
        checked = incoming.Result(
            "wrong" if problem == "commit" else remote,
            [
                incoming.Problem(
                    "ticket-counter.json" if problem.startswith("counter-") else "", problem, "refused"
                )
            ],
        )
        monkeypatch.setattr(incoming, "check", lambda *a, **kw: checked)
    before = repo.safe(b, "tickets/t_later1.json").read_bytes()
    args = proof(b, f"sync:keep-key:DM1-13:t_first1:{remote}", monkeypatch)
    with pytest.raises(repo.Refused):
        pause.keep_key(b, "DM1-13", "t_first1", args, now=NOW)
    assert repo.safe(b, "tickets/t_later1.json").read_bytes() == before
    assert not repo.safe(b, "tickets/t_first1.json").exists()
    assert not cli.read(b, "choices")


@pytest.mark.parametrize(
    "files",
    [
        [],
        {"x": 1},
        {"tickets/t_abc123/artifacts/a.txt": "mine"},
        {"../x": {"keep": "mine"}},
        {"tickets/t_abc123/artifacts/a.txt": {"keep": 5}},
    ],
)
def test_a_malformed_choice_store_counts_for_nothing(machines, files):
    # A hand-written choices.json of any other shape is no choice: the step goes on as usual.
    a, b, _ = both(machines)
    remote = step.oid(b, "refs/remotes/origin/orch-state")
    step.write(b, "run/sync/choices.json", step.encoded({"remote_sha": remote, "files": files}))
    assert pause.choices(b, remote) == {}
    edit(a, title="Still merges")
    success(a)
    state = success(b)
    assert not state.get("last_error") and load(b)["title"] == "Still merges"


def _history_pause(root, remote):
    state = cli.read(root, "state")
    # made as core makes it (pause.sign); step.write never signs a pause it is given
    state["paused"] = pause.sign(
        root,
        {
            "files": [],
            "since": NOW,
            "remote_sha": remote,
            "kind": pause.HISTORY,
            "reason": "The two histories cannot be combined automatically",
        },
    )
    step.write(root, "run/sync/state.json", step.encoded(state))


def test_a_history_pause_has_a_row_and_clears_when_the_remote_changes(machines):
    # No file to choose: a Needs row whose way out is take-remote (a person's proof, PR B), and the pause stays
    # only while the remote is the commit it was about.
    from pathlib import Path

    a, b, bare = both(machines)
    edit(a, title="Remote title")
    success(a)
    tip = remote_sha(bare).decode()
    _history_pause(b, tip)
    rows = needs.rows(b)
    (row,) = [r for r in rows if r["kind"] == "sync:history"]
    assert row["cli"] == "orch sync take-remote --proof-stdin" and row["tone"] == "warn"
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts/needs.schema.json").read_text())
    Draft202012Validator(schema).validate(rows)
    with pytest.raises(repo.Refused, match="not waiting"):
        pause.resolve(b, TICKET, "mine", now=NOW)
    assert run(b)["paused"]  # the same remote: it stays
    assert load(b)["title"] != "Remote title"
    edit(a, title="Later")
    success(a)
    state = run(b)  # the remote moved: look again
    assert not state.get("paused") and not state.get("last_error"), state
    assert load(b)["title"] == "Later"
    assert not [r for r in needs.rows(b) if r["kind"] == "sync:history"]


OLD_NAME = "tickets/t_abc123/artifacts/report.txt"
NEW_NAME = "tickets/t_abc123/artifacts/Report.txt"


def case_clash(machines):
    """The peer renamed report.txt to Report.txt (case only): B pauses, its file untouched (Fable A6/B13)."""
    a, b, bare = both(machines)
    save(a, OLD_NAME, b"the report")
    for i in range(9):  # so the deletion threshold does not hide the rename
        save(a, f"tickets/t_abc123/artifacts/other{i}.txt", b"other")
    success(a)
    success(b)
    repo.git(a, "mv", "-f", "--", OLD_NAME, NEW_NAME)
    tip = hostile(a, bare, ["commit", "-m", "case-only rename"])
    state = run(b)
    assert state["paused"]["files"] == [NEW_NAME]
    assert state["paused"]["case_names"] == {NEW_NAME: OLD_NAME}
    return a, b, bare, tip


def names(root):
    return sorted(
        p.name for p in (root / ".orch/tickets/t_abc123/artifacts").iterdir() if not p.name.startswith("o")
    )


def test_case_clash_needs_row_and_keep_is_refused(machines):
    _, b, _, _ = case_clash(machines)
    (row,) = [r for r in needs.rows(b) if r["kind"] == "sync:case"]
    assert row["answer"]["options"] == ["Keep my name", "Rename my file"]
    assert "--keep-local-name" in row["cli"] and "--rename-local" in row["cli"] and "git" not in row["text"]
    # keep mine/theirs would overwrite the other file on a disk that ignores case
    for keep in ("mine", "theirs"):
        with pytest.raises(repo.Refused, match="differ only in case"):
            pause.resolve(b, NEW_NAME, keep, now=NOW)
    assert names(b) in (["report.txt"], ["Report.txt"]) and b"the report" in [
        p.read_bytes() for p in (b / ".orch/tickets/t_abc123/artifacts").iterdir()
    ]


@pytest.mark.parametrize("action", ["keep", "rename"])
def test_case_clash_choice_needs_a_person(machines, action):
    _, b, bare, tip = case_clash(machines)
    rename = "report (B).txt" if action == "rename" else None
    with pytest.raises(Refused):
        pause.resolve_case(
            b, NEW_NAME, SimpleNamespace(proof_stdin=False, by="agent:test"), rename=rename, now=NOW
        )
    assert run(b)["paused"]["files"] == [NEW_NAME] and remote_sha(bare) == tip
    assert not cli.read(b, "choices") and not cli.read(b, "renamed")
    assert repo.safe(b, OLD_NAME).read_bytes() == b"the report"
    # the CLI refuses an agent the same way (no proof), and needs exactly one way out
    assert (
        cli.main(["--dir", str(b), "resolve", NEW_NAME, "--keep-local-name", "--by", "agent:x", "--json"])
        == 2
    )
    with pytest.raises(SystemExit):
        cli.main(["--dir", str(b), "resolve", NEW_NAME, "--keep-local-name", "--rename-local", "x.txt"])


def test_case_clash_keep_local_name(machines, monkeypatch):
    a, b, bare, tip = case_clash(machines)
    remote = run(b)["paused"]["remote_sha"]
    with pytest.raises(Refused):  # a proof for renaming is not a proof for keeping
        pause.resolve_case(
            b, NEW_NAME, proof(b, pause.case_target(NEW_NAME, remote, "x"), monkeypatch), now=NOW
        )
    args = proof(b, pause.case_target(NEW_NAME, remote), monkeypatch)
    result = pause.resolve_case(b, NEW_NAME, args, now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    # the other computer's variant is not applied, and it is reported
    assert repo.safe(b, OLD_NAME).read_bytes() == b"the report" and names(b) == ["report.txt"]
    assert any(
        "Kept your file name report.txt" in n and "Report.txt is not applied" in n for n in result["notices"]
    )
    assert OLD_NAME in tracked(b) and NEW_NAME not in tracked(b)
    # this machine's name is what it shares; the remote moved, so the choice is spent and asks again if needed
    assert remote_sha(bare) != tip
    shared = repo.git(b, "ls-tree", "-r", "--name-only", "origin/orch-state").stdout.decode().split()
    assert OLD_NAME in shared and NEW_NAME not in shared
    state = success(b)
    assert not state.get("paused") and not any("Kept your file name" in n for n in state["notices"])
    # the other computer now has to choose too (its file differs only in case): nothing is lost there
    state = run(a)
    assert state["paused"]["case_names"] == {OLD_NAME: NEW_NAME}
    assert b"the report" in [p.read_bytes() for p in (a / ".orch/tickets/t_abc123/artifacts").iterdir()]


def test_case_clash_keep_local_name_asks_again_when_the_remote_changes(machines, monkeypatch):
    a, b, bare, _ = case_clash(machines)
    remote = run(b)["paused"]["remote_sha"]
    args = proof(b, pause.case_target(NEW_NAME, remote), monkeypatch)
    save(a, NEW_NAME, b"the report, edited")
    repo.git(a, "add", "--", NEW_NAME)
    hostile(a, bare, ["commit", "-m", "edit"])
    result = pause.resolve_case(b, NEW_NAME, args, now=NOW)
    assert result["review_again"] and result["paused"]["case_names"] == {NEW_NAME: OLD_NAME}
    assert repo.safe(b, OLD_NAME).read_bytes() == b"the report"


def test_case_clash_rename_local(machines, monkeypatch):
    a, b, bare, _ = case_clash(machines)
    remote = run(b)["paused"]["remote_sha"]
    target = "tickets/t_abc123/artifacts/report (B).txt"
    for bad in ("../x.txt", "sub/x.txt", "REPORT.TXT", "other1.txt", ".env"):
        with pytest.raises(repo.Refused):
            pause.resolve_case(b, NEW_NAME, proof(b, "unused", monkeypatch), rename=bad, now=NOW)
    with pytest.raises(Refused):  # bound to the new name
        pause.resolve_case(
            b,
            NEW_NAME,
            proof(b, pause.case_target(NEW_NAME, remote, target + "x"), monkeypatch),
            rename="report (B).txt",
            now=NOW,
        )
    args = proof(b, pause.case_target(NEW_NAME, remote, target), monkeypatch)
    result = pause.resolve_case(b, NEW_NAME, args, rename="report (B).txt", now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    # both arrive: B's file under its new name, the other computer's under its own
    assert names(b) == ["Report.txt", "report (B).txt"]
    assert repo.safe(b, target).read_bytes() == b"the report"
    assert repo.safe(b, NEW_NAME).read_bytes() == b"the report"
    assert {target, NEW_NAME} <= tracked(b) and OLD_NAME not in tracked(b)
    success(a)
    assert repo.safe(a, target).read_bytes() == b"the report" and repo.safe(a, NEW_NAME).exists()
    tip = remote_sha(bare)
    for root in (b, a, b):
        assert not success(root).get("paused")
    assert remote_sha(bare) == tip
    assert cli.read(b, "renamed") == {}  # the person's rename is committed: the record is gone


def test_a_rename_record_whose_new_file_differs_counts_as_removal(machines):
    # A rename counts as a move only while the new file holds exactly the old bytes; otherwise the old file
    # is a removal and the deletion gate sees it (a record in .orch/run never hides a loss).
    _, b, bare = both(machines)
    folder = "tickets/t_abc123/artifacts"
    for i in range(9):
        save(b, f"{folder}/f{i}.txt", f"file {i}".encode())
    success(b)
    tip = remote_sha(bare)
    renamed = {}
    for i in range(9):
        old, new = f"{folder}/f{i}.txt", f"{folder}/g{i}.txt"
        (b / ".orch" / old).unlink()
        save(b, new, b"other bytes")
        renamed[old] = new
    step.write(b, "run/sync/renamed.json", step.encoded(renamed))
    state = run(b)
    assert state["paused"] and "Many files were removed (9)" in state["paused"]["reason"], state
    assert remote_sha(bare) == tip
    assert {f"{folder}/f{i}.txt" for i in range(9)} <= tracked(b)


def counter_jump(machines, hostile_value):
    a, b, bare = both(machines)
    save(b, "ticket-counter.json", {"last": 3})
    success(b)
    success(a)
    if hostile_value == "counter":
        save(a, "ticket-counter.json", {"last": 900_000_000})
    else:
        save(a, "tickets/t_far001.json", ticket() | {"id": "t_far001", "key": "AB-900000000"})
    repo.git(a, "add", "--", "ticket-counter.json", "tickets")
    tip = hostile(a, bare, ["commit", "-m", "jump"]).decode()
    state = run(b)
    assert state["paused"]["reason"] == pause.JUMP and state["paused"]["files"] == ["ticket-counter.json"]
    return a, b, tip


@pytest.mark.parametrize("hostile_value", ["counter", "key"])
@pytest.mark.parametrize("keep", ["mine", "theirs"])
def test_counter_jump_needs_a_person(machines, hostile_value, keep, monkeypatch):
    # M3: an agent cleared the jump gate with `resolve ticket-counter.json --keep theirs`; and with only a far
    # key (small counter) neither choice ever cleared the pause.
    _, b, tip = counter_jump(machines, hostile_value)
    counter = repo.safe(b, "ticket-counter.json")
    row = next(r for r in needs.rows(b) if r.get("title") == "ticket-counter.json")
    assert row["cli"].endswith("--proof-stdin")
    for by in ("agent:test", None):
        with pytest.raises(Refused):
            pause.resolve(b, "ticket-counter.json", keep, SimpleNamespace(proof_stdin=False, by=by), now=NOW)
    other = "mine" if keep == "theirs" else "theirs"
    with pytest.raises(Refused):  # a proof for the other choice is no proof for this one
        args = proof(b, f"sync:keep-{other}-counter:{tip}", monkeypatch)
        pause.resolve(b, "ticket-counter.json", keep, args, now=NOW)
    assert json.loads(counter.read_text())["last"] == 3
    assert cli.read(b, "state")["paused"]["reason"] == pause.JUMP
    args = proof(b, f"sync:keep-{keep}-counter:{tip}", monkeypatch)
    result = pause.resolve(b, "ticket-counter.json", keep, args, now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    last = json.loads(counter.read_text())["last"]
    assert last == (3 if (keep, hostile_value) == ("mine", "counter") else 900_000_000)
    if hostile_value == "key":
        assert json.loads(repo.safe(b, "tickets/t_far001.json").read_text())["key"] == "AB-900000000"
    assert not success(b).get("paused")


def test_a_refused_counter_choice_never_uses_up_the_proof(machines, monkeypatch):
    # LOW-4: reading the reviewed numbers ran after the proof was consumed; a refusal there burned the proof.
    import sys

    _, b, tip = counter_jump(machines, "key")
    args = proof(b, f"sync:keep-mine-counter:{tip}", monkeypatch)
    token = sys.stdin.getvalue()

    def refused(*_):
        raise pause.Pause("Document has a problem: tickets/t_far001.json", [])

    with monkeypatch.context() as m:
        m.setattr(step, "top_number", refused)
        with pytest.raises(pause.Pause):
            pause.resolve(b, "ticket-counter.json", "mine", args, now=NOW)
    monkeypatch.setattr("sys.stdin", io.StringIO(token))
    result = pause.resolve(b, "ticket-counter.json", "mine", args, now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result


def test_the_jump_row_says_the_far_tickets_arrive(machines):
    # LOW-5: "Keep mine" on a jump still lets the far-numbered tickets the person reviewed arrive.
    _, b, _ = counter_jump(machines, "key")
    row = next(r for r in needs.rows(b) if r.get("title") == "ticket-counter.json")
    assert "far numbers arrive" in row["text"] and len(row["text"]) <= 500
