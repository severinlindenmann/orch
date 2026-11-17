// ORCH-151: the Triage button on the Tickets page runs `orch triage --start` and opens the new Triage ticket.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');
const part = src.slice(src.indexOf('const TRIAGE_OPEN'), src.indexOf('function ticketNotFound'));

function context(list, result, snapshot = false) {
  const ctx = {snapshot, list, acts:[], toasts:[], location:{hash:'#tickets'}};
  ctx.tickets = () => ctx.list;
  ctx.h = (tag, attrs, ...kids) => ({tag, attrs, kids});
  ctx.button = (text, cls, click) => ({tag:'button', text, cls, click, attrs:{}, setAttribute(k, v) { this.attrs[k] = v; }});
  ctx.iconEl = name => ({icon:name});
  ctx.href = id => '#ticket/' + id;
  ctx.changeError = r => 'Refused: ' + r.text;
  ctx.window = {orch:{toast:(text, kind) => ctx.toasts.push([text, kind])}};
  ctx.act = async (op, args) => { ctx.acts.push([op, args]); if (result.ok) ctx.list = [...ctx.list, {id:'t_new123', title:'Triage 17 Nov', status:'active'}]; return result; };
  vm.createContext(ctx); vm.runInContext(part, ctx); return ctx;
}

test('the button shows only with open tickets and never on a shared copy', () => {
  assert.equal(context([{id:'a', status:'done'}], {ok:true}).triageButton(), null);
  assert.equal(context([{id:'a', status:'ready'}], {ok:true}, true).triageButton(), null);
  const menu = context([{id:'a', status:'ready'}, {id:'b', status:'open'}], {ok:true}).triageButton();
  assert.equal(menu.attrs['data-key'], 'triage');
  assert.ok(menu.kids[0].kids.includes('Triage'));
  const pop = menu.kids[1];
  assert.match(pop.kids[0].kids[0], /all 2 open tickets/);  // it says what happens before the helper starts
  assert.equal(pop.kids[2].attrs['data-key'], 'triage-start');
  assert.equal(typeof pop.kids[2].click, 'function');  // a real click handler, never an onclick attribute string
});

test('a click starts triage and opens the new Triage ticket', async () => {
  const ctx = context([{id:'a', status:'ready'}], {ok:true});
  const button = {disabled:false};
  await ctx.startTriage({currentTarget:button});
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.acts)), [['triage.start', {}]]);
  assert.equal(ctx.location.hash, '#ticket/t_new123');
  assert.equal(ctx.toasts[0][1], 'ok');
  assert.equal(button.disabled, false);
});

test('a refused start says why and stays on the page', async () => {
  const ctx = context([{id:'a', status:'ready'}], {ok:false, text:'Triage ORCH-9 is still open.'});
  await ctx.startTriage({currentTarget:{}});
  assert.equal(ctx.location.hash, '#tickets');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.toasts)), [['Refused: Triage ORCH-9 is still open.', 'error']]);
});
