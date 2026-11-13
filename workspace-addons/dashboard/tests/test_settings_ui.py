"""Settings contracts shared with delegated shell handlers and the API lane."""

from tests import webjs


def test_settings_navigation_and_cards():
    src = webjs.all_js()
    for text in (
        "role:'tablist'",
        "'data-action':'settings-tab'",
        "'data-key':'settings-switch-'",
        "a.dashboard?.panel === 'phone'",
        "panel('phone', phonePanel(phoneAddon, settings))",
        "OrchMobileMode?.settingsSection(h)",
        "'1. Relay connection'",
        "'Connect to your relay first'",
        "function addonDetailPage(addon)",
        "'About this add-on'",
        "OrchLook?.settingsSection()",
        "agent-card",
        "role:'status', className:'meta test-note'",
        "'data-action':'agent-test'",
        "'data-action':'settings-addon'",
        "settingsText('p', {className:'meta'}, addon.description)",
        "panelOf(id) === 'repeats'",
        "panelOf(id) === 'links'",
        "a?.dashboard?.label",
    ):
        assert text in src
    assert "className:'settings-details'" not in src
    # the phone tab is a real tab that stays in Settings (no link away to the add-on page)
    assert "href:'#addon/' + phoneAddon.name" not in src
    # the add-on detail page has no Details toggle; "Pair a phone" stays disabled until the relay is connected
    detail = src[src.index("function addonDetailPage(addon)") :][:3500]
    assert "h('summary'" not in detail and "'Details'" not in detail
    assert "connected ? {} : {disabled:true}" in src
    assert "history.replaceState(null, '', '#settings/' + tab)" in src
    assert "h('span', {className:'set-label'}, 'Folder')" in src
    # folder: plain name + Copy path + quiet full path, no Details toggle
    folder = src[src.index("h('span', {className:'set-label'}, 'Folder')") :][:900]
    assert "'Copy path'" in folder and "h('summary'" not in folder
    assert "['agent', 'Helper']" in src and "['agent', 'Agent']" not in src
    css = (webjs.WEB / "pages/settings.css").read_text()
    assert "@media(max-width:760px)" in css
    assert "overflow-x:auto" in css
    assert "min-height:44px" in css


def test_switch_rows_choices_and_closed_details_owner_pass():
    look = (webjs.WEB / "look.js").read_text(encoding="utf-8")
    css = (webjs.WEB / "pages/settings.css").read_text(encoding="utf-8")
    # Shared pages: like every other switch row (no label line above, so nothing wraps at 390 px)
    row = look[look.index("'data-key': 'lk-shared-row'") :][:500]
    assert "set-label" not in row and "className: 'switch'" in row
    # "When": the unselected choice is outlined like the hours choice; full width when stacked
    assert ".settings .copies-choices .btn.ghost{border-color:var(--border-strong);color:var(--text)}" in css
    narrow = css[css.index("@media(max-width:720px)") :]
    stacked = ".settings .copies-choices{justify-self:stretch;flex-direction:column;align-items:stretch}"
    assert stacked in narrow
    assert ".settings .copies-details{padding:0 16px;" in css


def test_repeat_window_offers_plain_choices_and_open_tickets():
    src = webjs.all_js()
    assert (
        "const REPEAT_FREQ = [['daily', 'Every day'], ['weekly', 'Every week'], ['monthly', 'Every month'], ['custom', 'Custom']];"
        in src
    )
    assert "tickets().filter(t => only ? t.id === only : !['done', 'dropped'].includes(t.status))" in src
    assert "{addon:addonName || route().id, verb:'repeat', target:ticket.value, value:plan.phrase}" in src
    assert "verb:'copy', target:ticket.value" in src
    assert "if (route().kind === 'addon') await loadAddon(route().id)" in src


def test_shared_links_are_optional_and_use_plain_actions():
    src = webjs.all_js()
    for text in (
        "fetch('/api/links', {cache:'no-store'})",
        "if (res.status !== 200) { sharedLinks = null; sharedLinksDown = false; return; }",
        "Array.isArray(data.links)",
        "catch (_) { sharedLinks = null; sharedLinksDown = false; }",
        "if (!link.copy) return;",
        "navigator.clipboard.writeText(link.link)",
        "act('link.extend', {id:link.id, days:7})",
        "act('link.stop', {id:link.id})",
        "'The link stops working.'",
        "'Stop sharing', send",
        "bindAddonControls(host)",
        "'data-native':'link-share'",  # the page heading's "Share a file"
    ):
        assert text in src


def test_message_button_opens_chat():
    src = webjs.all_js()
    part = src[src.index("function messageSend(") : src.index("async function copyText(")]
    assert "location.hash = '#chat/' + peer" in part
    assert "dialog(" not in part


def test_actions_and_feature_detection_in_node():
    import shutil
    import subprocess

    import pytest

    if not shutil.which("node"):
        pytest.skip("node not installed")
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInThisContext(source);
const controls = [], calls = [];
function node(tag, attrs = {}) {
  const n = {tag, ...attrs, children:[], options:[], value:'', dataset:{},
    append(...kids) { this.children.push(...kids.filter(Boolean)); if (tag === 'select') { this.options.push(...kids); if (!this.value) this.value = kids[0]?.value || ''; } },
    setAttribute() {}, focus() {}};
  return n;
}
const selects = [];
global.h = (tag, attrs, ...kids) => { const n = node(tag, attrs); n.append(...kids); if (tag === 'select') selects.push(n); return n; };
global.el = tag => node(tag);
global.button = (text, cls, fn) => { const n = node('button', {text, onclick:fn}); controls.push(n); return n; };
global.Option = function(text, value) { return {text, value}; };
global.dialog = () => ({d:node('dialog'), actions:node('div')});
global.snapshot = false;
global.capitalise = s => s[0].toUpperCase() + s.slice(1);
global.tickets = () => [{id:'t_open', title:'Open', status:'ready'}, {id:'t_done', status:'done'}, {id:'t_drop', status:'dropped'}];
global.route = () => ({kind:'addon', id:'automation'});
global.window = {orch:{open() {}, close:async () => {}, toast() {}}};
global.act = async (op, args) => { calls.push({op, args}); return {ok:true}; };
loadAddon = async () => {};
(async () => {
  const plan = repeatPlan;
  assert.deepEqual(plan({freq:'daily', time:'07:30'}), {phrase:'daily 07:30', summary:'Runs every day at 07:30', hint:''});
  assert.equal(plan({freq:'weekly', days:[1], time:'08:00'}).phrase, 'every monday 08:00');
  assert.equal(plan({freq:'weekly', days:[1], time:'08:00'}).summary, 'Runs every Monday at 08:00');
  assert.equal(plan({freq:'weekly', days:[5, 1, 3], time:'08:05'}).phrase, '5 8 * * 1,3,5');
  assert.equal(plan({freq:'weekly', days:[5, 1, 3], time:'08:05'}).summary, 'Runs every Monday, Wednesday and Friday at 08:05');
  assert.equal(plan({freq:'weekly', days:[0], time:'09:00'}).phrase, 'every sunday 09:00');
  assert.equal(plan({freq:'weekly', days:[], time:'08:00'}).phrase, null);
  assert.equal(plan({freq:'monthly', monthday:15, time:'09:00'}).phrase, 'monthly 15 09:00');
  assert.equal(plan({freq:'monthly', monthday:31, time:'09:00'}).phrase, null);
  assert.equal(plan({freq:'custom', every:3, time:'06:10'}).phrase, '10 6 */3 * *');
  assert.equal(plan({freq:'custom', every:1, time:'06:10'}).phrase, 'daily 06:10');
  assert.equal(plan({freq:'custom', every:0, time:'06:10'}).phrase, null);
  assert.equal(plan({freq:'daily', time:''}).phrase, null);
  assert.equal(plan({freq:'daily', time:'25:00'}).phrase, null);
  global.location = {hash:''};
  messageSend({dataset:{sendTo:'ws_abcdefghij'}});
  assert.equal(location.hash, '#chat/ws_abcdefghij');
  messageSend({dataset:{sendTo:'../../bad'}});
  assert.equal(location.hash, '#chat/ws_abcdefghij');
  global.fetch = async () => ({status:200, json:async () => ({links:[]})});
  await loadSharedLinks(); assert.deepEqual(sharedLinks, []);
  global.fetch = async () => ({status:200, json:async () => ({links:[], unreachable:true})});
  await loadSharedLinks(); assert.equal(sharedLinksDown, true); assert.deepEqual(sharedLinks, []);
  global.fetch = async () => ({status:404});
  await loadSharedLinks(); assert.equal(sharedLinks, null); assert.equal(sharedLinksDown, false);
  global.fetch = async () => { throw new Error('offline'); };
  await loadSharedLinks(); assert.equal(sharedLinks, null);
})().catch(err => { console.error(err); process.exitCode = 1; });
"""
    subprocess.run(
        ["node", "-e", script, str(webjs.WEB / "pages/settings.js")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_load_addons_passes_only_known_panels():
    from orch_dashboard.data import load_addons

    def row(name, panel):
        return {"name": name, "active": True, "dashboard": {"label": "X", "icon": "link", "panel": panel}}

    rows = load_addons(None, None, [row("aaa", "links"), row("bbb", "<script>"), row("ccc", None)])
    assert {r["name"]: r["dashboard"]["panel"] for r in rows} == {"aaa": "links", "bbb": None, "ccc": None}


def test_settings_git_private(ws, monkeypatch):
    from orch_dashboard import data

    default = {"count": 0, "lines": [], "agent_command_ignored": False, "pending": []}
    assert data.load_settings(ws, None)["git_private"] == default
    replies = [None, [], {}, {"count": "3", "lines": "bad", "agent_command_ignored": "yes"}]
    replies.append(
        {
            "count": 3,
            "lines": [None, "x" * 350, 1, "two", "three", "ignored", "five"],
            "agent_command_ignored": True,
        }
    )
    for reply in replies:
        calls = []

        def run(binary, args, root, calls=calls, reply=reply):
            calls.append((binary, args, root))
            return reply if args == ["private", "--json"] else None

        monkeypatch.setattr(data, "run_orch", run)
        result = data.load_settings(ws, "orch")["git_private"]
        assert ("orch", ["private", "--json"], ws) in calls
        assert result == (
            default
            if reply is not replies[-1]
            else {
                "count": 3,
                "lines": ["x" * 300, "two", "three", "ignored"],
                "agent_command_ignored": True,
                "pending": [],
            }
        )


def test_settings_pending_carries_every_hashed_field_in_full(ws, monkeypatch):
    from orch_dashboard import data

    row = {
        "name": "mine",
        "key": "a" * 64,
        "showable": True,
        "adapter": "generic",
        "command": "c" * 450,
        "interactive": "live",
        "prompt": "stdin",
    }
    bad = {"name": "Bad Name", "key": "a" * 64, "command": "x"}
    monkeypatch.setattr(
        data,
        "run_orch",
        lambda b, a, r: (
            {"count": 0, "lines": [], "pending_agents": [row, bad]} if a == ["private", "--json"] else None
        ),
    )
    assert data.load_settings(ws, "orch")["git_private"]["pending"] == [row]
