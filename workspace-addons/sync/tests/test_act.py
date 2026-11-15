"""`orch sync act <verb> -- <target>`: what the dashboard's Sync card and Needs rows run (one generic add-on op)."""

import hashlib
import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest
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


def test_set_is_a_persons_click(root, monkeypatch, capsys):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    assert sync(root, "set", "local") == 2
    assert "A person chooses where sync keeps a copy" in answer(capsys)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()


def test_check_uses_syncs_own_transport_rules(root, tmp_path, capsys, normal_install):
    for bad in (
        "file:///tmp/x",
        "/tmp/x",
        "http://example.org/x",
        "ext::sh -c x",
        "https://me:pw@example.org/x",
    ):
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


def test_set_review_shows_the_address_without_its_login(root, monkeypatch):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    target, review = act.proof_target(root, "set", "ssh://git@host.example/me/orch", "60")
    assert target == cli.remote_target("ssh://git@host.example/me/orch")
    assert review["value"] == "ssh://host.example/me/orch" and "every 60 minutes" in review["body"]


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
    assert (
        keep["keep-mine"]["review"]["here"] == "Title: Mine"
        and keep["keep-mine"]["review"]["there"] == "Title: Theirs"
    )
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
        assert (
            review["value"] == f"{raw.decode()} ({len(raw)} bytes)"
        )  # whole: the payload after a long prefix shows
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
    assert (
        act.plain("a\u202eb\u2066c\u200bd\x9be\x07f\ufeffg") == "a\ufffdb\ufffdc\ufffdd\ufffde\ufffdf\ufffdg"
    )
    assert act.plain("one\ntwo   three\x85four") == "one two three four"  # line breaks (also NEL): one space
    assert act.plain("x" * 10, 5) == "xxxx…"
    assert (
        act.plain("plain text, ünïcode 日本 é") == "plain text, ünïcode 日本 é"
    )  # ordinary text is untouched
    for hidden in (
        "\xad",
        "\u180e",
        "\ufe00",
        "\ufe0f",
        "\U000e0000",
        "\U000e0041",
        "\U000e007f",
        "\U000e0100",
        "\U000e01ef",
        "\u180b",
        "\u115f",
        "\u1160",
        "\u3164",
        "\uffa0",
        "\ue000",
        "\ud800",
        "\u0378",
        "\U000f0000",
    ):
        assert act.plain(f"a{hidden}b") == "a\ufffdb"


def test_needs_rows_never_hide_a_character():
    row = needs.row(
        "paused",
        "k",
        "x\U000e0041y",
        "now",
        "cmd",
        ["a\xadb"],
        title="t\ufe0fz",
        actions=[needs.action("Keep", "keep-mine", "p", review={"title": "r\u180es"})],
    )
    assert (row["text"], row["title"], row["answer"]["options"]) == ("x\ufffdy", "t\ufffdz", ["a\ufffdb"])
    assert row["actions"][0]["review"]["title"] == "r\ufffds"


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


@pytest.mark.parametrize("remote", [None, "", 0, ["x"]])
def test_a_pause_without_a_checked_version_offers_no_saved_copy(machines, remote):
    """L-3: a signed pause whose remote_sha is empty or not a string, or None with a saved copy, takes no saved copy."""
    a, b, _ = both(machines)
    edit(a, title="Theirs")
    edit(b, title="Mine")
    success(a)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        state = run(b)
    state["paused"] = pause.sign(
        b, {**{k: v for k, v in state["paused"].items() if k != "mac"}, "remote_sha": remote}
    )
    step.write(b, "run/sync/state.json", step.encoded(state))
    with pytest.raises(repo.Refused, match="Saved copy does not match the checked version"):
        pause.resolve_sides(b, TICKET)


def test_a_pause_with_no_remote_version_and_no_saved_copy_still_resolves(machines):
    """A pause before any remote version (first push, local mode) has no saved copy: Keep mine still works."""
    a, b, _ = both(machines)
    edit(a, title="Theirs")
    edit(b, title="Mine")
    success(a)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(step.merge, "merge_ticket", lambda *a, **k: None)
        state = run(b)
    state["paused"] = pause.sign(
        b, {**{k: v for k, v in state["paused"].items() if k != "mac"}, "remote_sha": None}
    )
    step.write(b, "run/sync/state.json", step.encoded(state))
    saved = repo.safe(b, "run/sync/theirs/" + TICKET)
    if saved.exists():
        saved.unlink()
    _paused, remote, _, theirs = pause.resolve_sides(b, TICKET)
    assert remote is None and theirs is None


def test_leave_deleted_review_names_the_ticket(machines):
    """L4: the sign step says which ticket: its title (of the synced copy left deleted) and its id."""
    a, _, _ = both(machines)
    repo.safe(a, TICKET).unlink()
    success(a)
    target, review = act.proof_target(a, "leave-deleted", "t_abc123")
    assert target == "sync:deleted:t_abc123"
    assert review == {
        "title": "Leave this ticket deleted?",
        "body": "It is removed on every computer that syncs.",
        "value": "“A task” (t_abc123)",
    }
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
    assert kw["env"]["GIT_SSH_COMMAND"] == repo.TYPED_SSH and "GIT_SSH" not in kw["env"]
    assert shlex.split(repo.TYPED_SSH) == [  # none of the person's config, keys or agent identities (L-1)
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityFile=/dev/null",
        "-o",
        "IdentityAgent=none",
        "-o",
        "PubkeyAuthentication=no",
    ]
    helpers = [
        cmd[i + 1] for i, v in enumerate(cmd[:-1]) if v == "-c" and cmd[i + 1].startswith("credential.helper")
    ]
    assert helpers == ["credential.helper="]


def test_rows_keep_the_needs_shape(root):
    schema = json.loads(
        (
            __import__("pathlib").Path(__file__).resolve().parents[3] / "contracts/needs.schema.json"
        ).read_text()
    )
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
    monkeypatch.setattr(
        act,
        "_proof_target",
        lambda *a: ("sync:keep-theirs:" + "0" * 64, {"title": "Keep?", "here": side, "there": side}),
    )
    with pytest.raises(repo.Refused, match="too large to review here"):
        act.proof_target(root, "keep-theirs", "tickets/t_abc123.json")
    small = {"title": "Keep?", "here": "a", "there": "\U0001f600" * 1800}  # 3600 UTF-16 units + 6: fits
    monkeypatch.setattr(act, "_proof_target", lambda *a: ("t", small))
    assert act.proof_target(root, "keep-theirs", "tickets/t_abc123.json") == ("t", small)
    big = {"title": "Keep?", "here": "a", "there": "\U0001f600" * 1950}  # 1950 characters but 3900 units
    monkeypatch.setattr(act, "_proof_target", lambda *a: ("t", big))
    with pytest.raises(repo.Refused, match="too large to review here"):
        act.proof_target(root, "keep-theirs", "tickets/t_abc123.json")


def test_review_size_counts_utf16_units():
    assert act._units("a") == 1 and act._units("\U0001f600") == 2  # an astral character is 2 in the dashboard


def test_secret_row_without_a_file_to_leave_out_offers_no_answer_buttons(root, monkeypatch):
    """fb14: a "Keep mine / Keep theirs" question with no buttons of its own could only fail in the dashboard."""
    paused = {
        "files": ["ticket-counter.json"],
        "since": "2026-11-11T10:12:00Z",
        "reason": "a secret was found",
    }
    monkeypatch.setattr(cli, "read", lambda *a: {})
    monkeypatch.setattr(pause, "verified_pause", lambda *a: paused)
    rows = needs.rows(root)
    assert [r["kind"] for r in rows] == ["sync:secret"]
    assert "answer" not in rows[0] and not rows[0].get("actions")
