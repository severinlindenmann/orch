"""Chat + Groups page contracts (pages/chat.js, chat.css): feature-detected groups, no VPN names, safe DOM, 44 px targets."""

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
    assert (
        "Array.isArray(state.chat?.groups)" in JS
        or "Array.isArray(state?.chat?.groups)" in JS
        or "chat?.groups" in JS
    )
    for text in (
        "Done groups → History",
        "Search chats",
        "Search History",
        "Context cleared daily at 04:00",
        "is thinking…",
        "Members",
        "Remove from group",
        "Allow once",
        "Answer on your phone or in ",
    ):
        assert text in JS
    assert "'chat.say'" in JS and "'chat.group_say'" in JS


def test_history_is_read_only_and_data_never_goes_through_innerhtml():
    assert "/api/chat/days" in JS and "/api/chat/day/" in JS
    assert "innerHTML" not in JS
    assert not re.search(r"vpn|netbird|relay", JS, re.IGNORECASE)


def test_css_is_scoped_small_screens_and_touch_targets():
    assert "min-height:44px" in CSS
    assert "@media" in CSS and "prefers-reduced-motion" in CSS
    selectors = re.findall(r"(?m)^([^{@}/]+)\{", CSS)
    assert selectors and all(s.strip().startswith(".chat-page") for s in selectors)
