"""Meetings, live (ORCH-1195): the orch Companion way in says when a call runs; Personal shows whether the call is
recorded and "Meeting ended", and a stale or missing answer never ends a call."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import as_helper, jrun

HERE = Path(__file__).parent
TEMPLATE = HERE.parent / "src" / "orch_personal" / "way_templates" / "companion"
SWIFT_DIR = HERE.parents[2] / "companion" / "mac"
# The way in runs in a clean environment without libfaketime (clock.yml): it reads the real time while the test
# stamps the moved one, so every answer looks stale there.
pytestmark = pytest.mark.skipif(
    "faketime" in os.environ.get("LD_PRELOAD", ""), reason="the way in sees the real clock, not libfaketime's"
)


def iso(ago=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago))


@pytest.fixture
def companion_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    d = home / "Library" / "Application Support" / "orch Companion"
    return d


def write_now(d, state, ago=0.0, **extra):
    d.mkdir(parents=True, exist_ok=True)
    (d / "now.json").write_text(
        json.dumps({"v": 1, "state": state, "updated": iso(ago), "instance": "a1", **extra})
    )


def on(cli, ws):
    assert jrun(cli, "add", "meetings")[0] == 0
    code, d = jrun(cli, "meetings", "companion")
    assert code == 0 and d["way"] == "companion"
    assert jrun(cli, "ways", "on", "companion")[0] == 0


def test_companion_way_in_is_added_off_and_only_the_person_adds_it(cli, ws, monkeypatch, companion_home):
    assert jrun(cli, "add", "meetings")[0] == 0
    assert jrun(cli, "meetings", "companion")[0] == 0
    way = ws / ".orch" / "addons" / "personal" / "ways" / "companion"
    assert sorted(p.name for p in way.iterdir()) == sorted(
        p.name for p in TEMPLATE.iterdir() if p.suffix in (".py", ".toml")
    )
    rows = {w["way"]: w for w in jrun(cli, "ways")[1]["ways"]}
    assert rows["companion"]["status"] == "off" and rows["companion"]["part"] == "meetings"
    assert jrun(cli, "meetings", "companion")[0] != 0  # already there
    as_helper(monkeypatch)
    assert jrun(cli, "meetings", "now")[0] != 0


def test_call_started_and_ended_show_on_meetings_and_in_the_activity(cli, ws, companion_home):
    write_now(companion_home, "idle")
    on(cli, ws)
    from orch_personal import meetings_live, store

    assert meetings_live.look(ws)["state"] == "idle"
    # the look renewed this workspace's wanted file, so Companion watches for calls
    wanted = list((companion_home / "wanted").glob("*.json"))
    assert len(wanted) == 1 and oct(wanted[0].stat().st_mode & 0o777) == "0o600"

    write_now(companion_home, "call", app="Teams", observed_since=iso(4))
    code, d = jrun(cli, "meetings", "now")
    assert code == 0 and d["now"]["state"] == "call" and d["now"]["words"] == "Teams call · not recording"
    meetings_live.look(ws)  # the same call again: no second "started"
    write_now(companion_home, "idle")
    assert meetings_live.look(ws)["state"] == "ended"
    assert meetings_live.live(ws)["words"] == "Meeting ended"
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert acts.count("Meeting started in Teams") == 1 and acts.count("Meeting ended in Teams") == 1
    listed = jrun(cli, "meetings", "list")[1]
    assert listed["now"]["state"] == "ended"


def test_a_stale_or_missing_answer_never_ends_a_running_call(cli, ws, companion_home):
    since = iso(10)
    write_now(companion_home, "call", app="Teams", observed_since=since)
    on(cli, ws)
    from orch_personal import meetings_live, store

    assert meetings_live.look(ws)["state"] == "call"
    write_now(companion_home, "idle", ago=120)  # Companion stopped writing: stale
    s = meetings_live.look(ws)
    assert s["state"] == "quiet" and s["app"] == "Teams"
    q = meetings_live.live(ws)
    assert q["words"] == "orch Companion is not running." and q["hint"] == "Open it on your Mac."
    (companion_home / "now.json").unlink()
    assert meetings_live.look(ws)["state"] == "quiet"
    write_now(companion_home, "call", app="Teams", observed_since=since)  # back: the same call, no new start
    meetings_live.look(ws)
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert acts == ["Meeting started in Teams"]


def test_broken_or_odd_files_count_as_not_answering(cli, ws, companion_home):
    write_now(companion_home, "idle")
    on(cli, ws)
    from orch_personal import meetings_live

    for body in (
        "not json",
        json.dumps({"v": 2, "state": "idle", "updated": iso()}),
        json.dumps({"v": 1, "state": "call", "updated": iso()}),  # a call without app
        json.dumps({"v": 1, "state": "dancing", "updated": iso()}),
        "x" * 5000,
    ):
        companion_home.mkdir(parents=True, exist_ok=True)
        (companion_home / "now.json").write_text(body)
        assert meetings_live.look(ws)["state"] == "quiet", body[:40]
    (companion_home / "now.json").unlink()
    (companion_home / "now.json").symlink_to(companion_home / "elsewhere.json")
    assert meetings_live.look(ws)["state"] == "quiet"


def test_self_check_says_install_or_open(cli, ws, companion_home):
    on(cli, ws)
    from orch_personal import ways

    r = ways.check(ws, "companion")
    assert r["status"] == "permission" and "Install and open orch Companion" in r["problem"]
    write_now(companion_home, "idle", ago=300)
    r = ways.check(ws, "companion")
    assert r["status"] == "stopped" and "not running" in r["problem"]
    write_now(companion_home, "idle")
    assert ways.check(ws, "companion")["status"] == "works"
    # running the scripts left no bytecode behind, so the way in is not "changed"
    way = ws / ".orch" / "addons" / "personal" / "ways" / "companion"
    assert not (way / "__pycache__").exists()
    assert ways.check(ws, "companion")["status"] == "works"


def test_no_live_recorder_means_nothing_shown(cli, ws, companion_home):
    assert jrun(cli, "add", "meetings")[0] == 0
    from orch_personal import meetings_live

    assert meetings_live.live(ws) is None
    assert jrun(cli, "meetings", "list")[1]["now"] is None
    code, out, _ = cli("meetings", "now")
    assert code == 0 and "No recorder that sees calls is on" in out


def test_a_helper_gets_no_live_call_state(cli, ws, monkeypatch, companion_home):
    write_now(companion_home, "call", app="Teams", observed_since=iso(4))
    on(cli, ws)
    from orch_personal import meetings_live

    meetings_live.look(ws)
    jrun(cli, "meetings", "rules", "--read", "all")
    as_helper(monkeypatch)
    assert jrun(cli, "meetings", "list")[1]["now"] is None


MAC = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc"
)


@pytest.fixture(scope="module")
def companion_exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("companion-build")
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    return out / "orch Companion.app" / "Contents" / "MacOS" / "orch-companion"


@MAC
def test_companion_app_state_machine_and_fake_call(tmp_path, companion_exe):
    exe = companion_exe
    r = subprocess.run([str(exe), "--selftest"], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stdout
    home = tmp_path / "chome"
    (home / "wanted").mkdir(parents=True)
    (home / "wanted" / "ws.json").write_text("{}")
    fake = tmp_path / "fake.txt"
    fake.write_text("0 com.microsoft.teams2 on\n5 com.microsoft.teams2 off\n")
    env = {
        **os.environ,
        "ORCH_COMPANION_HOME": str(home),
        "ORCH_COMPANION_TEST_KEYS": str(home.parent / (home.name + "-keys")),
    }
    p = subprocess.Popen([str(exe), "--headless", "--fake-input", str(fake)], env=env)
    seen = []
    try:
        end = time.time() + 25
        while time.time() < end:
            try:
                st = json.loads((home / "now.json").read_text())["state"]
            except (OSError, ValueError):
                st = None
            if st and (not seen or seen[-1] != st):
                seen.append(st)
            if seen[-3:] == ["idle", "call", "idle"]:
                break
            time.sleep(0.5)
    finally:
        p.terminate()
        p.wait(timeout=10)
    assert seen[-3:] == ["idle", "call", "idle"], seen
    assert oct((home / "now.json").stat().st_mode & 0o777) == "0o600"


def test_companion_opened_after_turning_on_starts_working_without_waiting_a_day(
    cli, ws, companion_home, monkeypatch
):
    on(cli, ws)  # not installed yet: needs the person
    from orch_personal import meetings_live, ways

    assert meetings_live.look(ws)["state"] == "none"
    write_now(companion_home, "idle")  # the person opened orch Companion
    monkeypatch.setattr(meetings_live, "RECHECK_EVERY", -1)
    assert meetings_live.look(ws)["state"] == "idle"
    assert {w["way"]: w["status"] for w in ways.status(ws)}["companion"] == "works"


def test_meetings_shows_whether_everyone_agreed(cli, ws, companion_home):
    write_now(companion_home, "idle")
    on(cli, ws)
    from orch_personal import meetings_live, store

    since = iso(5)
    write_now(companion_home, "call", app="Teams", observed_since=since, consent="asked", may_record=False)
    meetings_live.look(ws)
    n = meetings_live.live(ws)
    assert n["consent"] == "asked" and "Waiting for your answer" in n["hint"]
    write_now(
        companion_home,
        "call",
        app="Teams",
        observed_since=since,
        consent="agreed",
        may_record=True,
        recording=True,
    )
    meetings_live.look(ws)
    meetings_live.look(ws)
    assert meetings_live.live(ws)["hint"] == "Everyone agreed."
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert acts.count("Everyone on the call agreed to record in Teams") == 1
    write_now(companion_home, "call", app="Teams", observed_since=since, consent="maybe", may_record=True)
    assert meetings_live.look(ws)["consent"] == "asked"  # an unknown answer counts as no answer


def _run_companion(exe, home, fake_lines, until, audio=True):
    """Run the app headless with fake input; return every now.json state seen (state, consent, may_record)."""
    (home / "wanted").mkdir(parents=True)
    (home / "wanted" / "ws.json").write_text("{}")
    fake = home.parent / (home.name + ".txt")
    fake.write_text("\n".join(fake_lines) + "\n")
    env = {
        **os.environ,
        "ORCH_COMPANION_HOME": str(home),
        "ORCH_COMPANION_TEST_KEYS": str(home.parent / (home.name + "-keys")),
    }
    argv = [str(exe), "--headless", "--fake-input", str(fake)] + (["--fake-audio"] if audio else [])
    p = subprocess.Popen(argv, env=env)
    seen = []
    try:
        end = time.time() + until
        while time.time() < end:
            try:
                d = json.loads((home / "now.json").read_text())
                row = (d["state"], d.get("consent"), d.get("may_record"))
            except (OSError, ValueError, KeyError):
                row = None
            if row and (not seen or seen[-1] != row):
                seen.append(row)
            time.sleep(0.3)
    finally:
        p.terminate()
        p.wait(timeout=10)
    return seen


@MAC
def test_companion_records_nothing_without_yes(tmp_path, companion_exe):
    exe = companion_exe
    call = ["0 com.microsoft.teams2 on", "9 com.microsoft.teams2 off"]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(3) as pool:
        no, yes, silent = pool.map(
            lambda a: _run_companion(exe, tmp_path / a[0], call + a[1], 20),
            [("no", ["5 answer no"]), ("yes", ["5 answer yes"]), ("silent", [])],
        )
    for name, seen in (("no", no), ("silent", silent)):
        assert ("call", "asked", False) in seen and not any(r[2] for r in seen), seen
        assert not (tmp_path / name / "recordings").exists()  # nothing recorded, not even an empty file
    assert ("call", "declined", False) in no
    assert ("call", "agreed", True) in yes and yes[-1] == ("idle", None, False), yes
    # once the call ended the answer is gone: the next call asks again
    assert all(r[1] is None for r in yes if r[0] == "idle")


@MAC
def test_someone_joining_asks_again_and_pauses_until_the_answer(tmp_path, companion_exe):
    """ORCH-1501: a fake call agreed at 4 s, someone joins at 8 s; only yes records the new part again."""
    exe = companion_exe
    call = ["0 com.microsoft.teams2 on", "4 answer yes", "8 join", "16 com.microsoft.teams2 off"]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(3) as pool:
        yes, no, silent = pool.map(
            lambda a: _run_companion(exe, tmp_path / a[0], call + a[1], 28),
            [("yes", ["12 answer yes"]), ("no", ["12 answer no"]), ("silent", [])],
        )
    for seen in (yes, no, silent):
        agreed = seen.index(("call", "agreed", True))
        assert ("call", "asked", False) in seen[agreed:], seen  # asked again, may_record off: paused
        assert seen[-1] == ("idle", None, False), seen
    assert ("call", "agreed", True) in yes[yes.index(("call", "asked", False), agreed) :], yes
    assert ("call", "declined", False) in no and not ("call", "declined", False) in silent

    def one(name):
        recs = list((tmp_path / name / "recordings").iterdir())
        assert len(recs) == 1, recs  # the same recording goes on: a pause, never a second one
        info = json.loads((recs[0] / "info.json").read_text())
        return info, _read(exe, tmp_path / name, recs[0])

    info, r = one("yes")
    (span,) = info["paused"]
    assert info["state"] == "done" and span["to"] - span["from"] >= 2, info
    for track in ("me", "others"):
        t = r[track]
        assert t["state"] == "complete", t
        (gap,) = t["gaps"]  # nothing was kept while the new person had not agreed
        assert gap[0] <= span["from"] + 0.2 and gap[1] >= span["to"] - 0.2, (gap, span)
        assert t["seconds"] - gap[0] >= 3, t  # recording went on after yes
    for name, why in (("no", "not everyone agreed"), ("silent", "the call ended")):
        info, r = one(name)
        (span,) = info["paused"]
        assert info["state"] == "done" and info["why"] == why, info
        for track in ("me", "others"):
            t = r[track]
            # nothing of the new part: no audio after the join, no gap, the call agreed before is kept
            assert t["state"] == "complete" and t["gaps"] == [], t
            assert 2 <= t["seconds"] <= span["from"] + 0.2, (t, span)


def _read(exe, home, folder):
    env = {**os.environ, "ORCH_COMPANION_TEST_KEYS": str(home.parent / (home.name + "-keys"))}
    r = subprocess.run(
        [str(exe), "--read-recording", str(folder)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(r.stdout)


def _frames(data):
    """Byte spans of each frame after the 21-byte header (no decryption needed to cut or move them)."""
    at, out = 21, []
    while at + 16 <= len(data):
        n = int.from_bytes(data[at : at + 4], "big")
        out.append((at, at + 16 + n))
        at += 16 + n
    return out


@pytest.fixture(scope="module")
def recorded(tmp_path_factory, companion_exe):
    """Two fake calls answered yes: two recordings with 440 Hz (me) and 660 Hz (others)."""
    base = tmp_path_factory.mktemp("recorded")
    home = base / "home"
    call = [
        "0 com.microsoft.teams2 on",
        "4 answer yes",
        "8 com.microsoft.teams2 off",
        "20 com.microsoft.teams2 on",
        "24 answer yes",
        "28 com.microsoft.teams2 off",
    ]
    seen = _run_companion(companion_exe, home, call, 44)
    recs = sorted(
        (home / "recordings").iterdir(), key=lambda d: json.loads((d / "info.json").read_text())["started"]
    )
    return companion_exe, home, recs, seen


@MAC
def test_companion_records_two_encrypted_tracks_after_yes(recorded):
    exe, home, recs, seen = recorded
    assert len(recs) == 2
    assert any(r[2] for r in seen) and seen[-1][2] is False
    r = _read(exe, home, recs[0])
    for track, hz in (("me", 440), ("others", 660)):
        t = r[track]
        assert t["state"] == "complete" and t["seconds"] >= 5, t
        assert abs(t["hz"] - hz) < 5, t
        assert t["details"]["consent"] == "agreed" and t["details"]["track"] == track
    info = json.loads((recs[0] / "info.json").read_text())
    assert info["state"] == "done" and info["consent"]["answer"] == "agreed"
    for f in recs[0].iterdir():
        assert oct(f.stat().st_mode & 0o777) == "0o600", f
    assert oct(recs[0].stat().st_mode & 0o777) == "0o700"


@MAC
def test_no_plain_audio_is_written_to_disk(recorded):
    import array
    import math

    _, home, _, _ = recorded
    # the first 100 ms the fake microphone made, as the bytes a plain recording would hold
    plain = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(400, 1200)))
    needle = plain.tobytes()[:400]
    for f in home.rglob("*"):
        if f.is_file():
            assert needle not in f.read_bytes(), f
            assert f.suffix not in (".wav", ".caf", ".aiff", ".m4a"), f


@MAC
def test_a_changed_cut_or_moved_frame_is_never_read_as_complete(recorded, tmp_path):
    exe, home, recs, _ = recorded
    src = recs[0]
    data = (src / "me.ocr").read_bytes()
    spans = _frames(data)
    assert len(spans) > 10

    def variant(name, me_bytes, others=None):
        d = tmp_path / name / src.name
        d.mkdir(parents=True)
        (d / "me.ocr").write_bytes(me_bytes)
        (d / "others.ocr").write_bytes(others if others is not None else (src / "others.ocr").read_bytes())
        return _read(exe, home, d)["me"]

    # cut at a frame boundary or in the middle of one: readable up to there, never "complete"
    for i, cut in enumerate([spans[3][1], spans[-2][1], spans[5][0] + 10]):
        r = variant(f"cut{i}", data[:cut])
        assert r["state"] == "cut off", r
    flipped = bytearray(data)
    flipped[spans[4][0] + 30] ^= 1
    assert variant("flip", bytes(flipped))["state"] == "broken"
    a, b = spans[4], spans[5]
    assert variant("drop", data[: a[0]] + data[a[1] :])["state"] == "broken"
    assert variant("double", data[: a[1]] + data[a[0] : a[1]] + data[a[1] :])["state"] == "broken"
    assert (
        variant("swap", data[: a[0]] + data[b[0] : b[1]] + data[a[0] : a[1]] + data[b[1] :])["state"]
        == "broken"
    )
    huge = bytearray(data)
    huge[a[0] : a[0] + 4] = (1 << 30).to_bytes(4, "big")
    assert variant("huge", bytes(huge))["state"] == "broken"
    # the other track's file in place of mine, and a track from the second recording
    assert variant("track", (src / "others.ocr").read_bytes())["state"] == "broken"
    assert variant("other", (recs[1] / "me.ocr").read_bytes())["state"] == "broken"


@MAC
def test_without_its_key_a_recording_cannot_be_read(recorded, tmp_path):
    exe, _, recs, _ = recorded
    r = subprocess.run(
        [str(exe), "--read-recording", str(recs[0])],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "ORCH_COMPANION_TEST_KEYS": str(tmp_path / "no-keys")},
        check=True,
    )
    assert json.loads(r.stdout) == {"state": "broken", "why": "no key"}


def test_the_line_says_whether_the_call_is_recorded(cli, ws, companion_home):
    call_since, rec_since = iso(300), iso(120)
    write_now(companion_home, "call", app="Teams", observed_since=call_since, consent="asked")
    on(cli, ws)
    from orch_personal import meetings_live

    meetings_live.look(ws)
    n = meetings_live.live(ws)
    assert n["words"] == "Teams call · not recording" and n["since"] == call_since and not n["recording"]
    assert "did everyone agree" in n["hint"]
    # Companion says recording without everyone's agreement: never shown as recording
    write_now(companion_home, "call", app="Teams", observed_since=call_since, consent="asked", recording=True)
    meetings_live.look(ws)
    assert meetings_live.live(ws)["words"] == "Teams call · not recording"
    # agreed but nothing recorded (a missing permission): the line says so
    write_now(
        companion_home, "call", app="Teams", observed_since=call_since, consent="agreed", may_record=True
    )
    meetings_live.look(ws)
    n = meetings_live.live(ws)
    assert n["words"] == "Teams call · not recording" and "nothing is recorded" in n["hint"]
    write_now(
        companion_home,
        "call",
        app="Teams",
        observed_since=call_since,
        consent="agreed",
        may_record=True,
        recording=True,
        recording_since=rec_since,
    )
    meetings_live.look(ws)
    n = meetings_live.live(ws)
    assert n["words"] == "Teams call · recording" and n["recording"] and n["since"] == rec_since
    write_now(companion_home, "idle")
    meetings_live.look(ws)
    n = meetings_live.live(ws)
    assert n["words"] == "Meeting ended" and "recording" not in n


def test_an_ended_call_stays_ended_after_a_pause(cli, ws, companion_home):
    write_now(companion_home, "call", app="Teams", observed_since=iso(60))
    on(cli, ws)
    from orch_personal import meetings_live, store

    meetings_live.look(ws)
    write_now(companion_home, "idle")
    assert meetings_live.look(ws)["state"] == "ended"
    (companion_home / "now.json").unlink()  # orch Companion stops answering for a moment
    assert meetings_live.look(ws)["state"] == "quiet"
    write_now(companion_home, "idle")  # back, still no call
    assert meetings_live.look(ws)["state"] == "ended"
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert acts.count("Meeting ended in Teams") == 1


def test_a_call_belongs_to_the_recorder_that_reported_it(cli, ws, companion_home):
    write_now(companion_home, "idle")
    on(cli, ws)
    from orch_personal import meetings_live, store

    meetings_live.look(ws)
    since = iso(30)
    other = dict(meetings_live.saved(ws), way="yogurt", state="call", app="Zoom", since=since)
    meetings_live._save(ws, other)  # a call another recorder reported
    write_now(companion_home, "idle")
    s = meetings_live.look(ws)
    assert s["state"] == "idle" and s["way"] == "companion"
    write_now(
        companion_home, "call", app="Teams", observed_since=since
    )  # same time, other recorder: a new call
    meetings_live.look(ws)
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert "Meeting ended in Zoom" not in acts and acts.count("Meeting started in Teams") == 1
