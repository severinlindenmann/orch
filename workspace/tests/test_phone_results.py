"""Phone results (contracts/blocks.md 'Phone results'): the sender puts `ticket_view.results` into FULL
snapshots only, trimmed, value-hidden and checked; a result that fails any check is dropped."""

import base64
import copy
import json
import urllib.parse
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
    assert phone_results.prepare(Path("."), [ok], h=NOHIDE) == [], "checked is true or absent: dropped"


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


def test_hider_off_means_no_view_and_no_ticket_text(proj, run, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = _evidence_ticket(proj, new_ticket, [("a.json", doc(), "2026-11-11T08:00:00Z")])
    assert phone_view.view_for(proj, tid)["results"]
    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)
    assert phone_view.view_for(proj, tid) is None, "stored values can't be hidden: no view at all"
    t = tickets.load(proj, tid)
    closed = phone_view.build(proj, t, [])
    assert_valid(closed)
    assert closed["title"] == "Ticket" and "results" not in closed and "summary" not in closed
    assert closed["history_tail"] == [] and closed["checklist"] == [] and closed["attachments"] == []
    word = "Ready for your review" if t["status"] == "review" else "Done"
    assert phone_view.result_text(t, None) == word
    with pytest.raises(Refused):
        phone_view.light_view(proj, t)
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    body = _result_message(conn)["body"]
    assert "ticket_view" not in body and "title" not in body["update"], body


def _result_message(rel):
    return next(m for m in reversed(rel.sent) if m["body"].get("update", {}).get("kind") == "result")


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


SECRET_LABELS = ["Password", "pwd", "OTP", "Cookie", "Session", "Access_key", "Key ID", "Auth", "OAuth"]
SECRET_LABELS += ["Authorization", "Signature", "Pincode", "basic_auth", "auth_code", "authCode"]
SECRET_LABELS += ["hmac_signature", "session_id"]


@pytest.mark.parametrize("label", SECRET_LABELS)
def test_secret_names_hide(label):
    d = doc(blocks=[{"type": "kv", "items": [{"key": label, "value": "v4lu3xyz"}]}])
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "v4lu3xyz" not in json.dumps(r)


ORDINARY = ["Keyboard", "Monkey", "Hotkey", "Turkey", "Passed", "Passage", "Author", "Authored", "Authoring"]
ORDINARY += ["Authority", "Fail", "Pass/Fail", "pass count", "pass rate", "Passes"]


@pytest.mark.parametrize("label", ORDINARY)
def test_ordinary_names_stay(label):
    d = doc(blocks=[{"type": "kv", "items": [{"key": label, "value": "v4lu3xyz"}]}])
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "v4lu3xyz" in json.dumps(r)


@pytest.mark.parametrize("label", ["basic_auth", "auth_code", "authCode", "hmac_signature", "session_id"])
def test_split_names_hide_in_stat_and_table(label):
    d = doc(
        blocks=[
            {"type": "stat", "label": label, "value": "v4lu3xyz"},
            {"type": "table", "columns": [{"key": "a", "label": label}, {"key": label.lower(), "label": "X"}],
             "rows": [{"a": "v4lu3xyz", label.lower(): "v4lu3xyz"}]},
        ]
    )  # fmt: skip
    (r,) = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "v4lu3xyz" not in json.dumps(r)


@pytest.mark.parametrize("word", phone_view.SECRET_NAME_WORDS)
def test_one_word_list_drives_secret_name_and_the_kv_redact(word):
    assert phone_view.secret_name(word), word
    for sep in (":", "="):
        out = phone_view.redact(f"{word.replace(' ', '_')}{sep}hunter2value")  # a name has no spaces here
        assert "hunter2value" not in out, (word, sep)


def test_authorization_header_loses_scheme_and_token():
    for text in ("Authorization: Bearer abcdefghijklmnop", "Authorization: Basic dXNlcjpwYXNzd29yZA=="):
        out = phone_view.redact(text)
        assert "abcdefghijklmnop" not in out and "dXNlcjpwYXNzd29yZA" not in out, out
        assert phone_view._SECRET_KV.search(text)
    kv = phone_view._SECRET_KV
    assert kv.sub(lambda m: m.group(1) + m.group(2) + "[hidden]", "Authorization: Bearer abc") == (
        "Authorization: [hidden]"
    )


@pytest.mark.parametrize(
    "unit", ["token-", "auth-", "pass-", "secret_", "x", '"token": ', "token'] = ", "a'] "]
)
def test_kv_pattern_is_linear_on_long_names(unit, monkeypatch):
    """Structural, not a wall-clock race: every head search starts after the last one, at most one per
    separator (also with quoted and subscripted names). The 5 s bound only catches a quadratic blow-up."""
    import time

    text = unit * (65536 // len(unit))
    real, starts = phone_view._KV_HEAD, []

    class CountingHead:
        def search(self, s, pos=0):
            starts.append(pos)
            return real.search(s, pos)

    monkeypatch.setattr(phone_view, "_KV_HEAD", CountingHead())
    list(phone_view._SECRET_KV.finditer(text))
    assert starts == sorted(set(starts))  # strictly increasing: nothing is scanned twice
    assert len(starts) <= text.count(":") + text.count("=") + 1
    monkeypatch.undo()
    t0 = time.perf_counter()
    phone_view.redact(text)
    phone_view._has_secret(text.encode())
    assert time.perf_counter() - t0 < 5


def test_very_long_string_is_hidden_whole():
    assert phone_results._scrub({"k" * 5000: ["token-" * 1000]}, phone_view.redact) == {
        "[hidden]": ["[hidden]"]
    }


def test_several_long_keys_never_overwrite_each_other():
    d = {"a" * 5000: 1, "b" * 5000: 2, "c" * 5000: 3, "ok": 4}
    out = phone_results._scrub(d, phone_view.redact)
    assert out == {"[hidden]": 1, "[hidden] 2": 2, "[hidden] 3": 3, "ok": 4}
    assert phone_results._scrub(out, phone_view.redact) == out  # the second pass keeps them


INNER_PAIRS = ["Config: password=hunter2", "a=1,token=hunter2", "user=bob&secret=hunter2"]
INNER_PAIRS += ["x: y: password=hunter2"]
# quoted or subscripted names (H2) and the other separators (M1)
QUOTED_PAIRS = [
    '{"password": "hunter2"}',
    "{'db_password': 'hunter2'}",
    'os.environ["DB_PASSWORD"] = "hunter2"',
]
QUOTED_PAIRS += ["config['token'] = 'hunter2'", 'password: "hunter2"', 'password := "hunter2"']
QUOTED_PAIRS += [
    "PASSWORD ?= hunter2",
    "PASSWORD += hunter2",
    "'password' => 'hunter2'",
    '$c["api_key"] => "hunter2",',
]
INNER_PAIRS += QUOTED_PAIRS


@pytest.mark.parametrize("text", INNER_PAIRS)
def test_a_plain_name_never_hides_a_secret_pair_in_its_value(text):
    out = phone_view.redact(text)
    assert "hunter2" not in out and "[hidden]" in out, out
    assert phone_view._SECRET_KV.search(text)  # finditer/search see the inner pair too
    assert phone_view._has_secret(text.encode())


def test_plain_pairs_stay():
    assert phone_view.redact("Config: debug=1, rows=9") == "Config: debug=1, rows=9"
    # a bare `pass: value` is a password until proven otherwise (fail-safe, documented over-redaction);
    # the phrases pass rate / pass count / passed stay
    assert phone_view.redact("Fail: 0, pass rate: 100%, pass_count=5, passed: 12") == (
        "Fail: 0, pass rate: 100%, pass_count=5, passed: 12"
    )
    assert phone_view.redact("pass: 12") == "pass: [hidden]"


@pytest.mark.parametrize("unit", ["a=", "x: ", "Config: ", "a=1,", "user=bob&"])
def test_kv_pattern_is_linear_on_long_plain_pairs(unit, monkeypatch):
    """Structural, not a wall-clock race: the scan is one pass (every head search starts after the last
    one, at most one search per separator). The 5 s bound only catches a quadratic blow-up (minutes here)."""
    import time

    text = unit * (65536 // len(unit)) + "password=hunter2"
    real, starts = phone_view._KV_HEAD, []

    class CountingHead:
        def search(self, s, pos=0):
            starts.append(pos)
            return real.search(s, pos)

    monkeypatch.setattr(phone_view, "_KV_HEAD", CountingHead())
    t0 = time.perf_counter()
    m = phone_view._SECRET_KV.search(text)
    assert time.perf_counter() - t0 < 5
    assert m and m.group(1) == "password" and m.group(3) == "hunter2"
    assert starts == sorted(set(starts))  # strictly increasing: nothing is scanned twice
    assert len(starts) <= text.count(":") + text.count("=") + 1
    monkeypatch.undo()
    t0 = time.perf_counter()
    phone_view.redact(text)
    assert time.perf_counter() - t0 < 5
    short = unit * (16000 // len(unit)) + "password=hunter2"  # under the 20000 cut of clean_untrusted
    assert "hunter2" not in phone_view.redact(short)


SECRET_FLAGS = [
    ("mysql -u root --password hunter2 db", "mysql -u root --password [hidden] db"),
    ("mysql -u root --password=hunter2 db", "mysql -u root --password=[hidden] db"),
    ("mysql -u root -p hunter2 db", "mysql -u root -p [hidden] db"),
    ("mysql -u root -phunter2 db", "mysql -u root -p[hidden] db"),
    ("mysqldump -uroot -phunter2 shop", "mysqldump -uroot -p[hidden] shop"),
    ("$ /usr/bin/mysql -h db -phunter2", "$ /usr/bin/mysql -h db -p[hidden]"),
    ("sudo mysql -p'hunter2' -e 'select 1'", "sudo mysql -p[hidden] -e 'select 1'"),
    ("sshpass -p hunter2 ssh -o X=1 me@host", "sshpass -p [hidden] ssh -o X=1 me@host"),
    ("redis-cli -h cache -a hunter2 ping", "redis-cli -h cache -a [hidden] ping"),
    ("curl -u bob:hunter2 https://x.ch/api", "curl -u [hidden] https://x.ch/api"),
    ("curl -ubob:hunter2 https://x.ch/api", "curl -u[hidden] https://x.ch/api"),
    ("deploy --token hunter2 --env prod", "deploy --token [hidden] --env prod"),
    ("deploy --api-key hunter2", "deploy --api-key [hidden]"),
    ('deploy --api-key "hunter2 x" now', "deploy --api-key [hidden] now"),
    ("tool --password --token hunter2", "tool --password --token [hidden]"),
    ("ran:\n  mysql -phunter2 shop\ndone", "ran:\n  mysql -p[hidden] shop\ndone"),
    # a known command anywhere on its line, .exe, the flag last in a cluster (M8); an en dash flag (L3)
    ("docker compose exec db mysql -uroot -phunter2", "docker compose exec db mysql -uroot -p[hidden]"),
    ("cd /srv && mysql -phunter2", "cd /srv && mysql -p[hidden]"),
    ("curl -su bob:hunter2 https://x.ch", "curl -su [hidden] https://x.ch"),
    ("mysql.exe -phunter2", "mysql.exe -p[hidden]"),
    ("C:\\mysql\\bin\\mysql.exe -u root -phunter2", "C:\\mysql\\bin\\mysql.exe -u root -p[hidden]"),
    ("env X=1 sshpass -p hunter2 ssh me@host", "env X=1 sshpass -p [hidden] ssh me@host"),
    ("deploy \u2013password hunter2", "deploy \u2013password [hidden]"),
]


@pytest.mark.parametrize("text, want", SECRET_FLAGS)
def test_secret_flag_values_are_hidden_flags_stay(text, want):
    out = phone_view.redact(text)
    assert out == want and "hunter2" not in out, out
    assert phone_view.redact(out) == out  # stable: the results check scrubs twice


def test_authorization_header_flag_is_hidden():
    out = phone_view.redact('curl -H "Authorization: Bearer hunter2xyz" https://x.ch')
    assert "hunter2xyz" not in out and "Bearer" not in out and "Authorization: [hidden]" in out, out


@pytest.mark.parametrize("text", ["ｍｙｓｑｌ -phunter2", "mysql －－password hunter2", "mysql －ｐhunter2"])
def test_secret_flags_in_fullwidth_forms_are_hidden(text):
    out = phone_view.redact(text)
    assert "hunter2" not in out and "[hidden]" in out, out


PLAIN_FLAGS = [
    "-p 8080",
    "docker run -p 8080:80 web",
    "serve --port 8080",
    "ls -a",
    "ls -la /tmp",
    "psql -h db -p 5432 -U bob shop",
    "mysql -u root -P 3306 -h db shop",
    "redis-cli -h cache -p 6379 ping",
    "curl -s -o out.html https://x.ch",
    "mysql -u root -p",
    "mysqlx -p 33060",
    "run --verbose --author bob",
    "cd /srv && mysql -u root shop",
    "curl -sS -o out.html https://x.ch",
    "mysql -u root -p && curl -s https://x.ch",
]


@pytest.mark.parametrize("text", PLAIN_FLAGS)
def test_plain_flags_stay(text):
    assert phone_view.redact(text) == text


@pytest.mark.parametrize(
    "unit",
    ["--password ", "--x ", "--password=", "mysql -p\n", "mysql -u -u -u\n", '--token "', "-- "]
    + ["mysql ", "curl -su ", "mysql -x ", "a/b/c/", "a\\b\\mysqlx ", "\u2013token "],
)
def test_flag_scan_is_linear(unit):
    """A generous bound: a quadratic scan of 64 KiB takes minutes, the linear one milliseconds."""
    import time

    text = unit * (65536 // len(unit)) + "\ncurl -u bob:hunter2"
    t0 = time.perf_counter()
    out = phone_view._hide_flag_values(text)
    assert time.perf_counter() - t0 < 5
    assert out.endswith("\ncurl -u [hidden]") and "hunter2" not in out


FULLWIDTH = ["ｐａｓｓｗｏｒｄ=hunter2", "ＴＯＫＥＮ: hunter2", "Ａｐｉ_Ｋｅｙ = hunter2"]


@pytest.mark.parametrize("text", FULLWIDTH)
def test_fullwidth_names_are_hidden_in_free_text(text):
    out = phone_view.redact(text)
    assert "hunter2" not in out and "[hidden]" in out, out
    assert phone_view._has_secret(text.encode())
    assert phone_view.redact(out) == out  # stable: the results check scrubs twice


def test_text_without_secrets_keeps_its_own_characters():
    assert phone_view.redact("Ｈｅｌｌｏ ﬁle x²") == "Ｈｅｌｌｏ ﬁle x²"


OVER_REDACTED = ["auth: none", "signature: approved", "credential: rotated", "token-count: 512"]


@pytest.mark.parametrize("text", OVER_REDACTED)
def test_secret_words_in_free_text_over_redact(text):
    """Known and accepted (fail safe): a secret-name word hides the value even when it is harmless."""
    name = text.split(":")[0]
    assert phone_view.redact(text) == f"{name}: [hidden]"


SECRET_PARAMS = ["pwd", "pass", "otp", "pin", "Password", "api_key", "authToken", "ｐｗｄ"]


@pytest.mark.parametrize("param", SECRET_PARAMS)
def test_secret_query_params_are_hidden(param):
    url = phone_view.safe_url(f"https://example.ch/a?{urllib.parse.quote(param)}=s3cr3tv4lue&page=2")
    assert url and "s3cr3tv4lue" not in url and "page=2" in url, url


def test_ordinary_query_params_stay():
    url = phone_view.safe_url("https://example.ch/a?page=2&author=bob&shipping=fast")
    assert url == "https://example.ch/a?page=2&author=bob&shipping=fast"


@pytest.mark.parametrize(
    "label",
    [
        "Passwort",
        "passwrd",
        "key2",
        "pin1",
        "otp6",
        "pwd2",
        "X-Api-Key",
        "DB_PASS",
        "ＴＯＫＥＮ",
        "Ｐassword",
    ],
)
def test_more_secret_names(label):
    assert phone_view.secret_name(label), label


# ---- redact: one pipeline iterated to a fixed point (clean, NFKC, scrub raw, scrub NFKC) ----
def test_redact_comment_joined_secret_is_not_left_after_cleaning():
    from orch.phone_view import redact

    for text in ("pass<!-- x -->word=hunter2", "tok<!---->en=abc123xyz", "ghp_<!-- c -->" + "a" * 24):
        out = redact(text)
        assert "hunter2" not in out and "abc123xyz" not in out and "a" * 24 not in out, (text, out)


def test_redact_property_no_secret_survives_confusables_comments_fullwidth():
    import random
    import unicodedata

    from orch.phone_view import redact

    rnd = random.Random(1137)
    names = ["password", "passwd", "secret", "token", "api_key", "smtp_pass", "ADMIN_PASS", "Authorization"]
    names += [
        "smtpPass",
        "dbPass",
        "api.key",
        "client-secret",
        "authToken",
        "x.api-key",
        "ADMIN.PASS",
        "apiKey",
    ]
    full = lambda s: "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)  # noqa: E731
    for i in range(400):
        value = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(rnd.randint(8, 16)))
        value = f"Zq{i}x{value}"
        name = rnd.choice(names)
        # split the name or the value with a hidden comment / zero-width char, or write them fullwidth
        cut = rnd.randint(1, len(name) - 1)
        spelled = rnd.choice(
            [
                name + "=" + value,
                full(name) + "=" + value,
                name[:cut] + "<!-- c -->" + name[cut:] + "=" + value,
                name[:cut] + "​" + name[cut:] + ": " + value,
                name + "=" + full(value),
                name + "=" + value[:5] + full(value[5:]),  # mixed width
                full(name[:cut]) + name[cut:] + "=" + value,
                f"cfg: {name}={value}",
                f"a=1,{name}={value}",
                f'{{"{name}": "{value}"}}',  # JSON
                f"cfg['{name}'] = '{value}'",  # a subscript
                f"{name} := {value}",
            ]
        )
        out = redact(spelled)
        assert value not in out and unicodedata.normalize("NFKC", value) not in unicodedata.normalize(
            "NFKC", out
        ), (
            spelled,
            out,
        )


def test_redact_is_idempotent_and_hides_when_not_stable(monkeypatch):
    from orch import phone_view

    assert phone_view.redact(phone_view.redact("password=hunter2 ok")) == phone_view.redact(
        "password=hunter2 ok"
    )
    monkeypatch.setattr(phone_view, "_round", lambda t: t + "x")  # never settles
    assert phone_view.redact("hello") == phone_view.HIDDEN


def test_redact_secret_only_in_the_raw_form_is_hidden():
    from orch.phone_view import redact

    # a ligature/compat form that NFKC rewrites: the raw form holds the secret pattern
    assert "hunter2" not in redact("ｐassword=hunter2") and "hunter2" not in redact("password＝hunter2")


@pytest.mark.parametrize("name", ["smtp_pass", "ADMIN_PASS", "db_pass", "Pass", "pass"])
def test_pass_label_names_are_secrets(name):
    from orch.phone_view import secret_name

    assert secret_name(name)


@pytest.mark.parametrize("name", ["Pass/Fail", "pass rate", "pass count", "Passed", "Passage", "pass_rate"])
def test_pass_test_result_labels_stay_visible(name):
    from orch.phone_view import secret_name

    assert not secret_name(name)


@pytest.mark.parametrize("name", ["smtpPass", "dbPass", "api.key", "client-secret", "authToken", "x.pass"])
def test_redact_one_name_predicate_camel_dotted_and_dashed_names(name):
    from orch.phone_view import redact

    assert "hunter2" not in redact(f"{name}=hunter2") and "hunter2" not in redact(f"{name}: hunter2")


def test_redact_forms_that_disagree_hide_the_whole_value(monkeypatch):
    from orch import phone_view

    real = phone_view._scrub_text
    # a scrub that only sees the NFKC form of the text: raw and NFKC disagree -> the whole value is hidden
    monkeypatch.setattr(phone_view, "_scrub_text", lambda t: real(t) if t.isascii() else t)
    assert phone_view.redact("\uff50assword=hunter2") == phone_view.HIDDEN


def test_redact_linear_on_long_name_runs():
    import time

    from orch.phone_view import redact

    t0 = time.monotonic()
    for text in ("a=" * 20000, "a.b" * 20000, "pass-" * 8000, "a: " * 15000):
        redact(text)
    assert time.monotonic() - t0 < 5


# ---- review #497: each finding with its concrete strings ----


def _evidence_files(proj, new_ticket, files, title="Deploy"):
    """A ticket whose one task holds the given (name, bytes) proof files, role result."""
    tid = new_ticket(title)
    evs = []
    for name, data in files:
        p = proj / ".orch/tickets" / tid / "evidence" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        evs.append({"type": "file", "ref": f".orch/tickets/{tid}/evidence/{name}", "role": "result"})

    def op(t):
        t["checklist"] = [{"id": "c1", "text": "Deploy", "done": True, "evidence": evs}]

    tickets.apply_op(proj, tid, op)
    return tid


USERINFO = [
    ("DATABASE_URL=postgres://admin:hunter2@db:5432/shop", "DATABASE_URL=[hidden]db:5432/shop"),
    ("redis-cli -u redis://:hunter2@cache", "redis-cli -u [hidden]cache"),
    ("git clone https://bob:hunter2@git.example.ch/x.git", "git clone [hidden]git.example.ch/x.git"),
    ("curl https://bob:hunter2@x.ch/api", "curl [hidden]x.ch/api"),
    ("db: postgres://u:p@ss@db/x", "db: [hidden]db/x"),  # an @ in the password: up to the last one
]


@pytest.mark.parametrize("text, want", USERINFO)
def test_h3_url_userinfo_in_free_text_is_hidden(text, want):
    assert phone_view.redact(text) == want
    assert phone_view._has_secret(text.encode())


@pytest.mark.parametrize(
    "text", ["see https://x.ch:8080/a@b", "mail bob@x.ch", "ssh://git@host:22/x", "a://b"]
)
def test_h3_urls_without_a_password_stay(text):
    assert phone_view.redact(text) == text


H4_FORMS = [
    "pass\u200bword=hunter2",  # ZWSP: a text viewer shows password=hunter2
    "tok<!---->en=hunter2",  # in an .html/.md artifact the comment vanishes when shown
    "ｐａｓｓｗｏｒｄ=hunter2",
    "sshpass -p hunter2 ssh me@host",
    "deploy --token hunter2",
    "curl -u bob:hunter2 https://x.ch",
    "CREATE USER bob WITH PASSWORD 'hunter2';",
]


VALUE = "Xk93-pq7Lm-aa21"  # a stored key value, written in prose without any label


def test_h5_stored_values_never_leave_in_any_text_of_the_view(proj, run, new_ticket, conn):  # noqa: F811
    keystore.add(proj, "db-cred", "token", VALUE)
    tid = new_ticket(f"Rotate {VALUE} today")
    run("check", "add", tid, f"Use {VALUE} for the db")
    run("log", tid, f"Rotated the DB credentials, new value {VALUE}")
    # evidence and artifact files: covered by the backlog upload-gate PR (phone_view.attachments), not #497

    def op(t):
        t["summary"] = f"Done, new value {VALUE}"
        # url/file evidence: covered by the backlog upload-gate PR (phone_view.attachments), not #497

    tickets.apply_op(proj, tid, op)
    code, _, err = run("relay", "send", "phones", "Finished", "--ticket", tid, "--update", "result")
    assert code == 0, err
    assert VALUE not in json.dumps(conn.sent, ensure_ascii=False), "no message at all carries it"
    msg = _result_message(conn)
    assert "[hidden: db-cred]" in json.dumps(msg, ensure_ascii=False)
    tv = msg["body"]["ticket_view"]
    assert_valid(tv)
    assert tv["title"] == "Rotate [hidden: db-cred] today", "hidden in place, not the closed view"
    assert "[hidden: db-cred]" in msg["body"]["update"]["title"]
    t = tickets.load(proj, tid)
    h = phone_results.value_hider(proj)
    pushed = phone_view.result_text(t, h)
    assert VALUE not in pushed and "[hidden: db-cred]" in pushed
    assert VALUE not in json.dumps(phone_view.light_view(proj, t), ensure_ascii=False)


def test_h5_a_value_left_in_the_finished_view_closes_it(proj, new_ticket):
    keystore.add(proj, "db-cred", "token", VALUE)
    tid = new_ticket("Plain")
    att = {"kind": "link", "title": f"x {VALUE}", "url": "https://x.ch/", "at": "2026-11-11T08:00:00Z"}
    view = phone_view.build(proj, tickets.load(proj, tid), [att])  # a caller's attachment, not hidden
    assert VALUE not in json.dumps(view) and view["title"] == "Ticket" and view["attachments"] == []


@pytest.mark.parametrize(
    "text, want",
    [
        ("CREATE USER bob WITH PASSWORD 'hunter2'", "CREATE USER bob WITH PASSWORD [hidden]"),
        ("ALTER USER x IDENTIFIED BY 'hunter2'", "ALTER USER x IDENTIFIED BY [hidden]"),
        ("GRANT ALL TO x IDENTIFIED BY hunter2;", "GRANT ALL TO x IDENTIFIED BY [hidden]"),
        ("machine h login u password hunter2", "machine h login u password [hidden]"),
        ("machine h\n  login u\n  password hunter2", "machine h\n  login u\n  password [hidden]"),
    ],
)
def test_m2_labelled_values_without_a_separator(text, want):
    assert phone_view.redact(text) == want
    assert phone_view.redact(want) == want


@pytest.mark.parametrize("text", ["Reset the password for bob", "The password reset flow works", "password"])
def test_m2_password_in_prose_stays(text):
    assert phone_view.redact(text) == text


@pytest.mark.parametrize(
    "text, want",
    [
        ("password: correct horse battery staple", "password: [hidden]"),
        ("Cookie: a=1; sessionid=SECRET; csrftoken=x", "Cookie: [hidden]"),
        ("Set-Cookie: sid=SECRET; Path=/; HttpOnly", "Set-Cookie: [hidden]"),
        ("cookie=a=1; sid=SECRET", "cookie=[hidden]"),
        ("token: abc def\nnext line stays", "token: [hidden]\nnext line stays"),
    ],
)
def test_m3_colon_and_cookie_values_hide_to_the_end_of_the_line(text, want):
    assert phone_view.redact(text) == want


M4_NAMES = ["SSHPASS", "DBPASS", "ADMINPASS", "SMTPPASS", "sessionid", "SESSIONID", "PHPSESSID"]
M4_NAMES += ["passcode", "pw", "db_pw", "totp", "sessionId"]


@pytest.mark.parametrize("name", M4_NAMES)
def test_m4_compound_secret_names(name):
    assert phone_view.secret_name(name)
    assert "hunter2" not in phone_view.redact(f"{name}=hunter2")


@pytest.mark.parametrize("key", ["tok<!---->en", "to\u200bken", "pass\u200bword"])
def test_m5_labels_are_judged_after_cleaning(key):
    assert phone_view.secret_name(key)
    d = doc(blocks=[{"type": "kv", "items": [{"key": key, "value": "hunter2"}]}])
    out = phone_results.prepare(Path("."), [cand(1, "2026-11-11T08:00:00Z") | {"doc": d}], h=NOHIDE)
    assert "hunter2" not in json.dumps(out)


@pytest.mark.parametrize(
    "secret",
    ["eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig12345", "sk_live_4f9d7a1c8b2e6053aa11"],
)
def test_m6_a_query_key_that_is_a_secret_is_hidden(secret):
    url = phone_view.safe_url(f"https://app.ch/cb?{secret}&page=2")
    assert url and secret[:8] not in url and "page=2" in url, url


WEBHOOKS = [
    ("https://hooks." + "slack.com/services/T0ABCDEF1/B0ABCDEF1/" + "X" * 24, "XXXXXXXX"),
    ("https://discord.com/api/webhooks/123456789012345678/AbCdEf-ghIJ_klMNop", "AbCdEf-ghIJ"),
    ("https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage", "AAHdqTcv"),
]


@pytest.mark.parametrize("url, token", WEBHOOKS)
def test_m7_webhook_tokens_in_url_paths(url, token):
    assert token not in phone_view.redact(f"posted to {url}")
    out = phone_view.safe_url(url)
    assert out and token not in out, out


TOKEN_SHAPES = [
    "AIza" + "B" * 35,
    "-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBF0\n-----END PGP PRIVATE KEY BLOCK-----",
    "hf_" + "a" * 34,
    "npm_" + "a" * 36,
    "pypi-AgE" + "a" * 60,
    "SG." + "a" * 22 + "." + "b" * 43,
    "dop_v1_" + "a" * 64,
]


@pytest.mark.parametrize("token", TOKEN_SHAPES)
def test_m9_token_shapes(token):
    assert phone_view.redact(f"key {token} here") == "key [hidden] here"


@pytest.mark.parametrize("url", ["http://h:99999/", "http://h:x/", "https://h:-1/a"])
def test_l1_a_bad_port_is_no_url(url):
    assert phone_view.safe_url(url) is None


def test_l2_a_token_cut_at_the_limit_leaves_no_prefix():
    tok = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    text = ("word " * 5000)[: phone_view.TEXT_CUT - 10] + tok  # the cut falls inside the token
    out = phone_view.redact(text)
    assert "ghp_" not in out and out.endswith("[hidden]")
    assert phone_view.redact(out) == out


@pytest.mark.parametrize(
    "text, gone",
    [
        ('password="ab\\"cdefgh" rest', "cdefgh"),  # an escaped quote inside
        ("password=`hunter 2` rest", "2`"),  # backticks
        ('password="hunter 2', "2"),  # never closed: to the end of the line
    ],
)
def test_l3_quoted_values(text, gone):
    out = phone_view.redact(text)
    assert gone not in out and "hunter" not in out, out


def test_l9_status_outside_the_contract_is_open(proj, new_ticket):
    t = tickets.load(proj, new_ticket("Odd"))
    t["status"] = "<b>weird</b>"
    assert phone_view.build(proj, t, [])["status"] == "open"
    assert phone_view.light_view(proj, t)["status"] == "open"


@pytest.mark.parametrize(
    "unit",
    ["a.", "a+b://", "x://a:", "x://:a@", "login a ", "password ", "identified by ", "<!--", "<!--a-->"]
    + ['"', "'a", "-", "a\\", "bot1:", "token: a\n", '"a": ', "/services/T", "/api/webhooks/1"],
)
def test_new_patterns_are_linear(unit):
    """A generous bound: a quadratic scan of 64 KiB takes minutes, the linear one milliseconds."""
    import time

    from orch.text import clean_untrusted

    text = unit * (65536 // len(unit))
    t0 = time.perf_counter()
    phone_view._scrub_text(text)
    phone_view._has_secret(text.encode())
    phone_view.redact(text)
    clean_untrusted(text, 10**9)
    assert time.perf_counter() - t0 < 5


def test_clean_untrusted_unchanged_by_the_fast_path():
    """The distinct-character judge and the search up to the last `-->` give what the plain way gives."""
    import random

    from orch import text as text_mod

    def slow(t):
        import unicodedata

        t = unicodedata.normalize("NFC", t).replace("\u2028", "\n").replace("\u2029", "\n")
        t = "".join(ch for ch in t if not text_mod._drop(ch))
        while (new := text_mod._COMMENT.sub("", t)) != t:
            t = new
        cut = t.find("<!--")
        return t if cut == -1 else t[:cut]

    rnd = random.Random(497)
    alphabet = ["a", "b", " ", "\n", "<!--", "-->", "<!-", "->", "\u200b", "\u2028", "\x07", "e\u0301", "ﬁ"]
    for _ in range(500):
        t = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))
        assert text_mod.clean_untrusted(t, 10**6) == slow(t), repr(t)
