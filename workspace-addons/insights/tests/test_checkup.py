"""T0 check-up: the op table (one argv per op, bad ids refused), the proof only on needs_person, fixed texts, the
cleaned reads and the `needs` output. The core is a fake `orch` that follows the "CLI JSON" block of the design."""

import json
import sys

import pytest
from conftest import FakeSession, calls
from test_overview import request
from test_settings import link, person, post

from orch_insights import actions
from orch_insights.checkup import build_checkup, build_show
from orch_insights.needs import rows

HASH = "ab" * 32
PID = "pr_abcd1234"


def proposal(**over):
    base = {
        "id": PID, "kind": "skill.fix", "title": "Make the invoice skill check the date", "plain": "Adds one line.",
        "likely": False, "status": "tested",
        "tests": {"state": "passed", "cases_passed": 3, "cases": 3, "ran_at": "2026-11-15T07:00:00Z"},
        "target": {"kind": "skill", "name": "invoices", "source": "workspace", "version": "sha256:" + "0" * 64},
    }  # fmt: skip
    return {**base, **over}


LISTING = {
    "last": {"ticket": "t_chk123", "at": "2026-11-15T08:12:00Z", "runs": 412, "tickets": 38, "found": 3},
    "running": False, "weekly": "off",
    "proposals": [proposal(), proposal(id="pr_zzzz9999", status="proposed", likely=True)],
}  # fmt: skip

# Answers are files "<name>.json" next to the script; "<name>.code" is the exit code (default 0). Every call is logged
# by conftest-style calls.jsonl. A valid proof is a string the FakeSession minted for that op/target (minted.jsonl).
FAKE = """#!{python}
import json, sys
from pathlib import Path
folder = Path(__file__).parent
args = sys.argv[1:]
stdin = sys.stdin.read()
with open(folder / "calls.jsonl", "a") as log:
    log.write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
plain = [a for a in args if a != "--proof-stdin"]
def answer(name, code=0):
    f = folder / (name + ".json")
    print(f.read_text() if f.exists() else "{{}}")
    sys.exit(int((folder / (name + ".code")).read_text()) if (folder / (name + ".code")).exists() else code)
def proof_ok(op, target):
    if "--proof-stdin" not in args or not stdin:
        return False
    proof = stdin.splitlines()[0]
    m = folder / "minted.jsonl"
    rows = [json.loads(x) for x in m.read_text().splitlines()] if m.exists() else []
    return {{"op": op, "target": target, "proof": proof}} in rows
def need(op, target):
    if not proof_ok(op, target):
        print(json.dumps({{"error": "x", "code": "needs_person"}}))
        sys.exit(2)
if plain[:2] == ["checkup", "list"]:
    answer("list")
verb = plain[1] if plain[:1] == ["checkup"] and len(plain) > 1 else ""
if verb == "show":
    answer("show")
if (folder / "refuse.json").exists() and verb in ("accept", "rollback", "reject", "test", "start", "weekly"):
    print((folder / "refuse.json").read_text()); sys.exit(2)
if verb == "start":
    answer("start")
if verb == "test":
    answer("test")
if verb == "accept":
    need("checkup.accept", plain[2] + "@" + json.loads((folder / "show.json").read_text())["hash"]); answer("accept")
if verb in ("rollback", "reject"):
    need("checkup." + verb, plain[2]); answer(verb)
if verb == "weekly":
    need("insights.settings", "checkup.weekly=" + plain[2]); answer("weekly")
sys.exit(3)
"""


@pytest.fixture
def core(tmp_path):
    folder = tmp_path / "core"
    folder.mkdir()
    script = folder / "orch"
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(0o755)
    put(script, "list", LISTING)
    put(
        script,
        "show",
        {**proposal(), "hash": HASH, "diff": [{"path": "SKILL.md", "before_text": "a\n", "after": "b\n"}]},
    )
    put(script, "start", {"ticket": "t_chk123", "result": "started"})
    put(
        script,
        "test",
        {"id": PID, "status": "tested", "tests": {"state": "passed", "cases": 3, "ran_at": "x"}},
    )
    put(script, "accept", {"id": PID, "status": "accepted"})
    put(script, "rollback", {"id": PID, "status": "rolled_back"})
    put(script, "reject", {"id": PID, "status": "rejected"})
    put(script, "weekly", {"weekly": "on"})
    return script


@pytest.fixture
def fake_session(core):
    return FakeSession(core.parent)  # minted proofs land where this core looks for them


def put(script, name, data):
    (script.parent / f"{name}.json").write_text(json.dumps(data))


def act(srv, op, args=None):
    return person(srv, {"op": op, "args": args or {}})


def argvs(core):
    return [c["args"] for c in calls(core)]


@pytest.mark.parametrize(
    ("op", "args", "argv"),
    [
        ("checkup.start", {}, ["checkup", "start", "--json"]),
        ("checkup.test", {"id": PID}, ["checkup", "test", PID, "--json"]),
        ("checkup.accept", {"id": PID}, ["checkup", "accept", PID, "--json"]),
        ("checkup.rollback", {"id": PID}, ["checkup", "rollback", PID, "--json"]),
        ("checkup.reject", {"id": PID}, ["checkup", "reject", PID, "--json"]),
        ("checkup.weekly", {"value": "on"}, ["checkup", "weekly", "on", "--json"]),
        ("checkup.weekly", {"value": "off"}, ["checkup", "weekly", "off", "--json"]),
    ],
)
def test_one_argv_per_op(op, args, argv):
    assert actions.build_argv(op, args) == argv


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("checkup.test", {"id": "../x"}),
        ("checkup.test", {"id": "pr_ABCD1234"}),
        ("checkup.test", {"id": "pr_abc"}),
        ("checkup.test", {"id": "t_abc123"}),
        ("checkup.accept", {"id": PID + "\n--by"}),
        ("checkup.accept", {}),
        ("checkup.reject", {"id": 5}),
        ("checkup.start", {"id": PID}),
        ("checkup.weekly", {"value": "yes"}),
        ("checkup.weekly", {}),
        ("checkup.accept", {"id": PID, "by": "human:x"}),
        ("checkup.nope", {}),
    ],
)
def test_bad_requests_refused_before_any_run(start_server, core, fake_session, op, args):
    srv = start_server(orch_bin=core, session=fake_session)
    assert act(srv, op, args)[0] == 400
    assert calls(core) == [] and fake_session.minted == []


def test_start_and_test_never_mint(start_server, core, fake_session):
    srv = start_server(orch_bin=core, session=fake_session)
    code, _, body = act(srv, "checkup.start")
    assert code == 200 and json.loads(body) == {"result": {"ticket": "t_chk123", "result": "started"}}
    code, _, body = act(srv, "checkup.test", {"id": PID})
    assert code == 200 and json.loads(body) == {
        "result": {"id": PID, "status": "tested", "tests": {"state": "passed"}}
    }
    assert fake_session.minted == []
    assert argvs(core) == [["checkup", "start", "--json"], ["checkup", "test", PID, "--json"]]


def test_accept_mints_only_on_needs_person_with_the_hash_of_show(start_server, core, fake_session):
    srv = start_server(orch_bin=core, session=fake_session)
    code, _, body = act(srv, "checkup.accept", {"id": PID})
    assert code == 200 and json.loads(body) == {"result": {"id": PID, "status": "accepted"}}
    assert fake_session.minted == [("checkup.accept", f"{PID}@{HASH}")]
    a = argvs(core)
    assert a == [["checkup", "accept", PID, "--json"], ["checkup", "show", PID, "--json"],
                 ["checkup", "accept", PID, "--json", "--proof-stdin"]]  # fmt: skip
    proof = calls(core)[-1]["stdin"].splitlines()[0]
    assert proof == "hp1.fakeproof1.mac" and not any(proof in x for x in a[-1])


@pytest.mark.parametrize("verb", ["rollback", "reject"])
def test_rollback_and_reject_mint_op_and_id(start_server, core, fake_session, verb):
    srv = start_server(orch_bin=core, session=fake_session)
    assert act(srv, f"checkup.{verb}", {"id": PID})[0] == 200
    assert fake_session.minted == [(f"checkup.{verb}", PID)]


def test_weekly_mints_the_value_bound_settings_target(start_server, core, fake_session):
    srv = start_server(orch_bin=core, session=fake_session)
    code, _, body = act(srv, "checkup.weekly", {"value": "on"})
    assert code == 200 and json.loads(body) == {"result": {"weekly": "on"}}
    assert fake_session.minted == [("insights.settings", "checkup.weekly=on")]


def test_no_person_no_mint(start_server, core):
    srv = start_server(orch_bin=core)  # no session: watch-only
    code, _, body = post(srv, {"op": "checkup.accept", "args": {"id": PID}})
    assert code == 403 and body.decode() == actions.PERSON
    assert argvs(core) == [["checkup", "accept", PID, "--json"]]


def test_unreadable_hash_refuses_without_minting(start_server, core, fake_session):
    put(core, "show", {"hash": "nothex"})
    srv = start_server(orch_bin=core, session=fake_session)
    code, _, body = act(srv, "checkup.accept", {"id": PID})
    assert code == 422 and body.decode() == actions.FAILED and fake_session.minted == []


@pytest.mark.parametrize(
    ("why", "text"),
    [
        ("stale", "The skill changed since this was suggested. Run a new check-up."),
        ("not_tested", "Test it first."),
        ("admin_only", "Shared by your admin: ask your admin."),
        ("conflict", "Changed since it was applied. Nothing was rolled back."),
        ("not_supported", "Check-up needs Claude as the agent for now."),
        ("not_found", "That ticket was not found."),
        ("surprise", "That did not work."),
    ],
)
def test_core_refusals_are_fixed_texts(start_server, core, fake_session, why, text):
    (core.parent / "refuse.json").write_text(json.dumps({"error": "SECRET core words", "code": why}))
    srv = start_server(orch_bin=core, session=fake_session)
    code, _, body = act(srv, "checkup.test", {"id": PID})
    assert code == 422 and body.decode() == text and b"SECRET" not in body


def test_success_answer_is_cleaned(start_server, core, fake_session):
    put(core, "start", {"ticket": "t_chk123", "result": "started", "extra": "<script>", "secret": "x"})
    srv = start_server(orch_bin=core, session=fake_session)
    assert json.loads(act(srv, "checkup.start")[2]) == {"result": {"ticket": "t_chk123", "result": "started"}}


def test_list_read_is_whitelisted(start_server, core):
    dirty = json.loads(json.dumps(LISTING))
    dirty["proposals"][0]["change"] = {"files": [{"path": "SKILL.md", "after": "SECRET"}]}
    dirty["proposals"][0]["evidence"] = [{"ticket": "t_abc123"}]
    dirty["proposals"].append(
        {"id": "../evil", "kind": "note", "title": "x", "plain": "y", "status": "proposed"}
    )
    dirty["proposals"].append(proposal(id="pr_rejected1", status="rejected"))
    put(core, "list", dirty)
    srv = start_server(orch_bin=core)
    code, _, body = request(srv, "/api/checkup")
    data = json.loads(body)
    assert code == 200 and b"SECRET" not in body and b"evidence" not in body
    assert [p["id"] for p in data["proposals"]] == [PID, "pr_zzzz9999"]
    assert data["last"] == {
        "ticket": "t_chk123",
        "at": "2026-11-15T08:12:00Z",
        "runs": 412,
        "tickets": 38,
        "found": 3,
    }
    assert data["weekly"] == "off" and data["running"] is False and data["available"] is True
    assert set(data["proposals"][0]) == {
        "id",
        "kind",
        "title",
        "plain",
        "likely",
        "status",
        "tests",
        "target",
    }


def test_list_unreadable_means_not_available(start_server, core):
    (core.parent / "list.code").write_text("1")
    srv = start_server(orch_bin=core)
    assert json.loads(request(srv, "/api/checkup")[2]) == {"available": False}
    assert build_checkup({"proposals": "x"}) == {"available": False}
    assert build_checkup(None) == {"available": False}


def test_weekly_unknown_is_unavailable():
    assert build_checkup({"proposals": [], "weekly": "unavailable"})["weekly"] == "unavailable"
    assert build_checkup({"proposals": [], "weekly": "maybe"})["weekly"] == "unavailable"


def test_show_read_has_the_diff_and_no_hash(start_server, core):
    srv = start_server(orch_bin=core)
    code, _, body = request(srv, f"/api/checkup/{PID}")
    data = json.loads(body)
    assert code == 200 and data["diff"] == [{"path": "SKILL.md", "before_text": "a\n", "after": "b\n"}]
    assert HASH.encode() not in body and data["hashed"] is True
    assert request(srv, "/api/checkup/not-an-id")[0] == 404
    assert build_show({"id": "bad"}) is None


def test_needs_one_row_while_something_is_open(core):
    out = rows(core.parent.parent, core)
    assert len(out) == 1
    row = out[0]
    assert row["text"] == "Check-up has 2 suggestions to look at" and row["source"] == "insights"
    assert row["id"].startswith("insights:") and row["ticket"] is None and row["tone"] == "warn"
    assert row["since"] == "2026-11-15T08:12:00Z"


def test_needs_nothing_when_all_decided_or_cli_fails(core):
    done = json.loads(json.dumps(LISTING))
    for p in done["proposals"]:
        p["status"] = "accepted"
    put(core, "list", done)
    assert rows(core.parent.parent, core) == []
    (core.parent / "list.code").write_text("1")
    assert rows(core.parent.parent, core) == []


def test_needs_cli_prints_json(core, ws, monkeypatch, capsys):
    from orch_insights import cli

    monkeypatch.setenv("ORCH_BIN", str(core))
    assert cli.main(["--dir", str(ws), "needs", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["kind"] for r in out] == ["insights:checkup"]
    (core.parent / "list.code").write_text("1")
    assert cli.main(["--dir", str(ws), "needs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_session_is_a_fake_session_class():
    assert FakeSession.token and link  # imports used by the helpers above


def test_page_serves_the_card_script_and_markup(server):
    code, _, body = request(server, "/web/checkup.js")
    assert code == 200 and b"checkup.accept" in body
    page = request(server, "/")[2].decode()
    assert 'id="checkup"' in page and "/web/checkup.js" in page
    assert page.index('id="checkup"') < page.index('id="overview"')  # the card sits above the overview
