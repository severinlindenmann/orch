import hashlib
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


def vmac(ticket, step, nonce):
    on = bool(step.get("wont_do"))  # an "on" record binds the step's text and covers; an undo record does not
    parts = [
        ticket,
        str(step["id"]),
        str(nonce),
        str(step["text"] if on else ""),
        str((step.get("covers") or "") if on else ""),
        str(on),
        str((step.get("reason") if on else "") or ""),
    ]
    return "v1-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def person_for(ledger):
    """The vectors' stand-in for the receiving core (humanproof.wont_verifier): a MAC valid for the step's text and
    covers AND the CURRENT ledger entry."""

    def person(step, ticket):
        m = step.get("wont_mac")
        ok = m == ledger.get(f"{ticket}:{step.get('id')}") and m == vmac(ticket, step, step.get("wont_nonce"))
        return isinstance(m, str) and ok

    return person


def verdict_for(ledger, own):
    """The vectors' stand-in for the receiving core (humanproof.verdict_verifier): "current" = the entry's MAC
    is the ledger's current one, "stale" = it is one of the core's own MACs but not current, else None."""

    def verdict(entry, ticket):
        m = entry.get("mac")
        if ledger.get(ticket["id"]) == m:
            return "current"
        return "stale" if m in own else None

    return verdict


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
    person = person_for(c.get("ledger", {}))
    verdict = verdict_for(c.get("ledger", {}), c.get("own", []))
    assert merge_ticket(c["base"], c["a"], c["b"], NOW, person, verdict) == c["expect"]
    assert merge_ticket(c["base"], c["b"], c["a"], NOW, person, verdict) == c.get(
        "expect_reverse", c["expect"]
    )  # attribution follows the receiving machine
    if c.get("convergence"):
        checked = c["expect"]
        replay = merge_ticket(c["base"], c["a"], checked, NOW, person, verdict)
        assert replay["history"] == checked["history"]
        exchanged = merge_ticket(c["base"], checked, checked, NOW, person, verdict)
        assert exchanged["history"] == checked["history"]
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
    assert {"2", "3", "4", "5", "6", "7", "8", "9", "10", "D8", "add", "wont", "verdict"} <= rules


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
    assert texts(m) == ["created", "y", "(synced, not verified here) x"]


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
    reverse = merge_ticket(base, b, a, NOW)
    assert {k: v for k, v in m.items() if k not in ("history", "revision", "updated_at")} == {
        k: v for k, v in reverse.items() if k not in ("history", "revision", "updated_at")
    }
    assert (base, a, b) == before
    assert m["schema"] != "orch.ticket/1" or list(SCHEMA.iter_errors(m)) == []
    have = {(h["at"], h["by"], h["text"]) for h in m["history"]}
    for side in (a, b):  # history is never dropped
        for h in side["history"]:
            assert (h["at"], h["by"], h["text"]) in have or (
                h["at"],
                "agent:sync",
                "(synced, not verified here) " + h["text"],
            ) in have
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


# ---- Won't do: a person's decision (human `by`); done vs won't do is one side wholesale


def _step(**kw):
    c = {"id": "c1", "text": "Email finance", "done": False, "evidence": []}
    c.update(kw)
    return c


WONT = {"wont_do": True, "reason": "Not needed", "by": "human:Ann", "at": T2}
TK = "t_abc123"


def signed(step, nonce="n1"):
    step = {**step, "wont_nonce": nonce}
    return {**step, "wont_mac": vmac(TK, step, nonce)}


def ledger_of(*steps):
    return {f"{TK}:{x['id']}": x["wont_mac"] for x in steps}


DONE = {
    "done": True,
    "evidence": [{"type": "note", "ref": "sent it", "by": "agent:claude", "at": T2}],
    "by": "agent:claude",
    "at": T2,
}


def test_wont_do_from_a_person_syncs():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    a = up(base, T2, checklist=[on])
    for x, y in ((a, base), (base, a)):
        out = merge_ticket(base, x, y, NOW, person_for(ledger_of(on)))
        assert out["checklist"][0]["wont_do"] is True and out["checklist"][0]["reason"] == "Not needed"
        assert list(SCHEMA.iter_errors(out)) == []


def test_person_wont_do_keeps_attribution_against_newer_agent_rename():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    a = up(base, T2, checklist=[on], title="Person's ticket title")
    b = up(
        base, T3, checklist=[_step(text="Email sales", by="agent:codex", at=T3)], title="Agent's ticket title"
    )
    for x, y in ((a, b), (b, a)):
        out = merge_ticket(base, x, y, NOW, person_for(ledger_of(on)))
        c = out["checklist"][0]
        assert {k: c[k] for k in ("wont_do", "reason", "by")} == {
            k: on[k] for k in ("wont_do", "reason", "by")
        }
        assert c["text"] == on["text"]  # the existing signed decision also binds text
        assert out["title"] == "Agent's ticket title"
        assert list(SCHEMA.iter_errors(out)) == []


def test_two_verified_wont_do_copies_keep_newer_attribution():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    a = up(base, T2, checklist=[on])
    b = up(base, T3, checklist=[{**on, "by": "human:Bob", "at": T3}])
    for x, y in ((a, b), (b, a)):
        c = merge_ticket(base, x, y, NOW, person_for(ledger_of(on)))["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == on["reason"] and c["by"] == "human:Bob"


def test_wont_do_without_the_cores_say_so_is_dropped_whatever_by_says():
    base = tk(checklist=[_step()])
    for by in ("agent:claude", "human:Ann", None):  # `by: human:` alone is NOT the person
        item = _step(wont_do=True, reason="sneaky", **({"by": by, "at": T2} if by else {}))
        a = up(base, T2, checklist=[item])
        for x, y in ((a, base), (base, a)):
            c = merge_ticket(base, x, y, NOW, person_for({}))["checklist"][0]
            assert "wont_do" not in c and "reason" not in c


def test_done_vs_wont_do_a_verified_decision_wins_and_an_unverified_one_does_not():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    person = person_for(ledger_of(on))
    for newer_done in (True, False):
        a = up(base, T2 if newer_done else T3, checklist=[on])
        b = up(base, T3 if newer_done else T2, checklist=[_step(**DONE)])
        for x, y in ((a, b), (b, a)):
            out = merge_ticket(base, x, y, NOW, person)
            assert out["checklist"][0]["wont_do"] is True and out["checklist"][0]["done"] is False
            assert list(SCHEMA.iter_errors(out)) == []
    forged = _step(**WONT)  # no MAC: the newer done side wins wholesale as before
    a, b = up(base, T2, checklist=[forged]), up(base, T3, checklist=[_step(**DONE)])
    for x, y in ((a, b), (b, a)):
        assert merge_ticket(base, x, y, NOW, person_for({}))["checklist"][0] == _step(**DONE)


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
    assert all(e in ev for e in odd) and len([e for e in ev if e in runs]) == 45  # only runs are capped
    assert runs[-1] in ev


def test_core_and_merge_trim_runs_identically(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "workspace" / "src"))
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
    notes = [{"type": "note", "ref": f"n{i}"} for i in range(75)]
    odd = {"type": "note", "ref": "Grüße 日本語 \u2603", "z": [1, {"b": 2, "a": 3}]}
    assert merge._canon(odd) == tickets._canon(odd)
    for case in (hostile + many, ties, ties + hostile + many, notes + many + ties, many[:3]):
        assert tickets.trim_runs(list(case)) == merge.trim_runs(list(case))


def test_one_sided_forged_wont_do_is_dropped():
    base = tk(checklist=[_step()])
    forged = _step(wont_do=True, reason="x", by="agent:claude", at=T2)
    new_item = _step(id="c2", text="New", wont_do=True, by="agent:claude")
    a = up(base, T2, checklist=[forged, new_item])  # edited-vs-unchanged and a one-sided new item
    for x, y in ((a, base), (base, a)):
        for c in merge_ticket(base, x, y, NOW, person_for({}))["checklist"]:
            assert "wont_do" not in c and "reason" not in c


def test_conflict_pick_with_done_and_no_evidence_is_not_done():
    base = tk(checklist=[_step()])
    a = up(base, T2, checklist=[_step(**WONT)])
    b = up(base, T3, checklist=[_step(done=True, evidence=[])])
    for x, y in ((a, b), (b, a)):
        c = merge_ticket(base, x, y, NOW)["checklist"][0]
        assert c["done"] is False


# ---- #425: Won't do counts as the person's only by the receiving core's say-so (never by `by: human:`) ----------
# The core's say-so = a MAC valid for the step's text and covers that is also the CURRENT ledger entry.


def test_without_a_verifier_nobody_is_a_person_fail_closed():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    a = up(base, T2, checklist=[on])
    for x, y in ((a, base), (base, a)):
        c = merge_ticket(base, x, y, NOW)["checklist"][0]
        assert "wont_do" not in c and "reason" not in c
        c = merge_ticket(base, x, y, NOW, lambda step, ticket: 1 / 0)["checklist"][0]  # a verifier that fails
        assert "wont_do" not in c


def test_a_forged_by_human_is_not_kept_but_the_signed_one_is():
    base = tk(checklist=[_step(), _step(id="c2", text="Other")])
    forged = _step(**WONT)
    good = signed(_step(id="c2", text="Other", **WONT))
    a = up(base, T2, checklist=[forged, good])
    for x, y in ((a, base), (base, a)):
        c1, c2 = merge_ticket(base, x, y, NOW, person_for(ledger_of(good)))["checklist"]
        assert "wont_do" not in c1 and c2["wont_do"] is True


def test_a_decision_copied_onto_another_ticket_or_step_is_not_the_persons():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    for mac in ("valid:t_other99:c1:n1:Email finance:", "valid:t_abc123:c7:n1:Email finance:"):
        a = up(base, T2, checklist=[{**on, "wont_mac": mac}])
        for x, y in ((a, base), (base, a)):
            assert "wont_do" not in merge_ticket(base, x, y, NOW, person_for(ledger_of(on)))["checklist"][0]


# F1: with a base that holds the person's decision, a side that does not verify is "no change from base"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: {**s, "reason": "agent was here"},  # changed reason, MAC no longer valid
        lambda s: {**s, "wont_mac": "garbage"},
        lambda s: {k: v for k, v in s.items() if k != "wont_mac"},
        lambda s: {k: v for k, v in s.items() if k not in ("wont_do", "reason")},  # dropped, mac left
        lambda s: {k: v for k, v in s.items() if k not in ("wont_do", "reason", "wont_mac", "wont_nonce")},
    ],
)
def test_an_unverified_side_never_changes_a_held_wont_do_either_argument_order(mutate):
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    person = person_for(ledger_of(on))
    agent = up(base, T2, checklist=[mutate(on)])
    for x, y in ((agent, base), (base, agent)):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == "Not needed" and c["wont_mac"] == on["wont_mac"]


def test_an_unverified_side_with_a_changed_decision_is_not_newer_wholesale_over_a_done_side():
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    person = person_for(ledger_of(on))
    bad = up(base, T3, checklist=[{**on, "reason": "x"}])  # newer, but unverified
    done = up(base, T2, checklist=[_step(**DONE)])
    for x, y in ((bad, done), (done, bad)):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == "Not needed"  # base's decision stands


def test_deleted_on_one_side_and_edited_on_the_other_does_not_bring_back_an_unverified_decision():
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    person = person_for(ledger_of(on))
    gone = up(base, T2, checklist=[])
    edited = up(base, T3, checklist=[{**on, "reason": "x"}])
    for x, y in ((gone, edited), (edited, gone)):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == "Not needed"


def test_a_signed_undo_that_is_the_current_ledger_entry_is_accepted():
    on = signed(_step(**WONT), "n1")
    undo = signed(_step(), "n2")
    base = tk(checklist=[on])
    person = person_for(ledger_of(undo))  # the undo is now the current entry
    for x, y in ((up(base, T2, checklist=[undo]), base), (base, up(base, T2, checklist=[undo]))):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert "wont_do" not in c and "reason" not in c


# F2: the ledger holds the CURRENT MAC; an older signed decision replayed later does not verify


def test_replaying_an_older_signed_on_over_a_newer_off_is_not_accepted():
    on1, undo2 = signed(_step(**WONT), "n1"), signed(_step(), "n2")
    base = tk(checklist=[undo2])
    person = person_for(ledger_of(undo2))
    for x, y in ((up(base, T2, checklist=[on1]), base), (base, up(base, T2, checklist=[on1]))):
        assert "wont_do" not in merge_ticket(base, x, y, NOW, person)["checklist"][0]


def test_replaying_an_older_signed_undo_over_a_current_on_is_not_accepted():
    undo2, on3 = signed(_step(), "n2"), signed(_step(**WONT), "n3")
    base = tk(checklist=[on3])
    person = person_for(ledger_of(on3))
    for x, y in ((up(base, T2, checklist=[undo2]), base), (base, up(base, T2, checklist=[undo2]))):
        assert merge_ticket(base, x, y, NOW, person)["checklist"][0]["wont_do"] is True


def test_a_removed_steps_id_reused_with_the_old_mac_is_not_the_persons():
    on1 = signed(_step(**WONT))
    base = tk(checklist=[])
    person = person_for({f"{TK}:c1": None})  # tombstone: the step was removed
    new_step_old_mac = up(base, T2, checklist=[on1])
    for x, y in ((new_step_old_mac, base), (base, new_step_old_mac)):
        assert "wont_do" not in merge_ticket(base, x, y, NOW, person)["checklist"][0]


def test_no_ledger_entry_means_nobody_even_for_a_valid_looking_mac():
    base = tk(checklist=[_step()])
    on = signed(_step(**WONT))
    a = up(base, T2, checklist=[on])
    for x, y in ((a, base), (base, a)):
        assert "wont_do" not in merge_ticket(base, x, y, NOW, person_for({}))["checklist"][0]


# F3: the decision binds the step's text and covers


@pytest.mark.parametrize("edit", [{"text": "Email the auditor instead"}, {"covers": "everything"}])
def test_rewriting_ONLY_text_or_covers_under_a_persons_wont_do_changes_nothing(edit):
    """RR1: an agent that changes just the text or covers must not drop the decision (no MAC needed to do so)."""
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    person = person_for(ledger_of(on))
    agent = up(base, T2, checklist=[{**on, **edit}])
    for x, y in ((agent, base), (base, agent)):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert c == on  # no change from base: the decision AND the text/covers stay


def test_rewriting_text_and_dropping_the_decision_is_all_restored():
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    stripped = {k: v for k, v in on.items() if k not in ("wont_do", "reason", "wont_mac", "wont_nonce")}
    agent = up(base, T2, checklist=[{**stripped, "text": "skip the security review"}])
    for x, y in ((agent, base), (base, agent)):
        c = merge_ticket(base, x, y, NOW, person_for(ledger_of(on)))["checklist"][0]
        assert c["wont_do"] is True and c["text"] == "Email finance"


def test_an_agent_rename_of_a_reopened_step_cannot_bring_the_old_wont_do_back():
    on1, undo2 = signed(_step(**WONT), "n1"), signed(_step(), "n2")
    renamed = {**undo2, "text": "Email finance, renamed"}  # an undo record binds no text: still verifies
    base = tk(checklist=[renamed])
    person = person_for(ledger_of(undo2))
    assert person(renamed, TK)
    stale = up(base, T2, checklist=[on1])  # a stale peer still has the old "on"
    for x, y in ((stale, base), (base, stale)):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert "wont_do" not in c


def test_a_rename_of_a_never_decided_step_is_free():
    base = tk(checklist=[_step()])
    agent = up(base, T2, checklist=[_step(text="Email finance and the auditor")])
    for x, y in ((agent, base), (base, agent)):
        assert merge_ticket(base, x, y, NOW, person_for({}))["checklist"][0]["text"].endswith("auditor")


def test_drop_wont_clears_the_nonce_too():
    on = signed(_step(**WONT))
    a = up(tk(checklist=[_step()]), T2, checklist=[on])
    c = merge_ticket(tk(checklist=[_step()]), a, tk(checklist=[_step()]), NOW)["checklist"][0]  # no verifier
    assert "wont_do" not in c and "wont_nonce" not in c and "wont_mac" not in c


def test_a_proven_edit_re_signs_and_keeps_the_wont_do():
    on = signed(_step(**WONT), "n1")
    base = tk(checklist=[on])
    resigned = signed(_step(**WONT, text="Email finance and the auditor"), "n2")
    person = person_for(ledger_of(resigned))
    for x, y in ((up(base, T2, checklist=[resigned]), base), (base, up(base, T2, checklist=[resigned]))):
        c = merge_ticket(base, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["text"] == "Email finance and the auditor"


def test_a_renumbered_won_t_do_without_a_base_is_dropped_fail_closed():
    on = signed(_step(**WONT))
    renumbered = {**on, "id": "c2"}  # _renumber_clashes changed the id: the MAC is for c1
    a = up(tk(checklist=[]), T2, checklist=[renumbered])
    base = tk(checklist=[])
    for x, y in ((a, base), (base, a)):
        assert "wont_do" not in merge_ticket(None, x, y, NOW, person_for(ledger_of(on)))["checklist"][0]


def test_one_side_deleting_a_persons_wont_do_step_does_not_delete_it():
    on = signed(_step(**WONT))
    base = tk(checklist=[on])
    person = person_for(ledger_of(on))
    gone = up(base, T2, checklist=[])
    for x, y in ((gone, base), (base, gone)):
        assert [c["wont_do"] for c in merge_ticket(base, x, y, NOW, person)["checklist"]] == [True]
    both = merge_ticket(base, gone, up(base, T3, checklist=[]), NOW, person)
    assert both["checklist"] == []  # both sides deleted it: final


# ---- RR2: the ledger's CURRENT entry is the authority, not the base (a stale base proves nothing) -------------


def _rename(step, text):
    return {**step, "text": text}


def test_stale_base_with_the_persons_newer_on_and_an_agent_rename_of_the_stale_copy():
    on1 = signed(_step(**WONT), "n1")
    on2 = signed(_step(**{**WONT, "reason": "Not needed any more"}), "n2")  # re-signed since the last sync
    stale = tk(checklist=[on1])
    person = person_for(ledger_of(on2))
    newer = up(stale, T3, checklist=[on2])
    agent = up(stale, T2, checklist=[_rename(on1, "skip security review")])
    for x, y in ((newer, agent), (agent, newer)):
        c = merge_ticket(stale, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == "Not needed any more" and c["text"] == "Email finance"


def test_stale_base_with_the_persons_newer_on_and_the_agent_dropping_wont_do_on_its_stale_copy():
    on1 = signed(_step(**WONT), "n1")
    on2 = signed(_step(**{**WONT, "reason": "Not needed any more"}), "n2")
    stale = tk(checklist=[on1])
    person = person_for(ledger_of(on2))
    newer = up(stale, T3, checklist=[on2])
    dropper = up(stale, T2, checklist=[_step()])
    for x, y in ((newer, dropper), (dropper, newer)):
        c = merge_ticket(stale, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["reason"] == "Not needed any more"


def test_stale_base_on_with_the_current_undo_on_one_side_stays_undone_and_the_rename_is_free():
    on1, undo2 = signed(_step(**WONT), "n1"), signed(_step(), "n2")
    stale = tk(checklist=[on1])
    person = person_for(ledger_of(undo2))
    undone = up(stale, T3, checklist=[undo2])
    agent = up(stale, T2, checklist=[_rename(on1, "Email finance, renamed")])
    for x, y in ((undone, agent), (agent, undone)):
        c = merge_ticket(stale, x, y, NOW, person)["checklist"][0]
        assert "wont_do" not in c and c["text"] == "Email finance, renamed"


def test_stale_base_undo_with_the_persons_newer_on_and_an_agent_rename_of_the_stale_undo():
    undo2, on3 = signed(_step(), "n2"), signed(_step(**WONT), "n3")
    stale = tk(checklist=[undo2])
    person = person_for(ledger_of(on3))
    newer = up(stale, T3, checklist=[on3])
    agent = up(stale, T2, checklist=[_rename(undo2, "skip security review")])
    for x, y in ((newer, agent), (agent, newer)):
        c = merge_ticket(stale, x, y, NOW, person)["checklist"][0]
        assert c["wont_do"] is True and c["text"] == "Email finance"


def test_no_authority_means_no_wont_do_even_a_stale_bases():
    on1 = signed(_step(**WONT))
    base = tk(checklist=[on1])
    for x, y in ((up(base, T2, checklist=[on1]), base), (base, up(base, T2, checklist=[on1]))):
        assert "wont_do" not in merge_ticket(base, x, y, NOW, person_for({}))["checklist"][0]


def test_two_different_verifying_decisions_cannot_exist_and_if_a_verifier_said_so_nobody_wins():
    on1, on2 = signed(_step(**WONT), "n1"), signed(_step(**{**WONT, "reason": "other"}), "n2")
    ledger = ledger_of(on2)
    person = person_for(ledger)
    assert person(on2, TK) and not person(on1, TK)  # one current entry: at most one input can verify
    base = tk(checklist=[_step()])
    a, b = up(base, T2, checklist=[on1]), up(base, T3, checklist=[on2])
    loud = lambda step, ticket: step.get("wont_do") is True  # a (wrong) verifier that vouches for both
    for x, y in ((a, b), (b, a)):
        assert "wont_do" not in merge_ticket(base, x, y, NOW, loud)["checklist"][0]  # fail closed


# ---- RR3: a renumbering never moves an item the core vouches for (updated_at is peer-controlled) --------------


def _by_id(t, i):
    return next(c for c in t["checklist"] if c["id"] == i)


@pytest.mark.parametrize("agent_at", [T1, T3])  # the agent copy older, then newer
def test_a_clash_renumbers_the_agents_item_never_the_persons_signed_one(agent_at):
    base = tk(checklist=[_step()])
    mine_c2 = signed(_step(id="c2", text="Call the bank", **WONT))
    person = person_for(ledger_of(mine_c2))
    mine = up(base, T2, checklist=[_step(), mine_c2])
    agent = up(base, agent_at, checklist=[_step(), _step(id="c2", text="Skip the security review")])
    for x, y in ((mine, agent), (agent, mine)):
        out = merge_ticket(base, x, y, NOW, person)
        kept = _by_id(out, "c2")
        assert kept["wont_do"] is True and kept["text"] == "Call the bank"  # the signed item kept its id
        moved = [c for c in out["checklist"] if c["text"] == "Skip the security review"]
        assert len(moved) == 1 and moved[0]["id"] != "c2" and "wont_do" not in moved[0]


def test_two_vouched_items_with_one_id_cannot_be_merged_and_the_caller_pauses():
    base = tk(checklist=[_step()])
    one = signed(_step(id="c2", text="Call the bank", **WONT), "n1")
    two = signed(_step(id="c2", text="Another decision", **WONT), "n2")
    loud = lambda step, ticket: step.get("wont_do") is True  # a (wrong) verifier that vouches for both
    a, b = up(base, T2, checklist=[_step(), one]), up(base, T3, checklist=[_step(), two])
    for x, y in ((a, b), (b, a)):
        assert merge_ticket(base, x, y, NOW, loud) is None


def test_without_a_vouched_item_updated_at_still_decides_the_clash():
    base = tk(checklist=[_step()])
    old = up(base, T1, checklist=[_step(), _step(id="c2", text="First")])
    new = up(base, T3, checklist=[_step(), _step(id="c2", text="Second")])
    for x, y in ((old, new), (new, old)):
        out = merge_ticket(base, x, y, NOW, person_for({}))
        assert _by_id(out, "c2")["text"] == "First"  # the older keeps the id (as before)


# ---- signed verdicts (human-proof.md "Done needs a signed verdict") -------------------------------------------


def test_merge_verdict_fields_and_shape():
    from orch_sync import merge

    assert merge._VERDICT_FIELDS == ("kind", "nonce", "mac")
    good = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    assert merge._verdict_shape(good)
    for bad in (
        None,
        {},
        {**good, "extra": 1},
        {**good, "kind": "bot"},
        {**good, "nonce": "XYZ"},
        {**good, "mac": "short"},
        {k: v for k, v in good.items() if k != "mac"},
    ):
        assert not merge._verdict_shape(bad)


def test_a_verdict_is_never_dropped_for_being_ours_without_a_verifier():
    A = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    base = tk(status="done", verdicts=[A])
    peer = up(base, T3, note="y")
    for x, y in ((base, peer), (peer, base)):
        assert merge_ticket(base, x, y, NOW)["verdicts"] == [
            A
        ]  # verdict=None: nobody verifies, nothing is "stale"


def test_a_verdict_verifier_that_fails_vouches_for_nobody():
    A = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    base = tk(status="done", verdicts=[A])

    def boom(entry, ticket):
        raise RuntimeError("no")

    out = merge_ticket(base, up(base, T2, note="x"), up(base, T3, note="y"), NOW, None, boom)
    assert out["verdicts"] == [A] and out["status"] == "done"


def test_the_merge_output_validates_against_the_schema_with_verdicts():
    A = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    base = tk(status="done", verdicts=[A])
    out = merge_ticket(
        base,
        up(base, T2, note="x"),
        up(base, T3, note="y"),
        NOW,
        None,
        verdict_for({"t_abc123": "A" * 43}, ["A" * 43]),
    )
    assert list(SCHEMA.iter_errors(out)) == []
    assert list(SCHEMA.iter_errors({**out, "verdicts": [{**A, "mac": "bad"}]})) != []
    assert list(SCHEMA.iter_errors({**out, "verdicts": [A] * 9})) != []


@pytest.mark.parametrize("decision", ["wont", "verdict"])
def test_history_verifier_failure_is_closed(decision):
    line = {"at": T2, "by": "human:A", "text": "Looks good"}
    peer = tk(status="done", verdicts=[{"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}])
    if decision == "wont":
        peer = tk(checklist=[signed(_step(**WONT))])
        line["text"] = "Marked c1 as won't do"
    peer["history"] = [line]

    def boom(*args):
        raise RuntimeError("unavailable")

    out = merge_ticket(tk(), peer, tk(), NOW, boom, boom)
    assert out["history"] == [
        {**line, "by": "agent:sync", "text": "(synced, not verified here) " + line["text"]}
    ]
    assert list(SCHEMA.iter_errors(out)) == []
    assert merge_ticket(tk(), tk(), peer, NOW, boom, boom)["history"] == [line]


@pytest.mark.parametrize(
    "by",
    [
        "Human:lindenmann",
        " human:x",
        "lindenmann",
        ["human:x"],
        "agent:relay from ph_abc",
        "agent:relay",
        "agent:\u200brelay from ph_abc",
        "agent:Severin Lindenmann",
        " Agent:Worker ",
        "agent:",
        "agent:" + "a" * 41,
        "agent:worker\n",
        "agent:ＲＥＬＡＹ",
        None,
    ],
)
def test_remote_person_labels_are_demoted_but_local_lines_are_preserved(by, root):
    line = {"at": T2, "by": by, "text": "Approved"}
    peer = tk(history=[line])
    assert merge_ticket(tk(), peer, tk(), NOW)["history"] == [
        {**line, "by": "agent:sync", "text": "(synced, not verified here) Approved"}
    ]
    assert merge_ticket(tk(), tk(), peer, NOW)["history"] == [line]
    from orch.phone_view import build

    rendered = build(root, merge_ticket(tk(), peer, tk(), NOW), [])["history_tail"]
    assert rendered[0]["role"] == "agent"
    assert rendered[0]["text"] == "(synced, not verified here) Approved"


@pytest.mark.parametrize("decision", ["wont", "verdict"])
@pytest.mark.parametrize("known", [None, "base", "local"])
def test_verified_decision_does_not_authenticate_history_author(decision, known):
    check = signed(_step(**WONT))
    entry = {"kind": "person", "nonce": "0123456789abcdef", "mac": "A" * 43}
    peer = tk(checklist=[check]) if decision == "wont" else tk(status="done", verdicts=[entry])
    text = "Marked c1 as won't do" if decision == "wont" else "Looks good"
    base = deepcopy(peer) if known == "base" else tk()
    local = deepcopy(peer) if known == "local" else tk()
    peer["history"] = [
        {"at": at, "by": by, "text": text}
        for at, by in [(T1, "human:Impostor"), (T2, "human:Ann"), (T3, "human:Ann")]
    ]
    out = merge_ticket(
        base, peer, local, NOW, person_for(ledger_of(check)), verdict_for({TK: entry["mac"]}, [])
    )
    human = [h for h in out["history"] if h["by"] != "agent:sync"]
    assert human == []
    # Returning the untrusted original cannot resurrect a demoted line.
    again = merge_ticket(
        base, peer, out, NOW, person_for(ledger_of(check)), verdict_for({TK: entry["mac"]}, [])
    )
    assert again["history"] == out["history"]


def test_returned_demotion_cannot_erase_local_unpushed_answer():
    line = {"at": T2, "by": "human:lindenmann", "text": "Answered q1: yes"}
    local = tk(history=[line])
    remote = tk(history=[{**line, "by": "agent:sync", "text": "(synced, not verified here) " + line["text"]}])
    assert line in merge_ticket(tk(), remote, local, NOW)["history"]


@pytest.mark.parametrize(
    "by",
    [
        "agent:worker",
        "AGENT:worker",
        "agent:claude",
        "agent:sync",
        "agent:codex",
        "agent:automation",
        "agent:focus",
        "agent:my-agent_1.2",
        "agent:" + "a" * 40,
        "ａｇｅｎｔ:ＣＯＤＥＸ",
    ],
)
def test_phone_attribution_and_sync_share_agent_allowlist(by):
    from orch.phone_view import _who, is_agent_history_author

    assert is_agent_history_author(by)
    assert _who(by)[1] == "agent"
    line = {"at": T2, "by": by, "text": "Working"}
    assert merge_ticket(tk(), tk(history=[line]), tk(), NOW)["history"] == [line]


@pytest.mark.parametrize("text", [123, ["bad"], None])
@pytest.mark.parametrize("by", ["human:Ann", "agent:worker", "agent:sync"])
@pytest.mark.parametrize("has_base", [False, True])
def test_malformed_remote_history_text_does_not_stall_merge(text, by, has_base):
    bad = {"at": T2, "by": by, "text": text}
    good = {"at": T2, "by": "agent:worker", "text": "Working"}
    local_line = {"at": T1, "by": "human:Ann", "text": "Requested"}
    base = tk() if has_base else None
    remote = tk(title="Remote update", history=[bad, good])
    local = tk(history=[local_line])
    before = deepcopy((base, remote, local))
    out = merge_ticket(base, remote, local, NOW)
    assert out is not None
    assert out["title"] == "Remote update"
    assert out["history"][:2] == [local_line, good]
    assert bad not in out["history"]
    assert all(isinstance(h["text"], str) for h in out["history"])
    assert list(SCHEMA.iter_errors(out)) == []
    assert (base, remote, local) == before
    assert merge_ticket(base, remote, out, NOW)["history"] == out["history"]
