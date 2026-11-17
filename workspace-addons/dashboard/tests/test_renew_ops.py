"""Renew from the warning (ORCH-46): the dashboard's login ops. A pasted code and a new key go on stdin only."""

import json

import pytest

from orch_dashboard import actions, server


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


def test_renew_status_cancel_build_one_fixed_argv():
    assert actions.build_argv("logins.renew", {"name": "claude"})[:3] == ["logins", "renew", "claude"]
    assert actions.build_argv("logins.status", {"name": "claude"})[:4] == [
        "logins",
        "renew",
        "claude",
        "--status",
    ]
    assert actions.build_argv("logins.cancel", {"name": "claude"})[:4] == [
        "logins",
        "renew",
        "claude",
        "--cancel",
    ]
    for bad in ({"name": "../x"}, {"name": "--code"}, {"name": 5}, {}, {"name": "claude", "value": "x"}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("logins.renew", bad)


class _R:
    returncode, stdout, stderr = 0, json.dumps({"name": "claude", "state": "checking"}), ""


@pytest.mark.parametrize(
    ("op", "words"),
    [
        ("logins.code", ["logins", "renew", "claude", "--code", "-"]),
        ("logins.replace", ["logins", "replace", "claude"]),
    ],
)
def test_code_and_key_go_on_stdin_only(ws, monkeypatch, op, words):
    from orch.pagesession import SELF

    seen = {}
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: seen.update(argv=argv, kw=kw) or _R())
    secret = "value-that-must-not-be-in-argv-123"
    with pytest.raises(actions.NeedsPerson):  # watch-only: nothing runs
        actions.run_op(ws, SELF, op, {"name": "claude", "value": secret})
    assert seen == {}
    code, _, out = actions.run_op(ws, SELF, op, {"name": "claude", "value": secret}, session=True)
    assert code == 200 and out == {"name": "claude", "state": "checking"}
    i = seen["argv"].index("logins")
    assert seen["argv"][i : i + len(words)] == words
    assert secret not in json.dumps(seen["argv"]) and seen["kw"]["input"] == secret
    from orch import renew

    assert seen["kw"]["env"].get(renew.GRANT_ENV + "_FD")  # a one-time person grant goes with the call ...
    assert renew.GRANT_ENV not in seen["kw"]["env"] and seen["kw"]["pass_fds"]  # ... in a pipe, not the env


@pytest.mark.parametrize(
    "args", [{"name": "claude"}, {"name": "claude", "value": "  "}, {"name": "x y", "value": "abc"}]
)
def test_code_without_a_value_is_refused(ws, monkeypatch, args):
    from orch.pagesession import SELF

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: pytest.fail("ran"))
    with pytest.raises(actions.BadRequest):
        actions.run_op(ws, SELF, "logins.code", args, session=True)


def test_a_refusal_never_echoes_the_value(ws, monkeypatch):
    from orch.pagesession import SELF

    class R:
        returncode, stdout, stderr = 2, json.dumps({"error": "The sign-in is no longer waiting."}), ""

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: R())
    code, text, out = actions.run_op(
        ws, SELF, "logins.code", {"name": "claude", "value": "abc-123"}, session=True
    )
    assert (code, out) == (422, None) and "abc-123" not in text and "no longer waiting" in text


def test_the_answer_the_page_reads_holds_a_few_facts():
    got = server._renew_answer(
        {
            "name": "claude",
            "state": "link",
            "link": "https://claude.com/x",
            "other": "secret",
            "went_on": ["A-1"],
        }
    )
    assert got == {"state": "link", "link": "https://claude.com/x", "name": "claude", "went_on": ["A-1"]}
    assert server._renew_answer({"state": "weird", "link": "javascript:alert(1)"}) == {
        "state": "failed",
        "went_on": [],
    }
    assert server._renew_answer(None) is None


def test_every_script_the_page_loads_is_served(server):
    """A page file missing from the server's list loads as a 404 and its functions are missing (renew.js)."""
    import re
    import urllib.request

    index = urllib.request.urlopen(server + "/").read().decode()
    srcs = [s for s in re.findall(r'<script src="([^"]+)"', index) if not s.startswith(("http", "kit/"))]
    assert "pages/renew.js" in srcs
    for src in srcs:
        with urllib.request.urlopen(f"{server}/{src}") as r:
            assert r.status == 200, src


def test_a_key_is_never_in_the_audit_or_the_request_log(ws, monkeypatch, capsys):
    """R5.2: logins.replace writes no audit entry; the server's request line names the op only."""
    from orch.pagesession import SELF

    monkeypatch.setattr(actions, "_audit", lambda *a, **k: pytest.fail("audited"))
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: _R())
    secret = "replaced-key-VALUE-7f3a9c"
    actions.run_op(ws, SELF, "logins.replace", {"name": "payments", "value": secret}, session=True)
    cap = capsys.readouterr()
    assert secret not in cap.out + cap.err


def test_the_status_poll_carries_a_grant_and_only_with_a_session(ws, monkeypatch):
    from orch import renew
    from orch.pagesession import SELF

    seen = {}
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: seen.update(env=kw["env"]) or _R())
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, SELF, "logins.status", {"name": "claude"})
    assert seen == {}
    actions.run_op(ws, SELF, "logins.status", {"name": "claude"}, session=True)
    assert seen["env"].get(renew.GRANT_ENV + "_FD") and renew.GRANT_ENV not in seen["env"]
    n = len(list(renew._grants(ws).iterdir()))
    actions.run_op(ws, SELF, "logins.status", {"name": "claude"}, session=True)
    assert len(list(renew._grants(ws).iterdir())) == n  # a poll leaves no grant file behind
    actions.run_op(ws, SELF, "logins.check", {}, session=True)
    assert renew.GRANT_ENV + "_FD" not in seen["env"]  # a plain check needs no grant
