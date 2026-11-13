import json
import os
import subprocess

from conftest import CONTRACTS

from orch_factory import authority
from orch_factory.store import Store


def core(ws, *args):
    result = subprocess.run(
        [os.environ["ORCH_BIN"], *args, "--json"], cwd=ws, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def edit(ws, tid, fn):
    path = ws / "fake-tickets" / f"{tid}.json"
    t = json.loads(path.read_text())
    fn(t)
    path.write_text(json.dumps(t))


def run_proposal(**changes):
    p = json.loads((CONTRACTS / "examples/factory-proposal/valid-run.json").read_text())
    p["line"] = [
        {"stage": "build", "stop": True, "why": "You judge the look."},
        {"stage": "ship", "stop": True, "why": "You decide whether it goes live."},
    ]
    p["tasks"] = [
        {"slug": "booking-form", "title": "Booking form", "role": "builder", "stage": "build", "proves": [0]},
        {"slug": "release", "title": "Prepare the release", "role": "builder", "stage": "ship"},
    ]
    p.update(changes)
    return json.dumps(p).encode()


def stop_file(stage, *items):
    items = items or ({"title": "Button colour", "tag": "taste"},)
    return json.dumps(
        {"schema": "orch.factory.proposal/1", "kind": "stop", "stage": stage, "items": list(items)}
    ).encode()


def autopilot_file(**limits):
    return json.dumps(
        {
            "schema": "orch.factory.proposal/1",
            "kind": "autopilot",
            "title": "Keep improving",
            "goal": "Small routine fixes while I am away.",
            "may_decide": limits.pop("may", ["routine", "taste"]),
            "limits": {"days": 3, "max_orders": 2, "active_min_per_day": 60, **limits},
            "done_means": ["Nothing big changes."],
        }
    ).encode()


def started(ws, run, data=None, by="human:anna"):
    order = run("idea", "Booking page")["order"]
    q = run("propose", order, "--file", "-", data=data or run_proposal())["question"]
    core(ws, "answer", order, q, "Start", "--by", by)
    return order, q


def finish_crew(ws, run, order, task):
    tid = run("crew", "add", order, task)["ticket"]
    edit(ws, tid, lambda t: t.update(status="done"))
    return tid


def ask_stop(ws, run, order, stage, *items):
    return run("stop", order, "--file", "-", data=stop_file(stage, *items))["question"]


def autopilot_order(ws, run, by="human:anna", **limits):
    a = run("idea", "Autopilot")["order"]
    q = run("autopilot", a, "--file", "-", data=autopilot_file(**limits))["question"]
    core(ws, "answer", a, q, "Start", "--by", by)
    return a, q


def waiting_stop(ws, run, *items, stage="build"):
    order, _ = started(ws, run)
    assert run("next", order)["step"] == "start-crew"
    finish_crew(ws, run, order, "booking-form")
    return order, ask_stop(ws, run, order, stage, *items)


def test_happy_path(ws, run):
    order, _ = started(ws, run)
    first = run("next", order)
    assert first["step"] == "start-crew" and first["stage"] == "build"
    assert [t["slug"] for t in first["tasks"]] == ["booking-form"]
    tid = run("crew", "add", order, "booking-form")["ticket"]
    run("crew", "start", order, "booking-form")
    assert json.loads((ws / "runs.jsonl").read_text()) == {
        "ticket": tid,
        "agent": "codex",
        "by": "agent:factory",
    }
    ext = core(ws, "ticket", "show", tid)["ext"]["factory"]
    assert ext == {
        "role": "crew",
        "order": order,
        "task": "booking-form",
        "crew_role": "builder",
        "agent": "codex",
    }
    assert core(ws, "ticket", "show", tid)["parent"] == order
    edit(ws, tid, lambda t: t.update(status="done"))
    assert run("next", order)["step"] == "stop"
    q = ask_stop(ws, run, order, "build")
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["stage"] == "waiting"
    assert run("next", order)["step"] == "wait"
    core(ws, "answer", order, q, "Continue", "--by", "human:anna")
    nxt = run("next", order)
    assert nxt["step"] == "start-crew" and nxt["stage"] == "ship"
    finish_crew(ws, run, order, "release")
    assert run("next", order)["step"] == "stop"
    q = ask_stop(ws, run, order, "ship")
    assert core(ws, "ticket", "show", order)["questions"][-1]["options"] == ["Ship it", "Send back"]
    core(ws, "answer", order, q, "Ship it", "--by", "human:anna")
    shipping = run("next", order)
    assert shipping["step"] == "ship" and "Merges" in shipping["does"]
    run("ship", order)
    assert run("next", order)["step"] == "done"
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["stage"] == "shipped"
    types = [r["type"] for r in Store(ws).journal_read()]
    assert types.count("shipped") == 1 and types.count("started") == 1


def test_not_started_states(ws, run, proposal):
    order = run("idea", "Booking")["order"]
    assert run("next", order)["step"] == "wait"
    q = run("propose", order, "--file", "-", data=proposal)["question"]
    assert run("next", order)["step"] == "wait"
    core(ws, "answer", order, q, "Edit", "--by", "human:anna")
    assert run("next", order)["step"] == "edit"
    new = run("propose", order, "--file", "-", data=proposal + b"\n")["question"]
    assert run("next", order)["step"] == "wait"
    core(ws, "answer", order, new, "Not now", "--by", "human:anna")
    assert run("next", order)["step"] == "parked"


def test_answers_are_consumed_once(ws, run):
    order, q = started(ws, run)
    a = run("next", order)
    b = run("next", order)
    assert a == b
    rows = [r for r in Store(ws).journal_read() if r["type"] in ("consumed", "started")]
    assert [r["type"] for r in rows] == ["consumed", "started"] and rows[0]["q"] == q


def test_agent_start_is_ignored(ws, run, proposal):
    order, _ = started(ws, run, by="agent:worker")
    assert run("next", order)["step"] == "wait"
    assert run("next", order)["step"] == "wait"
    assert not [r for r in Store(ws).journal_read() if r["type"] in ("consumed", "started")]
    log = [
        h["text"]
        for h in core(ws, "ticket", "show", order)["history"]
        if "ignored the agent answer" in h["text"]
    ]
    assert len(log) == 1
    run("crew", "add", order, "booking-form", code=2)


def test_crew_add_is_idempotent_and_limited(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    one = run("crew", "add", order, "booking-form")
    two = run("crew", "add", order, "booking-form")
    assert one["ticket"] == two["ticket"] and one["created"] and not two["created"]
    subs = [t for t in core(ws, "ticket", "list", "--all") if t.get("parent") == order]
    assert len(subs) == 1
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["crew"] == [one["ticket"]]
    assert run("crew", "add", order, "not-approved", code=2)["code"] == "not_allowed"


def test_crew_start_refusals(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    run("crew", "add", order, "booking-form")
    run("crew", "add", order, "release")
    assert run("crew", "start", order, "release", code=2)["code"] == "not_allowed"  # not the current stage
    edit(ws, order, lambda t: t["ext"]["factory"]["budget"].update(active_min_used=150))
    refused = run("crew", "start", order, "booking-form", code=2)
    assert refused["code"] == "refused" and "more time" in refused["error"]
    assert not (ws / "runs.jsonl").exists()


def test_crew_start_before_start_refused(ws, run, proposal):
    order = run("idea", "Booking")["order"]
    run("propose", order, "--file", "-", data=proposal)
    assert run("crew", "start", order, "booking-form", code=2)["code"] == "not_allowed"


def change_file(**changes):
    c = {
        "schema": "orch.factory.proposal/1",
        "kind": "change",
        "title": "Add a waiting list",
        "what": "Customers can join a waiting list.",
        "adds_min": 25,
        "adds_usd": 2,
        "lands_in": "build",
        "adds_tasks": [{"slug": "waitlist", "title": "Waiting list", "role": "builder", "stage": "build"}],
    }
    c.update(changes)
    return json.dumps(c).encode()


def test_change_refused_before_start(ws, run, proposal):
    order = run("idea", "Booking")["order"]
    run("propose", order, "--file", "-", data=proposal)
    assert run("change", order, "--file", "-", data=change_file(), code=2)["code"] == "not_allowed"
    assert run("tiny", order, "--minutes", "3", "--what", "x", code=2)["code"] == "not_allowed"


def test_change_accepted_adds_tasks(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    c = run("change", order, "--file", "-", data=change_file())
    assert run("change", order, "--file", "-", data=change_file())["question"] == c["question"]
    q = core(ws, "ticket", "show", order)["questions"][-1]
    assert q["kind"] == "factory:change" and q["options"] == ["Accept", "Edit", "Save for later"]
    assert q["text"].startswith("Add 'Add a waiting list'? +25 min · +$2 · lands in build")
    assert run("next", order)["step"] == "wait"
    run("crew", "add", order, "waitlist", code=2)
    core(ws, "answer", order, c["question"], "Accept", "--by", "human:anna")
    step = run("next", order)
    assert step["step"] == "start-crew" and {t["slug"] for t in step["tasks"]} == {"booking-form", "waitlist"}
    assert run("crew", "add", order, "waitlist")["created"]
    assert [r["type"] for r in Store(ws).journal_read()].count("change-accepted") == 1
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["budget"]["active_min_cap"] == 175


def test_change_cannot_use_new_role(ws, run):
    order, _ = started(ws, run)
    bad = change_file(adds_tasks=[{"slug": "x", "title": "X", "role": "designer", "stage": "build"}])
    assert run("change", order, "--file", "-", data=bad, code=2)["code"] == "not_allowed"


def test_tiny_caps(ws, run):
    order, _ = started(ws, run)
    for i in range(3):
        assert run("tiny", order, "--minutes", "5", "--what", f"Tweak {i}")["count"] == i + 1
    refused = run("tiny", order, "--minutes", "5", "--what", "Fourth", code=2)
    assert refused["code"] == "refused" and "change proposal" in refused["error"]
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["tiny"] == {"count": 3, "minutes": 15}
    other, _ = started(ws, run)
    refused = run("tiny", other, "--minutes", "31", "--what", "Big", code=2)
    assert refused["code"] == "refused" and "change proposal" in refused["error"]
    assert run("tiny", other, "--minutes", "30", "--what", "Edge")["minutes"] == 30


def test_stop_rules(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    taste = {"title": "Colour", "tag": "taste", "recommend": "Continue"}
    assert run("stop", order, "--file", "-", data=stop_file("build", taste), code=2)["code"] == "not_allowed"
    assert run("stop", order, "--file", "-", data=stop_file("ship"), code=2)["code"] == "not_allowed"
    routine = {"title": "Typo", "tag": "routine", "recommend": "Continue"}
    q = run("stop", order, "--file", "-", data=stop_file("build", routine))
    other = stop_file("build", {"title": "Other", "tag": "routine"})
    assert run("stop", order, "--file", "-", data=other, code=2)["code"] == "conflict"
    assert run("stop", order, "--file", "-", data=stop_file("build", routine))["question"] == q["question"]


def test_send_back(ws, run):
    order, q = waiting_stop(ws, run)
    core(ws, "answer", order, q, "Send back", "--by", "human:anna")
    step = run("next", order)
    assert step["step"] == "work" and step["comments"] == ["Button colour"]
    assert run("next", order) == step
    q2 = ask_stop(ws, run, order, "build", {"title": "New colour", "tag": "taste"})
    assert q2 != q and run("next", order)["step"] == "wait"


def test_agent_answer_to_stop_is_ignored(ws, run):
    order, q = waiting_stop(ws, run)
    core(ws, "answer", order, q, "Continue", "--by", "agent:worker")
    assert run("next", order)["step"] == "wait"
    assert run("ship", order, code=2)["code"] == "not_allowed"


# ---- autopilot ----------------------------------------------------------------------------------------


def test_decide_needs_a_grant(ws, run):
    order, q = waiting_stop(ws, run)
    refused = run("decide", order, q, "--answer", "Continue", "--why", "Fine", code=2)
    assert refused["code"] == "not_allowed"
    autopilot_order(ws, run, by="agent:worker")  # an agent cannot press Start on an autopilot
    assert run("decide", order, q, "--answer", "Continue", "--why", "Fine", code=2)["code"] == "not_allowed"
    assert run("next", order)["step"] == "wait"


def test_decide_under_a_human_grant(ws, run):
    a, _ = autopilot_order(ws, run)
    assert run("next", a)["step"] == "resume"
    assert core(ws, "ticket", "show", a)["ext"]["factory"]["kind"] == "autopilot"
    order, q = waiting_stop(
        ws, run, {"title": "Wording", "tag": "routine"}, {"title": "Colour", "tag": "taste"}
    )
    done = run("decide", order, q, "--answer", "Continue", "--why", "Same as the house rule", code=0)
    assert done["by"] == "agent:factory"
    t = core(ws, "ticket", "show", order)
    assert next(x for x in t["questions"] if x["id"] == q)["answer"] is None  # a person never answered
    assert any(h["text"] == "Decided by agent:factory · Same as the house rule" for h in t["history"])
    assert (
        run("decide", order, q, "--answer", "Continue", "--why", "Same as the house rule")["answer"]
        == "Continue"
    )
    step = run("next", order)
    assert step["step"] == "start-crew" and step["stage"] == "ship"
    rows = Store(ws).journal_read()
    assert [r["by"] for r in rows if r["type"] == "decided"] == ["agent:factory"]
    assert [r["by"] for r in rows if r["type"] == "stop-answered"] == ["agent:factory"]
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["line"][0]["by"] == "agent:factory"
    notice = run("view")["notice"]
    assert "Autopilot is on" in notice and "decided today: 1" in notice


def test_decide_refusals(ws, run):
    autopilot_order(ws, run, may=["routine"])
    order, q = waiting_stop(ws, run, {"title": "Colour", "tag": "taste"})
    assert run("decide", order, q, "--answer", "Continue", "--why", "x", code=2)["code"] == "not_allowed"
    cant, q2 = waiting_stop(ws, run, {"title": "Delete data", "tag": "cant-undo"})
    assert run("decide", cant, q2, "--answer", "Continue", "--why", "x", code=2)["code"] == "not_allowed"
    ok, q3 = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    assert run("decide", ok, q3, "--answer", "Maybe", "--why", "x", code=2)["code"] == "not_allowed"
    run("decide", ok, q3, "--answer", "Continue", "--why", "x")


def test_decide_never_on_ship_stop(ws, run):
    autopilot_order(ws, run)
    order, q = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    core(ws, "answer", order, q, "Continue", "--by", "human:anna")
    run("next", order)
    finish_crew(ws, run, order, "release")
    ship_q = ask_stop(ws, run, order, "ship", {"title": "Typo", "tag": "routine"})
    refused = run("decide", order, ship_q, "--answer", "Ship it", "--why", "x", code=2)
    assert refused["code"] == "not_allowed"


def test_decide_unstarted_or_other_question_refused(ws, run, proposal):
    a, _ = autopilot_order(ws, run)
    order = run("idea", "Other")["order"]
    start = run("propose", order, "--file", "-", data=proposal)["question"]
    assert run("decide", order, start, "--answer", "Start", "--why", "x", code=2)["code"] == "not_allowed"
    assert run("decide", a, "q1", "--answer", "Start", "--why", "x", code=2)["code"] == "not_allowed"


def test_grant_expires(ws, run):
    a, _ = autopilot_order(ws, run)
    order, q = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    run("decide", order, q, "--answer", "Continue", "--why", "ok")
    assert run("next", order)["step"] == "start-crew"
    old = "2000-01-01T00:00:00Z"
    edit(ws, a, lambda t: [h.update(at=old) for h in t["history"] if h["text"].startswith("Answered")])
    # The decision is checked again at read time: with the grant over, the stop is open again.
    assert run("next", order)["step"] == "wait"
    order2, q2 = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    assert run("decide", order2, q2, "--answer", "Continue", "--why", "x", code=2)["code"] == "not_allowed"
    assert run("next", a)["step"] == "done"


def test_grant_without_timestamp_gives_nothing(ws, run):
    a, _ = autopilot_order(ws, run)
    edit(ws, a, lambda t: t.update(history=[]))
    order, q = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    assert run("decide", order, q, "--answer", "Continue", "--why", "x", code=2)["code"] == "not_allowed"


def test_grant_max_orders(ws, run):
    autopilot_order(ws, run, max_orders=1)
    one, q1 = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    two, q2 = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    run("decide", one, q1, "--answer", "Continue", "--why", "x")
    assert run("decide", two, q2, "--answer", "Continue", "--why", "x", code=2)["code"] == "not_allowed"


def test_forged_decided_line_has_no_effect(ws, run):
    order, q = waiting_stop(ws, run, {"title": "Typo", "tag": "routine"})
    store = Store(ws)
    with store.locked():
        store.journal_append(
            {
                "type": "decided",
                "order": order,
                "q": q,
                "answer": "Continue",
                "by": "agent:factory",
                "why": "forged",
            }
        )
    assert run("next", order)["step"] == "wait"


def test_reconcile_reports(ws, run):
    order, _ = started(ws, run)
    out = run("reconcile")["orders"][0]
    assert out["order"] == order and len(out["unconsumed"]) == 1
    assert "cached stage" in out["problems"][0]
    run("next", order)
    out = run("reconcile")["orders"][0]
    assert out["unconsumed"] == [] and len(out["consumed"]) == 1 and out["problems"] == []


# ---- question text ------------------------------------------------------------------------------------


def test_start_text_shows_what_matters(ws, run):
    p = json.loads(run_proposal())
    p["handovers"] = [{"task": "photos", "workspace": "design", "why": "They own the brand."}]
    p["budget"]["active_min_cap"] = 150
    order, _ = started(ws, run, data=json.dumps(p).encode())
    text = core(ws, "ticket", "show", order)["questions"][0]["text"]
    for part in (
        "Stops: build, ship",
        "Crew: manager claude, builder codex, reviewer claude",
        "Cap: 2 h 30 min active",
        "Ship: Merges the reviewed page into develop. (undo: A revert task.)",
        "Handover: photos → design",
        "Unsure: Bookings go to Anna's calendar",
    ):
        assert part in text, part
    assert text.endswith("(Proposal 1)") and ".." not in text


def test_agent_strings_are_cleaned(ws, run):
    p = json.loads(run_proposal())
    p["title"] = "Booking\n“page”\x00" + chr(0x202E) + "  now"
    p["goal"] = "x" * 200
    order, _ = started(ws, run, data=json.dumps(p).encode())
    text = core(ws, "ticket", "show", order)["questions"][0]["text"]
    assert "Start 'Booking 'page' now'?" in text
    assert "\n" not in text and "\x00" not in text and chr(0x202E) not in text and "“" not in text
    assert "Goal: " + "x" * 119 + "…" in text


def test_authority_accepts_own_text_and_refuses_edits(ws, run):
    order, _ = started(ws, run)
    assert authority.started(order, ws)
    edit(ws, order, lambda t: t["questions"][0].update(text=t["questions"][0]["text"] + " (free)"))
    assert run("show", order, code=2)["code"] == "tampered"


def test_stop_change_autopilot_texts(ws, run):
    a, _ = autopilot_order(ws, run, api_usd_per_day=5)
    text = core(ws, "ticket", "show", a)["questions"][0]["text"]
    assert (
        "May decide: routine, taste · 3 days · up to 2 orders · target 60 min active per day, $5 per day (not enforced yet)"
        in text
    )
    assert "Always asks you: ship, scope, budget, new connections, can't-undo, other workspaces." in text
    order, q = waiting_stop(ws, run, {"title": "Hero\nimage “v2”", "tag": "taste"})
    stop_text = next(x for x in core(ws, "ticket", "show", order)["questions"] if x["id"] == q)["text"]
    assert "Hero image 'v2' [taste]" in stop_text and stop_text.endswith("(Stop 1)")
    edit(ws, order, lambda t: t["questions"][-1].update(options=["Continue", "Send back", "Ship it"]))
    assert run("next", order, code=2)["code"] == "tampered"


def test_clock_moves_only_forward(monkeypatch):
    """An agent setting FACTORY_NOW to the past cannot revive an expired grant."""
    from datetime import UTC, datetime, timedelta

    from orch_factory.store import clock

    monkeypatch.setenv("FACTORY_NOW", "2020-01-01T00:00:00+00:00")
    assert clock() > datetime(2025, 1, 1, tzinfo=UTC)
    later = datetime.now(UTC) + timedelta(days=30)
    monkeypatch.setenv("FACTORY_NOW", later.isoformat())
    assert clock() == later
    monkeypatch.setenv("FACTORY_NOW", "not a time")
    assert clock() <= datetime.now(UTC)


def test_first_orders_counts_in_journal_order_inside_the_grant():
    from datetime import UTC, datetime, timedelta

    from orch_factory.autopilot import first_orders

    start = datetime(2026, 11, 13, 12, tzinfo=UTC)
    grant = {"from": start, "until": start + timedelta(days=1), "limits": {"max_orders": 2}}
    at = lambda h: (start + timedelta(hours=h)).isoformat()
    rows = [
        {"order": "t_before", "at": (start - timedelta(hours=1)).isoformat()},
        {"order": "t_a", "at": at(1)},
        {"order": "t_a", "at": at(2)},
        {"order": "t_b", "at": at(3)},
        {"order": "t_c", "at": at(4)},
    ]
    assert first_orders(grant, rows) == ["t_a", "t_b"]
