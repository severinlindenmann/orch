"""`orch diag report` layout and hiding, content switch, window, budgets, and incident capture."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from diag_fixtures import SECRET, claim_dead, reset_diag, stuck

from orch import cli_report, diag, diag_incident, diag_report, hider, relay, runs, tickets
from orch.errors import Refused
from orch.hider import Hider


@pytest.fixture
def proj(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    reset_diag(monkeypatch)
    monkeypatch.setattr(diag_incident, "_STATE", "incidents.json")
    return proj


@pytest.fixture
def hid():
    h = Hider({"api_key": SECRET})
    hider.register_hider(h)
    yield h
    hider.unregister_hider()


def files(folder: Path):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def test_report_layout_modes_and_summary_size(proj, hid):
    tid = stuck(proj, title=f"Pay with {SECRET}")
    claim_dead(proj, tid)
    diag.log("ticket.op_refused", "warn", root=proj, ticket=tid, op="done", guard="conflict")
    diag.error("test.boom", ValueError("x"), root=proj, ticket=tid)
    made = diag_report.make(proj, ticket=tid, note="stuck since 10:00", expected="Ready")
    f = Path(made["path"])
    assert (
        made["ref"].startswith("r-")
        and made["ref"].endswith(f"-{tid}")
        and f.parent == proj / ".orch/diag/reports"
    )
    got = files(f)
    for must in (
        "SUMMARY.md",
        "manifest.json",
        "timeline.jsonl",
        "errors.json",
        "checks.json",
        "state/tickets.json",
        "state/runs.json",
        "state/locks.json",
    ):
        assert must in got, got
    assert any(g.startswith("logs/") for g in got) and any(g.startswith("content/") for g in got)
    summary = (f / "SUMMARY.md").read_text()
    assert len(summary.encode()) < 20 * 1024
    assert "run_gone_ticket_working" in summary and "stuck since 10:00" in summary and "PROBLEM" in summary
    assert summary.index("## Checks") < summary.index("## Top errors") < summary.index("## Last")
    assert (f.stat().st_mode & 0o777) == 0o700 and all(((f / g).stat().st_mode & 0o777) == 0o600 for g in got)
    man = json.loads((f / "manifest.json").read_text())
    assert (
        man["schema"] == "orch.diag-report/1"
        and man["content"] is True
        and "run_gone_ticket_working" in man["problems"]
    )
    errs = json.loads((f / "errors.json").read_text())
    assert errs and errs[0]["count"] == 1 and errs[0]["type"] == "ValueError"


def test_summary_stays_under_20kb_with_huge_inputs(proj, hid):
    tid = stuck(proj)
    for i in range(300):
        diag.log("ticket.op_applied", "info", root=proj, ticket=tid, op="set", note="x" * 250, n=i)
    made = diag_report.make(proj, ticket=tid, note="n" * 5000, expected="e" * 5000)
    assert len((Path(made["path"]) / "SUMMARY.md").read_bytes()) < 20 * 1024


def test_content_off_has_no_content_folder_and_no_ticket_text(proj, hid):
    tid = stuck(proj, title="Secret plans for the export")
    made = diag_report.make(proj, ticket=tid, content=False)
    f = Path(made["path"])
    assert not (f / "content").exists()
    assert "Secret plans" not in "".join(p.read_text() for p in f.rglob("*") if p.is_file())
    on = Path(diag_report.make(proj, ticket=tid, content=True, now=time.time() + 120)["path"])
    assert "Secret plans" in (on / f"content/ticket-{tid}.json").read_text()


def test_secrets_are_hidden_in_every_file(proj, hid):
    tid = stuck(proj, title=f"key {SECRET} here")
    claim_dead(proj, tid)
    made = diag_report.make(proj, ticket=tid, note=f"token {SECRET}", expected=SECRET)
    f = Path(made["path"])
    for p in f.rglob("*"):
        if p.is_file():
            assert SECRET not in p.read_text(), p
    assert "[hidden" in (f / "SUMMARY.md").read_text()
    assert "[hidden" in (f / f"content/ticket-{tid}.json").read_text()


def test_no_hider_means_no_report(proj, monkeypatch):
    monkeypatch.setattr(diag, "_hider", lambda root: None)
    with pytest.raises(Exception, match="hidden"):
        diag_report.make(proj)
    assert not (proj / ".orch/diag/reports").exists() or not list((proj / ".orch/diag/reports").iterdir())


def test_window_starts_at_the_run_not_a_fixed_two_hours(proj, hid):
    tid = stuck(proj)
    claim_dead(proj, tid, minutes_ago=30)
    man = json.loads((Path(diag_report.make(proj, ticket=tid)["path"]) / "manifest.json").read_text())
    assert man["window"]["why"] == "start of the run"
    start = runs._parse(man["window"]["from"])
    assert abs(time.time() - start - 30 * 60) < 5
    man2 = json.loads(
        (
            Path(diag_report.make(proj, since="10m", now=time.time() + 120)["path"]) / "manifest.json"
        ).read_text()
    )
    assert man2["window"]["why"] == "--since 10m"


def test_timeline_keeps_per_source_order_and_logs_are_cut_to_the_window(proj, hid):
    tid = stuck(proj)
    for i in range(5):
        diag.log("test.step", "info", root=proj, ticket=tid, i=i)
    f = Path(diag_report.make(proj, ticket=tid, since="1h")["path"])
    rows = [json.loads(ln) for ln in (f / "timeline.jsonl").read_text().splitlines()]
    steps = [r["kv"]["i"] for r in rows if r["ev"] == "test.step"]
    assert steps == [0, 1, 2, 3, 4]
    assert all(r["source"] == "diag" for r in rows)
    old = Path(diag_report.make(proj, ticket=tid, since="1h", now=time.time() + 5 * 3600)["path"])
    assert not any(g.startswith("logs/") for g in files(old))


def test_report_writes_only_under_reports(proj, hid):
    tid = stuck(proj)
    claim_dead(proj, tid)
    before = {
        str(p): p.read_bytes() for p in (proj / ".orch").rglob("*") if p.is_file() and "diag" not in p.parts
    }
    diag_report.make(proj, ticket=tid)
    after = {
        str(p): p.read_bytes() for p in (proj / ".orch").rglob("*") if p.is_file() and "diag" not in p.parts
    }
    assert before == after


def test_symlinked_reports_folder_is_refused(proj, hid, tmp_path):
    d = proj / ".orch" / "diag"
    d.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.symlink(target, d / "reports")
    with pytest.raises(Exception, match="link"):
        diag_report.make(proj)
    assert not list(target.iterdir())


def test_cli_report(proj, hid, run):
    tid = stuck(proj)
    code, out, _ = run("diag", "report", "--ticket", tid, "--no-content", "--note", "hello", "--json")
    assert code == 0
    res = json.loads(out)
    assert Path(res["path"]).is_dir() and res["ref"].startswith("r-")
    assert not (Path(res["path"]) / "content").exists()


def _mark_ticketed(proj, *refs):
    d = proj / ".orch" / "diag"
    (d / diag_report.TICKETS_STATE).write_text(json.dumps({"seen": {r: {"ticket": "t_x"} for r in refs}}))


def test_a_full_debug_log_never_costs_a_report(proj, hid, monkeypatch):
    refs = [Path(diag_report.make(proj, now=time.time() + 120 * i)["path"]) for i in range(4)]
    (proj / ".orch" / "diag" / "2026-11-17-0.jsonl").write_bytes(b"x" * 5000)
    monkeypatch.setattr(diag, "MAX_TOTAL_BYTES", 100)  # the log is over its budget
    assert diag_report.prune(proj) == []
    assert all(r.exists() for r in refs)


def test_over_the_report_room_only_ticketed_reports_go_oldest_first(proj, hid, monkeypatch):
    refs = []
    for i in range(4):
        refs.append(Path(diag_report.make(proj, now=time.time() + 120 * i)["path"]))
        os.utime(refs[-1], (time.time() + i, time.time() + i))
    monkeypatch.setattr(diag_report, "REPORT_BYTES", 1)  # everything is over the room
    assert diag_report.prune(proj) == []  # no ticket yet: nothing may go
    _mark_ticketed(proj, refs[0].name, refs[2].name)
    assert diag_report.prune(proj) == [refs[0].name, refs[2].name]
    assert not refs[0].exists() and refs[1].exists() and refs[3].exists()
    assert [e for e in diag.read_events(proj) if e["ev"] == "diag.report_pruned"]


def test_report_problem_says_plainly_it_was_kept(proj, hid):
    res = cli_report.report(proj, "problem", "something broke", send=False)
    assert res["kept"] is True and Path(res["path"]).is_dir()
    text = cli_report._text(res)
    assert "is kept here until it becomes a ticket" in text and "saved here" not in text


def test_report_problem_refuses_when_the_report_is_gone(proj, hid, monkeypatch):
    monkeypatch.setattr(
        diag_report, "prune", lambda root: shutil.rmtree(next((proj / ".orch/diag/reports").iterdir())) or []
    )
    with pytest.raises(Refused, match="NOT kept"):
        cli_report.report(proj, "problem", "something broke", send=False)


def test_a_name_that_has_a_ticket_is_not_given_out_again(proj, hid):
    now = time.time()
    first = Path(diag_report.make(proj, now=now)["path"])
    _mark_ticketed(proj, first.name)
    shutil.rmtree(first)
    again = Path(diag_report.make(proj, now=now)["path"])
    assert again.name != first.name


# ------------------------------------------------------------ incidents


def test_incident_is_frozen_before_settle_orphan_changes_the_ticket(proj, hid):
    tid = stuck(proj)
    assert runs.settle_orphan(proj, tid) is True
    assert tickets.load(proj, tid)["status"] == "ready"  # the recovery ran
    (inc,) = list((proj / ".orch/diag/reports").glob("i-*"))
    state = json.loads((inc / "state/tickets.json").read_text())
    assert state["data"]["tickets"][tid]["status"] == "active"  # the frozen picture still shows it stuck
    man = json.loads((inc / "manifest.json").read_text())
    assert man["kind"] == "incident" and man["content"] is False and not (inc / "content").exists()
    assert "run_gone_ticket_working" in man["problems"]


def test_incident_dedupe_cooldown_and_cap(proj, hid):
    now = time.time()
    a = diag_incident.capture(proj, "x", fingerprint="fp1", now=now)
    assert a and diag_incident.capture(proj, "x", fingerprint="fp1", now=now + 60) is None  # cooling down
    assert diag_incident.capture(proj, "x", fingerprint="fp2", now=now + 61)  # another fingerprint
    assert diag_incident.capture(proj, "x", fingerprint="fp1", now=now + 16 * 60)  # cooldown over
    for i in range(25):
        diag_incident.capture(proj, "x", fingerprint=f"n{i}", now=now + 1000 + i * 120)
    assert len(list((proj / ".orch/diag/reports").glob("i-*"))) <= diag_report.INCIDENT_MAX


def test_incident_off_when_the_log_is_off(proj, hid):
    from orch import config

    config.set_diag_enabled(proj, False)
    diag.forget_settings()
    assert diag_incident.capture(proj, "x", fingerprint="f") is None


def test_same_delivery_failure_three_times_freezes_one_incident(proj, hid):
    for _ in range(2):
        relay.log_send_failure(proj, "proposal", ValueError("boom"))
    assert (
        not list((proj / ".orch/diag/reports").glob("i-*"))
        if (proj / ".orch/diag/reports").exists()
        else True
    )
    relay.log_send_failure(proj, "proposal", ValueError("boom"))
    assert len(list((proj / ".orch/diag/reports").glob("i-*"))) == 1


def test_a_crash_in_a_command_freezes_an_incident_and_still_raises(proj, hid, monkeypatch):
    from orch import cli

    (proj / ".orch" / "tickets").mkdir(exist_ok=True)
    monkeypatch.setattr(cli, "run", lambda args: (_ for _ in ()).throw(RuntimeError("kaboom")))
    monkeypatch.chdir(proj)
    with pytest.raises(RuntimeError):
        cli.main(["status"])
    assert len(list((proj / ".orch/diag/reports").glob("i-*"))) == 1


def test_a_crafted_src_cannot_write_outside_the_report_folder(proj, hid, tmp_path):
    d = proj / ".orch" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    evil = {"v": 1, "at": now, "ev": "test.evil", "lvl": "info", "src": "../../../../evil", "seq": 1}
    day = now[:10]
    (d / f"{day}.cli.1.jsonl").write_text(json.dumps(evil) + "\n")
    f = Path(diag_report.make(proj, since="1h")["path"])
    assert (f / "logs" / "unknown.jsonl").exists()
    assert not list(proj.rglob("evil*"))
    w = diag_report._Writer(proj, f, lambda t: t)
    with pytest.raises(Exception, match="outside"):
        w.put("../x.txt", "no")
