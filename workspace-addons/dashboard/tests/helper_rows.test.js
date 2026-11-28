// Home › Blocked now: work that stopped short (ORCH-26; O-01 D, 28 Nov: one line and ONE action per row). A pull
// request left open after its checks passed (Merge), a helper idle at its prompt (Remind), a helper that waits for an
// OK on its screen or a step that keeps failing (Open). More ways (Start helper, Start fresh) are on the Review card.
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
test('pull request left open: Merge merges exactly the shown commit in one click', async () => {
  const {c, calls, toasts} = context();
  const row = c.stoppedRow(UNMERGED);
  assert.match(text(row), /passed its checks but was not merged/);
  assert.match(text(row), /Invoice export/);
  assert.deepEqual(all(row, x => x.tag === 'a').map(a => a.attrs.href), ['#ticket/' + TID, PR]);
  assert.deepEqual(buttons(row).map(text), ['Merge']);
  assert.match(buttons(row)[0].attrs.className, /outline/);
  await click(buttons(row)[0]);
  assert.deepEqual(calls, [['pull.merge', {ticket:TID, url:PR, head:HEAD}]]);
  assert.deepEqual(toasts, [['Merged', 'ok']]);
});

test('pull request left open: a refused merge says why and nothing else runs', async () => {
  const {c, calls, toasts} = context({results:{'pull.merge':{ok:false, text:'GitHub did not merge it: checks pending.'}}});
  await click(buttons(c.stoppedRow(UNMERGED))[0]);
  assert.equal(calls.length, 1);
  assert.deepEqual(toasts, [['GitHub did not merge it: checks pending.', 'error']]);
});

test('idle helper: Remind sends one fixed message; with no live helper it starts one after the message', async () => {
  const {c, calls, toasts} = context({runs:{[TID]:{running:true}}});
  const row = c.stoppedRow(IDLE);
  assert.match(text(row), /idle for 14 min with nothing running/);
  assert.deepEqual(buttons(row).map(text), ['Remind']);
  await click(buttons(row)[0]);
  assert.deepEqual(calls.map(x => x[0]), ['run.send']);
  assert.match(calls[0][1].text, /idle for a while/);
  assert.deepEqual(toasts, [['Message sent', 'ok']]);
  const gone = context();
  await click(buttons(gone.c.stoppedRow(IDLE))[0]);
  assert.deepEqual(gone.calls.map(x => x[0]), ['run.send', 'run.start']);
});

test('the Review card still finds the words and the fresh start it shares with Home', async () => {
  const {c, calls} = context({runs:{[TID]:{running:true}}, results:{'run.stop':{ok:false, text:'Could not stop it.'}}});
  assert.match(vm.runInContext('MERGE_ASK', c), /passed its checks but is still open/);
  const r = await vm.runInContext('restartFresh', c)(TID);
  assert.equal(r.ok, false);
  assert.deepEqual(calls.map(x => x[0]), ['run.stop'], 'a stop that fails starts nothing');
});

test('a shared read-only copy shows the rows without buttons; other rows are not helper rows', () => {
  const {c} = context({snapshot:true});
  assert.equal(buttons(c.stoppedRow(UNMERGED)).length, 0);
  assert.equal(buttons(c.stoppedRow(IDLE)).length, 0);
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


test('stuck rows never merge with a question of the same ticket', () => {
  const {c} = context();
  const question = {id:'core:q:' + TID + ':q1', source:'core', kind:'question', ticket:TID, title:'Invoice export', tone:'needs-you', since:'2026-11-16T09:00:00Z', text:'Which format?', answer:{question:'q1', options:['CSV', 'PDF']}};
  const groups = c.homeNeeds([question, PERMISSION, FAILING]);
  assert.deepEqual([...groups.map(g => g.row.id)], [question.id, PERMISSION.id, FAILING.id]);
});



test('stuck rows: one line, one action: Open goes to the ticket, where the answer is', () => {
  const {c} = context({runs:{[TID]:{running:true}}});
  for (const row of [PERMISSION, FAILING]) {
    const el = c.stoppedRow(row);
    assert.deepEqual(buttons(el), []);
    const open = all(el, x => x.tag === 'a' && /btn/.test(x.attrs.className || ''));
    assert.deepEqual(open.map(a => [text(a), a.attrs.href]), [['Open', '#ticket/' + TID]]);
    assert.equal(el.attrs['data-blocked'], 'stopped'); assert.equal(el.attrs['data-counts'], '1');
  }
  assert.match(text(c.stoppedRow(FAILING)), /failed 2 times in a row/);
  // every row of Blocked now is blocked: no pill repeats it
  assert.deepEqual(all(c.stoppedRow(PERMISSION), x => /(^| )pill( |$)/.test(x.attrs.className || '')), []);
});

test('a ticket the Reviewer left for you is a card of the Review page, never a row of Blocked now', () => {
  const {c} = context();
  const ticket = c.ticketOf(TID);
  c.needsList = () => [UNSURE]; c.shown = t => t; c.titleTag = () => null; c.parse = v => new Date(v); c.now = () => new Date('2026-11-16T12:00:00Z');
  c.heading = (t, s) => node('header', {}, [t, s]); c.card = (key, title, suffix, kids) => node('section', {'data-key':key}, [title, kids]); c.emptyRow = t => node('p', {}, [t]);
  const page = c.home(), said = text(page);
  assert.doesNotMatch(said, /Reviewer|Invoice export/);
  assert.match(said, /Nothing is blocked\./);
  assert.match(said, /1 thing waits in Review/);
  assert.equal(ticket.status, 'review');
});
