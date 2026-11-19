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
        orch_home.move_here(copy)  # the core step refuses on its own too
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
    assert set(res["files"]) >= {
        "binding.json",
        "permissions.json",
        "ports.json",
        "consent.json",
        "running.json",
    }
    assert json.loads((home / "permissions.json").read_text()) == {h(new): "full", "other": "ask"}
    assert json.loads((home / "ports.json").read_text()) == {f"{new}\tdashboard": 8790, "/x\tdashboard": 8791}
    assert json.loads((home / "consent.json").read_text())[0]["workspace"] == new
    assert json.loads((home / "running.json").read_text())[0]["workspace"] == new
