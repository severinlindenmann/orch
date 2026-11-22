"""ORCH-1035: `orch dashboard token new|list|revoke` (the login screen's tokens)."""

import json

import pytest

pytest.importorskip("orch")

from orch import tickets

from orch_dashboard import cli


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A test workspace with a test orch home (never the real one)."""
    from orch import addons

    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    return root


@pytest.fixture
def person(monkeypatch):
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)


def _run(capsys, ws, *argv):
    code = cli.main(["--dir", str(ws), "token", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_new_list_revoke(ws, capsys, person):
    code, out, _ = _run(capsys, ws, "new", "--label", "Anna", "--json")
    assert code == 0
    made = json.loads(out)
    assert made["token"].startswith("odt_") and made["state"] == "active"
    code, out, _ = _run(capsys, ws, "list", "--json")
    listed = json.loads(out)["tokens"]
    assert [t["id"] for t in listed] == [made["id"]] and "token" not in listed[0]
    code, out, _ = _run(capsys, ws, "list")
    assert made["id"] in out and "works until" in out and made["token"] not in out
    code, out, _ = _run(capsys, ws, "revoke", made["id"])
    assert code == 0 and "revoked" in out
    code, out, _ = _run(capsys, ws, "list", "--json")
    assert json.loads(out)["tokens"][0]["state"] == "revoked"


def test_revoke_needs_a_known_id(ws, capsys, person):
    assert _run(capsys, ws, "revoke")[0] == 2
    code, _, err = _run(capsys, ws, "revoke", "zzzzzzzz")
    assert code == 2 and "no token" in err


def test_an_agent_cannot_make_one(ws, capsys, monkeypatch):
    from orch import pagelaunch

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    code, _, err = _run(capsys, ws, "new")
    assert code == 2 and "Only a person" in err
