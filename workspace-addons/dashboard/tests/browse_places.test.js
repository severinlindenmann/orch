// ORCH-1494: where the helper's browser shows (pages/livebrowse.js): the small live preview is the one way in (ticket
// Activity, Focus, ticket chat, Browser page), the live view opens in the ticket next to the steps, the Browser page
// lists every helper's browser (live, then ended today as links), all only while the browser add-on is on.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

global.setTimeout = () => 0;
global.clearTimeout = () => {};
const streams = [];
global.EventSource = class {
  constructor(url) { this.url = url; this.l = {}; streams.push(this); }
  addEventListener(t, f) { this.l[t] = f; }
  emit(t, data) { this.l[t]({data: JSON.stringify(data)}); }
  close() { this.closed = true; }
};
const said = [];
const fake = name => ({el: {isConnected: true}, hello: d => said.push([name, 'hello', d]), tabs: t => said.push([name, 'tabs', t]),
  frame: f => said.push([name, 'frame', f]), clear: () => said.push([name, 'clear']), event: e => said.push([name, 'event', e]),
  show() {}, end: (e, at) => said.push([name, 'end', at]), hide: () => said.push([name, 'hide']), open() {}, dispose() {}});
global.window = {UI: {browserView: () => fake('view'), browserPeek: () => fake('peek')}};
let on = true;
global.addons = () => on ? [{name: 'browse', dashboard: {label: 'Browser', panel: 'browser'}}] : [];
global.location = {hash: '#ticket/t_abc123?browser=open'};
let renders = 0;
global.render = () => { renders += 1; };
global.document = {querySelector: () => null, querySelectorAll: () => [], hidden: false};
const tree = (tag, props, ...kids) => ({tag, props: props || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false)});
global.h = tree;
global.fragment = (...kids) => tree('#', {}, ...kids);
global.heading = (title, sub) => tree('header', {}, title, sub);
global.addonTitle = a => a.dashboard.label;
global.stateNote = (title, text, kind) => tree('state', {kind: kind || 'empty'}, title, text);
global.clean = s => String(s);
global.ticketOf = id => ({t_abc123: {title: 'Check our listing on the partner site'}, t_end0001: {title: 'Look up the delivery times'}})[id] || null;
const lb = require('../src/orch_dashboard/web/pages/livebrowse.js');
const words = n => typeof n === 'string' ? n : (n.kids || []).map(words).join('');
const find = (n, pred) => typeof n !== 'object' ? null : pred(n) ? n : (n.kids || []).map(k => find(k, pred)).find(Boolean) || null;

test('the live view opens in the ticket only when its address asks and the add-on is on', () => {
  assert.equal(lb.browseViewIn('t_abc123'), true);
  assert.equal(lb.browseViewIn('t_other1'), false);
  location.hash = '#ticket/t_abc123?tab=files';
  assert.equal(lb.browseViewIn('t_abc123'), false);
  location.hash = '#ticket/t_abc123?browser=open';
  on = false;
  assert.equal(lb.browseViewIn('t_abc123'), false);
  assert.equal(lb.browsePeekHost('t_abc123', 'ticket'), null, 'no preview while the add-on is off');
  on = true;
  const host = lb.browsePeekHost('t_abc123', 'focus');
  assert.equal(host.props['data-browse-peek'], 't_abc123');
  assert.equal(host.props['data-place'], 'focus');
});

test('a preview says live, a quiet ended line with its time, or nothing', () => {
  const b = lb.liveBrowseFor('t_abc123'), peek = fake('p1');
  said.length = 0;
  assert.equal(lb.browsePeekSay(b, null, peek), false);
  assert.deepEqual(said.at(-1), ['p1', 'hide']);
  assert.equal(lb.browsePeekSay(b, {ticket: 't_abc123', open: false, ended: 1700000000}, peek), false);
  assert.deepEqual(said.at(-1), ['p1', 'end', 1700000000]);
  assert.equal(lb.browsePeekSay(b, {ticket: 't_abc123', open: true, generation: 'a'.repeat(16)}, peek), true);
});

test('one stream feeds the view and every preview; page events reach only the view; a new browser is watched again', () => {
  const b = lb.liveBrowseFor('t_feed01');
  b.peeks.set('ticket', fake('peekA'));
  b.peeks.set('focus', fake('peekB'));
  lb.liveBrowseView('t_feed01', b);
  lb.liveBrowseOpen('t_feed01', b);
  const es = streams.at(-1);
  said.length = 0;
  es.emit('hello', {generation: '0123456789abcdef'});
  es.emit('frame', {jpeg: 'AAAA', w: 1280, h: 800, at: 5});
  es.emit('event', {text: 'The page showed a message and it was closed.'});
  const who = kind => said.filter(s => s[1] === kind).map(s => s[0]).sort();
  assert.deepEqual(who('hello'), ['peekA', 'peekB', 'view']);
  assert.deepEqual(who('frame'), ['peekA', 'peekB', 'view']);
  assert.deepEqual(who('event'), ['view']);
  // a preview made later gets what the stream already said
  const late = fake('late');
  lb.browsePeekSay(b, {ticket: 't_feed01', open: true, generation: '0123456789abcdef'}, late);
  assert.ok(said.some(s => s[0] === 'late' && s[1] === 'frame'));
  es.emit('end', {why: 'closed after 15 minutes without a command', final: true});
  assert.equal(b.final, true);
  assert.ok(said.some(s => s[0] === 'peekA' && s[1] === 'end'));
  const n = streams.length;
  lb.liveBrowseOpen('t_feed01', b);
  assert.equal(streams.length, n, 'an ended browser is not watched again');
  lb.browsePeekSay(b, {ticket: 't_feed01', open: true, generation: 'fedcba9876543210'}, late);
  assert.equal(b.final, false, 'another generation (a new browser) is watched afresh');
});

test('the list is read and the page painted again only when it changed', async () => {
  const doc = {on: true, browsers: [{ticket: 't_abc123', open: true, generation: '0123456789abcdef', started: 1}]};
  global.fetch = async url => { assert.equal(url, '/api/browse/list'); return {ok: true, json: async () => doc}; };
  renders = 0;
  await lb.browseListLoad();
  assert.equal(renders, 1);
  await lb.browseListLoad();
  assert.equal(renders, 1, 'the same list does not paint again');
  assert.equal(lb.browseRow('t_abc123').open, true);
  on = false;
  global.fetch = async () => { throw new Error('must not ask while the add-on is off'); };
  await lb.browseListLoad();
  on = true;
});

test('the Browser page: live ones with their preview, ended today as links, else one empty state', () => {
  const now = Date.now() / 1000, a = {name: 'browse', dashboard: {label: 'Browser'}};
  lb.browseList.doc = {on: true, browsers: [
    {ticket: 't_abc123', open: true, generation: '0123456789abcdef', started: now},
    {ticket: 't_end0001', open: false, ended: now - 60, why: 'stopped by a person'},
    {ticket: 't_old0001', open: false, ended: now - 3 * 86400}]};
  const page = lb.browserListPage(a);
  const text = words(page);
  assert.match(text, /Live now · 1/);
  assert.match(text, /Check our listing on the partner site/);
  assert.match(text, /Ended today · 1/);
  assert.match(text, /Look up the delivery times · ended at/);
  assert.ok(find(page, n => n.props?.['data-browse-peek'] === 't_abc123' && n.props['data-place'] === 'list'));
  assert.ok(find(page, n => n.tag === 'a' && n.props.href === '#ticket/t_end0001'), 'an ended browser is a link to its ticket');
  assert.ok(!find(page, n => n.props?.['data-browse-peek'] === 't_end0001'), 'no picture of an ended browser');
  lb.browseList.doc = {on: true, browsers: []};
  assert.match(words(lb.browserListPage(a)), /No helper is using a browser right now/);
  lb.browseList.doc = {on: false, browsers: []};
  assert.match(words(lb.browserListPage(a)), /not turned on/);
});

test('the places: ticket Activity, Focus pane, ticket chat, the Browser tab; no header button', () => {
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const read = f => fs.readFileSync(path.join(web, f), 'utf8');
  const ticket = read('pages/ticket.js');
  const at = ticket.indexOf("browsePeekHost(t.id, 'ticket')");
  assert.ok(at > 0 && at < ticket.indexOf('ticketProgressBeside(t, planQ') && at < ticket.indexOf('overviewHistory(t, story.entries)'),
    'the preview sits right above the steps, above the Activity');
  assert.match(ticket, /ticketProgressBeside\(t, /);
  assert.match(ticket, /'data-live-browse':t\.id/);
  assert.match(read('pages/ticketchat.js'), /browsePeekHost\(t\.id, 'chat'\)/);
  assert.match(read('pages/live-layer.js'), /browsePeekHost\(sess\.id, 'pane'\)/);
  assert.match(read('pages/live-layer.js'), /mountLiveBrowse\(\)/);
  const settings = read('pages/settings.js');
  assert.match(settings, /panelOf\(id\) === 'browser'/);
  assert.match(settings, /a\.dashboard\.panel !== 'browser'/, 'the Browser tab has no add-on view to fetch');
  assert.equal((ticket.match(/browseSetOpen|browseHref/g) || []).length, 0, 'no header button: the preview is the one way in');
  assert.doesNotMatch(read('pages/livebrowse.js'), /'browse'/, 'the page code names no add-on');
});
