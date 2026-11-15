"""The check-up of the add-on: propose, isolated test, accept / roll back / reject (plain clicks, no proofs), list/show,
the CLI. `orch` is a fake (`orchcall`): tickets, runs and counts are its answers."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from orch_insights import checkup_core as cc
from orch_insights import cli

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
VEC = json.loads((CONTRACTS / "vectors/proposal-v1.json").read_text())
SCHEMA = json.loads((CONTRACTS / "proposal.schema.json").read_text())
SKILL = "---\nname: invoice-export\ndescription: Export invoices to CSV with dates\n---\n# Invoice export\nWrite dates as you like.\n"
NEW_SKILL = "---\nname: refund-flow\ndescription: Handle a customer refund request\n---\n# Refund flow\nCheck the order first.\n"
CHK = "t_chk001"
TICKETS = {"t_inv7c2": {"id": "t_inv7c2", "title": "Export the invoices for October as CSV", "done_when": ""}}


class FakeOrch:
    def __init__(self):
        self.calls = []
        self.counts = {"runs": 0, "tickets": 0, "items": []}
        self.automation = True
        self.repeating = False
        self.running = False

    def __call__(self, root, *argv, timeout=60):
        self.calls.append(list(argv))
        a = list(argv)
        if a[:2] == ["ticket", "show"]:
            if a[2] == CHK:
                return {"id": CHK, "ext": {"automation": {"recurring": self.repeating}}}
            return TICKETS.get(a[2])
        if a[:2] == ["ticket", "new"]:
            return {"id": CHK}
        if a[:2] == ["ticket", "summary"]:
            return {}
        if a[:2] == ["run", "start"]:
            return {"run": "r_xxxxxx1"}
        if a[:2] == ["run", "status"]:
            return {"running": self.running}
        if a[:2] == ["record", "counts"]:
            return self.counts
        if a[:2] == ["addon", "list"]:
            return [{"name": "automation", "active": self.automation}]
        if a[:2] == ["automation", "repeat"]:
            self.repeating = "--off" not in a
            return {"recurring": self.repeating}
        return None


@pytest.fixture
def fake(monkeypatch):
    f = FakeOrch()
    monkeypatch.setattr(cc, "orchcall", f)
    return f


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    d = root / ".agents" / "skills" / "invoice-export"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL)
    (root / ".orch").mkdir()
    return root


@pytest.fixture
def inrun(ws, fake, monkeypatch):
    cc._ensure_ticket(ws)
    monkeypatch.setenv("ORCH_TICKET", CHK)
    monkeypatch.setenv("ORCH_RUN", "r_run00001")


def draft(**over):
    d = {
        "kind": "skill.fix",
        "title": "invoice-export: say the date format",
        "plain": "Write dates as YYYY-MM-DD.",
        "likely": False,
        "evidence": [{"ticket": "t_inv7c2"}],
        "target": {"kind": "skill", "name": "invoice-export"},
        "change": {"files": [{"path": "SKILL.md", "after": SKILL.replace("as you like", "as YYYY-MM-DD")}]},
    }
    d.update(over)
    return d


def tree(ws):
    h = hashlib.sha256()
    for p in sorted(ws.rglob("*")):
        if ".orch" in p.parts:
            continue
        h.update(str(p.relative_to(ws)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def proposed(ws, **over):
    return cc.propose(ws, draft(**over))["id"]


def mk_tested(ws, **over):
    pid = proposed(ws, **over)
    assert cc.run_test(ws, pid)["status"] == "tested"
    return pid


# ------------------------------------------------------------------------------------------ vectors


def reference(d, ctx):
    try:
        cc.validate_draft(d)
    except cc.CheckupError:
        return "refused:invalid"
    if ctx.get("checkup") is None:
        return "refused:not_checkup"
    if d["kind"] == "skill.new" and (
        d["target"]["name"].startswith("orch") or d["target"]["name"] in ctx["existing_names"]
    ):
        return "refused:name_taken"
    return cc.from_draft(d, ctx)


@pytest.mark.parametrize("case", VEC["from_draft"], ids=lambda c: c["name"])
def test_vectors_from_draft(case):
    got = reference(case["draft"], case["ctx"])
    assert got == case["expect"]
    if isinstance(got, dict):
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(got)


@pytest.mark.parametrize("case", VEC["steps"], ids=lambda c: c["name"])
def test_vectors_steps(case):
    assert cc.step(case) == case["result"]
    assert cc.proposal_hash(case["file"]) == cc.proposal_hash(json.loads(json.dumps(case["file"])))


def test_vector_commands_match_the_read_only_list():
    import sys

    sys.path.insert(0, str(CONTRACTS))
    from_json = VEC["checkup_commands"]
    assert any(c["command"].startswith("orch insights propose") and c["allowed"] for c in from_json)


def test_validate_draft_matches_the_draft_schema():
    v = Draft202012Validator(
        {"$ref": "#/$defs/draft", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
    )
    good = VEC["from_draft"][0]["draft"]
    for ex in (
        good, {**good, "title": "x" * 121}, {**good, "likely": "no"}, {**good, "evidence": [{"ticket": "bad"}]},
        {**good, "target": {"kind": "skill", "name": "../x"}}, {**good, "change": {"files": [{"path": "/etc/x", "after": "x"}]}},
        {**good, "change": {"files": [{"path": "a\\b", "after": "x"}]}}, {**good, "change": {"files": [{"path": "a/.b", "after": "x"}]}},
        {**good, "change": {"files": [{"path": "..", "after": "x"}]}}, {**good, "change": {"files": []}},
        {**good, "change": {"files": [{"path": "a", "after": "x" * 65537}]}}, {**good, "status": "tested"}, {**good, "plain": "bad\x01"},
    ):  # fmt: skip
        ok = not list(v.iter_errors(ex))
        try:
            cc.validate_draft(ex)
            mine = True
        except cc.CheckupError:
            mine = False
        assert mine == ok, ex


# ------------------------------------------------------------------------------------------ propose


def test_propose_outside_a_checkup_run_is_refused(ws, fake, monkeypatch):
    cc._ensure_ticket(ws)
    for env in ({}, {"ORCH_TICKET": CHK}, {"ORCH_TICKET": "t_other11", "ORCH_RUN": "r_run00001"}):
        monkeypatch.delenv("ORCH_TICKET", raising=False)
        monkeypatch.delenv("ORCH_RUN", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(cc.CheckupError) as e:
            cc.propose(ws, draft())
        assert e.value.code == "not_checkup"
    assert not list((ws / ".orch/insights/proposals").glob("*.json"))


def test_propose_builds_the_proposal_here(ws, inrun):
    pid = cc.propose(ws, draft())["id"]
    doc = json.loads((ws / ".orch/insights/proposals" / f"{pid}.json").read_text())
    assert doc["status"] == "proposed" and doc["checkup"] == {"ticket": CHK, "run": "r_run00001"}
    files = cc.skill_files(ws / ".agents/skills/invoice-export")
    assert doc["target"]["version"] == cc.skill_version(files) and doc["target"]["source"] == "workspace"
    assert doc["change"]["files"][0]["before"] == cc.sha(files["SKILL.md"])
    assert (ws / ".orch/insights/.gitignore").read_text() == "*\n"


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "tested"},
        {"target": {"kind": "skill", "name": "invoice-export", "version": "sha256:" + "a" * 64}},
        {"kind": "note"},
        {"change": {"files": [{"path": "a/.orch-shared", "after": "x"}]}},
        {"evidence": []},
        {"evidence": [{"ticket": "t_nothere1"}]},
    ],
)
def test_propose_refuses_bad_drafts(ws, inrun, bad):
    with pytest.raises(cc.CheckupError) as e:
        cc.propose(ws, draft(**bad))
    assert e.value.code == "invalid"


def test_propose_new_skill_rules(ws, inrun):
    new = {"kind": "skill.new", "target": {"kind": "skill", "name": "refund-flow"},
           "change": {"files": [{"path": "SKILL.md", "after": NEW_SKILL}]}}  # fmt: skip
    assert cc.propose(ws, draft(**new))["status"] == "proposed"
    for name in ("invoice-export", "orch-x", "orch"):
        with pytest.raises(cc.CheckupError) as e:
            cc.propose(ws, draft(**{**new, "target": {"kind": "skill", "name": name}}))
        assert e.value.code == "conflict"
    with pytest.raises(cc.CheckupError):
        cc.propose(ws, draft(**{**new, "change": {"files": [{"path": "x.md", "after": "x"}]}}))


def test_propose_fix_of_a_missing_or_builtin_skill(ws, inrun):
    with pytest.raises(cc.CheckupError) as e:
        cc.propose(ws, draft(target={"kind": "skill", "name": "nothing-here"}))
    assert e.value.code == "not_found"
    with pytest.raises(cc.CheckupError):
        cc.propose(ws, draft(target={"kind": "skill", "name": "orch"}))


def test_cli_propose_from_stdin_and_draft(ws, inrun, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(draft())))
    assert cli.main(["--dir", str(ws), "propose", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "proposed"
    assert cli.main(["--dir", str(ws), "propose", "--json", "--draft", json.dumps(draft())]) == 0
    capsys.readouterr()
    assert cli.main(["--dir", str(ws), "propose", "--json", "--draft", "{nope"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "invalid"


# ------------------------------------------------------------------------------------------ test in a copy


def test_test_never_writes_the_real_workspace(ws, inrun):
    pid = proposed(ws)
    before = tree(ws)
    res = cc.run_test(ws, pid)
    assert tree(ws) == before
    assert res["status"] == "tested" and res["tests"]["state"] == "passed"
    assert res["tests"]["cases"] == 1 and res["tests"]["cases_passed"] == 1
    assert cc.load(ws, pid)["tests"]["hash"] == cc.proposal_hash(cc.load(ws, pid))


def test_test_fails_for_a_broken_skill_file(ws, inrun):
    pid = proposed(ws, change={"files": [{"path": "SKILL.md", "after": "no header here"}]})
    res = cc.run_test(ws, pid)
    assert res["status"] == "proposed" and res["tests"]["state"] == "failed"
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, pid)
    assert e.value.code == "not_tested"


def test_test_marks_better_when_the_description_fits(ws, inrun):
    new_desc = SKILL.replace("Export invoices to CSV with dates", "Export October invoices to CSV")
    pid = proposed(ws, change={"files": [{"path": "SKILL.md", "after": new_desc}]})
    assert cc.run_test(ws, pid)["tests"]["detail"][0]["result"] == "better"


def test_test_after_the_skill_changed_is_stale(ws, inrun):
    pid = proposed(ws)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text(SKILL + "more\n")
    with pytest.raises(cc.CheckupError) as e:
        cc.run_test(ws, pid)
    assert e.value.code == "stale" and cc.load(ws, pid)["status"] == "stale"


def test_a_note_has_nothing_to_test(ws, inrun):
    pid = cc.propose(ws, draft(kind="note", change=None, target={"kind": "key", "name": "deploy"}))["id"]
    with pytest.raises(cc.CheckupError) as e:
        cc.run_test(ws, pid)
    assert e.value.code == "invalid"


# ------------------------------------------------------------------------------------------ accept / rollback / reject


def test_accept_writes_only_the_skill_folder_and_rollback_restores(ws, inrun):
    pid = mk_tested(ws)
    skill = ws / ".agents/skills/invoice-export"
    old = cc.skill_files(skill)
    outside = tree(ws)
    assert cc.accept(ws, pid) == {"id": pid, "status": "accepted"}
    assert b"YYYY-MM-DD" in (skill / "SKILL.md").read_bytes()
    doc = cc.load(ws, pid)
    assert doc["applied"]["version_before"] == cc.skill_version(old)
    assert doc["applied"]["version_after"] == cc.skill_version(cc.skill_files(skill))
    new = (skill / "SKILL.md").read_bytes()
    (skill / "SKILL.md").write_bytes(old["SKILL.md"])
    assert tree(ws) == outside  # nothing else in the project changed
    (skill / "SKILL.md").write_bytes(new)
    assert cc.rollback(ws, pid)["status"] == "rolled_back"
    assert cc.skill_files(skill) == old


def test_accept_refuses_a_proposal_changed_after_the_test(ws, inrun):
    pid = mk_tested(ws)
    p = ws / ".orch/insights/proposals" / f"{pid}.json"
    doc = json.loads(p.read_text())
    for field, value in (
        ("title", "other"),
        ("plain", "Delete everything."),
        ("likely", True),
        ("evidence", []),
    ):
        p.write_text(json.dumps({**doc, field: value}))
        with pytest.raises(cc.CheckupError) as e:
            cc.accept(ws, pid)
        assert e.value.code == "changed", field
    doc["change"]["files"][0]["after"] = "evil\n"
    p.write_text(json.dumps(doc))
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, pid)
    assert (
        e.value.code == "changed"
        and b"evil" not in (ws / ".agents/skills/invoice-export/SKILL.md").read_bytes()
    )


def test_accept_refusal_codes(ws, inrun):
    pid = proposed(ws)
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, pid)
    assert e.value.code == "not_tested"
    cc.run_test(ws, pid)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text(SKILL + "x\n")
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, pid)
    assert e.value.code == "stale"
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, "pr_nonexist01")
    assert e.value.code == "not_found"


def test_admin_skill_is_admin_only(ws, inrun):
    (ws / ".agents/skills/invoice-export/.orch-shared").write_text("")
    pid = mk_tested(ws)
    with pytest.raises(cc.CheckupError) as e:
        cc.accept(ws, pid)
    assert e.value.code == "admin_only"


def test_rollback_after_another_change_is_a_conflict(ws, inrun):
    pid = mk_tested(ws)
    cc.accept(ws, pid)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text("changed again\n")
    with pytest.raises(cc.CheckupError) as e:
        cc.rollback(ws, pid)
    assert e.value.code == "conflict" and cc.load(ws, pid)["status"] == "accepted"


def test_rollback_checks_the_kept_files(ws, inrun):
    pid = mk_tested(ws)
    cc.accept(ws, pid)
    (ws / ".orch/insights/proposals" / pid / "before" / "SKILL.md").write_text("planted\n")
    with pytest.raises(cc.CheckupError) as e:
        cc.rollback(ws, pid)
    assert e.value.code == "changed"
    assert b"YYYY-MM-DD" in (ws / ".agents/skills/invoice-export/SKILL.md").read_bytes()


def test_a_new_skill_is_added_and_rolled_back(ws, inrun):
    new = {"kind": "skill.new", "target": {"kind": "skill", "name": "refund-flow"},
           "change": {"files": [{"path": "SKILL.md", "after": NEW_SKILL}, {"path": "notes/a.md", "after": "a\n"}]}}  # fmt: skip
    pid = mk_tested(ws, **new)
    folder = ws / ".agents/skills/refund-flow"
    assert not folder.exists()
    cc.accept(ws, pid)
    assert (folder / "notes/a.md").read_text() == "a\n"
    cc.rollback(ws, pid)
    assert not folder.exists()


def test_reject_also_dismisses_a_stale_proposal(ws, inrun):
    pid = proposed(ws)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text("moved\n")
    with pytest.raises(cc.CheckupError):
        cc.run_test(ws, pid)
    assert cc.reject(ws, pid)["status"] == "rejected"
    with pytest.raises(cc.CheckupError) as e:
        cc.reject(ws, pid)
    assert e.value.code == "conflict"


def test_accept_does_not_follow_a_link_in_the_skill_folder(ws, inrun, tmp_path):
    pid = mk_tested(ws, change={"files": [{"path": "notes/a.md", "after": "x"}]})
    out = tmp_path / "out"
    out.mkdir()
    (ws / ".agents/skills/invoice-export/notes").symlink_to(out, target_is_directory=True)
    with pytest.raises(cc.CheckupError):
        cc.accept(ws, pid)
    assert not list(out.iterdir())


def test_the_whole_flow_with_real_locks(ws, inrun):
    pid = mk_tested(ws)
    cc.accept(ws, pid)
    assert cc.rollback(ws, pid)["status"] == "rolled_back"


# ------------------------------------------------------------------------------------------ list / show / start / weekly


def test_list_show_and_cli(ws, inrun, capsys):
    pid = mk_tested(ws)
    assert cli.main(["--dir", str(ws), "checkup", "list", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["running"] is False and res["weekly"] == "off"
    (item,) = res["proposals"]
    assert item["id"] == pid and item["status"] == "tested" and "change" not in item
    assert item["tests"] == {"state": "passed", "cases_passed": 1, "cases": 1}
    assert cli.main(["--dir", str(ws), "checkup", "show", pid, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["diff"][0]["path"] == "SKILL.md" and "as you like" in shown["diff"][0]["before_text"]
    assert len(shown["hash"]) == 64
    assert cli.main(["--dir", str(ws), "checkup", "accept", "pr_nonexist01", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "not_found"
    assert cli.main(["--dir", str(ws), "checkup", "accept", pid, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": pid, "status": "accepted"}


def test_start_makes_a_read_only_ticket_and_lists_it(ws, fake, capsys):
    fake.counts = {
        "runs": 40,
        "tickets": 5,
        "items": [{"kind": "skill", "name": "invoice-export", "source": "workspace", "uses": 4, "failed": 3}],
    }
    assert cli.main(["--dir", str(ws), "checkup", "start", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ticket": CHK, "result": "started"}
    new = next(c for c in fake.calls if c[:2] == ["ticket", "new"])
    assert "--read-only" in new and new[new.index("--allow-cmd") + 1] == "insights propose"
    summary = next(c for c in fake.calls if c[:2] == ["ticket", "summary"])
    assert "invoice-export failed 3 of 4" in summary[3]
    assert ["run", "start", CHK, "--fresh", "--mode", "oneshot"] in fake.calls
    last = cc.listing(ws)["last"]
    assert last["ticket"] == CHK and last["runs"] == 40 and last["found"] == 0
    fake.running = True
    assert cc.start(ws)["result"] == "busy"


def test_weekly_uses_automation(ws, fake):
    assert cc.weekly_state(ws) == "off"
    assert cc.weekly(ws, True) == {"weekly": "on"}
    assert ["automation", "repeat", CHK, "every monday 07:00"] in fake.calls
    assert cc.weekly(ws, False) == {"weekly": "off"}
    fake.automation = False
    assert cc.weekly_state(ws) == "unavailable"
    with pytest.raises(cc.CheckupError) as e:
        cc.weekly(ws, True)
    assert e.value.code == "not_available"


def test_finder(ws, fake):
    f = cc.finder(ws)
    assert f["candidates"] == [
        {"kind": "note", "name": "invoice-export", "text": "skill invoice-export was not used in 30 days"}
    ]
    assert "nothing" not in cc.finder_text(f)
