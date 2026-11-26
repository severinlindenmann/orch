"""ORCH-2170 (RP2): the Publish page's paste box. The admin's whole text goes on stdin to the same
`orch publish connect --paste` the terminal uses; the token is never in the argv or the answer."""

import json
import subprocess

import pytest

from orch_dashboard import actions

TOKEN = "orp_" + "s" * 30
TEXT = f"Hi! Connect this workspace:\n  orch publish connect https://pub.example --workspace ws_abcdefghij --token {TOKEN}\n"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, kw=kw)
        return seen.get("answer") or subprocess.CompletedProcess(
            argv, 0, json.dumps({"name": "Marketing", "token": TOKEN}), ""
        )

    monkeypatch.setattr(actions, "_run", run)
    monkeypatch.setattr(actions, "_addon_is_on", lambda root, orch_bin, name: name == "publish")
    monkeypatch.setattr(actions, "human_env", lambda root, orch_bin: {})
    return seen


def test_the_text_goes_on_stdin_to_publish_connect_paste(tmp_path, fake):
    code, text, out = actions.run_op(tmp_path, "orch", "link.connect", {"text": TEXT}, session=True)
    assert (code, text, out) == (200, "", {"name": "Marketing"})  # the name only, never the token
    i = fake["argv"].index("publish")
    assert fake["argv"][i : i + 3] == ["publish", "connect", "--paste"] and "--json" in fake["argv"]
    assert TOKEN not in json.dumps(fake["argv"]) and fake["kw"]["input"] == TEXT


def test_watch_only_runs_nothing(tmp_path, fake):
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(tmp_path, "orch", "link.connect", {"text": TEXT})
    assert fake == {}


@pytest.mark.parametrize(
    "args",
    [{}, {"text": "  "}, {"text": 5}, {"text": "x" * 9000}, {"text": "a\x00b"}, {"text": TEXT, "x": 1}],
)
def test_bad_text_is_refused_before_anything_runs(tmp_path, fake, args):
    with pytest.raises(actions.BadRequest):
        actions.run_op(tmp_path, "orch", "link.connect", args, session=True)
    assert fake == {}


def test_publish_off_is_refused(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(actions, "_addon_is_on", lambda *a: False)
    with pytest.raises(actions.BadRequest):
        actions.run_op(tmp_path, "orch", "link.connect", {"text": TEXT}, session=True)
    assert fake == {}


def test_a_refusal_says_what_to_do_and_never_echoes_the_text(tmp_path, fake):
    err = (
        "The connect line in that text is cut off. Ask your admin to send the text again and paste all of it."
    )
    fake["answer"] = subprocess.CompletedProcess([], 2, json.dumps({"error": err}), "")
    code, text, out = actions.run_op(tmp_path, "orch", "link.connect", {"text": TEXT}, session=True)
    assert (code, out) == (422, None) and text == err and TOKEN not in text
