# ruff: noqa: E501
"""The weekly check-up core (contracts/proposal.md, vectors/proposal-v1.json): propose, isolated test,
accept / roll back / reject with a person's proof, counts, the read-only run."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from orch import adapters, checkup, runs, tickets
from orch import humanproof as hp

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VEC = json.loads((CONTRACTS / "vectors/proposal-v1.json").read_text())
SCHEMA = json.loads((CONTRACTS / "proposal.schema.json").read_text())
SKILL = "---\nname: invoice-export\ndescription: Export invoices to CSV with dates\n---\n# Invoice export\nWrite dates as you like.\n"
NEW_SKILL = "---\nname: refund-flow\ndescription: Handle a customer refund request\n---\n# Refund flow\nCheck the order first.\n"


@pytest.fixture
def ws(proj, monkeypatch):
    """A TEST workspace under <fake home>/.orch-test with its test orch home, one skill and two tickets."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    d = root / ".agents" / "skills" / "invoice-export"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL)
    return root


def make_ticket(ws, title="Export the invoices for October as CSV"):
    return tickets.create(ws, title, "human:pat", None, None, {})["id"]


@pytest.fixture
def inrun(ws, monkeypatch):
    """The caller is a check-up run: a listed check-up ticket, a claimed run with profile checkup, ORCH_RUN."""
    tid = checkup._ensure_ticket(ws, "human:pat")
    rec = runs.claim(ws, tid, "human:pat", "claude", "oneshot")
    assert rec["profile"] == "checkup"
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", tid)
    yield rec
    monkeypatch.delenv("ORCH_RUN")
    monkeypatch.delenv("ORCH_TICKET")


def draft(ws, **over):
    t = make_ticket(ws)
    d = {
        "kind": "skill.fix",
        "title": "invoice-export: say the date format",
        "plain": "Write dates as YYYY-MM-DD.",
        "likely": False,
        "evidence": [{"ticket": t}],
        "target": {"kind": "skill", "name": "invoice-export"},
        "change": {"files": [{"path": "SKILL.md", "after": SKILL.replace("as you like", "as YYYY-MM-DD")}]},
    }
    d.update(over)
    return d


def tree(ws, orch=True):
    """Hash of everything in the workspace except the check-up's own record folder (`.orch/record/proposals`);
    orch=False leaves `.orch` out too (the project itself)."""
    h = hashlib.sha256()
    for p in sorted(ws.rglob("*")):
        if "proposals" in p.parts or p.name.endswith(".lock") or (not orch and ".orch" in p.parts):
            continue
        h.update(str(p.relative_to(ws)).encode())
        if p.is_file() and not p.is_symlink():
            h.update(p.read_bytes())
    return h.hexdigest()


def proof(ws, op, target, **kw):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, kw.pop("by", "human:pat"), **kw))


def cli(run, monkeypatch, line, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((line + "\n") if line else ""))
    return run(*argv, "--proof-stdin", "--json")


def answer(out):
    return json.loads(out.strip().splitlines()[-1])


def propose_one(ws, inrun, **over):
    return checkup.propose(ws, draft(ws, **over))["id"]


def make_tested(ws, inrun, **over):
    pid = propose_one(ws, inrun, **over)
    assert checkup.run_test(ws, pid)["status"] == "tested"
    return pid


def accept_cli(ws, run, monkeypatch, pid):
    ent = checkup._entry(ws, pid)
    target = f"{pid}@{ent['hash'].removeprefix('sha256:')}"
    return cli(run, monkeypatch, proof(ws, "checkup.accept", target), "checkup", "accept", pid)


# ------------------------------------------------------------------------------------------ the contract vectors


@pytest.mark.parametrize("case", VEC["steps"], ids=lambda c: c["name"])
def test_vectors_steps(case):
    assert checkup.step(case) == case["result"]
    if case["result"] == "accepted":  # the recorded hash is the one proposal_hash makes of the file
        assert checkup.proposal_hash(case["file"]) == case["record"]["hash"]


def reference(draft_, ctx):
    try:
        checkup.validate_draft(draft_)
    except checkup.CheckupError:
        return "refused:invalid"
    if ctx.get("profile") != "checkup":
        return "refused:not_checkup"
    if draft_["kind"] == "skill.new" and (
        draft_["target"]["name"].startswith("orch") or draft_["target"]["name"] in ctx["existing_names"]
    ):
        return "refused:name_taken"
    return checkup.from_draft(draft_, ctx)


@pytest.mark.parametrize("case", VEC["from_draft"], ids=lambda c: c["name"])
def test_vectors_from_draft(case):
    got = reference(case["draft"], case["ctx"])
    assert got == case["expect"]
    if isinstance(got, dict):
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(got)


def test_validate_draft_matches_the_draft_schema():
    v = Draft202012Validator(
        {"$ref": "#/$defs/draft", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
    )
    good = VEC["from_draft"][0]["draft"]
    for ex in (
        good,
        {**good, "title": "x" * 121},
        {**good, "likely": "no"},
        {**good, "evidence": [{"ticket": "bad"}]},
        {**good, "target": {"kind": "skill", "name": "../x"}},
        {**good, "change": {"files": [{"path": "/etc/x", "after": "x"}]}},
        {**good, "change": {"files": [{"path": "a\\b", "after": "x"}]}},
        {**good, "change": {"files": [{"path": "a/.b", "after": "x"}]}},
        {**good, "change": {"files": [{"path": "..", "after": "x"}]}},
        {**good, "change": {"files": []}},
        {**good, "change": {"files": [{"path": "a", "after": "x" * 65537}]}},
        {**good, "status": "tested"},
        {**good, "plain": "bad\x01"},
    ):
        ok = not list(v.iter_errors(ex))
        try:
            checkup.validate_draft(ex)
            mine = True
        except checkup.CheckupError:
            mine = False
        assert mine == ok, ex


# ------------------------------------------------------------------------------------------ propose


def test_propose_outside_a_checkup_run_is_refused(ws):
    with pytest.raises(checkup.CheckupError) as e:
        checkup.propose(ws, draft(ws))
    assert e.value.code == "not_checkup"
    assert not (ws / ".orch" / "record" / "proposals").exists()


def test_propose_from_env_alone_is_refused(ws, monkeypatch):
    """ORCH_RUN of a normal run, or of a ticket that is not listed, is no check-up."""
    t = make_ticket(ws)
    rec = runs.claim(ws, t, "human:pat", "claude", "oneshot")
    assert "profile" not in rec
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t)
    with pytest.raises(checkup.CheckupError) as e:
        checkup.propose(ws, draft(ws))
    assert e.value.code == "not_checkup"


def test_propose_builds_the_proposal_in_the_core(ws, inrun):
    d = draft(ws)
    pid = checkup.propose(ws, d)["id"]
    doc = json.loads((ws / ".orch/record/proposals" / f"{pid}.json").read_text())
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(doc)
    assert doc["status"] == "proposed" and doc["tests"]["state"] == "not_run"
    assert doc["checkup"] == {"ticket": inrun["ticket"], "run": inrun["run"]}
    assert doc["target"]["source"] == "workspace"
    files = checkup.skill_files(ws / ".agents/skills/invoice-export")
    assert doc["target"]["version"] == checkup.skill_version(files)
    assert doc["change"]["files"][0]["before"] == checkup.sha(files["SKILL.md"])
    ent = checkup._entry(ws, pid)
    assert ent["status"] == "proposed" and ent["hash"] == checkup.proposal_hash(doc)


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "tested"},
        {"target": {"kind": "skill", "name": "invoice-export", "version": "sha256:" + "a" * 64}},
        {"kind": "note"},  # a note carries no files
        {"change": {"files": [{"path": "a/.orch-shared", "after": "x"}]}},
        {"change": {"files": [{"path": "SKILL.md", "after": "x"}, {"path": "SKILL.md", "after": "y"}]}},
    ],
)
def test_propose_refuses_bad_drafts(ws, inrun, bad):
    with pytest.raises(checkup.CheckupError) as e:
        checkup.propose(ws, draft(ws, **bad))
    assert e.value.code == "invalid"


def test_propose_new_skill_rules(ws, inrun):
    new = {
        "kind": "skill.new",
        "target": {"kind": "skill", "name": "refund-flow"},
        "change": {"files": [{"path": "SKILL.md", "after": NEW_SKILL}]},
    }
    assert checkup.propose(ws, draft(ws, **new))["status"] == "proposed"
    for name in ("invoice-export", "orch-x", "orch"):
        with pytest.raises(checkup.CheckupError) as e:
            checkup.propose(ws, draft(ws, **{**new, "target": {"kind": "skill", "name": name}}))
        assert e.value.code == "conflict"
    with pytest.raises(checkup.CheckupError):  # a new skill needs a SKILL.md
        checkup.propose(ws, draft(ws, **{**new, "change": {"files": [{"path": "x.md", "after": "x"}]}}))


def test_propose_fix_of_a_missing_or_builtin_skill(ws, inrun):
    with pytest.raises(checkup.CheckupError) as e:
        checkup.propose(ws, draft(ws, target={"kind": "skill", "name": "nothing-here"}))
    assert e.value.code == "not_found"
    with pytest.raises(checkup.CheckupError):
        checkup.propose(ws, draft(ws, target={"kind": "skill", "name": "orch"}))


def test_cli_record_propose(ws, inrun, run, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(draft(ws))))
    code, out, _ = run("record", "propose", "--json")
    assert code == 0 and answer(out)["status"] == "proposed"
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out, _ = run("record", "propose", "--json")
    assert code == 2 and answer(out)["code"] == "invalid"


def test_cli_record_propose_outside_a_run(ws, run, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(draft(ws))))
    code, out, _ = run("record", "propose", "--json")
    assert code == 2 and answer(out)["code"] == "not_checkup"


# ------------------------------------------------------------------------------------------ test in a copy


def test_test_never_writes_the_real_workspace(ws, inrun):
    pid = propose_one(ws, inrun)
    before = tree(ws)
    res = checkup.run_test(ws, pid)
    assert tree(ws) == before  # the real workspace is as it was (the result lives in the record)
    assert res["status"] == "tested" and res["tests"]["state"] == "passed"
    assert res["tests"]["cases"] == 1 and res["tests"]["cases_passed"] == 1
    assert checkup._entry(ws, pid)["status"] == "tested"
    assert not (hp.guarded_home(ws) / "checkup-tmp").exists()  # the copy is removed
    assert json.loads((ws / ".orch/record/proposals" / f"{pid}.json").read_text())["status"] == "tested"


def test_test_fails_for_a_broken_skill_file(ws, inrun):
    pid = propose_one(ws, inrun, change={"files": [{"path": "SKILL.md", "after": "no header here"}]})
    res = checkup.run_test(ws, pid)
    assert res["status"] == "proposed" and res["tests"]["state"] == "failed"
    assert res["tests"]["detail"][0]["result"] == "worse"
    with pytest.raises(checkup.CheckupError) as e:
        checkup.accept(ws, _args(), pid)
    assert e.value.code == "not_tested"


def test_test_marks_better_when_the_description_fits(ws, inrun):
    new_desc = SKILL.replace("Export invoices to CSV with dates", "Export October invoices to CSV")
    pid = propose_one(ws, inrun, change={"files": [{"path": "SKILL.md", "after": new_desc}]})
    assert checkup.run_test(ws, pid)["tests"]["detail"][0]["result"] == "better"


def test_test_after_the_skill_changed_is_stale(ws, inrun):
    pid = propose_one(ws, inrun)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text(SKILL + "more\n")
    with pytest.raises(checkup.CheckupError) as e:
        checkup.run_test(ws, pid)
    assert e.value.code == "stale" and checkup._entry(ws, pid)["status"] == "stale"


def test_test_refuses_a_changed_workspace_copy(ws, inrun):
    pid = propose_one(ws, inrun)
    p = ws / ".orch/record/proposals" / f"{pid}.json"
    doc = json.loads(p.read_text())
    doc["target"]["name"] = "other"
    p.write_text(json.dumps(doc))
    with pytest.raises(checkup.CheckupError) as e:
        checkup.run_test(ws, pid)
    assert e.value.code == "changed"


def test_a_note_has_nothing_to_test(ws, inrun):
    pid = checkup.propose(ws, draft(ws, kind="note", change=None, target={"kind": "key", "name": "deploy"}))[
        "id"
    ]
    with pytest.raises(checkup.CheckupError) as e:
        checkup.run_test(ws, pid)
    assert e.value.code == "invalid"


# ------------------------------------------------------------------------------------------ accept / rollback / reject


def _args(**kw):
    import argparse

    return argparse.Namespace(**{"by": None, "proof_stdin": False, **kw})


def test_accept_writes_only_the_skill_folder_and_rollback_restores(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    skill = ws / ".agents/skills/invoice-export"
    old = checkup.skill_files(skill)
    outside = tree(ws, orch=False)
    code, out, err = accept_cli(ws, run, monkeypatch, pid)
    assert code == 0, out + err
    assert answer(out) == {"id": pid, "status": "accepted"}
    assert b"YYYY-MM-DD" in (skill / "SKILL.md").read_bytes()
    ent = checkup._entry(ws, pid)
    assert ent["status"] == "accepted" and ent["decided"]["by"].startswith("human:")
    assert ent["decided"]["op"] == "checkup.accept"
    assert ent["applied"]["version_before"] == checkup.skill_version(old)
    assert ent["applied"]["version_after"] == checkup.skill_version(checkup.skill_files(skill))
    # nothing outside the skill folder (and the check-up's own record) changed
    assert {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()} >= {
        ".agents/skills/invoice-export/SKILL.md"
    }
    (skill / "SKILL.md").write_bytes(old["SKILL.md"])
    assert tree(ws, orch=False) == outside
    (skill / "SKILL.md").write_text(SKILL.replace("as you like", "as YYYY-MM-DD"))
    code, out, err = cli(run, monkeypatch, proof(ws, "checkup.rollback", pid), "checkup", "rollback", pid)
    assert code == 0, out + err
    assert answer(out)["status"] == "rolled_back"
    assert checkup.skill_files(skill) == old
    assert checkup._entry(ws, pid)["status"] == "rolled_back"


def test_accept_without_a_proof_is_needs_person_and_changes_nothing(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    before = tree(ws, orch=False)
    code, out, _ = run("checkup", "accept", pid, "--json")
    assert code == 2 and answer(out)["code"] == "needs_person"
    for bad in (
        "",
        "hp1.e30.AAAA",
        proof(ws, "checkup.accept", pid + "@" + "0" * 64),
        proof(ws, "checkup.reject", pid),
    ):
        code, out, _ = cli(run, monkeypatch, bad, "checkup", "accept", pid)
        assert code == 2 and answer(out)["code"] == "needs_person"
    assert tree(ws, orch=False) == before and checkup._entry(ws, pid)["status"] == "tested"


def test_accept_proof_is_single_use(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    ent = checkup._entry(ws, pid)
    p = proof(ws, "checkup.accept", f"{pid}@{ent['hash'].removeprefix('sha256:')}")
    assert cli(run, monkeypatch, p, "checkup", "accept", pid)[0] == 0
    code, out, _ = cli(run, monkeypatch, p, "checkup", "rollback", pid)
    assert code == 2 and answer(out)["code"] == "needs_person"


def test_an_agent_cannot_decide(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    for sub in ("accept", "rollback", "reject"):
        code, out, _ = run("checkup", sub, pid, "--by", "agent:x", "--json")
        assert code == 2 and answer(out)["code"] == "needs_person"
    monkeypatch.setenv("CLAUDECODE", "1")  # an agent tool in the environment, even with a valid proof
    ent = checkup._entry(ws, pid)
    p = proof(ws, "checkup.accept", f"{pid}@{ent['hash'].removeprefix('sha256:')}")
    code, out, _ = cli(run, monkeypatch, p, "checkup", "accept", pid)
    assert code == 2 and answer(out)["code"] == "needs_person"


def test_accept_refusal_codes(ws, inrun, run, monkeypatch):
    pid = propose_one(ws, inrun)  # not tested
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and answer(out)["code"] == "not_tested"
    checkup.run_test(ws, pid)
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text(SKILL + "x\n")  # the skill moved on
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and answer(out)["code"] == "stale"
    code, out, _ = run("checkup", "accept", "pr_nonexist01", "--json")
    assert code == 2 and answer(out)["code"] == "not_found"


def test_accept_refuses_a_workspace_copy_that_does_not_match_the_record(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    p = ws / ".orch/record/proposals" / f"{pid}.json"
    doc = json.loads(p.read_text())
    doc["change"]["files"][0]["after"] = "evil\n"
    p.write_text(json.dumps(doc))
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and answer(out)["code"] == "changed"
    assert b"evil" not in (ws / ".agents/skills/invoice-export/SKILL.md").read_bytes()


def test_workspace_copy_cannot_claim_tests_passed(ws, inrun, run, monkeypatch):
    pid = propose_one(ws, inrun)
    p = ws / ".orch/record/proposals" / f"{pid}.json"
    doc = json.loads(p.read_text())
    doc["status"], doc["tests"]["state"] = "tested", "passed"
    p.write_text(json.dumps(doc))
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and answer(out)["code"] == "not_tested"


def test_admin_skill_is_admin_only(ws, inrun, run, monkeypatch):
    (ws / ".agents/skills/invoice-export/.orch-shared").write_text("")
    pid = make_tested(ws, inrun)
    assert checkup._entry(ws, pid)["target"]["source"] == "admin"
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and answer(out)["code"] == "admin_only"


def test_rollback_after_another_change_is_a_conflict(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    assert accept_cli(ws, run, monkeypatch, pid)[0] == 0
    (ws / ".agents/skills/invoice-export/SKILL.md").write_text("changed again\n")
    code, out, _ = cli(run, monkeypatch, proof(ws, "checkup.rollback", pid), "checkup", "rollback", pid)
    assert code == 2 and answer(out)["code"] == "conflict"
    assert checkup._entry(ws, pid)["status"] == "accepted"


def test_rollback_checks_the_kept_files_against_the_record(ws, inrun, run, monkeypatch):
    pid = make_tested(ws, inrun)
    assert accept_cli(ws, run, monkeypatch, pid)[0] == 0
    kept = ws / ".orch/record/proposals" / pid / "before" / "SKILL.md"
    kept.write_text("planted\n")  # the kept copy is workspace-writable
    code, out, _ = cli(run, monkeypatch, proof(ws, "checkup.rollback", pid), "checkup", "rollback", pid)
    assert code == 2 and answer(out)["code"] == "changed"
    assert b"YYYY-MM-DD" in (ws / ".agents/skills/invoice-export/SKILL.md").read_bytes()


def test_a_new_skill_is_added_and_rolled_back(ws, inrun, run, monkeypatch):
    new = {
        "kind": "skill.new",
        "target": {"kind": "skill", "name": "refund-flow"},
        "change": {
            "files": [{"path": "SKILL.md", "after": NEW_SKILL}, {"path": "notes/a.md", "after": "a\n"}]
        },
    }
    pid = make_tested(ws, inrun, **new)
    folder = ws / ".agents/skills/refund-flow"
    assert not folder.exists()  # the test ran in a copy
    assert accept_cli(ws, run, monkeypatch, pid)[0] == 0
    assert (folder / "notes/a.md").read_text() == "a\n"
    code, out, _ = cli(run, monkeypatch, proof(ws, "checkup.rollback", pid), "checkup", "rollback", pid)
    assert code == 0 and not folder.exists()


def test_reject(ws, inrun, run, monkeypatch):
    pid = propose_one(ws, inrun)
    code, out, _ = run("checkup", "reject", pid, "--json")
    assert code == 2 and answer(out)["code"] == "needs_person"
    code, out, _ = cli(run, monkeypatch, proof(ws, "checkup.reject", pid), "checkup", "reject", pid)
    assert code == 0 and answer(out) == {"id": pid, "status": "rejected"}
    code, out, _ = cli(run, monkeypatch, proof(ws, "checkup.reject", pid), "checkup", "reject", pid)
    assert code == 2 and answer(out)["code"] == "conflict"


def test_accept_does_not_follow_a_link_in_the_skill_folder(ws, inrun, run, monkeypatch, tmp_path):
    pid = make_tested(ws, inrun, change={"files": [{"path": "notes/a.md", "after": "x"}]})
    outside = tmp_path / "out"
    outside.mkdir()
    (ws / ".agents/skills/invoice-export/notes").symlink_to(outside, target_is_directory=True)
    code, out, _ = accept_cli(ws, run, monkeypatch, pid)
    assert code == 2 and not list(outside.iterdir())


# ------------------------------------------------------------------------------------------ list / show / counts / run


def test_list_and_show(ws, inrun, run):
    pid = make_tested(ws, inrun)
    res = answer(run("checkup", "list", "--json")[1])
    assert res["running"] is True and res["weekly"] in ("off", "unavailable")
    (item,) = res["proposals"]
    assert item["id"] == pid and item["status"] == "tested"
    assert item["tests"] == {"state": "passed", "cases_passed": 1, "cases": 1}
    assert item["target"] == {"kind": "skill", "name": "invoice-export", "source": "workspace"}
    assert "change" not in item
    shown = answer(run("checkup", "show", pid, "--json")[1])
    assert shown["diff"][0]["path"] == "SKILL.md" and "as you like" in shown["diff"][0]["before_text"]
    assert "sha256:" + shown["hash"] == checkup._entry(ws, pid)["hash"] and len(shown["hash"]) == 64


def test_counts_skip_checkup_runs(ws, inrun, run):
    from orch import hider
    from orch.record import RecordWriter

    ex = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    hp.ensure_record_key(ws)
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    other = make_ticket(ws, "another")
    w.append(dict(ex, run="r_8k2m01", ticket=inrun["ticket"], id="toolu_c1", at="2026-11-16T09:10:00Z"))
    w.append(dict(ex, run="r_9z8y77", ticket=other, id="toolu_o1", at="2026-11-16T09:11:00Z"))
    got = answer(run("record", "counts", "--from", "2026-11-01", "--to", "2026-12-31", "--json")[1])
    assert got["runs"] == 1 and got["tickets"] == 1


def test_secret_refuses_inside_a_checkup_run(ws, inrun, run):
    code, out, err = run("secret", "list", "--json")
    assert code == 2 and "check-up" in (out + err).lower()


def test_run_argv_is_read_only_and_always_fresh(ws, inrun):
    rec = inrun
    runs.release(ws, rec["ticket"], rec["run"])
    p = runs.plan(ws, rec["ticket"], mode="live", agent="claude")
    argv = p["argv"]
    head = argv[: argv.index("--")]
    assert p["mode"] == "oneshot" and p["resumed"] is False
    allowed = head[head.index("--allowedTools") + 1]
    assert "Bash(orch record propose:*)" in allowed and f"Bash(orch log {rec['ticket']}:*)" in allowed
    assert "orch ticket new" not in allowed and "orch ask" not in allowed and "orch run done" not in allowed
    assert head.count("--allowedTools") == 1
    assert "--strict-mcp-config" in head and "--dangerously-skip-permissions" not in head
    denied = head[head.index("--disallowedTools") + 1]
    for t in ("WebFetch", "Edit", "Write"):
        assert t in denied
    assert "Workspace check-up" in p["prompt"] or "check-up" in p["prompt"]


def test_run_argv_drops_the_no_questions_flags(ws, inrun, monkeypatch):
    argv = [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "auto",
        "--allowedTools",
        "Bash(x)",
        "--",
        "p",
    ]
    out = adapters.readonly_argv("claude", argv, inrun["ticket"], ws)
    assert "--dangerously-skip-permissions" not in out and "--permission-mode" not in out
    assert out[-2:] == ["--", "p"]


def test_other_agents_cannot_run_a_checkup(ws, run):
    assert adapters.readonly("codex") is None and adapters.readonly("generic") is None
    from orch import config

    config.set_key(ws, "workspace", "agent", "codex")
    code, out, _ = run("checkup", "start", "--json")
    assert code == 2 and answer(out)["code"] == "not_supported"
    assert "needs Claude" in answer(out)["error"]


def test_start_creates_the_ticket_and_lists_it(ws, run, monkeypatch):
    started = []
    monkeypatch.setattr(
        runs, "start", lambda root, tid, by, **kw: started.append((tid, kw)) or {"run": "r_x"}
    )
    code, out, err = run("checkup", "start", "--json")
    assert code == 0, out + err
    res = answer(out)
    assert res["result"] == "started" and checkup.is_checkup_ticket(ws, res["ticket"])
    assert started[0][1]["mode"] == "oneshot" and started[0][1]["fresh"] is True
    assert tickets.load(ws, res["ticket"])["title"] == "Workspace check-up"
    last = answer(run("checkup", "list", "--json")[1])["last"]
    assert last["ticket"] == res["ticket"] and last["found"] == 0


def test_finder_from_counts(ws):

    json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    assert checkup.finder(ws) == {
        "runs": 0,
        "tickets": 0,
        "candidates": [
            {"kind": "note", "name": "invoice-export", "text": "skill invoice-export was not used in 30 days"}
        ],
    }
    assert "check-up" in checkup.prompt(ws, "t_abc123")


def test_weekly_needs_the_insights_proof(ws, run, monkeypatch):
    code, out, _ = run("checkup", "weekly", "on", "--json")
    assert code == 2 and answer(out)["code"] in ("needs_person", "not_available")
    monkeypatch.setattr(checkup, "weekly_state", lambda root: "off")
    code, out, _ = cli(
        run, monkeypatch, proof(ws, "insights.settings", "checkup.weekly=on"), "checkup", "weekly", "off"
    )
    assert code == 2 and answer(out)["code"] == "needs_person"  # a proof for "on" is no proof for "off"
