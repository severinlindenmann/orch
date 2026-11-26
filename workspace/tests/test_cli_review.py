"""`orch ask` with a card, and `orch review` list, answer, wait, link (the person is the --by name)."""

import json
from datetime import UTC, datetime

import pytest

from orch import net, review, tickets

ME = "human:pat"


@pytest.fixture
def clock(monkeypatch):
    """One held local clock for what a history line stamps (tickets.now) and what `when` compares it with
    (ORCH-1183: a test that crossed midnight between the accept and the look read 'yesterday 23:59').
    Call it with a local time to move the clock."""
    held = {}

    def at(local: str):
        held["t"] = datetime.fromisoformat(local).astimezone()

    at("2026-11-21T12:00:00")
    monkeypatch.setattr(tickets, "now", lambda: held["t"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    monkeypatch.setattr(net, "_now", lambda: held["t"])
    return at


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


def test_drafts_card_three_pages_side_by_side(tk, run):
    """ORCH-257: the card a Fable ticket ends with (runs.drafts_text): three HTML drafts from the ticket's
    files folder, each a page tile on one choose card, one suggested."""
    root, tid = tk
    folder = root / ".orch" / "tickets" / tid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    for x in "abc":
        (folder / f"draft-{x}.html").write_text(f"<!doctype html><a href='#s2'>Next</a><p id='s2'>{x}</p>")
    code, out, err = _add(
        run, tid, "--choose", "Focus mode", "--option", "A=One column:artifacts/draft-a.html",
        "--option", "B=Two panes:artifacts/draft-b.html", "--option", "C=Chat first:artifacts/draft-c.html",
        "--describe", "A=Everything in one list", "--suggest", "B", "--then", "I build the one you pick.",
    )  # fmt: skip
    assert code == 0, out + err
    q = json.loads(out)
    assert q["options"] == ["A", "B", "C"] and q["recommended"] == "B"
    opts = q["card"]["preview"]["options"]
    assert [o["preview"]["type"] for o in opts] == ["page", "page", "page"]
    assert all(o["preview"]["src"].startswith("reviewed/") for o in opts)


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


def test_text_card_reads_the_tickets_own_artifact(tk, run):
    """#2326, #1062: --file artifacts/plan.md was always refused; it reads the ticket's own file, as images
    and pages do. A missing or too large one is still refused."""
    root, tid = tk
    folder = root / ".orch" / "tickets" / tid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.md").write_text("Goal.\n\nSteps.\n")
    (folder / "glance.json").write_text(json.dumps({"headline": "All green"}))
    (folder / "big.md").write_text("x" * (65 * 1024))
    code, out, err = _add(run, tid, "--plan", "Plan", "--file", "artifacts/plan.md", "--then", "x")
    assert code == 0, out + err
    assert json.loads(out)["card"]["preview"]["paras"] == ["Goal.", "Steps."]
    code, out, err = _add(run, tid, "--plan", "Glance", "--file", "artifacts/glance.json", "--then", "x")
    assert code == 0 and json.loads(out)["card"]["preview"]["headline"] == "All green", out + err
    for name in ("artifacts/nope.md", "artifacts/big.md", "artifacts/../../../x.md"):
        code, out, _ = _add(run, tid, "--plan", "Plan", "--file", name, "--then", "x")
        assert code == 2 and json.loads(out)["code"] == "refused", name


def test_card_reads_the_path_artifacts_dir_prints(tk, run):
    """ORCH-1777: .orch/tickets/<this ticket>/artifacts/<name> (what `orch ticket artifacts-dir` prints, also
    with backslashes) is read as artifacts/<name> for text, glance and option cards."""
    root, tid = tk
    folder = root / ".orch" / "tickets" / tid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "intro.md").write_text("New intro.\n\nSecond part.\n")
    (folder / "note.txt").write_text("Plain note.\n")
    (folder / "card.json").write_text(json.dumps({"headline": "Ready."}))
    (folder / "a.md").write_text("Option A.\n")
    for src in (f".orch/tickets/{tid}/artifacts/intro.md", f".orch\\tickets\\{tid}\\artifacts\\intro.md"):
        code, out, err = _add(run, tid, "--draft", "Intro", "--file", src, "--then", "x")
        assert code == 0, out + err
        pv = json.loads(out)["card"]["preview"]
        assert pv["heading"] == "intro.md" and pv["paras"] == ["New intro.", "Second part."]
    code, out, err = _add(
        run, tid, "--draft", "Note", "--file", f".orch/tickets/{tid}/artifacts/note.txt", "--then", "x"
    )
    assert code == 0 and json.loads(out)["card"]["preview"]["paras"] == ["Plain note."], out + err
    code, out, err = _add(
        run, tid, "--draft", "Glance", "--file", f".orch/tickets/{tid}/artifacts/card.json", "--then", "x"
    )
    assert code == 0 and json.loads(out)["card"]["preview"]["headline"] == "Ready.", out + err
    code, out, err = _add(
        run, tid, "--choose", "Pick", "--option", "A=Title:artifacts/a.md", "--option", "B=Two", "--then", "x"
    )
    assert code == 0, out + err
    assert json.loads(out)["card"]["preview"]["options"][0]["preview"]["paras"] == ["Option A."]


@pytest.mark.parametrize(
    "src, says",
    [
        (".orch/tickets/t_other1/artifacts/x.md", "inside a .orch folder"),  # another ticket stays refused
        (".orch/secrets/key.md", "inside a .orch folder"),
        ("artifacts/nope.md", "was not found (checked .orch/tickets/"),
        ("docs/nope.md", "was not found (checked docs/nope.md)"),
        ("artifacts/big.md", "over the 64 KB limit"),
        ("big.md", "over the 64 KB limit"),
    ],
)
def test_text_card_refusals_name_the_cause(tk, run, src, says):
    """ORCH-1777: one message per cause instead of 'was not found or is too large'."""
    root, tid = tk
    folder = root / ".orch" / "tickets" / tid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "big.md").write_text("x" * (65 * 1024))
    (root / "big.md").write_text("x" * (65 * 1024))
    code, out, _ = _add(run, tid, "--draft", "T", "--file", src, "--then", "x")
    assert code == 2 and json.loads(out)["code"] == "refused"
    error = json.loads(out)["error"]
    assert says in error and "or is too large" not in error, error
    assert tickets.load(root, tid)["questions"] == []


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


def test_answer_ok_resumes_helper_and_records(tk, run, monkeypatch, person_grant):
    root, tid = tk
    q = _draft(run, tid)
    seen = []
    monkeypatch.setattr("orch.runs_live.pass_answer", lambda *a, **k: seen.append((a, k)))
    person_grant(root)  # a signed-in page (ORCH-582: only a person picks a draft)
    code, out, err = run(
        "review", "answer", tid, q["id"], "--verdict", "ok", "--digest", _digest(root, tid, q["id"]),
        "--via", "page", "--by", ME, "--json",
    )  # fmt: skip
    assert code == 0, out + err
    e = json.loads(out)
    assert e["decision"]["action"] == "approve" and e["answered_by"] == ME and e["via"] == "page"
    assert len(seen) == 1 and seen[0][1] == {}
    code, out, _ = run("review", "list", "--json")
    assert json.loads(out)["cards"] == []


def test_answer_talk_with_note_and_answered_list(tk, run, person_grant):
    root, tid = tk
    q = _draft(run, tid)
    note = json.dumps({"changes": ["Shorter title."], "pins": [{"n": 1, "on": "title", "text": "here"}]})
    person_grant(root)
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
    # every Answered card can name its ticket and what was asked (ORCH-172: no bare "Answered" cards)
    assert e["ticket_title"] == "Home layout" and e["ticket_key"] and e["text"] == "Please look: New block"
    code, out, _ = run("review", "list", "--answered")
    assert "Answered (newest first)" in out and "Send back" in out


def test_a_long_send_back_note_reaches_the_helper_whole(tk, run, person_grant, monkeypatch):
    """#1174, #1775: a send-back comment was saved cut off after about 80 characters ("…"); the answer and
    the run input (runs_live.pass_answer sends the answer) are what the helper reads: the whole comment."""
    from orch import runs_live

    root, tid = tk
    q = _draft(run, tid)
    passed = []
    monkeypatch.setattr(runs_live, "pass_answer", lambda root, tid, entry, who: passed.append(entry))
    words = "Make the draft more detailed: " + " ".join(f"point{i} needs a line of its own" for i in range(9))
    assert 280 < len(words) <= 500
    person_grant(root)
    code, out, err = run(
        "review", "answer", tid, q["id"], "--verdict", "talk", "--note", json.dumps({"text": words}),
        "--by", ME, "--via", "dashboard", "--json",
    )  # fmt: skip
    assert code == 0, out + err
    saved = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == q["id"])
    assert saved["answer"] == f"Send back for changes: {words}." and "…" not in saved["answer"]
    assert [e["answer"] for e in passed] == [saved["answer"]]


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


def test_answer_choose_in_own_words_is_the_answer_not_a_send_back(tk, run):
    """ORCH-246: words on a question with options are the person's answer, as on Home's "Write your own"."""
    root, tid = tk
    code, out, _ = _add(
        run, tid, "--choose", "Which?", "--option", "A=One", "--option", "B=Two", "--then", "x"
    )
    qid = json.loads(out)["id"]
    note = json.dumps({"changes": ["Neither: use a drop-down."]})
    code, out, err = run(
        "review", "answer", tid, qid, "--verdict", "talk", "--note", note, "--by", ME, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out)["decision"]["summary"] == "Neither: use a drop-down."
    q = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == qid)
    assert "Send back" not in str(q["answer"]) and "drop-down" in str(q["answer"])


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


def test_unattended_review_leaves_the_decision_for_the_terminal(tk, run, monkeypatch):
    root, tid = tk
    _in_review(root, tid)
    code, out, _ = run("review", "answer", tid, "review", "--verdict", "ok", "--json")
    assert code == 2 and json.loads(out)["code"] == "needs_person"
    code, _, err = run("review", "undo", tid)
    assert code == 2 and "Only a person" in err
    assert tickets.load(root, tid)["status"] == "review"
    monkeypatch.setattr(tickets.term, "is_terminal", lambda stream: True)
    monkeypatch.setenv("ORCH_RUN", "r_test")
    code, out, _ = run("review", "answer", tid, "review", "--verdict", "ok", "--json")
    assert code == 2 and json.loads(out)["code"] == "needs_person"
    monkeypatch.delenv("ORCH_RUN")
    code, out, err = run("review", "answer", tid, "review", "--verdict", "ok")
    assert code == 0, out + err
    assert tickets.load(root, tid)["status"] == "done"


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


def _in_review(root, tid, *, finished=True):
    tickets.check_add(root, tid, "Write it", "agent:claude")
    if finished:
        tickets.check_done(root, tid, "c1", ['{"type":"note","ref":"wrote it"}'], "agent:claude")
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


def _check_card(run):
    code, out, _ = run("review", "list", "--json")
    return next(c for c in json.loads(out)["cards"] if c["key"] == "review")


def _ok(run, tid, digest):
    code, out, err = run(
        "review", "answer", tid, "review", "--verdict", "ok", "--digest", digest, "--by", ME, "--json"
    )
    return code, json.loads(out) if out.strip() else {}, err


def test_a_second_looks_good_says_it_is_done_already(tk, run, clock):
    """ORCH-548: a Looks good saved twice (another tab, the phone, a page that sent its held answers again)
    is not a failure: it says the ticket is Done, who did it and when (code decided), never "not waiting for
    your review"."""
    root, tid = tk
    _in_review(root, tid)
    digest = _check_card(run)["digest"]
    assert _ok(run, tid, digest)[0] == 0
    code, out, _ = _ok(run, tid, digest)
    assert code == 2 and out["code"] == "decided", out
    assert out["error"].startswith("Already Done: you accepted it today "), out
    assert tickets.load(root, tid)["status"] == "done"


@pytest.mark.parametrize(
    ("accepted", "looked", "said"),
    [
        ("2026-11-21T23:59:40", "2026-11-21T23:59:40", "today 23:59"),
        ("2026-11-21T23:59:59", "2026-11-21T23:59:59", "today 23:59"),
        ("2026-11-22T00:00:05", "2026-11-22T00:00:05", "today 00:00"),
        # Midnight between the accept and the look: the same refusal, only the time word is honest about it.
        ("2026-11-21T23:59:40", "2026-11-22T00:00:05", "yesterday 23:59"),
    ],
)
def test_looks_good_after_the_reviewer_accepted_says_so(tk, run, clock, accepted, looked, said):
    root, tid = tk
    clock(accepted)
    _in_review(root, tid)
    digest = _check_card(run)["digest"]
    assert run("config", "set", "workflow.reviewer", "on")[0] == 0
    tickets.accept_for_owner(root, tid, "small change, every task has evidence")
    clock(looked)
    code, out, _ = _ok(run, tid, digest)
    assert code == 2 and out["code"] == "decided", out
    want = f"Already Done: the Reviewer accepted it for you {said}. Nothing more to press."
    assert out["error"] == want, out


def test_looks_good_after_the_reviewer_sent_it_back_says_why(tk, run, clock):
    """The race with the Reviewer (ORCH-548): it sent the ticket back in the seconds before the person's Looks
    good was saved. The answer names the Reviewer's reason and what happens next, even with the card's old
    digest."""
    root, tid = tk
    _in_review(root, tid)
    digest = _check_card(run)["digest"]
    tickets.ask_for_changes(root, tid, "Pull request #12 is not merged yet.", tickets.REVIEWER)
    code, out, _ = _ok(run, tid, digest)
    assert code == 2 and out["code"] == "decided", out
    assert out["error"].startswith("The Reviewer sent it back today "), out
    assert (
        ": Pull request #12 is not merged yet. It is To do now and comes back to Check"
        " when the helper is done." in out["error"]
    ), out
    assert tickets.load(root, tid)["status"] == "ready"


def test_looks_good_after_you_sent_it_back(tk, run, clock):
    root, tid = tk
    _in_review(root, tid)
    digest = _check_card(run)["digest"]
    note = json.dumps({"changes": ["Redo the test."]})
    assert run("review", "answer", tid, "review", "--verdict", "talk", "--note", note, "--by", ME)[0] == 0
    code, out, _ = _ok(run, tid, digest)
    assert code == 2 and out["code"] == "decided", out
    assert out["error"].startswith("You sent it back today "), out


def test_an_open_step_turns_looks_good_off_with_the_reason(tk, run):
    """Owner 18 Nov (ORCH-548): open steps stop Looks good, like the ticket page's button (ORCH-250); the card
    says why and what to press, and an answer that comes anyway is refused with the same line."""
    root, tid = tk
    _in_review(root, tid, finished=False)
    card = _check_card(run)
    assert card["card"]["blocked"] == "1 step is not finished. Send it back to get it done."
    assert card["card"]["need"] == "Looks good is off"
    code, out, _ = _ok(run, tid, card["digest"])
    assert code == 2 and out["code"] == "refused" and out["error"] == card["card"]["blocked"], out
    assert tickets.load(root, tid)["status"] == "review"
    wire = review.wire_card(card["card"], {})
    assert wire["then"] == "Looks good is off: 1 step is not finished. Send it back to get it done."


def test_an_open_question_turns_looks_good_off(tk, run):
    root, tid = tk
    _in_review(root, tid)
    # a plain question keeps a ticket out of Check (set_status refuses); an add-on's own question does not
    tickets.ask(root, tid, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    tickets.set_status(root, tid, "review", "agent:claude")
    card = _check_card(run)
    assert card["card"]["blocked"] == (
        "A question on this ticket still waits for your answer. Answer it first, then press Looks good."
    )
    assert _ok(run, tid, card["digest"])[0] == 2
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--picked", "Start", "--by", ME)[0] == 0
    card = _check_card(run)
    assert "blocked" not in card["card"]
    assert _ok(run, tid, card["digest"])[0] == 0
    assert tickets.load(root, tid)["status"] == "done"


def test_an_unmerged_pull_request_and_a_second_look_only_say_so(tk, run):
    """Owner 18 Nov (ORCH-548): a pull request not merged yet and the Reviewer's second look still to come do
    not
    stop Looks good; the card's "If you approve" line says them, and Looks good makes the ticket Done."""
    from orch import lookreview

    root, tid = tk
    _in_review(root, tid)
    tickets.ref_add(root, tid, "https://github.com/acme/app/pull/12", "agent:x")
    t = tickets.load(root, tid)
    for r in t["refs"]:  # as the pull-requests add-on keeps them
        r.update(kind="github-pr", status="ready to merge")
    assert review.check_card(t, root)["then"] == (
        "The ticket is done, although pull request #12 is not merged yet. Nothing else starts: no new"
        " ticket, no more work." + review._CHECK_SEND_BACK
    )
    lookreview.queue(root, tid, "the look of a page changed")
    t = tickets.load(root, tid)
    for r in t["refs"]:
        r.update(kind="github-pr", status="merged")
    assert review.check_card(t, root)["then"] == (
        review.CHECK_DONE + " The Reviewer's second look is not needed then." + review._CHECK_SEND_BACK
    )
    assert "blocked" not in review.check_card(t, root)
    assert _ok(run, tid, _check_card(run)["digest"])[0] == 0
    assert tickets.load(root, tid)["status"] == "done"


def test_ticket_show_lists_what_applies_now_and_the_answers(tk, run, person_grant):
    root, tid = tk
    q = _draft(run, tid)
    code, out, _ = run("ticket", "show", tid)
    assert "Needs an answer" in out and "What applies now" not in out
    person_grant(root)
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


def test_wait_returns_the_answer_and_times_out(tk, run, monkeypatch, person_grant):
    root, tid = tk
    q = _draft(run, tid)
    monkeypatch.setattr("orch.cli_review.time.sleep", lambda s: None)
    code, out, err = run("review", "wait", tid, "--timeout", "0", "--json")
    assert code == 2 and json.loads(out)["code"] == "busy"
    person_grant(root)
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
            tickets.answer(root, tid, q["id"], "Yes", ME, "cli", person=True)

    monkeypatch.setattr("orch.cli_review.time.sleep", fake_sleep)
    code, out, _ = run("review", "wait", tid, q["id"])
    assert code == 0 and out.startswith("Yes (pat, cli,") and len(calls) == 2


def test_link_without_a_server(tk, run):
    code, out, _ = run("review", "link")
    assert code == 0 and "No review page runs. Start it in your terminal: orch review" in out
    code, out, _ = run("review", "link", "--json")
    assert json.loads(out)["running"] is False


# ---------------------------------------------------------------- a design review on cards (ORCH-65)


def test_the_question_text_and_group_reach_the_review_list(tk, run):
    root, tid = tk
    code, out, err = run(
        "ask", tid, "Now: three counts. Proposal: one list.", "--draft", "Home list", "--then", "I build it.",
        "--group", "  Home   look ", "--json", "--by", "agent:x",
    )  # fmt: skip
    assert code == 0, out + err
    q = json.loads(out)
    assert q["group"] == "Home look" and "group" not in q["card"]
    (c,) = [c for c in json.loads(run("review", "list", "--json")[1])["cards"] if c["ticket"] == tid]
    assert c["text"] == "Now: three counts. Proposal: one list." and c["group"] == "Home look"
    assert c["digest"] == _digest(root, tid, "q1")  # the group is not part of what the digest covers


def test_group_goes_only_with_a_card_and_is_short(tk, run):
    _, tid = tk
    code, out, err = run("ask", tid, "Plain?", "--group", "Set", "--by", "agent:x")
    assert code == 2 and "go with a card" in out + err
    code, out, err = _add(run, tid, "--draft", "T", "--then", "x", "--group", "x" * 81)
    assert code == 2 and "at most 80" in out + err


def test_a_draft_card_can_suggest_ok_or_no(tk, run):
    _, tid = tk
    code, out, err = _add(run, tid, "--draft", "T", "--then", "x", "--suggest", "ok")
    assert code == 0, out + err
    assert json.loads(out)["recommended"] == "ok"
    code, out, err = _add(run, tid, "--plan", "P", "--then", "x", "--suggest", "no")
    assert code == 0 and json.loads(out)["recommended"] == "no", out + err
    code, out, err = _add(run, tid, "--draft", "U", "--then", "x", "--suggest", "B")
    assert code == 2 and "ok (approve) or no" in out + err


def test_a_choice_can_show_how_it_is_today(tk, run):
    root, tid = tk
    for n in ("today", "a", "b"):
        (root / f"{n}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + n.encode())
    code, out, err = _add(
        run, tid, "--choose", "Which?", "--before", "today.png", "--option", "A=One:a.png",
        "--option", "B=Two:b.png", "--suggest", "A", "--then", "x",
    )  # fmt: skip
    assert code == 0, out + err
    pv = json.loads(out)["card"]["preview"]
    assert pv["type"] == "options" and pv["before"]["src"].startswith("reviewed/")
    code, out, err = _add(
        run, tid, "--choose", "W2", "--before", "today.png", "--after", "a.png",
        "--option", "A=One", "--option", "B=Two", "--then", "x",
    )  # fmt: skip
    assert code == 2 and "--before FILE" in out + err


def test_the_phone_card_leaves_out_the_today_picture():
    ref = "reviewed/aaaaaaaaaaaa/"
    opts = [
        {"id": "A", "title": "One", "preview": {"type": "img", "src": ref + "a.png"}},
        {"id": "B", "title": "Two"},
    ]
    before = {"type": "img", "src": ref + "t.png"}
    card = {
        "kind": "choice",
        "title": "T",
        "then": "x",
        "preview": {"type": "options", "before": before, "options": opts},
    }
    files = review.card_files_of(card)
    assert files == ["reviewed/aaaaaaaaaaaa/a.png"]
    wire = review.wire_card(card, {f: i for i, f in enumerate(files)})
    assert "before" not in wire["preview"] and wire["preview"]["options"][0]["preview"]["src"] == {"file": 0}


def test_a_typed_comment_from_the_page_is_kept_with_the_answer(tk, run, person_grant):
    # the dashboard turns the page's {text, pins} into {words: {text}, pins} (actions._review_answer)
    root, tid = tk
    q = _draft(run, tid)
    note = json.dumps({"words": {"text": "Make the rows taller."}, "pins": []})
    person_grant(root)  # the signed-in dashboard hands its call a person grant (ORCH-582)
    code, out, err = run(
        "review",
        "answer",
        tid,
        q["id"],
        "--verdict",
        "talk",
        "--note",
        note,
        "--via",
        "dashboard",
        "--by",
        ME,
    )
    assert code == 0, out + err
    saved = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == q["id"])
    assert saved["decision"]["action"] == "send_back" and saved["via"] == "dashboard"
    assert saved["decision"]["words"]["text"] == "Make the rows taller."
    assert "Make the rows taller." in saved["answer"]


def test_a_card_carries_links_and_option_descriptions(tk, run):
    root, tid = tk
    code, out, err = _add(
        run, tid, "--choose", "Which?", "--option", "A=One", "--option", "B=Two",
        "--describe", "A=Keeps the menu as it is", "--ref", "Mockup=http://127.0.0.1:8780/home.html",
        "--ref", "Issue=https://example.com/issues/12", "--then", "x",
    )  # fmt: skip
    assert code == 0, out + err
    q = json.loads(out)
    assert q["card"]["preview"]["options"][0]["text"] == "Keeps the menu as it is"
    assert "text" not in q["card"]["preview"]["options"][1]
    assert q["links"] == [
        {"label": "Mockup", "url": "http://127.0.0.1:8780/home.html"},
        {"label": "Issue", "url": "https://example.com/issues/12"},
    ]
    (c,) = [c for c in json.loads(run("review", "list", "--json")[1])["cards"] if c["ticket"] == tid]
    assert c["links"] == q["links"] and c["digest"] == _digest(root, tid, "q1")
    saved = tickets.load(root, tid)["questions"][0]
    assert tickets.question_digest(saved) != tickets.question_digest(
        {**saved, "links": []}
    )  # links are shown


@pytest.mark.parametrize(
    "extra",
    [
        ["--draft", "T", "--then", "x", "--ref", "Mockup=javascript:alert(1)"],
        ["--draft", "T", "--then", "x", "--ref", "no-equals"],
        ["--draft", "T", "--then", "x", *sum([["--ref", f"L{i}=https://e.com/{i}"] for i in range(6)], [])],
        ["--draft", "T", "--then", "x", "--describe", "A=x"],
        ["--choose", "T", "--option", "A=One", "--option", "B=Two", "--describe", "Z=x", "--then", "x"],
    ],
)
def test_links_and_descriptions_are_checked(tk, run, extra):
    _, tid = tk
    code, out, err = _add(run, tid, *extra)
    assert code == 2, out + err


def test_answer_on_a_card_answered_elsewhere_says_so_and_changes_nothing(tk, run):
    """ORCH-921: the page still shows a question that was answered in the terminal (the phone, another
    tab). Its answer with the digest it was shown must not become a second, opposite answer: refused as
    decided, saying what was answered, by whom and when, like a Check card since ORCH-548."""
    root, tid = tk
    code, out, _ = _add(
        run, tid, "--choose", "Which?", "--option", "A=One", "--option", "B=Two", "--then", "x"
    )
    qid = json.loads(out)["id"]
    shown = _digest(root, tid, qid)  # the open card as the page showed it
    code, out, err = run(
        "review", "answer", tid, qid, "--verdict", "ok", "--picked", "A", "--by", "human:sam"
    )
    assert code == 0, out + err
    before = tickets.load(root, tid)["questions"]
    code, out, err = run(
        *("review", "answer", tid, qid, "--verdict", "ok", "--picked", "B"),
        *("--digest", shown, "--by", ME, "--json"),
    )
    assert code == 2, out + err
    res = json.loads(out)
    assert res["code"] == "decided"
    assert "answered already" in res["error"] and "sam" in res["error"] and "Use A" in res["error"]
    assert tickets.load(root, tid)["questions"] == before  # no q2, no replaced_by


def test_change_from_the_terminal_without_a_shown_card_still_replaces(tk, run):
    """A person who chooses to change an answer (no shown card, no digest) still gets a new answer."""
    root, tid = tk
    code, out, _ = _add(
        run, tid, "--choose", "Which?", "--option", "A=One", "--option", "B=Two", "--then", "x"
    )
    qid = json.loads(out)["id"]
    run("review", "answer", tid, qid, "--verdict", "ok", "--picked", "A", "--by", "human:sam")
    code, out, err = run(
        "review", "answer", tid, qid, "--verdict", "ok", "--picked", "B", "--by", ME, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out)["decision"]["replaces"] == qid
