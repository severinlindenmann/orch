// ORCH-151: the Triage menu on the Tickets page: pick the lanes, Start triage runs `orch triage --start --lanes`
// and opens the new Triage ticket.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');
const part = src.slice(src.indexOf('const TRIAGE_LANES'), src.indexOf('function ticketNotFound'));

function el(tag, attrs = {}, kids = []) {
  const node = {tag, attrs:{...attrs}, kids:kids.flat().filter(k => k != null), listeners:{}, disabled:false, checked:false, textContent:''};
  node.addEventListener = (ev, fn) => { node.listeners[ev] = fn; };
  node.setAttribute = (k, v) => { node.attrs[k] = v; };
  return node;
}
function find(node, key) {
  if (!node || typeof node !== 'object') return null;
  if (node.attrs?.['data-key'] === key) return node;
  for (const k of node.kids || []) { const f = find(k, key); if (f) return f; }
  return null;
}
function context(list, result, snapshot = false) {
  const ctx = {snapshot, list, acts:[], toasts:[], location:{hash:'#tickets'}};
  ctx.tickets = () => ctx.list;
  ctx.h = (tag, attrs, ...kids) => el(tag, attrs, kids);
  ctx.button = (text, cls, click) => { const b = el('button', {}, [text]); b.click = click; return b; };
  ctx.iconEl = name => ({icon:name});
  ctx.href = id => '#ticket/' + id;
  ctx.changeError = r => 'Refused: ' + r.text;
  ctx.window = {orch:{toast:(text, kind) => ctx.toasts.push([text, kind])}};
  ctx.act = async (op, args) => { ctx.acts.push([op, args]); if (result.ok) ctx.list = [...ctx.list, {id:'t_new123', title:'Triage 17 Nov', status:'active'}]; return result; };
  vm.createContext(ctx); vm.runInContext(part, ctx); return ctx;
}
const DEMO = [{id:'a', status:'open'}, {id:'b', status:'active'}, {id:'c', status:'waiting', questions:[{answer:null}]},
  {id:'d', status:'review'}, {id:'e', status:'done'}, {id:'f', status:'dropped', superseded_by:'a'}];

test('lanes follow the board: backlog, working, needs you, check, done, superseded', () => {
  const ctx = context(DEMO, {ok:true});
  assert.deepEqual(DEMO.map(t => ctx.triageLane(t)), ['backlog', 'working', 'needs-you', 'check', 'done', 'superseded']);
});

test('the menu shows each lane with tickets and its count; closed lanes start unticked', () => {
  const menu = context(DEMO, {ok:true}).triageButton();
  assert.equal(menu.attrs['data-key'], 'triage');
  assert.equal(find(menu, 'triage-lane-backlog').checked, true);
  assert.equal(find(menu, 'triage-lane-working').checked, true);
  assert.equal(find(menu, 'triage-lane-done').checked, false);
  assert.equal(find(menu, 'triage-lane-todo'), null);  // no tickets in To do: no box
  assert.match(find(menu, 'triage-title').kids[0], /Triage · 4 tickets/);  // backlog, working, needs you, check
  assert.equal(typeof find(menu, 'triage-start').click, 'function');
});

test('ticking Done counts it in; unticking every lane disables Start triage', () => {
  const ctx = context(DEMO, {ok:true});
  const menu = ctx.triageButton();
  const done = find(menu, 'triage-lane-done'); done.checked = true; done.listeners.change();
  assert.match(find(menu, 'triage-title').textContent, /5 tickets/);
  for (const id of ['backlog', 'working', 'needs-you', 'check', 'done']) { const b = find(menu, 'triage-lane-' + id); b.checked = false; b.listeners.change(); }
  assert.equal(find(menu, 'triage-start').disabled, true);
  assert.match(find(menu, 'triage-title').textContent, /Pick a lane/);
});

test('hidden on a shared copy and with no tickets', () => {
  assert.equal(context(DEMO, {ok:true}, true).triageButton(), null);
  assert.equal(context([], {ok:true}).triageButton(), null);
});

test('a click sends the picked lanes in board order and opens the new Triage ticket', async () => {
  const ctx = context(DEMO, {ok:true});
  const button = {disabled:false};
  await ctx.startTriage({currentTarget:button});
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.acts)), [['triage.start', {lanes:['backlog', 'todo', 'working', 'needs-you', 'waiting', 'check']}]]);
  assert.equal(ctx.location.hash, '#ticket/t_new123');
  assert.equal(ctx.toasts[0][1], 'ok');
});

test('a refused start says why and stays on the page', async () => {
  const ctx = context(DEMO, {ok:false, text:'Triage ORCH-9 is still open.'});
  await ctx.startTriage({currentTarget:{}});
  assert.equal(ctx.location.hash, '#tickets');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.toasts)), [['Refused: Triage ORCH-9 is still open.', 'error']]);
});
