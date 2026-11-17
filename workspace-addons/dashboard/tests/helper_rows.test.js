// Home › Needs you: work that stopped short (ORCH-26). A pull request left open after its checks passed (Merge /
// Start helper) and a helper idle at its prompt (Nudge / Start fresh): two buttons, each one click.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const PAGES = path.join(__dirname, '../src/orch_dashboard/web/pages');
function node(tag, attrs = {}, children = []) {
  return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false), dataset:{}, listeners:{},
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }, querySelectorAll() { return []; }};
}
const text = n => n == null ? '' : typeof n === 'string' || typeof n === 'number' ? String(n) : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
const buttons = n => all(n, x => x.tag === 'button');
const click = async n => { for (const fn of n.listeners.click || []) await fn({preventDefault() {}}); };

const TID = 't_abcdef', PR = 'https://github.com/acme/app/pull/12', HEAD = 'a'.repeat(40);
const UNMERGED = {id:'core:unmerged:' + TID, source:'core', kind:'helper:unmerged', ticket:TID, title:'Invoice export', tone:'needs-you', since:'2026-11-16T10:00:00Z',
  text:'The pull request passed its checks but was not merged, and no helper is working on it.', cli:'orch run start DM-1', pull:{url:PR, head:HEAD}, helper:'none'};
const IDLE = {id:'core:idle:' + TID, source:'core', kind:'helper:idle', ticket:TID, title:'Invoice export', tone:'warn', since:'2026-11-16T10:00:00Z',
  text:'The helper has been idle for 14 min with nothing running.', cli:'orch run send DM-1 "Carry on with the open tasks."'};

function context({runs = {}, results = {}, snapshot = false} = {}) {
  const calls = [], toasts = [], ticket = {id:TID, title:'Invoice export', status:'review'};
  const c = vm.createContext({
    window:{DashHelpers:helpers, orch:{toast:(t, k) => toasts.push([t, k])}},
    localStorage:{getItem:() => null, setItem() {}},
    h:(tag, attrs, ...children) => node(tag, attrs || {}, children), fragment:(...children) => node('fragment', {}, children),
    button:(t, cls, fn) => { const b = node('button', {className:'btn ' + cls}, [t]); b.listeners.click = [fn]; return b; },
    iconEl:name => node('icon', {name}), array:v => Array.isArray(v) ? v : [], snapshot, clean:v => String(v ?? ''),
    capitalise:v => String(v).replace(/^./, x => x.toUpperCase()), today:() => '2026-11-16', render() {}, setTimeout:() => 1, clearTimeout() {},
    document:{getElementById:() => null}, locks:new Set(), changeUnavailable:() => false, changeError:r => r.text,
    tickets:() => [ticket], ticketOf:id => id === TID ? ticket : null, href:id => '#ticket/' + id, state:{runs, settings:{}}, addons:() => [],
    act:async (op, args) => { calls.push(JSON.parse(JSON.stringify([op, args]))); return results[op] || {ok:true}; },
  });
  vm.runInContext(fs.readFileSync(path.join(PAGES, 'home.js'), 'utf8'), c);
  return {c, calls, toasts};
}

test('pull request left open: Merge merges exactly the shown commit in one click', async () => {
  const {c, calls, toasts} = context();
  const row = c.needRow(UNMERGED, null);
  assert.match(text(row), /passed its checks but was not merged/);
  assert.match(text(row), /Invoice export/);
  assert.deepEqual(all(row, x => x.tag === 'a').map(a => a.attrs.href), ['#ticket/' + TID, PR]);
  assert.deepEqual(buttons(row).map(text), ['Merge', 'Start helper']);
  await click(buttons(row)[0]);
  assert.deepEqual(calls, [['pull.merge', {ticket:TID, url:PR, head:HEAD}]]);
  assert.deepEqual(toasts, [['Merged', 'ok']]);
});

test('pull request left open: a refused merge says why and nothing else runs', async () => {
  const {c, calls, toasts} = context({results:{'pull.merge':{ok:false, text:'GitHub did not merge it: checks pending.'}}});
  await click(buttons(c.needRow(UNMERGED, null))[0]);
  assert.equal(calls.length, 1);
  assert.deepEqual(toasts, [['GitHub did not merge it: checks pending.', 'error']]);
});

test('pull request left open: Start helper tells the helper what is left, then starts it', async () => {
  const {c, calls, toasts} = context();
  await click(buttons(c.needRow(UNMERGED, null))[1]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send', 'run.start']);
  assert.equal(calls[0][1].ticket, TID);
  assert.match(calls[0][1].text, /passed its checks but is still open/);
  assert.deepEqual(calls[1][1], {ticket:TID});
  assert.deepEqual(toasts, [['Helper started', 'ok']]);
});

test('pull request left open with a helper idle on it: the second button is Nudge and starts nothing', async () => {
  const {c, calls} = context({runs:{[TID]:{running:true}}});
  const row = c.needRow({...UNMERGED, helper:'idle'}, null);
  assert.deepEqual(buttons(row).map(text), ['Merge', 'Nudge']);
  await click(buttons(row)[1]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send']);
});

test('idle helper: Nudge sends one fixed message, Start fresh stops it and starts a new one', async () => {
  const {c, calls, toasts} = context({runs:{[TID]:{running:true}}});
  const row = c.needRow(IDLE, null);
  assert.match(text(row), /idle for 14 min with nothing running/);
  assert.deepEqual(buttons(row).map(text), ['Nudge', 'Start fresh']);
  await click(buttons(row)[0]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send']);
  assert.match(calls[0][1].text, /idle for a while/);
  await click(buttons(row)[1]);
  assert.deepEqual(calls.slice(1), [['run.stop', {ticket:TID}], ['run.start', {ticket:TID, fresh:true}]]);
  assert.deepEqual(toasts, [['Message sent', 'ok'], ['Helper started fresh', 'ok']]);
});

test('idle helper: a stop that fails starts nothing', async () => {
  const {c, calls, toasts} = context({runs:{[TID]:{running:true}}, results:{'run.stop':{ok:false, text:'Could not stop it.'}}});
  await click(buttons(c.needRow(IDLE, null))[1]);
  assert.deepEqual(calls.map(x => x[0]), ['run.stop']);
  assert.deepEqual(toasts, [['Could not stop it.', 'error']]);
});

test('a shared read-only copy shows the rows without buttons; other rows are not helper rows', () => {
  const {c} = context({snapshot:true});
  assert.equal(buttons(c.needRow(UNMERGED, null)).length, 0);
  const isHelperRow = vm.runInContext('isHelperRow', c);
  assert.equal(isHelperRow({...IDLE, source:'sync'}), false);
  assert.equal(isHelperRow({...IDLE, kind:'overdue-wait'}), false);
  assert.equal(helpers.needsYouCount([UNMERGED], []), 0);  // listed on Home, not in the number (no question, ORCH-63)
  assert.equal(helpers.isNotice(IDLE), false);
});
