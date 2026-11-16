"""`orch sync act <verb> -- <target>`: what the dashboard's Sync card and Needs rows run (one generic add-on op)."""

import json
import shlex
import subprocess

import pytest
from test_step import ART, TICKET, configure, run, save, success
from test_two_machines import both, edit, machines

from orch_sync import act, cli, needs, pause, repo, step

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
        "since": "2026-11-11T10:12:00Z",
        "reason": "a secret was found",
    }
    monkeypatch.setattr(cli, "read", lambda *a: {})
    monkeypatch.setattr(pause, "verified_pause", lambda *a: paused)
    rows = needs.rows(root)
    assert [r["kind"] for r in rows] == ["sync:secret"]
    assert "answer" not in rows[0] and not rows[0].get("actions")
