const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const WEB = require('node:path').join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(require('node:path').join(WEB, f), 'utf8');
// app.js (shell) and the page modules share one scope as classic scripts; the checks slice one concatenation.
const source = [read('app.js'), ...['home', 'tickets', 'ticket', 'newticket', 'settings'].map(p => read('pages/' + p + '.js'))].join('\n');
const action = source.slice(source.indexOf('async function act('), source.indexOf('async function refresh('));
function context(fetch, snapshot = false) {
  const ctx = {snapshot, state:{tickets:[{id:'t_abcdef', status:'ready'}]}, starting:new Set(), writing:0, mutation:0, fetch, renders:[], toasts:[]};
  ctx.ticketOf = id => ctx.state.tickets.find(t => t.id === id);
  ctx.render = () => ctx.renders.push({status:ctx.state.tickets[0].status, starting:ctx.starting.has('t_abcdef')});
  ctx.accept = next => { ctx.state = next; };
  ctx.window = {orch:{toast:text => ctx.toasts.push(text)}};
  vm.createContext(ctx); vm.runInContext(action, ctx); return ctx;
}
test('Start moves immediately and reconciles with the server', async () => {
  let resolve;
  const ctx = context(() => new Promise(r => { resolve = r; }));
  const pending = ctx.act('run.start', {ticket:'t_abcdef'});
  assert.equal(ctx.state.tickets[0].status, 'active');
  assert.equal(ctx.starting.has('t_abcdef'), true);
  resolve({status:200, json:async () => ({tickets:[{id:'t_abcdef', status:'review'}]})});
  assert.equal((await pending).ok, true);
  assert.equal(ctx.state.tickets[0].status, 'review');
  assert.equal(ctx.starting.size, 0);
});
test('Start failure restores the status and reports it', async () => {
  const ctx = context(async () => ({status:422, text:async () => 'No agent'}));
  assert.equal((await ctx.act('run.start', {ticket:'t_abcdef'})).ok, false);
  assert.equal(ctx.state.tickets[0].status, 'ready');
  assert.equal(ctx.toasts.length, 1);
  assert.equal(ctx.writing, 0);
});
test('snapshot actions never fetch or alter tickets', async () => {
  const ctx = context(() => { throw Error('network'); }, true);
  assert.equal((await ctx.act('run.start', {ticket:'t_abcdef'})).ok, false);
  assert.equal(ctx.state.tickets[0].status, 'ready');
});
const initSource = read('app.js').slice(read('app.js').lastIndexOf('if (snapshot) accept('));
const refSource = source.slice(source.indexOf('function referenceRow('), source.indexOf('async function startLinkAdd('));
function referenceContext(snapshot) {
  const ctx = {snapshot, array:x => x || [], ticketOf:() => ({id:'t_other01', title:'Current title', status:'review'}), clean:x => x, statusWord:() => 'Review', href:id => '#ticket/' + id, iconEl:x => x, h:(tag, attrs, ...children) => ({tag, attrs, children})};
  vm.createContext(ctx); vm.runInContext(refSource, ctx); return ctx;
}
test('snapshot file and artifact references have no opening action', () => {
  const ctx = referenceContext(true);
  for (const ref of [{kind:'file', path:'docs/a.md'}, {kind:'file', path:'/local/a.md', local:true}, {kind:'artifact', ticket:'t_other01', name:'a.md'}]) {
    const row = ctx.referenceRow({refs:[ref]}, ref, true);
    assert.equal(row.children[0].tag, 'span');
    assert.equal(row.children[0].attrs['data-action'], undefined);
  }
});
test('live local files stay text, project files use stored indices and tickets resolve current titles', () => {
  const ctx = referenceContext(false);
  const ref = {kind:'file', path:'docs/a.md'};
  const row = ctx.referenceRow({id:'t_abcdef', refs:[{}, ref]}, ref, false);
  assert.equal(row.children[0].attrs['data-n'], 2);
  assert.equal(row.children[0].attrs['data-action'], 'ref-preview');
  assert.equal(ctx.referenceRow({refs:[ref]}, {...ref, local:true}, false).children[0].tag, 'span');
  const ticket = ctx.referenceRow({refs:[]}, {kind:'ticket', ticket:'t_other01'}, false);
  assert.equal(ticket.children[0].attrs.href, '#ticket/t_other01');
  assert.match(JSON.stringify(ticket), /Current title/);
  assert.match(JSON.stringify(ticket), /Review/);
});
test('push uses a 50 ms debounce and changes polling only while live', () => {
  const streams = [], intervals = [], timeouts = new Map();
  let refreshed = 0, nextTimer = 0;
  const ctx = {
    snapshot:false, window:{addEventListener() {}}, refresh:() => { refreshed++; },
    setInterval:(_, ms) => { intervals.push(ms); return intervals.length; }, clearInterval() {},
    setTimeout:(fn, ms) => { assert.equal(ms, 50); timeouts.set(++nextTimer, fn); return nextTimer; }, clearTimeout:id => timeouts.delete(id),
    EventSource:class { constructor(url) { assert.equal(url, '/api/events'); streams.push(this); } addEventListener(event, fn) { assert.equal(event, 'rev'); this.rev = fn; } },
  };
  vm.createContext(ctx);
  vm.runInContext(initSource, ctx);
  assert.equal(refreshed, 1);
  streams[0].onopen(); assert.equal(intervals.at(-1), 20000);
  streams[0].rev(); streams[0].rev(); assert.equal(timeouts.size, 1);
  [...timeouts.values()][0](); assert.equal(refreshed, 2);
  streams[0].onerror(); assert.equal(intervals.at(-1), 3000);
  ctx.snapshot = true; ctx.accept = () => {}; ctx.window.ORCH_SNAPSHOT = {};
  vm.runInContext(initSource, ctx);
  assert.equal(streams.length, 1);
});
