"""`orch ask` with a card, and `orch review` list, answer, wait, link (the person is the --by name)."""

import json

import pytest

from orch import review, tickets

ME = "human:pat"


@pytest.fixture
def tk(proj, run):
    code, out, _ = run("ticket", "new", "Home layout", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _add(run, tid, *extra, by="agent:x"):
    return run("ask", tid, f"Please look: {extra[1]}", *extra, "--json", "--by", by)


def _draft(run, tid, title="New block"):
    code, out, err = _add(run, tid, "--draft", title, "--then", "I build it.", "--ok", "Build it")
    assert code == 0, out + err
    return json.loads(out)


def _digest(root, tid, qid):
    q = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == qid)
    return tickets.question_digest(q)


def test_review_is_in_help(run, capsys):
    with pytest.raises(SystemExit):
        run("--help")
    out = capsys.readouterr().out
    assert "review" in out and "the page where you answer what waits for you" in out


def test_no_subcommand_starts_the_page(run, monkeypatch):
    from orch import review_server

    seen = []
    monkeypatch.setattr(
        review_server, "serve", lambda args: seen.append((args.port, args.until, args.no_open)) or 0
    )
    assert run("review", "--port", "8500", "--until", "18:30", "--no-open")[0] == 0
    assert seen == [(8500, "18:30", True)]
    monkeypatch.setattr(review_server, "serve", lambda args: 2)
    with pytest.raises(SystemExit) as e:
        run("review")
    assert e.value.code == 2


def test_add_draft_shows_in_list_and_text(tk, run):
    root, tid = tk
    code, out, _ = run(
        "ask", tid, "New block", "--draft", "New block", "--then", "I build it.", "--by", "agent:x"
    )
    assert code == 0 and out.startswith("Asked q1, waiting.")
    q = tickets.load(root, tid)["questions"][0]
    assert q["card"]["kind"] == "draft" and q["shown"]["digest"] and q.get("kind") in (None, "plain")
    code, out, _ = run("review", "list", "--json")
    data = json.loads(out)
    assert data["workspace"] == root.name
    (c,) = [c for c in data["cards"] if c["ticket"] == tid]
    assert c["key"] == "q1" and c["kind"] == "draft" and c["digest"] == _digest(root, tid, "q1")
    code, out, _ = run("review", "list")
    assert "1 thing waits on you." in out and "New block" in out


def test_add_choose_with_files_and_suggest(tk, run):
    root, tid = tk
    (root / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    (root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\nB")
    code, out, err = _add(
        run, tid, "--choose", "Which layout?", "--option", "A=As today:a.png", "--option",
        "B=Recent first:b.png", "--option", "C=Questions: first", "--suggest", "B", "--then", "I build it.",
    )  # fmt: skip
    assert code == 0, out + err
    q = json.loads(out)
    assert q["options"] == ["A", "B", "C"] and q["recommended"] == "B"
    opts = q["card"]["preview"]["options"]
    assert opts[0]["preview"]["src"].startswith("reviewed/") and opts[2]["title"] == "Questions: first"
    assert "preview" not in opts[2]


def test_add_before_after_file_link_and_plan(tk, run):
    root, tid = tk
    (root / "o.png").write_bytes(b"\x89PNG\r\n\x1a\n1")
    (root / "n.png").write_bytes(b"\x89PNG\r\n\x1a\n2")
    (root / "p.md").write_text("First para.\n\nSecond para.\n")
    code, out, err = _add(
        run, tid, "--draft", "Block", "--before", "o.png", "--after", "n.png", "--then", "x"
    )
    assert code == 0 and json.loads(out)["card"]["preview"]["type"] == "compare", out + err
    code, out, err = _add(run, tid, "--plan", "Plan", "--file", "p.md", "--then", "x")
    assert code == 0 and json.loads(out)["card"]["preview"]["paras"] == ["First para.", "Second para."]
    code, out, err = _add(run, tid, "--link", "Site", "--open", "https://example.com/x", "--then", "x")
    assert code == 0, out + err
    assert "signs" not in json.loads(out)["card"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--choose", "T", "--option", "A=One", "--then", "x"],  # one option only
        ["--choose", "T", "--option", "A=One", "--option", "B=Two", "--suggest", "Z", "--then", "x"],
        ["--draft", "T", "--before", "a.png", "--then", "x"],  # before without after
        ["--draft", "T", "--option", "A=One", "--then", "x"],  # option without choose
        ["--link", "T", "--then", "x"],  # a link needs an address
        ["--draft", "T", "--file", "nope.png", "--then", "x"],  # missing file
        ["--draft", "T", "--file", "https://x.test/a.png", "--then", "x"],  # a link as a file
        ["--draft", "T", "--open", "javascript:alert(1)", "--then", "x"],
    ],
)
def test_add_refusals(tk, run, extra):
    root, tid = tk
    code, out, err = _add(run, tid, *extra)
    assert code == 2 and json.loads(out)["code"] == "refused"
    assert tickets.load(root, tid)["questions"] == []


def test_add_needs_then_and_a_ticket(tk, run):
    root, tid = tk
    code, out, _ = _add(run, tid, "--draft", "T")  # --then is needed with a card
    assert code == 2 and "--then" in out
    code, out, _ = _add(run, "t_nonexistent", "--draft", "T", "--then", "x")
    assert code == 2


def test_answer_ok_resumes_helper_and_records(tk, run, monkeypatch):
    root, tid = tk
    q = _draft(run, tid)
    seen = []
    monkeypatch.setattr("orch.runs_live.pass_answer", lambda *a, **k: seen.append((a, k)))
    code, out, err = run(
        "review", "answer", tid, q["id"], "--verdict", "ok", "--digest", _digest(root, tid, q["id"]),
        "--via", "page", "--by", ME, "--json",
    )  # fmt: skip
    assert code == 0, out + err
    e = json.loads(out)
    assert e["decision"]["action"] == "approve" and e["answered_by"] == ME and e["via"] == "page"
    assert len(seen) == 1 and seen[0][1] == {"proven": True}
    code, out, _ = run("review", "list", "--json")
    assert json.loads(out)["cards"] == []


def test_answer_talk_with_note_and_answered_list(tk, run):
    root, tid = tk
    q = _draft(run, tid)
    note = json.dumps({"changes": ["Shorter title."], "pins": [{"n": 1, "on": "title", "text": "here"}]})
    code, out, err = run(
        "review", "answer", tid, q["id"], "--verdict", "talk", "--note", note, "--by", ME, "--json"
    )
    assert code == 0, out + err
    code, out, _ = run("review", "list", "--answered", "--json")
    (e,) = json.loads(out)
    assert e["ticket"] == tid and e["by"] == ME and e["via"] == "cli" and e["at"]
    d = e["decision"]
    assert d["action"] == "send_back" and d["changes"] == ["Shorter title."] and d["pins"][0]["n"] == 1
    assert {"card", "shown", "id"} <= set(e)
    code, out, _ = run("review", "list", "--answered")
    assert "Answered (newest first)" in out and "Send back" in out


def test_answer_choose_picked_and_change_again(tk, run):
    root, tid = tk
    code, out, _ = _add(
        run, tid, "--choose", "Which?", "--option", "A=One", "--option", "B=Two", "--then", "x"
    )
    qid = json.loads(out)["id"]
    code, out, err = run("review", "answer", tid, qid, "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "refused"  # pick one
    run("review", "answer", tid, qid, "--verdict", "ok", "--picked", "A", "--by", ME)
    code, out, err = run(
        "review", "answer", tid, qid, "--verdict", "ok", "--picked", "B", "--by", ME, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out)["decision"]["replaces"] == qid


def test_answer_digest_changed(tk, run):
    root, tid = tk
    q = _draft(run, tid)
    for d in ("0" * 64, "nonsense"):
        code, out, _ = run(
            "review", "answer", tid, q["id"], "--verdict", "ok", "--digest", d, "--by", ME, "--json"
        )
        assert code == 2 and json.loads(out)["code"] == "changed"
    assert tickets.load(root, tid)["questions"][0]["answer"] is None


def test_answer_agent_acting_as_person_needs_person(tk, run, monkeypatch):
    root, tid = tk
    q = _draft(run, tid)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _ = run("review", "answer", tid, q["id"], "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "needs_person"
    code, out, _ = run("review", "answer", tid, q["id"], "--verdict", "ok", "--by", "agent:x", "--json")
    assert code == 2 and json.loads(out)["code"] == "needs_person"
    assert tickets.load(root, tid)["questions"][0]["answer"] is None


def test_answer_too_large_note_and_unknown_keys(tk, run):
    root, tid = tk
    q = _draft(run, tid)
    big = json.dumps({"words": {"text": "x" * (review.MAX_NOTE_BYTES + 10)}})
    code, out, _ = run(
        "review", "answer", tid, q["id"], "--verdict", "talk", "--note", big, "--by", ME, "--json"
    )
    assert code == 2 and json.loads(out)["code"] == "too_large"
    code, out, _ = run("review", "answer", tid, "q9", "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "not_found"
    code, out, _ = run("review", "answer", tid, "bogus", "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "not_found"
    code, out, _ = run("review", "answer", tid, q["id"], "--verdict", "talk", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "refused"  # words alone need something to change


def _in_review(root, tid):
    tickets.check_add(root, tid, "Write it", "agent:claude")
    tickets.set_status(root, tid, "review", "agent:claude")


def test_answer_check_card_ok_and_changes(tk, run):
    root, tid = tk
    _in_review(root, tid)
    code, out, _ = run("review", "list", "--json")
    (c,) = [c for c in json.loads(out)["cards"] if c["key"] == "review"]
    code, out, err = run(
        "review", "answer", tid, "review", "--verdict", "ok", "--digest", "f" * 64, "--by", ME, "--json"
    )
    assert code == 2 and json.loads(out)["code"] == "changed"
    code, out, err = run(
        "review", "answer", tid, "review", "--verdict", "ok", "--digest", c["digest"], "--by", ME, "--json"
    )
    assert code == 0, out + err
    assert tickets.load(root, tid)["status"] == "done"


def test_answer_check_send_back_needs_note(tk, run):
    root, tid = tk
    _in_review(root, tid)
    code, out, _ = run("review", "answer", tid, "review", "--verdict", "no", "--by", ME, "--json")
    assert code == 2 and json.loads(out)["code"] == "refused"
    note = json.dumps({"changes": ["Redo the test."]})
    code, out, err = run(
        "review", "answer", tid, "review", "--verdict", "talk", "--note", note, "--by", ME, "--json"
    )
    assert code == 0, out + err
    assert tickets.load(root, tid)["status"] not in ("review", "done")


def test_ticket_show_lists_what_applies_now_and_the_answers(tk, run):
    root, tid = tk
    q = _draft(run, tid)
    code, out, _ = run("ticket", "show", tid)
    assert "Needs an answer" in out and "What applies now" not in out
    run("review", "answer", tid, q["id"], "--verdict", "ok", "--by", ME)
    code, out, _ = run("ticket", "show", tid)
    assert "What applies now" in out and "Build it" in out and "Answered q1:" in out
    assert "Decisions" not in out and "History (newest first)" not in out


def test_ticket_show_plain_answer_is_listed(tk, run):
    root, tid = tk
    run("ask", tid, "Ship it?", "--by", "agent:x")
    run("answer", tid, "q1", "Yes", "--by", ME)
    code, out, _ = run("ticket", "show", tid)
    assert "Answered q1: Ship it? - Yes" in out and "What applies now" not in out


def test_wait_returns_the_answer_and_times_out(tk, run, monkeypatch):
    root, tid = tk
    q = _draft(run, tid)
    monkeypatch.setattr("orch.cli_review.time.sleep", lambda s: None)
    code, out, err = run("review", "wait", tid, "--timeout", "0", "--json")
    assert code == 2 and json.loads(out)["code"] == "busy"
    run("review", "answer", tid, q["id"], "--verdict", "ok", "--via", "phone", "--by", ME)
    code, out, _ = run("review", "wait", tid)
    assert code == 0 and "(pat, phone," in out
    code, out, _ = run("review", "wait", tid, "q7", "--json")
    assert code == 2 and json.loads(out)["code"] == "not_found"


def test_wait_polls_until_answered(tk, run, monkeypatch):
    root, tid = tk
    q = _draft(run, tid)
    calls = []

    def fake_sleep(_s):
        calls.append(1)
        if len(calls) == 2:
            tickets.answer(root, tid, q["id"], "Yes", ME, "cli")

    monkeypatch.setattr("orch.cli_review.time.sleep", fake_sleep)
    code, out, _ = run("review", "wait", tid, q["id"])
    assert code == 0 and out.startswith("Yes (pat, cli,") and len(calls) == 2


def test_link_without_a_server(tk, run):
    code, out, _ = run("review", "link")
    assert code == 0 and "No review page runs. Start it in your terminal: orch review" in out
    code, out, _ = run("review", "link", "--json")
    assert json.loads(out)["running"] is False
