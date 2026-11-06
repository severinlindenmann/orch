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
