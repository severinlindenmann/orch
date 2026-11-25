"""`orch sync act <verb> -- <target>`: what the dashboard's Sync card and Needs rows run (one generic add-on op)."""

import json
import shlex
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_step import ART, TICKET, configure, run, save, success, tracked
from test_two_machines import both, edit, machines

from orch_sync import act, cli, needs, paths, pause, repo, step

__all__ = ["machines"]
SECRET = b"orp_" + b"a" * 30


def sync(root, *args):
    return cli.main(["--dir", str(root), "act", *args, "--json"])


def answer(capsys):
    return json.loads(capsys.readouterr().out)


def choose(root, remote, monkeypatch, value="15"):
    """The person's choice of a sync address in the dashboard (act set)."""
    return sync(root, "set", remote, "--value", value)


def public_waits(root, tmp_path, monkeypatch, capsys):
    """A public address the person chose, waiting for their use-public choice."""
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


def test_keep_theirs_runs_plain_from_the_needs_row(machines, monkeypatch, capsys):
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
    assert not any("sign" in x for x in row["actions"])
    assert keep["keep-theirs"]["review"]["title"] == "Keep the other computer’s version of “Mine”?"
    assert cli.main(["--dir", str(b), "act", "keep-theirs", TICKET, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "Kept the other version."
    assert json.loads(repo.safe(b, TICKET).read_text())["title"] == "Theirs"


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


def test_secret_row_without_a_file_to_leave_out_offers_no_answer_buttons(root, monkeypatch):
    """fb14: a "Keep mine / Keep theirs" question with no buttons of its own could only fail in the dashboard."""
    paused = {
        "files": ["ticket-counter.json"],
        # an hour ago: a fixed date grew past 7 days on 18 Nov and added the "paused for 7 days" row (ORCH-390)
        "since": (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "reason": "a secret was found",
    }
    monkeypatch.setattr(cli, "read", lambda *a: {})
    monkeypatch.setattr(pause, "verified_pause", lambda *a: paused)
    rows = needs.rows(root)
    assert [r["kind"] for r in rows] == ["sync:secret"]
    assert "answer" not in rows[0] and not rows[0].get("actions")


def refused(root, capsys, *args):
    assert sync(root, *args) == 2
    return answer(capsys)["error"]


def test_a_file_name_sync_cannot_send_is_shown_never_silently_missing(root, capsys):
    """R1.6: a ticket's file named with an umlaut or & stays here, and the Sync card says so (rename to sync it)."""
    configure(root)
    save(root)
    capsys.readouterr()
    folder = "tickets/t_abc123/artifacts"
    for name in ("Grüße an Müller.pdf", "Q&A.txt", "Fotos März/Bild 1.jpg", "notes.txt", "x.pem", ".tmp-1"):
        save(root, f"{folder}/{name}", b"text")
    save(root, f"{folder}/.git/HEAD", b"ref")
    state = success(root)
    assert tracked(root) == {TICKET, f"{folder}/notes.txt"}
    assert sorted(state["skipped"]) == sorted(
        f"{folder}/{n}: {paths.ODD_NAME}" for n in ("Grüße an Müller.pdf", "Q&A.txt", "Fotos März/Bild 1.jpg")
    )  # never the key file, the temp file or a .git folder: those stay here quietly
    capsys.readouterr()
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert {r["name"] for r in card["not_synced"]} == {"Grüße an Müller.pdf", "Q&A.txt", "Bild 1.jpg"}
    assert all("rename it" in r["why"] for r in card["not_synced"])
    assert card["counts"] == {"tickets": 1, "files": 1, "bytes": card["counts"]["bytes"]}
    assert card["shown"] == "synced"


def test_not_synced_reads_names_with_a_colon_and_odd_lines(root, monkeypatch):
    lines = [
        f"tickets/t_abc123/artifacts/Plan: v2.txt: {paths.ODD_NAME}",
        "tickets/t_abc123/artifacts/big.bin: File exceeds 25 MB",
        "tickets/t_abc123/artifacts/odd.bin: something new",
        "Ticket t_abc123 has a problem and was not synced: bad: shape",
        7,
    ]
    got = act._not_synced(root, {"skipped": lines})
    assert got == [
        {"name": "Plan: v2.txt", "why": act.WHY[paths.ODD_NAME]},
        {"name": "big.bin", "why": "too big, stays on this computer"},
        {"name": "odd.bin", "why": "stays on this computer"},
        {"name": lines[3], "why": ""},
    ]
    assert act._not_synced(root, {"skipped": "not a list"}) == []


def test_status_card_before_the_first_sync_is_empty_not_an_error(root, capsys):
    assert sync(root, "status", "sync") == 0
    card = answer(capsys)
    assert card["shown"] == "off" and card["counts"] == {"tickets": 0, "files": 0, "bytes": 0}
    assert card["not_synced"] == [] and card["history"] == [] and card["remote"] is None


def test_set_where_saves_and_refuses_plainly(root, tmp_path, capsys, monkeypatch):
    assert sync(root, "set", "local") == 0
    assert answer(capsys) == {"mode": "local", "text": "Saved."}
    remote = f"file://{bare(tmp_path)}"
    assert "preview-only" in refused(root, capsys, "set", remote)  # remote sync is not on in this install
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    for value in ("7", "soon"):
        assert (
            refused(root, capsys, "set", remote, "--value", value) == "Sync can run every 5, 15 or 60 minutes"
        )
    assert sync(root, "set", remote, "--value", "60") == 0
    assert answer(capsys)["interval"] == 60
    assert sync(root, "set", remote, "--value", "5") == 0  # the same address: only how often
    got = answer(capsys)
    assert got["interval"] == 5 and got["mode"] == "remote"
    assert cli.read(root, "settings")["interval"] == 5
    assert sync(root, "set", "off") == 0
    assert answer(capsys)["mode"] == "off"
    assert "off" in refused(root, capsys, "now", "sync")


def test_public_address_waits_for_the_persons_choice(root, tmp_path, monkeypatch, capsys):
    remote = public_waits(root, tmp_path, monkeypatch, capsys)
    assert act.pending_public(root) == {"remote": remote, "interval": 15}
    assert sync(root, "status", "sync") == 0
    assert answer(capsys)["public"] == cli.safe_address(remote)
    assert sync(root, "now", "sync") == 0
    assert answer(capsys)["choose_first"] is True
    assert sync(root, "use-public", "sync") == 0
    assert answer(capsys)["text"] == "Using the public location."
    assert cli.read(root, "settings")["remote"] == remote and act.pending_public(root) is None
    assert refused(root, capsys, "use-public", "sync") == "No public address waits for a choice"


@pytest.mark.parametrize("body", [[1], {"remote": 5, "interval": 15}, {"remote": "x"}, "{"])
def test_a_malformed_public_record_counts_as_absent(root, body):
    p = root / ".orch/run/sync/pending-public.json"
    p.parent.mkdir(parents=True)
    p.write_text(body if isinstance(body, str) else json.dumps(body))
    assert act.pending_public(root) is None


def test_sync_now_wakes_a_running_loop_or_runs_once(root, monkeypatch, capsys):
    from orch_sync import loop, service

    configure(root)
    save(root)
    capsys.readouterr()
    woken = []
    monkeypatch.setattr(service, "running_pid", lambda r: 4242)
    monkeypatch.setattr(loop, "wake_up", lambda r, *a: woken.append(r))
    assert sync(root, "now", "sync") == 0
    assert answer(capsys) == {"woken": True, "text": "Syncing…"} and woken == [root]
    monkeypatch.setattr(service, "running_pid", lambda r: None)
    assert sync(root, "now", "sync") == 0
    got = answer(capsys)
    assert got["text"] == "Synced." and got["last_error"] is None and got["last_ok"]
    assert TICKET in tracked(root)


def test_unknown_verbs_and_targets_are_refused(root, capsys):
    from types import SimpleNamespace

    with pytest.raises(repo.Refused, match="not available"):
        act.act(root, dict(cli.DEFAULTS), SimpleNamespace(verb="fly", target="x"))
    assert refused(root, capsys, "allow", "t_abc123") == "Say the ticket and the add-on: <ticket>:<add-on>"
