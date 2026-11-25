"""Record a call (ORCH-1104): the dashboard's recorder writes a call down piece by piece through op meet_record. The
person's own "everyone agreed" makes the meeting; each piece's words land once and in order; Record is offered only
while the relay is on; a helper can never record."""

import json

import pytest
from conftest import as_helper
from test_server import call, server  # noqa: F401

START = {
    "rec": "browser-20261125-111500-ab12cd",
    "started": "2026-11-25T11:15:00+01:00",
    "consent_at": "2026-11-25T11:14:50+01:00",
}


def act(port, **args):
    code, body = call(port, "POST", "/api/act", {"op": "meet_record", "args": args})
    return code, json.loads(body)


def meetings(port):
    return json.loads(call(port, "GET", "/api/meetings")[1])


def meeting(port, mid):
    return json.loads(call(port, "GET", f"/api/meeting?id={mid}")[1])


@pytest.fixture
def on(server):  # noqa: F811
    assert call(server, "POST", "/api/act", {"op": "add", "args": {"part": "meetings"}})[0] == 200
    return server


def test_a_recording_lands_on_a_meeting_with_the_persons_consent(on):
    code, got = act(on, **START, meeting_audio=True)
    assert code == 200, got
    mid = got["result"]["id"]
    row = meetings(on)["meetings"][0]
    assert row["id"] == mid and row["recording"] == "recording" and row["title"] == "Call at 11:15"
    assert row["source"] == "Recorded in the browser" and row["mic_only"] is False
    # piece 2 arrives before piece 1 (a retry), piece 1 twice: each lands once, in order
    assert (
        act(on, rec=START["rec"], n=2, k=0, at="11:17", text="Dann schicke ich die Offerte.", secs=100)[0]
        == 200
    )
    assert (
        act(on, rec=START["rec"], n=1, k=0, at="11:15", text="Wir starten mit Phase 1.", secs=100)[0] == 200
    )
    assert (
        act(on, rec=START["rec"], n=1, k=0, at="11:15", text="Wir starten mit Phase 1.", secs=100)[0] == 200
    )
    assert act(on, rec=START["rec"], n=3, k=0, at="11:18", text="", secs=40)[0] == 200  # nothing heard
    code, _ = act(on, rec=START["rec"], done=True, minutes=4, missing=0)
    assert code == 200
    m = meeting(on, mid)
    assert [x["text"] for x in m["transcript"]] == [
        "Wir starten mit Phase 1.",
        "Dann schicke ich die Offerte.",
    ]
    assert m["recording"] == "done" and m["minutes"] == 4
    assert m["consent"]["by"].startswith("human:") and m["consent"]["at"] == START["consent_at"]
    assert m["consent"]["words"] == "Everyone on the call agreed before the recording started."


def test_only_the_microphone_and_missing_parts_are_said(on):
    mid = act(on, **START, meeting_audio=False)[1]["result"]["id"]
    act(on, rec=START["rec"], done=True, minutes=1, missing=2)
    m = meeting(on, mid)
    assert m["mic_only"] is True and m["missing"] == 2


def test_a_piece_for_a_deleted_or_unknown_recording_is_refused(on):
    code, got = act(on, rec="browser-nope", n=1, k=0, at="11:15", text="Hallo", secs=10)
    assert code == 409 and "Start it again from Meetings" in got["error"]
    mid = act(on, **START)[1]["result"]["id"]
    assert call(on, "POST", "/api/act", {"op": "meet_delete", "args": {"id": mid}})[0] == 200
    code, got = act(on, rec=START["rec"], n=1, k=0, at="11:15", text="Hallo", secs=10)
    assert code == 409 and "deleted" in got["error"]


def test_bad_values_are_refused(on):
    assert act(on, rec="../x", started="2026-11-25T11:15:00+01:00")[0] == 409
    assert act(on, rec=START["rec"], n=0, k=0, text="x")[0] == 409
    assert act(on, rec=START["rec"], n=1, k=0, text="x" * 4001)[0] == 409


def test_a_recording_that_went_quiet_shows_it_stopped_early(ws):
    from orch_personal import meetings as meetings_mod

    m = meetings_mod.record(ws, START["rec"], "human:sl", started=START["started"])
    assert meetings_mod.recording_state(m) == "recording"
    later = meetings_mod.dt.datetime.now().timestamp() + meetings_mod.QUIET_AFTER + 1
    assert meetings_mod.recording_state(m, later) == "stopped"


def test_a_helper_can_not_record(ws, monkeypatch):
    from orch_personal import api

    as_helper(monkeypatch)
    with pytest.raises(api.Refused):
        api.meetings_record(ws, api.who_from_env(), START["rec"], started=START["started"])


def test_record_is_offered_only_while_the_relay_is_on(on, ws, monkeypatch):
    from orch import addons

    assert meetings(on)["record"] is False
    monkeypatch.setattr(addons, "active", lambda root: {"relay": {}})
    assert meetings(on)["record"] is False  # on, but not connected to a relay
    secrets = ws / ".orch" / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "relay.json").write_text('{"url": "https://relay.example"}', encoding="utf-8")
    assert meetings(on)["record"] is True
