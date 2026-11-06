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


def starts(fake):
    return [c for c in calls(fake) if c[:2] == ["run", "start"]]


def sync(p, claim=CLAIM, ticket=None, running=False, last=RUN, denials=()):
    return p.sync(TID, claim, running, last, list(denials), ticket or {"questions": []}, "Claude")


def test_denial_becomes_one_question_with_two_options(ws, fake_orch):
    p = mk(ws, fake_orch)
    assert sync(p, denials=DENIAL) is False
    [ask] = asked(fake_orch)
    assert ask[:3] == ["ask", TID, "Claude needs your OK to use WebFetch. Allow it and try again?"]
    assert ask[ask.index("--kind") + 1] == KIND
    assert [ask[i + 1] for i, a in enumerate(ask) if a == "--option"] == [ALLOW, NOT_NOW]
    assert json.loads(ask[ask.index("--action") + 1]) == {"tool": "WebFetch", "run": RUN}
    assert ask[ask.index("--by") + 1] == "agent:focus"
    sync(p, denials=DENIAL)  # the same denial is not asked twice
    assert len(asked(fake_orch)) == 1
    sync(mk(ws, fake_orch), denials=DENIAL)  # nor after a restart
    assert len(asked(fake_orch)) == 1


@pytest.mark.parametrize(
    "claim",
    [{**CLAIM, "mode": "live"}, {**CLAIM, "agent": "codex"}, {**CLAIM, "agent": "generic"}, {**CLAIM, "agent": "no such"}, {**CLAIM, "run": "../x"}],
)  # fmt: skip
def test_no_question_for_live_runs_or_agents_without_permission_retry(ws, fake_orch, claim):
    sync(mk(ws, fake_orch), claim=claim, denials=DENIAL)
    assert asked(fake_orch) == []


def answered(answer, tool="WebFetch", kind=KIND, qid="q7", run=RUN):
    return {"questions": [{"id": qid, "kind": kind, "answer": answer, "action": {"tool": tool, "run": run}}]}


def asked_by_focus(ws, fake):
    p = mk(ws, fake)
    sync(p, denials=DENIAL)  # Focus asks: stored as q7 for RUN and WebFetch
    return p


def test_allow_and_retry_starts_the_run_again_with_that_tool_once(ws, fake_orch):
    p = asked_by_focus(ws, fake_orch)
    # the run is over (no claim running); the latest run is still the one that was refused
    assert sync(p, claim={}, ticket=answered(ALLOW)) is True
    assert starts(fake_orch) == [["run", "start", TID, "--allow=WebFetch", "--by", "focus", "--json"]]
    assert sync(p, claim={}, ticket=answered(ALLOW)) is False
    assert sync(mk(ws, fake_orch), claim={}, ticket=answered(ALLOW)) is False
    assert len(starts(fake_orch)) == 1


def test_an_agent_made_up_question_does_nothing(ws, fake_orch):
    p = mk(ws, fake_orch)  # Focus never asked q9
    assert sync(p, claim={}, ticket=answered(ALLOW, qid="q9", tool="Bash")) is False
    assert starts(fake_orch) == []


def test_an_old_answer_does_nothing_after_the_state_is_gone_or_a_newer_run(ws, fake_orch):
    p = asked_by_focus(ws, fake_orch)
    (ws / ".orch" / "run" / "focus" / "permissions.json").unlink()
    assert sync(mk(ws, fake_orch), claim={}, ticket=answered(ALLOW)) is False  # lost state file: nothing
    p = asked_by_focus(ws, fake_orch)
    assert sync(p, claim={}, ticket=answered(ALLOW), last="r_newer001") is False  # a newer run exists
    assert starts(fake_orch) == []


def test_ask_text_says_one_tool_and_the_action_another_only_the_stored_tool_counts(ws, fake_orch):
    p = asked_by_focus(ws, fake_orch)
    assert sync(p, claim={}, ticket=answered(ALLOW, tool="Bash")) is True  # action says Bash: ignored
    assert starts(fake_orch) == [["run", "start", TID, "--allow=WebFetch", "--by", "focus", "--json"]]


def test_nothing_starts_while_the_run_still_runs(ws, fake_orch):
    p = asked_by_focus(ws, fake_orch)
    assert sync(p, claim=CLAIM, running=True, ticket=answered(ALLOW)) is False
    assert starts(fake_orch) == []


@pytest.mark.parametrize(
    "ticket",
    [
        answered(NOT_NOW),
        answered("allow and retry please"),
        answered(ALLOW, kind=None),
        answered(ALLOW, kind="focus:other"),
        answered(None),
    ],
)
def test_nothing_starts_unless_the_exact_answer(ws, fake_orch, ticket):
    p = asked_by_focus(ws, fake_orch)
    sync(p, claim={}, ticket=ticket)
    assert starts(fake_orch) == []


def test_allow_never_comes_from_the_page(ws, fake_orch):
    from orch_focus import actions

    with pytest.raises(actions.BadRequest):
        actions.build_argv("run.start", {"ticket": TID, "allow": ["Bash"]})


def test_state_file_is_in_a_plain_folder(ws, fake_orch, tmp_path):
    (ws / ".orch" / "run").symlink_to(tmp_path)
    p = mk(ws, fake_orch)  # a symlinked run folder: nothing is remembered, nothing is written there
    sync(p, denials=DENIAL)
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
