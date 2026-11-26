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
  return all(c.settingsPage(), n => n.attrs?.id === 'settings-panel-general')[0];
}
const shown = panel => all(panel, n => n.attrs?.['data-key'] === 'settings-look').length === 1;

test('publish off: Settings › General has no Shared pages section; publish on: it shows', () => {
  assert.equal(shown(generalPanel([])), false, 'no add-ons');
  assert.equal(shown(generalPanel([{name:'dashboard', active:true, shipped:true}])), false, 'only the dashboard');
  assert.equal(shown(generalPanel([{name:'publish', active:false, shipped:true}])), false, 'publish turned off');
  assert.equal(shown(generalPanel([{name:'publish', active:true, shipped:true}])), true, 'publish on');
});
