"""The Merge unblocker (`orch github unblock`, ORCH-180): a green pull request on a ticket that did not merge
within STUCK_MIN minutes is merged, or reported when the merge limit is full, or put to the owner when it
changes a workflow file; each said once per commit; off until the role ticket is set; nothing while paused."""

import json

import pytest

from orch import brake, ghlimit, prwait, tickets
from orch import unblock as ub
from orch.errors import Refused

PR = "https://github.com/acme/app/pull/12"
PR2 = "https://github.com/acme/app/pull/13"
HEAD = "a" * 40
OK = {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "test"}
T0 = 1_800_000_000.0
LATER = T0 + ub.STUCK_MIN * 60 + 1


def view(head=HEAD, base="develop", **kw):
    v = {
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewDecision": "",
        "baseRefName": base,
        "headRefOid": head,
        "statusCheckRollup": [OK],
    }
    v.update(kw)
    return v


class FakeGH:
    def __init__(self, views, files=None, outcome=None):
        self.views, self.file_map, self.outcome = views, files or {}, outcome
        self.merged: list[tuple[str, str]] = []

    def view(self, url):
        return self.views.get(url)

    def files(self, url):
        return self.file_map.get(url, ["workspace/src/orch/x.py"])

    def merge(self, url, head):
        self.merged.append((url, head))
        return self.outcome or prwait.Outcome(url, True, "merged", f"Merged {url} on green checks.")


@pytest.fixture
def role(proj, new_ticket, run):
    rid = new_ticket("Role: unblock stuck merges")
    ub.set_role(proj, rid)
    return rid


@pytest.fixture
def linked(proj, new_ticket, run):
    tid = new_ticket("Work with a pull request")
    assert run("ref", "add", tid, PR)[0] == 0
    return tid


@pytest.fixture(autouse=True)
def room(monkeypatch):
    """The merge limit has room unless a test says otherwise."""
    rows = [{"kind": "merge", "used": 0, "per_hour": 30, "last_secs_ago": None, "next_in_secs": 0}]
    monkeypatch.setattr(ghlimit, "status", lambda: rows)
    return rows


def history(proj, tid):
    return [h.get("text") or "" for h in tickets.load(proj, tid).get("history") or []]


def two_passes(proj, gh):
    first = ub.run(proj, now=T0, gh=gh)
    return first, ub.run(proj, now=LATER, gh=gh)


# ---------------------------------------------------------------- switch


def test_off_until_role_ticket_set(proj):
    assert ub.run(proj, gh=FakeGH({})) == {"off": True}
    assert "off here" in ub.text({"off": True})


def test_paused_does_nothing(proj, role, linked):
    brake.pause(proj, "human:tester")
    gh = FakeGH({PR: view()})
    assert ub.run(proj, now=LATER, gh=gh) == {"paused": True}
    assert gh.merged == []


def test_settings_refuse_main_and_release(proj):
    with pytest.raises(Refused):
        ub.set_bases(proj, "develop,main")
    with pytest.raises(Refused):
        ub.set_bases(proj, "release/1.2")
    assert ub.set_bases(proj, "develop,next") == ["develop", "next"]
    assert ub.bases(proj) == ["develop", "next"]
    assert ub.merge_on(proj) is False
    ub.set_merge(proj, "on")
    assert ub.merge_on(proj) is True


def test_config_cli(proj, role, run):
    assert run("config", "set", "github.unblock_merge", "on")[0] == 0
    code, out, _ = run("config", "get", "github.unblock_merge")
    assert code == 0 and "on" in out
    code, out, _ = run("github", "unblock", "--json")
    assert code == 0 and json.loads(out)["merge"] is True


# ---------------------------------------------------------------- the green clock


def test_green_is_not_stuck_before_its_time(proj, role, linked):
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view()})
    res = ub.run(proj, now=T0, gh=gh)
    assert res["watching"] == 1 and gh.merged == [] and res["note"] is None
    res = ub.run(proj, now=T0 + (ub.STUCK_MIN - 1) * 60, gh=gh)
    assert gh.merged == []


def test_new_commit_restarts_the_clock(proj, role, linked):
    ub.set_merge(proj, "on")
    ub.run(proj, now=T0, gh=FakeGH({PR: view()}))
    gh = FakeGH({PR: view(head="b" * 40)})
    ub.run(proj, now=LATER, gh=gh)
    assert gh.merged == []
    ub.run(proj, now=LATER + ub.STUCK_MIN * 60 + 1, gh=gh)
    assert gh.merged == [(PR, "b" * 40)]


@pytest.mark.parametrize(
    "kw",
    [
        {"isDraft": True},
        {"mergeable": "CONFLICTING"},
        {"reviewDecision": "CHANGES_REQUESTED"},
        {"statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE", "name": "lint"}]},
        {"statusCheckRollup": [{"status": "IN_PROGRESS", "name": "test"}]},
        {"base": "main"},
        {"base": "release/1.0"},
        {"state": "MERGED"},
    ],
)
def test_not_green_or_not_ours_is_left_alone(proj, role, linked, kw):
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view(**kw)})
    two_passes(proj, gh)
    assert gh.merged == []


# ---------------------------------------------------------------- what it does


def test_stuck_green_is_merged_and_said_once(proj, role, linked):
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view()})
    _, res = two_passes(proj, gh)
    assert gh.merged == [(PR, HEAD)]
    assert res["merged"] and res["note"].startswith("Merge unblocker")
    assert any("Merge unblocker" in h for h in history(proj, linked))
    assert any("Merge unblocker" in h and "merged" in h for h in history(proj, role))
    ref = next(r for r in tickets.load(proj, linked)["refs"] if r.get("url") == PR)
    assert ref.get("status") == "merged"


def test_merge_off_only_reports_once(proj, role, linked):
    gh = FakeGH({PR: view()})
    _, res = two_passes(proj, gh)
    assert gh.merged == [] and res["reported"]
    before = history(proj, linked)
    assert sum("nothing merged it" in h for h in before) == 1
    ub.run(proj, now=LATER + 600, gh=gh)
    assert history(proj, linked) == before  # the same report is not said again


def test_never_merges_past_a_merge_queue_on_its_base_branch(proj, role, linked, queue_on):
    """#1809: green pull requests into develop were merged by the unblocker, past the merge queue."""
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view()})
    _, res = two_passes(proj, gh)
    assert gh.merged == [] and res["reported"]
    said = [h for h in history(proj, linked) if "nothing merged it" in h]
    assert len(said) == 1 and f"orch pull-requests queue add {PR} --ticket" in said[0]


def test_merge_limit_full_reports_with_next_place(proj, role, linked, room):
    ub.set_merge(proj, "on")
    room[0].update(used=30, next_in_secs=720)
    gh = FakeGH({PR: view()})
    _, res = two_passes(proj, gh)
    assert gh.merged == [] and res["limit"]
    said = [h for h in history(proj, linked) if "merge limit" in h]
    assert len(said) == 1 and "30 of 30" in said[0] and "12 minutes" in said[0]
    notes = [h for h in history(proj, role) if "waiting for the merge limit" in h]
    ub.run(proj, now=LATER + 600, gh=gh)
    assert [h for h in history(proj, role) if "waiting for the merge limit" in h] == notes  # no repeat


def test_workflow_file_asks_the_owner_once(proj, role, linked):
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view()}, files={PR: [".github/workflows/ci.yml", "README.md"]})
    _, res = two_passes(proj, gh)
    assert gh.merged == [] and res["asked"]
    qs = tickets.load(proj, linked)["questions"]
    assert len(qs) == 1 and PR in qs[0]["text"] and "workflow" in qs[0]["text"]
    ub.run(proj, now=LATER + 600, gh=gh)
    assert len(tickets.load(proj, linked)["questions"]) == 1


def test_merge_refused_for_workflow_right_asks_the_owner(proj, role, linked):
    ub.set_merge(proj, "on")
    refused = prwait.Outcome(
        PR, False, "checks passed",
        f"Checks of {PR} passed but GitHub did not merge it: refusing to allow a GitHub App to create or "
        "update workflow without workflows permission",
    )  # fmt: skip
    gh = FakeGH({PR: view()}, outcome=refused)
    _, res = two_passes(proj, gh)
    assert res["asked"] and len(tickets.load(proj, linked)["questions"]) == 1


def test_held_merge_is_said_once(proj, role, linked):
    ub.set_merge(proj, "on")
    held = prwait.Outcome(PR, False, "behind", f"develop keeps changing files of {PR}; not merged.")
    gh = FakeGH({PR: view()}, outcome=held)
    _, res = two_passes(proj, gh)
    assert res["held"]
    ub.run(proj, now=LATER + 600, gh=gh)
    assert sum("keeps changing" in h for h in history(proj, linked)) == 1


def test_merge_card_and_queue_are_left_alone(proj, role, new_ticket, run, queue_on):
    ub.set_merge(proj, "on")
    a = new_ticket("Merged by a person")
    run("ref", "add", a, PR)
    tickets.apply_op(
        proj, a,
        lambda t: t["questions"].append(
            {"id": "q1", "text": "Merge?", "options": [], "answer": None,
             "action": {"merge": PR}, "card": {"kind": "link", "open": PR, "ok_label": "Merge"}}
        ),
        by="agent:x",
    )  # fmt: skip
    b = new_ticket("In the queue")
    run("ref", "add", b, PR2)
    qdir = proj / ".orch" / "addons" / "pull-requests"
    qdir.mkdir(parents=True)
    (qdir / "queue.json").write_text(json.dumps({"entries": [{"url": PR2, "state": "waiting"}]}))
    gh = FakeGH({PR: view(), PR2: view()})
    two_passes(proj, gh)
    assert gh.merged == []


def test_dry_run_writes_nothing(proj, role, linked):
    ub.set_merge(proj, "on")
    gh = FakeGH({PR: view()})
    ub.run(proj, now=T0, gh=gh)
    before = history(proj, linked)
    res = ub.run(proj, now=LATER, gh=gh, dry_run=True)
    assert gh.merged == [] and "would merge" in res["merged"][0]
    assert history(proj, linked) == before


def test_quiet_pass_writes_no_note(proj, role, linked):
    gh = FakeGH({PR: view(state="MERGED")})
    before = history(proj, role)
    res = ub.run(proj, now=LATER, gh=gh)
    assert res["note"] is None and history(proj, role) == before
    assert "Nothing stuck" in ub.text(res)


def test_unreadable_pull_request_keeps_its_clock(proj, role, linked):
    ub.set_merge(proj, "on")
    ub.run(proj, now=T0, gh=FakeGH({PR: view()}))
    res = ub.run(proj, now=T0 + 60, gh=FakeGH({}))
    assert res["errors"]
    gh = FakeGH({PR: view()})
    ub.run(proj, now=LATER, gh=gh)
    assert gh.merged == [(PR, HEAD)]  # green since T0, not since GitHub answered again


def test_one_pass_at_a_time(proj, role, linked):
    assert ub._take_lock(proj)
    assert ub.run(proj, now=T0, gh=FakeGH({PR: view()})) == {"busy": True}
    ub._drop_lock(proj)


def test_merges_per_pass_are_capped(proj, role, new_ticket, run):
    ub.set_merge(proj, "on")
    views = {}
    for n in range(ub.MAX_MERGES + 2):
        url = f"https://github.com/acme/app/pull/{100 + n}"
        tid = new_ticket(f"Work {n}")
        run("ref", "add", tid, url)
        views[url] = view()
    gh = FakeGH(views)
    two_passes(proj, gh)
    assert len(gh.merged) == ub.MAX_MERGES
    ub.run(proj, now=LATER + 600, gh=gh)
    assert len(gh.merged) == ub.MAX_MERGES + 2


# ---------------------------------------------------------------- prwait: merged meanwhile


def test_run_one_counts_a_merge_by_someone_else_as_merged(monkeypatch):
    """A helper's `orch ref wait --merge` whose merge GitHub refuses because the unblocker merged it first
    says merged, not 'GitHub did not merge it'."""
    states = iter(["OPEN", "OPEN"])

    class Src:
        gh = "/fake/gh"

        def view(self):
            return {"state": next(states, "MERGED"), "baseRefName": "develop", "headRefOid": HEAD}

        def landed(self, head, base):
            return []

        def changed_files(self):
            return ["a.py"]

        def take(self, kind, what):
            return True

    monkeypatch.setattr(prwait, "wait", lambda src, timeout=0, **_: prwait.Verdict(True, "all passed"))
    monkeypatch.setattr(
        prwait, "_run",
        lambda argv, timeout=30: type(
            "P", (), {"returncode": 1, "stderr": "Pull request is not open", "stdout": ""}
        )(),
    )  # fmt: skip
    monkeypatch.setattr(ghlimit, "give_back", lambda kind, what: True)
    o = prwait.run_one(PR, True, src=Src())
    assert o.ok and o.status == "merged" and "meanwhile" in o.line
