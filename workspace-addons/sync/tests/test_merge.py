import json
import random
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from orch_sync.merge import merge_counter, merge_ticket, old_keys_of, renumber_key_clashes

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
VEC = json.loads((CONTRACTS / "vectors" / "ticket-merge-v1.json").read_text(encoding="utf-8"))
SCHEMA = Draft202012Validator(
    json.loads((CONTRACTS / "ticket.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
NOW = VEC["now"]
T1, T2, T3 = "2026-11-09T08:00:00Z", "2026-11-09T09:00:00Z", "2026-11-09T10:00:00Z"


def tk(**kw):
    t = {
        "schema": "orch.ticket/1",
        "id": "t_abc123",
        "key": "DM1-1",
        "title": "Invoice export",
        "status": "open",
        "created_at": T1,
        "updated_at": T1,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [],
        "revision": 1,
    }
    t.update(kw)
    return t


def up(t, at, **kw):
    t = deepcopy(t)
    t.update(kw)
    t["updated_at"] = at
    return t


def texts(t):
    return [h["text"] for h in t["history"]]


# ---- the shared vectors, both directions -------------------------------------------------------------------


@pytest.mark.parametrize("c", VEC["tickets"], ids=lambda c: c["name"])
def test_vector_ticket(c):
    before = deepcopy((c["base"], c["a"], c["b"]))
    assert merge_ticket(c["base"], c["a"], c["b"], NOW) == c["expect"]
    assert merge_ticket(c["base"], c["b"], c["a"], NOW) == c["expect"]  # symmetric: two machines converge
    assert (c["base"], c["a"], c["b"]) == before  # pure
    if c["expect"] is not None:
        assert list(SCHEMA.iter_errors(c["expect"])) == []


@pytest.mark.parametrize("c", VEC["counter"], ids=lambda c: c["name"])
def test_vector_counter(c):
    keys = c.get("keys", [])
    assert merge_counter(c["base"], c["a"], c["b"], keys) == c["expect"]
    assert merge_counter(c["base"], c["b"], c["a"], keys) == c["expect"]


@pytest.mark.parametrize("c", VEC["key_clash"], ids=lambda c: c["name"])
def test_vector_key_clash(c):
    before = deepcopy(c["tickets"])
    got = renumber_key_clashes(c["tickets"], c["counter"], NOW, c.get("held", ()))
    assert (got and {"changed": got[0], "counter": got[1]}) == (c["expect"] or None)
    assert c["tickets"] == before


def test_every_rule_has_a_vector():
    rules = {c["rule"] for c in VEC["tickets"]}
    assert {"2", "3", "4", "5", "6", "7", "8", "9", "10", "D8", "add"} <= rules


# ---- hand-written expectations (so the vectors are not only the code's own output) -------------------------


def test_scalar_loser_goes_to_history_and_newer_wins():
    base = tk()
    m = merge_ticket(base, up(base, T2, title="Export invoices"), up(base, T3, title="CSV export"), NOW)
    assert m["title"] == "CSV export"
    assert m["history"][-1] == {
        "at": NOW,
        "by": "agent:sync",
        "text": 'sync: title "Export invoices" was replaced',
        "lost": {"field": "title", "value": "Export invoices"},
    }


def test_one_sided_change_wins_without_history():
    base = tk()
    m = merge_ticket(base, up(base, T2, owner="Ann"), up(base, T3, due="2026-12-01"), NOW)
    assert (m["owner"], m["due"]) == ("Ann", "2026-12-01") and m["history"] == []


def test_final_status_beats_open_even_if_older_and_leaves_a_line():
    base = tk()
    m = merge_ticket(base, up(base, T2, status="done"), up(base, T3, status="active"), NOW)
    assert m["status"] == "done" and any("status" in x for x in texts(m))


def test_done_with_a_new_open_item_becomes_active():
    done_item = {"id": "c1", "text": "x", "done": True, "evidence": [{"type": "note", "ref": "ok"}]}
    base = tk(checklist=[done_item])
    new = {"id": "c2", "text": "y", "done": False, "evidence": []}
    m = merge_ticket(base, up(base, T2, status="done"), up(base, T3, checklist=[done_item, new]), NOW)
    assert m["status"] == "active" and any("reopened" in x for x in texts(m))


def test_checklist_clash_older_side_keeps_the_id_and_refs_follow():
    c = lambda t: {"id": "c1", "text": t, "done": False, "evidence": []}
    q = {
        "id": "q1",
        "text": "?",
        "options": [],
        "recommended": None,
        "answer": None,
        "answered_by": None,
        "via": None,
        "check": "c1",
    }
    base = tk()
    m = merge_ticket(
        base, up(base, T2, checklist=[c("old")]), up(base, T3, checklist=[c("new")], questions=[q]), NOW
    )
    assert [(x["id"], x["text"]) for x in m["checklist"]] == [("c1", "old"), ("c2", "new")]
    assert m["questions"][0]["check"] == "c2"


def test_done_needs_evidence_else_open():
    base = tk(checklist=[{"id": "c1", "text": "x", "done": False, "evidence": []}])
    a = up(base, T2, checklist=[{"id": "c1", "text": "x", "done": True, "evidence": []}])
    assert merge_ticket(base, a, up(base, T3, owner="A"), NOW)["checklist"][0]["done"] is False


def test_both_answers_newer_wins_other_kept_in_history():
    def q(ans, by):
        return {
            "id": "q1",
            "text": "?",
            "options": [],
            "recommended": None,
            "answer": ans,
            "answered_by": by,
            "via": "cli" if ans else None,
        }

    base = tk(questions=[q(None, None)])
    m = merge_ticket(
        base,
        up(base, T2, questions=[q("csv", "human:A")]),
        up(base, T3, questions=[q("xlsx", "human:B")]),
        NOW,
    )
    assert (
        m["questions"][0]["answer"] == "xlsx"
        and 'another answer "csv" by human:A was replaced' in texts(m)[-1]
    )


def test_history_and_evidence_never_lost():
    h = lambda at, t: {"at": at, "by": "human:A", "text": t}
    base = tk(history=[h(T1, "created")])
    m = merge_ticket(
        base,
        up(base, T2, history=base["history"] + [h(T3, "x")]),
        up(base, T3, history=base["history"] + [h(T2, "y")]),
        NOW,
    )
    assert texts(m) == ["created", "y", "x"]


def test_sessions_cap_keeps_newest():
    def s(i):
        return {"agent": "a", "id": f"s{i}", "host": f"h{i}", "last_used": f"2026-11-09T08:{i:02d}:00Z"}

    base = tk()
    m = merge_ticket(
        base,
        up(base, T2, sessions=[s(i) for i in range(20)]),
        up(base, T3, sessions=[s(i) for i in range(20, 40)]),
        NOW,
    )
    assert len(m["sessions"]) == 32 and m["sessions"][-1]["id"] == "s39" and m["sessions"][0]["id"] == "s8"


def test_sync_history_line_is_not_added_twice_even_with_a_later_now():
    base = tk()
    first = merge_ticket(base, up(base, T2, title="A"), up(base, T3, title="B"), NOW)
    again = merge_ticket(base, up(first, T3, title="A"), up(base, T3, title="B"), "2026-11-11T00:00:00Z")
    lines = [x for x in texts(again) if x.startswith("sync: title")]
    assert len(lines) == len(set(lines))


def test_clock_is_injected_only():
    base = tk()
    a, b = up(base, T2, title="A"), up(base, T3, title="B")
    assert merge_ticket(base, a, b, NOW) == merge_ticket(base, a, b, NOW)
    assert merge_ticket(base, a, b, "2030-01-01T00:00:00Z")["history"][-1]["at"] == "2030-01-01T00:00:00Z"


@pytest.mark.parametrize("bad", [None, [], "x", {"id": "t_other99"}])
def test_unmergeable_gives_none(bad):
    base = tk()
    assert merge_ticket(base, tk(), bad, NOW) is None or isinstance(bad, dict) and bad.get("id") == "t_abc123"


# ---- counter and key clash ----------------------------------------------------------------------------------


def test_counter_highest_wins_and_counts_old_keys():
    assert merge_counter({"last": 3}, {"last": 5}, {"last": 4})["last"] == 5
    assert merge_counter({"last": 3}, {"last": 3}, {"last": 3}, ["DM1-12", "junk"])["last"] == 12


def test_key_clash_keeps_old_key_resolvable_and_two_machines_agree():
    t1 = tk(id="t_aaa111", key="DM1-13", created_at=T1)
    t2 = tk(id="t_bbb222", key="DM1-13", created_at=T2)
    ch1, c1 = renumber_key_clashes({"t_aaa111": t1, "t_bbb222": t2}, {"last": 14}, NOW)
    ch2, c2 = renumber_key_clashes({"t_bbb222": t2, "t_aaa111": t1}, {"last": 14}, NOW)
    assert (ch1, c1) == (ch2, c2) and list(ch1) == ["t_bbb222"] and c1["last"] == 15
    new = ch1["t_bbb222"]
    assert (
        new["key"] == "DM1-15"
        and old_keys_of(new) == ["DM1-13"]
        and "DM1-13 to DM1-15" in new["history"][-1]["text"]
    )
    assert list(SCHEMA.iter_errors(new)) == []


# ---- property style: random three-way inputs ---------------------------------------------------------------


def _rand_side(rng, base, at):
    t = deepcopy(base)
    for _ in range(rng.randint(1, 4)):
        k = rng.choice(
            [
                "title",
                "status",
                "owner",
                "check",
                "uncheck",
                "q",
                "hist",
                "ref",
                "ext",
                "del",
                "created",
                "schema",
                "key",
            ]
        )
        if k == "title":
            t["title"] = rng.choice(["A", "B", "C"])
        elif k == "status":
            t["status"] = rng.choice(["open", "active", "waiting", "review", "dropped"])
        elif k == "owner":
            t["owner"] = rng.choice(["Ann", "Bob"])
        elif k == "check":
            n = rng.randint(1, 3)
            t["checklist"] = [c for c in t["checklist"] if c["id"] != f"c{n}"] + [
                {"id": f"c{n}", "text": rng.choice(["x", "y", "z"]), "done": False, "evidence": []}
            ]
        elif k == "uncheck" and t["checklist"]:
            t["checklist"].pop(rng.randrange(len(t["checklist"])))
        elif k == "q":
            n = rng.randint(1, 2)
            ans = rng.choice([None, "yes", "no"])
            t["questions"] = [x for x in t["questions"] if x["id"] != f"q{n}"] + [
                {
                    "id": f"q{n}",
                    "text": rng.choice(["p", "r"]),
                    "options": [],
                    "recommended": None,
                    "answer": ans,
                    "answered_by": "human:A" if ans else None,
                    "via": "cli" if ans else None,
                }
            ]
        elif k == "hist":
            t["history"].append(
                {
                    "at": f"2026-11-09T0{rng.randint(1, 9)}:00:00Z",
                    "by": "human:A",
                    "text": rng.choice(["m", "n", "o"]),
                }
            )
        elif k == "ref":
            t["refs"] = [
                {"kind": "web", "url": f"https://e.com/{rng.randint(1, 3)}", "at": T1, "by": "human:A"}
            ]
        elif k == "ext":
            t.setdefault("ext", {})["automation"] = {"cron": rng.choice(["a", "b"])}
        elif k == "created":
            t["created_at"] = rng.choice([T1, T2, T3])
        elif k == "schema":
            t["schema"] = rng.choice(["orch.ticket/1", "orch.ticket/2"])
        elif k == "key":
            t["key"] = rng.choice(["DM1-1", "DM1-2", "DM1-3"])
        elif k == "del" and t["refs"]:
            t["refs"] = []
    t["updated_at"] = at
    return t


@pytest.mark.parametrize("seed", range(150))
def test_property_symmetry_purity_and_no_loss(seed):
    rng = random.Random(seed)
    base = rng.choice([None, tk(checklist=[{"id": "c1", "text": "x", "done": False, "evidence": []}])])
    root = base or tk()
    a = _rand_side(rng, root, rng.choice([T1, T2, T3]))
    b = _rand_side(rng, root, rng.choice([T1, T2, T3]))
    before = deepcopy((base, a, b))
    m = merge_ticket(base, a, b, NOW)
    assert m == merge_ticket(base, b, a, NOW)
    assert json.dumps(m, sort_keys=True) == json.dumps(merge_ticket(base, b, a, NOW), sort_keys=True)
    assert (base, a, b) == before
    assert m["schema"] != "orch.ticket/1" or list(SCHEMA.iter_errors(m)) == []
    have = {(h["at"], h["by"], h["text"]) for h in m["history"]}
    for side in (a, b):  # history is never dropped
        assert {(h["at"], h["by"], h["text"]) for h in side["history"]} <= have
    one = merge_ticket(base, a, a, NOW)  # merging a side with itself changes nothing but the revision

    def norm(t):  # history and the order of added items come back in a fixed order
        return {
            k: (
                sorted(v, key=lambda x: json.dumps(x, sort_keys=True))
                if k in ("history", "checklist", "questions")
                else v
            )
            for k, v in t.items()
            if k != "revision"
        }

    assert norm(one) == norm(a)


def test_ext_sync_matches_its_contract_schema():
    schema = json.loads((CONTRACTS / "addons" / "sync" / "ext.schema.json").read_text(encoding="utf-8"))
    t1 = tk(id="t_aaa111", key="DM1-13", created_at=T1)
    t2 = tk(id="t_bbb222", key="DM1-13", created_at=T2)
    changed, _ = renumber_key_clashes({"t_aaa111": t1, "t_bbb222": t2}, {"last": 14}, NOW)
    assert list(Draft202012Validator(schema).iter_errors(changed["t_bbb222"]["ext"]["sync"])) == []
    assert list(Draft202012Validator(schema).iter_errors({"old_keys": ["dm1-1"]})) != []


# ---- review fixes (Opus review of #372) ---------------------------------------------------------------------


def _nest(n):
    d = {"leaf": 1}
    for _ in range(n):
        d = {"a": d}
    return d


def test_crafted_deep_ticket_returns_none_and_never_raises():
    base = tk()
    for deep in ({"ext": {"x": _nest(500)}}, {"ext": {"x": _nest(40)}}, {"note": _nest(5000)}):
        assert merge_ticket(base, up(base, T2, **deep), up(base, T3, owner="A"), NOW) is None
        assert merge_ticket(base, up(base, T3, owner="A"), up(base, T2, **deep), NOW) is None
        assert merge_ticket(base, up(base, T2, **deep), up(base, T3, owner="A"), NOW) is None
    assert merge_ticket(base, up(base, T2, ext={"x": _nest(20)}), up(base, T3, owner="A"), NOW) is not None
    assert renumber_key_clashes({"t_abc123": up(tk(), T1, ext=_nest(500))}, {"last": 1}, NOW) is None


def test_size_caps():
    base = tk()
    big = [{"at": T1, "by": "human:A", "text": f"n{i}"} for i in range(5001)]
    assert merge_ticket(base, up(base, T2, history=big), up(base, T3), NOW) is None
    assert merge_ticket(base, up(base, T2, note="x" * 2_100_000), up(base, T3), NOW) is None


def test_garbage_types_never_raise():
    base = tk()
    for bad in (
        {"checklist": [{"id": 1, "text": "x"}]},
        {"checklist": [{"text": "x"}]},
        {"refs": [[]]},
        {"questions": "no"},
        {"sessions": [{"agent": ["x"], "host": {}}, {"agent": ["x"], "host": {}}]},
        {"history": [{"at": 1}, {"at": "x"}]},
        {"ext": {"a": 5}},
        {"updated_at": 5},
    ):
        merge_ticket(base, up(base, T2, **bad), up(base, T3, owner="A"), NOW)  # must not raise


def test_loser_is_never_truncated():
    base = tk()
    long = "x" * 1900
    m = merge_ticket(base, up(base, T2, note=long), up(base, T3, note="short"), NOW)
    line = next(h for h in m["history"] if "lost" in h)
    assert line["lost"] == {"field": "note", "value": long} and len(line["text"]) < 260


def test_duplicate_ids_cannot_merge():
    base = tk()
    dup = [
        {"id": "c1", "text": "a", "done": False, "evidence": []},
        {"id": "c1", "text": "b", "done": False, "evidence": []},
    ]
    assert merge_ticket(base, up(base, T2, checklist=dup), up(base, T3), NOW) is None
    assert merge_ticket(base, up(base, T3), up(base, T2, checklist=dup), NOW) is None
    ref = {"kind": "web", "url": "https://e.com", "at": T1, "by": "human:A"}
    assert merge_ticket(base, up(base, T2, refs=[ref, ref]), up(base, T3), NOW) is None


def test_schema_and_created_at_follow_the_three_way_rule_in_both_orders():
    base = tk()
    a, b = up(base, T2, created_at=T2, schema="orch.ticket/2"), up(base, T3, created_at=T3)
    m = merge_ticket(base, a, b, NOW)
    assert m == merge_ticket(base, b, a, NOW) and m["created_at"] == T3 and m["schema"] == "orch.ticket/2"


def test_key_loser_goes_to_old_keys_and_text_conflicts_are_logged():
    base = tk()
    m = merge_ticket(base, up(base, T2, key="DM1-15"), up(base, T3, key="DM1-16"), NOW)
    assert m["key"] == "DM1-16" and old_keys_of(m) == ["DM1-15"]
    c = lambda t: {"id": "c1", "text": t, "done": False, "evidence": []}
    b2 = tk(checklist=[c("o")])
    m = merge_ticket(b2, up(b2, T2, checklist=[c("theirs")]), up(b2, T3, checklist=[c("mine")]), NOW)
    assert m["checklist"][0]["text"] == "mine"
    assert [h["lost"] for h in m["history"] if "lost" in h] == [{"field": "c1 text", "value": "theirs"}]


def test_key_clash_malformed_input_gives_none():
    ok = tk(id="t_aaa111", key="DM1-13")
    for bad in ({"key": [1]}, {"key": "x-1"}, {"ext": []}, {"created_at": 5}, {"ext": {"sync": []}}):
        assert (
            renumber_key_clashes(
                {"t_aaa111": ok, "t_bbb222": {**tk(id="t_bbb222", key="DM1-13"), **bad}}, {"last": 1}, NOW
            )
            is None
        )
    assert (
        renumber_key_clashes(
            {"t_aaa111": ok, "t_bbb222": tk(id="t_bbb222", key="DM1-13")}, {"last": 999_000_000}, NOW
        )
        is None
    )
    assert renumber_key_clashes("no", {}, NOW) is None


def test_backdating_cannot_steal_a_key_the_local_ticket_holds():
    mine = tk(id="t_bbb222", key="DM1-13", created_at=T2)
    theirs = tk(id="t_aaa111", key="DM1-13", created_at="2001-01-01T00:00:00Z")
    changed, _ = renumber_key_clashes(
        {"t_aaa111": theirs, "t_bbb222": mine}, {"last": 13}, NOW, held=["t_bbb222"]
    )
    assert list(changed) == ["t_aaa111"]


def test_question_answered_by_differs_only_is_symmetric():
    def q(by, via):
        return {
            "id": "q1",
            "text": "?",
            "options": [],
            "recommended": None,
            "answer": None,
            "answered_by": by,
            "via": via,
        }

    base = tk(questions=[q(None, None)])
    a, b = up(base, T2, questions=[q("human:A", "cli")]), up(base, T3, questions=[q("human:B", "web")])
    assert merge_ticket(base, a, b, NOW) == merge_ticket(base, b, a, NOW)


def test_counter_never_raises_on_garbage():
    assert merge_counter({"last": 3}, "x", [1], ["DM1-9"])["last"] == 9
    assert merge_counter({1: 1, "a": 2}, {"a": 3}, None)["last"] == 0
    assert merge_counter(_nest(500), {"last": 2}, None)["last"] == 2
    assert merge_counter({"last": True}, {"last": "9"}, {"last": [5]})["last"] == 0


def test_two_recorded_runs_of_the_same_command_are_both_kept():
    run = lambda at, code: {"type": "command", "ref": "pytest -q", "ran_at": at, "exit": code, "at": at}
    first, second = run("2026-11-09T10:00:00Z", 1), run("2026-11-09T11:00:00Z", 0)
    base = tk(checklist=[{"id": "c1", "text": "x", "done": False, "evidence": [first]}])
    ours = [{"id": "c1", "text": "x", "done": False, "evidence": [first, second]}]
    m = merge_ticket(base, up(base, T2, checklist=ours), up(base, T3), NOW)
    assert [e["exit"] for e in m["checklist"][0]["evidence"]] == [1, 0]


def test_hostile_ran_at_does_not_crash_and_runs_are_capped():
    def run(at, code, **kw):
        return {"type": "command", "ref": "pytest -q", "ran_at": at, "exit": code, "at": at, **kw}

    runs = [run(f"2026-11-09T10:00:0{i}Z", i) for i in range(8)]
    bad = [
        {"type": "command", "ref": ["x"], "ran_at": {"a": 1}},
        {"type": ["t"], "ref": "y", "ran_at": [1]},
        "junk",
    ]
    base = tk(checklist=[{"id": "c1", "text": "x", "done": False, "evidence": []}])
    a = [{"id": "c1", "text": "x", "done": False, "evidence": runs[:6] + bad}]
    b = [{"id": "c1", "text": "x", "done": False, "evidence": runs[3:] + bad}]
    m = merge_ticket(base, up(base, T2, checklist=a), up(base, T3, checklist=b), NOW)
    got = [e["exit"] for e in m["checklist"][0]["evidence"] if e.get("ref") == "pytest -q"]
    assert got == [3, 4, 5, 6, 7]  # newest five, both replicas end the same
    m2 = merge_ticket(base, up(base, T3, checklist=b), up(base, T2, checklist=a), NOW)
    assert [e.get("exit") for e in m2["checklist"][0]["evidence"]] == [
        e.get("exit") for e in m["checklist"][0]["evidence"]
    ]


def test_only_well_formed_runs_count_and_each_check_is_capped():
    base = tk(checklist=[{"id": "c1", "text": "x", "done": False, "evidence": []}])
    odd = [
        {"type": "command", "ref": "pytest", "ran_at": f"bad{i}", "at": f"2026-11-09T09:00:{i:02d}Z"}
        for i in range(8)
    ]
    runs = [
        {
            "type": "command",
            "ref": f"c{c}",
            "ran_at": f"2026-11-09T10:{c:02d}:{i:02d}Z",
            "at": f"2026-11-09T10:{c:02d}:{i:02d}Z",
        }
        for c in range(15)
        for i in range(5)
    ]
    side = [{"id": "c1", "text": "x", "done": False, "evidence": odd + runs}]
    m = merge_ticket(base, up(base, T2, checklist=side), up(base, T3), NOW)
    ev = m["checklist"][0]["evidence"]
    assert len(ev) == 50 and all(e in ev for e in odd)  # not-runs are never trimmed; the oldest runs go first


def test_core_and_merge_trim_runs_identically():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workspace" / "src"))
    from orch import tickets

    from orch_sync import merge

    def run(ref, at, **kw):
        return {"type": "command", "ref": ref, "ran_at": at, **kw}

    hostile = [
        run("a", "2026-99-99T99:00:00Z"),
        run("a", "2026-11-09T10:00:00Z\n"),
        run("a", 5),
        run(["x"], "2026-11-09T10:00:00Z"),
        {"type": "note", "ref": "n"},
        "junk",
    ]
    ties = [run(ref, "2026-11-09T10:00:00Z", exit=i) for i, ref in enumerate("abcdefgh" * 8)]
    many = [run("r", f"2026-11-09T11:00:{i:02d}Z", exit=i) for i in range(9)]
    notes = [{"type": "note", "ref": f"n{i}"} for i in range(55)]
    for case in (hostile + many, ties, ties + hostile + many, notes + many + ties, many[:3]):
        assert tickets.trim_runs(list(case)) == merge.trim_runs(list(case))
