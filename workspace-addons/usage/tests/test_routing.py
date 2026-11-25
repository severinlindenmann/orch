"""Stage 2: kinds of work on every rule, and the answer to the core's start question."""

import io
import json
from datetime import UTC, datetime

import pytest
from conftest import jrun, switcher_data

from orch_usage import acts, asking, page, routing, store, switching


# The core's own tests check the schema with jsonschema (workspace/tests/test_startask.py); this env has none, so the
# answer's shape is checked by hand against contracts/before-start.schema.json.
def _answer_ok(ans) -> bool:
    if ans.get("go") is True:
        return set(ans) <= {"go", "agent", "model", "account", "say"} and len(ans.get("say", "")) <= 200
    return set(ans) <= {"go", "why", "until"} and 0 < len(ans["why"]) <= 200


def _needs_ok(row) -> bool:
    keys = {"id", "source", "kind", "ticket", "title", "text", "tone", "since"}
    return set(row) == keys and row["id"].startswith("usage:") and row["kind"] == "usage:no-room"


def req(
    kind_ext=None, *, agent="main-tool", agents=("main-tool",), chosen_agent=False, ticket="t_aaaaaa", **kw
):
    return {
        "schema": "orch.before-start/1",
        "ticket": ticket,
        "key": "X-1",
        "title": "Some work",
        "parent": None,
        "manager": False,
        "chat": False,
        "ext": kind_ext or {},
        "by": "agent:automation",
        "mode": None,
        "agent": agent,
        "agents": list(agents),
        "model": None,
        "chosen": {"agent": chosen_agent, "model": False},
        **kw,
    }


def CREW(role):
    return {"factory": {"role": "crew", "order": "t_bbbbbb", "task": "x", "crew_role": role}}


# ---------------------------------------------------------------- kinds of work for a ticket


@pytest.mark.parametrize(
    "r, kind",
    [
        (req(manager=True), "lead"),
        (req(chat=True), "lead"),
        (req({"factory": {"role": "order", "stage": "run"}}), "lead"),
        (req(CREW("reviewer")), "reviews"),
        (req(CREW("checker")), "reviews"),
        (req(CREW("builder")), "code"),
        (req(CREW("release")), "builds"),
        (req(CREW("writer")), "helpers"),
        (req({"automation": {"script": "nightly"}}), "scripts"),
        (req({"automation": {"agent": "x"}}), "helpers"),
        (req(), "helpers"),
    ],
)
def test_kind_of_work_for_a_ticket(r, kind):
    assert routing.kind_of(r) == kind


# ---------------------------------------------------------------- `for` on every rule


def test_for_sets_kinds_with_history_and_shows_them(cli, fake_switcher, ws):
    code, d = jrun(cli, "for", "first", "lead", "Helpers", "--by", "human:owner")
    assert code == 0 and d["account"]["rule"]["for"] == ["lead", "helpers"]
    h = store.history(ws)[0]
    assert h["what"] == "for Lead, Helpers" and h["who"] == "human:owner"
    assert h["before"]["for"] == [] and h["after"]["for"] == ["lead", "helpers"]
    _c, out, _ = cli("list")
    assert "1. first (on, in use): no limit, for Lead, Helpers" in out
    code, d = jrun(cli, "for", "first", "any")
    assert d["account"]["rule"]["for"] == [] and store.history(ws)[0]["what"] == "for every kind of work"
    code, d = jrun(cli, "for", "first", "any")
    assert d["changed"] is False


@pytest.mark.parametrize("words", [["lunch"], ["any", "lead"]])
def test_for_refuses_unknown_words(cli, fake_switcher, ws, words):
    jrun(cli, "list")
    code, d = jrun(cli, "for", "first", *words)
    assert code == 2 and "kind" in d["error"] or "any" in d["error"]


def test_for_with_an_end_falls_back(cli, fake_switcher, ws):
    jrun(cli, "for", "first", "lead")
    code, d = jrun(cli, "for", "first", "reviews", "--end", "2999-01-01")
    assert code == 0 and d["account"]["rule"]["for"] == ["reviews"]
    acc = store.load(ws)["accounts"][0]
    assert acc["prev"]["for"] == ["lead"]


def test_page_act_for_and_page_model(cli, fake_switcher, ws):
    jrun(cli, "list")
    a = store.load(ws)["accounts"][0]
    assert acts.argv_for(ws, "for", f"{a['id']}:lead,reviews", "human:o") == [
        "for",
        a["id"],
        "lead",
        "reviews",
        "--by",
        "human:o",
    ]
    assert acts.argv_for(ws, "for", f"{a['id']}:any", None) == ["for", a["id"], "any"]
    for bad in (f"{a['id']}:lunch", f"{a['id']}:lead;rm", "x:lead"):
        with pytest.raises(store.Refused):
            acts.argv_for(ws, "for", bad, None)
    code, _out, _ = cli("act", "for", f"{a['id']}:code", "--by", "human:o")
    assert code == 0
    from orch_usage.cli import gather

    m = page.build(gather(ws), ws)
    assert m["accounts"][0]["for"] == ["code"]


# ---------------------------------------------------------------- the answer


def _owner_rules(cli):
    """17 Nov: the first subscription only, up to 100 % weekly, for Lead and Helpers; the others off."""
    jrun(cli, "list")
    jrun(cli, "for", "first", "lead", "helpers")
    jrun(cli, "limit", "first", "100%", "--period", "week")
    jrun(cli, "off", "second")
    jrun(cli, "off", "TEAMCO")


def test_owner_rules_helpers_use_the_first_subscription(cli, fake_switcher, ws):
    _owner_rules(cli)
    ans = routing.decide(ws, req())
    assert ans == {"go": True, "account": "first"} and _answer_ok(ans)


def test_a_kind_no_account_is_set_for_starts_as_usual(cli, fake_switcher, ws):
    _owner_rules(cli)
    assert routing.decide(ws, req(CREW("reviewer"))) == {"go": True}


def test_switches_to_the_first_account_with_room_for_the_kind(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")  # in use, 97 %: no room
    jrun(cli, "for", "second", "helpers")
    jrun(cli, "for", "TEAMCO", "reviews")
    jrun(cli, "switching", "on")
    calls = []
    ans = routing.decide(ws, req(), switch=_switch_to(fake_switcher, calls))
    assert (
        ans["go"] is True and ans["account"] == "second" and "Switched to second for Helpers." == ans["say"]
    )
    assert calls == [2] and _answer_ok(ans)
    assert store.history(ws)[0]["what"] == "switched to second"
    calls.clear()  # Reviews may use TEAMCO only
    ans = routing.decide(ws, req(CREW("reviewer")), switch=_switch_to(fake_switcher, calls))
    assert ans["account"] == "TEAMCO" and calls == [3]


def test_switching_off_only_says_it(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")
    ans = routing.decide(ws, req(), switch=lambda slot: pytest.fail("switched while switching is off"))
    assert ans["account"] == "second" and "switching is off" in ans["say"]


def test_no_room_waits_with_one_warning_and_one_needs_row(cli, fake_switcher, ws):
    fake_switcher.answer(switcher_data(first=(97.0, 80.0), second=(95.0, 78.0), third=(96.0, 44.0)))
    jrun(cli, "list")
    for acc in ("first", "second", "TEAMCO"):
        jrun(cli, "limit", acc, "90%", "--period", "5h")
    a1 = routing.decide(ws, req(ticket="t_aaaaaa"))
    a2 = routing.decide(ws, req(ticket="t_cccccc"))
    assert a1["go"] is False and _answer_ok(a1)
    assert a1["why"].startswith("No room for Helpers: first: 5 hours 97% of 90%")
    assert a1["until"] == "2026-11-16T19:29:59Z" and "Waits until" in a1["why"]
    warns = [h for h in store.history(ws) if h["what"] == "warning: work for Helpers waits"]
    assert len(warns) == 1 and a2["go"] is False
    (row,) = routing.needs_rows(ws)
    assert _needs_ok(row)
    assert row["id"] == "usage:no-room-helpers" and "2 tickets wait." in row["text"]
    jrun(cli, "limit", "TEAMCO", "100%", "--period", "5h")  # the owner raises a limit
    assert routing.decide(ws, req())["account"] == "TEAMCO"
    assert routing.needs_rows(ws) == []
    assert store.history(ws)[0]["what"] == "room again for Helpers"


def test_a_weekly_limit_reached_waits_for_the_weekly_reset(cli, fake_switcher, ws):
    # ORCH-307: the owner's 17 Nov rule (one subscription up to 100 % weekly) at its limit. The 5-hour window has
    # room and resets first; waking then would only hold the start again.
    fake_switcher.answer(switcher_data(first=(50.0, 100.0), second=(0.0, 10.0), third=(0.0, 10.0)))
    jrun(cli, "list")
    jrun(cli, "off", "second")
    jrun(cli, "off", "TEAMCO")
    ans = routing.decide(ws, req())
    assert ans["go"] is False and ans["until"] == "2026-11-18T19:59:59Z"
    assert ans["why"].startswith("No room for Helpers: first: week 100% of 100%")


def _tool_account(ws, tool="tool-x", kinds=("code",)):
    p = store.usage_dir(ws) / "accounts.json"
    data = json.loads(p.read_text())
    data["accounts"].append(
        {
            "id": "a_tool01",
            "label": "Second tool",
            "type": "helper-tool",
            "provider": "x",
            "tool": tool,
            "source": {"reader": "none"},
            "on": True,
            "order": 0,
            "rule": {"limits": [], "for": list(kinds), "ends": None},
            "prev": None,
        }
    )
    p.write_text(json.dumps(data))


def test_code_goes_to_a_helper_tool_when_it_is_set_up(cli, fake_switcher, ws):
    jrun(cli, "list")
    _tool_account(ws)
    ans = routing.decide(ws, req(CREW("builder"), agents=("main-tool", "tool-x")))
    assert ans == {"go": True, "account": "Second tool", "agent": "tool-x"} and _answer_ok(ans)
    # not installed here: Code falls back to the subscription
    assert routing.decide(ws, req(CREW("builder")))["account"] == "first"
    # a tool chosen for this start stays
    ans = routing.decide(ws, req(CREW("builder"), agents=("main-tool", "tool-x"), chosen_agent=True))
    assert "agent" not in ans and ans["account"] == "first"


def test_api_key_at_its_limit_is_skipped(cli, fake_switcher, ws, tmp_path):
    jrun(cli, "list")
    log = tmp_path / "spend.jsonl"
    log.write_text(json.dumps({"t": store.now(), "account": "main", "usd": 120}) + "\n")
    p = store.usage_dir(ws) / "accounts.json"
    data = json.loads(p.read_text())
    for acc in data["accounts"]:
        acc["rule"]["for"] = ["lead"]
    data["accounts"].append(
        {
            "id": "a_api001",
            "label": "API key 1",
            "type": "api-key",
            "provider": "anthropic-api",
            "tool": "tool-x",
            "source": {"reader": "spend-log", "path": str(log), "name": "main"},
            "on": True,
            "order": 0,
            "rule": {
                "limits": [{"value": 100, "unit": "$", "period": "month"}],
                "for": ["reviews"],
                "ends": None,
            },
            "prev": None,
        }
    )
    p.write_text(json.dumps(data))
    ans = routing.decide(ws, req(CREW("reviewer"), agents=("main-tool", "tool-x")), at=datetime.now(UTC))
    assert ans["go"] is False and "API key 1 reached $100 (month)" in ans["why"] and ans["until"]
    assert "spend" not in json.dumps(ans) and str(log) not in json.dumps(ans)


def test_cannot_read_use_never_blocks(cli, no_switcher, ws):
    p = store.usage_dir(ws)
    p.mkdir(parents=True)
    acc = {
        "id": "a_sub001",
        "label": "Only one",
        "type": "subscription",
        "provider": "anthropic",
        "source": {"reader": "cswap", "key": "c_1"},
        "on": True,
        "order": 1,
        "rule": {"limits": [{"value": 10, "unit": "%", "period": "week"}], "for": [], "ends": None},
        "prev": None,
    }
    (p / "accounts.json").write_text(json.dumps({"schema": store.SCHEMA, "accounts": [acc]}))
    assert routing.decide(ws, req()) == {"go": True, "account": "Only one"}


def test_before_start_command_reads_stdin_and_answers(cli, fake_switcher, ws, monkeypatch):
    _owner_rules(cli)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(req())))
    code, out, _ = cli("before-start", "--json")
    assert code == 0 and json.loads(out) == {"go": True, "account": "first"}
    monkeypatch.setattr("sys.stdin", io.StringIO("nope"))
    code, out, _ = cli("before-start", "--json")
    assert code == 2


def test_needs_command_is_a_list(cli, fake_switcher, ws):
    code, out, _ = cli("needs", "--json")
    assert code == 0 and json.loads(out) == []


def test_the_switcher_module_is_untouched_by_kinds(cli, fake_switcher, ws):
    """The background loop still judges every subscription that is on (kinds only steer starts)."""
    jrun(cli, "list")
    jrun(cli, "for", "first", "reviews")
    ch = switching.choose(store.load(ws)["accounts"], [], {}, 10)
    assert ch.target is None


def _credit(ws, *, tool=None, spent_log=None):
    """The owner's 17 Nov rule: the Codex / OpenAI credit, $100, first for Reviews and Code (added by hand)."""
    p = store.usage_dir(ws) / "accounts.json"
    data = json.loads(p.read_text())
    src = {"reader": "spend-log", "path": str(spent_log), "name": "oa"} if spent_log else {"reader": "none"}
    data["accounts"].append(
        {
            "id": "a_oacred",
            "label": "Codex / OpenAI credit",
            "type": "api-key",
            "provider": "openai",
            **({"tool": tool} if tool else {}),
            "source": src,
            "on": True,
            "order": 0,
            "rule": {
                "limits": [{"value": 100, "unit": "$", "period": "month"}],
                "for": ["reviews", "code"],
                "ends": None,
            },
            "prev": None,
        }
    )
    p.write_text(json.dumps(data))


def test_owner_credit_without_a_helper_tool_never_holds_a_start(cli, fake_switcher, ws):
    _owner_rules(cli)
    _credit(ws)
    assert store.load(ws)["accounts"][0]["label"] == "Codex / OpenAI credit"  # first in order
    assert routing.decide(ws, req(CREW("reviewer"))) == {"go": True}  # Reviews helpers start as usual
    assert routing.decide(ws, req(CREW("builder"))) == {"go": True}  # Code too, until Codex helpers ship
    assert routing.decide(ws, req())["account"] == "first"  # Helpers keep the subscription


def test_owner_credit_runs_code_once_its_tool_is_here_and_stops_at_100(cli, fake_switcher, ws, tmp_path):
    _owner_rules(cli)
    log = tmp_path / "oa.jsonl"
    log.write_text(json.dumps({"t": store.now(), "account": "oa", "usd": 12}) + "\n")
    _credit(ws, tool="tool-x", spent_log=log)
    here = ("main-tool", "tool-x")
    ans = routing.decide(ws, req(CREW("builder"), agents=here))
    assert ans == {"go": True, "account": "Codex / OpenAI credit", "agent": "tool-x"}
    log.write_text(json.dumps({"t": store.now(), "account": "oa", "usd": 100}) + "\n")
    ans = routing.decide(ws, req(CREW("builder"), agents=here))
    assert ans["go"] is False and "Codex / OpenAI credit reached $100 (month)" in ans["why"]


# ---------------------------------------------------------------- outside review of the merge (guards, left, credit)


def _switch_to(fake_switcher, calls):
    """A switch that really moves the account in use (as the switcher reads it afterwards)."""

    def go(slot):
        calls.append(slot)
        fake_switcher.answer(switcher_data(active=slot))
        return True

    return go


def test_a_start_switches_under_the_computer_switch_lock_and_notes_it(cli, fake_switcher, ws):
    from orch_usage import computer

    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")
    jrun(cli, "switching", "on")
    calls = []
    ans = routing.decide(ws, req(), switch=_switch_to(fake_switcher, calls))
    assert ans["say"] == "Switched to second for Helpers." and calls == [2]
    shared = computer.shared_dir(ws)
    assert shared is not None and computer.last_switch(shared)["to"] == "second"  # the computer's switch line
    memory = switching._read(switching.memory_path(ws))
    assert (
        memory["mine"]["to"] == store.find(store.load(ws)["accounts"], "second")["id"]
    )  # not "another program"


def test_a_switch_the_switcher_did_not_keep_is_a_failure(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")
    jrun(cli, "switching", "on")
    ans = routing.decide(ws, req(), switch=lambda slot: True)  # exit 0, but the account in use did not change
    assert ans["go"] is True and ans["say"] == "Could not switch to second; the account in use stays."
    assert not any(r["what"] == "switched to second" for r in store.history(ws))


def test_a_follower_workspace_never_switches_before_a_start(cli, fake_switcher, ws, tmp_path):
    from orch_usage import computer

    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")
    jrun(cli, "switching", "on")
    other = tmp_path / "fernscout"
    (other / ".orch" / "tickets").mkdir(parents=True)
    owner = computer.Switcher(other, computer.shared_dir(other))
    try:
        assert owner.hold() is True  # the other workspace's Usage loop switches the accounts
        ans = routing.decide(ws, req(), switch=lambda slot: pytest.fail("a follower switched"))
    finally:
        owner.release()
    assert ans["go"] is True and ans["account"] == "second"
    assert "switches the accounts, so the account in use stays" in ans["say"]


def test_a_start_does_not_switch_while_usage_waits_for_the_outside_switch_answer(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "limit", "first", "95%", "--period", "5h")
    jrun(cli, "switching", "on")
    memory = switching._read(switching.memory_path(ws))
    memory["hold"] = {"account": "x", "label": "first", "answers": switching.answers(ws), "since": "now"}
    switching._write(switching.memory_path(ws), memory)
    assert switching.held(ws)
    ans = routing.decide(ws, req(), switch=lambda slot: pytest.fail("switched during the hold"))
    assert ans["go"] is True and "waits for your answer" in ans["say"]


def _tool_credit(cli, ws, left_amount):
    code, d = jrun(cli, "add", "Tool credit", "--provider", "openai", "--name", "tc", "--left", left_amount)
    assert code == 0, d
    p = store.usage_dir(ws) / "accounts.json"
    data = json.loads(p.read_text())
    for a in data["accounts"]:
        if a["label"] == "Tool credit":
            a.update(tool="tool-x", order=0)
            a["rule"]["for"] = ["code"]
    p.write_text(json.dumps(data))
    return store.find(store.load(ws)["accounts"], "Tool credit")


def test_a_helper_tool_credit_with_nothing_left_gets_no_start(cli, fake_switcher, ws):
    from orch_usage import left

    jrun(cli, "list")
    a = _tool_credit(cli, ws, "$5")
    here = ("main-tool", "tool-x")
    assert routing.decide(ws, req(CREW("builder"), agents=here))["account"] == "Tool credit"
    left.record(ws, a, 5, "agent:x")  # all of it spent: the same rule as `orch usage ask`
    ans = routing.decide(ws, req(CREW("builder"), agents=here))
    assert ans.get("account") != "Tool credit" and ans.get("agent") != "tool-x"
    assert asking.stopped(ws, store.find(store.load(ws)["accounts"], "Tool credit"), datetime.now(UTC))
    jrun(cli, "for", "first", "lead")  # nothing else may do Code: it waits, in plain words
    jrun(cli, "for", "second", "lead")
    jrun(cli, "for", "TEAMCO", "lead")
    ans = routing.decide(ws, req(CREW("builder"), agents=here))
    assert ans["go"] is False and "Tool credit has nothing left" in ans["why"] and _answer_ok(ans)


@pytest.mark.parametrize("how", ["removed", "ended", "spent"])
def test_a_start_on_an_api_key_is_refused_only_when_its_credit_is_closed(cli, fake_switcher, ws, how):
    from orch_usage import left

    jrun(cli, "list")
    a = _tool_credit(cli, ws, "$5")
    key_start = req(CREW("builder"), credit={"account": "Tool credit"})
    assert routing.decide(ws, key_start) == {"go": True, "account": "Tool credit"}
    if how == "spent":
        left.record(ws, a, 5, "agent:x")
    else:
        p = store.usage_dir(ws) / "accounts.json"
        data = json.loads(p.read_text())
        for x in data["accounts"]:
            if x["label"] == "Tool credit":
                if how == "removed":
                    x["removed"] = True
                else:
                    x["credit_ends"] = "2026-01-01T00:00:00Z"
        p.write_text(json.dumps(data))
    ans = routing.decide(ws, key_start, switch=lambda slot: pytest.fail("a key start switched"))
    assert ans["go"] is False and "Tool credit" in ans["why"] and "until" not in ans and _answer_ok(ans)
    assert routing.held(ws) == {}  # a refusal, not a hold
    assert routing.decide(ws, req(credit={"account": "Not listed"})) == {"go": True}


def test_the_stored_pace_counts_before_a_start_and_never_crashes(cli, fake_switcher, ws):
    """#2740: the loop keeps {"per_minute", "at"} per window; the before-start answers got that dict as the number."""
    jrun(cli, "list")
    jrun(cli, "off", "first")
    jrun(cli, "off", "second")  # only TEAMCO is left: 23 % of 5 hours, not in use
    at = datetime.now(UTC).replace(microsecond=0)
    stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    switching._write(switching.memory_path(ws), {"pace": {"5h": {"per_minute": 10.0, "at": stamp}}})
    for ans in (routing.decide(ws, req(), at=at), asking.ask(ws, "helpers", at=at)):
        assert ans["go"] is False and "at this pace" in ans["why"]
    old = "2026-01-01T00:00:00Z"  # a pace older than the loop keeps it: forgotten
    switching._write(switching.memory_path(ws), {"pace": {"5h": {"per_minute": 10.0, "at": old}}})
    assert routing.decide(ws, req(), at=at)["go"] is True
