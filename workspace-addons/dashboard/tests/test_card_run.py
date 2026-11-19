"""Run it now on a run card (ORCH-848): the dashboard's card.run op. Only the signed-in page session, with the
one-time person grant in a pipe; the page sees what it printed whether it worked or not."""

import json

import pytest

from orch_dashboard import actions

TID = "t_abcdef"
DIGEST = "a" * 64


@pytest.fixture
def ws(ws, tmp_path, monkeypatch):
    """The workspace where a guarded orch home pairs with it (the person grant is kept there)."""
    import shutil
    from pathlib import Path

    from orch import addons

    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    return Path(shutil.copytree(ws, acct / ".orch-test" / ws.name))


def test_one_fixed_argv():
    argv = actions.build_argv("card.run", {"ticket": TID, "key": "q2", "digest": DIGEST})
    assert argv[:4] == ["review", "run", TID, "q2"]
    assert argv[argv.index("--digest") + 1] == DIGEST and "--confirmed" not in argv
    assert argv[argv.index("--via") + 1] == "dashboard"
    argv = actions.build_argv("card.run", {"ticket": TID, "key": "q2", "digest": DIGEST, "confirmed": True})
    assert "--confirmed" in argv
    argv = actions.build_argv("card.run", {"ticket": TID, "key": "q2", "digest": DIGEST, "confirmed": "yes"})
    assert "--confirmed" not in argv  # only a real true confirms


@pytest.mark.parametrize(
    "args",
    [
        {"ticket": TID, "key": "review", "digest": DIGEST},
        {"ticket": TID, "key": "q1;rm", "digest": DIGEST},
        {"ticket": TID, "key": "q1", "digest": "short"},
        {"ticket": "../x", "key": "q1", "digest": DIGEST},
        {"ticket": TID, "key": "q1", "digest": DIGEST, "command": "rm -rf ~"},
        {"ticket": TID, "key": "q1"},
    ],
)
def test_bad_args_are_refused(args):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("card.run", args)


class _R:
    def __init__(self, code, out):
        self.returncode, self.stdout, self.stderr = code, json.dumps(out), ""


def test_needs_the_session_and_hands_the_grant_in_a_pipe(ws, monkeypatch):
    from orch import renew
    from orch.pagesession import SELF

    seen = {}
    ran = {"ok": True, "exit": 0, "output": "workflow.reviewer_look = on", "answered": True}
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: seen.update(argv=argv, kw=kw) or _R(0, ran))
    args = {"ticket": TID, "key": "q1", "digest": DIGEST}
    with pytest.raises(actions.NeedsPerson):  # watch-only: nothing runs
        actions.run_op(ws, SELF, "card.run", args)
    assert seen == {}
    code, _, out = actions.run_op(ws, SELF, "card.run", args, session=True)
    assert code == 200 and out == ran
    assert seen["kw"]["env"].get(renew.GRANT_ENV + "_FD") and seen["kw"]["pass_fds"]
    assert renew.GRANT_ENV not in seen["kw"]["env"]
    assert seen["kw"]["timeout"] >= 120


def test_a_failed_run_comes_back_with_its_output(ws, monkeypatch):
    from orch.pagesession import SELF

    failed = {"ok": False, "exit": 1, "output": "orch: refused", "error": "It ended with exit code 1.",
              "answered": False}  # fmt: skip
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: _R(1, failed))
    code, _, out = actions.run_op(ws, SELF, "card.run", {"ticket": TID, "key": "q1", "digest": DIGEST},
                                  session=True)  # fmt: skip
    assert code == 200 and out == failed


def test_a_refusal_is_a_plain_error(ws, monkeypatch):
    from orch.pagesession import SELF

    class R:
        returncode, stdout, stderr = 2, "", "Refused: The card changed after you saw it.\n"

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: R())
    code, text, _ = actions.run_op(ws, SELF, "card.run", {"ticket": TID, "key": "q1", "digest": DIGEST},
                                   session=True)  # fmt: skip
    assert code == 422 and "changed after you saw it" in text
