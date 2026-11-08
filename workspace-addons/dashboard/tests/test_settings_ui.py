"""Settings contracts shared with delegated shell handlers and the API lane."""
from tests import webjs


def test_settings_navigation_and_cards():
    src = webjs.all_js()
    for text in (
        "role:'tablist'", "'data-action':'settings-tab'", "'data-key':'settings-switch-'",
        "a.dashboard?.panel === 'phone'", "href:'#addon/' + phoneAddon.name",
        "className:'settings-details'", "h('summary', {}, 'Details')",
        "OrchMobileMode?.settingsSection(h)", "OrchLook?.settingsSection()",
        "agent-card", "role:'status', className:'meta test-note'",
        "'data-action':'agent-test'", "'data-action':'settings-addon'",
        "settingsText('p', {className:'meta'}, addon.description)",
        "panelOf(id) === 'repeats'", "panelOf(id) === 'links'", "a?.dashboard?.label",
    ):
        assert text in src
    css = (webjs.WEB / 'pages/settings.css').read_text()
    assert '@media(max-width:760px)' in css
    assert 'overflow-x:auto' in css
    assert 'min-height:44px' in css


def test_repeat_uses_only_presets_and_open_tickets():
    src = webjs.all_js()
    assert "['every day at 9', 'every weekday at 9', 'every monday at 9', 'every hour']" in src
    assert "tickets().filter(t => !['done', 'dropped'].includes(t.status))" in src
    assert "{addon:route().id, verb, target:ticket.value}" in src
    assert "if (verb === 'repeat') args.value = preset.value;" in src
    assert "await act('addon.act', args)" in src
    assert "await loadAddon(route().id)" in src


def test_shared_links_are_optional_and_use_plain_actions():
    src = webjs.all_js()
    for text in (
        "fetch('/api/links', {cache:'no-store'})",
        "if (res.status !== 200) { sharedLinks = null; return; }",
        "Array.isArray(data.links)", "catch (_) { sharedLinks = null; }",
        "sharedLinks !== null", "No shared links yet.", "Link valid until ",
        "No end date", "'Expired'", "if (!link.copy) return;",
        "navigator.clipboard.writeText(link.link)",
        "act('link.extend', {id:link.id, days:7})", "act('link.stop', {id:link.id})",
        "'The link stops working.'", "'Stop sharing', send", "bindAddonControls(host)",
    ):
        assert text in src


def test_reply_is_optional_and_never_invented():
    src = webjs.all_js()
    part = src[src.index('function messageSend('):src.index('async function copyText(')]
    assert 'const args = {workspace:peer, text};' in part
    assert 'if (control.dataset.replyTo !== undefined) args.reply_to = control.dataset.replyTo;' in part
    assert "act('message.send', args)" in part


def test_actions_and_feature_detection_in_node():
    import shutil
    import subprocess

    import pytest

    if not shutil.which('node'):
        pytest.skip('node not installed')
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
global.h = (tag, attrs, ...kids) => { const n = node(tag, attrs); n.append(...kids); return n; };
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
  repeatsDialog('repeat');
  await controls.at(-1).onclick();
  assert.deepEqual(calls.pop(), {op:'addon.act', args:{addon:'automation', verb:'repeat', target:'t_open', value:'every day at 9'}});
  repeatsDialog('copy');
  await controls.at(-1).onclick();
  assert.deepEqual(calls.pop(), {op:'addon.act', args:{addon:'automation', verb:'copy', target:'t_open'}});
  global.el = tag => Object.assign(node(tag), {value:'A reply'});
  for (const reply of [undefined, 'msg_123']) {
    const dataset = {sendTo:'ws_peer'};
    if (reply !== undefined) dataset.replyTo = reply;
    messageSend({dataset}); await controls.at(-1).onclick();
    const expected = {workspace:'ws_peer', text:'A reply'};
    if (reply !== undefined) expected.reply_to = reply;
    assert.deepEqual(calls.pop(), {op:'message.send', args:expected});
  }
  global.fetch = async () => ({status:200, json:async () => ({links:[]})});
  await loadSharedLinks(); assert.deepEqual(sharedLinks, []);
  global.fetch = async () => ({status:404});
  await loadSharedLinks(); assert.equal(sharedLinks, null);
  global.fetch = async () => { throw new Error('offline'); };
  await loadSharedLinks(); assert.equal(sharedLinks, null);
})().catch(err => { console.error(err); process.exitCode = 1; });
"""
    subprocess.run(
        ['node', '-e', script, str(webjs.WEB / 'pages/settings.js')],
        check=True, capture_output=True, text=True,
    )


def test_load_addons_passes_only_known_panels():
    from orch_dashboard.data import load_addons

    def row(name, panel):
        return {"name": name, "active": True, "dashboard": {"label": "X", "icon": "link", "panel": panel}}

    rows = load_addons(None, None, [row("aaa", "links"), row("bbb", "<script>"), row("ccc", None)])
    assert {r["name"]: r["dashboard"]["panel"] for r in rows} == {"aaa": "links", "bbb": None, "ccc": None}
