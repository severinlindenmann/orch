// ORCH-2112: Settings › General shows the Shared pages section (files shared with a link) only while publish is on (R1.1).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const PAGES = path.join(__dirname, '../src/orch_dashboard/web/pages');
function node(tag, attrs = {}, children = []) {
  return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false), dataset:{}, listeners:{},
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }, append(...kids) { this.children.push(...kids.filter(Boolean)); },
    querySelectorAll() { return []; }};
}
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];

function generalPanel(addons) {
  const c = vm.createContext({
    window:{DashHelpers:helpers, orch:{toast() {}}, OrchLook:{profileCard:() => null, settingsSection:() => node('div', {'data-key':'settings-look'})}},
    localStorage:{getItem:() => null, setItem() {}},
    h:(tag, attrs, ...children) => node(tag, attrs || {}, children), fragment:(...children) => node('fragment', {}, children),
    el:(tag, cls, t) => node(tag, {className:cls}, t === undefined ? [] : [t]),
    button:(t, cls) => node('button', {className:'btn ' + cls}, [t]),
    iconEl:name => node('icon', {name}), array:v => Array.isArray(v) ? v : [], snapshot:false, clean:v => String(v ?? ''),
    name:v => String(v ?? ''), capitalise:v => String(v), time:() => '', today:() => '2026-11-25', render() {},
    route:() => ({kind:'settings'}), location:{hash:'#settings'}, requestAnimationFrame:fn => fn(), queueMicrotask() {},
    setTimeout:() => 1, clearTimeout() {}, document:{getElementById:() => null}, locks:new Set(),
    tickets:() => [], needsList:() => [], questions:() => [], heading:(...t) => node('h1', {}, t),
    state:{workspace:'Finance', settings:{folder:'/tmp/Finance', addons}, addons}, addons:() => addons,
    addonLabel:a => a?.name, fetch:async () => ({ok:false, status:404, json:async () => ({})}), act:async () => ({ok:true}), URL,
  });
  for (const file of ['home', 'settings']) vm.runInContext(fs.readFileSync(path.join(PAGES, file + '.js'), 'utf8'), c);
  const general = all(c.settingsPage(), n => n.attrs?.id === 'settings-panel-general')[0];
  const row = addons.find(a => a.name === 'publish');
  return {general, detail:row ? c.addonDetailPage(row) : null};
}
const key = (n, k) => all(n, x => x.attrs?.['data-key'] === k);

// W-059 (owner 28 Nov): the shared pages options are an add-on's own: they are edited on that add-on's Settings page,
// and General only links there. Still only while publish is on (R1.1, ORCH-2112).
test('publish off: no Shared pages row in General and no section on its Settings page; publish on: the row links to the section', () => {
  for (const [addons, why] of [[[], 'no add-ons'], [[{name:'dashboard', active:true, shipped:true}], 'only the dashboard'], [[{name:'publish', active:false, shipped:true}], 'publish turned off']]) {
    const {general, detail} = generalPanel(addons);
    assert.equal(key(general, 'settings-look').length, 0, why);
    assert.equal(key(general, 'settings-everyday-shared-row').length, 0, why);
    if (detail) assert.equal(key(detail, 'settings-look').length, 0, why + ': its Settings page shows the switch only');
  }
  const {general, detail} = generalPanel([{name:'publish', active:true, shipped:true, dashboard:{panel:'links', label:'Publish'}}]);
  assert.equal(key(general, 'settings-look').length, 0, 'General does not edit it');
  const [link] = key(general, 'settings-everyday-shared');
  assert.deepEqual([link.tag, link.attrs.href], ['a', '#settings/addons/publish']);
  assert.equal(key(detail, 'settings-look').length, 1, 'the add-on\u2019s Settings page holds it');
});
