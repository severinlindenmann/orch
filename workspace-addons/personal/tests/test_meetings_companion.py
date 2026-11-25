"""Meetings 7 (ORCH-1269): a call orch Companion recorded shows on Meetings with its transcript, once the transcript
is done; before that Meetings says it is being transcribed (or the plain problem). Companion asked everyone before it
recorded, so Meetings does not ask again. With two workspaces (personal and work) on one Mac, Companion asks after
the call which gets it; only the workspaces the person picked see it (owner, 22 Nov)."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from conftest import as_helper, jrun
from test_meetings_live import companion_home, on, write_now  # noqa: F401  (fixture)

from orch_personal import api, meetings

ISO = "%Y-%m-%dT%H:%M:%SZ"


def iso(ago=0.0):
    return time.strftime(ISO, time.gmtime(time.time() - ago))


def wid(root):
    """The name a workspace's companion way in has in Companion's folder (companion_files.me)."""
    way = Path(root) / ".orch" / "addons" / "personal" / "ways" / "companion"
    return hashlib.sha256(str(way.resolve()).encode()).hexdigest()[:16]


def recording(
    home, minutes=12, state="done", transcript=None, consent="agreed", rid=None, made_for=None, pick=None
):
    rid = rid or str(uuid.uuid4())
    d = home / "recordings" / rid
    d.mkdir(parents=True)
    info = {
        "v": 1,
        "id": rid,
        "app": "Teams",
        "started": iso(minutes * 60 + 60),
        "state": state,
        "consent": {"answer": consent, "at": iso(minutes * 60 + 70)},
        "for": made_for if made_for is not None else [wid(os.environ["ORCH_ROOT"])],
    }
    if state != "recording":
        info["ended"] = iso(60)
    (d / "info.json").write_text(json.dumps(info))
    if transcript is not None:
        (d / "transcript.json").write_text(json.dumps({"v": 1, "id": rid, **transcript}))
    if pick is not None:
        (d / "pick.json").write_text(json.dumps({"v": 1, "for": pick, "at": iso(30)}))
    return rid


LINES = [
    {"start": 1.2, "end": 3.0, "who": "me", "text": "Grüezi zäme, chönd mer afange?"},
    {"start": 4.0, "end": 9.5, "who": "others", "text": "Ja, gern. Zuerst die Offerte für Helvetia."},
    {"start": 3725.0, "end": 3730.0, "who": "others", "text": "Dann bis nächste Woche."},
]


def test_a_transcribed_call_arrives_with_its_transcript_without_a_second_ask(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    rid = recording(companion_home, transcript={"state": "done", "minutes": 62, "lines": LINES})
    on(cli, ws)
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["problems"] == [] and r["new"] == 0 and r["taken"] == 1
    d = jrun(cli, "meetings", "list")[1]
    assert d["waiting"] == [] and d["pending"] == []
    (m,) = d["meetings"]
    assert m["title"] == "Teams call" and m["minutes"] == 62
    full = jrun(cli, "meetings", "show", m["id"])[1]
    assert [(x["who"], x["at"], x["text"]) for x in full["transcript"]] == [
        ("Me", "00:01", "Grüezi zäme, chönd mer afange?"),
        ("Others", "00:04", "Ja, gern. Zuerst die Offerte für Helvetia."),
        ("Others", "1:02:05", "Dann bis nächste Woche."),
    ]
    saved = meetings.load(ws, m["id"])
    assert saved["ref"] == rid and saved["consent"]["by"] == "recorder:orch Companion"
    assert saved["consent"]["words"] == meetings.CONSENT_WORDS
    tile = api._meetings_tile(ws, {}, [], api.Who(helper=False, by="human"))
    assert tile["status"] == "1 meeting" and tile["line"] == "Teams call"


def test_waiting_and_failed_calls_say_so_and_arrive_later(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    rec = recording(companion_home, state="recording")
    soon = recording(companion_home, transcript=None)
    down = (
        "Transcript waits: the transcription service cannot be reached. orch Companion tries again at 14:05."
    )
    late = recording(companion_home, transcript={"state": "waiting", "problem": down})
    gone = recording(companion_home, transcript={"state": "failed", "problem": ""})
    on(cli, ws)
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["new"] == 0 and r["taken"] == 0
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == []
    words = sorted(p["words"] for p in d["pending"])
    assert words == sorted(
        [
            "Being recorded.",
            "Being transcribed. It arrives here when the transcript is ready.",
            down,
            "The transcript could not be made. The recording is kept.",
        ]
    )
    assert all(p["source"] == "orch Companion" and p["title"] == "Teams call" for p in d["pending"])
    assert {rec, soon, late, gone}  # four different recordings
    # the service is back: the transcript is done and the call arrives; it is no longer pending
    (companion_home / "recordings" / late / "transcript.json").write_text(
        json.dumps({"v": 1, "id": late, "state": "done", "lines": LINES[:1]})
    )
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["taken"] == 1
    d = jrun(cli, "meetings", "list")[1]
    assert len(d["meetings"]) == 1 and len(d["pending"]) == 3


def test_odd_files_are_never_shown(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    recording(companion_home, consent="declined", transcript={"state": "done", "lines": LINES})
    rid = recording(companion_home, transcript={"state": "done", "lines": LINES})
    (companion_home / "recordings" / rid / "transcript.json").write_text("{broken")
    other = recording(companion_home, transcript={"state": "done", "lines": LINES})
    t = companion_home / "recordings" / other / "transcript.json"
    t.write_text(json.dumps({"v": 1, "id": "someone-else", "state": "done", "lines": LINES}))
    (companion_home / "recordings" / "not-an-id").mkdir()
    linked = companion_home / "recordings" / str(uuid.uuid4())
    linked.symlink_to(companion_home / "recordings" / rid)
    on(cli, ws)
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["taken"] == 0 and r["problems"] == []
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == []
    assert len(d["pending"]) == 2  # broken and wrong id: still waiting for a transcript, never read


def test_a_long_transcript_comes_in_pages(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    many = [
        {"start": i * 2.0, "end": i * 2.0 + 1, "who": "me" if i % 2 else "others", "text": f"Satz {i}"}
        for i in range(1201)
    ]
    recording(companion_home, transcript={"state": "done", "lines": many})
    on(cli, ws)
    assert jrun(cli, "meetings", "pickup")[1]["taken"] == 1
    mid = jrun(cli, "meetings", "list")[1]["meetings"][0]["id"]
    got = jrun(cli, "meetings", "show", mid)[1]["transcript"]
    assert len(got) == 1201 and got[-1]["text"] == "Satz 1200" and got[-1]["at"] == "40:00"


def _work(tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / ".orch" / "tickets").mkdir(parents=True)
    return work


def _use(monkeypatch, root):
    monkeypatch.setenv("ORCH_ROOT", str(root))


def test_only_the_picked_workspace_gets_the_call(cli, ws, tmp_path, monkeypatch, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    work = _work(tmp_path, monkeypatch)
    both = [wid(ws), wid(work)]
    rid = recording(companion_home, transcript={"state": "done", "lines": LINES}, made_for=both)
    on(cli, ws)
    _use(monkeypatch, work)
    on(cli, work)
    for root in (ws, work):  # not picked yet: neither workspace sees anything of it, not even the time
        _use(monkeypatch, root)
        assert jrun(cli, "meetings", "pickup")[1]["taken"] == 0
        d = jrun(cli, "meetings", "list")[1]
        assert d["meetings"] == [] and d["pending"] == []
    pick = companion_home / "recordings" / rid / "pick.json"
    pick.write_text(json.dumps({"v": 1, "for": [wid(work)], "at": iso(1)}))
    _use(monkeypatch, work)
    assert jrun(cli, "meetings", "pickup")[1]["taken"] == 1
    d = jrun(cli, "meetings", "list")[1]
    assert len(d["meetings"]) == 1 and d["pending"] == []
    assert len(jrun(cli, "meetings", "show", d["meetings"][0]["id"])[1]["transcript"]) == 3
    _use(monkeypatch, ws)  # the personal workspace never gets it
    assert jrun(cli, "meetings", "pickup")[1]["taken"] == 0
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == [] and d["pending"] == []


def test_both_get_the_call_when_both_are_picked(cli, ws, tmp_path, monkeypatch, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    work = _work(tmp_path, monkeypatch)
    both = [wid(ws), wid(work)]
    recording(companion_home, transcript={"state": "done", "lines": LINES}, made_for=both, pick=both)
    on(cli, ws)
    _use(monkeypatch, work)
    on(cli, work)
    for root in (ws, work):
        _use(monkeypatch, root)
        assert jrun(cli, "meetings", "pickup")[1]["taken"] == 1
    mid = jrun(cli, "meetings", "list")[1]["meetings"][0]["id"]
    assert jrun(cli, "meetings", "delete", mid)[0] == 0  # deleting it in work keeps it in personal
    _use(monkeypatch, ws)
    assert len(jrun(cli, "meetings", "list")[1]["meetings"]) == 1


def test_a_call_made_for_another_workspace_is_never_shown(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    recording(companion_home, transcript={"state": "done", "lines": LINES}, made_for=["0123456789abcdef"])
    recording(companion_home, transcript={"state": "done", "lines": LINES}, made_for=[])
    on(cli, ws)
    assert jrun(cli, "meetings", "pickup")[1]["taken"] == 0
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == [] and d["pending"] == []


def test_the_workspace_hands_its_name_to_companion(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    on(cli, ws)
    from orch_personal import meetings_live, ways

    meetings_live.look(ws)
    wanted = companion_home / "wanted" / f"{wid(ws)}.json"
    assert json.loads(wanted.read_text())["name"] == "ws"
    ways.check(ws, "companion")  # the self-check renews the file without a name: the name stays
    assert json.loads(wanted.read_text())["name"] == "ws"


def test_a_helper_sees_no_pending_calls(cli, ws, monkeypatch, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    recording(companion_home, transcript={"state": "waiting"})
    on(cli, ws)
    jrun(cli, "meetings", "pickup")
    assert len(jrun(cli, "meetings", "list")[1]["pending"]) == 1
    jrun(cli, "meetings", "rules", "--read", "all")
    as_helper(monkeypatch)
    code, d = jrun(cli, "meetings", "list")
    assert code != 0 or d["pending"] == []


def test_one_odd_recording_never_hides_the_others(cli, ws, companion_home):  # noqa: F811
    write_now(companion_home, "idle")
    odd = recording(companion_home, transcript={"state": "done", "lines": LINES})
    info = companion_home / "recordings" / odd / "info.json"
    data = json.loads(info.read_text())
    data.update(started="2026-11-22T10:00:00", ended="2026-11-22T10:30:00+01:00")  # one without a zone
    info.write_text(json.dumps(data))
    recording(companion_home, transcript={"state": "done", "minutes": 1e308, "lines": LINES})
    on(cli, ws)
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["problems"] == [] and r["taken"] == 2


def test_a_linked_recording_folder_is_never_read_by_name(cli, ws, companion_home):  # noqa: F811
    import subprocess
    import sys

    write_now(companion_home, "idle")
    real = recording(companion_home, transcript={"state": "done", "lines": LINES})
    alias = str(uuid.uuid4())
    (companion_home / "recordings" / alias).symlink_to(companion_home / "recordings" / real)
    on(cli, ws)
    way = ws / ".orch" / "addons" / "personal" / "ways" / "companion"
    for ref, ok in ((real, True), (alias, False)):
        p = subprocess.run(
            [sys.executable, "-B", "meetings.py"],
            cwd=way,
            check=False,
            input=json.dumps({"action": "meeting", "values": {"ref": ref}}),
            capture_output=True,
            text=True,
        )
        assert (p.returncode == 0) is ok, (ref, p.stderr)
