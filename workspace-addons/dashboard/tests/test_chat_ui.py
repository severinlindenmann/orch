"""Chat + Groups page contracts (pages/chat.js, chat.css): feature-detected groups, no VPN names, safe DOM, 44 px targets."""

import json
import re

from tests import webjs

JS = (webjs.WEB / "pages" / "chat.js").read_text(encoding="utf-8")
CSS = (webjs.WEB / "pages" / "chat.css").read_text(encoding="utf-8")


def test_page_is_wired_into_the_shell():
    app = (webjs.WEB / "app.js").read_text(encoding="utf-8")
    assert "chatPage()" in app and "navLink('#chat', 'Chat'" in app
    assert "function generalPage" not in webjs.all_js()
    index = (webjs.WEB / "index.html").read_text(encoding="utf-8")
    assert "pages/chat.js" in index and "pages/chat.css" in index


def test_groups_render_only_when_data_exists():
    assert "state?.groups?.hosted" in JS and "state?.groups?.joined" in JS
    for text in (
        "Done groups → History",
        "Search chats",
        "Search History",
        "Context cleared daily at 04:00",
        "is thinking…",
        "Members",
        "Remove from group",
        "Answer on your phone or in ",
    ):
        assert text in JS
    assert "'chat.say'" in JS and "'group.say'" in JS and "'group.remove'" in JS and "'group.add'" in JS
    assert "chat.group_" not in JS


def test_history_is_read_only_and_data_never_goes_through_innerhtml():
    assert "/api/chat/days" in JS and "/api/chat/day/" in JS
    assert "innerHTML" not in JS
    assert not re.search(r"vpn|netbird", JS, re.IGNORECASE)


def test_css_is_scoped_small_screens_and_touch_targets():
    assert "min-height:44px" in CSS
    assert "@media" in CSS and "prefers-reduced-motion" in CSS
    selectors = re.findall(r"(?m)^([^{@}/]+)\{", CSS)
    assert selectors and all(s.strip().startswith(".chat-page") for s in selectors)


def test_group_talk_is_marked_by_the_data_layer(ws):
    from orch_dashboard.data import load_tickets

    tdir = ws / ".orch" / "tickets"
    path = next(tdir.glob("t_weekly01.json"))
    t = json.loads(path.read_text())
    t["history"] = [
        {"at": "2026-11-08T10:00:00+01:00", "by": "agent:Home", "text": "hi", "via": "relay", "chat_message": True},
        {"at": "2026-11-08T10:01:00+01:00", "by": "human:me", "text": "yo", "via": "dashboard", "chat_message": True},
        {"at": "2026-11-08T10:01:30+01:00", "by": "agent:Home", "text": "Added a task", "via": "relay"},
        {"at": "2026-11-08T10:01:40+01:00", "by": "agent:Home", "text": "Claude started", "via": "dashboard"},
        {"at": "2026-11-08T10:02:00+01:00", "by": "agent:x", "text": "note", "via": "cli"},
    ]
    path.write_text(json.dumps(t))
    got = next(x for x in load_tickets(ws)[0] if x["id"] == "t_weekly01")["history"]
    assert [bool(e.get("in_chat")) for e in got] == [True, True, False, False, False]
    assert "in_chat === true" in JS and "rel' + 'ay" not in JS
