// The live bar under every page (draft D, ORCH-337): which session lands in which group, the counts read right, it is
// loaded and served like the other page modules, it names no add-on, and its look lives in the kit.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const bar = require('../src/orch_dashboard/web/pages/livebar.js');

const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static');
const run = state => ({running:true, helper:{state}, claim:{agent:'agent:claude'}});
const t = (id, key, extra = {}) => ({id, key, title:'Title of ' + key, status:'active', questions:[], ...extra});

test('sessions by state: needs you, working, in line, idle; pinned is taken out of the counts', () => {
  const tickets = [t('t_a', 'ORCH-1'), t('t_b', 'ORCH-2'), t('t_c', 'ORCH-3'), t('t_d', 'ORCH-4'), t('t_e', 'ORCH-5'),
    t('t_f', 'ORCH-6'), t('t_g', 'ORCH-7', {status:'dropped'})];
  const runs = {t_a:run('you'), t_b:run('working'), t_c:{running:false, hold:'Waits for a free place'}, t_d:run('idle'),
    t_e:run('working'), t_g:run('working')};
  const all = bar.liveBarModel(tickets, runs, ['t_e', 't_a'], helpers.helperState);
  assert.deepEqual(all.map(o => [o.key, o.s, o.pin]), [['ORCH-1', 'wait', true], ['ORCH-5', 'run', true], ['ORCH-2', 'run', false],
    ['ORCH-3', 'queue', false], ['ORCH-4', 'idle', false]], 'no helper (ORCH-6) and dropped (ORCH-7) are not sessions');
  const keys = l => all.filter(o => bar.liveBarIn(o, l)).map(o => o.key);
  assert.deepEqual(keys('wait'), ['ORCH-1'], 'needs you wins over pinned');
  assert.deepEqual(keys('pin'), ['ORCH-5']);
  assert.deepEqual(keys('run'), ['ORCH-2']);
  assert.deepEqual(keys('queue'), ['ORCH-3']);
  assert.deepEqual(keys('idle'), ['ORCH-4']);
  assert.deepEqual(keys('more'), ['ORCH-2', 'ORCH-3', 'ORCH-4'], 'More is everything that is not a chip');
  assert.equal(all.find(o => o.key === 'ORCH-3').word, 'In line');
  assert.equal(all.find(o => o.key === 'ORCH-1').word, 'Needs you');
});

test('an open question with the helper at its prompt needs you; nothing running is no session', () => {
  const all = bar.liveBarModel([t('t_a', 'ORCH-1', {questions:[{id:'q1', text:'Which?'}]})],
    {t_a:{running:true, claim:{live:{state:'idle'}}}}, [], helpers.helperState);
  assert.equal(all[0].s, 'wait');
  assert.deepEqual(bar.liveBarModel([t('t_a', 'ORCH-1')], {t_a:{running:false}}, [], helpers.helperState), []);
  assert.deepEqual(bar.liveBarModel(null, null, null, helpers.helperState), []);
});

test('counts read right: "1 session", "2 sessions", "9 in line", "Pinned (1)", "More (20)"', () => {
  assert.equal(bar.liveBarSessions(1), '1 session');
  assert.equal(bar.liveBarSessions(2), '2 sessions');
  assert.equal(bar.liveBarCountText('queue', 9), '9 in line');
  assert.equal(bar.liveBarCountText('run', 1), '1 working');
  assert.equal(bar.liveBarCountText('pin', 1), 'Pinned (1)');
  assert.equal(bar.liveBarCountText('more', 20), 'More (20)');
  assert.equal(bar.liveBarCountText('idle', 8, true), '8');
});

test('loaded before app.js, served as a page module, painted on every render, names no add-on', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  assert.ok(index.indexOf('pages/livebar.js') > 0 && index.indexOf('pages/livebar.js') < index.indexOf('src="app.js"'));
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /\|livebar\)\\\.js/);
  assert.match(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8'), /window\.paintLiveBar\?\.\(\)/);
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.doesNotMatch(src.replace(/\.focus\(\)|focusKey/g, ''), /\b(focus|automation|factory|insights|relay)\b/i, 'found by its live_session capability, never by name');
  assert.match(src, /live_session === true/);
  assert.match(src, /querySelector\('\.shell-body \[data-keep\]'\)/, 'the bar goes into the keep place of soft page changes when it exists');
  assert.match(src, /LiveBar = \{(\s*\/\/[^\n]*\n)+\s*mount\(host/, 'another page can move the bar into its own mount point');
});

test('the look is the kit component, with the gallery entry and the thumbtack icon', () => {
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  for (const rule of ['.lbar{', '.lbar-chip,.lbar-cnt{', '.lbar-pop{', '.lbar-row{', '.lbar-sw{display:flex;flex:1 1 0;flex-wrap:nowrap']) assert.ok(css.includes(rule), rule);
  const block = css.slice(css.indexOf('/* ---- Live bar'));
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgb\(/i, 'tokens only, no colour literals');
  assert.match(fs.readFileSync(path.join(KIT, 'gallery.html'), 'utf8'), /id="live-bar"[\s\S]*data-fold="3"/);
  assert.match(fs.readFileSync(path.join(KIT, 'icons.js'), 'utf8'), /pinned: '/);
  for (const f of ['pages/livebar.js']) assert.doesNotMatch(fs.readFileSync(path.join(WEB, f), 'utf8'), /\bstyle="/);
});

test('plugs into the layer: a chip opens its session there, open ones are marked, the layer fills the right end', () => {
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.match(src, /window\.LiveLayer\.open\(o\.dataset\.lbarOpen\)/, 'a chip or row opens in the layer when it is there');
  assert.match(src, /!e\.metaKey && !e\.ctrlKey && !e\.shiftKey/, 'a new-tab click stays a link');
  assert.match(src, /addEventListener\('orch:live-layer'/, 'the layer says which sessions are open');
  assert.match(src, /'aria-current':bar\.panes\.includes\(o\.id\)/);
  assert.match(src, /end\(fn\) \{/, 'the layer puts Open and Place at the right end');
  assert.match(src, /mount\(host, opts = \{\}\)/);
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  assert.ok(css.includes('.lbar.lbar-docked{position:relative') && css.includes('.lbar-chip[aria-current=true]{'));
});

test('sessions without a ticket (ORCH-364): open ones join the bar by their title, a plain terminal is open until closed', () => {
  const sessions = [
    {id:'t_emp', kind:'empty', title:'Empty helper', open:true},
    {id:'t_chat', kind:'chat', title:'Chat helper', open:false},
    {id:'t_term', kind:'terminal', title:'Plain terminal', open:true},
    {id:'t_man', kind:'manager', title:'Manager', open:true},
    {id:'t_odd', kind:'ticket', title:'Not a kind', open:true},
  ];
  const runs = {t_emp:run('working'), t_man:run('idle')};
  const all = bar.liveBarModel([t('t_a', 'ORCH-1')], {...runs, t_a:run('working')}, ['t_emp', 't_term', 't_man'], helpers.helperState, sessions);
  assert.deepEqual(all.map(o => [o.key || o.title, o.s, o.pin, o.kind]), [['Empty helper', 'run', true, 'empty'], ['ORCH-1', 'run', false, ''],
    ['Plain terminal', 'idle', true, 'terminal'], ['Manager', 'idle', true, 'manager']], 'a closed one and an unknown kind are left out');
  assert.equal(all.find(o => o.kind === 'terminal').word, 'Open');
  assert.deepEqual(all.filter(o => bar.liveBarIn(o, 'pin')).map(o => o.title), ['Empty helper', 'Plain terminal', 'Manager'], 'a new one is pinned: a chip');
  assert.equal(bar.liveBarNewOpen(sessions, 'manager').id, 't_man');
  assert.equal(bar.liveBarNewOpen(sessions, 'chat'), null, 'a closed one starts again');
  assert.equal(bar.liveBarNewOpen(null, 'empty'), null);
  assert.deepEqual(bar.LIVEBAR_NEW.map(n => n.title), ['Empty helper', 'Chat helper', 'Plain terminal', 'Manager'], 'draft D words, in its order');
});

// ORCH-365: the Focus button on every ticket says what pressing it does, from the same session states as the bar.
test('the Focus button word: Answer, Watch, Open, In line, Start; none on a finished ticket without a helper', () => {
  const ask = {questions:[{id:'q1', text:'Which one?'}]};
  const verb = (tk, r) => bar.liveFocusVerb(tk, r, helpers.helperState);
  assert.equal(verb(t('t_a', 'ORCH-1'), run('you')), 'Answer');
  assert.equal(verb(t('t_b', 'ORCH-2'), run('working')), 'Watch');
  assert.equal(verb(t('t_c', 'ORCH-3'), run('idle')), 'Open');
  assert.equal(verb(t('t_d', 'ORCH-4'), {running:false, hold:'Waits for a free place'}), 'In line');
  assert.equal(verb(t('t_e', 'ORCH-5', {status:'ready'}), undefined), 'Start');
  assert.equal(verb(t('t_f', 'ORCH-6', {status:'waiting', ...ask}), undefined), 'Answer', 'an open question with no helper');
  assert.equal(verb(t('t_g', 'ORCH-7', {questions:[{id:'q1', text:'x', answer:'yes'}]}), undefined), 'Start', 'an answered question is not one');
  for (const status of ['done', 'dropped', 'superseded']) assert.equal(verb(t('t_h', 'ORCH-8', {status, ...ask}), undefined), '', status);
  assert.equal(verb(t('t_i', 'ORCH-9', {status:'done'}), run('working')), 'Watch', 'a helper still running on a done ticket can be watched');
  assert.equal(verb(null, null), '');
});

test('the ticket page and every ticket row use the one Focus button; a pane has Open ticket, also in More', () => {
  const read = f => fs.readFileSync(path.join(WEB, 'pages', f), 'utf8');
  const ticket = read('ticket.js'), list = read('tickets.js'), layer = read('live-layer.js');
  assert.equal((ticket.match(/liveFocusButton\(t, true\)/g) || []).length, 2, 'both ticket page headers (working and not)');
  assert.match(list, /function ticketRowFocus/);
  assert.match(list, /ticketRowFocus\(t, nextAction\)/, 'the table row');
  assert.match(list, /function shortSide[^]*?liveFocusButton\(t\)/, 'the phone row');
  assert.match(layer, /function liveFocusButton[^]*?livePreviewOn\(\)/, 'only behind the Preview switch');
  assert.match(layer, /'data-key':'live-open-ticket'/);
  assert.match(layer, /'data-key':'live-more-ticket'/);
});
