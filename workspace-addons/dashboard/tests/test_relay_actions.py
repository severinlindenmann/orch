import subprocess

import pytest

from orch_dashboard import actions

MID = "m_0123456789abcdef"
CASES = [
    (
        "relay.reply",
        {"to": "My.phone-1", "message": MID, "text": "--hello"},
        ["relay", "send", "My.phone-1", "--reply-to", MID],
        "text",
    ),
    ("relay.topic", {"message": MID, "title": "--hello"}, ["relay", "topic", "--from", MID], "title"),
]


@pytest.mark.parametrize("op,args,words,field", CASES)
def test_relay_argv(op, args, words, field):
    assert actions.build_argv(op, args) == [*words, "--by", actions.actor(), "--json", "--", args[field]]
    assert actions.build_argv(op, {**args, field: "x" * 2000})[-1] == "x" * 2000


@pytest.mark.parametrize("op,args,words,field", CASES)
def test_relay_rejects_bad_args(op, args, words, field):
    bad = [
        {**args, "message": v}
        for v in (
            None,
            1,
            "",
            "../message",
            "--help",
            "m_abc",
            "m_0123456789abcdeF",
            MID + "0",
            MID + "\n",
        )
    ]
    bad += [{**args, field: v} for v in (None, "", "  ", "x" * 2001, "x\x00")]
    bad += [{**args, "extra": True}]
    bad += [{k: v for k, v in args.items() if k != missing} for missing in args]
    if op == "relay.reply":
        bad += [{**args, "to": v} for v in (None, "--file", "a b", "a" * 65, "a/b")]
    for invalid in bad:
        with pytest.raises(actions.BadRequest):
            actions.build_argv(op, invalid)


@pytest.mark.parametrize("op,args,words,field", CASES)
@pytest.mark.parametrize(
    "rows",
    [
        None,
        {},
        [],
        [{"name": "relay", "active": False}],
        [{"name": "relay", "active": "true"}],
        [{"name": "other", "active": True}],
    ],
)
def test_relay_requires_active_addon(ws, monkeypatch, op, args, words, field, rows):
    monkeypatch.setattr(actions, "run_orch", lambda *a: rows)
    monkeypatch.setattr(actions.subprocess, "run", lambda *a, **kw: pytest.fail("ran action"))
    with pytest.raises(actions.BadRequest, match="not on"):
        actions.run_op(ws, "orch", op, args)


@pytest.mark.parametrize("op,args,words,field", CASES)
def test_relay_runs_argv_when_on(ws, monkeypatch, op, args, words, field):
    def read(binary, argv, root):
        assert (binary, argv, root) == ("orch", ["addon", "list", "--json"], ws)
        return [{"name": "relay", "active": True}]

    def run(argv, **kwargs):
        assert argv == ["orch", *words, "--by", actions.actor(), "--json", "--", args[field]]
        assert not kwargs.get("shell")
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(actions, "run_orch", read)
    monkeypatch.setattr(actions, "human_env", lambda *a: {})
    monkeypatch.setattr(actions.subprocess, "run", run)
    assert actions.run_op(ws, "orch", op, args) == (200, "", {})
