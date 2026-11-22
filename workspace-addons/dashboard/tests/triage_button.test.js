// ORCH-151: the Triage menu on the Tickets page: pick the lanes, Start triage runs `orch triage --start --lanes`
// and opens the new Triage ticket.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const helpers = require('../src/orch_dashboard/web/helpers.js');
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
  ctx.window = {orch:{toast:(text, kind) => ctx.toasts.push([text, kind])}, DashHelpers:helpers};
  ctx.runResult = {ok:true};
  ctx.act = async (op, args, opts) => {
    ctx.acts.push([op, args, opts || null]);
    if (op === 'run.start') { ctx.hashAtRun = ctx.location.hash; return ctx.runResult; }
    if (result.ok) ctx.list = [...ctx.list, {id:'t_new123', title:'Triage 17 Nov', status:'open'}];
    return result.ok ? {...result, state:{created:{id:'t_new123'}}} : result;
  };
  vm.createContext(ctx); vm.runInContext(part, ctx); return ctx;
}
const DEMO = [{id:'a', status:'open'}, {id:'b', status:'active'}, {id:'c', status:'waiting', questions:[{answer:null}]},
  {id:'d', status:'review'}, {id:'e', status:'done'}, {id:'f', status:'dropped', superseded_by:'a'}];

test('lanes follow the board: backlog, working, needs you, check, done, superseded', () => {
  const ctx = context(DEMO, {ok:true});
  assert.deepEqual(DEMO.map(t => ctx.triageLane(t)), ['backlog', 'working', 'needs-you', 'check', 'done', 'superseded']);
  assert.equal(ctx.triageLane({status:'waiting', waiting_on:{kind:'time', until:'2026-12-01'}}), 'waiting');
  assert.equal(ctx.triageLane({status:'dropped'}), 'wont-do');
  assert.equal(ctx.triageLane({status:'ready'}), 'todo');
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

test('a click opens the new Triage ticket by id at once, then starts the helper there (ORCH-1096)', async () => {
  const ctx = context(DEMO, {ok:true});
  const button = el('button', {}, ['Start triage']);
  button.replaceChildren = (...kids) => { button.kids = kids; };
  button.removeAttribute = k => { delete button.attrs[k]; };
  button.getAttribute = k => button.attrs[k];
  const seen = [];
  const plain = ctx.act; ctx.act = async (op, args, opts) => { seen.push([op, button.attrs['aria-busy'], JSON.stringify(button.kids)]); return plain(op, args, opts); };
  await ctx.startTriage({currentTarget:button});
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.acts)), [
    ['triage.start', {lanes:['backlog', 'todo', 'working', 'needs-you', 'waiting', 'check']}, null],
    ['run.start', {ticket:'t_new123'}, {quiet:true}]]);
  // busy with the spinner and "Starting…" while orch opens the ticket; plain again afterwards
  assert.equal(seen[0][1], 'true'); assert.match(seen[0][2], /spinner/); assert.match(seen[0][2], /Starting…/);
  assert.equal(button.attrs['aria-busy'], undefined); assert.deepEqual(button.kids, ['Start triage']);
  assert.equal(ctx.hashAtRun, '#ticket/t_new123');  // the ticket is open before the helper starts
  assert.equal(ctx.location.hash, '#ticket/t_new123');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.toasts)), [['Triage started: a helper is going through the tickets', 'ok']]);
});

test('a helper that waits in line or fails to start is said on the open ticket', async () => {
  const ctx = context(DEMO, {ok:true});
  ctx.runResult = {ok:false, queued:true, text:'waits in line'};
  await ctx.startTriage({currentTarget:null});
  assert.equal(ctx.location.hash, '#ticket/t_new123');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.toasts)), [['The Triage ticket is open and waits for a free helper.', 'ok']]);
  const bad = context(DEMO, {ok:true});
  bad.runResult = {ok:false, text:'No helper is set up.'};
  await bad.startTriage({currentTarget:null});
  assert.deepEqual(JSON.parse(JSON.stringify(bad.toasts)), [['The Triage ticket is open, but the helper did not start: No helper is set up.', 'error']]);
});

test('a refused start says why and stays on the page', async () => {
  const ctx = context(DEMO, {ok:false, text:'Triage ORCH-9 is still open.'});
  await ctx.startTriage({currentTarget:null});
  assert.equal(ctx.location.hash, '#tickets');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.toasts)), [['Refused: Triage ORCH-9 is still open.', 'error']]);
});

test('a redraw while orch opens the ticket keeps Starting…, and a second click sends nothing', async () => {
  const ctx = context(DEMO, {ok:true});
  let release; const plain = ctx.act;
  ctx.act = (op, args, opts) => op === 'triage.start' ? new Promise(r => { release = () => r(plain(op, args, opts)); }) : plain(op, args, opts);
  const first = ctx.startTriage({currentTarget:null});
  const redrawn = find(ctx.triageButton(), 'triage-start');
  assert.equal(redrawn.attrs['aria-busy'], 'true'); assert.equal(redrawn.disabled, true);
  await ctx.startTriage({currentTarget:null});
  release(); await first;
  assert.equal(ctx.acts.filter(a => a[0] === 'triage.start').length, 1);
  assert.equal(find(ctx.triageButton(), 'triage-start').attrs['aria-busy'], undefined);
});

test('with the kit starting moment (UI.launch) the menu shows its steps; a refusal brings the menu back', async () => {
  for (const ok of [true, false]) {
    const ctx = context(DEMO, ok ? {ok:true} : {ok:false, text:'No.'});
    const made = [];
    ctx.window.UI = {launch:o => { const l = {o, el:{launch:true}, at:0, failed:false, step(i) { l.at = i; }, fail() { l.failed = true; }}; made.push(l); return l; }};
    const row = {hidden:false}, pop = {children:[row], appended:[], append(x) { pop.appended.push(x); }};
    const button = el('button', {}, ['Start triage']);
    button.closest = sel => sel === '.menu-pop' ? pop : null;
    await ctx.startTriage({currentTarget:button});
    assert.deepEqual([...made[0].o.steps], ['Making the Triage list', 'Opening it']);
    assert.equal(pop.appended[0], made[0].el);
    if (ok) { assert.equal(made[0].at, 1); assert.equal(row.hidden, true); assert.equal(ctx.location.hash, '#ticket/t_new123'); }
    else { assert.equal(made[0].failed, true); assert.equal(row.hidden, false); assert.equal(ctx.location.hash, '#tickets'); }
  }
});
