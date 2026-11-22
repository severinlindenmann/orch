// ORCH-1495: take over and give back in the dashboard (pages/livebrowse.js): the stream's page id and owner state
// reach the view and every preview; Take over, Give back and input go to /api/browse/* with that page id and epoch;
// the page that holds control renews its lease; a helper asking for a person is one line on Home.
const test = require('node:test');
const assert = require('node:assert/strict');

const timers = [];
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.setInterval = (f, ms) => { timers.push({f, ms}); return timers.length; };
global.clearInterval = id => { if (timers[id - 1]) timers[id - 1].cleared = true; };
const streams = [];
global.EventSource = class {
  constructor(url) { this.url = url; this.l = {}; streams.push(this); }
  addEventListener(t, f) { this.l[t] = f; }
  emit(t, data) { this.l[t]({data: JSON.stringify(data)}); }
  close() { this.closed = true; }
};
const said = [];
let viewOpts = null;
const fake = name => ({el: {isConnected: true}, hello: d => said.push([name, 'hello', d]), tabs() {}, frame() {}, clear() {}, event() {},
  control: c => said.push([name, 'control', c]), show() {}, end() {}, hide() {}, open() {}, dispose() {}});
global.window = {UI: {browserView: o => { viewOpts = o; return fake('view'); }, browserPeek: () => fake('peek')}, orch: {toast: t => said.push(['toast', t])}};
global.addons = () => [{name: 'browse', dashboard: {label: 'Browser', panel: 'browser'}}];
global.location = {hash: '#home'};
global.render = () => {};
global.document = {querySelector: () => null, querySelectorAll: () => [], hidden: false};
const tree = (tag, props, ...kids) => ({tag, props: props || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false)});
global.h = tree;
global.fragment = (...kids) => tree('#', {}, ...kids);
global.heading = (t, s) => tree('header', {}, t, s);
global.clean = s => String(s);
global.ticketOf = id => ({t_take01: {title: 'Download the October invoices'}})[id] || null;
const lb = require('../src/orch_dashboard/web/pages/livebrowse.js');
const words = n => typeof n === 'string' ? n : (n.kids || []).map(words).join('');

const posts = [];
global.fetch = async (url, o) => {
  posts.push([url, JSON.parse(o.body)]);
  const body = url.endsWith('/give') ? {state: 'helper', epoch: 9, text: 'Given back to the helper. 1 password field(s) on the page were emptied (where orch could reach them).'}
    : url.endsWith('/take') ? {state: 'finishing', epoch: 8, mine: true} : {state: 'person', epoch: 8, sent: 2};
  return {ok: true, text: async () => JSON.stringify(body)};
};

test('the page id and owner state reach the view and every preview; calls name page, generation and epoch', async () => {
  const b = lb.liveBrowseFor('t_take01');
  b.peeks.set('ticket', fake('peek'));
  lb.liveBrowseView('t_take01', b);
  lb.liveBrowseOpen('t_take01', b);
  const es = streams.at(-1);
  es.emit('hello', {generation: '0123456789abcdef', page: 'minted-by-the-broker'});
  assert.equal(b.page, 'minted-by-the-broker');
  es.emit('control', {state: 'helper', epoch: 7, mine: false});
  assert.deepEqual(said.filter(s => s[1] === 'control').map(s => s[0]).sort(), ['peek', 'view']);
  await viewOpts.control.take();
  assert.deepEqual(posts.at(-1), ['/api/browse/take', {ticket: 't_take01', generation: '0123456789abcdef', page: 'minted-by-the-broker', epoch: 7, action: 'take'}]);
  assert.equal(b.ctl.epoch, 8, 'the answer moves the epoch on');
  es.emit('control', {state: 'person', epoch: 8, mine: true});
  const lease = timers.at(-1);
  assert.equal(lease.ms, lb.BROWSE_RENEW_EVERY);
  lease.f();
  await new Promise(r => setImmediate(r));
  assert.equal(posts.at(-1)[1].action, 'renew');
  await viewOpts.control.send([{t: 'move', x: 1, y: 2}], {w: 1280, h: 800});
  assert.deepEqual(posts.at(-1), ['/api/browse/input', {ticket: 't_take01', generation: '0123456789abcdef', page: 'minted-by-the-broker', epoch: 8, w: 1280, h: 800, events: [{t: 'move', x: 1, y: 2}]}]);
  const r = await viewOpts.control.give();
  assert.equal(r.ok, true);
  assert.equal(posts.at(-1)[0], '/api/browse/give');
  assert.ok(said.some(s => s[0] === 'toast' && /password field/.test(s[1])), 'what was emptied is said');
  es.emit('control', {state: 'helper', epoch: 9, mine: false});
  assert.equal(lease.cleared, true, 'no lease once control is given back');
});

test('a refusal comes back as words; nothing is sent before the stream said who drives', async () => {
  const b = lb.liveBrowseFor('t_take02');
  let r = await lb.liveBrowsePost('t_take02', b, 'take', {action: 'take'});
  assert.equal(r.ok, false);
  assert.match(r.text, /still connecting/);
  b.page = 'p'; b.gen = '0123456789abcdef'; b.ctl = {state: 'person', epoch: 3, mine: false};
  const before = global.fetch;
  global.fetch = async () => ({ok: false, text: async () => 'Another page has control of this browser.'});
  r = await lb.liveBrowsePost('t_take02', b, 'input', {w: 1, h: 1, events: []});
  assert.deepEqual(r, {ok: false, text: 'Another page has control of this browser.'});
  global.fetch = before;
});

test('Home: a helper asking for a person is one line with one button; none keeps a hidden host for the list', () => {
  lb.browseList.doc = {on: true, browsers: [{ticket: 't_take01', open: true, asking: 'Please sign in to the supplier portal'}]};
  const banner = lb.browseAskBanner();
  assert.match(words(banner), /The helper needs you in its browser\. Please sign in to the supplier portal · Download the October invoices/);
  const link = banner.kids[0].kids.find(k => k.tag === 'a');
  assert.equal(link.props.href, '#ticket/t_take01?browser=open');
  assert.equal(words(link), 'Open the browser');
  lb.browseList.doc = {on: true, browsers: [{ticket: 't_take01', open: true}]};
  const empty = lb.browseAskBanner();
  assert.equal(empty.props.hidden, true);
  assert.equal(empty.props['data-browse-asks'], '');
});
