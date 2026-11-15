"""Adversarial tests for the Review stack (security review of feature/review-stack, 15 Nov 2026).

Each test pins a finding that is fixed (the attack is refused).
"""

import hashlib
import json
import sys

import pytest
from test_review_server import TOKENS, _reviewed, open_session, req, srv, ws  # noqa: F401 - shared helpers and fixtures

from orch import review_server, tickets

PNG = b"\x89PNG\r\n\x1a\nXX"


def _card(root, run, *extra):
    code, out, _ = run("ticket", "new", "Q", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    args = extra or ("--draft", "Block", "--then", "I build it.")
    code, out, err = run("ask", tid, "Block", *args, "--json", "--by", "agent:x")
    assert code == 0, out + err
    q = json.loads(out)
    return tid, q["id"], tickets.question_digest(q)


def test_agent_cannot_answer_a_review_card_with_plain_answer(ws, run):  # noqa: F811
    tid, qid, _ = _card(ws, run)
    code, out, err = run("answer", tid, qid, "Approve", "--by", "agent:other", "--json")
    assert code != 0 and tickets.load(ws, tid)["questions"][0]["answer"] is None, out + err


# ------------------------------------------------------------------ Q2: page session and origin checks


def test_answer_from_another_loopback_port_is_refused(srv, ws, run):  # noqa: F811
    """A page on another localhost port (an agent's dev server) the person has open: the browser sends the
    cookie, Origin is that port, Sec-Fetch-Site same-site. Refused."""
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = _card(ws, run)
    body = {"id": f"core:q:{tid}:{qid}", "digest": d, "verdict": "ok", "picked": None, "note": None}
    for h in (
        {"Cookie": ck, "Origin": "http://127.0.0.1:9"},
        {"Cookie": ck, "Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-site"},
        {"Cookie": ck, "Origin": "null"},
    ):
        assert req(port, "POST", "/api/answer", body, headers=h)[0] == 403, h
    # a simple-request CSRF (text/plain, no preflight) never reads as JSON
    st, _, _ = req(
        port, "POST", "/api/answer", json.dumps(body), headers={"Cookie": ck, "Content-Type": "text/plain"}
    )
    assert st in (400, 403)
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_session_post_cross_site_and_dns_rebinding(srv, ws):  # noqa: F811
    port = srv.server_address[1]
    tok = TOKENS[port]
    for h, host in (
        ({"Origin": "http://evil.example"}, None),
        ({"Origin": f"http://attacker.test:{port}"}, f"attacker.test:{port}"),  # rebinding: foreign Host
        ({"Sec-Fetch-Site": "cross-site"}, None),
        ({"X-Forwarded-For": "1.2.3.4"}, None),
    ):
        assert req(port, "POST", "/session", {"token": tok}, headers=h, host=host)[0] == 403, h
    # a failed attempt must not have spent a good token for the person... nor handed a cookie out
    st, hd, _ = req(port, "POST", "/session", {"token": tok})
    assert "Set-Cookie" not in hd or st == 200


def test_page_and_files_cannot_be_framed_or_run_script(srv, ws, run):  # noqa: F811
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, _, _ = _card(ws, run)
    sha = "e" * 12
    _reviewed(
        ws, tid, sha, "x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    )
    st, hd, _ = req(port, "GET", "/")
    csp = hd.get("Content-Security-Policy", "")
    assert (
        "frame-ancestors 'none'" in csp
        and "script-src" not in csp
        and "'unsafe-inline'" not in csp.split("style-src")[0]
    )
    st, hd, _ = req(port, "GET", f"/api/file?t={tid}&c={sha}&n=x.svg", headers={"Cookie": ck})
    assert st == 200 and hd["X-Content-Type-Options"] == "nosniff"
    fcsp = [p.strip() for p in hd["Content-Security-Policy"].split(";")]
    assert "sandbox" in fcsp and "default-src 'none'" in fcsp  # bare sandbox: no allow-scripts
    assert "Access-Control-Allow-Origin" not in hd


# ------------------------------------------------------------------ Q3: reviewed copies


def test_reviewed_folder_links_are_refused(srv, ws, run, tmp_path):  # noqa: F811
    """An agent replaces reviewed/<sha12> (or reviewed/ itself) with a link to another folder."""
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, _, _ = _card(ws, run)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.png").write_bytes(PNG)
    rv = ws / ".orch" / "tickets" / tid / "reviewed"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / ("d" * 12)).symlink_to(outside, target_is_directory=True)
    h = {"Cookie": ck}
    assert req(port, "GET", f"/api/file?t={tid}&c={'d' * 12}&n=leak.png", headers=h)[0] == 404
    # a sub folder link inside a real copy
    real = rv / ("f" * 12)
    real.mkdir()
    (real / "sub").symlink_to(outside, target_is_directory=True)
    assert req(port, "GET", f"/api/file?t={tid}&c={'f' * 12}&n=sub/leak.png", headers=h)[0] == 404
    # the ticket folder of another ticket through the t= value: refused by the id pattern
    assert req(port, "GET", f"/api/file?t={tid}/..&c={'f' * 12}&n=leak.png", headers=h)[0] == 404


# ------------------------------------------------------------------ Q4: digests (RULE A)


def test_rule_a_old_formula_still_matches(proj):
    """question_digest of a card-less question equals develop's formula (computed here independently)."""
    q = {"id": "q1", "text": "Go?", "options": ["Yes", "No"], "recommended": None, "kind": "plain",
         "action": None, "answer": None, "answered_by": None, "via": None}  # fmt: skip
    old = {k: q.get(k) for k in ("id", "text", "options", "kind", "action", "recommended")}
    canon = json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert tickets.question_digest(q) == hashlib.sha256(canon.encode()).hexdigest()
    # explicit None values of the new keys do not change it either
    assert tickets.question_digest({**q, "card": None, "shown": None}) == tickets.question_digest(q)


def test_answer_mark_binds_the_decision(proj):
    from orch import history

    a = {"id": "q2", "text": "Ok?", "options": [], "recommended": None, "answer": "Don't do",
         "answered_by": "human:me", "via": "page", "decision": {"action": "dont", "summary": "Don't do",
         "replaced_by": None}}  # fmt: skip
    forged = {**a, "decision": {**a["decision"], "action": "approve"}}
    assert history._digest("answers", a) != history._digest("answers", forged)
    assert history._digest("answers", a) != history._digest("answers", {**a, "card": {"kind": "draft"}})


# ------------------------------------------------------------------ Q5: the kit is found by path


def test_a_planted_orch_ui_on_sys_path_is_not_used(tmp_path, monkeypatch):
    import orch

    plant = tmp_path / "plant" / "orch_ui"
    (plant / "static").mkdir(parents=True)
    (plant / "__init__.py").write_text("")
    (plant / "static" / "review.html").write_text("<p>fake</p>")
    marker = tmp_path / "ran"
    (plant / "origin.py").write_text(
        f"open({str(marker)!r}, 'w').close()\ndef check_request(*a, **k):\n    return None\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path / "plant"))
    for m in [m for m in sys.modules if m == "orch_ui" or m.startswith("orch_ui.")]:
        monkeypatch.delitem(sys.modules, m)
    monkeypatch.setattr(review_server, "_ORIGIN", [])
    review_server._origin_check()
    assert not marker.exists()
    d = review_server.kit_dir()
    assert (
        d is None
        or d.resolve().parent.parent == __import__("pathlib").Path(orch.__file__).resolve().parent.parent
    )


def test_record_answered_refuses_an_agent_entry_with_a_card(tmp_path):
    """Delta review L2: record_answered checks the person itself (not only its callers)."""

    from orch import tickets

    with pytest.raises(tickets.Refused):
        tickets.record_answered(
            tmp_path, "t_x", {"answer": "Use C", "card": {"kind": "choice"}}, "agent:x", "cli"
        )
