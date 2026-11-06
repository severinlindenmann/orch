import json

import pytest

from orch_focus import adapterdata, chat
from orch_focus.permissions import ALLOW, KIND, NOT_NOW, Permissions

from .conftest import TID, calls

RUN = "r_abcd1234"
CLAIM = {"run": RUN, "agent": "claude", "mode": "oneshot", "by": "focus"}
DENIAL = [{"tool": "WebFetch", "text": "Needs your OK to use WebFetch", "at": "2026-11-06T08:00:00Z"}]


def mk(ws, fake):
    return Permissions(ws, str(fake))


def asked(fake):
    return [c for c in calls(fake) if c[0] == "ask"]


def test_denial_becomes_one_question_with_two_options(ws, fake_orch):
    p = mk(ws, fake_orch)
    assert p.sync(TID, CLAIM, DENIAL, {"questions": []}, "Claude") is False
    [ask] = asked(fake_orch)
    assert ask[:3] == ["ask", TID, "Claude needs your OK to use WebFetch. Allow it and try again?"]
    assert ask[ask.index("--kind") + 1] == KIND
    assert [ask[i + 1] for i, a in enumerate(ask) if a == "--option"] == [ALLOW, NOT_NOW]
    assert json.loads(ask[ask.index("--action") + 1]) == {"tool": "WebFetch", "run": RUN}
    assert ask[ask.index("--by") + 1] == "agent:focus"
    p.sync(TID, CLAIM, DENIAL, {"questions": []}, "Claude")  # the same denial is not asked twice
    assert len(asked(fake_orch)) == 1
    mk(ws, fake_orch).sync(TID, CLAIM, DENIAL, {"questions": []}, "Claude")  # nor after a restart
    assert len(asked(fake_orch)) == 1


@pytest.mark.parametrize(
    "claim",
    [{**CLAIM, "mode": "live"}, {**CLAIM, "agent": "codex"}, {**CLAIM, "agent": "generic"}, {**CLAIM, "agent": "no such"}, {**CLAIM, "run": "../x"}],
)  # fmt: skip
def test_no_question_for_live_runs_or_agents_without_permission_retry(ws, fake_orch, claim):
    mk(ws, fake_orch).sync(TID, claim, DENIAL, {"questions": []}, "Agent")
    assert asked(fake_orch) == []


def answered(answer, tool="WebFetch", kind=KIND, qid="q4"):
    return {"questions": [{"id": qid, "kind": kind, "answer": answer, "action": {"tool": tool, "run": RUN}}]}


def test_allow_and_retry_starts_the_run_again_with_that_tool_once(ws, fake_orch):
    p = mk(ws, fake_orch)
    assert p.sync(TID, CLAIM, [], answered(ALLOW), "Claude") is True
    [start] = [c for c in calls(fake_orch) if c[:2] == ["run", "start"]]
    assert start == ["run", "start", TID, "--allow=WebFetch", "--by", "focus", "--json"]
    assert p.sync(TID, CLAIM, [], answered(ALLOW), "Claude") is False
    assert mk(ws, fake_orch).sync(TID, CLAIM, [], answered(ALLOW), "Claude") is False
    assert len([c for c in calls(fake_orch) if c[:2] == ["run", "start"]]) == 1


@pytest.mark.parametrize(
    "ticket",
    [answered(NOT_NOW), answered("allow and retry please"), answered(ALLOW, tool="WebFetch; rm -rf /"), answered(ALLOW, tool="a b"),
     answered(ALLOW, tool=""), answered(ALLOW, kind=None), answered(ALLOW, kind="focus:other"), answered(None)],
)  # fmt: skip
def test_nothing_starts_unless_the_exact_answer_and_a_plain_tool_name(ws, fake_orch, ticket):
    mk(ws, fake_orch).sync(TID, CLAIM, [], ticket, "Claude")
    assert [c for c in calls(fake_orch) if c[:2] == ["run", "start"]] == []


def test_allow_never_comes_from_the_page(ws, fake_orch):
    from orch_focus import actions

    with pytest.raises(actions.BadRequest):
        actions.build_argv("run.start", {"ticket": TID, "allow": ["Bash"]})


def test_state_file_is_in_a_plain_folder(ws, fake_orch, tmp_path):
    (ws / ".orch" / "run").symlink_to(tmp_path)
    p = mk(ws, fake_orch)  # a symlinked run folder: nothing is remembered, nothing is written there
    p.sync(TID, CLAIM, DENIAL, {"questions": []}, "Claude")
    assert list(tmp_path.glob("**/permissions.json")) == []


def test_adapter_data_picks_the_mapper(ws, tmp_path):
    assert adapterdata.events_kind(ws, "claude", "live") == "claude-transcript/1"
    assert adapterdata.events_kind(ws, "claude", "oneshot") == "claude-stream-json/1"
    assert adapterdata.events_kind(ws, "codex", "oneshot") is None
    assert adapterdata.events_kind(ws, "generic", "live") is None
    assert adapterdata.events_kind(ws, "../x", "live") is None
    (ws / ".orch" / "config.toml").write_text('[agents.mine]\nadapter = "claude"\n')
    assert adapterdata.events_kind(ws, "mine", "live") == "claude-transcript/1"
    assert adapterdata.permission_retry(ws, "mine") and not adapterdata.permission_retry(ws, "codex")


def test_chat_notes():
    assert chat.note({"delivered": 1}, True, True) == "Sent."
    assert chat.note({"delivered": 0}, True, True) == "Goes in after this step."
    assert chat.note({"delivered": 0}, False, False) == "Saved for the next run."
    assert chat.note(None, False, False) == "Saved for the next run."
