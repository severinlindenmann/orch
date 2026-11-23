// Home › Needs you: work that stopped short (ORCH-26). A pull request left open after its checks passed (Merge /
// Start helper) and a helper idle at its prompt (Remind / Start fresh): two buttons, each one click.
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
  vm.runInContext(fs.readFileSync(path.join(PAGES, 'start.js'), 'utf8'), c);  // the one Start button (ORCH-475)
  return {c, calls, toasts};
}
// One click on the main half of a kit Start button (kit/start-choice.js) as the page set it up: the page's ops first
// (before), then the start: plain, or fresh on the usual tool and model; it stops at the first refusal, as the kit does.
async function kitClick(c, row, label) {
  const host = all(row, x => x.attrs?.['data-start-host']).find(x => text(x) === label);
  assert.ok(host, 'a Start button ' + label);
  const o = vm.runInContext('startOpts', c).get(host.attrs['data-key']);
  const ticket = host.attrs['data-start-host'], ops = o.fresh ? [['run.start', {ticket, fresh:true}]] : [['run.start', {ticket}]];
  const first = o.before ? await o.before(ops) : [];
  if (first === null) return;
  for (const [op, args] of [...first, ...ops]) { const r = await c.act(op, args); if (!r.ok) break; }
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
  const {c, calls} = context();
  await kitClick(c, c.needRow(UNMERGED, null), 'Start helper');
  assert.deepEqual(calls.map(x => x[0]), ['run.send', 'run.start']);
  assert.equal(calls[0][1].ticket, TID);
  assert.match(calls[0][1].text, /passed its checks but is still open/);
  assert.deepEqual(calls[1][1], {ticket:TID});
});

test('pull request left open with a helper idle on it: the second button is Remind and starts nothing', async () => {
  const {c, calls} = context({runs:{[TID]:{running:true}}});
  const row = c.needRow({...UNMERGED, helper:'idle'}, null);
  assert.deepEqual(buttons(row).map(text), ['Merge', 'Remind']);
  await click(buttons(row)[1]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send']);
});

test('idle helper: Remind sends one fixed message, Start fresh stops it and starts a new one', async () => {
  const {c, calls, toasts} = context({runs:{[TID]:{running:true}}});
  const row = c.needRow(IDLE, null);
  assert.match(text(row), /idle for 14 min with nothing running/);
  assert.deepEqual(buttons(row).map(text), ['Remind', 'Start fresh']);
  await click(buttons(row)[0]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send']);
  assert.match(calls[0][1].text, /idle for a while/);
  await kitClick(c, row, 'Start fresh');
  assert.deepEqual(calls.slice(1), [['run.stop', {ticket:TID}], ['run.start', {ticket:TID, fresh:true}]]);
  assert.deepEqual(toasts, [['Message sent', 'ok']]);
});

test('idle helper: a stop that fails starts nothing', async () => {
  const {c, calls, toasts} = context({runs:{[TID]:{running:true}}, results:{'run.stop':{ok:false, text:'Could not stop it.'}}});
  await kitClick(c, c.needRow(IDLE, null), 'Start fresh');
  assert.deepEqual(calls.map(x => x[0]), ['run.stop']);  // the kit shows the refusal's words and ends Starting
  assert.deepEqual(toasts, []);
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

// ORCH-295: Changes asked is derived, same rule as the core (tickets.changes_asked)
test('changesAsked: Ready with an open change_request task only', () => {
  const ask = {origin:'change_request', done:false};
  assert.equal(helpers.changesAsked({status:'ready', checklist:[ask]}), true);
  assert.equal(helpers.changesAsked({status:'ready', checklist:[{...ask, done:true}]}), false);
  assert.equal(helpers.changesAsked({status:'ready', checklist:[{...ask, wont_do:true}]}), false);
  assert.equal(helpers.changesAsked({status:'review', checklist:[ask]}), false);
  assert.equal(helpers.changesAsked({status:'ready', checklist:[{done:false}]}), false);
});

// ORCH-426: stuck tickets come first, whether or not the ticket needs a person's review.
const stuckRow = (kind, text, tone = 'needs-you') => ({id:'core:' + kind.split(':')[1] + ':' + TID, source:'core', kind, ticket:TID, title:'Invoice export', tone, since:'2026-11-16T10:00:00Z', text});
const PERMISSION = stuckRow('helper:permission', 'The helper has waited 5 min for your OK on its screen.');
const FAILING = stuckRow('helper:failing', 'The check failed 2 times in a row on the step "Export works".', 'bad');
const UNSURE = stuckRow('reviewer:unsure', 'The Reviewer was not sure and left it for you: no pull request to check.');

test('stuck rows: Open goes to the ticket; a failing step also offers Remind and Start fresh', () => {
  const {c} = context({runs:{[TID]:{running:true}}});
  for (const row of [PERMISSION, UNSURE]) {
    const el = c.needRow(row, null);
    assert.deepEqual(buttons(el), []);
    const open = all(el, x => x.tag === 'a' && /btn/.test(x.attrs.className || ''));
    assert.deepEqual(open.map(a => [text(a), a.attrs.href]), [['Open', '#ticket/' + TID]]);
  }
  const failing = c.needRow(FAILING, null);
  assert.match(text(failing), /failed 2 times in a row/);
  assert.deepEqual(buttons(failing).map(text), ['Remind', 'Start fresh']);
});

test('stuck rows never merge with a question of the same ticket', () => {
  const {c} = context();
  const question = {id:'core:q:' + TID + ':q1', source:'core', kind:'question', ticket:TID, title:'Invoice export', tone:'needs-you', since:'2026-11-16T09:00:00Z', text:'Which format?', answer:{question:'q1', options:['CSV', 'PDF']}};
  const groups = c.homeNeeds([question, PERMISSION, FAILING]);
  assert.deepEqual([...groups.map(g => g.row.id)], [question.id, PERMISSION.id, FAILING.id]);
});

test('work that stopped carries the Helpers list word as a pill: Stuck, or Idle for an idle helper', () => {
  const {c} = context();
  c.window.UI = {helperPill:(state, word) => node('span', {className:'pill helper-pill', 'data-state':state}, [word]),
    ticketPill:s => node('span', {className:'pill', 'data-state':s.pill}, [s.word])};
  const pill = row => all(c.needRow(row, null), x => /(^| )pill( |$)/.test(x.attrs.className || '')).map(text);
  assert.deepEqual(pill(PERMISSION), ['Stuck']);
  assert.deepEqual(pill(FAILING), ['Stuck']);
  assert.deepEqual(pill(UNMERGED), ['Stuck']);
  assert.deepEqual(pill(IDLE), ['Idle']);
  // ORCH-1717: a ticket the Reviewer left for the person waits for a look, it is not stuck
  assert.deepEqual(pill(UNSURE), ['Check']);
});

test('a ticket the Reviewer left for you says its one plain reason, not the Reviewer\'s counts', () => {
  const {c} = context();
  const row = {...UNSURE, text:'The Reviewer was not sure and left it for you: too big for a small fix (25 files, 4070 lines; small is 10 and 300).', short:'It is a big change.'};
  const said = text(c.needRow(row, null));
  assert.match(said, /It is a big change\./);
  assert.doesNotMatch(said, /Reviewer|files|small is/);
  assert.match(text(c.needRow(UNSURE, null)), /no pull request to check/);  // an older core without `short`: its text
});
