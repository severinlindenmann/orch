"""ORCH-853: a moved workspace folder. Its saved keys stay bound to the old path (N17), so every refusal must
name that and the way out (never "holds a secret"), and `orch workspace move-here` re-binds it for a person,
moving the old path's records in the orch home; a copy stays refused. All under a temp account home."""

import hashlib
import json
import os
import shutil

import pytest

from orch import addons, cli, keystore, secretscan, workspace_move
from orch import home as orch_home
from orch.errors import Refused

TOKEN = "tok-Q7xP2mK9vL4zR8"  # a made-up value, long enough to be stored


@pytest.fixture
def acct(tmp_path, monkeypatch):
    a = tmp_path / "acct"
    (a / ".orch-test").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: a)
    monkeypatch.setattr(orch_home, "install_kind", lambda: "test")
    monkeypatch.delenv("ORCH_HOME", raising=False)
    for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_JOB", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    return a


@pytest.fixture
def tws(acct, monkeypatch):
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    keystore.add(ws, "k", "token", TOKEN)
    return ws


@pytest.fixture
def moved(tws, acct):
    m = acct / ".orch-test" / "moved"
    tws.rename(m)
    return m


@pytest.fixture
def person(monkeypatch):
    monkeypatch.setattr(workspace_move, "is_person", lambda by=None: True)


def _yes(question):
    return "y"


def test_a_moved_folder_says_why_and_names_the_command(moved):
    with pytest.raises(Refused, match="copied or moved") as e:
        keystore.get_value(moved, "k")
    assert orch_home.MOVE_HERE in str(e.value) and "ws" in str(e.value)  # the old folder is named
    assert orch_home.binding_state(moved) == "moved"
    # every strict secret check fails closed with its own kind, and the refusal carries the reason
    found = secretscan.find("hello", moved)
    assert found == [{"kind": "keys-unreadable", "line": 1}]
    text = secretscan.refusal(found, moved)
    assert orch_home.MOVE_HERE in text and "secret value" not in text and "stored keys" not in text
    # a line the scrub flags too: the keys reason still comes first (fix that, then the line is shown)
    both = secretscan.find("password: hunter2-long-value", moved)
    assert {f["kind"] for f in both} == {"keys-unreadable", "secret-value"}
    assert orch_home.MOVE_HERE in secretscan.refusal(both, moved)
    # sends (strict=False) still skip only the comparison: plain text goes, a real secret does not
    secretscan.refuse_if_secret_in(moved, {"text": "hello"})


def test_the_scan_command_names_the_reason(moved, monkeypatch, capsys):
    import io
    import sys

    monkeypatch.chdir(moved)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"hello\n"), encoding="utf-8"))
    code = cli.main(["secret", "scan", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["code"] == "stored_keys_unreadable" and orch_home.MOVE_HERE in out["error"]


def test_move_here_rebinds_and_the_keys_work_again(moved, person):
    res = workspace_move.move_here(moved, ask=_yes)
    assert res["moved"] and res["new"] == os.path.realpath(moved) and "binding.json" in res["files"]
    assert keystore.get_value(moved, "k") == TOKEN
    assert orch_home.binding_state(moved) == "here"
    assert secretscan.find("hello", moved) == []
    again = workspace_move.move_here(moved, ask=lambda q: pytest.fail("asked although nothing to move"))
    assert again["moved"] is False


def test_the_question_names_both_folders_and_no_moves_nothing(moved, person):
    asked = []
    with pytest.raises(Refused, match="Nothing was moved"):
        workspace_move.move_here(moved, ask=lambda q: asked.append(q) or "")
    assert os.path.realpath(moved) in asked[0] and "ws" in asked[0]
    assert orch_home.binding_state(moved) == "moved"

    def eof(q):
        raise EOFError

    with pytest.raises(Refused, match="Nothing was moved"):  # input closed: no, never a crash
        workspace_move.move_here(moved, ask=eof)


def test_a_copy_is_refused_and_the_original_keeps_its_keys(tws, acct, person):
    copy = acct / ".orch-test" / "copy"
    shutil.copytree(tws, copy)
    assert orch_home.binding_state(copy) == "copy"
    with pytest.raises(Refused, match="is a copy of"):
        keystore.get_value(copy, "k")
    with pytest.raises(Refused, match="is a copy of"):
        workspace_move.move_here(copy, ask=_yes)
    with pytest.raises(Refused, match="is a copy of"):
        wid = addons.read_local_id(copy)
        orch_home.move_here(copy, expect_id=wid, expect_old=os.path.realpath(tws))  # the core refuses too
    assert keystore.get_value(tws, "k") == TOKEN


def test_a_helper_cannot_move_the_keys(moved, monkeypatch):
    monkeypatch.setenv("ORCH_AGENT", "claude")
    with pytest.raises(Refused, match="a helper can't"):
        workspace_move.move_here(moved, ask=_yes)
    monkeypatch.delenv("ORCH_AGENT")
    with pytest.raises(Refused, match="a helper can't"):  # no terminal (pytest's stdin): no person to ask
        workspace_move.move_here(moved, ask=_yes)
    assert orch_home.binding_state(moved) == "moved"


def test_the_command_refuses_without_a_person(moved, monkeypatch, capsys):
    monkeypatch.chdir(moved)
    code = cli.main(["workspace", "move-here", "--json"])
    assert code == 2 and "a helper can't" in json.loads(capsys.readouterr().out)["error"]


def test_the_old_paths_records_move_along(tws, acct, person):
    old = os.path.realpath(tws)
    home = addons.home()
    wid = addons.read_local_id(tws)
    h = lambda p: hashlib.sha256(p.encode()).hexdigest()[:32]  # noqa: E731
    (home / "permissions.json").write_text(json.dumps({h(old): "full", "other": "ask"}))
    (home / "ports.json").write_text(json.dumps({f"{old}\tdashboard": 8790, "/x\tdashboard": 8791}))
    (home / "consent.json").write_text(json.dumps([{"workspace_id": wid, "workspace": old, "name": "relay"}]))
    (home / "running.json").write_text(json.dumps([{"workspace": old, "addon": "dashboard", "pid": 1}]))
    m = acct / ".orch-test" / "moved"
    tws.rename(m)
    new = os.path.realpath(m)
    res = workspace_move.move_here(m, ask=_yes)
    assert set(res["files"]) == {"binding.json", "permissions.json", "ports.json", "consent.json"}
    assert "not_moved" not in res
    assert json.loads((home / "permissions.json").read_text()) == {h(new): "full", "other": "ask"}
    assert json.loads((home / "ports.json").read_text()) == {f"{new}\tdashboard": 8790, "/x\tdashboard": 8791}
    assert json.loads((home / "consent.json").read_text())[0]["workspace"] == new
    assert json.loads((home / "running.json").read_text())[0]["workspace"] == new


def test_an_id_swapped_while_the_question_waits_moves_nothing(moved, acct, person):
    # Codex review: .local-id is workspace-writable; the re-bind checks the id the person was asked about
    idf = moved / ".orch" / ".local-id"

    def swap(q):
        idf.write_text("f" * 32)
        return "y"

    old = os.path.realpath(moved).replace("moved", "ws")
    home = addons.home()
    key = hashlib.sha256(old.encode()).hexdigest()[:32]
    (home / "permissions.json").write_text(json.dumps({key: "full"}))
    with pytest.raises(Refused, match="changed while orch asked"):
        workspace_move.move_here(moved, ask=swap)
    assert json.loads((home / "permissions.json").read_text()) == {key: "full"}  # no record moved either


def test_the_core_step_checks_the_confirmed_id_and_folder(moved):
    wid = addons.read_local_id(moved)
    with pytest.raises(Refused, match="changed while orch asked"):
        orch_home.move_here(moved, expect_id="e" * 32, expect_old="/x")
    with pytest.raises(Refused, match="changed while orch asked"):
        orch_home.move_here(moved, expect_id=wid, expect_old="/not/the/old/folder")
    assert orch_home.binding_state(moved) == "moved"


def test_an_original_whose_id_was_removed_still_counts_as_a_copy(tws, acct, person):
    # Codex review: a missing or broken id in the original folder must not let a copy take its keys
    copy = acct / ".orch-test" / "copy"
    shutil.copytree(tws, copy)
    (tws / ".orch" / ".local-id").unlink()
    assert orch_home.binding_state(copy) == "copy"
    with pytest.raises(Refused, match="is a copy of"):
        workspace_move.move_here(copy, ask=_yes)
    shutil.rmtree(tws / ".orch")
    with pytest.raises(Refused, match="is a copy of"):  # a plain folder left at the old place: still refused
        workspace_move.move_here(copy, ask=_yes)


def test_a_new_workspace_at_the_old_place_does_not_block_the_move(tws, acct, person):
    m = acct / ".orch-test" / "moved"
    tws.rename(m)
    (tws / ".orch").mkdir(parents=True)
    (tws / ".orch" / ".local-id").write_text("a" * 32)  # another workspace now lives at the old path
    assert workspace_move.move_here(m, ask=_yes)["moved"]
    assert keystore.get_value(m, "k") == TOKEN


def test_a_record_that_cannot_be_moved_stops_before_the_keys_and_a_retry_finishes(tws, acct, person):
    # Codex review: a failed record was skipped and could never be retried once the keys moved
    old = os.path.realpath(tws)
    home = addons.home()
    (home / "ports.json").write_text(json.dumps({f"{old}\tdashboard": 8790}))
    (home / "permissions.json").mkdir()  # cannot be read as a file: a failure
    m = acct / ".orch-test" / "moved"
    tws.rename(m)
    with pytest.raises(Refused, match="permissions.json"):
        workspace_move.move_here(m, ask=_yes)
    assert orch_home.binding_state(m) == "moved"  # the keys did not move
    (home / "permissions.json").rmdir()
    res = workspace_move.move_here(m, ask=_yes)
    assert res["moved"] and "ports.json" not in res["files"]  # moved in the first try already
    assert json.loads((home / "ports.json").read_text()) == {f"{os.path.realpath(m)}\tdashboard": 8790}


def test_the_text_says_when_running_services_were_not_updated():
    from orch import cli_workspace

    res = {"moved": True, "old": "/a", "new": "/b", "files": ["binding.json"], "not_moved": ["running.json"]}
    assert "running background services" in cli_workspace._text(res)
    assert "running" not in cli_workspace._text({**res, "not_moved": []})


def test_none_of_the_new_texts_reads_as_a_secret():
    # the line scrub reads "<key word>: <value>" as a secret: a helper quoting one of these in a note, or a
    # problem report holding the check, would itself be refused or blanked when shared
    from orch import cli_workspace
    from orch.diag_checks import workspace_folder_moved as chk

    old = "/Users/someone/Documents/Internal"
    texts = [
        orch_home.MOVED_FROM.format(old=old),
        orch_home.COPY_OF.format(old=old),
        orch_home.CHANGED_WHILE_ASKED,
        workspace_move.NOT_A_PERSON,
        cli_workspace._text(
            {"moved": True, "old": old, "new": "/b", "files": [], "not_moved": ["running.json"]}
        ),
        cli_workspace._text({"moved": False}),
        f"orch could not compare the text with your saved keys, so it stays refused: {orch_home.MOVED_FROM}",
        json.dumps({"workspace_folder": "moved"}),
    ]
    for state in ("here", "moved", "copy", "none", "unknown"):
        c = chk.check({"collected": {"env": {"data": {"workspace_folder": state}}}})
        texts += [f"[{c['verdict']}] {c['name']}: {c['fact']}", *c["evidence"]]
    for t in texts:
        assert secretscan.find(t.removeprefix("Refused: ")) == [], t
