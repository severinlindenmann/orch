"""Live sessions close by themselves (idle / waiting / ticket Done for an hour); ticket artifacts folder."""

import json
import os
import time

import pytest

from orch import config, runs, runs_live, tickets


def _ticket(run, title="Make a report"):
    return json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]


@pytest.fixture
def closed(monkeypatch):
    got = []
    monkeypatch.setattr(runs_live, "_close", lambda root, rec, interrupt: got.append(rec["ticket"]))
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)
    monkeypatch.delenv("ORCH_RUN_IDLE_SECONDS", raising=False)
    return got


def _live(proj, run, state, age_min):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": state, "since": runs._iso(time.time() - age_min * 60)}
    runs._write(proj, rec)
    return tid


@pytest.mark.parametrize(
    "state,age,shut",
    [
        ("idle", 61, True),
        ("idle", 30, False),
        ("attention", 61, True),
        ("attention", 30, False),
        ("working", 600, False),
    ],
)
def test_default_is_an_hour(proj, run, closed, state, age, shut):
    tid = _live(proj, run, state, age)
    assert runs_live.cleanup(proj) == ([tid] if shut else [])
    assert closed == ([tid] if shut else [])


def test_live_idle_minutes_is_configurable(proj, run, closed):
    tid = _live(proj, run, "idle", 6)
    runs_live.cleanup(proj)
    assert closed == []
    code, out, _ = run("config", "set", "workspace.live_idle_minutes", "5")
    assert code == 0 and "= 5" in out
    assert run("config", "get", "workspace.live_idle_minutes")[1].strip() == "5"
    assert runs_live.cleanup(proj) == [tid]
    for bad in ("0", "abc", "-3", "99999"):
        assert run("config", "set", "workspace.live_idle_minutes", bad)[0] != 0
    config.set_key(proj, "workspace", "live_idle_minutes", "soon")  # a hand-edited bad value is the default
    assert config.live_idle_minutes(proj) == 60


def test_a_ticket_done_for_an_hour_closes_its_session(proj, run, closed):
    tid = _live(proj, run, "idle", 1)  # idle only a minute
    runs_live.cleanup(proj)
    assert closed == []
    tickets.set_status(proj, tid, "done", "human:t")
    runs_live.cleanup(proj)
    assert closed == []  # Done just now
    p = tickets.ticket_path(proj, tid)
    t = json.loads(p.read_text())
    t["updated_at"] = runs._iso(time.time() - 61 * 60)
    p.write_text(json.dumps(t))
    assert runs_live.cleanup(proj) == [tid]


@pytest.mark.parametrize("change", ["state", "input"])
def test_idle_close_rechecks_under_the_lock(proj, run, closed, monkeypatch, change):
    """The run became busy, or a message came in, between the read and the close: it is not closed."""
    tid = _live(proj, run, "idle", 61)
    stale = runs_live.records(proj)
    if change == "state":
        rec = runs.read(proj, tid)
        runs_live._set_state(proj, tid, rec["run"], "working")
    else:
        runs.pending_add(proj, tid, "human:t", "message", "one more thing")
    monkeypatch.setattr(runs_live, "records", lambda root: stale)
    assert runs_live.cleanup(proj) == [] and closed == []


def test_a_closing_session_gets_no_more_input(proj, run, closed, monkeypatch):
    tid = _live(proj, run, "idle", 61)
    assert runs_live.cleanup(proj) == [tid]
    assert runs.read(proj, tid).get("closing")
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    pasted = []
    monkeypatch.setattr(runs_live, "tmux", lambda root, *a, **kw: pasted.append(a))
    runs.pending_add(proj, tid, "human:t", "message", "late")
    assert runs_live.deliver(proj, tid) == 0 and pasted == []
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["late"]  # kept for the next start


def test_a_failed_close_lets_input_in_again(proj, run, monkeypatch):
    tid = _live(proj, run, "idle", 61)
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)

    def boom(root, rec, interrupt):
        raise RuntimeError("busy")

    monkeypatch.setattr(runs_live, "_close", boom)
    assert runs_live.cleanup(proj) == []
    assert not runs.read(proj, tid).get("closing")


# ---------------------------------------------------------------- artifacts


def test_artifacts_dir_and_list(proj, run):
    tid = _ticket(run)
    assert run("ticket", "artifacts", tid, "--json")[1].strip() == "[]"
    code, out, _ = run("ticket", "artifacts-dir", tid)
    assert code == 0 and out.strip() == f".orch/tickets/{tid}/artifacts"
    d = proj / out.strip()
    assert d.is_dir()
    assert run("ticket", "artifacts-dir", tid)[0] == 0  # again: fine
    (d / "report.csv").write_bytes(b"a,b\n")  # 4 bytes on every system (text mode adds \r on Windows)
    (d / "sub").mkdir()
    (d / "sub" / "x.txt").write_text("hello")
    code, out, _ = run("ticket", "artifacts", tid, "--json")
    rows = json.loads(out)
    assert [r["name"] for r in rows] == ["report.csv", "sub/x.txt"]
    r = rows[0]
    assert set(r) == {"name", "size", "mtime", "path"} and r["size"] == 4
    assert r["path"] == f".orch/tickets/{tid}/artifacts/report.csv" and r["mtime"].endswith("Z")
    assert "report.csv" in run("ticket", "artifacts", tid)[1]


def test_artifacts_take_the_ticket_key(proj, run):
    tid = _ticket(run)
    key = json.loads(run("ticket", "show", tid, "--json")[1])["key"]
    assert run("ticket", "artifacts-dir", key.lower())[1].strip() == f".orch/tickets/{tid}/artifacts"


def test_artifacts_unknown_ticket_and_links(proj, run):
    assert run("ticket", "artifacts", "t_nope")[0] != 0
    tid = _ticket(run)
    d = proj / ".orch" / "tickets" / tid
    d.mkdir()
    (proj / "elsewhere").mkdir()
    (d / "artifacts").symlink_to(proj / "elsewhere")
    code, _, err = run("ticket", "artifacts-dir", tid)
    assert code != 0 and "link" in err


def test_artifacts_are_not_gitignored_and_can_be_proof(proj, run):
    from orch import skills

    assert not any("artifacts" in ln for ln in skills.GITIGNORE_LINES)
    tid = _ticket(run)
    run("check", "add", tid, "Report", "--by", "human:t")
    d = proj / run("ticket", "artifacts-dir", tid)[1].strip()
    (d / "report.pdf").write_bytes(b"%PDF")
    code, out, err = run("check", "done", tid, "c1", "--file", str(d / "report.pdf"), "--by", "human:t")
    assert code == 0, err


def test_the_start_prompt_and_skill_point_at_the_folder(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    p = runs.plan(proj, tid)["prompt"]
    assert f"orch ticket artifacts-dir {tid}" in p and "unless the person asked" in p
    from orch import skills

    text = (skills.packaged_skills_dir() / "orch" / "SKILL.md").read_text(encoding="utf-8")
    assert "orch ticket artifacts-dir" in text and "unless the person" in text


def test_init_prints_the_permission_mode_in_one_line(proj, run):
    code, out, _ = run("init", "--yes")
    assert code == 0
    assert [ln for ln in out.splitlines() if ln.startswith("Permissions")] == [
        "Permissions auto: agents work on their own and the tool checks risky steps "
        "(change: orch config set workspace.permissions ask|auto|full)"
    ]
