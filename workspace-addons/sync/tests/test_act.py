"""`orch sync act <verb> -- <target>`: what the dashboard's Sync card and Needs rows run (one generic add-on op)."""

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from orch import humanproof
from test_step import ART, TICKET, configure, proof, run, save, success
from test_two_machines import both, edit, machines

from orch_sync import act, cli, needs, pause, repo, step

__all__ = ["machines"]
SECRET = b"orp_" + b"a" * 30


def sync(root, *args):
    return cli.main(["--dir", str(root), "act", *args, "--json"])


def answer(capsys):
    return json.loads(capsys.readouterr().out)


def choose(root, remote, monkeypatch, value="15"):
    """The person's signed choice of a sync address in the dashboard (act set with the set-remote proof)."""
    proof(root, cli.remote_target(remote), monkeypatch)
    return sync(root, "set", remote, "--value", value, "--proof-stdin")


def public_waits(root, tmp_path, monkeypatch, capsys):
    """A public address the person chose, waiting (signed by core) for their use-public choice."""
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", "local") == 0
    assert choose(root, remote, monkeypatch) == 0
    capsys.readouterr()
    return remote


def bare(tmp_path):
    path = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return path


def test_status_off_then_local(root, capsys):
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["mode"] == "off" and card["shown"] == "off" and card["not_synced"] == [] and card["public"] is None
    assert sync(root, "set", "local") == 0
    assert answer(capsys)["mode"] == "local"
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["mode"] == "local"
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "never"
    (root / ".orch/run/sync/state.json").write_text('{"last_error":"offline","last_ok":"2026-11-11T10:15:00Z"}')
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "offline"
    (root / ".orch/run/sync/state.json").write_text('{"last_ok":"2026-11-11T10:15:00Z"}')
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["shown"] == "synced"
    assert sync(root, "set", "off") == 0
    assert answer(capsys)["mode"] == "off"
    # the argv the dashboard's generic op builds: flags, then the target after `--`
    assert cli.main(["--dir", str(root), "act", "status", "--by", "human:pat", "--json", "--", "sync"]) == 0
    assert answer(capsys)["shown"] == "off"
    assert cli.main(["--dir", str(root), "act", "set", "--value=15", "--by", "human:pat", "--json", "--", "-x"]) == 2


def test_set_is_a_persons_click(root, monkeypatch, capsys):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    assert sync(root, "set", "local") == 2
    assert "A person chooses where sync keeps a copy" in answer(capsys)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()


def test_check_uses_syncs_own_transport_rules(root, tmp_path, capsys, normal_install):
    for bad in ("file:///tmp/x", "/tmp/x", "http://example.org/x", "ext::sh -c x", "https://me:pw@example.org/x"):
        assert sync(root, "check", bad) == 0
        got = answer(capsys)
        assert got["ok"] is False and got["reason"], bad
    assert not (root / ".orch/.git").exists()  # a check never sets anything up


def test_check_reaches_a_test_remote_and_reports_a_missing_one(root, tmp_path, capsys):
    assert sync(root, "check", f"file://{bare(tmp_path)}") == 0
    assert answer(capsys) == {"ok": True}
    assert sync(root, "check", f"file://{tmp_path / 'nothing-here.git'}") == 0
    assert answer(capsys)["ok"] is False
    assert not (root / ".orch/.git").exists()


def test_interval_and_remote_need_the_preview(root, tmp_path, monkeypatch, capsys):
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", remote, "--value", "15") == 2
    assert "preview-only" in answer(capsys)["error"]
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    assert sync(root, "set", remote, "--value", "7") == 2
    assert answer(capsys)["error"] == "Sync can run every 5, 15 or 60 minutes"
    assert choose(root, remote, monkeypatch, "60") == 0
    got = answer(capsys)
    assert got["mode"] == "remote" and got["interval"] == 60
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["remote"] == remote
    assert sync(root, "set", remote, "--value", "5") == 0  # the same address, only how often: unsigned
    assert answer(capsys)["interval"] == 5
    assert sync(root, "set", remote, "--value", "5", "--proof-target") == 0
    assert answer(capsys) == {"target": None}


def test_set_remote_without_a_proof_is_refused(root, tmp_path, monkeypatch, capsys):
    """M4: choosing the address is a signed choice (sync:set-remote:<sha256(address)>), whatever the environment
    says; the review shows that exact address (without a login), from the same value the target hashes."""
    from orch import tickets

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", remote, "--value", "15") == 2
    assert "proof" in answer(capsys)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()
    proof(root, cli.remote_target(f"file://{bare(tmp_path / 'other')}"), monkeypatch)
    assert sync(root, "set", remote, "--value", "15", "--proof-stdin") == 2  # a proof of another address
    assert "error" in answer(capsys)
    assert not (root / ".orch/run/sync/settings.json").exists()
    assert sync(root, "set", remote, "--value", "15", "--proof-target") == 0
    got = answer(capsys)
    assert got["target"] == "sync:set-remote:" + hashlib.sha256(remote.encode()).hexdigest()
    assert got["review"] == {"title": "Sync to this address?", "value": remote,
                             "body": "Your tickets and their files are copied there every 15 minutes."}
    assert sync(root, "set", "local", "--proof-target") == 0 and answer(capsys) == {"target": None}
    assert sync(root, "set", "local") == 0  # mode local and off stay unsigned
    assert sync(root, "set", "off") == 0


def test_set_review_shows_the_address_without_its_login(root, monkeypatch):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    target, review = act.proof_target(root, "set", "ssh://git@host.example/me/orch", "60")
    assert target == cli.remote_target("ssh://git@host.example/me/orch")
    assert review["value"] == "ssh://host.example/me/orch" and "every 60 minutes" in review["body"]


def test_public_address_waits_for_the_signed_choice(root, tmp_path, monkeypatch, capsys):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", "local") == 0
    capsys.readouterr()
    assert choose(root, remote, monkeypatch) == 0  # the person chose this address (set-remote proof) ...
    got = answer(capsys)
    assert got["public"] == remote and got["mode"] == "local"  # ... and that it is public waits for them
    assert got["text"] == "This sync address is public. Anyone can read your tickets."
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["public"] == remote
    assert sync(root, "now", "sync") == 0  # never syncs to it while the choice waits
    assert answer(capsys)["text"] == "Not synced: choose a location above first"
    target = "sync:use-public:" + hashlib.sha256(remote.encode()).hexdigest()
    assert sync(root, "use-public", "pending", "--proof-target") == 0
    assert answer(capsys) == {"target": target, "review": {
        "title": "Use a public location?", "body": "Anyone who knows the address can read your tickets.", "value": remote}}
    assert sync(root, "use-public", "pending") == 2  # no proof: refused
    capsys.readouterr()
    proof(root, target, monkeypatch)
    assert sync(root, "use-public", "pending", "--proof-stdin") == 0
    assert answer(capsys)["mode"] == "remote"
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["public"] is None and card["mode"] == "remote"


def test_keep_on_this_computer_drops_the_public_address(root, tmp_path, monkeypatch, capsys):
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    assert choose(root, f"file://{bare(tmp_path)}", monkeypatch, "5") == 0
    assert sync(root, "set", "local") == 0
    capsys.readouterr()
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["public"] is None and card["mode"] == "local"


def test_sync_now_never_clears_a_pause(root, monkeypatch, capsys):
    configure(root)
    save(root)
    save(root, ART, SECRET)
    assert "secret" in run(root)["last_error"]
    monkeypatch.setattr(step, "run_once", lambda *a, **k: pytest.fail("Sync now ran while paused"))
    capsys.readouterr()
    assert sync(root, "now", "sync") == 0
    got = answer(capsys)
    assert got == {"still_paused": 1, "text": "Still paused: 1 thing needs you"}
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["shown"] == "paused" and card["paused_needs"] == 1


def test_leave_it_out_is_signed_bound_to_the_bytes_and_ends_the_pause(root, monkeypatch, capsys):
    configure(root)
    save(root)
    save(root, ART, SECRET)
    run(root)
    rows = needs.rows(root)
    assert [r["text"] for r in rows] == ["Not synced: a.txt may contain a password or access key."]
    labels = [(a["label"], a.get("verb"), a.get("sign", False)) for a in rows[0]["actions"]]
    assert labels == [("Leave it out", "leave-out", True), ("View file", None, False)]
    assert rows[0]["actions"][1]["view"] == {"ticket": "t_abc123", "name": "a.txt"}
    capsys.readouterr()
    assert sync(root, "leave-out", ART, "--proof-target") == 0
    got = answer(capsys)
    target = got["target"]
    assert target == "sync:leave-out:" + hashlib.sha256(ART.encode() + b"\0" + SECRET).hexdigest()
    assert got["review"] == {"title": "Leave a.txt out of sync?", "body": "It stays on this computer only.",
                             "value": f"a.txt, {len(SECRET)} bytes"}
    with pytest.raises(Exception, match="proof|person"):
        pause.leave_out(root, ART, SimpleNamespace(proof_stdin=False, by="agent:test"))
    proof(root, target, monkeypatch)
    assert sync(root, "leave-out", ART, "--proof-stdin") == 0
    assert answer(capsys)["paused"] is False
    state = run(root)
    assert state["last_error"] is None and not state.get("paused"), state
    assert ART not in repo.git(root, "ls-files").stdout.decode()
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["not_synced"] == [{"name": "a.txt", "why": "may contain a password or access key"}]
    # changed content asks again
    save(root, ART, SECRET + b" changed")
    assert "secret" in run(root)["last_error"]


def test_proof_target_of_keep_theirs_is_what_resolve_checks(machines, monkeypatch, capsys):
    a, b, _ = both(machines)
    edit(a, title="Theirs")
    edit(b, title="Mine")
    success(a)
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)  # the two copies can't be combined
        assert run(b)["paused"]["files"] == [TICKET]
    rows = needs.rows(b)
    row = rows[0]
    assert row["text"] == "Sync paused: “Mine” changed here and on another computer."
    keep = {x["verb"]: x for x in row["actions"]}
    assert keep["keep-mine"]["review"]["here"] == "Title: Mine" and keep["keep-mine"]["review"]["there"] == "Title: Theirs"
    assert all(x["sign"] for x in row["actions"])
    assert act.proof_target(b, "keep-mine", TICKET)[0] is None
    target, review = act.proof_target(b, "keep-theirs", TICKET)
    assert target.startswith("sync:keep-theirs:")
    # the review comes from the same bytes the target hashes: the saved copy that IS the remote blob
    theirs = repo.safe(b, "run/sync/theirs/" + TICKET).read_bytes()
    assert target == "sync:keep-theirs:" + hashlib.sha256(TICKET.encode() + b"\0" + theirs).hexdigest()
    assert review["title"] == "Keep the other computer’s version of “Mine”?"
    assert "title: Mine" in review["here"] and "title: Theirs" in review["there"]
    proof(b, target, monkeypatch)
    assert cli.main(["--dir", str(b), "act", "keep-theirs", TICKET, "--proof-stdin", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "Kept the other version."
    assert json.loads(repo.safe(b, TICKET).read_text())["title"] == "Theirs"


@pytest.mark.parametrize("how", ["unsigned", "forged", "edited"])
def test_a_planted_pending_public_counts_as_absent(root, tmp_path, monkeypatch, capsys, how):
    """H1: an agent-written pending-public.json (no local1 MAC, a made-up one, or a signed record with another
    address put in) is no waiting address: not on the card, no proof target, use-public refuses even with a
    person's proof of exactly that address, and Sync now does not wait for it."""
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    assert sync(root, "set", "local") == 0
    attacker = f"file://{bare(tmp_path)}"
    record = {"remote": attacker, "interval": 5}
    if how == "forged":
        record["mac"] = "A" * 43
    if how == "edited":
        humanproof.human_key(root)
        signed = {"remote": "https://files.example.org/mine", "interval": 5}
        record["mac"] = humanproof.local_sign(root, act.PUBLIC_KIND, signed)
        assert record["mac"] and humanproof.local_ok(root, act.PUBLIC_KIND, signed, record["mac"])
    (root / ".orch/run/sync/pending-public.json").write_text(json.dumps(record))
    capsys.readouterr()
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["public"] is None
    assert sync(root, "use-public", "pending", "--proof-target") == 2
    assert answer(capsys)["error"] == "No public address waits for a choice"
    proof(root, cli.remote_target(attacker, public=True), monkeypatch)
    assert sync(root, "use-public", "pending", "--proof-stdin") == 2
    assert answer(capsys)["error"] == "No public address waits for a choice"
    settings = json.loads((root / ".orch/run/sync/settings.json").read_text())
    assert settings["mode"] == "local" and "remote" not in settings
    assert act.pending_public(root) is None
    monkeypatch.setattr(step, "run_once", lambda *a, **k: {"last_error": None, "last_ok": "now"})
    assert sync(root, "now", "sync") == 0
    assert answer(capsys)["text"] == "Synced."


def test_the_waiting_public_address_is_signed_by_core(root, tmp_path, monkeypatch, capsys):
    remote = public_waits(root, tmp_path, monkeypatch, capsys)
    data = json.loads((root / ".orch/run/sync/pending-public.json").read_text())
    assert set(data) == {"remote", "interval", "mac"} and data["remote"] == remote
    assert act.pending_public(root) == {"remote": remote, "interval": 15}


def test_a_planted_visibility_cache_cannot_skip_the_public_warning(root, tmp_path, monkeypatch, capsys):
    """M1: visibility.json says the address is private (planted); the probe runs every time, so the public
    address still waits for the person's own choice, on the dashboard path and on the plain set path."""
    from test_step import set_remote

    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    probed = []
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: probed.append(url) or "public")
    remote = f"file://{bare(tmp_path)}"
    assert sync(root, "set", "local") == 0
    (root / ".orch/run/sync/visibility.json").write_text(json.dumps({remote: "private", cli.safe_address(remote): "private"}))
    capsys.readouterr()
    assert choose(root, remote, monkeypatch) == 0
    got = answer(capsys)
    assert got["public"] == remote and got["mode"] == "local" and probed == [remote]
    assert "remote" not in json.loads((root / ".orch/run/sync/settings.json").read_text())
    assert set_remote(root, remote) == 2
    assert "remote" not in json.loads((root / ".orch/run/sync/settings.json").read_text())


def test_use_public_reads_the_waiting_address_once(root, tmp_path, monkeypatch, capsys):
    """H1 race: right after use-public reads the waiting address, a valid record of another address lands. The
    proof's target and the address applied both come from that one read: the other address is never used."""
    remote = public_waits(root, tmp_path, monkeypatch, capsys)
    other = f"file://{bare(tmp_path / 'other')}"
    real, reads = cli.read, []

    def read(where, name):
        data = real(where, name)
        if name == act.PUBLIC:
            reads.append(data.get("remote"))
            if len(reads) == 1:
                act._write_public(root, other, 5)  # swapped in between (a signed record: the worst case)
        return data

    monkeypatch.setattr(cli, "read", read)
    proof(root, cli.remote_target(remote, public=True), monkeypatch)
    assert sync(root, "use-public", "pending", "--proof-stdin") == 0
    assert answer(capsys)["remote"] == remote
    assert reads == [remote]
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["remote"] == remote
    # and a proof of the swapped-in address never applies the first one
    monkeypatch.setattr(cli, "read", real)
    act._write_public(root, remote, 15)
    proof(root, cli.remote_target(other, public=True), monkeypatch)
    assert sync(root, "use-public", "pending", "--proof-stdin") == 2


def test_allow_review_shows_the_held_value_the_target_hashes(machines):
    """M2 + M-C: the sign step of allow / ignore shows the peer's value IN FULL with its byte count, computed from
    the same bytes the target hashes; a value too large to show is refused (nothing to sign in the dashboard)."""
    from orch_sync import approval

    a, b, _ = both(machines)
    value = {"enabled": True, "note": "x" * 400}
    edit(a, ext={"automation": value})
    success(a)
    success(b)
    raw = approval.canonical(value)
    for kind in ("allow", "ignore"):
        target, review = act.proof_target(b, kind, "t_abc123:automation")
        assert target == f"sync:{kind}:t_abc123:automation:{hashlib.sha256(raw).hexdigest()}"
        assert review["value"] == f"{raw.decode()} ({len(raw)} bytes)"  # whole: the payload after a long prefix shows
        assert "automation" in review["title"] and "t_abc123" in review["title"]
    with pytest.raises(repo.Refused):
        act.proof_target(b, "allow", "t_abc123:other")
    big = {"aaa": "x" * 4000, "zrun": "payload"}  # a harmless prefix past what a sign step shows
    edit(a, ext={"automation": big})
    success(a)
    success(b)
    for kind in ("allow", "ignore"):
        with pytest.raises(repo.Refused, match="too large to review here"):
            act.proof_target(b, kind, "t_abc123:automation")


def test_review_text_never_hides_a_character():
    assert act.plain("a\u202eb\u2066c\u200bd\x9be\x07f\ufeffg") == "a\ufffdb\ufffdc\ufffdd\ufffde\ufffdf\ufffdg"
    assert act.plain("one\ntwo   three\x85four") == "one two three four"  # line breaks (also NEL): one space
    assert act.plain("x" * 10, 5) == "xxxx…"


def test_a_planted_saved_copy_is_never_offered_for_signing(machines, monkeypatch):
    """L3: run/sync/theirs/<path> is agent-writable. Its bytes count only when they are the blob of the signed
    pause's remote commit: neither the proof target nor resolve take a planted copy."""
    a, b, _ = both(machines)
    edit(a, title="Theirs")
    edit(b, title="Mine")
    success(a)
    with monkeypatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        assert run(b)["paused"]["files"] == [TICKET]
    saved = repo.safe(b, "run/sync/theirs/" + TICKET)
    planted = saved.read_bytes().replace(b"Theirs", b"Planted")
    saved.write_bytes(planted)
    with pytest.raises(repo.Refused, match="Saved copy does not match the checked version"):
        act.proof_target(b, "keep-theirs", TICKET)
    with pytest.raises(repo.Refused, match="Saved copy does not match the checked version"):
        act.proof_target(b, "keep-mine", TICKET)
    proof(b, "sync:keep-theirs:" + hashlib.sha256(TICKET.encode() + b"\0" + planted).hexdigest(), monkeypatch)
    with pytest.raises(repo.Refused, match="Saved copy does not match the checked version"):
        pause.resolve(b, TICKET, "theirs", SimpleNamespace(proof_stdin=True, by=None))
    assert json.loads(repo.safe(b, TICKET).read_text())["title"] == "Mine"


def test_leave_deleted_review_names_the_ticket(machines):
    """L4: the sign step says which ticket: its title (of the synced copy left deleted) and its id."""
    a, _, _ = both(machines)
    repo.safe(a, TICKET).unlink()
    success(a)
    target, review = act.proof_target(a, "leave-deleted", "t_abc123")
    assert target == "sync:deleted:t_abc123"
    assert review == {"title": "Leave this ticket deleted?", "body": "It is removed on every computer that syncs.",
                      "value": "“A task” (t_abc123)"}
    for bad in ("t_zzzzzz", "../x", "t_abc123\u202e"):
        with pytest.raises(repo.Refused):
            act.proof_target(a, "leave-deleted", bad)


def test_check_sends_no_login_and_never_echoes_the_address(root, tmp_path, monkeypatch, capsys):
    """L2: a typed address is reached with no prompt, no credential helper and ssh in batch mode (not the
    person's own ssh command); a refused address gets a fixed reason, never the address or its login."""
    for bad in ("https://me:pw@example.org/x", "ext::sh -c x", "http://example.org/x"):
        assert sync(root, "check", bad) == 0
        assert answer(capsys) == {"ok": False, "reason": act.NO_ADDRESS}
    remote = f"file://{bare(tmp_path)}"
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /home/person/.ssh/id")
    monkeypatch.setenv("GIT_SSH", "/usr/local/bin/person-ssh")
    calls, real = [], subprocess.run
    monkeypatch.setattr(repo.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or real(cmd, **kw))
    assert sync(root, "check", remote) == 0
    assert answer(capsys) == {"ok": True}
    cmd, kw = next((c, k) for c, k in calls if "ls-remote" in c)
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kw["env"]["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes" and "GIT_SSH" not in kw["env"]
    helpers = [cmd[i + 1] for i, v in enumerate(cmd[:-1]) if v == "-c" and cmd[i + 1].startswith("credential.helper")]
    assert helpers == ["credential.helper="]


def test_rows_keep_the_needs_shape(root):
    schema = json.loads((__import__("pathlib").Path(__file__).resolve().parents[3] / "contracts/needs.schema.json").read_text())
    configure(root)
    save(root)
    save(root, ART, SECRET)
    run(root)
    from jsonschema import Draft202012Validator

    Draft202012Validator(schema).validate(needs.rows(root))


def test_a_two_sided_review_too_large_as_a_whole_is_refused(root, monkeypatch):
    """N-2: each side fits (< REVIEW_MAX), but the whole review would not fit the sign step: refused, never
    clipped; a review that fits is returned as it is."""
    side = "k: " + "x" * 2000
    assert len(side) < act.REVIEW_MAX
    monkeypatch.setattr(act, "_proof_target", lambda *a: ("sync:keep-theirs:" + "0" * 64,
                                                         {"title": "Keep?", "here": side, "there": side}))
    with pytest.raises(repo.Refused, match="too large to review here"):
        act.proof_target(root, "keep-theirs", "tickets/t_abc123.json")
    small = {"title": "Keep?", "here": "a", "there": "\U0001F600" * 1800}  # 3600 UTF-16 units + 6: fits
    monkeypatch.setattr(act, "_proof_target", lambda *a: ("t", small))
    assert act.proof_target(root, "keep-theirs", "tickets/t_abc123.json") == ("t", small)
    big = {"title": "Keep?", "here": "a", "there": "\U0001F600" * 1950}  # 1950 characters but 3900 units
    monkeypatch.setattr(act, "_proof_target", lambda *a: ("t", big))
    with pytest.raises(repo.Refused, match="too large to review here"):
        act.proof_target(root, "keep-theirs", "tickets/t_abc123.json")


def test_review_size_counts_utf16_units():
    assert act._units("a") == 1 and act._units("\U0001F600") == 2  # an astral character is 2 in the dashboard
