"""Focus reads live steps through `orch record tail --follow --json`, never from files (contracts/activity.md)."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from orch_focus import record
from orch_focus.board import Board
from orch_focus.record import RecordFeed, to_events

ROOT = Path(__file__).resolve().parents[3]
FAKE = ROOT / "workspace" / "tests" / "fakes" / "orch"
EX = ROOT / "contracts" / "examples" / "activity"
RUN, TICKET = "r_8k2m01", "t_inv7c2"


def example(name, **kw):
    e = json.loads((EX / name).read_text())
    e.update(kw)
    return e


def wait(feed, n=1, secs=15.0):
    got, end = [], time.time() + secs
    while len(got) < n and time.time() < end:
        got += feed.poll()
        time.sleep(0.05)
    return got


@pytest.fixture
def feed_for(monkeypatch, tmp_path):
    feeds = []
    monkeypatch.setenv("ORCH_FAKE_FOLLOW_PINGS", "0")

    def make(run=RUN, orch_bin=str(FAKE)):
        f = RecordFeed(tmp_path, orch_bin, run, TICKET)
        feeds.append(f)
        return f

    yield make
    for f in feeds:
        f.close()


def test_step_started_and_finished_become_board_steps():
    s = to_events(example("valid-step-started.json"), TICKET, RUN)
    assert [e["kind"] for e in s] == ["tool.start"] and s[0]["text"] == "Read report-2025-11.pdf"
    fin = example("valid-step-started.json", outcome={"ok": False, "error": "boom", "ms": 5})
    assert to_events(fin, TICKET, RUN)[0]["data"]["ok"] is False
    b = Board.from_events(s)
    assert b.snapshot()["step"] == "Read report-2025-11.pdf"


def test_other_kinds_and_bad_shapes_give_nothing_or_the_right_event():
    assert to_events({"kind": "task.start", "run": RUN}, TICKET, RUN) == []  # the ticket watcher makes these
    assert to_events({"kind": "key.use"}, TICKET, RUN) == []
    assert to_events({"nonsense": 1}, TICKET, RUN) == [] and to_events({"kind": "step"}, TICKET, RUN) == []
    st = to_events(example("valid-run-state-say.json", checked=True), TICKET, RUN)
    assert st and st[0]["kind"] == "run.state"
    # an unchecked line (a hook line, a line from before protection) never drives the run state
    assert to_events(example("valid-run-state-say.json", checked=False), TICKET, RUN) == []
    assert to_events(example("valid-run-state-say.json"), TICKET, RUN) == []


def test_text_is_hidden_again_before_it_reaches_the_page():
    e = example("valid-step-started.json", text="Run curl -H 'Authorization: Bearer abcdefghijklmnop1234'")
    assert "abcdefghijklmnop1234" not in json.dumps(to_events(e, TICKET, RUN))


def test_feed_follows_the_fake_orch_and_keeps_the_cursor(feed_for):
    f = feed_for()
    got = wait(f)
    assert got and all(e["run"] == RUN and e["ticket"] == TICKET for e in got)
    assert f.cursor and f.cursor.startswith("c")


def test_feed_refuses_a_run_id_that_is_not_one_and_a_missing_orch(feed_for):
    assert feed_for(run="../x").poll() == []
    assert feed_for(orch_bin=None).poll() == []


def test_a_broken_orch_gives_no_steps_and_no_crash(feed_for, tmp_path):
    bad = tmp_path / "nothing-here"
    f = feed_for(orch_bin=str(bad))
    assert f.poll() == []
    time.sleep(0.3)
    assert f.poll() == []


def test_garbled_lines_are_skipped_and_the_cursor_only_moves_on_good_lines(feed_for):
    f = feed_for(run=RUN)
    f._line(b"not json")
    f._line(b"[1]")
    f._line(
        json.dumps(
            {"type": "event", "cursor": "rc1.abc", "event": example("valid-step-started.json")}
        ).encode()
    )
    f._line(json.dumps({"type": "error", "error": "x", "cursor": "rc1.zzz"}).encode())
    assert f.cursor == "rc1.abc" and len(f.queue) == 1


def test_restart_passes_the_last_cursor(feed_for):
    f = feed_for()
    assert "--since" not in f._argv()
    f.cursor = "rc1.abc"
    assert f._argv()[-2:] == ["--since", "rc1.abc"] and "--follow" in f._argv()


def test_close_ends_the_followed_command(monkeypatch, tmp_path):
    started = []
    real = record._popen

    def spy(*a, **kw):
        p = real(*a, **kw)
        started.append(p)
        return p

    monkeypatch.setattr(record, "_popen", spy)
    sleeper = tmp_path / "orch"
    sleeper.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    sleeper.chmod(0o755)
    f = RecordFeed(tmp_path, str(sleeper), RUN, TICKET)
    f.poll()
    end = time.time() + 10
    while not started and time.time() < end:
        time.sleep(0.05)
    assert started
    f.close()
    assert started[0].poll() is not None
    assert not any(t.name == "focus-record" and t.is_alive() for t in threading.enumerate())


def test_the_view_shows_live_steps_from_the_record(server, ws, fake_orch, monkeypatch):
    """Through the real server: status says a run is on, the wrapper answers `record tail`, the board shows the step."""
    run = "r_start001"
    wrap = fake_orch.parent / "wrap"
    ev = example("valid-step-started.json", run=run, ticket="t_inv7c2ab", text="Read the March report")
    line = json.dumps({"type": "event", "cursor": "rc1.x", "event": ev})
    wrap.write_text(
        f"#!{sys.executable}\nimport os, sys, time\na = sys.argv[1:]\n"
        f"if a[:2] == ['record', 'tail']:\n    print({line!r}, flush=True)\n    time.sleep(30)\n"
        f"os.execv({str(fake_orch)!r}, [{str(fake_orch)!r}, *a])\n"
    )
    wrap.chmod(0o755)
    (fake_orch.parent / "status.json").write_text(
        json.dumps({"running": True, "claim": {"run": run, "agent": "claude", "mode": "oneshot"}})
    )
    server.tracker.orch_bin = str(wrap)
    from tests.test_server import req

    seen, end = None, time.time() + 15
    while time.time() < end:
        v = json.loads(req(server, "GET", "/api/t/t_inv7c2ab")[1])
        if v["board"]["step"]:
            seen = v["board"]["step"]
            break
        time.sleep(0.2)
    assert seen == "Read the March report"


def denial(**kw):
    e = example(
        "valid-step-started.json",
        kind="denial",
        text="Not allowed by this workspace",
        via="log",
        checked=True,
    )
    e["outcome"] = {"ok": False, "error": "Not allowed by this workspace", "ms": None}
    e.update(kw)
    return e


def test_a_denial_counts_only_from_a_collector_or_the_core():
    assert [x["kind"] for x in to_events(denial(via="log"), TICKET, RUN)] == ["denial"]
    assert [x["kind"] for x in to_events(denial(via="core"), TICKET, RUN)] == ["denial"]
    assert (
        to_events(denial(via="hook"), TICKET, RUN) == []
    )  # a forged hook line must not drive a permission prompt
    assert to_events(denial(via="job"), TICKET, RUN) == [] and to_events(denial(via=None), TICKET, RUN) == []


def test_lines_of_another_run_or_ticket_are_ignored():
    assert to_events(denial(run="r_other001"), TICKET, RUN) == []
    assert to_events(denial(ticket="t_other001"), TICKET, RUN) == []
    step = example("valid-step-started.json")
    assert to_events({**step, "run": "r_other001"}, TICKET, RUN) == []
    assert to_events({**step, "ticket": "t_other001"}, TICKET, RUN) == []
    assert to_events(step, TICKET, RUN)


def test_steps_carry_what_they_used_and_the_board_counts_each_use_once():
    skill = {
        "kind": "skill",
        "name": "newsletter-writing",
        "action": None,
        "source": "workspace",
        "version": None,
    }
    conn = {"kind": "mcp", "name": "Slack", "action": "search", "source": "harness", "version": None}
    evs = []
    for i, used in enumerate([skill, conn, conn, None]):
        e = example("valid-step-started.json", id=f"toolu_{i}", used=used)
        evs += to_events(e, TICKET, RUN)
        evs += to_events(
            {**e, "outcome": {"ok": True, "error": None, "ms": 3}}, TICKET, RUN
        )  # its end: same use
    snap = Board.from_events(evs).snapshot()
    assert [(u["kind"], u["name"], u["source"], u["count"]) for u in snap["used"]] == [
        ("mcp", "Slack", "harness", 2),
        ("skill", "newsletter-writing", "workspace", 1),
    ]
    assert snap["used"][0]["actions"] == ["search"]


def test_an_unknown_kind_or_source_is_not_a_label():
    odd = example(
        "valid-step-started.json",
        used={"kind": "key", "name": "k", "action": "env", "source": "x", "version": None},
    )
    assert "used" not in to_events(odd, TICKET, RUN)[0]["data"]
    src = example(
        "valid-step-started.json",
        used={"kind": "tool", "name": "Read", "action": None, "source": "weird", "version": None},
    )
    assert to_events(src, TICKET, RUN)[0]["data"]["used"]["source"] == "harness"


def test_helpers_keep_their_parent_and_stay_in_the_tree_when_finished():
    start = example(
        "valid-step-started.json",
        id="h1",
        kind="helper.start",
        agent="h_1",
        parent="main",
        via="log",
        checked=True,  # a line orch checked: only those open and close helpers
        used={"kind": "helper", "name": "x", "action": None, "source": "builtin", "version": None},
    )
    end = {**start, "kind": "helper.end", "outcome": {"ok": True, "error": None, "ms": 5}}
    snap = Board.from_events(to_events(start, TICKET, RUN) + to_events(end, TICKET, RUN)).snapshot()
    assert snap["helpers"] == [] and [(h["agent"], h["parent"], h["open"]) for h in snap["helper_tree"]] == [
        ("h_1", "main", False)
    ]


# Unit tests of the `files` list (shape of contracts/activity.md). The real writer and reader: test_focus_real_record.py.
def stepf(files, name="Read", i=0, **kw):
    used = {"kind": "tool", "name": name, "action": None, "source": "builtin", "version": None}
    return example("valid-step-started.json", id=f"toolu_f{i}", used=used, files=files, **kw)


def test_files_are_kept_only_when_they_are_workspace_relative_paths():
    from orch_focus.record import clean_files

    good = ["src/app.py", "budget-2026.xlsx", "a b/c.txt"]
    bad = ["/etc/passwd", "../x", "a/../b", "a\\b", "C:/x", "a\x00b", "", "x" * 261, 5, None]
    assert clean_files(good + bad) == good
    assert clean_files("src/app.py") == [] and clean_files(None) == []
    assert len(clean_files([f"f{i}.txt" for i in range(20)])) == 8


def test_the_board_tracks_files_read_and_changed_and_a_change_wins():
    evs = to_events(stepf(["a.txt", "b.txt"], "Read", 1), TICKET, RUN) + to_events(
        stepf(["a.txt"], "Edit", 2), TICKET, RUN
    )
    evs += to_events(stepf(["c.txt", "../evil"], "Bash", 3), TICKET, RUN)
    files = {f["path"]: f["how"] for f in Board.from_events(evs).snapshot()["files"]}
    assert files == {"a.txt": "changed", "b.txt": "read", "c.txt": "touched"}


def test_same_file_needs_two_tickets_and_a_change():
    from orch_focus.livecards import same_file

    c1 = {
        "ticket": "t_a",
        "agent": "Claude",
        "key": "PIL-1",
        "title": "x",
        "files": [{"path": "budget.xlsx", "how": "read"}, {"path": "only1.txt", "how": "changed"}],
    }
    c2 = {
        "ticket": "t_b",
        "agent": "Codex",
        "key": "PIL-2",
        "title": "y",
        "files": [{"path": "budget.xlsx", "how": "changed"}],
    }
    got = same_file([c1, c2])
    assert [
        (g["path"], [(t["key"], t["how"], t["ticket"], t["agent"], t["title"]) for t in g["tickets"]])
        for g in got
    ] == [
        ("budget.xlsx", [("PIL-1", "read", "t_a", "Claude", "x"), ("PIL-2", "changed", "t_b", "Codex", "y")])
    ]
    c2["files"][0]["how"] = "read"
    assert same_file([c1, c2]) == []  # two readers are not a clash


def test_the_board_remembers_each_agents_latest_step_for_the_tree():
    a = stepf(["a.txt"], "Read", 1, text="Read the plan")
    b = stepf([], "Bash", 2, text="Searched Slack", agent="h_1", parent="main")
    snap = Board.from_events(to_events(a, TICKET, RUN) + to_events(b, TICKET, RUN)).snapshot()
    assert snap["agent_now"] == {"main": "Read the plan", "h_1": "Searched Slack"}


def test_focus_checks_paths_the_way_the_core_writer_does():
    from orch.record_files import file_ok as core_ok

    from orch_focus.record import file_ok

    cases = ["a.txt", "a b/c.d", "ünï/x", "e\u0301.txt", "/x", "../x", "a/../b", "a\\b", "C:/x", "c:x", "~/x", "$HOME/x",
             "file:x", "a\x00b", "a\u200bb", "", "x" * 260, "x" * 261, "a//b", ".", "a/./b", 5, None]  # fmt: skip
    assert [file_ok(c) for c in cases] == [core_ok(c) for c in cases]


def test_an_unchecked_denial_or_a_before_protection_line_never_drives_the_board():
    assert to_events(denial(checked=False), TICKET, RUN) == []  # via log, but from before protection
    assert to_events(denial(checked=False, via="core"), TICKET, RUN) == []
    step = to_events(example("valid-step-started.json", via="log", checked=False), TICKET, RUN)
    assert step and step[0]["data"]["source"] == "hook"  # shown, but as the agent's word
    ok = to_events(example("valid-step-started.json", via="log", checked=True), TICKET, RUN)
    assert ok[0]["data"]["source"] == "log"


def test_problem_markers_of_orch_are_kept_not_dropped(tmp_path):
    f = RecordFeed(tmp_path, None, RUN, TICKET)
    f._line(
        json.dumps(
            {
                "type": "unavailable",
                "cursor": "rc1.x",
                "run": RUN,
                "status": "ok",
                "reason": "content",
                "message": "m",
                "changed": 2,
                "removed": 0,
            }
        ).encode()
    )
    assert f.notes["content"]["changed"] == 2 and f.cursor == "rc1.x"


def test_h_an_unchecked_helper_line_never_closes_a_helper_or_shows_done():
    start = example(
        "valid-step-started.json", kind="helper.start", via="log", checked=True, agent="h_1", parent="main"
    )
    end = example(
        "valid-step-started.json", kind="helper.end", via="hook", checked=False, agent="h_1", parent="main"
    )
    end["outcome"] = {"ok": None, "error": None, "ms": None}
    assert to_events(end, TICKET, RUN) == []  # not a helper end at all: only the agent's word
    assert [e["kind"] for e in to_events(start, TICKET, RUN)] == ["helper.start"]


def test_h_an_unchecked_tool_end_keeps_its_unknown_outcome():
    e = example(
        "valid-step-started.json", via="hook", checked=False, outcome={"ok": None, "error": None, "ms": None}
    )
    (got,) = to_events(e, TICKET, RUN)
    assert got["data"].get("ok") is None and got["data"]["confirmed"] is False
    checked = example(
        "valid-step-started.json", via="log", checked=True, outcome={"ok": True, "error": None, "ms": 1}
    )
    assert to_events(checked, TICKET, RUN)[0]["data"]["ok"] is True


def test_s3_unchecked_steps_say_why_and_checked_steps_say_nothing():
    name = "valid-step-started.json"
    old = to_events(example(name, checked=False, before_protection=True), TICKET, RUN)
    assert old[0]["data"]["source"] == "hook" and old[0]["data"]["before"] is True
    hook = to_events(example(name, checked=False), TICKET, RUN)
    assert "before" not in hook[0]["data"]
    ok = to_events(example(name, via="log", checked=True, before_protection=True), TICKET, RUN)
    assert "before" not in ok[0]["data"] and ok[0]["data"]["source"] == "log"


def test_s3_problems_are_orch_words_once_and_skip_stream_news(tmp_path):
    f = RecordFeed(tmp_path, None, RUN, TICKET)
    changed, unchecked = "Some records were changed outside orch.", "Some records cannot be checked."
    lines = (("content", changed), ("recovered", "Again."), ("unchecked", unchecked), ("content", changed))
    for reason, msg in lines:
        doc = {"type": "unavailable", "run": RUN, "status": "ok", "reason": reason, "message": msg}
        f._line(json.dumps(doc).encode())
    assert f.problems() == [changed, unchecked]
