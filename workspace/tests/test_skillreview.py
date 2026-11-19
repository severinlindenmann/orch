"""Skill format step 5 (ORCH-536): a passed review-by date opens one ticket without an AI call, and a
skill that needs a skill which is not here is warned about."""

import json
from datetime import date

import pytest

from orch import skillmeta, skillreview, tickets

TODAY = date(2027, 3, 2)


def skill(proj, name, meta=None, where=(".agents", "skills"), shared=False):
    d = proj.joinpath(*where, name)
    d.mkdir(parents=True)
    lines = ["---", f"name: {name}", f"description: The {name} skill. Use when testing."]
    if meta:
        lines.append("metadata:")
        lines += [f'  {k}: "{v}"' for k, v in meta.items()]
    (d / "SKILL.md").write_text("\n".join([*lines, "---", "", "Body.", ""]), encoding="utf-8")
    if shared:
        (d / ".orch-shared").write_text("", encoding="utf-8")
    return d


@pytest.fixture
def ws(proj, run):
    assert run("init")[0] == 0
    return proj


def reminders(proj):
    return [t for t in tickets.list_all(proj) if t["title"].startswith("Look at the skill")]


# ---- review-by


def test_a_passed_review_by_date_opens_one_ticket_for_the_owner(ws):
    skill(ws, "github", {"owner": "Severin", "review-by": "2027-03-01"})
    skill(ws, "later", {"review-by": "2027-04-01"})
    skill(ws, "no-date")
    res = skillreview.review_due(ws, today=TODAY)
    assert [(r["skill"], r["date"]) for r in res["opened"]] == [("github", "2027-03-01")]
    assert res["waiting"] == [{"skill": "later", "date": "2027-04-01"}]
    (t,) = reminders(ws)
    assert t["title"] == "Look at the skill github again"
    fields = {**t, **(t.get("fields") or {})}
    assert fields["owner"] == "Severin"
    assert "2027-03-01" in fields["note"] and "review-by" in fields["note"]
    # the next pass opens nothing: one ticket per skill and date
    assert skillreview.review_due(ws, today=TODAY)["opened"] == []
    assert len(reminders(ws)) == 1


def test_a_new_date_later_opens_a_new_ticket(ws):
    d = skill(ws, "github", {"review-by": "2027-03-01"})
    skillreview.review_due(ws, today=TODAY)
    (d / "SKILL.md").write_text(
        (d / "SKILL.md").read_text(encoding="utf-8").replace("2027-03-01", "2027-06-01"), encoding="utf-8"
    )
    assert skillreview.review_due(ws, today=TODAY)["opened"] == []  # not due yet
    assert [r["date"] for r in skillreview.review_due(ws, today=date(2027, 6, 2))["opened"]] == ["2027-06-01"]
    assert len(reminders(ws)) == 2
    # the old date comes back: it had its ticket already
    (d / "SKILL.md").write_text(
        (d / "SKILL.md").read_text(encoding="utf-8").replace("2027-06-01", "2027-03-01"), encoding="utf-8"
    )
    assert skillreview.review_due(ws, today=date(2027, 6, 2))["opened"] == []
    assert len(reminders(ws)) == 2


def test_relay_skills_and_bad_dates_open_nothing(ws):
    skill(ws, "from-admin", {"review-by": "2020-01-01"}, shared=True)  # the admin's workspace is reminded
    skill(ws, "odd", {"review-by": "next spring"})
    assert skillreview.review_due(ws, today=TODAY) == {"opened": [], "waiting": []}
    assert reminders(ws) == []


def test_dry_run_opens_nothing(ws):
    skill(ws, "github", {"review-by": "2027-03-01"})
    res = skillreview.review_due(ws, today=TODAY, dry_run=True)
    assert [r["ticket"] for r in res["opened"]] == [None]
    assert reminders(ws) == []


def test_review_due_on_the_command_line_needs_no_ai(ws, run, monkeypatch):
    import subprocess

    def no_child(*a, **k):  # no agent, no AI call: the pass is plain file work
        raise AssertionError(f"started a process: {a}")

    monkeypatch.setattr(subprocess, "Popen", no_child)
    skill(ws, "github", {"review-by": "2000-01-01"})
    code, out, err = run("skill", "review-due", "--json")
    assert code == 0, err
    (row,) = json.loads(out)["opened"]
    assert row["skill"] == "github" and row["ticket"]
    code, out, _ = run("skill", "review-due")
    assert code == 0 and out.strip() == "No skill is due for a look."


def test_check_warns_about_a_passed_or_unreadable_date(ws):
    skill(ws, "old", {"review-by": "2027-03-01"})
    skill(ws, "odd", {"review-by": "soon"})
    found = skillreview.check_review_by(skillmeta.list_skills(ws), ws, today=TODAY)
    assert {(f["skill"], f["level"]) for f in found} == {("old", "warn"), ("odd", "warn")}
    assert any("has passed" in f["message"] for f in found)


# ---- requires-skills


def test_a_missing_needed_skill_is_warned_about(ws):
    skill(ws, "github", {"requires-skills": "git-basics, gone"})
    skill(ws, "git-basics", shared=True)  # a relay skill counts as here
    found = skillreview.check_needed_skills(skillmeta.list_skills(ws), ws)
    assert [(f["skill"], f["level"], f["field"]) for f in found] == [
        ("github", "warn", "metadata.requires-skills")
    ]
    assert "gone" in found[0]["message"]


def test_checking_one_skill_still_sees_the_others(ws, run):
    skill(ws, "github", {"requires-skills": "git-basics"})
    skill(ws, "git-basics")
    code, out, err = run("skill", "check", "github", "--json")
    assert code == 0, err
    assert [f for f in json.loads(out)["findings"] if f["field"] == "metadata.requires-skills"] == []
    skill(ws, "needs-more", {"requires-skills": "nowhere"})
    code, out, _ = run("skill", "check", "needs-more", "--json")
    assert code == 0  # a warning, never a failed check
    assert any("nowhere" in f["message"] for f in json.loads(out)["findings"])


def test_the_checks_are_part_of_the_skill_check():
    assert skillreview.check_needed_skills in skillmeta.CHECKS
    assert skillreview.check_review_by in skillmeta.CHECKS
