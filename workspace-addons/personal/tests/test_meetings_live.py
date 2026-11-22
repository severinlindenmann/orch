"""Meetings, live (ORCH-1195): the orch Companion way in says when a call runs; Personal shows "Meeting started" and
"Meeting ended", and a stale or missing answer never ends a call."""

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
    assert code == 0 and d["now"]["state"] == "call" and d["now"]["words"] == "Meeting started in Teams"
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
    assert "not answering" in meetings_live.live(ws)["words"]
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


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc")
def test_companion_app_state_machine_and_fake_call(tmp_path):
    out = tmp_path / "build"
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    exe = out / "orch Companion.app" / "Contents" / "MacOS" / "orch-companion"
    r = subprocess.run([str(exe), "--selftest"], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stdout
    home = tmp_path / "chome"
    (home / "wanted").mkdir(parents=True)
    (home / "wanted" / "ws.json").write_text("{}")
    fake = tmp_path / "fake.txt"
    fake.write_text("0 com.microsoft.teams2 on\n5 com.microsoft.teams2 off\n")
    env = {**os.environ, "ORCH_COMPANION_HOME": str(home)}
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
    write_now(companion_home, "call", app="Teams", observed_since=since, consent="agreed", may_record=True)
    meetings_live.look(ws)
    meetings_live.look(ws)
    assert meetings_live.live(ws)["hint"] == "Everyone agreed."
    acts = [a["what"] for a in store.activity(ws) if a["part"] == "meetings"]
    assert acts.count("Everyone on the call agreed to record in Teams") == 1
    write_now(companion_home, "call", app="Teams", observed_since=since, consent="maybe", may_record=True)
    assert meetings_live.look(ws)["consent"] == "asked"  # an unknown answer counts as no answer


def _run_companion(exe, home, fake_lines, until):
    """Run the app headless with fake input; return every now.json state seen (state, consent, may_record)."""
    (home / "wanted").mkdir(parents=True)
    (home / "wanted" / "ws.json").write_text("{}")
    fake = home.parent / (home.name + ".txt")
    fake.write_text("\n".join(fake_lines) + "\n")
    env = {**os.environ, "ORCH_COMPANION_HOME": str(home)}
    p = subprocess.Popen([str(exe), "--headless", "--fake-input", str(fake)], env=env)
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


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc")
def test_companion_records_nothing_without_yes(tmp_path):
    out = tmp_path / "build"
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    exe = out / "orch Companion.app" / "Contents" / "MacOS" / "orch-companion"
    call = ["0 com.microsoft.teams2 on", "9 com.microsoft.teams2 off"]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(3) as pool:
        no, yes, silent = pool.map(
            lambda a: _run_companion(exe, tmp_path / a[0], call + a[1], 20),
            [("no", ["5 answer no"]), ("yes", ["5 answer yes"]), ("silent", [])],
        )
    for seen in (no, silent):
        assert ("call", "asked", False) in seen and not any(r[2] for r in seen), seen
    assert ("call", "declined", False) in no
    assert ("call", "agreed", True) in yes and yes[-1] == ("idle", None, False), yes
    # once the call ended the answer is gone: the next call asks again
    assert all(r[1] is None for r in yes if r[0] == "idle")
