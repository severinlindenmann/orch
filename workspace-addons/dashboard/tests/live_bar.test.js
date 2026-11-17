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
  assert.match(src, /LiveBar = \{\s*\/\/[^\n]*\n\s*mount\(host\)/, 'another page can move the bar into its own mount point');
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
