import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from . import webjs

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
HARNESS = Path(__file__).parent / "helpers_harness.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def call(fn, *args):
    out = subprocess.run(
        ["node", str(HARNESS), str(WEB / "helpers.js"), json.dumps({"fn": fn, "args": list(args)})],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TZ": "UTC"},
    )
    return json.loads(out.stdout)


@node
@pytest.mark.parametrize(
    "raw,want",
    [
        ("Created", "Ticket created"),
        ("Created under t_abc12345", "Created as a sub-ticket"),
        ("Edited due, owner", "Changed the due day and the owner"),
        ("Edited title", "Changed the title"),
        ("Asked q1, waiting", "Asked a question"),
        ("Answered q1: Yes", "Answered a question"),
        ("Status open -> active", "Moved to Working"),
        ("Check c2 done", "Finished a task"),
        ("Status active -> done", "Moved to Done"),
        ("Patched status (status done -> open)", "Moved to Not started"),
        ("Something the agent wrote", "Something the agent wrote"),
    ],
)
def test_history_lines_are_plain_words(raw, want):
    assert call("historyLine", {"text": raw}) == want


@node
def test_winning_answer_has_text_who_and_via():
    t = [
        {
            "id": "t_a",
            "questions": [
                {"id": "q1", "answer": "Travel", "answered_by": "human:Marco", "via": "phone"},
                {"id": "q2", "answer": None},
            ],
        }
    ]
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
    tickets = [
        {
            "id": "t_a",
            "title": "A",
            "questions": [],
            "sessions": [{"agent": "claude", "last_used": "2026-11-03T10:00:00Z"}],
        },
        {"id": "t_b", "title": "B", "questions": [{"id": "q1", "answer": None}], "sessions": []},
        {
            "id": "t_c",
            "title": "C",
            "questions": [],
            "sessions": [{"agent": "codex", "last_used": "2026-11-03T10:00:00Z"}],
        },
    ]
    runs = {
        "t_a": {
            "running": True,
            "state": "alive",
            "claim": {"agent": "claude", "started_at": "2026-11-06T07:00:00Z"},
        },
        "t_b": {"running": True, "state": "alive", "claim": {"agent": "gemini"}},
    }
    rows = call("agentRows", tickets, runs, 1793923200000)
    assert [(r["agent"], r["state"]) for r in rows] == [
        ("gemini", "needs"),
        ("claude", "working"),
        ("codex", "idle"),
    ]


@node
def test_service_links_only_other_local_running_pages():
    s = [
        {"addon": "dashboard", "running": True, "url": "http://127.0.0.1:8420"},
        {"addon": "panel", "running": True, "url": "http://127.0.0.1:8500"},
        {"addon": "evil", "running": True, "url": "https://example.com"},
        {"addon": "off", "running": False, "url": "http://127.0.0.1:8600"},
    ]
    assert call("serviceLinks", s, "http://127.0.0.1:8420") == [
        {"label": "panel", "url": "http://127.0.0.1:8500"}
    ]


T = {"id": "t_a", "questions": [], "sessions": []}


@node
def test_agent_line_states_one_main_action():
    now = 1793923200000  # 2026-11-06
    line = lambda t, r=None, live=None: call("agentLine", t, r, now, live)
    w = line(
        T,
        {
            "running": True,
            "state": "alive",
            "claim": {"agent": "claude", "by": "human:Mia", "started_at": "2026-11-06T00:00:00Z"},
        },
    )
    assert (
        w["state"] == "working"
        and "started by Mia" in w["status"]
        and w["primary"]["op"] == "run.stop"
        and w["items"] == []
    )
    w2 = line(
        T,
        {"running": True, "state": "alive", "claim": {"agent": "claude"}},
        {"label": "focus", "url": "http://127.0.0.1:1"},
    )
    assert w2["primary"]["op"] == "open" and w2["items"][0]["op"] == "run.stop"
    stuck = line(T, {"running": False, "state": "maybe-stale", "claim": {"agent": "claude"}})
    assert stuck["state"] == "stuck" and stuck["primary"] == {
        "label": "Start anyway",
        "op": "run.start",
        "args": {"ticket": "t_a", "take_over": True},
    }
    needs = line({**T, "questions": [{"id": "q1", "answer": None}]})
    assert needs["state"] == "needs" and needs["primary"]["label"] == "Answer"
    dead = line(T, {"running": False, "state": "dead", "claim": {"agent": "claude"}})
    assert (
        dead["state"] == "failed"
        and dead["primary"]["label"] == "Try again"
        and dead["items"][0]["args"]["fresh"] is True
    )
    resume = line({**T, "sessions": [{"agent": "claude", "last_used": "2026-11-03T10:00:00Z"}]})
    assert (
        resume["state"] == "resume"
        and resume["status"] == "last worked 3 days ago"
        and resume["primary"]["label"] == "Continue"
    )
    assert resume["items"][0]["label"] == "Start fresh"
    new = line(T)
    assert new["state"] == "new" and new["primary"]["label"] == "Start" and new["status"] == "not started yet"


@node
def test_tree_rows_children_counts_collapse_and_missing_parent():
    ts = (
        [{"id": "t_p", "status": "open"}]
        + [{"id": f"t_c{i}", "status": "done" if i < 2 else "open", "parent": "t_p"} for i in range(5)]
        + [{"id": "t_o", "status": "open", "parent": "t_gone"}]
    )
    rows = call("treeRows", ts)
    assert rows[0]["children"] == 5 and rows[0]["done"] == 2 and rows[0]["depth"] == 0
    assert [r["late"] for r in rows[1:6]] == [False, False, False, True, True] and all(
        r["depth"] == 1 for r in rows[1:6]
    )
    orphan = rows[-1]
    assert orphan["ticket"]["id"] == "t_o" and orphan["depth"] == 0 and orphan["parentMissing"] is True
    cyc = call("treeRows", [{"id": "t_a", "parent": "t_b"}, {"id": "t_b", "parent": "t_a"}])
    assert sorted(r["ticket"]["id"] for r in cyc) == ["t_a", "t_b"]


@node
def test_ago_says_just_now_under_a_minute():
    now = 1_762_437_600_000  # 2025-11-06T14:00:00Z
    assert call("ago", "2025-11-06T13:59:40Z", now) == "just now"
    assert call("ago", "2025-11-06T13:55:00Z", now) == "5 min ago"
    assert call("ago", "not a date", now) == ""


@node
def test_a_file_proof_shows_its_name_and_size():
    ev = {"type": "file", "ref": ".orch/tickets/t_x/evidence/hello.txt", "text": "1 KB"}
    assert call("fileProofLabel", ev) == "hello.txt · 1 KB"
    assert call("fileProofLabel", {**ev, "title": "Q3 chart"}) == "Q3 chart · 1 KB"
    assert call("fileProofLabel", {"type": "file", "ref": "out/a.png"}) == "a.png"


@node
def test_a_file_proof_shows_when_it_was_added():
    now = 1793980800000  # 2026-11-06T16:00:00Z
    ev = {"type": "file", "ref": "evidence/hello.txt", "text": "1 KB", "at": "2026-11-06T16:05:00Z"}
    assert call("fileProofLabel", ev, now) == "hello.txt · 1 KB · today 16:05"
    assert (
        call("fileProofLabel", {**ev, "at": "2026-11-05T09:12:00Z"}, now)
        == "hello.txt · 1 KB · yesterday 09:12"
    )
    assert (
        call("fileProofLabel", {**ev, "at": "2026-10-30T09:12:00Z"}, now) == "hello.txt · 1 KB · 30 Oct 09:12"
    )
    assert (
        call("fileProofLabel", {**ev, "at": "2025-12-24T07:00:00Z"}, now)
        == "hello.txt · 1 KB · 24 Dec 2025 07:00"
    )
    assert call("fileProofLabel", {**ev, "at": "nonsense"}, now) == "hello.txt · 1 KB"
    assert call("fileProofLabel", {k: v for k, v in ev.items() if k != "at"}, now) == "hello.txt · 1 KB"


@node
def test_proof_mark_you_or_agent_says():
    assert call("proofMark", {"by": "human:Mia"})["label"] == "You"
    assert (
        call("proofMark", {"by": "agent:claude"})["label"] == "Agent says"
        and call("proofMark", {})["mark"] == "○"
    )


@node
def test_tree_children_follow_creation_order_not_list_order():
    ts = [
        {"id": "t_p", "created_at": "2026-11-01T00:00:00Z"},
        {"id": "t_c3", "parent": "t_p", "created_at": "2026-11-03T00:00:00Z"},
        {"id": "t_c1", "parent": "t_p", "created_at": "2026-11-01T01:00:00Z"},
        {"id": "t_c2", "parent": "t_p", "created_at": "2026-11-02T00:00:00Z"},
    ]
    assert [r["ticket"]["id"] for r in call("treeRows", ts)] == ["t_p", "t_c1", "t_c2", "t_c3"]


@node
def test_service_link_port_has_one_to_five_digits():
    ok = {"addon": "panel", "running": True, "url": "http://127.0.0.1:8"}
    bad = {"addon": "panel2", "running": True, "url": "http://127.0.0.1:123456"}
    assert [r["label"] for r in call("serviceLinks", [ok, bad], "http://127.0.0.1:1")] == ["panel"]


@node
def test_flush_pending_sends_an_answer_in_its_undo_window():
    js = """
const H = require(process.argv[1]); const sent = [];
const mk = phase => { let st = {phase, answer: 'Yes'}; return {getState: () => st, reset() { st = {phase: 'idle'}; }}; };
const n = H.flushPending([{state: mk('pending'), send: a => sent.push(a)}, {state: mk('idle'), send: a => sent.push('bad')},
                          {state: mk('sending'), send: a => sent.push('bad')}]);
console.log(JSON.stringify([n, sent]));
"""
    out = subprocess.run(
        ["node", "-e", js, str(WEB / "helpers.js")], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out) == [1, ["Yes"]]


@node
def test_agent_line_run_states_starting_background_stopped():
    now = 1793923200000
    link = {"label": "focus", "url": "#open/focus/t/t_a"}
    run = {
        "running": True,
        "state": "alive",
        "claim": {"agent": "claude", "mode": "live", "live": {"state": "starting", "since": "x"}},
    }
    w = call("agentLine", T, run, now, link)
    assert w["state"] == "starting" and w["status"] == "Starting…" and w["primary"]["op"] == "open"
    run = {"running": True, "state": "alive", "claim": {"agent": "mine", "mode": "oneshot"}}
    w = call("agentLine", T, run, now, link)
    assert (
        w["state"] == "background"
        and "no live view" in w["status"]
        and w["primary"]["label"] == "Watch in focus"
    )


@node
def test_agent_line_with_the_status_shapes_core_really_returns():
    now = 1793923200000
    t = {**T, "sessions": [{"agent": "claude", "last_used": "2026-11-06T00:00:00Z"}]}
    # `orch run status --json`: running is state == alive; a stale claim has running false; a stop releases the claim
    stale = call(
        "agentLine",
        t,
        {
            "ticket": "t_a",
            "running": False,
            "state": "maybe-stale",
            "claim": {"agent": "claude", "mode": "live"},
        },
        now,
        None,
    )
    assert stale["state"] == "stuck" and stale["primary"]["args"]["take_over"] is True
    after_stop = call("agentLine", t, {"ticket": "t_a", "running": False, "pending": 0}, now, None)
    assert (
        after_stop["state"] == "resume"
        and after_stop["status"].startswith("last worked")
        and after_stop["primary"]["label"] == "Continue"
    )
    dead = call(
        "agentLine",
        t,
        {"ticket": "t_a", "running": False, "state": "dead", "claim": {"agent": "claude"}},
        now,
        None,
    )
    assert dead["state"] == "failed"


@node
def test_history_lines_name_the_task_and_the_addon():
    tasks = [{"id": "c1", "text": "Ask about the currency"}]
    assert call("historyLine", {"text": "Added check c1"}, tasks) == "Added a task: Ask about the currency"
    assert call("historyLine", {"text": "Check c1 done"}, tasks) == "Finished a task: Ask about the currency"
    assert call("historyLine", {"text": "Set ext.automation"}) == "Updated Automation settings"
    assert call("historyLine", {"text": "Removed ext.automation.repeat"}) == "Removed Automation settings"


@node
def test_last_worked_just_now_has_no_ago():
    from datetime import UTC, datetime

    now = 1793923200000
    used = datetime.fromtimestamp(now / 1000 - 20, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # 20 s earlier
    t = {"id": "t_a", "questions": [], "sessions": [{"agent": "claude", "last_used": used}]}
    assert call("agentLine", t, None, now)["status"] == "last worked just now"


@node
def test_a_live_session_waiting_for_a_message_is_idle_not_working():
    now = 1793923200000
    live = {
        "agent": "claude",
        "mode": "live",
        "by": "human:lume",
        "started_at": "2026-11-06T00:00:00Z",
        "live": {"state": "idle", "since": "2026-11-06T00:05:00Z"},
    }
    run = {"running": True, "state": "alive", "claim": live}
    w = call("agentLine", T, run, now, {"label": "Focus", "url": "#open/focus/t/t_a"})
    assert w["state"] == "idle" and "waiting for a message" in w["status"] and w["primary"]["op"] == "open"
    rows = call("agentRows", [T], {"t_a": run}, now)
    assert rows[0]["state"] == "idle" and rows[0]["since"] == "2026-11-06T00:05:00Z"


@node
def test_an_agent_that_is_starting_is_a_starting_row_not_idle_or_lost():
    """4A: the live state 'starting' shows as its own row so the Home header can say '1 agent starting'."""
    run = {"running": True, "state": "alive", "claim": {"agent": "claude", "live": {"state": "starting"}}}
    rows = call("agentRows", [T], {"t_a": run}, 1793923200000)
    assert [(r["agent"], r["state"], r["ticket"]) for r in rows] == [("claude", "starting", "t_a")]


def test_ticket_rows_use_one_status_chip_and_inline_next_step():
    src = webjs.all_js()
    tree = src[src.index("function treeBranch") : src.index("let ticketView")]
    assert tree.count("ticketAttentionChip(t)") == 1  # the one chip: Needs you (yellow) or the status word
    assert "ticketNext(t)" in tree and "ticketMenu(t, 'tree')" in tree
    assert "activity(t," not in tree


def test_home_counts_a_starting_ticket_and_the_sidebar_badge_has_words():
    src = webjs.all_js()
    assert "working-now" in src and "Getting started…" in src
    assert "needsYou(needsList().length)" in src  # 5A: the badge says what it counts


@node
def test_cron_in_plain_words():
    for cron, words in [
        ("30 7 * * *", "Every day at 07:30"),
        ("0 9 * * 1-5", "Weekdays at 09:00"),
        ("15 18 * * 5", "Every Friday at 18:15"),
        ("*/2 * * * *", "Every 2 minutes"),
        ("5 * * * *", "Every hour at :05"),
        ("0 8 1 * *", "Every month on day 1 at 08:00"),
        ("0 8 * 1 *", "0 8 * 1 *"),
        ("nonsense", "nonsense"),
    ]:
        assert call("cronHuman", cron) == words


@node
def test_phone_text_is_split_into_readable_parts():
    tid = "t_abc123456"
    text = "\n".join(
        [
            "From Anna: Look at this",
            'Voice message (de-CH): "Das Dach ist kaputt"',
            f"Photo: .orch/tickets/{tid}/files/roof.jpg",
            f"Voice recording: .orch/tickets/{tid}/files/v.m4a",
            f"File: .orch/tickets/{tid}/files/a.pdf",
            "Location: 47.37690, 8.54170 (Office) - https://maps.apple.com/?ll=47.3769%2C8.5417&q=Office",
            "Feedback on Report (a1b2): changes wanted",
            '  1. "Total": too high',
            "  (+3 more comments not shown)",
            "Photo x.jpg: could not be downloaded.",
        ]
    )
    r = call("phoneParts", text, tid)
    assert r["who"] == "Anna" and r["text"] == "Look at this"
    kinds = [p["type"] for p in r["parts"]]
    assert kinds == ["voice", "photo", "sound", "file", "location", "feedback", "pin", "note"]
    assert r["parts"][0]["transcript"] == "Das Dach ist kaputt" and r["parts"][1]["name"] == "roof.jpg"
    assert (
        r["parts"][4]["label"] == "Office"
        and r["parts"][5]["rev"] == "a1b2"
        and r["parts"][5]["approve"] is False
    )
    assert r["parts"][6] == {"type": "pin", "n": "1", "where": '"Total"', "said": "too high"}


@node
def test_phone_text_with_only_a_voice_or_a_thumbs_up_and_foreign_files():
    tid = "t_abc123456"
    r = call("phoneParts", 'From Ben: Voice message (en): "hi"', tid)
    assert r["text"] == "" and r["parts"][0]["type"] == "voice"
    r = call("phoneParts", "From Ben: Feedback on Page: \U0001f44d Looks good", tid)
    assert r["parts"][0]["approve"] is True
    r = call(
        "phoneParts", "From Ben: File: .orch/tickets/t_other/files/x.txt", tid
    )  # another ticket's folder is never opened
    assert r["parts"] == [] and r["text"].startswith("File:")
    assert call("phoneParts", "Edited the title", tid) is None
    r = call("phoneParts", "From Ben: Location: 1.0, 2.0 - https://evil.example/x", tid)
    assert r["parts"] == [] and r["text"].startswith("Location")


@node
def test_pins_with_quotes_and_overflow_note_and_sound_and_failed_download():
    tid = "t_abc123456"
    text = "\n".join(
        [
            "From Anna: hi",
            '  1. "say "no" now": fix it',
            "  2. page 3: wrong",
            "  (+3 more comments not shown)",
            f"Voice recording: .orch/tickets/{tid}/files/v.m4a",
            "File x.pdf: could not be downloaded.",
        ]
    )
    r = call("phoneParts", text, tid)
    assert [p["type"] for p in r["parts"]] == ["pin", "pin", "sound", "note"]
    assert r["parts"][0]["where"] == '"say "no" now"' and r["parts"][0]["said"] == "fix it"
    assert r["parts"][1]["where"] == "page 3" and r["parts"][2]["name"] == "v.m4a"


@node
def test_first_run_note_is_not_shown_as_an_answer():
    assert call("historyLine", {"text": "Answered q1: Hi"}) == "Answered a question"
    first = "Answered Claude's first-run screens (theme, notes, folder trust)."
    assert call("historyLine", {"text": first}) == first


@node
@pytest.mark.parametrize(
    "status,word",
    [
        ("open", "Not started"),
        ("ready", "Not started"),
        ("active", "Working"),
        ("waiting", "Needs you"),
        ("review", "Ready for review"),
        ("done", "Done"),
    ],
)
def test_all_status_words(status, word):
    assert call("historyLine", {"text": f"Status open -> {status}"}) == "Moved to " + word


@node
@pytest.mark.parametrize(
    "why,want",
    [
        (
            "Claude wants a login. Open the live session to finish it: orch run attach PIL-2",
            "Claude needs you to sign in",
        ),
        (
            "Claude shows its security notes. Open the live session to go on: orch run attach PIL-2",
            "Claude shows its security notes",
        ),
        ("Open the live session to see why: orch run attach t_ab12", ""),
        ("Waiting for your OK", "Waiting for your OK"),
    ],
)
def test_plain_why_has_no_command_text(why, want):
    got = call("plainWhy", why, "Claude")
    assert got == want and "orch run" not in got


@node
@pytest.mark.parametrize(
    "status,live,want",
    [
        ("active", "attention", "waiting"),
        ("active", "working", "active"),
        ("active", None, "active"),
        ("review", "attention", "review"),
    ],
)
def test_a_ticket_that_cannot_go_on_is_waiting_not_working(status, live, want):
    run = {"running": True, "claim": {"live": {"state": live}}} if live else None
    assert call("shownStatus", {"status": status}, run) == want


@node
@pytest.mark.parametrize(
    "ticket,live,want",
    [
        ({"questions": [{"answer": None}]}, None, True),
        ({"questions": [{"answer": "Yes"}]}, None, False),
        ({}, "attention", True),
        ({}, "working", False),
    ],
)
def test_one_chip_while_a_question_is_open(ticket, live, want):
    run = {"claim": {"live": {"state": live}}} if live else None
    assert call("showsAnswerChip", ticket, run) is want


def test_the_move_to_control_is_a_visible_labelled_button():
    """6A: one visible "Move to" button with four places; no chevron-only summary, no jargon in the choices."""
    src = webjs.all_js()
    assert "status-sum-icon" not in src
    assert "'Move to'" in src
    assert [w for _, w in node_value("MOVE_CHOICES")] == ["Not started", "Working", "Ready for review", "Done"]
    assert "Backlog" not in src


@node
@pytest.mark.parametrize(
    "counts,want",
    [
        ({"open": 0, "ready": 0, "active": 2, "done": 1}, "active"),
        ({"open": 3, "active": 2}, "open"),
        ({"open": 0, "ready": 0}, "open"),
        ({}, ""),
    ],
)
def test_first_column_with_tickets(counts, want):
    assert call("firstColumnWithTickets", counts) == want


@node
@pytest.mark.parametrize("label,n,want", [("Working", 2, "Working 2"), ("Backlog", 0, "Backlog")])
def test_column_chip_label(label, n, want):
    assert call("columnChipLabel", label, n) == want


@node
def test_question_preview_is_one_short_line_of_the_open_question():
    t = {"questions": [{"answer": "Yes", "text": "old"}, {"answer": None, "text": "Which   date\nfor launch?"}]}
    assert call("questionPreview", t) == "Which date for launch?"
    assert call("questionPreview", {"questions": [{"answer": "x", "text": "q"}]}) == ""
    assert call("questionPreview", {}) == ""
    long = call("questionPreview", {"questions": [{"answer": None, "text": "w" * 200}]})
    assert len(long) == 90 and long.endswith("\u2026")


@node
def test_agent_line_waiting_text_has_no_command():
    run = {"running": True, "claim": {"agent": "claude", "live": {"state": "attention",
           "why": "Claude wants a login. Open the live session to finish it: orch run attach PIL-3"}}}
    line = call("agentLine", {"id": "t1"}, run, 0, None)
    assert line["status"] == "Claude needs you to sign in" and "orch run" not in line["status"]


def test_ticket_screens_use_plain_wording_and_one_chip():
    src = webjs.all_js()
    assert "No tickets are being worked on." in src and "No agent is working right now" not in src
    assert "plainWhy(question" in src  # Needs-you rows carry no command text
    assert "seconds + ' s ago'" not in src  # one calm time format
    assert "'Not chosen yet'" not in src.split("const agent = window.DashHelpers.agentLabel")[1].split("\n")[0]  # one label source
    assert "Ideas to plan" in src and "Finished work" in src
    assert "hideStatus" not in src and "'Needs you'" in src  # 10A: short board chip; 7A: no chip beside the banner


@node
def test_unique_needs_counts_each_question_once():
    rows = [
        {"id": "core:q:t_1:q1", "ticket": "t_1", "answer": {"question": "q1"}},
        {"id": "addon:q:t_1:q1", "ticket": "t_1", "answer": {"question": "q1"}},
        {"id": "core:q:t_1:q2", "ticket": "t_1", "answer": {"question": "q2"}},
        {"id": "core:down:x", "ticket": None},
    ]
    assert [r["id"] for r in call("uniqueNeeds", rows)] == ["core:q:t_1:q1", "core:q:t_1:q2", "core:down:x"]
    assert call("uniqueNeeds", None) == []


@node
def test_in_needs_only_for_listed_questions():
    rows = [{"id": "a", "ticket": "t_1", "answer": {"question": "q1"}}, {"id": "b", "ticket": "t_2"}]
    assert call("inNeeds", rows, "t_1") is True
    assert call("inNeeds", rows, "t_2") is False
    assert call("inNeeds", rows, "t_3") is False


@node
@pytest.mark.parametrize("n,want", [(0, "0 need you"), (1, "1 needs you"), (2, "2 need you")])
def test_needs_you_count_words_match_the_phone(n, want):
    assert call("needsYou", n) == want


def test_groups_follow_the_lifecycle_and_old_phrases_are_gone():
    src = webjs.all_js()
    assert [w for _, w in node_value("STATUS_CHOICES")] == [
        "Not started", "Working", "Needs you", "Ready for review", "Done"
    ]
    assert "question needs you" not in src and "questions need you" not in src


def node_value(name):
    out = subprocess.run(
        ["node", "-e", f"console.log(JSON.stringify(require(process.argv[1]).{name}))", str(WEB / "helpers.js")],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


@node
def test_one_label_per_status_single_sourced():
    """fb12: every label site reads the words from helpers.js; no second map of status words in app.js."""
    src = webjs.all_js()
    for word in ("Ready to start", "Backlog"):
        assert word not in src and word not in (WEB / "helpers.js").read_text()
    # Lifecycle step names are separate from status labels.
    src = src.split("function ticketStepState")[0] + src.split("function ticketStepper")[1]
    for pair in ("open:'Not started'", "active:'Working'", "review:'Ready for review'", "done:'Done'"):
        assert pair not in src.replace(" ", "")
    words = node_value("STATUS_WORD")
    assert words["ready"] == words["open"] == "Not started" and words["waiting"] == "Needs you"
    assert all(w in src for w in ("DashHelpers.statusWord", "DashHelpers.STATUS_CHOICES", "DashHelpers.MOVE_CHOICES"))
    assert [s for s, _ in node_value("STATUS_CHOICES")] == node_value("STATUS_ORDER")
    assert call("columnOf", "ready") == "open" and call("columnOf", "review") == "review"


def test_home_row_is_one_link_and_the_review_chip_shows_once():
    src = webjs.all_js()
    css = (WEB / "style.css").read_text()
    assert ".ticket-row h3 a::after" in css and "position:absolute;inset:0" in css
    assert ".ticket-row .status-menu" in css  # Move to stays clickable above the row link
    assert "'Ready for your review'" not in src
    assert "['head', 'board'].includes(where)" in src


@node
def test_review_ticket_without_run_offers_no_start():
    w = call("agentLine", {"id": "t_a", "status": "review"}, None, 0, None)
    assert w["primary"] is None and w["items"] == [] and "Start" not in w["status"]
    assert call("agentLine", {"id": "t_a", "status": "active"}, None, 0, None)["primary"]["label"] == "Start"
    src = webjs.all_js()
    assert "line.primary && !['answer', 'open'].includes(line.primary.op)" in src
    assert "!['done', 'review'].includes(t.status) ? agentBar(t) : null" in src


def test_ui2_small_bugs_in_markup_and_css():
    app = webjs.all_js()
    css = (WEB / "style.css").read_text()
    mm = (WEB / "mobile-mode.js").read_text()
    html = (WEB / "index.html").read_text()
    # 3: an open-page row is the link alone, not "Focus page | Focus page"
    assert "r.format === 'open-page' ? h('dd', {className:'addon-page'}, v)" in app
    # 2: the sidebar colour and the modal dim layer fill the viewport
    assert "background:linear-gradient(to right,var(--sidebar)" in css and "body:has(dialog[open]:modal){overflow:hidden}" in css
    # 4: the end time never wraps off alone at 720; two lines only below 480
    assert "mm-desc" in mm and ".mm-bar.live{flex-wrap:nowrap}" in css and "@media(max-width:480px){.mm-bar.live{flex-wrap:wrap}" in css
    # 6: a skeleton is in the page before the first data arrives
    assert 'class="loading-home"' in html and 'aria-busy="true"' in html


@node
def test_history_line_shows_names_not_actor_ids():
    line = call("historyLine", {"text": "agent:claude finished the work and moved it to Review"}, [])
    assert line == "Claude finished the work and moved it to Review"


@node
def test_plain_names_and_history_dedupe():
    assert call("plainNames", "agent:claude finished it, human:Mia agreed") == "Claude finished it, Mia agreed"
    at = "2026-11-08T08:00:00Z"
    entries = [
        {"at": at, "by": "agent:claude", "text": "Check c1 done"},
        {"at": "2026-11-08T08:00:20Z", "by": "agent:claude", "text": "Finished a task: Write the export"},
        {"at": "2026-11-08T09:30:00Z", "by": "agent:claude", "text": "Finished a task: Write the export"},
    ]
    kept = call("dedupeHistory", entries, [{"id": "c1", "text": "Write the export"}])
    assert [e["at"] for e in kept] == ["2026-11-08T08:00:00Z", "2026-11-08T09:30:00Z"]
    assert len(kept) == 2
    src = webjs.all_js() + (WEB / "blocks.js").read_text()
    assert "plainNames" in src and "dedupeHistory" in src  # ticket history still uses both; Home no longer repeats it


@node
def test_footer_shows_the_relay_connection():
    on = {"settings": {"addons": [{"name": "relay", "active": True, "detail": {"connected": True}}]}}
    assert call("footerState", on, False) == "Connected"
    off = {"settings": {"addons": [{"name": "relay", "active": True, "detail": {"connected": False}}]}}
    assert call("footerState", off, False) == "Not connected yet"
    assert call("footerState", {"settings": {"addons": []}}, False) == "Local workspace"
    assert call("footerState", on, True) == "Shared copy"
    assert "NetBird" not in (WEB / "helpers.js").read_text()


@node
@pytest.mark.parametrize("status,word", [
    ("open", "Not started"), ("ready", "Not started"), ("active", "Working"),
    ("waiting", "Needs you"), ("review", "Ready for review"),
    ("done", "Done"), ("dropped", "Dropped"),
])
@pytest.mark.parametrize("started", [None, False, True, 1])
def test_status_words_started(status, word, started):
    expected = "Paused" if status in ("open", "ready") and started is True else word
    assert call("statusWord", status, started) == expected
    assert call("columnOf", "ready") == "open"


@node
def test_failed_agent_start_is_plain_with_a_retry():
    now = 1793923200000
    ref = "The agent could not be started: [Errno 2] No such file or directory: 'claude'"
    t = {
        "id": "t_a",
        "status": "waiting",
        "questions": [],
        "sessions": [],
        "waiting_on": {"kind": "external", "ref": ref, "start": True},
    }
    settings = {"agents": [{"name": "claude", "label": "Claude", "chosen": True}]}
    w = call("agentLine", t, None, now, None, settings)
    assert w["state"] == "failed" and w["startFailed"] is True
    assert w["status"] == "Claude could not start: the claude program was not found"
    assert w["primary"] == {"label": "Retry", "op": "run.start", "args": {"ticket": "t_a"}}
    assert "Errno" not in w["status"]
    assert call("startFailure", {**t, "status": "active"}, None, settings) is None
    t["waiting_on"] = {"kind": "question", "ref": "q1"}
    assert call("startFailure", t, None, settings) is None
    assert call("plainStartReason", "The agent did not start") == "it did not start"
    assert call("plainStartReason", "[Errno 13] Permission denied: '/x/claude'") == "it is not allowed to run"


@node
def test_start_reason_never_shows_paths_commands_or_secrets():
    r = lambda ref: call("plainStartReason", ref)
    assert r("The agent could not be started: [Errno 2] No such file or directory: '/usr/local/bin/claude'") == (
        "the claude program was not found"
    )
    assert r("[Errno 2] No such file or directory: '/x/a b; rm -rf /'") == "it did not start"
    for raw in (
        "boom: ghp_abcdefghijklmnopqrstuvwxyz0123 at /Users/me/secret/dir",
        "claude --token sk-live-abcdefabcdefabcdef exited 1",
        "",
    ):
        assert r(raw) == "it did not start"
