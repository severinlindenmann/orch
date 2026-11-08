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
    main:{replaceChildren(node) { assert.equal(node, 'loading'); }}, loadingView:() => 'loading',
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

const ticketsSource = read('pages/tickets.js');
const homeSource = read('pages/home.js');
test('ticket search matches title, key, owner and note; Mine excludes agents', () => {
  const ctx = vm.createContext({});
  vm.runInContext(ticketsSource.slice(ticketsSource.indexOf('function filterTickets'), ticketsSource.indexOf('function filteredTickets')), ctx);
  const items = [{id:'a', title:'Launch', owner:'agent:claude'}, {id:'b', key:'PIL-2', owner:'human:me', note:'Invoice'}, {id:'c', owner:''}, {id:'d', owner:'Sam'}];
  for (const [query, mine, ids] of [[' LAUNCH ', false, ['a']], ['pil-2', true, ['b']], ['invoice', false, ['b']], ['SAM', true, ['d']], ['', true, ['b','c','d']], ['missing', false, []]]) {
    assert.deepEqual(Array.from(ctx.filterTickets(items, query, mine), t => t.id), ids);
  }
  const linked = ctx.ticketParents([{id:'p', children:['a','b']}, {id:'a'}, {id:'b', parent:'other'}]);
  assert.equal(linked[1].parent, 'p'); assert.equal(linked[2].parent, 'other');
});

// A small DOM double exercises the page controls without a browser dependency.
function pageContext(snapshot = false) {
  class Element {
    constructor(tag, attrs = {}, ...children) { this.tag = tag; this.attrs = attrs; this.dataset = {}; this.children = children.flat(Infinity).filter(x => x != null); this.disabled = false; }
    querySelectorAll(tag) { return this.children.flatMap(c => c instanceof Element ? [...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag)] : []); }
    replaceChildren(...children) { this.children = children; }
  }
  const connection = {hidden:true}, toasts = [], calls = [];
  const t = {id:'t_one', title:'Launch', questions:[{id:'q1', text:'Which greeting?'}]};
  const ctx = {snapshot, state:{runs:{}}, locks:new Set(), document:{getElementById:() => connection},
    h:(...args) => new Element(...args), button:(label, cls, click) => Object.assign(new Element('button', {}, label), {click}),
    array:v => Array.isArray(v) ? v : [], clean:x => x, ticketOf:() => t, ticketTitle:() => new Element('h3'), parentLine:() => null,
    window:{DashHelpers:{needAction:() => ({label:'Answer'}), plainWhy:text => text}, orch:{toast:text => toasts.push(text)}}, render:() => calls.push('render'), refresh:() => calls.push('refresh')};
  vm.createContext(ctx);
  vm.runInContext(homeSource.slice(homeSource.indexOf('function changeUnavailable'), homeSource.indexOf('function ticketTitle')), ctx);
  vm.runInContext(homeSource.slice(homeSource.indexOf('function needRow'), homeSource.indexOf('function workingRow')), ctx);
  vm.runInContext(homeSource.slice(homeSource.indexOf('function loadingView'), homeSource.indexOf('// Chat (former General)')), ctx);
  return {ctx, connection, toasts, calls};
}
test('inline options send the question and selected answer, disable together, and unlock', async () => {
  const {ctx, toasts, calls} = pageContext();
  let complete, sent;
  ctx.act = (op, args) => { sent = {op, ...args}; return new Promise(resolve => { complete = resolve; }); };
  const row = ctx.needRow({id:'n1', ticket:'t_one', answer:{question:'q1', options:['Hi','Hello'], recommended:'Hi'}});
  const buttons = row.querySelectorAll('button');
  assert.equal(buttons.length, 2); assert.equal(buttons[0].children[0], 'Hi · Suggested');
  const pending = buttons[0].click({currentTarget:{closest:() => row}});
  assert.ok(buttons.every(b => b.disabled));
  assert.deepEqual(sent, {op:'answer', ticket:'t_one', question:'q1', answer:'Hi'});
  complete({ok:true}); await pending;
  assert.ok(buttons.every(b => !b.disabled)); assert.deepEqual(toasts, ['Answered']); assert.deepEqual(calls, ['render']);
});
test('offline answers do not send; network failures show the plain message; snapshots have no answer buttons', async () => {
  const {ctx, connection, toasts} = pageContext();
  const data = {id:'n1', ticket:'t_one', answer:{question:'q1', options:['Hi']}};
  let sent = 0; ctx.act = async () => { sent++; return {ok:false, status:0}; };
  const row = ctx.needRow(data), control = row.querySelectorAll('button')[0], event = {currentTarget:{closest:() => row}};
  connection.hidden = false; await control.click(event); assert.equal(sent, 0);
  connection.hidden = true; await control.click(event); assert.equal(sent, 1);
  assert.ok(toasts.every(text => text === "Can't reach orch. Your change was not sent."));
  assert.equal(pageContext(true).ctx.needRow(data).querySelectorAll('button').length, 0);
});
test('loading is keyed and busy; connection notice offers retry and details', () => {
  const {ctx, connection, calls} = pageContext();
  const loading = ctx.loadingView();
  assert.equal(loading.attrs['data-key'], 'loading'); assert.equal(loading.attrs['aria-busy'], 'true');
  connection.replaceChildren = (...children) => { connection.children = children; };
  ctx.connectionNotice(connection, false);
  assert.equal(connection.hidden, false); assert.match(connection.children[0].children[0], /Can't reach orch yet/);
  connection.children[1].click(); assert.deepEqual(calls, ['refresh']);
  ctx.connectionNotice(connection, true); assert.match(connection.children[0].children[0], /Showing the last update/);
});
