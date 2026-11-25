"""The Auto Reviewer and Away mode (ORCH-425): finished work on a ticket without Human review needed gets a
written verdict by its kind (screen, campaign, data, code) and is accepted or sent back by itself; a ticket
with
the switch on (or a draft) is never touched; the owner undoes each verdict and each answer; Away mode answers
plain questions and choice cards at once, never what the owner keeps."""

import json
import time

import pytest

from orch import autoreview, reviewer, runs, tickets
from orch.errors import Refused

PR = "https://github.com/acme/app/pull/12"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ME = "human:tester"


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    calls = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: calls.append(tid) or {"run": "r_x"})
    return calls


@pytest.fixture
def midnight(monkeypatch):
    """The day turns over right after the test first asks where today starts: every later "today" is the next
    day (ORCH-1829, the 23:59:40 clock job). A test that reads its window once keeps seeing its own rows."""
    real = reviewer.since_time
    asked = []

    def since_time(word=None, now=None):
        if asked and now is None:
            now = time.time() + 86400
        asked.append(word)
        return real(word, now)

    monkeypatch.setattr(reviewer, "since_time", since_time)


@pytest.fixture
def facts(monkeypatch):
    """GitHub as the test says it: one merged, green change of 30 code files (too big for the small
    Reviewer)."""
    box = {
        "facts": {
            "url": PR,
            "number": 12,
            "state": "MERGED",
            "green": True,
            "checks": 17,
            "failed": 0,
            "merged_at": "2999-01-01T00:00:00Z",
            "files": [
                {"path": f"workspace/src/orch/m{i}.py", "additions": 40, "deletions": 4} for i in range(30)
            ],
            "added": {},
        }
    }
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: box["facts"] if url == PR else None)
    return box


def _on(run, key="auto_reviewer"):
    code, out, err = run("config", "set", f"workflow.{key}", "on", "--by", ME)
    assert code == 0, out + err


def _ticket(
    proj, run, new_ticket, title="Speed up the run tests", switch=False, done_when="the tests are fast"
):
    tid = new_ticket(title)
    assert (
        run("ticket", "tidy", tid, title, "--description", "d", "--done-when", done_when, "--by", ME)[0] == 0
    )
    if not switch:
        tickets.set_human_review(proj, tid, False, ME)
    return tid


def _finish(proj, run, tid, step, covers, *evidence):
    assert run("check", "add", tid, step, "--covers", covers, "--by", ME)[0] == 0
    cid = tickets.load(proj, tid)["checklist"][-1]["id"]
    code, out, err = run("check", "done", tid, cid, *evidence, "--by", ME)
    assert code == 0, out + err


def _review(proj, tid):
    tickets.set_status(proj, tid, "review", ME)


def _lines(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def _tend(run):
    code, out, err = run("review", "tend", "--json")
    assert code == 0, out + err
    return json.loads(out)


# ------------------------------------------------------------------ kinds


@pytest.mark.parametrize(
    "ticket,facts,kind",
    [
        ({"title": "x"}, [{"files": [{"path": "web/pages/home.css"}]}], "screen"),
        ({"title": "x"}, [{"files": [{"path": "workspace/src/orch/runs.py"}]}], "code"),
        ({"title": "Newsletter for December"}, [], "campaign"),
        ({"title": "LinkedIn campaign for the launch"}, [], "campaign"),
        ({"title": "Export the sales figures"}, [], "data"),
        (
            {"title": "Clean up", "checklist": [{"evidence": [{"type": "file", "ref": "out/list.csv"}]}]},
            [],
            "data",
        ),
        ({"title": "The home page"}, [], "screen"),
        ({"title": "Think about it"}, [], "other"),
    ],
)
def test_kind_of_work(ticket, facts, kind):
    assert autoreview.kind_of_work(ticket, facts) == kind


# ------------------------------------------------------------------ verdicts by kind


def test_big_code_work_is_accepted_with_a_written_verdict(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    res = _tend(run)
    assert [(a["verdict"], a.get("auto"), a.get("kind"), a["done"]) for a in res["actions"]] == [
        ("accept", True, "code", True)
    ]
    t = tickets.load(proj, tid)
    assert t["status"] == "done"
    lines = _lines(proj, tid)
    assert lines[-3] == (
        "Auto Reviewer, point by point (code): task 'Make the tests fast': shown; "
        "pull request #12 merged, checks green: shown"
    )
    assert lines[-1] == "Accepted for you by the Auto Reviewer: code work, all 2 points shown."
    assert tickets.load(proj, tid)["history"][-1]["by"] == tickets.REVIEWER


def test_a_ticket_with_human_review_needed_is_never_touched(proj, run, new_ticket, facts):
    """End to end: the switch on (the default) -> no verdict, no line, no change, in Auto and in Away."""
    _on(run)
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, switch=True)
    tickets.set_human_review(proj, tid, True, ME)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    assert (
        run(
            "ask",
            tid,
            "Fix it now or open an issue?",
            "--option",
            "Fix",
            "--option",
            "Issue",
            "--recommend",
            "Fix",
            "--by",
            "agent:helper",
        )[0]
        == 0
    )
    before = tickets.load(proj, tid)
    res = _tend(run)
    assert res["actions"] == []
    assert [a for a in res["answers"] if a["done"]] == []
    after = tickets.load(proj, tid)
    assert after["revision"] == before["revision"] and after["questions"][0]["answer"] is None


def test_a_draft_kind_ticket_is_never_touched_by_auto_or_away(proj, run, new_ticket, facts):
    """ORCH-645 meets ORCH-425: a ticket of kind draft (drafts, mockups, designs) is the owner's alone,
    even with Human review needed off and no draft card yet: no verdict, no answer, no change."""
    _on(run)
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket)
    assert run("ticket", "kind", tid, "draft", "--by", ME)[0] == 0
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    assert (
        run(
            "ask",
            tid,
            "Fix it now or open an issue?",
            "--option",
            "Fix",
            "--option",
            "Issue",
            "--recommend",
            "Fix",
            "--by",
            "agent:helper",
        )[0]
        == 0
    )
    _review(proj, tid)
    before = tickets.load(proj, tid)
    res = _tend(run)
    assert [a for a in res["actions"] if a["done"]] == []
    assert [a for a in res["answers"] if a["done"]] == []
    after = tickets.load(proj, tid)
    assert after["status"] == "review" and after["questions"][0]["answer"] is None
    assert after["revision"] == before["revision"]


def test_human_review_needed_in_review_is_left_alone(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    tickets.set_human_review(proj, tid, True, ME)
    _review(proj, tid)
    rev = tickets.load(proj, tid)["revision"]
    assert _tend(run)["actions"] == []
    assert tickets.load(proj, tid)["revision"] == rev and tickets.load(proj, tid)["status"] == "review"
    with pytest.raises(Refused, match="Human review needed"):
        tickets.accept_for_owner(proj, tid, "x", auto="points")


def test_screen_work_without_pictures_goes_back_once_then_stays(proj, run, new_ticket, facts, no_starts):
    facts["facts"]["files"] = [{"path": "web/pages/home.css", "additions": 10, "deletions": 1}]
    _on(run)
    tid = _ticket(proj, run, new_ticket, "Home page spacing", done_when="the home page breathes")
    _finish(proj, run, tid, "Fix the spacing", "the home page breathes", "--pr", PR)
    _review(proj, tid)
    res = _tend(run)
    a = res["actions"][0]
    assert (a["verdict"], a["kind"]) == ("back", "screen")
    assert "pictures of the screen" in a["why"]
    t = tickets.load(proj, tid)
    assert t["status"] == "ready" and no_starts == [tid]
    assert t["checklist"][-1]["text"].startswith("The Auto Reviewer found work missing (screen work)")
    assert any(x.startswith("Sent back by the Auto Reviewer: ") for x in _lines(proj, tid))
    # the helper finishes without pictures again: left for the owner, not a second send-back
    cid = t["checklist"][-1]["id"]
    assert run("check", "done", tid, cid, "--note", "done", "--by", ME)[0] == 0
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert a["verdict"] == "leave" and a["why"].startswith("sent back once already")


def test_screen_work_with_pictures_at_three_widths_is_accepted(proj, run, new_ticket, facts):
    facts["facts"]["files"] = [{"path": "web/pages/home.css", "additions": 10, "deletions": 1}]
    _on(run)
    tid = _ticket(proj, run, new_ticket, "Home page spacing", done_when="the home page breathes")
    ev = ["--pr", PR]
    for w in ("1280", "1920", "390"):
        (proj / f"home-{w}.png").write_bytes(PNG)
        ev += ["--file", f"home-{w}.png"]
    _finish(proj, run, tid, "Fix the spacing", "the home page breathes", *ev)
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert (a["verdict"], a["kind"]) == ("accept", "screen"), a
    assert "pictures at 1280, 1920 and 390 px wide: shown" in a["points"]


def test_campaign_without_pull_request_is_accepted_when_its_text_is_there(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket, "December newsletter", done_when="the newsletter text is ready")
    (proj / "newsletter.md").write_text("Hello\n", encoding="utf-8")
    _finish(proj, run, tid, "Write the newsletter", "the newsletter text is ready", "--file", "newsletter.md")
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert (a["verdict"], a["kind"]) == ("accept", "campaign"), a
    assert "the campaign itself on the ticket: shown" in a["points"]


def test_a_campaign_that_went_out_stays_with_the_owner(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket, "December newsletter", done_when="the newsletter text is ready")
    (proj / "newsletter.md").write_text("Hello\n", encoding="utf-8")
    _finish(
        proj,
        run,
        tid,
        "Write the newsletter",
        "the newsletter text is ready",
        "--file",
        "newsletter.md",
        "--summary",
        "The newsletter was sent to 400 people.",
    )
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert a["verdict"] == "leave" and "went out" in a["why"]
    assert tickets.load(proj, tid)["status"] == "review"


def test_data_work_needs_a_data_file_or_a_passing_check(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket, "Export the sales figures", done_when="the figures are exported")
    _finish(proj, run, tid, "Export them", "the figures are exported", "--note", "did it")
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert (a["verdict"], a["kind"]) == ("back", "data")
    tid2 = _ticket(proj, run, new_ticket, "Export the sales figures", done_when="the figures are exported")
    (proj / "sales.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _finish(proj, run, tid2, "Export them", "the figures are exported", "--file", "sales.csv")
    _review(proj, tid2)
    a = next(x for x in _tend(run)["actions"] if x["ticket"] == tid2)
    assert (a["verdict"], a["kind"]) == ("accept", "data")


def test_a_security_file_next_to_a_page_stays_with_the_owner(proj, run, new_ticket, facts):
    facts["facts"]["files"] = [
        {"path": "web/pages/home.css", "additions": 10, "deletions": 1},
        {"path": "workspace/src/orch/signin.py", "additions": 3, "deletions": 1},
    ]
    _on(run)
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert a["verdict"] == "leave" and "security" in a["why"]


def test_unknown_kind_and_a_part_without_task_stay_with_the_owner(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket, "Think about it", done_when="we know more")
    _finish(proj, run, tid, "Think", "we know more", "--note", "thought")
    _review(proj, tid)
    a = _tend(run)["actions"][0]
    assert a["verdict"] == "leave" and "not clear what kind" in a["why"]
    tid2 = _ticket(proj, run, new_ticket, done_when="the tests are fast; the docs say so")
    _finish(proj, run, tid2, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid2)
    a = next(x for x in _tend(run)["actions"] if x["ticket"] == tid2)
    assert a["verdict"] == "leave" and "has no task" in a["why"]


def test_a_verdict_on_a_ticket_that_changed_meanwhile_is_refused(proj, run, new_ticket, facts):
    _on(run)
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    t = tickets.load(proj, tid)
    res = autoreview.decide(proj, t, [facts["facts"]])
    tickets.log(proj, tid, "the helper said one more thing", ME)
    with pytest.raises(Refused):
        autoreview.act(proj, t, res)
    assert tickets.load(proj, tid)["status"] == "review"


def test_off_does_nothing(proj, run, new_ticket, facts):
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    assert _tend(run)["off"] is True
    with pytest.raises(Refused, match="Auto Reviewer is off"):
        tickets.accept_for_owner(proj, tid, "x", auto="points")


def test_only_a_person_turns_away_on(proj, run):
    code, out, err = run("config", "set", "workflow.away", "on", "--by", "agent:helper")
    assert code == 2 and "Only the owner" in out + err
    _on(run, "away")
    code, out, _ = run("config", "get", "workflow.away", "--json")
    assert code == 0 and "true" in out.lower()


# ------------------------------------------------------------------ undo


def test_the_owner_undoes_an_accept_and_it_is_not_accepted_again(proj, run, new_ticket, facts, midnight):
    since = reviewer.since_time("today")  # once, before anything: a test that crosses midnight keeps its day
    _on(run)
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    _tend(run)
    rows = reviewer.accepted(proj, since)
    assert [(r["auto"], r["undo"]) for r in rows] == [(True, "accept")]
    code, out, err = run("review", "undo", tid, "--by", "agent:helper")
    assert code == 2 and "Only a person" in out + err
    code, out, err = run("review", "undo", tid, "--by", ME)
    assert code == 0 and "back in Review" in out, out + err
    t = tickets.load(proj, tid)
    assert t["status"] == "review" and tickets.human_review(t)
    assert _lines(proj, tid)[-1].startswith("Undone by you: the Reviewer's accept")
    assert _tend(run)["actions"] == []
    assert tickets.load(proj, tid)["status"] == "review"
    rows = reviewer.accepted(proj, since)
    assert [(r["undo"], r["undone"]) for r in rows] == [(None, True)]
    code, out, _ = run("review", "undo", tid, "--by", ME)
    assert code == 2


def test_the_owner_undoes_a_send_back_before_a_helper_takes_it(
    proj, run, new_ticket, facts, validate, midnight
):
    since = reviewer.since_time("today")  # once, before anything: a test that crosses midnight keeps its day
    facts["facts"]["files"] = [{"path": "web/pages/home.css", "additions": 10, "deletions": 1}]
    _on(run)
    tid = _ticket(proj, run, new_ticket, "Home page spacing", done_when="the home page breathes")
    _finish(proj, run, tid, "Fix the spacing", "the home page breathes", "--pr", PR)
    _review(proj, tid)
    _tend(run)
    assert runs.undelivered(proj, tid)
    rows = reviewer.accepted(proj, since)
    assert [(r.get("back"), r["undo"]) for r in rows] == [(True, "back")]
    code, out, err = run("review", "undo", tid, "--by", ME)
    assert code == 0, out + err
    t = tickets.load(proj, tid)
    assert t["status"] == "review" and len(t["checklist"]) == 1 and tickets.human_review(t)
    validate(t)
    assert not [i for i in runs.undelivered(proj, tid) if i.get("by") == tickets.REVIEWER]


# ------------------------------------------------------------------ Away mode answers


def _choice(
    run, tid, what="Which way should the list sort?", opts=("A=By date", "B=By size"), rec="A", action=()
):
    args = ["ask", tid, what, "--choose", what, "--then", "I build it."]
    for o in opts:
        args += ["--option", o]
    if rec:
        args += ["--recommend", rec]
    code, out, err = run(*args, *action, "--json", "--by", "agent:helper")
    assert code == 0, out + err
    return json.loads(out)


def _plain(run, tid, text, options=("Fix it now", "Open an issue"), rec="Fix it now"):
    args = ["ask", tid, text]
    for o in options:
        args += ["--option", o]
    if rec:
        args += ["--recommend", rec]
    code, out, err = run(*args, "--json", "--by", "agent:helper")
    assert code == 0, out + err
    return json.loads(out)


def _q(proj, tid, qid):
    return next(q for q in tickets.load(proj, tid)["questions"] if q["id"] == qid)


def test_away_answers_a_plain_question_and_a_choice_card_at_once(proj, run, new_ticket):
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, "Sort the list")
    p = _plain(run, tid, "The run test fails once in ten. Fix it now or open an issue?")
    c = _choice(run, tid)
    res = _tend(run)
    done = {a["question"]: a["answer"] for a in res["answers"] if a["done"]}
    assert done == {p["id"]: "Fix it now", c["id"]: "A"}
    d = _q(proj, tid, c["id"])["decision"]  # the same structured pick a person's click records
    assert (d["action"], d["picked"]) == ("use", "A")
    assert _q(proj, tid, c["id"])["answered_by"] == tickets.REVIEWER
    assert any(x.startswith("Answered for you in Away mode: ") for x in _lines(proj, tid))


@pytest.mark.parametrize(
    "text",
    [
        "Rename the button to Save?",  # words or names
        "Deploy it to the server tonight?",  # production
        "Delete the old records?",  # cannot be undone
        "Rotate the API key now?",  # logins or keys
        "Log in with the shared profile?",  # logins
        "Redeploy it tonight?",  # a prefix does not hide it
        "Run the pre-delete step?",
        "Truncate the table?",
        "Buy the bigger plan for $20?",  # money
        # security review of #1646 (ORCH-1375): outside-visible and go-aheads that hide what they start
        "Share the report by private link?",
        "Invite the client to the workspace?",
        "Expose the preview port to the network?",
        "Grant the helper access to the Documents folder?",
        "Proceed with step 3 as planned?",
        "Go ahead?",
        "Continue with c4?",
        "Upload the export to the drive?",
        "Notify the team on their phones?",
        "Go-ahead with the sorting?",  # a hyphen or two spaces do not hide a word
        "Do  it for the sorted list?",
        "Go.ahead with the sorting?",  # any mark between the words, not only a hyphen
        "Do,it for the sorted list?",
        "Share/send the sorted list?",
        "Let the client team view the sorted list?",  # several words before the verb
        "Let Alice view the sorted list?",
        "Give Alice read rights on the list?",
        "Is that OK?",  # too short to say what the yes does
        "Ready?",
    ],
)
def test_away_never_answers_what_the_owner_keeps(proj, run, new_ticket, text):
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, "Sort the list")
    q = _plain(run, tid, text, ("Yes", "No"), "Yes")
    _tend(run)
    assert _q(proj, tid, q["id"])["answer"] is None


def test_away_leaves_cards_without_a_recommendation_and_switch_on_tickets(proj, run, new_ticket):
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, "Sort the list")
    c = _choice(run, tid, rec=None)
    tid2 = _ticket(proj, run, new_ticket, "Sort the list", switch=True)
    tickets.set_human_review(proj, tid2, True, ME)
    p = _plain(run, tid2, "Fix it now or open an issue?")
    _tend(run)
    assert _q(proj, tid, c["id"])["answer"] is None
    assert _q(proj, tid2, p["id"])["answer"] is None


def test_away_never_answers_a_merge_card():
    t = {"id": "t_aaaaaa", "title": "x", "status": "active", "human_review": False, "questions": []}
    q = {
        "id": "q1",
        "text": "Merge it?",
        "options": ["Merge", "Not now"],
        "recommended": "Merge",
        "answer": None,
        "action": {"merge": PR},
        "card": {"kind": "link", "title": "Merge"},
    }
    assert autoreview.away_answerable(t, q)[0] is False
    q2 = {**q, "action": None, "text": "Go on?", "options": ["Go", "Wait"], "recommended": "Go"}
    assert autoreview.away_answerable(t, q2)[0] is False  # a link card


def test_the_owner_undoes_an_away_answer_and_it_waits_for_them(proj, run, new_ticket, validate, midnight):
    since = reviewer.since_time("today")  # once, before anything: a test that crosses midnight keeps its day
    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, "Sort the list")
    c = _choice(run, tid)
    _tend(run)
    rows = reviewer.accepted(proj, since)
    assert [(r.get("question"), r["undo"], r["auto"]) for r in rows] == [(c["id"], "answer", True)]
    code, out, err = run("review", "undo", tid, c["id"], "--by", ME)
    assert code == 0, out + err
    q = _q(proj, tid, c["id"])
    assert q["answer"] is None and q["answered_by"] is None and q.get("owner_only") is True
    validate(tickets.load(proj, tid))
    assert any("undid the answer" in i.get("text", "") for i in runs.undelivered(proj, tid))
    _tend(run)
    assert _q(proj, tid, c["id"])["answer"] is None
    rows = reviewer.accepted(proj, since)
    assert [(r["undo"], r["undone"]) for r in rows] == [(None, True)]


def test_an_undone_accept_stays_with_the_owner_also_with_the_plain_reviewer_on(proj, run, new_ticket, facts):
    _on(run)
    _on(run, "reviewer")
    facts["facts"]["files"] = [{"path": "workspace/src/orch/runs.py", "additions": 5, "deletions": 1}]
    facts["facts"]["added"] = {"workspace/src/orch/runs.py": ["    x = 1"]}
    tid = _ticket(proj, run, new_ticket)
    _finish(proj, run, tid, "Make the tests fast", "the tests are fast", "--pr", PR)
    _review(proj, tid)
    assert _tend(run)["actions"][0]["verdict"] == "accept"  # the small Reviewer's accept
    assert run("review", "undo", tid, "--by", ME)[0] == 0
    assert _tend(run)["actions"] == []
    assert tickets.load(proj, tid)["status"] == "review"


def test_routine_answers_skip_a_question_the_owner_took_back(proj, run, new_ticket):
    import time

    _on(run, "away")
    tid = _ticket(proj, run, new_ticket, "Sort the list")
    q = _plain(run, tid, "The run test fails once in ten. Fix it now or open an issue?")
    _tend(run)
    assert run("review", "undo", tid, q["id"], "--by", ME)[0] == 0
    assert run("config", "set", "workflow.away", "off", "--by", ME)[0] == 0
    _on(run, "reviewer_answers")
    rows = reviewer.answer_routine(proj, now=time.time() + 3600)
    assert [r["routine"] for r in rows] == [False] and "took it back" in rows[0]["why"]
    assert _q(proj, tid, q["id"])["answer"] is None


def test_away_reads_every_word_of_a_card():
    t = {"id": "t_aaaaaa", "title": "x", "status": "active", "human_review": False, "questions": []}
    card = {
        "kind": "choice",
        "title": "Which?",
        "preview": {
            "type": "options",
            "heading": "Wipe the old records",
            "options": [{"id": "A", "title": "One"}, {"id": "B", "title": "Two"}],
        },
    }
    q = {
        "id": "q1",
        "text": "Which?",
        "options": ["A", "B"],
        "recommended": "A",
        "answer": None,
        "card": card,
    }
    ok, why = autoreview.away_answerable(t, q)
    assert ok is False and "cannot be undone" in why
    plan = {**q, "card": {"kind": "plan", "title": "Plan"}}
    assert autoreview.away_answerable(t, plan)[0] is False


def test_away_leaves_a_card_too_deep_to_read():
    t = {"id": "t_aaaaaa", "title": "x", "status": "active", "human_review": False, "questions": []}
    deep = "fine"
    for _ in range(10):
        deep = {"x": deep}
    card = {"kind": "choice", "title": "Which?", "extra": deep}
    q = {
        "id": "q1",
        "text": "Which?",
        "options": ["A", "B"],
        "recommended": "A",
        "answer": None,
        "card": card,
    }
    assert autoreview.away_answerable(t, q)[0] is False


def _away_ticket(steps):
    checklist = [{"id": f"c{i + 1}", "text": t, "done": d} for i, (t, d) in enumerate(steps)]
    return {"id": "t_aaaaaa", "title": "Sort the list", "status": "active", "human_review": False,
            "questions": [], "checklist": checklist}  # fmt: skip


def _away_q(text):
    return {"id": "q1", "text": text, "options": ["Yes", "No"], "recommended": "Yes", "answer": None}


def test_away_reads_the_open_steps_a_short_yes_would_start():
    """ORCH-1375: 'Is the list right?' can stand for an open step that sends it out: that step keeps it."""
    q = _away_q("Is the sorted list right?")
    assert autoreview.away_answerable(_away_ticket([("Sort by date", False)]), q) == (
        True,
        autoreview.AWAY_WHY,
    )
    ok, why = autoreview.away_answerable(_away_ticket([("Send the list to the public link", False)]), q)
    assert ok is False and why.startswith("an open step names")
    # a step that is done or won't be done no longer starts anything
    assert autoreview.away_answerable(_away_ticket([("Share the list by link", True)]), q)[0] is True
    t = _away_ticket([("Share the list by link", False)])
    t["checklist"][0]["wont_do"] = {"reason": "x"}
    assert autoreview.away_answerable(t, q)[0] is True
    weird = _away_ticket([("Sort by date \u202e", False)])
    assert autoreview.away_answerable(weird, q)[0] is False  # not plain text: stays
