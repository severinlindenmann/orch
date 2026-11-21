// The wall of the new live page (draft D, ORCH-360): which session lands in which band, needs you first, the filter,
// the summary words, the peek, the folded bands kept per workspace; loaded and served like the other page modules,
// names no add-on, opens a tile in the layer, and its look lives in the kit.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const wall = require('../src/orch_dashboard/web/pages/livewall.js');

const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static');
const sess = (id, key, status, extra = {}) => ({id, key, title:'Title of ' + key, status, word:{working:'Working', idle:'Idle', 'in-line':'In line', closed:'No session', 'needs-you':'Waits for you'}[status], ...extra});
const keys = list => list.map(s => s.key);

test('bands: pinned, needs you and working (needs you first), in line, idle and no session', () => {
  const list = [sess('t_b', 'ORCH-2', 'working'), sess('t_a', 'ORCH-1', 'needs-you'), sess('t_c', 'ORCH-3', 'in-line'),
    sess('t_d', 'ORCH-4', 'idle'), sess('t_e', 'ORCH-5', 'working'), sess('t_f', 'ORCH-6', 'closed'), sess('t_g', 'ORCH-7', 'needs-you')];
  const b = wall.liveWallBands(list, ['t_e', 't_g']);
  assert.deepEqual(keys(b.pin), ['ORCH-7', 'ORCH-5'], 'a pinned session that needs you stays first in Pinned');
  assert.deepEqual(keys(b.need), ['ORCH-1', 'ORCH-2'], 'needs you before working');
  assert.deepEqual(keys(b.queue), ['ORCH-3']);
  assert.deepEqual(keys(b.idle), ['ORCH-4', 'ORCH-6'], 'idle, then the tickets without a session');
  assert.equal(b.total, 7);
  assert.equal(b.shown, 7);
  const none = wall.liveWallBands(null, null);
  assert.deepEqual([none.pin, none.need, none.queue, none.idle, none.total], [[], [], [], [], 0]);
  assert.equal(wall.liveWallBands([{id:'t_x', status:'gone'}, null, {status:'working'}], []).total, 0, 'unknown or broken rows are left out');
});

test('the filter keeps only matching sessions by key, title or status, and leaves the total alone', () => {
  const list = [sess('t_a', 'ORCH-201', 'needs-you', {title:'Send the weekly summary'}), sess('t_b', 'ORCH-217', 'in-line', {title:'New logo on every page'}),
    sess('t_c', 'ORCH-241', 'idle', {title:'Survey for customers'})];
  assert.deepEqual(keys(wall.liveWallBands(list, [], 'LOGO').queue), ['ORCH-217']);
  assert.equal(wall.liveWallBands(list, [], 'logo').shown, 1);
  assert.equal(wall.liveWallBands(list, [], 'logo').total, 3);
  assert.deepEqual(keys(wall.liveWallBands(list, [], 'orch-24').idle), ['ORCH-241']);
  assert.deepEqual(keys(wall.liveWallBands(list, [], 'needs you').need), ['ORCH-201'], 'the status words match too');
  assert.equal(wall.liveWallBands(list, [], 'nothing like this').shown, 0);
  assert.equal(wall.liveWallBands(list, [], '   ').shown, 3, 'blanks are no filter');
});

test('the summary line reads right: "1 needs you", "3 need you", "Nobody needs you"; counts of every session', () => {
  const one = [sess('a', 'A', 'needs-you'), sess('b', 'B', 'working'), sess('c', 'C', 'idle')];
  assert.deepEqual(wall.liveWallSummary(one).map(p => p.text), ['1 needs you', '1 working', '1 idle']);
  const many = [...one, sess('d', 'D', 'needs-you'), sess('e', 'E', 'needs-you'), sess('f', 'F', 'in-line'), sess('g', 'G', 'closed')];
  assert.deepEqual(wall.liveWallSummary(many).map(p => p.text), ['3 need you', '1 working', '1 in line', '1 idle']);
  assert.deepEqual(wall.liveWallSummary([sess('b', 'B', 'working')]).map(p => [p.s, p.text]), [['', 'Nobody needs you'], ['working', '1 working']]);
  // ORCH-674: the wall reads the same one number as the live bar (results to check count too)
  assert.deepEqual(wall.liveWallSummary([sess('b', 'B', 'working')], 2).map(p => [p.s, p.text]), [['needs-you', '2 need you'], ['working', '1 working']]);
  assert.equal(wall.liveWallSummary(many, 1)[0].text, '3 need you');
  assert.equal(wall.liveWallSessions(1), '1 session');
  assert.equal(wall.liveWallSessions(24), '24 sessions');
  assert.equal(wall.liveWallSessions(0), '0 sessions');
});

test('the peek: the last three lines that say something; none while a question waits or nothing is live', () => {
  const s = sess('a', 'A', 'working', {lines:['one', '', 'two   ', '  ', 'three', 'four']});
  assert.equal(wall.liveWallPeek(s), 'two\nthree\nfour');
  assert.equal(wall.liveWallPeek({...s, status:'needs-you'}), '', 'the tile shows the question instead');
  assert.equal(wall.liveWallPeek(sess('b', 'B', 'in-line', {lines:[]})), '');
  assert.equal(wall.liveWallPeek(sess('c', 'C', 'working', {lines:null})), '');
  assert.equal(wall.liveWallPeek(null), '');
});

test('folded bands are kept per workspace in this browser; broken or foreign data reads as nothing folded', () => {
  const mem = new Map(), store = {getItem:k => mem.get(k) ?? null, setItem:(k, v) => mem.set(k, String(v))};
  assert.deepEqual(wall.liveWallRead(store, 'Pilatus'), {col:{}});
  wall.liveWallWrite(store, 'Pilatus', {col:{queue:true}});
  wall.liveWallWrite(store, 'Rigi', {col:{idle:true, pin:true}});
  assert.deepEqual(wall.liveWallRead(store, 'Pilatus'), {col:{queue:true}});
  assert.deepEqual(wall.liveWallRead(store, 'Rigi'), {col:{pin:true, idle:true}}, 'another workspace on the same port keeps its own (issue 1351)');
  mem.set('orch.live.wall', JSON.stringify({Pilatus:{col:{queue:'yes', evil:true, need:true}}}));
  assert.deepEqual(wall.liveWallRead(store, 'Pilatus'), {col:{need:true}});
  mem.set('orch.live.wall', '{not json');
  assert.deepEqual(wall.liveWallRead(store, 'Pilatus'), {col:{}});
  const broken = {getItem() { throw new Error('private window'); }, setItem() { throw new Error('private window'); }};
  assert.deepEqual(wall.liveWallRead(broken, 'x'), {col:{}});
  assert.doesNotThrow(() => wall.liveWallWrite(broken, 'x', {col:{}}));
});

test('loaded before app.js after the layer, served as a page module, names no add-on, a tile opens in the layer', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), at = f => index.indexOf('pages/' + f);
  assert.ok(at('livewall.js') > at('live-layer.js') && at('livewall.js') > at('livesessions.js') && at('livewall.js') < index.indexOf('src="app.js"'));
  assert.match(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8'), /\|livewall[|)]/);
  const src = fs.readFileSync(path.join(WEB, 'pages/livewall.js'), 'utf8');
  assert.doesNotMatch(src.replace(/\.focus\(/g, ''), /\b(focus|automation|factory|insights|relay)\b/i, 'the wall never names the add-on');
  assert.match(src, /window\.LiveLayer\.open\(open\.dataset\.wallOpen, true\)/, 'zoom: the tile opens in the layer, the keyboard in its pane');
  assert.match(src, /window\.LiveLayer\.beside\(/);
  assert.match(src, /addEventListener\('orch:live-sessions', liveWallRepaint\)/, 'every answer of the sessions API repaints the wall in place');
  assert.doesNotMatch(src, /\bstyle="|innerHTML/);
  assert.match(fs.readFileSync(path.join(WEB, 'pages/live.js'), 'utf8'), /liveWall\(\)/);
});

test('the look is the kit component: tokens only, orange needs-you tiles, a gallery entry and the design note', () => {
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  const block = css.slice(css.indexOf('/* ---- Live wall'));
  assert.ok(block.length > 100, 'the wall block is in widgets.css');
  for (const rule of ['.wall{', '.wall-band{', '.wall-tile{', '.wall-tile[data-s=needs-you]{border-color:var(--needs-you)', '.wall-peek{', '.wall-line{', '.wall-bands[data-many] [data-many]{max-height:']) assert.ok(block.includes(rule), rule);
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgb\(/i, 'tokens only, no colour literals');
  assert.match(block, /prefers-reduced-motion:reduce/);
  assert.match(fs.readFileSync(path.join(KIT, 'gallery.html'), 'utf8'), /id="live-wall"[\s\S]*class="wall-tile" data-s="needs-you"/);
  assert.match(fs.readFileSync(path.join(KIT, 'DESIGN.md'), 'utf8'), /### Live wall \(ORCH-360\)/);
});

test('an idle or closed session whose ticket waits for the person lands in Needs you, first (ORCH-790)', () => {
  const list = [sess('t_a', 'ORCH-1', 'working'), sess('t_b', 'ORCH-2', 'closed', {needs:true}), sess('t_c', 'ORCH-3', 'idle', {needs:true}),
    sess('t_d', 'ORCH-4', 'idle'), sess('t_e', 'ORCH-5', 'needs-you')];
  const b = wall.liveWallBands(list, []);
  assert.deepEqual(keys(b.need), ['ORCH-2', 'ORCH-3', 'ORCH-5', 'ORCH-1']);
  assert.deepEqual(keys(b.idle), ['ORCH-4']);
});
