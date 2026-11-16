"""ORCH-7: the starter task on a first `orch init`, and the workspace profile (name, description, tags) an
agent may fill in until a person chose it."""

import json

import pytest

from orch import adapters, config, init, term, tickets


@pytest.fixture(autouse=True)
def no_agent_found(monkeypatch):
    monkeypatch.setattr(adapters, "detect", lambda: [])


def _tickets(proj):
    return tickets.list_all(proj)


def test_first_init_adds_the_starter_task_when_asked(proj, run):
    code, out, _ = run("init", "--starter", "--json")
    assert code == 0
    data = json.loads(out)
    ts = _tickets(proj)
    assert len(ts) == 1 and data["starter"] == ts[0]["key"]
    t = ts[0]
    assert t["title"] == init.STARTER_TITLE
    assert [c["text"] for c in t["checklist"]] == list(init.STARTER_STEPS)
    assert "orch config set workspace.tags" in t["note"]


def test_starter_is_added_only_on_the_first_init(proj, run):
    assert run("init", "--starter")[0] == 0
    assert run("init", "--starter")[0] == 0
    assert len(_tickets(proj)) == 1


def test_not_in_a_script_by_default(proj, run):
    assert run("init", "--json")[0] == 0  # stdin is no terminal here
    assert _tickets(proj) == []


def test_no_starter_turns_it_off_at_a_terminal(proj, run, monkeypatch):
    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert run("init", "--no-starter")[0] == 0
    assert _tickets(proj) == []


def test_a_person_at_a_terminal_gets_it(proj, run, monkeypatch):
    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr("builtins.input", lambda *_: "")  # no agent found: "Other", no command
    code, out, _ = run("init")
    assert code == 0 and "Starter task" in out
    assert len(_tickets(proj)) == 1


# ---- the profile: who may set name, description and tags


@pytest.fixture
def ws(proj, run):
    assert run("init")[0] == 0
    return proj


def _as_agent(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")


def test_agent_sets_name_description_tags_while_nobody_chose(ws, run, monkeypatch):
    _as_agent(monkeypatch)
    assert run("config", "set", "workspace.name", "Bakery site")[0] == 0
    assert run("config", "set", "workspace.description", "Our bakery's website.")[0] == 0
    assert run("config", "set", "workspace.tags", "web, Bakery")[0] == 0
    assert run("config", "set", "workspace.name", "Bakery website")[0] == 0  # its own pick: may change
    assert config.workspace_name(ws) == "Bakery website"
    assert config.workspace_tags(ws) == ["web", "bakery"]
    assert config.profile_set_by(ws) == {"name": "agent", "description": "agent", "tags": "agent"}
    code, out, _ = run("config", "get", "workspace.tags")
    assert out.splitlines()[0] == "web,bakery"


def test_agent_is_refused_after_a_person_chose(ws, run, monkeypatch):
    assert run("config", "set", "workspace.name", "My bakery")[0] == 0
    assert run("config", "set", "workspace.tags", "shop")[0] == 0
    _as_agent(monkeypatch)
    code, out, err = run("config", "set", "workspace.name", "Agent name")
    assert code == 2 and "The person chose the workspace name" in out + err
    assert run("config", "set", "workspace.tags", "web")[0] == 2
    assert config.workspace_name(ws) == "My bakery" and config.workspace_tags(ws) == ["shop"]
    assert run("config", "set", "workspace.description", "free for the agent")[0] == 0


def test_a_value_from_before_counts_as_the_persons(ws, run, monkeypatch):
    config.set_workspace_description(ws, "set by hand, nothing recorded")
    _as_agent(monkeypatch)
    assert run("config", "set", "workspace.description", "agent text")[0] == 2


def test_faking_the_record_in_the_workspace_does_not_help(ws, run, monkeypatch):
    assert run("config", "set", "workspace.name", "Mine")[0] == 0
    config.set_key(ws, "workspace", "profile_set_by", "agent")  # ignored: kept in the orch home
    _as_agent(monkeypatch)
    assert run("config", "set", "workspace.name", "Theirs")[0] == 2


@pytest.mark.parametrize("bad", ["a,b,c,d,e", "Has Space!", "x" * 25])
def test_tags_are_checked(ws, run, bad):
    assert run("config", "set", "workspace.tags", bad)[0] == 2
    assert config.workspace_tags(ws) == []


def test_empty_clears_the_tags(ws, run):
    assert run("config", "set", "workspace.tags", "a,b")[0] == 0
    assert run("config", "set", "workspace.tags", "")[0] == 0
    assert config.workspace_tags(ws) == []
    assert "tags" not in (config.read(ws).get("workspace") or {})
