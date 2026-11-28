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
  assert.match(words(lb.browserListPage(a)), /The browser is turned off in this workspaceTurn it on again in Settings, under Add-ons\./);
});

test('the Browser page says when the list did not load, with Try again, instead of loading on', async () => {
  const a = {name: 'browse', dashboard: {label: 'Browser'}};
  lb.browseList.doc = null; lb.browseList.sig = ''; lb.browseList.failed = false;
  global.fetch = async () => ({ok: false, status: 502, json: async () => ({})});
  renders = 0;
  await lb.browseListLoad();
  assert.equal(renders, 1, 'the page paints the error once');
  const err = find(lb.browserListPage(a), n => n.tag === 'state');
  assert.equal(err.props.kind, 'error');
  assert.match(words(err), /The browsers did not load/);
  await lb.browseListLoad();
  assert.equal(renders, 1, 'a second miss does not paint again');
  global.fetch = async () => ({ok: true, json: async () => ({on: true, browsers: []})});
  await lb.browseListLoad();
  assert.equal(renders, 2, 'the list that loads later replaces the error');
  assert.match(words(lb.browserListPage(a)), /No helper is using a browser right now/);
});

test('the places: ticket Activity, Focus pane, ticket chat, the Browser tab; no header button', () => {
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const read = f => fs.readFileSync(path.join(web, f), 'utf8');
  const ticket = read('pages/ticket.js');
  const at = ticket.indexOf("browsePeekHost(t.id, 'ticket')");
  assert.ok(at > 0 && at < ticket.indexOf('ticketProgressBeside(t, progress),') && at < ticket.indexOf('overviewHistory(t, story.entries)'),
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

// ---- O-20, O-21 (owner, 28 Nov): Allowed sites on the Browser page, and a browser you open yourself ----
global.chip = (text, cls) => tree('chip', {className: cls || ''}, text);
const A = {name: 'browse', dashboard: {label: 'Browser'}};
const sitesDoc = (workspace, tickets = []) => ({on: true, workspace, tickets, max: 5000});
const reset = doc => Object.assign(lb.browseSites, {doc, busy: false, tried: true, failed: false, query: '', draft: '', check: null, saving: false, said: '', error: '', address: '', opening: false, openError: ''});

test('O-21: the allowed sites show where each comes from, with a count', () => {
  reset(sitesDoc(['20min.ch', 'sbb.ch'], [{ticket: 't_abc123', title: 'ignored', sites: ['docs.python.org']}]));
  const card = lb.browseSitesCard(), text = words(card);
  assert.match(text, /Allowed sites · 3 sites/);
  assert.deepEqual(lb.browseSiteRows(lb.browseSites.doc).map(r => [r.site, r.source]),
    [['20min.ch', 'Workspace'], ['sbb.ch', 'Workspace'], ['docs.python.org', 'Ticket: Check our listing on the partner site']]);
  const remove = find(card, n => n.props?.['data-browse-act'] === 'remove' && n.props['data-site'] === 'docs.python.org');
  assert.equal(remove.props['data-scope'], 'ticket'); assert.equal(remove.props['data-ticket'], 't_abc123');
  assert.equal(remove.props['aria-label'], 'Remove docs.python.org');
  assert.match(text, /“\*\.20min\.ch” is stored as 20min\.ch/); assert.match(text, /Only a person changes the list/);
  assert.ok(!find(card, n => n.props?.['data-browse-field'] === 'query'), 'three sites need no search field');
});

test('O-21: 1,000 sites are a count, a search and twenty rows, never 1,000 rows', () => {
  reset(sitesDoc(Array.from({length: 1000}, (_, i) => 'site' + i + '.example.org')));
  let card = lb.browseSitesCard();
  const rows = n => { const out = []; (function walk(x) { if (x && x.props && x.props.role === 'listitem') out.push(x); (x && x.kids || []).forEach(walk); })(n); return out; };
  assert.match(words(card), /Allowed sites · 1,000 sites/);
  assert.equal(rows(card).length, lb.BROWSE_SITE_ROWS);
  assert.match(words(card), /And 980 more sites\. Search to find one\./);
  assert.ok(find(card, n => n.props?.['data-browse-field'] === 'query'));
  lb.browseSites.query = '*.site999.example';             // a wildcard is read as the site it means
  card = lb.browseSitesCard();
  assert.equal(rows(card).length, 1); assert.match(words(card), /site999\.example\.org/); assert.doesNotMatch(words(card), /more sites/);
  lb.browseSites.query = 'nothing-like-this';
  assert.match(words(lb.browseSitesCard()), /No site matches “nothing-like-this”\./);
});

test('O-21: empty, loading and failed states of the list', () => {
  reset(sitesDoc([]));
  assert.match(words(lb.browseSitesCard()), /No site is allowed yetAdd the sites your helpers and you may open\. Nothing else opens\./);
  reset(null); lb.browseSites.busy = true;
  assert.match(words(lb.browseSitesCard()), /Allowed sitesLoading…/);
  reset(null); lb.browseSites.failed = true;
  const err = find(lb.browseSitesCard(), n => n.tag === 'state');
  assert.equal(err.props.kind, 'error'); assert.match(words(err), /The allowed sites did not load/);
});

test('O-21: a clean entry is added with one click; a pasted list is read first and shows what is stored', async () => {
  const posts = [];
  const answer = body => body.check
    ? (body.add === 'example.com' ? {new: ['example.com'], known: 0, changed: [], refused: [], refused_count: 0, repeats: 0, saved: false}
      : {new: ['20min.ch', 'www.nzz.ch'], known: 1, changed: [{entry: '*.20min.ch', site: '20min.ch'}, {entry: 'https://www.NZZ.ch/x', site: 'www.nzz.ch'}],
        refused: [{entry: '10.0.0.1', why: '10.0.0.1 is an address; give the site\'s name'}], refused_count: 1, repeats: 0, saved: false})
    : {new: body.add, known: 0, changed: [], refused: [], refused_count: 0, repeats: 0, saved: true};
  global.fetch = async (url, o) => {
    if (!o) return {ok: true, json: async () => sitesDoc(['sbb.ch'])};
    const body = JSON.parse(o.body); posts.push([url, body]);
    return {ok: true, status: 200, text: async () => JSON.stringify(answer(body))};
  };
  reset(sitesDoc(['sbb.ch'])); lb.browseSites.draft = 'example.com';
  await lb.browseSitesAdd(false);
  assert.deepEqual(posts.map(p => [p[1].add, p[1].check]), [['example.com', true], [['example.com'], false]]);
  assert.equal(lb.browseSites.draft, ''); assert.equal(lb.browseSites.said, 'Added 1 site.'); assert.equal(lb.browseSites.check, null);
  posts.length = 0; lb.browseSites.draft = '*.20min.ch https://www.NZZ.ch/x sbb.ch 10.0.0.1';
  await lb.browseSitesAdd(false);
  assert.equal(posts.length, 1, 'nothing is saved before the person has seen the reading');
  const note = words(lb.browseCheckNote(lb.browseSites.check));
  assert.match(note, /2 sites to add · 1 is on the list already\./);
  assert.match(note, /Stored as: \*\.20min\.ch → 20min\.ch, https:\/\/www\.NZZ\.ch\/x → www\.nzz\.ch/);
  assert.match(note, /1 entry cannot be a site: 10\.0\.0\.1 \(10\.0\.0\.1 is an address; give the site's name\)\. They are left out\./);
  assert.match(note, /Add 2 sites/);
  await lb.browseSitesAdd(true);
  assert.deepEqual(posts.at(-1)[1], {scope: 'workspace', ticket: null, add: ['20min.ch', 'www.nzz.ch'], remove: [], check: false});
  assert.equal(lb.browseSites.said, 'Added 2 sites.');
});

test('O-21: Remove names the list it came from; a refusal is said next to the list', async () => {
  const posts = [];
  global.window.orch = {toast() {}};
  global.fetch = async (url, o) => { if (!o) return {ok: true, json: async () => sitesDoc([])}; posts.push(JSON.parse(o.body)); return {ok: true, status: 200, text: async () => '{"saved":true,"removed":1}'}; };
  reset(sitesDoc(['sbb.ch']));
  await lb.browseSitesRemove('sbb.ch', 'workspace', null);
  await lb.browseSitesRemove('docs.python.org', 'ticket', 't_abc123');
  assert.deepEqual(posts.map(p => [p.scope, p.ticket, p.remove]), [['workspace', null, ['sbb.ch']], ['ticket', 't_abc123', ['docs.python.org']]]);
  global.fetch = async (url, o) => o ? {ok: false, status: 409, text: async () => 'A list holds at most 5000 sites. Remove some first.'} : {ok: true, json: async () => sitesDoc([])};
  global.window.DashHelpers = undefined;
  reset(sitesDoc(['sbb.ch'])); lb.browseSites.draft = 'x.example.org';
  await lb.browseSitesAdd(false);
  assert.match(words(lb.browseSitesCard()), /A list holds at most 5000 sites\. Remove some first\./);
});

test('O-20: Open a browser is the page\'s action, only with an allowed site; a refusal says what to do', async () => {
  reset(sitesDoc([]));
  lb.browseList.doc = {on: true, browsers: []};
  let page = lb.browserListPage(A), open = find(page, n => n.props?.['data-browse-act'] === 'open');
  assert.equal(words(open), 'Open a browser'); assert.equal(open.props.disabled, true);
  assert.match(words(page), /No site is allowed yet\. Add one under Allowed sites first\./);
  reset(sitesDoc(['20min.ch', 'sbb.ch']));
  page = lb.browserListPage(A); open = find(page, n => n.props?.['data-browse-act'] === 'open');
  assert.equal(open.props.disabled, false); assert.equal(open.props.className, 'btn primary');
  assert.match(words(page), /Your browser/); assert.match(words(page), /Only the allowed sites open/);
  const sent = [];
  global.fetch = async (url, o) => { if (url === '/api/browse/open') { sent.push(JSON.parse(o.body)); return {ok: false, status: 409, text: async () => 'evil.example is not on the allowed sites. Add it under Allowed sites first.'}; } return {ok: true, json: async () => ({on: true, browsers: []})}; };
  lb.browseSites.address = 'evil.example';
  await lb.browseOpenOwn();
  assert.deepEqual(sent, [{address: 'evil.example'}]);
  assert.match(words(lb.browserListPage(A)), /evil\.example is not on the allowed sites\. Add it under Allowed sites first\./);
  global.fetch = async (url, o) => { if (url === '/api/browse/open') { sent.push(JSON.parse(o.body)); return {ok: true, status: 200, text: async () => '{"ticket":"t_chat01","site":"20min.ch"}'}; } return {ok: true, json: async () => ({on: true, browsers: []})}; };
  lb.browseSites.address = '';
  await lb.browseOpenOwn();
  assert.deepEqual(sent.at(-1), {address: '20min.ch'}, 'no address typed: the first allowed site');
  assert.equal(lb.browseSites.openError, '');
});

test('O-20: your open browser is "Your browser" with Close and the live view, apart from the helpers\' list', () => {
  reset(sitesDoc(['20min.ch']));
  lb.browseList.doc = {on: true, browsers: [
    {ticket: 't_chat01', open: true, own: true, generation: 'aaaaaaaaaaaaaaaa', started: 5},
    {ticket: 't_abc123', open: true, generation: '0123456789abcdef', started: 4}]};
  const page = lb.browserListPage(A);
  const close = find(page, n => n.props?.['data-browse-act'] === 'close');
  assert.equal(words(close), 'Close'); assert.equal(close.props['data-ticket'], 't_chat01'); assert.equal(close.props['data-generation'], 'aaaaaaaaaaaaaaaa');
  const view = find(page, n => n.props?.['data-live-browse'] === 't_chat01');
  assert.equal(view.props['data-own'], 'yes');
  assert.match(words(page), /Live now · 1/);
  assert.ok(!find(page, n => n.props?.['data-browse-peek'] === 't_chat01'), 'your own browser is not listed again as a helper\'s');
  assert.equal(words(find(page, n => n.props?.['data-browse-act'] === 'open')), 'Go');
});

test('the Browser page has one filled button, also while a pasted list waits for its Add', () => {
  reset(sitesDoc(['20min.ch']));
  lb.browseSites.check = {new: ['nzz.ch'], known: 0, changed: [{entry: '*.nzz.ch', site: 'nzz.ch'}], refused: [], refused_count: 0, repeats: 0};
  lb.browseList.doc = {on: true, browsers: []};
  const filled = [];
  (function walk(n) { if (n && n.props && /\bbtn primary\b/.test(n.props.className || '')) filled.push(words(n)); (n && n.kids || []).forEach(walk); })(lb.browserListPage(A));
  assert.deepEqual(filled, ['Open a browser']);
});
