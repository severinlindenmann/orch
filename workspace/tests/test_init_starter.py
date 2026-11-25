"""ORCH-7: the starter task on a first `orch init`, and the workspace profile (name, description, tags) an
agent may fill in until a person chose it."""

import json

import pytest

from orch import adapters, config, init, term, tickets


@pytest.fixture(autouse=True)
def no_agent_found(monkeypatch):
    monkeypatch.setattr(adapters, "detect", lambda **_: [])


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
    monkeypatch.setattr("builtins.input", lambda *_: "")  # no agent found: not now
    code, out, _ = run("init")
    assert code == 0 and "Starter task" in out
    assert len(_tickets(proj)) == 1


# ---- the person's name, asked once at a terminal (report r-1119-1255-ws-8: only the dashboard asked it)


def _answers(monkeypatch, *given):
    """Answers typed at the terminal, in order; the agent question gets "" (no agent found: not now).
    The name is asked with --recommended only (ORCH-1862: the dashboard shows it); nothing to turn on here."""
    monkeypatch.setattr(init, "recommended", lambda *a, **k: [])
    asked = []
    left = list(given)

    def ask(prompt=""):
        asked.append(prompt)
        return left.pop(0) if prompt.startswith("Your name") and left else ""

    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr("builtins.input", ask)
    return asked


def test_init_asks_the_name_once(proj, run, monkeypatch):
    from orch import whoami

    asked = _answers(monkeypatch, "Anna")
    code, out, err = run("init", "--recommended", "--no-starter")
    assert code == 0, err
    assert "You         Anna" in out
    assert whoami.current(proj) == "Anna"
    asked.clear()
    assert run("init", "--recommended", "--no-starter")[0] == 0
    assert not [a for a in asked if a.startswith("Your name")]  # chosen: never asked again


def test_a_plain_init_asks_no_name(proj, run, monkeypatch):
    from orch import whoami

    asked = _answers(monkeypatch, "Anna")
    code, out, _ = run("init", "--no-starter")
    assert code == 0 and "dashboard" not in "".join(asked) and whoami.current(proj) is None


def test_an_empty_name_is_skipped(proj, run, monkeypatch):
    from orch import whoami

    _answers(monkeypatch, "")
    assert run("init", "--recommended", "--no-starter")[0] == 0
    assert whoami.current(proj) is None  # the dashboard still offers Pick your name


def test_name_not_asked_with_yes_or_under_a_helper(proj, run, monkeypatch):
    asked = _answers(monkeypatch, "Anna")
    assert run("init", "--recommended", "--yes", "--no-starter")[0] == 0
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("init", "--recommended", "--no-starter")[0] == 0
    assert not [a for a in asked if a.startswith("Your name")]


# ---- ORCH-1862: one clear first step; local tickets work after a plain init, the dashboard stays optional


def _recommends(monkeypatch, names):
    monkeypatch.setattr(init, "recommended_names", lambda root: list(names))


@pytest.mark.parametrize("again", [False, True])
def test_a_plain_init_with_no_agent_says_ready_first(proj, run, monkeypatch, again):
    _recommends(monkeypatch, ["dashboard"])
    if again:
        assert run("init")[0] == 0
    code, out, _ = run("init")  # no terminal, no agent on this computer
    assert code == 0 and out.startswith(init.READY + "\n")
    assert init.NO_AGENT in out and init.CAN_USE not in out and init.CONSENT in out
    assert init.optional_line(["dashboard"]) in out
    assert out.rstrip().endswith('Next: orch ticket new "<title>"')  # never another init


def test_nothing_to_recommend_is_not_offered(proj, run, monkeypatch):
    _recommends(monkeypatch, [])
    code, out, _ = run("init")
    assert code == 0 and "--recommended" not in out


def test_init_json_stays_one_document(proj, run, monkeypatch):
    _recommends(monkeypatch, ["dashboard"])
    code, out, _ = run("init", "--json")
    data = json.loads(out)
    assert data["agent"] == init.NO_AGENT and init.optional_line(["dashboard"]) in data["details"]


def test_recommended_turns_on_and_offers_nothing_more(proj, run, monkeypatch):
    monkeypatch.setattr(init, "recommended", lambda *a, **k: ["dashboard"])
    code, out, _ = run("init", "--recommended", "--yes")
    assert code == 0 and out.startswith(init.READY) and "Turned on: dashboard" in out
    assert "Optional    " not in out and out.rstrip().endswith('Next: orch ticket new "<title>"')


def _one_recommended(monkeypatch):
    from orch import addons

    monkeypatch.setattr(addons, "listing", lambda root: [{"name": "x", "recommended": True, "active": False}])
    monkeypatch.setattr(addons, "discover", lambda: {"x": {"name": "x"}})
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: {})
    monkeypatch.setattr(addons, "consent_text", lambda m, _: "x: adds a tab")
    monkeypatch.setattr(addons, "add", lambda *a, **k: pytest.fail("nothing is turned on without a yes"))


def test_recommended_without_yes_in_a_script_says_tickets_work(proj, run, monkeypatch):
    _one_recommended(monkeypatch)
    code, _, err = run("init", "--recommended")
    assert code == 2 and "Local tickets work here already" in err and "--yes" in err
    assert (proj / ".orch" / "tickets").is_dir()


def test_declined_at_a_terminal_ready_first_then_nothing_turned_on(proj, run, monkeypatch):
    _one_recommended(monkeypatch)
    asked = []
    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "")
    monkeypatch.setattr("sys.stdin.readline", lambda: "n\n")
    code, out, err = run("init", "--recommended", "--no-starter")
    assert code == 2 and out.startswith(init.READY) and init.NO_AGENT in out
    assert "Not confirmed, so no add-on was turned on. Local tickets work here" in err
    assert [a for a in asked if a.startswith("None found here")]  # the optional agent question, declined


def test_no_agent_at_a_terminal_the_question_comes_after_ready(proj, run, monkeypatch, capsys):
    _recommends(monkeypatch, [])
    seen = []

    def ask(prompt=""):
        seen.append(capsys.readouterr().out)  # what was on screen when the question came
        return ""

    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr("builtins.input", ask)
    code, out, _ = run("init")
    assert code == 0 and seen[0].startswith(init.READY) and init.NO_AGENT in out
    assert out.rstrip().endswith('Next: orch ticket new "<title>"')  # the starter needs an agent first


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


# ---- Ctrl-D / Ctrl-C at a question (ORCH-1868: a traceback and a half .orch folder)


@pytest.mark.parametrize("stop", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("found", [True, False])  # "Pick [1]:" or, with no agent found, "Name for it"
def test_stopping_at_the_agent_question_keeps_local_tickets(proj, run, monkeypatch, stop, found):
    """Local tickets are in place before the first question (ORCH-1862): a stop says so, no traceback."""
    from orch import adapters

    agents = [{"name": "claude", "label": "Claude", "found": True, "version": None}] if found else []
    monkeypatch.setattr(adapters, "detect", lambda: agents)
    monkeypatch.setattr(term, "is_terminal", lambda f: True)

    def ask(prompt=""):
        raise stop

    monkeypatch.setattr("builtins.input", ask)
    code, out, err = run("init")
    assert code == 2 and "Traceback" not in err and "Refused" not in err
    assert err.strip() == (
        "Stopped. orch is set up in this folder; the rest was skipped. Run orch init again to finish."
    )
    assert (proj / ".orch" / "tickets").is_dir()


def test_stopping_at_the_name_question_says_orch_is_set_up(proj, run, monkeypatch):
    from orch import init as init_mod

    monkeypatch.setattr(term, "is_terminal", lambda f: True)
    monkeypatch.setattr(init_mod, "recommended", lambda root, yes=False, interactive=False: [])

    def ask(prompt=""):
        if prompt.startswith("Your name"):
            raise KeyboardInterrupt
        return ""

    monkeypatch.setattr("builtins.input", ask)
    code, _, err = run("init", "--recommended")  # the name is for the dashboard: asked with --recommended
    assert code == 2 and "Traceback" not in err and "Refused" not in err
    assert "Stopped. orch is set up in this folder" in err and "Run orch init again" in err
    assert (proj / ".orch" / "tickets").is_dir()
