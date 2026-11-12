"""Sync card and sync Needs rows on the server side: everything goes through the ONE generic op `addon.act`
(`orch <addon> act <verb> -- <target>`); a signed click mints a proof for exactly the target the add-on names."""

import base64
import json
import subprocess

import pytest

pytest.importorskip("orch")
from orch import humanproof as hp

from orch_dashboard import actions
from tests.test_proof_session import live, post, session

__all__ = ["live"]


def common(target):
    return ["--by", actions.actor(), "--json", "--", target]


def test_sync_verbs_map_to_one_generic_argv():
    url = "https://files.example.org/mia/month-end"
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "status", "target": "sync"}) == [
        "sync", "act", "status", *common("sync")]
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "set", "target": url, "value": "15"}) == [
        "sync", "act", "set", "--value=15", *common(url)]
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "check", "target": "git@host:me/orch"})[-1] == "git@host:me/orch"
    path = "tickets/t_abc123/artifacts/payroll access.txt"
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "leave-out", "target": path, "sign": True}) == [
        "sync", "act", "leave-out", *common(path)]  # `sign` is the page's, never an argv word


@pytest.mark.parametrize(
    "args",
    [
        {"addon": "sync", "verb": "check", "target": "--upload-pack=x"},
        {"addon": "sync", "verb": "check", "target": "https://a\nb"},
        {"addon": "sync", "verb": "check", "target": " https://a"},
        {"addon": "sync", "verb": "check", "target": "x" * 501},
        {"addon": "sync", "verb": "check", "target": ""},
        {"addon": "sync", "verb": "set", "target": "local", "value": "15 min"},
        {"addon": "sync", "verb": "set", "target": "local", "value": 15},
        {"addon": "sync", "verb": "now", "target": "sync", "value": "5"},
        {"addon": "sync", "verb": "now", "target": "sync", "sign": "yes"},
    ],
)
def test_bad_sync_clicks_are_refused(args):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("addon.act", args)


def _answer(target_reply):
    """A fake `orch`: the proof-target query answers `target_reply`; every other call is recorded."""
    calls = []

    def run(argv, *a, **k):
        calls.append(argv)
        if "--proof-target" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(target_reply), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps({"text": "Done."}), "")

    return calls, run


class R:
    returncode, stdout, stderr = 0, '{"text": "Kept the other version."}', ""


def test_a_signed_sync_click_mints_for_the_target_the_addon_names(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    target = "sync:keep-theirs:" + "a" * 64
    calls, run = _answer({"target": target})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    seen = []
    monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **kw: seen.append((argv, proof)) or R())
    args = {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 200, body
    query = calls[0]
    assert query[query.index("act"):] == ["act", "keep-theirs", "--by", actions.actor(), "--json", "--proof-target",
                                          "--", "tickets/t_abc123.json"]
    assert len(seen) == 1 and "--proof-target" not in seen[0][0] and seen[0][0][:3] == ["sync", "act", "keep-theirs"]
    payload = json.loads(base64.urlsafe_b64decode(seen[0][1].split(".")[1] + "=="))
    assert (payload["op"], payload["target"]) == ("addon.act", target)
    assert hp.verify_and_consume(root, seen[0][1], "addon.act", target).startswith("human:")
    assert json.loads(body)["act_answer"] == {"addon": "sync", "answer": {"text": "Kept the other version."}}


@pytest.mark.parametrize("reply", [{"target": "other:keep-theirs:x"}, {"target": "sync:has space"}, {"target": 5},
                                   {"error": "This file is not waiting for a choice"}, ["sync:x"]])
def test_a_target_outside_the_addons_own_name_is_never_minted(live, monkeypatch, reply):
    root, port = live
    ck = session(root, port)
    _, run = _answer(reply)
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: pytest.fail("a proof was minted"))
    args = {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 400
    if isinstance(reply, dict) and "error" in reply:
        assert body.decode() == "This file is not waiting for a choice"


def test_a_signed_click_that_needs_no_proof_runs_plainly(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    calls, run = _answer({"target": None})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: pytest.fail("no proof is needed"))
    args = {"addon": "sync", "verb": "keep-mine", "target": "tickets/t_abc123.json", "sign": True}
    assert post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})[0] == 200
    assert [c[c.index("act") + 1] for c in calls] == ["keep-mine", "keep-mine"] and "--proof-target" not in calls[1]


def test_an_unsigned_sync_click_never_asks_for_a_target(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    calls, run = _answer({"target": "sync:x"})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    args = {"addon": "sync", "verb": "status", "target": "sync"}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 200 and len(calls) == 1 and "--proof-target" not in calls[0]
    assert json.loads(body)["act_answer"]["answer"] == {"text": "Done."}


def test_sync_clicks_are_watch_only_without_a_session(live, monkeypatch):
    _root, port = live
    monkeypatch.setattr(actions, "_run", lambda *a, **k: pytest.fail("ran without a session"))
    for args in ({"addon": "sync", "verb": "set", "target": "local"},
                 {"addon": "sync", "verb": "leave-out", "target": "tickets/t_abc123/artifacts/a.txt", "sign": True}):
        assert post(port, "/api/act", {"op": "addon.act", "args": args})[0] == 403
