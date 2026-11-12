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
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "leave-out", "target": path, "sign": True,
                                            "seen": "sync:leave-out:" + "a" * 64}) == [
        "sync", "act", "leave-out", *common(path)]  # `sign` and `seen` are the page's, never argv words
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "leave-out", "target": path, "review": True}) == [
        "sync", "act", "leave-out", *common(path)]  # a review only ever adds --proof-target (run_op)


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
        {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True},  # no `seen`
        {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True, "seen": 5},
        {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "seen": "sync:x"},  # unsigned
        {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "review": "yes"},
        {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "review": True, "sign": True,
         "seen": None},
    ],
)
def test_bad_sync_clicks_are_refused(args):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("addon.act", args)


@pytest.mark.parametrize(
    "target",
    [
        "tickets/t_abc123/artifacts/pay\u202etxt.exe",  # RIGHT-TO-LEFT OVERRIDE
        "https://files.example.org/\u202dmia",  # LEFT-TO-RIGHT OVERRIDE
        "https://files.example.org/\u2066mia\u2069",  # isolates
        "https://files.example.org/\u200fmia",  # RIGHT-TO-LEFT MARK
        "https://files.example.org/m\u200bia",  # ZERO WIDTH SPACE
        "https://files.example.org/m\u200dia",  # ZERO WIDTH JOINER
        "https://files.example.org/m\u2060ia",  # WORD JOINER
        "https://files.example.org/m\ufeffia",  # BOM / ZERO WIDTH NO-BREAK SPACE
        "https://files.example.org/m\x85ia",  # C1: NEXT LINE
        "https://files.example.org/m\x9bia",  # C1: CSI
        "https://files.example.org/m\x9fia",  # C1: APC
        "https://files.example.org/m\u061cia",  # ARABIC LETTER MARK
    ],
)
def test_bidi_c1_and_zero_width_targets_are_refused(target):
    """L1: such a character can disguise a path or an address in an error or a sign step."""
    with pytest.raises(actions.BadRequest):
        actions.build_argv("addon.act", {"addon": "sync", "verb": "check", "target": target})
    with pytest.raises(actions.BadRequest):
        actions.build_argv("addon.act", {"addon": "other", "verb": "refresh", "target": target})


def test_plain_unicode_targets_still_work():
    path = "tickets/t_abc123/artifacts/Prüfung März €.txt"
    assert actions.build_argv("addon.act", {"addon": "sync", "verb": "leave-out", "target": path})[-1] == path


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


REVIEW = {"title": "Keep the other computer’s version of “Close March books”?", "body": "The change made here is set aside.",
          "here": "due: 2026-03-31", "there": "note: bank fees"}


def test_a_signed_sync_click_mints_for_the_target_the_addon_names(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    target = "sync:keep-theirs:" + "a" * 64
    calls, run = _answer({"target": target, "review": REVIEW})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    seen = []
    monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **kw: seen.append((argv, proof)) or R())
    args = {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json"}
    # phase 1: what the person will sign; nothing runs, nothing is minted
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": {**args, "review": True}}, {"Cookie": ck})
    assert st == 200, body
    assert json.loads(body)["act_answer"] == {"addon": "sync", "answer": {"target": target, "review": REVIEW}}
    assert len(calls) == 1 and "--proof-target" in calls[0] and seen == []
    # phase 2: the signed click echoes the target the page showed
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": {**args, "sign": True, "seen": target}}, {"Cookie": ck})
    assert st == 200, body
    query = calls[1]
    assert query[query.index("act"):] == ["act", "keep-theirs", "--by", actions.actor(), "--json", "--proof-target",
                                          "--", "tickets/t_abc123.json"]
    assert len(seen) == 1 and "--proof-target" not in seen[0][0] and seen[0][0][:3] == ["sync", "act", "keep-theirs"]
    payload = json.loads(base64.urlsafe_b64decode(seen[0][1].split(".")[1] + "=="))
    assert (payload["op"], payload["target"]) == ("addon.act", target)
    assert hp.verify_and_consume(root, seen[0][1], "addon.act", target).startswith("human:")
    assert json.loads(body)["act_answer"] == {"addon": "sync", "answer": {"text": "Kept the other version."}}


@pytest.mark.parametrize("shown", ["sync:keep-theirs:" + "b" * 64, None, ""])
def test_review_vs_target_mismatch_mints_nothing(live, monkeypatch, shown):
    """The add-on now names another target than the one the page showed (the bytes changed after the dialog
    opened, or a page that skipped the review): refused, no proof exists, the verb never runs."""
    root, port = live
    ck = session(root, port)
    calls, run = _answer({"target": "sync:keep-theirs:" + "a" * 64, "review": REVIEW})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: pytest.fail("a proof was minted"))
    args = {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True, "seen": shown}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 400 and body.decode() == "This changed after you opened it. Nothing was changed; open it again."
    assert len(calls) == 1 and "--proof-target" in calls[0]


def test_a_review_is_plain_text_lines_only(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    reply = {"target": None, "review": {"title": "T", "value": "v" * 5000, "html": "<b>x</b>", "body": 5}}
    calls, run = _answer(reply)
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    args = {"addon": "sync", "verb": "keep-mine", "target": "tickets/t_abc123.json", "review": True}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 200
    assert json.loads(body)["act_answer"]["answer"] == {"target": None, "review": {"title": "T", "value": "v" * 4000}}
    _, run = _answer({"target": None})  # no review: nothing to sign
    monkeypatch.setattr(actions, "_run", run)
    assert post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})[0] == 400
    assert len(calls) == 1


@pytest.mark.parametrize("reply", [{"target": "other:keep-theirs:x"}, {"target": "sync:has space"}, {"target": 5},
                                   {"error": "This file is not waiting for a choice"}, ["sync:x"]])
def test_a_target_outside_the_addons_own_name_is_never_minted(live, monkeypatch, reply):
    root, port = live
    ck = session(root, port)
    _, run = _answer(reply)
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: pytest.fail("a proof was minted"))
    seen = reply.get("target") if isinstance(reply, dict) and isinstance(reply.get("target"), str) else None
    args = {"addon": "sync", "verb": "keep-theirs", "target": "tickets/t_abc123.json", "sign": True, "seen": seen}
    st, _, body = post(port, "/api/act", {"op": "addon.act", "args": args}, {"Cookie": ck})
    assert st == 400
    st, _, _ = post(port, "/api/act", {"op": "addon.act", "args": {**{k: v for k, v in args.items() if k not in ("sign", "seen")},
                                                                  "review": True}}, {"Cookie": ck})
    assert st == 400  # never shown for signing either
    if isinstance(reply, dict) and "error" in reply:
        assert body.decode() == "This file is not waiting for a choice"


def test_a_signed_click_that_needs_no_proof_runs_plainly(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    calls, run = _answer({"target": None})
    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: True)
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: pytest.fail("no proof is needed"))
    args = {"addon": "sync", "verb": "keep-mine", "target": "tickets/t_abc123.json", "sign": True, "seen": None}
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
                 {"addon": "sync", "verb": "leave-out", "target": "tickets/t_abc123/artifacts/a.txt", "sign": True,
                  "seen": "sync:leave-out:" + "a" * 64},
                 {"addon": "sync", "verb": "leave-out", "target": "tickets/t_abc123/artifacts/a.txt", "review": True}):
        assert post(port, "/api/act", {"op": "addon.act", "args": args})[0] == 403
