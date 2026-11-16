"""Automatic update (Settings > About & updates): off until a person turns it on, installs only at a quiet
moment, keeps a note for Home with the new version and what changed (or why it failed)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from orch import autoupdate, updateinfo
from orch.errors import Refused

OLD, NEW = "a" * 40, "b" * 40
NOW = 1_800_000_000.0


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "run" / "tickets").mkdir(parents=True)
    installed = {"sha": OLD, "release": 16}
    monkeypatch.setattr(updateinfo, "installed", lambda: dict(installed))
    monkeypatch.setattr(
        updateinfo,
        "info",
        lambda use_cache=True: {
            "installed": {"sha": installed["sha"], "release": 16, "label": "orch 16"},
            "newest": {"sha": NEW, "release": 17, "label": "orch 17"},
            "update_available": installed["sha"] != NEW,
            "changes": ["Helpers tidy up a new ticket", "Sync shows where your copy lives"],
        },
    )
    monkeypatch.setattr(autoupdate, "_update_under_way", lambda: False)
    return SimpleNamespace(root=root, installed=installed)  # the test plays the update by changing installed


class Starter:
    def __init__(self, pid=None):
        self.calls, self.pid = 0, pid

    def __call__(self):
        self.calls += 1
        return self.pid or 999_999


def helper_running(root, pid):
    rec = {"run": "r_1", "ticket": "t_abc123", "pid": pid}
    (root / ".orch" / "run" / "tickets" / "t_abc123.json").write_text(json.dumps(rec))


def test_off_by_default_never_starts(ws):
    start = Starter()
    assert autoupdate.enabled() is False
    assert autoupdate.tick(ws.root, start, now=NOW) == "off"
    assert start.calls == 0


def test_only_a_person_turns_it_on_an_agent_may_turn_it_off():
    with pytest.raises(Refused):
        autoupdate.set_enabled(True, by="agent:claude")
    assert autoupdate.enabled() is False
    autoupdate.set_enabled(True, by="human:owner")
    assert autoupdate.enabled() is True
    autoupdate.set_enabled(False, by="agent:claude")
    assert autoupdate.enabled() is False


def test_newer_release_at_a_quiet_moment_starts_the_update(ws):
    autoupdate.set_enabled(True)
    start = Starter()
    assert autoupdate.tick(ws.root, start, now=NOW) == "started"
    assert start.calls == 1
    assert autoupdate.status()["updating"] is True
    assert autoupdate.tick(ws.root, start, now=NOW + 60) != "started"  # never a second one meanwhile
    assert start.calls == 1


def test_helper_running_waits_and_retries_later(ws):
    autoupdate.set_enabled(True)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        helper_running(ws.root, sleeper.pid)
        start = Starter()
        assert autoupdate.tick(ws.root, start, now=NOW) == "waiting: 1 helper is working"
        assert start.calls == 0
        assert autoupdate.tick(ws.root, start, now=NOW + 60) == "later"  # looks again after a few minutes
    finally:
        sleeper.kill()
        sleeper.wait()
    # the helper finished: the next look after the pause starts it
    assert autoupdate.tick(ws.root, start, now=NOW + autoupdate.RETRY_BUSY + 1) == "started"
    assert start.calls == 1


def test_a_finished_helper_does_not_block(ws):
    autoupdate.set_enabled(True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    helper_running(ws.root, dead.pid)
    assert autoupdate.tick(ws.root, Starter(), now=NOW) == "started"


def test_a_click_under_way_or_just_now_waits(ws):
    autoupdate.set_enabled(True)
    start = Starter()
    assert autoupdate.tick(ws.root, start, clicking=True, now=NOW).startswith("waiting: a person")
    autoupdate.set_enabled(True)  # look again at once
    import time

    assert autoupdate.tick(ws.root, start, last_click=time.time() - 10, now=NOW).startswith(
        "waiting: a person"
    )
    assert start.calls == 0


def test_an_update_already_running_waits(ws, monkeypatch):
    autoupdate.set_enabled(True)
    monkeypatch.setattr(autoupdate, "_update_under_way", lambda: True)
    assert autoupdate.tick(ws.root, Starter(), now=NOW) == "waiting: an update is already running"


def test_up_to_date_looks_again_in_an_hour(ws):
    autoupdate.set_enabled(True)
    ws.installed["sha"] = NEW
    start = Starter()
    assert autoupdate.tick(ws.root, start, now=NOW) == "current"
    assert autoupdate.tick(ws.root, start, now=NOW + 600) == "later"
    assert start.calls == 0


def test_after_the_update_home_gets_the_new_version_and_what_changed(ws):
    autoupdate.set_enabled(True)
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert autoupdate.tick(ws.root, Starter(pid=done.pid), now=NOW) == "started"
    ws.installed.update(sha=NEW, release=17)  # what `orch update` wrote
    assert autoupdate.tick(ws.root, Starter(), now=NOW + 120) == "updated"
    n = autoupdate.note()
    assert n["state"] == "updated" and n["from"] == "orch 16" and n["to"] == "orch 17"
    assert n["changes"] == ["Helpers tidy up a new ticket", "Sync shows where your copy lives"]
    autoupdate.dismiss_note()
    assert autoupdate.note() is None


def test_a_failed_update_says_so_stays_and_tries_again_later(ws):
    autoupdate.set_enabled(True)
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert autoupdate.tick(ws.root, Starter(pid=done.pid), now=NOW) == "started"
    # nothing changed: the install failed and orch is still the old version
    assert autoupdate.tick(ws.root, Starter(), now=NOW + 120) == "failed"
    n = autoupdate.note()
    assert n["state"] == "failed" and n["from"] == "orch 16" and n["to"] == "orch 17" and n["reason"]
    start = Starter()
    assert autoupdate.tick(ws.root, start, now=NOW + 3600) == "later"  # not again within the hour
    assert autoupdate.tick(ws.root, start, now=NOW + autoupdate.RETRY_FAILED + 200) == "started"


def test_still_running_update_is_left_alone(ws):
    autoupdate.set_enabled(True)
    assert autoupdate.tick(ws.root, Starter(pid=os.getpid()), now=NOW) == "started"
    assert autoupdate.tick(ws.root, Starter(), now=NOW + 60) == "updating"
    assert autoupdate.note() is None


def test_start_error_is_a_plain_note(ws):
    autoupdate.set_enabled(True)

    def broken():
        raise OSError("no")

    assert autoupdate.tick(ws.root, broken, now=NOW) == "failed"
    assert autoupdate.note()["reason"] == "the update could not be started"
    assert autoupdate.status()["updating"] is False


def test_status_says_when_a_development_build_follows_its_branch(monkeypatch):
    monkeypatch.setattr(autoupdate, "_ref", lambda: "develop")
    assert autoupdate.status()["branch"] is True and autoupdate.status()["ref"] == "develop"
    monkeypatch.setattr(autoupdate, "_ref", lambda: "main")
    assert autoupdate.status()["branch"] is False


def test_config_key(tmp_path, monkeypatch):
    from orch import cli

    monkeypatch.chdir(tmp_path)
    for k in ("CLAUDECODE", "CODEX_SANDBOX", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("orch.tickets.agent_tool", lambda: None)
    cli.main(["config", "set", "update.auto", "on"])
    assert autoupdate.enabled() is True
    cli.main(["config", "set", "update.auto", "off"])
    assert autoupdate.enabled() is False
