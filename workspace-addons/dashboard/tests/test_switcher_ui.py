"""Source contracts for the local workspace menu and optional backend fields."""

from .webjs import WEB


def test_switcher_only_lists_local_workspaces_current_first():
    js = (WEB / "switcher.js").read_text()
    assert "w.here || !w.url || /^http:\\/\\/(127\\.0\\.0\\.1|localhost)[:/]/.test(w.url)" in js
    assert "Number(!!b.here) - Number(!!a.here)" in js
    assert "attrs.href = w.url" in js  # a running local workspace stays a link
    assert "'Current'" in js and "'✓ '" in js


def test_optional_workspace_details_and_safe_text():
    js = (WEB / "switcher.js").read_text()
    assert "L.badge(w, w.name, 32)" in js
    assert "typeof w.type === 'string' && w.type.trim()" in js
    assert "Number.isInteger(w.needs)" in js
    assert "w.needs === 1 ? ' needs you' : ' need you'" in js
    assert "innerHTML" not in js


def test_switcher_keyboard_and_touch_targets():
    js = (WEB / "switcher.js").read_text()
    css = (WEB / "look.css").read_text().split("/* v3-pages: switcher + mobile mode */")[1]
    assert "role: 'menuitem'" in js and "row.tabIndex = 0" in js
    assert "menu.querySelector('[role=menuitem]')?.focus()" in js
    assert "e.key === 'Escape' && menu" in js
    assert "close(); box.focus();" in js
    assert "ArrowDown:" in js and "ArrowUp:" in js
    assert "min-height:64px" in css and ":focus-visible" in css


def test_switcher_stays_one_row_in_the_open_menu():
    # The kit shows the workspace box as a block in the open Menu (0,3,0); the switcher
    # (icon, name + sub-label, chevron) must win with a more specific flex rule.
    kit = (WEB / "kit" / "components.css").read_text()
    look = (WEB / "look.css").read_text()
    assert ".sidebar[data-open=true] .workspace," in kit
    assert ".sidebar[data-open=true] .workspace.ws-switch{display:flex}" in look
