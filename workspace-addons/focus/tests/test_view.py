import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest

from orch_focus import cli, runfiles
from orch_focus.events import EventLog, make
from orch_focus.needs import rows
from orch_focus.view import build

from .conftest import TID

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
VIEW = json.loads((CONTRACTS / "addon-view.schema.json").read_text())
NEEDS = json.loads((CONTRACTS / "needs.schema.json").read_text())
RUN = "r_abcd1234"


def check_view(v):
    jsonschema.Draft202012Validator(VIEW, format_checker=jsonschema.FormatChecker()).validate(v)


def check_needs(rs):
    jsonschema.Draft202012Validator(NEEDS, format_checker=jsonschema.FormatChecker()).validate(rs)


def claim(ws, tid=TID, mode="live", live=None, pid=None, **kw):
    d = ws / ".orch" / "run" / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    rec = {
        "schema": "orch.run/1", "ticket": tid, "run": RUN, "by": "focus", "agent": "claude", "mode": mode,
        "tmux": None, "pid": pid, "pid_started": runfiles.proc_start(pid) if pid > 1 else None,
        "started_at": "2026-11-06T08:00:00Z", "renewed_at": "2026-11-06T08:00:00Z", "pending": False,
        "stop_requested": None, "seen_revision": 0, **({"live": live} if live else {}), **kw,
    }  # fmt: skip
    (d / f"{tid}.json").write_text(json.dumps(rec))


def test_empty_view_is_valid_and_says_so(ws, fake_orch):
    v = build(ws, str(fake_orch))
    check_view(v)
    assert v["blocks"][0]["value"] == 0 and "No agent" in v["notice"]


def test_live_and_one_run_lists_with_page_links(ws, fake_orch):
    claim(ws)
    d = ws / ".orch" / "tickets"
    (d / "t_other0001.json").write_text(
        json.dumps({"id": "t_other0001", "title": "Other <b>", "status": "active"})
    )
    claim(ws, tid="t_other0001", mode="oneshot")
    v = build(ws, str(fake_orch))
    check_view(v)
    assert v["blocks"][0]["value"] == 2
    lists = {b["title"]: b["items"] for b in v["blocks"] if b["type"] == "list"}
    assert lists["Live now"][0]["title"] == "Close March books"
    assert lists["Live now"][0]["link"] == f"addon:t/{TID}"
    assert lists["Working now"][0]["title"] == "Other b"  # no markup survives
    assert lists["Working now"][0]["subtitle"] == "Claude · one run"
    assert "notice" not in v


def test_dead_or_foreign_claims_are_not_live(ws, fake_orch, tmp_path):
    claim(ws, pid=2**30)  # no such process
    assert build(ws, str(fake_orch))["blocks"][0]["value"] == 0
    claim(ws, pid=None, pid_started="not the start time")  # this pid, another start time: a reused pid
    d = ws / ".orch" / "run" / "tickets"
    rec = json.loads((d / f"{TID}.json").read_text())
    rec["pid_started"] = "Thu Jan  1 00:00:00 1970"
    (d / f"{TID}.json").write_text(json.dumps(rec))
    assert build(ws, str(fake_orch))["blocks"][0]["value"] == 0
    (d / f"{TID}.json").write_text("{not json")
    (d / "t_big000001.json").write_text('{"x":"' + "a" * 200000 + '"}')
    assert build(ws, str(fake_orch))["blocks"][0]["value"] == 0


def test_linked_record_and_folder_are_ignored(ws, fake_orch, tmp_path):
    claim(ws)
    d = ws / ".orch" / "run" / "tickets"
    real = tmp_path / "real"
    d.rename(real)
    d.symlink_to(real)
    assert build(ws, str(fake_orch))["blocks"][0]["value"] == 0


def test_needs_waiting_for_ok(ws, fake_orch):
    claim(ws, live={"state": "attention", "since": "2026-11-06T08:30:00Z"})
    rs = rows(ws, str(fake_orch))
    check_needs(rs)
    assert [r["id"] for r in rs] == [f"focus:waiting-{TID}"]
    assert rs[0]["tone"] == "needs-you" and rs[0]["cli"] == f"orch run attach {TID}"
    assert rs[0]["since"] == "2026-11-06T08:30:00Z"
    v = build(ws, str(fake_orch))
    check_view(v)
    assert v["blocks"][1]["items"][0]["chips"][0]["label"] == "Waiting for your OK"


def test_needs_denial_only_when_it_is_not_already_a_question(ws, fake_orch):
    claim(ws, mode="oneshot")
    EventLog(ws, RUN).append(
        make(RUN, TID, "main", "denial", "Needs your OK to use WebFetch", "adapter", tool="WebFetch")
    )
    rs = rows(ws, str(fake_orch))
    check_needs(rs)
    assert len(rs) == 1 and rs[0]["kind"] == "focus:denied" and "WebFetch" in rs[0]["text"]
    # the ticket now has the question about that tool: Focus adds nothing (core lists the question)
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["questions"] = [
        {
            "id": "q1",
            "kind": "focus:permission",
            "text": "Allow?",
            "options": [],
            "answer": None,
            "action": {"tool": "WebFetch"},
        }
    ]
    p.write_text(json.dumps(t))
    assert rows(ws, str(fake_orch)) == []


def test_needs_nothing_when_nothing_runs(ws, fake_orch):
    assert rows(ws, str(fake_orch)) == []


def test_cli_view_and_needs_json(ws, fake_orch, capsys, monkeypatch):
    monkeypatch.setenv("ORCH_BIN", str(fake_orch))
    claim(ws, live={"state": "attention", "since": "2026-11-06T08:30:00Z"})
    assert cli.main(["--dir", str(ws), "view", "--json"]) == 0
    check_view(json.loads(capsys.readouterr().out))
    assert cli.main(["--dir", str(ws), "needs", "--json"]) == 0
    check_needs(json.loads(capsys.readouterr().out))
    assert cli.main(["--dir", str(ws), "needs"]) == 0
    assert "Waiting for your OK" in capsys.readouterr().out


@pytest.mark.parametrize("field", ["background", "runs_agents", "needs"])
def test_manifest_flags(field):
    import tomllib
    from importlib import resources

    m = tomllib.loads((resources.files("orch_focus") / "orch-addon.toml").read_text())
    assert m[field] is True and m["page"]["path"] == "/" and m["dashboard"]["label"] == "Focus"
    assert (resources.files("orch_focus") / "skills" / "orch-focus" / "SKILL.md").is_file()
    assert (resources.files("orch_focus") / "skills" / "orch-focus" / "AGENTS-block.md").is_file()


def test_manifest_validates_against_the_contract_schema_and_ext_copy_is_identical():
    import tomllib
    from importlib import resources

    m = tomllib.loads((resources.files("orch_focus") / "orch-addon.toml").read_text())
    jsonschema.validate(m, json.loads((CONTRACTS / "addon-manifest.schema.json").read_text()))
    assert m["ticket_ext"] == "ext.schema.json"
    assert m["ticket_view"] == [{"field": "page", "label": "Focus page", "format": "open-page"}]
    ours = (resources.files("orch_focus") / "ext.schema.json").read_bytes()
    assert ours == (CONTRACTS / "addons" / "focus" / "ext.schema.json").read_bytes()


def test_stat_is_running_now(ws, fake_orch):
    assert build(ws, str(fake_orch))["blocks"][0]["label"] == "Running now"


def test_rows_show_the_ticket_key(ws, fake_orch):
    claim(ws)
    d = ws / ".orch" / "tickets"
    t = json.loads((d / f"{TID}.json").read_text())
    (d / f"{TID}.json").write_text(json.dumps({**t, "key": "DM1-12"}))
    lists = {b["title"]: b["items"] for b in build(ws, str(fake_orch))["blocks"] if b["type"] == "list"}
    assert lists["Live now"][0]["title"] == "DM1-12 · Close March books"


def test_view_asks_orch_twice_at_the_same_time_not_one_after_the_other(ws, tmp_path):
    """fb20: the dashboard gives `orch focus view` 2 s; a live session made it start two more orch commands one
    after the other (titles, then agent names), so a slow machine went past the limit and the tab went stale."""
    import sys
    import time

    slow = tmp_path / "slow-orch"
    slow.write_text(f"#!{sys.executable}\nimport sys, time\ntime.sleep(1.0)\nprint('[]')\n")
    slow.chmod(0o755)
    claim(ws)
    t0 = time.monotonic()
    build(ws, str(slow))
    assert time.monotonic() - t0 < 1.7


@pytest.mark.parametrize("loc", ["de_CH.UTF-8", "en_GB.UTF-8", "fr_FR.UTF-8"])
def test_a_live_session_is_counted_under_any_mac_language(ws, fake_orch, monkeypatch, loc):
    """fb20 (lane C): `ps -o lstart=` printed "Mo.  9 Nov. ..." under a non-English Mac language, the start time
    did not parse, the run looked like another process with the same pid, and Focus said "0 Running now"."""
    from orch_focus import livedata

    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    core_form = livedata._core_start(subprocess.run(  # what core writes in the claim record (UTC, ISO)
        ["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True, check=True
    ).stdout.strip())
    assert core_form
    monkeypatch.setenv("LC_ALL", loc)
    monkeypatch.setenv("LANG", loc)
    claim(ws, pid_started=core_form)
    v = build(ws, str(fake_orch))
    assert v["blocks"][0]["value"] == 1
