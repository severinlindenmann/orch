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
const sess = (id, key, status, extra = {}) => ({id, key, title:'Title of ' + key, status, word:{working:'Working', idle:'Idle', 'in-line':'In line', closed:'No session', 'needs-you':'Needs you'}[status], ...extra});
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
  for (const rule of ['.wall{', '.wall-band{', '.wall-tile{', '.wall-tile[data-s=needs-you]{border-color:var(--needs-you)', '.wall-peek{', '.wall-line{', '.wall-bands[data-many] .wall-lines[data-many]{max-height:']) assert.ok(block.includes(rule), rule);
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

test('ORCH-1471: a preview line cut at the right edge ends with an ellipsis, on the wall peek and in a small result', () => {
  const kit = path.join(KIT);
  const wall = fs.readFileSync(path.join(kit, 'widgets.css'), 'utf8').match(/\.wall-peek\{[^}]*\}/)[0];
  assert.match(wall, /text-overflow:ellipsis/);
  assert.match(fs.readFileSync(path.join(kit, 'results.css'), 'utf8'), /\.result\[data-size=sm\] \.result-ln>span\{[^}]*text-overflow:ellipsis/);
});

// ORCH-1358: the bar, the wall summary and its bands count the same sessions as needing you, and the line under the
// summary says how many helper places are in use (draft D).
test('an idle session that asks counts as needs you in the summary, the band and the bar', () => {
  const W = require('../src/orch_dashboard/web/pages/livewall.js');
  const ls = require('../src/orch_dashboard/web/pages/livesessions.js');
  const list = [sess('t_1', 'ORCH-1', 'idle', {needs:true}), sess('t_2', 'ORCH-2', 'idle'), sess('t_3', 'ORCH-3', 'needs-you'), sess('t_4', 'ORCH-4', 'closed', {needs:true})];
  const c = W.liveWallCounts(list);
  assert.equal(c['needs-you'], 3);
  assert.equal(c.idle, 1);
  assert.equal(c.total, 4);
  assert.equal(W.liveWallBands(list, [], '').need.length, 3);
  const bar = ls.liveBarRows(list, []);
  assert.deepEqual(bar.filter(r => r.s === 'wait').map(r => r.key).sort(), ['ORCH-1', 'ORCH-3', 'ORCH-4']);
  assert.ok(bar.filter(r => r.s === 'wait').every(r => r.word === 'Needs you'));
});

test('the line under the summary says the helper places in use', () => {
  const W = require('../src/orch_dashboard/web/pages/livewall.js');
  assert.equal(W.liveWallTotal(24, {used:8, max:8}), '24 sessions · 8 of 8 helper places in use');
  assert.equal(W.liveWallTotal(1, {used:1, max:1}), '1 session · 1 of 1 helper place in use');
  assert.equal(W.liveWallTotal(5, {used:3, max:null}), '5 sessions · 3 helper places in use');
  assert.equal(W.liveWallPlaces({used:1, max:null}), '1 helper place in use', 'the New menu\'s places line (ORCH-1660)');
  assert.equal(W.liveWallTotal(5, {used:1, max:null}), '5 sessions · 1 helper place in use');
  assert.equal(W.liveWallTotal(5, null), '5 sessions');
});
test('ORCH-1687: an empty band never contradicts the header or the Pinned band', () => {
  const term = {id:'s1', status:'idle', kind:'terminal'};
  const b = wall.liveWallBands([term], ['s1'], '', null);
  assert.equal(b.idle.length, 0);
  assert.equal(wall.liveWallEmpty('idle', 'x', b), 'The idle session is pinned above.');
  assert.equal(wall.liveWallEmpty('idle', 'x', wall.liveWallBands([], [], '', null)), 'Nothing is idle right now.');
  assert.equal(wall.liveWallEmpty('need', 'Nothing needs you and no helper is working right now.', b), 'Nothing needs you and no helper is working right now.');
  const busy = wall.liveWallBands([{id:'t1', status:'working'}], ['t1'], '', null);
  assert.equal(wall.liveWallEmpty('need', 'x', busy), 'Nothing needs you outside Pinned.');
  // a ticket that needs you without a session joins the wall from the needs-you number and sits in the Needs you band
  const joined = wall.liveWallWithNeeds([term, {id:'t3', status:'working'}], [{id:'t2', key:'K-2', title:'Logo', word:'Check'}, {id:'t3', title:'Has a session'}]);
  assert.equal(joined.length, 3, 'a ticket with a session keeps its own entry');
  assert.equal(JSON.stringify(wall.liveWallBands(joined, ['s1'], '', null).need.map(s => s.id)), JSON.stringify(['t2', 't3']));  // the one that asks first
  assert.equal(joined[2].word, 'Check');
  // #1801: an idle session whose ticket the number counts (no needs flag from the server) moves to Needs you too
  const idle = {id:'t4', status:'idle', title:'In Review'};
  const flagged = wall.liveWallWithNeeds([idle, {id:'t5', status:'idle'}], [{id:'t4', word:'Check'}]);
  const fb = wall.liveWallBands(flagged, [], '', null);
  assert.deepEqual(fb.need.map(s => s.id), ['t4']);
  assert.deepEqual(fb.idle.map(s => s.id), ['t5']);
  assert.equal(idle.needs, undefined, 'the sessions list itself is not changed');
  const need = wall.liveWallBands([{id:'t2', status:'closed', needs:true}, term], ['s1'], '', null);
  assert.equal(need.need.length, 1);
  assert.equal(wall.liveWallSummary([{id:'t2', status:'closed', needs:true}], 1)[0].text, '1 needs you');
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livewall.js'), 'utf8');
  assert.doesNotMatch(src, /Every ticket has a working helper/);
});

// ORCH-2045: a result to check without a session sits in Needs you; the filter finds it by "Needs you" (its band and the
// summary's word) and by its own reason ("Check"), in 119 other sessions, pinned or in a group, never twice.
test('the filter finds a result that needs you by "Needs you" and by its reason, and nothing it does not', () => {
  const others = Array.from({length:119}, (_, i) => sess('t_' + i, 'ORCH-' + (3001 + i), ['working', 'in-line', 'idle', 'closed'][i % 4], {title:'Order form ' + i}));
  const list = wall.liveWallWithNeeds(others, [{id:'t_chk', key:'ORCH-412', title:'Price page for schools', word:'Check'}]);
  const hits = (q, pins = [], groups) => { const b = wall.liveWallBands(list, pins, q, groups); return {b, ids:[...b.pin, ...b.need, ...b.queue, ...b.idle].map(s => s.id)}; };
  for (const q of ['Needs you', 'needs YOU', 'Check', 'orch-412', 'schools']) {
    const {b, ids} = hits(q);
    assert.deepEqual(ids, ['t_chk'], q);
    assert.deepEqual(keys(b.need), ['ORCH-412'], q + ' sits in Needs you');
    assert.equal(b.total, 120, 'the total is the workspace, not the hits');
  }
  assert.equal(hits('zebra crossing').b.shown, 0);
  assert.equal(hits('').b.shown, 120, 'cleared: every entry again');
  assert.equal(hits('working').ids.length, 30, '"working" finds the working sessions, never the result that asks');
  assert.deepEqual(hits('Needs you', ['t_chk']).b.pin.map(s => s.id), ['t_chk'], 'pinned: found in Pinned only');
  assert.deepEqual(hits('Needs you', ['t_chk']).ids, ['t_chk']);
  // an idle session whose ticket asks reads "Idle" on its tile and is found by both words
  const idle = wall.liveWallWithNeeds([sess('t_i', 'ORCH-9', 'idle'), sess('t_j', 'ORCH-10', 'idle')], [{id:'t_i', word:'Check'}]);
  assert.deepEqual(keys(wall.liveWallBands(idle, [], 'needs you').need), ['ORCH-9']);
  assert.equal(wall.liveWallBands(idle, [], 'idle').shown, 2);
  // a group whose helper is the result to check: the one group entry is found by "Check" and by "Needs you", once
  const groups = [{id:'g1', key:'ORCH-400', title:'Shop for schools', members:[{id:'t_0', key:'ORCH-3001', title:'Order form 0', status:'working', word:'Working', main:true},
    {id:'t_chk', key:'ORCH-412', title:'Price page for schools', status:'closed', word:'No session'}]}];
  for (const q of ['Check', 'Needs you']) {
    const {b, ids} = hits(q, [], groups);
    assert.deepEqual(ids, ['g1'], q + ' finds the group once, not its tickets on their own');
    assert.equal(b.need[0].status, 'needs-you');
  }
  // the one rule: the band, the counts and the filter agree on who asks
  assert.equal(wall.liveWallAsks({status:'closed', needs:true}), true);
  assert.equal(wall.liveWallAsks({status:'working', needs:true}), false);
  assert.equal(wall.liveWallCounts(list)['needs-you'], 1);
});

test('with a filter, a band without a match is left out and the filter is a plain search box', () => {
  const src = fs.readFileSync(path.join(WEB, 'pages/livewall.js'), 'utf8');
  assert.match(src, /filter\(\(\[id\]\) => b\[id\]\.length \|\| !ui\.f\.trim\(\)\)/);
  // typing only filters what is drawn: no form to submit, no action, no start
  const input = src.slice(src.indexOf("document.addEventListener('input'"), src.indexOf("document.addEventListener('click'"));
  assert.match(input, /liveWallState\(\)\.f = e\.target\.value;\s*liveWallRepaint\(\);/);
  assert.doesNotMatch(input, /fetch|act\(|start|submit/i);
  assert.doesNotMatch(src, /<form|h\('form'/);
});

// Focus polish: the wall says when it is loading, when the sessions did not load, when there are none and when the
// filter finds none; each is the kit's state with one next step, under the filter (keyboard order = visual order).
test('the wall state: loading, error only before the first answer, empty, no match, bands', () => {
  assert.equal(wall.liveWallView(false, false, 0, 0), 'wait');
  assert.equal(wall.liveWallView(false, true, 0, 0), 'error');
  assert.equal(wall.liveWallView(true, true, 3, 3), 'bands', 'a later failed read keeps the sessions on screen');
  assert.equal(wall.liveWallView(true, false, 0, 0), 'empty');
  assert.equal(wall.liveWallView(true, false, 4, 0), 'nomatch');
  assert.equal(wall.liveWallView(true, false, 4, 2), 'bands');
  const src = fs.readFileSync(path.join(WEB, 'pages/livewall.js'), 'utf8');
  const order = ['data-key\':\'wall-head', 'data-key\':\'wall-tools', 'data-key\':\'wall-body'].map(k => src.indexOf(k, src.indexOf('function liveWall()')));
  assert.ok(order.every((n, i) => n > 0 && (!i || n > order[i - 1])), 'summary, then the filter, then the bands');
  for (const k of ['wall-error', 'Try again', 'data-wall-retry', 'Clear filter', 'data-wall-clear', 'skeleton sk-card']) assert.ok(src.includes(k), k);
});

test('a session without a live helper that asks shows the needs-you mark, as the summary counts it', () => {
  for (const status of ['idle', 'closed']) {
    assert.equal(wall.liveWallMark(sess('t_1', 'ORCH-1', status, {needs:true})), 'needs-you', status);
    assert.equal(wall.liveWallMark(sess('t_2', 'ORCH-2', status)), status);
  }
});
