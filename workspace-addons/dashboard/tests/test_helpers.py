import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
HARNESS = Path(__file__).parent / "helpers_harness.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def call(fn, *args):
    out = subprocess.run(["node", str(HARNESS), str(WEB / "helpers.js"), json.dumps({"fn": fn, "args": list(args)})],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@node
@pytest.mark.parametrize("raw,want", [
    ("Created", "Ticket created"), ("Created under t_abc12345", "Created as a sub-ticket"),
    ("Edited due, owner", "Changed the due day and the owner"), ("Edited title", "Changed the title"),
    ("Asked q1, waiting", "Asked a question"), ("Answered q1: Yes", "Answered a question"),
    ("Status open -> active", "Moved to Doing"), ("Status active -> done", "Moved to Done"),
    ("Something the agent wrote", "Something the agent wrote")])
def test_history_lines_are_plain_words(raw, want):
    assert call("historyLine", {"text": raw}) == want


@node
def test_winning_answer_has_text_who_and_via():
    t = [{"id": "t_a", "questions": [{"id": "q1", "answer": "Travel", "answered_by": "human:Marco", "via": "phone"},
                                     {"id": "q2", "answer": None}]}]
    assert call("winningAnswer", t, "t_a", "q1") == {"text": "Travel", "who": "human:Marco", "via": "phone"}
    assert call("winningAnswer", t, "t_a", "q2") is None and call("winningAnswer", t, "t_x", "q1") is None


@node
def test_need_action_per_kind():
    a = lambda r: call("needAction", r)["label"]
    assert a({"kind": "question", "answer": {"options": []}}) == "Answer"
    assert a({"kind": "x-addon:ask", "answer": {"options": ["Yes"]}}) == "Review"
    assert a({"kind": "overdue-wait", "ticket": "t_a"}) == "Open"
    assert a({"kind": "x-addon:stopped", "tone": "bad", "ticket": "t_a"}) == "Run again"


@node
def test_agent_rows_working_needs_and_idle():
    tickets = [{"id": "t_a", "title": "A", "questions": [], "sessions": [{"agent": "claude", "last_used": "2026-11-03T10:00:00Z"}]},
               {"id": "t_b", "title": "B", "questions": [{"id": "q1", "answer": None}], "sessions": []},
               {"id": "t_c", "title": "C", "questions": [], "sessions": [{"agent": "codex", "last_used": "2026-11-03T10:00:00Z"}]}]
    runs = {"t_a": {"running": True, "state": "alive", "claim": {"agent": "claude", "started_at": "2026-11-06T07:00:00Z"}},
            "t_b": {"running": True, "state": "alive", "claim": {"agent": "gemini"}}}
    rows = call("agentRows", tickets, runs, 1793923200000)
    assert [(r["agent"], r["state"]) for r in rows] == [("gemini", "needs"), ("claude", "working"), ("codex", "idle")]


@node
def test_service_links_only_other_local_running_pages():
    s = [{"addon": "dashboard", "running": True, "url": "http://127.0.0.1:8420"},
         {"addon": "panel", "running": True, "url": "http://127.0.0.1:8500"},
         {"addon": "evil", "running": True, "url": "https://example.com"},
         {"addon": "off", "running": False, "url": "http://127.0.0.1:8600"}]
    assert call("serviceLinks", s, "http://127.0.0.1:8420") == [{"label": "panel", "url": "http://127.0.0.1:8500"}]


T = {"id": "t_a", "questions": [], "sessions": []}


@node
def test_agent_line_states_one_main_action():
    now = 1793923200000  # 2026-11-06
    line = lambda t, r=None, live=None: call("agentLine", t, r, now, live)
    w = line(T, {"running": True, "state": "alive", "claim": {"agent": "claude", "by": "human:Mia", "started_at": "2026-11-06T00:00:00Z"}})
    assert w["state"] == "working" and "started by Mia" in w["status"] and w["primary"]["op"] == "run.stop" and w["items"] == []
    w2 = line(T, {"running": True, "state": "alive", "claim": {"agent": "claude"}}, {"label": "focus", "url": "http://127.0.0.1:1"})
    assert w2["primary"]["op"] == "open" and w2["items"][0]["op"] == "run.stop"
    stuck = line(T, {"running": True, "state": "maybe-stale", "claim": {"agent": "claude"}})
    assert stuck["state"] == "stuck" and stuck["primary"] == {"label": "Start anyway", "op": "run.start", "args": {"ticket": "t_a", "take_over": True}}
    needs = line({**T, "questions": [{"id": "q1", "answer": None}]})
    assert needs["state"] == "needs" and needs["primary"]["label"] == "Answer"
    dead = line(T, {"running": False, "state": "dead", "claim": {"agent": "claude"}})
    assert dead["state"] == "failed" and dead["primary"]["label"] == "Try again" and dead["items"][0]["args"]["fresh"] is True
    resume = line({**T, "sessions": [{"agent": "claude", "last_used": "2026-11-03T10:00:00Z"}]})
    assert resume["state"] == "resume" and resume["status"] == "last worked 3 days ago" and resume["primary"]["label"] == "Continue"
    assert resume["items"][0]["label"] == "Start fresh"
    new = line(T)
    assert new["state"] == "new" and new["primary"]["label"] == "Start" and new["status"] == "not started yet"


@node
def test_tree_rows_children_counts_collapse_and_missing_parent():
    ts = [{"id": "t_p", "status": "open"}] + [{"id": f"t_c{i}", "status": "done" if i < 2 else "open", "parent": "t_p"} for i in range(5)] \
        + [{"id": "t_o", "status": "open", "parent": "t_gone"}]
    rows = call("treeRows", ts)
    assert rows[0]["children"] == 5 and rows[0]["done"] == 2 and rows[0]["depth"] == 0
    assert [r["late"] for r in rows[1:6]] == [False, False, False, True, True] and all(r["depth"] == 1 for r in rows[1:6])
    orphan = rows[-1]
    assert orphan["ticket"]["id"] == "t_o" and orphan["depth"] == 0 and orphan["parentMissing"] is True
    cyc = call("treeRows", [{"id": "t_a", "parent": "t_b"}, {"id": "t_b", "parent": "t_a"}])
    assert sorted(r["ticket"]["id"] for r in cyc) == ["t_a", "t_b"]


@node
def test_proof_mark_you_or_agent_says():
    assert call("proofMark", {"by": "human:Mia"})["label"] == "You"
    assert call("proofMark", {"by": "agent:claude"})["label"] == "Agent says" and call("proofMark", {})["mark"] == "○"
