"""ORCH-1741 (owner 23 Nov): work with nothing left for the person closes without a card.

- Every linked pull request merged, no draft, no open question: accepted at once (whatever its kind, size or
  Human review needed; owner's answer q2), when it is sent to Review, when the queue merges it, and on the
  Reviewer's pass for a moment that was missed.
- A security review orch made itself with an ok that names no High or Medium finding: accepted at once.
"""

import pytest

from orch import reviewer, secreview, tickets

PR = "https://github.com/acme/app/pull/12"
ME = "agent:claude"


@pytest.fixture(autouse=True)
def _on(proj, run, monkeypatch):
    monkeypatch.setenv("ORCH_NO_PULL_LOOK", "1")
    assert run("config", "set", "workflow.reviewer", "on")[0] == 0


def _ticket(proj, run, new_ticket, title="Add the export page", status="merged", prs=(PR,), kind="feature"):
    tid = new_ticket(title)
    assert run("ticket", "tidy", tid, title, "--kind", kind)[0] == 0
    for url in prs:
        tickets.ref_add(proj, tid, url, "agent:x")
    _set_refs(proj, tid, status)
    assert run("check", "add", tid, "Build it")[0] == 0
    assert run("check", "done", tid, "c1", "--note", "built", "--by", "human:tester")[0] == 0
    return tid


def _set_refs(proj, tid, status, url=None):
    t = tickets.load(proj, tid)
    for r in t["refs"]:
        if url is None or r["url"] == url:
            r.update(kind="github-pr", status=status)
    tickets.save(proj, t)


def _to_review(proj, run, tid):
    code, out, _ = run("ticket", "status", tid, "done", "--by", ME)
    assert code == 0, out
    return tickets.load(proj, tid), out


def _accepted(t):
    return any(str(h.get("text", "")).startswith(tickets.ACCEPTED_LINE) for h in t.get("history") or [])


def test_merged_with_nothing_open_is_done_at_once(proj, run, new_ticket):
    tid = _ticket(proj, run, new_ticket)
    assert tickets.human_review(tickets.load(proj, tid))  # on: still closes (owner, q2)
    t, out = _to_review(proj, run, tid)
    assert t["status"] == "done" and _accepted(t)
    assert tickets.CLOSED_ITSELF_MESSAGE in out
    assert "Pull request #12 merged and nothing else is open." in t["history"][-1]["text"]


@pytest.mark.parametrize(
    "why", ["open", "second open", "draft", "question", "reviewer off", "no pull request"]
)
def test_anything_open_keeps_it_for_the_person(proj, run, new_ticket, why):
    prs = (
        (PR, "https://github.com/acme/app/pull/13")
        if why == "second open"
        else ()
        if why == "no pull request"
        else (PR,)
    )
    kind = "draft" if why == "draft" else "feature"
    tid = _ticket(proj, run, new_ticket, status="open" if why == "open" else "merged", prs=prs, kind=kind)
    assert tickets.kind(tickets.load(proj, tid)) == kind
    if why == "second open":
        _set_refs(proj, tid, "ready to merge", "https://github.com/acme/app/pull/13")
    if why == "question":
        tickets.ask(proj, tid, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    if why == "reviewer off":
        assert run("config", "set", "workflow.reviewer", "off")[0] == 0
    t, _ = _to_review(proj, run, tid)
    assert t["status"] == "review"
    assert reviewer.close_now(proj, tid) is None


def test_the_queue_merging_the_last_pull_request_closes_it(proj, run, new_ticket):
    tid = _ticket(proj, run, new_ticket, status="ready to merge")
    t, _ = _to_review(proj, run, tid)
    assert t["status"] == "review"
    _set_refs(proj, tid, "merged")  # what the queue writes when it merged it, then it calls close_now
    assert reviewer.close_now(proj, tid)["status"] == "done"


def test_the_pass_catches_a_missed_moment(proj, run, new_ticket):
    tid = _ticket(proj, run, new_ticket, status="ready to merge", kind="feature")
    _to_review(proj, run, tid)
    _set_refs(proj, tid, "merged")
    res = reviewer.run(proj, facts_of=lambda u: None)  # GitHub is not needed for it
    assert tickets.load(proj, tid)["status"] == "done"
    assert [a["verdict"] for a in res["actions"] if a["ticket"] == tid] == ["accept"]


def _security(monkeypatch, ok=True, line="No High/Medium. Low: a log line names the folder."):
    monkeypatch.setattr(
        reviewer,
        "review_result",
        lambda root, t: (
            {"ok": ok, "line": line, "what": "the security review of pull request #5"}
            if t["title"].startswith("Security review")
            else None
        ),
    )


def test_a_security_ok_closes_itself(proj, run, new_ticket, monkeypatch):
    _security(monkeypatch)
    tid = _ticket(
        proj, run, new_ticket, "Security review: pull request #5 Fix the export", prs=(), kind="other"
    )
    t, _ = _to_review(proj, run, tid)
    assert t["status"] == "done" and "found nothing for you" in t["history"][-1]["text"]


@pytest.mark.parametrize(
    "ok,line", [(True, "OK overall. Medium: the token is logged once."), (False, "High: the key leaks.")]
)
def test_a_security_finding_stays_for_the_person(proj, run, new_ticket, monkeypatch, ok, line):
    _security(monkeypatch, ok, line)
    tid = _ticket(
        proj, run, new_ticket, "Security review: pull request #5 Fix the export", prs=(), kind="other"
    )
    t, _ = _to_review(proj, run, tid)
    assert t["status"] == "review"


def test_the_verdict_on_a_ticket_in_review_closes_it(proj, run, new_ticket, monkeypatch):
    tid = _ticket(
        proj, run, new_ticket, "Security review: pull request #5 Fix the export", prs=(), kind="other"
    )
    _to_review(proj, run, tid)
    assert tickets.load(proj, tid)["status"] == "review"  # no verdict yet
    monkeypatch.setattr(secreview, "_keeper_entry", lambda root, n: {"sha": "abcdef1234", "tid": tid})
    monkeypatch.setattr(secreview, "_may_record", lambda root, n, e: None)
    _security(monkeypatch)
    secreview.verdict(proj, 5, "ok", "No High/Medium.", ME, sha="abcdef1")
    assert tickets.load(proj, tid)["status"] == "done"
