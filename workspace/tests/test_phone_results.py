"""Phone results (contracts/blocks.md 'Phone results'): the sender puts `ticket_view.results` into FULL
snapshots only, trimmed, value-hidden and checked; a result that fails any check is dropped."""

import base64
import copy
import json
from pathlib import Path

import pytest
from test_ticket_view import assert_valid, conn, views  # noqa: F401 (fixture)

from orch import hider, keystore, phone_results, phone_view, tickets
from orch.errors import Refused

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VEC = json.loads((CONTRACTS / "vectors" / "phone-results-v1.json").read_text())
TV = json.loads((CONTRACTS / "vectors" / "ticket-view-v1.json").read_text())
NOHIDE = hider.Hider({})
SECRET = "sk-live-4f9d7a1c8b2e6053aa11"


def doc(text="Totals match.", frm="agent", blocks=None):
    return {"schema": "orch.blocks/1", "from": frm, "blocks": blocks or [{"type": "summary", "text": text}]}


def cand(i, at, frm="agent", **kw):
    aid = f"a_{i:012x}" if frm != "job" else f"j_job{i:06d}"
    r = {"id": aid, "from": frm, "at": at, "doc": doc(frm=frm)}
    r.update(kw)
    return r


def test_schema_copy_matches_the_contract():
    here = Path(phone_results.__file__).with_name("blocks.schema.json")
    assert json.loads(here.read_text()) == json.loads((CONTRACTS / "blocks.schema.json").read_text())


@pytest.mark.parametrize("case", VEC["trim"], ids=lambda c: c["name"][:20])
def test_trim_vectors(case, proj):
    assert phone_results.prepare(proj, [case["in"]], h=NOHIDE) == [case["out"]]
    assert phone_results.phone_ok(case["out"])
    assert phone_results.trim(case["out"]) == case["out"]


def test_ticket_view_vector_cases_agree():
    for c in TV["cases"]:
        if not c["name"].startswith("results-"):
            continue
        results = c["message"]["body"]["ticket_view"].get("results", [])
        if c["ok"]:
            assert results and all(phone_results.phone_ok(r) for r in results), c["name"]
            assert phone_results.prepare(Path("."), results, h=NOHIDE) == results, c["name"]
        elif c["name"] not in ("results-six", "results-in-light"):
            sent = phone_results.prepare(Path("."), results, h=NOHIDE)
            assert sent != results and all(phone_results.phone_ok(r) for r in sent), c["name"]


def test_ordering_unique_ids_and_max_five():
    cs = [cand(i, f"2026-11-11T08:0{i}:00Z") for i in range(7)]
    cs.append(cand(6, "2026-11-11T07:00:00Z"))  # same id as the newest: only one is kept
    out = phone_results.prepare(Path("."), cs, h=NOHIDE)
    assert [r["id"] for r in out] == [f"a_{i:012x}" for i in (6, 5, 4, 3, 2)]
    assert [r["at"] for r in out] == sorted((r["at"] for r in out), reverse=True)


def test_all_results_together_at_most_8192_bytes_newest_never_dropped():
    big = [{"type": "kv", "items": [{"key": f"k{i}", "value": "v" * 40} for i in range(25)]}]
    cs = []
    for i in range(5):
        c = cand(i, f"2026-11-11T08:0{i}:00Z")
        c["doc"] = doc(blocks=big)
        cs.append(c)
    out = phone_results.prepare(Path("."), cs, h=NOHIDE)
    assert 1 <= len(out) < 5 and phone_results.cj(out) <= phone_results.RESULTS_BYTES
    assert out[0]["id"] == cs[4]["id"], "the newest is kept, the oldest go first"


def test_forged_checked_is_impossible():
    job = cand(1, "2026-11-11T08:00:00Z", frm="job", checked=True)
    orch = cand(2, "2026-11-11T08:01:00Z", frm="orch", checked=True)
    mismatch = cand(3, "2026-11-11T08:02:00Z", frm="agent")
    mismatch["doc"]["from"] = "job"
    assert phone_results.prepare(Path("."), [job, orch, mismatch], h=NOHIDE) == []
    ok = cand(4, "2026-11-11T08:03:00Z", checked=True)
    assert phone_results.prepare(Path("."), [ok], h=NOHIDE)[0]["checked"] is True
    ok["checked"] = False
    assert (
        phone_results.prepare(Path("."), [ok], h=NOHIDE) == []
        or "checked" not in (phone_results.prepare(Path("."), [ok], h=NOHIDE)[0])
    )


def test_invalid_document_is_dropped_never_sent():
    bad = [
        cand(1, "2026-11-11T08:00:00Z", doc=None) | {"doc": {"schema": "orch.blocks/1", "from": "agent"}},
        cand(2, "2026-11-11T08:01:00Z")
        | {"doc": doc(blocks=[{"type": "table", "columns": [], "rows": "x"}])},
        cand(3, "2026-11-11T08:02:00Z")
        | {"doc": doc(blocks=[{"type": "link", "label": "a", "url": "http://x.ch/"}])},
        cand(4, "2026-11-11T08:03:00Z") | {"doc": doc(blocks=[{"type": "summary", "text": 5}])},
        cand(5, "2026-11-11T08:04:00Z") | {"id": "nope"},
    ]
    good = cand(6, "2026-11-11T07:00:00Z")
    assert phone_results.prepare(Path("."), bad + [good], h=NOHIDE) == [good]


def test_value_hider_unavailable_sends_nothing(proj, monkeypatch):
    def boom(root):
        raise Refused("damaged")

    monkeypatch.setattr(keystore, "all_needles", boom)
    assert phone_results.value_hider(proj) is None
    assert phone_results.prepare(proj, [cand(1, "2026-11-11T08:00:00Z")]) == []


def _evidence_ticket(proj, new_ticket, docs, done=True):
    tid = new_ticket("Invoice export")
    evs = []
    for name, d, at in docs:
        p = proj / ".orch/tickets" / tid / "evidence" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d))
        evs.append(
            {"type": "file", "ref": f".orch/tickets/{tid}/evidence/{name}", "role": "result", "at": at}
        )

    def op(t):
        t["checklist"] = [{"id": "c1", "text": "Export", "done": done, "evidence": evs}]

    tickets.apply_op(proj, tid, op)
    return tid


def test_full_snapshot_carries_results_light_does_not(proj, new_ticket, conn):  # noqa: F811
    tid = _evidence_ticket(
        proj,
        new_ticket,
        [
            ("a.json", doc("Old", frm="job"), "2026-11-11T08:00:00Z"),
            ("b.json", doc("New"), "2026-11-11T09:00:00Z"),
            ("notes.json", {"hello": 1}, "2026-11-11T09:30:00Z"),  # not a blocks document: no result
        ],
    )
    view = phone_view.view_for(proj, tid)
    assert_valid(view)
    assert [r["doc"]["blocks"][0]["text"] for r in view["results"]] == ["New", "Old"]
    assert all(r["from"] == "agent" and r["checked"] is True for r in view["results"]), (
        "a document claiming to be the job's is the agent's proof here, and checked only as done step"
    )
    assert view["results"][0]["id"] == phone_view.artifact_id("file", f".orch/tickets/{tid}/evidence/b.json")
    assert "results" not in phone_view.light_view(proj, tickets.load(proj, tid))


def test_unchecked_when_step_not_done(proj, new_ticket, conn):  # noqa: F811
    tid = _evidence_ticket(proj, new_ticket, [("a.json", doc(), "2026-11-11T08:00:00Z")], done=False)
    (r,) = phone_view.view_for(proj, tid)["results"]
    assert "checked" not in r


def test_secrets_never_leave_in_result_text_kv_or_table(proj, new_ticket, conn):  # noqa: F811
    keystore.add(proj, "api-token", "token", SECRET)
    forms = [SECRET, SECRET.encode().hex(), base64.b64encode(SECRET.encode()).decode()]
    d = doc(
        blocks=[
            {"type": "summary", "text": f"Used {SECRET} to export"},
            {"type": "kv", "items": [{"key": "hex", "value": forms[1]}, {"key": "b64", "value": forms[2]}]},
            {
                "type": "table",
                "columns": [{"key": "c", "label": "C"}],
                "rows": [{"c": f"row {SECRET}"}],
            },
            {"type": "link", "label": "x", "url": f"https://x.example.ch/{SECRET}"},
            {"type": "file", "path": f"out/{SECRET}.csv"},
        ]
    )
    d["title"] = f"T {SECRET}"
    tid = _evidence_ticket(proj, new_ticket, [("a.json", d, "2026-11-11T08:00:00Z")])
    view = phone_view.view_for(proj, tid)
    out = json.dumps(view.get("results", []), ensure_ascii=False)
    for f in forms:
        assert f not in out
    assert "[hidden: api-token]" in out or not view.get("results")


def test_hider_off_means_no_results_in_the_snapshot(proj, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = _evidence_ticket(proj, new_ticket, [("a.json", doc(), "2026-11-11T08:00:00Z")])
    assert phone_view.view_for(proj, tid)["results"]
    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)
    assert "results" not in phone_view.view_for(proj, tid)


def test_budget_sheds_history_first_and_results_last_never_the_newest():
    rs = [cand(i, f"2026-11-11T08:0{i}:00Z") for i in range(5)][::-1]
    view = {
        "history_tail": [{"at": "2026-11-11T08:00:00Z", "who": "a", "role": "agent", "text": "h" * 900}] * 20,
        "attachments": [],
        "checklist": [{"text": "t" * 500, "done": True} for _ in range(5)],
        "results": copy.deepcopy(rs),
    }
    out = phone_view.fit(copy.deepcopy(view))
    assert phone_view.size_of(out) <= phone_view.BUDGET
    assert out["results"] == rs and len(out["history_tail"]) < 20, "history goes first, results stay"
    heavy = copy.deepcopy(view)
    heavy["checklist"] = []
    heavy["results"] = rs
    heavy["history_tail"] = []
    heavy["title"] = "x" * 14900
    out = phone_view.fit(heavy)
    assert [r["id"] for r in out["results"]] == [rs[0]["id"]], "oldest dropped first, the newest stays"


def test_older_relay_gets_the_same_update_without_results(proj, run, new_ticket, conn):  # noqa: F811
    tid = _evidence_ticket(proj, new_ticket, [("a.json", doc(), "2026-11-11T08:00:00Z")])
    post = next(fn for m, rx, fn in conn.routes if rx == "/v1/messages")
    seen = []

    def old(m, q, body):
        b = json.loads(body)
        seen.append(b)
        if "results" in b["body"].get("ticket_view", {}):
            return 422, {"error": "invalid", "message": "unknown field results"}
        return post(m, q, body)

    conn.routes.insert(0, ("POST", "/v1/messages", old))
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    (m,) = views(conn)
    assert "results" not in m["body"]["ticket_view"] and m["body"]["ticket_view"]["title"]
    assert len({b["id"] for b in seen}) == 1, "the same message id"


def test_pattern_secrets_in_cell_title_and_key_never_reach_the_output(proj, new_ticket, conn):  # noqa: F811
    tok = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    forms = [tok, tok.encode().hex(), base64.b64encode(tok.encode()).decode()]
    d = doc(
        blocks=[
            {"type": "table", "columns": [{"key": "c", "label": "C"}], "rows": [{"c": f"token={tok}"}]},
            {"type": "kv", "items": [{"key": f"password={tok}", "value": "x"}]},
        ]
    )
    d["title"] = f"password: {tok}"
    tid = _evidence_ticket(proj, new_ticket, [("a.json", d, "2026-11-11T08:00:00Z")])
    out = json.dumps(phone_view.view_for(proj, tid).get("results", []))
    assert not any(f in out for f in forms)
    assert (
        phone_results.prepare(proj, [cand(1, "2026-11-11T08:00:00Z") | {"title": f"token={tok}"}], h=NOHIDE)[
            0
        ]["title"]
        == "token=[hidden]"
    )


def test_deeply_nested_or_huge_proof_file_never_fails_the_send(proj, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Nest")
    for name, data in (("deep.json", "[" * 200_000), ("huge.json", '{"x":"' + "a" * 300_000 + '"}')):
        p = proj / ".orch/tickets" / tid / "evidence" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)

    def op(t):
        t["checklist"] = [
            {
                "id": "c1",
                "text": "x",
                "done": True,
                "evidence": [
                    {"type": "file", "ref": f".orch/tickets/{tid}/evidence/{n}", "role": "result"}
                    for n in ("deep.json", "huge.json")
                ],
            }
        ]

    tickets.apply_op(proj, tid, op)
    assert "results" not in phone_view.view_for(proj, tid)


def test_any_error_in_prepare_means_no_results(proj, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = _evidence_ticket(proj, new_ticket, [("a.json", doc(), "2026-11-11T08:00:00Z")])

    def boom(*a, **k):
        raise RecursionError

    monkeypatch.setattr(phone_results, "prepare", boom)
    assert "results" not in phone_view.view_for(proj, tid)


def test_secret_cut_by_the_title_limit_leaks_nothing(proj, new_ticket, conn):  # noqa: F811
    keystore.add(proj, "api-token", "token", SECRET)
    d = doc()
    d["title"] = "ok"
    title = "t" * 190 + SECRET
    out = phone_results.prepare(
        proj, [cand(1, "2026-11-11T08:00:00Z") | {"title": title}], h=hider.Hider(keystore.all_needles(proj))
    )
    assert out and SECRET[:6] not in json.dumps(out) and len(out[0]["title"]) <= 200


def test_secret_labels_hide_their_values():
    d = doc(
        blocks=[
            {
                "type": "kv",
                "items": [{"key": "DB password", "value": "hunter2pass"}, {"key": "Rows", "value": "9"}],
            },
            {"type": "stat", "label": "API key", "value": "abc123xyz"},
            {
                "type": "table",
                "columns": [{"key": "n", "label": "Name"}, {"key": "tk", "label": "Token"}],
                "rows": [{"n": "a", "tk": "s3cr3tvalue"}],
            },
        ]
    )
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    out = json.dumps(r)
    assert "hunter2pass" not in out and "abc123xyz" not in out and "s3cr3tvalue" not in out
    assert '"value": "9"' in out and '"n": "a"' in out


def test_order_parses_timestamps():
    cs = [cand(1, "2026-11-11T08:00:00.5Z"), cand(2, "2026-11-11T08:00:00Z")]
    assert [r["id"] for r in phone_results.prepare(Path("."), cs, h=NOHIDE)] == [cs[0]["id"], cs[1]["id"]]


def test_long_title_does_not_eat_the_block_budget():
    c = cand(1, "2026-11-11T08:00:00Z") | {"title": "T" * 2400}
    (r,) = phone_results.prepare(Path("."), [c], h=NOHIDE)
    assert len(r["title"]) == 200 and r["doc"]["blocks"][0]["text"] == "Totals match."


@pytest.mark.parametrize("label", ["Password", "pwd", "OTP", "Cookie", "Session", "Access_key", "Key ID",
                                   "Auth", "OAuth", "Authorization", "Signature", "Pincode"])  # fmt: skip
def test_secret_names_hide(label):
    d = doc(blocks=[{"type": "kv", "items": [{"key": label, "value": "v4lu3xyz"}]}])
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "v4lu3xyz" not in json.dumps(r)


@pytest.mark.parametrize("label", ["Keyboard", "Monkey", "Hotkey", "Turkey", "Passed", "Passage", "Author"])
def test_ordinary_names_stay(label):
    d = doc(blocks=[{"type": "kv", "items": [{"key": label, "value": "v4lu3xyz"}]}])
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "v4lu3xyz" in json.dumps(r)
