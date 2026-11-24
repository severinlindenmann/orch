"""Before a helper starts, the core asks add-ons with `before_start = true` (before-start.schema.json)."""

import json
import os
from pathlib import Path

import pytest
import test_run_wrap
from jsonschema import Draft202012Validator
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import adapters, addons, modelpick, runs, runs_live, startask, tickets
from orch.errors import Refused

gen = test_run_wrap.gen
_wait = test_run_wrap._wait

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/before-start.schema.json").read_text(encoding="utf-8")
)

ASK_MAIN = """\
import json, os, sys
from pathlib import Path
root = Path(os.environ["ORCH_ROOT"])
if sys.argv[1:2] == ["before-start"]:
    req = json.loads(sys.stdin.read())
    (root / "asked.json").write_text(json.dumps(req))
    p = root / "answer.txt"
    text = p.read_text() if p.exists() else '{"go": true}'
    if text == "crash":
        sys.exit(1)
    print(text)
"""


def _valid(kind: str, value) -> list:
    sub = {**SCHEMA["$defs"][kind], "$defs": SCHEMA["$defs"]}
    return list(Draft202012Validator(sub).iter_errors(value))


@pytest.fixture
def asker(proj, run, tmp_path, monkeypatch, request):
    request.getfixturevalue("uv_calls")
    folder = make_addon(tmp_path / "b", extra="before_start = true")
    (folder / "src/orch_hello/__main__.py").write_text(ASK_MAIN, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    assert run("init")[0] == 0
    install(run, folder)

    def answer(obj):
        (proj / "answer.txt").write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")

    return answer


def _new(proj, title="Make the report"):
    return tickets.create(proj, title, "human:t")["id"]


def test_manifest_key_is_a_boolean(tmp_path):
    folder = make_addon(tmp_path / "a", extra="before_start = true")
    assert addons.folder_manifest(folder)["before_start"] is True
    assert addons.folder_manifest(make_addon(tmp_path / "c"))["before_start"] is False
    with pytest.raises(Refused, match="before_start"):
        addons.folder_manifest(make_addon(tmp_path / "d", extra='before_start = "yes"'))


def test_without_an_asking_addon_nothing_is_called(proj, monkeypatch):
    _new(proj)
    monkeypatch.setattr(startask, "_ask", lambda *a: pytest.fail("asked without an add-on"))
    assert startask.ask(proj, _new(proj), "agent:automation", None, "generic", False) == ({}, [])


def test_request_holds_the_ticket_facts_and_the_choices(proj, asker):
    tid = _new(proj)
    out, notes = startask.ask(proj, tid, "agent:automation", "oneshot", "generic", False)
    assert out == {} and notes == []
    req = json.loads((proj / "asked.json").read_text())
    assert _valid("request", req) == []
    assert req["ticket"] == tid and req["agent"] == "generic" and "generic" in req["agents"]
    assert req["chosen"] == {"agent": False, "model": False}
    assert "history" not in req and "note" not in req


def test_request_says_whose_sign_in_each_tool_runs_on_and_a_move_up(proj, asker, monkeypatch):
    """ORCH-342: an add-on can hold a start that would spend a full subscription, and may narrow the model
    only until orch or the helper moved the ticket up."""
    names = adapters.builtin_names()
    monkeypatch.setattr(adapters, "detect", lambda **_: [{"name": n, "found": True} for n in names])
    tid = _new(proj)
    startask.ask(proj, tid, "agent:automation", None, "generic", False)
    req = json.loads((proj / "asked.json").read_text())
    assert _valid("request", req) == []
    want = {n: adapters.load(n)["provider"] for n in names if adapters.load(n).get("provider")}
    assert req["providers"] == want and len(want) >= 2 and "generic" not in want
    assert req["model_up"] is False

    def op(t):
        t["model"] = {"name": "opus", "by": modelpick.BY_ORCH, "why": "hard", "up": True}

    tickets.apply_op(proj, tid, op, by="human:t")
    startask.ask(proj, tid, "agent:automation", None, "generic", False)
    assert json.loads((proj / "asked.json").read_text())["model_up"] is True


def test_answer_tool_model_and_account_are_used(proj, asker, monkeypatch):
    monkeypatch.setattr(adapters, "detect", lambda **_: [{"name": "generic", "found": True}])
    tid = _new(proj)
    ans = {
        "go": True,
        "agent": "generic",
        "model": "sonnet",
        "account": "Personal 1",
        "say": "On Personal 1.",
    }
    assert _valid("answer", ans) == []
    asker(ans)
    out, notes = startask.ask(proj, tid, "agent:automation", None, "other", False)
    assert out == {"agent": "generic", "model": "sonnet", "account": "Personal 1"}
    assert notes == ["On Personal 1."]


def test_a_persons_choice_is_never_changed(proj, asker):
    tid = _new(proj)

    def op(t):
        t["model"] = {"name": "opus", "by": "human:t"}

    tickets.apply_op(proj, tid, op, by="human:t")
    assert modelpick.by_person(tickets.load(proj, tid))
    asker({"go": True, "agent": "generic", "model": "haiku"})
    out, _ = startask.ask(proj, tid, "human:t", None, "other", True)  # --agent other given for this start
    assert out == {}
    req = json.loads((proj / "asked.json").read_text())
    assert req["chosen"] == {"agent": True, "model": True}


def test_unknown_tool_is_ignored_with_a_note(proj, asker):
    asker({"go": True, "agent": "not-here"})
    out, notes = startask.ask(proj, _new(proj), "agent:automation", None, "generic", False)
    assert out == {} and "not set up here" in notes[0]


@pytest.mark.parametrize("bad", ["crash", "not json", '{"go": "yes"}', "[1]"])
def test_no_or_bad_answer_starts_as_usual_with_one_note(proj, asker, bad):
    asker(bad)
    out, notes = startask.ask(proj, _new(proj), "agent:automation", None, "generic", False)
    assert out == {} and len(notes) == 1 and "starts as usual" in notes[0]


def test_slow_addon_starts_as_usual(proj, asker, monkeypatch):
    monkeypatch.setattr(startask, "TIMEOUT", 0.01)
    out, notes = startask.ask(proj, _new(proj), "agent:automation", None, "generic", False)
    assert out == {} and "starts as usual" in notes[0]


def test_wait_answer_raises_with_plain_words(proj, asker):
    ans = {"go": False, "why": "No room for Reviews until Mon 08:00.", "until": "2999-01-01T08:00:00Z"}
    assert _valid("answer", ans) == []
    asker(ans)
    with pytest.raises(startask.Wait) as e:
        startask.ask(proj, _new(proj), "agent:automation", None, "generic", False)
    assert e.value.why == "No room for Reviews until Mon 08:00." and e.value.until == "2999-01-01T08:00:00Z"


def test_hold_with_a_time_uses_the_time_wait_once(proj):
    tid = _new(proj)
    w = startask.Wait("hello", "No room for Reviews.", "2999-01-01T08:00:00Z")
    startask.hold(proj, tid, w)
    startask.hold(proj, tid, w)
    t = tickets.load(proj, tid)
    assert t["status"] == "waiting"
    assert t["waiting_on"] == {"kind": "time", "until": "2999-01-01T08:00:00Z", "ref": "No room for Reviews."}
    assert sum("Waiting: No room for Reviews." in h.get("text", str(h)) for h in t["history"]) == 1


def test_hold_without_a_time_is_external(proj):
    tid = _new(proj)
    startask.hold(proj, tid, startask.Wait("hello", "No room for Code.", None))
    assert tickets.load(proj, tid)["waiting_on"] == {"kind": "external", "ref": "No room for Code."}


pytestmark_wrap = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


@pytestmark_wrap
def test_automatic_start_waits_and_nothing_is_claimed(proj, gen, asker, monkeypatch):
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    gen("--silent 0.2")
    tid = _new(proj)
    asker({"go": False, "why": "No room for Helpers."})
    with pytest.raises(Refused, match="Not started: No room for Helpers."):
        runs.start(proj, tid, "agent:automation")
    assert runs.read(proj, tid) is None
    assert tickets.load(proj, tid)["status"] == "waiting"


@pytestmark_wrap
def test_a_persons_start_goes_ahead_with_the_reason_as_a_note(proj, gen, asker, monkeypatch):
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    gen("--silent 0.2")
    tid = _new(proj)
    asker({"go": False, "why": "No room for Helpers."})
    r = runs.start(proj, tid, "human:t")
    assert "Started anyway: No room for Helpers." in r["notes"]
    _wait(proj, tid)


@pytestmark_wrap
def test_a_helper_at_work_gets_the_message_and_no_addon_is_asked(proj, gen, asker, monkeypatch):
    """Only a real new start asks: a helper already holds the ticket, so no switch, hold or re-route."""
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    gen("--silent 0.2")
    tid = _new(proj)
    runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=os.getpid())  # a helper at work (this process)
    asker({"go": False, "why": "No room for Helpers."})
    with pytest.raises(runs.Busy):
        runs.start(proj, tid, "agent:automation", text="One more thing.")
    assert not (proj / "asked.json").exists()
    assert tickets.load(proj, tid)["status"] != "waiting"
    assert runs.read(proj, tid)["pending"] is True  # the message went to the helper at work


@pytestmark_wrap
def test_a_key_start_names_its_credit_and_may_only_be_refused(proj, gen, asker, monkeypatch):
    from orch import keystart

    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    gen("--silent 0.2")
    monkeypatch.setattr(
        keystart, "check", lambda root, name, credit: {"account": "OpenAI credit", "key": "oa", "why": ""}
    )
    tid = _new(proj)
    asker({"go": False, "why": "OpenAI credit has nothing left. Set what is left on the Usage page."})
    credit = {"account": "OpenAI credit", "key": "oa", "why": ""}
    with pytest.raises(Refused, match="Not started on OpenAI credit: OpenAI credit has nothing left"):
        runs.start(proj, tid, "human:t", credit=credit)  # a person too: a spent credit is never used
    req = json.loads((proj / "asked.json").read_text())
    assert _valid("request", req) == [] and req["credit"] == {"account": "OpenAI credit"}
    assert "oa" not in json.dumps(req["credit"])  # the label only, never the key's name
    assert runs.read(proj, tid) is None and tickets.load(proj, tid)["status"] != "waiting"


@pytestmark_wrap
def test_a_key_start_is_checked_for_its_credit_even_when_a_helper_looked_busy(proj, gen, asker, monkeypatch):
    """The helper may end between the busy look and the claim: the refusal-only credit check runs anyway."""
    from orch import keystart

    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    gen("--silent 0.2")
    monkeypatch.setattr(
        keystart, "check", lambda root, name, credit: {"account": "OpenAI credit", "key": "oa", "why": ""}
    )
    monkeypatch.setattr(runs, "_helper_at_work", lambda root, tid, take_over: True)  # looked busy
    tid = _new(proj)
    asker({"go": False, "why": "OpenAI credit has nothing left. Set what is left on the Usage page."})
    with pytest.raises(Refused, match="Not started on OpenAI credit"):
        runs.start(proj, tid, "human:t", credit={"account": "OpenAI credit", "key": "oa", "why": ""})
    assert runs.read(proj, tid) is None


def test_a_start_without_a_credit_does_not_name_one(proj, asker):
    startask.ask(proj, _new(proj), "agent:automation", None, "generic", False)
    assert "credit" not in json.loads((proj / "asked.json").read_text())
