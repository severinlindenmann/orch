'use strict';
// ORCH-345: groups on the new live page (draft A on draft D): an epic or a factory order is one tile on the wall and
// one chip in the bar with the same helper count, a click opens the helper that needs you, the filter finds a group by
// any helper, a pane's switcher swaps the session in that pane, and the message box names who receives it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const G = require('../src/orch_dashboard/web/pages/livegroups.js');
const wall = require('../src/orch_dashboard/web/pages/livewall.js');
const {liveBarRows} = require('../src/orch_dashboard/web/pages/livesessions.js');

const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static');
const m = (id, key, title, status, extra = {}) => ({id, key, title, depth:1, main:false, status, word:{working:'Working', idle:'Idle', 'in-line':'In line', closed:'No session', 'needs-you':'Waits for you'}[status], small:[], ...extra});
const EPIC = {id:'t_ep', key:'ORCH-300', title:'Autumn newsletter', kind:'epic', members:[
  m('t_ep', 'ORCH-300', 'Autumn newsletter', 'working', {depth:0, main:true}),
  m('t_tx', 'ORCH-301', 'Write the texts', 'working', {small:[{what:'Draft intro', seconds:180}, {what:'Draft offers', seconds:60}]}),
  m('t_mp', 'ORCH-302', 'Build the mail page', 'needs-you'),
  m('t_st', 'ORCH-303', 'Send a test to the team', 'closed'),
  m('t_ck', 'ORCH-304', 'Check the links', 'in-line'),
]};
const sess = (id, key, status, extra = {}) => ({id, key, title:'Title of ' + key, status, word:'W', ...extra});
// the API's order: needs you, working, in line, idle; a group member's session is in the list like any other
const SESSIONS = [sess('t_mp', 'ORCH-302', 'needs-you'), sess('t_zz', 'ORCH-9', 'needs-you'), sess('t_ep', 'ORCH-300', 'working'),
  sess('t_tx', 'ORCH-301', 'working'), sess('t_ot', 'ORCH-12', 'working'), sess('t_ck', 'ORCH-304', 'in-line')];

test('counts and the one line the tile, the chip and the switcher share', () => {
  assert.deepEqual(G.liveGroupCounts(EPIC), {helpers:3, small:2, need:1, line:1});
  assert.equal(G.liveGroupLine(EPIC), '3 helpers · 2 small helpers · 1 in line · 1 needs you');
  assert.equal(G.liveGroupLine({members:[m('a', '', 'A', 'working', {main:true})]}), '1 helper');
  assert.equal(G.liveGroupStatus(EPIC), 'needs-you', 'one helper that needs you makes the whole group need you');
  assert.equal(G.liveGroupStatus({members:[m('a', '', 'A', 'in-line'), m('b', '', 'B', 'idle')]}), 'idle');
});

test('a click opens the helper that needs you, else the main helper, else the first live one', () => {
  assert.equal(G.liveGroupFocus(EPIC), 't_mp');
  const calm = {...EPIC, members:EPIC.members.map(x => x.status === 'needs-you' ? {...x, status:'working'} : x)};
  assert.equal(G.liveGroupFocus(calm), 't_ep');
  const noMain = {...calm, members:calm.members.map(x => x.main ? {...x, status:'closed'} : x)};
  assert.equal(G.liveGroupFocus(noMain), 't_tx');
  assert.equal(G.liveGroupFocus({members:[]}), '');
  assert.equal(G.liveGroupOf([EPIC], 't_ck'), EPIC);
  assert.equal(G.liveGroupOf([EPIC], 't_ot'), null);
  assert.equal(G.liveGroupOf(null, 't_ck'), null);
});

test('the fold: one entry per group where its first member stood, the others untouched', () => {
  const out = G.liveGroupFold(SESSIONS, [EPIC]);
  assert.deepEqual(out.map(s => s.id), ['t_ep', 't_zz', 't_ot']);
  const g = out[0];
  assert.equal(g.status, 'needs-you');
  assert.equal(g.opens, 't_mp');
  assert.equal(g.title, 'Autumn newsletter');
  assert.equal(g.question, 'Needs you: ORCH-302 Build the mail page');
  assert.equal(g.group, EPIC);
  assert.deepEqual(G.liveGroupFold(SESSIONS, []), SESSIONS);
});

test('the filter finds a group by any helper or small helper, never a loose helper tile', () => {
  assert.ok(G.liveGroupMatch(EPIC, 'mail page'));
  assert.ok(G.liveGroupMatch(EPIC, 'draft intro'));
  assert.ok(G.liveGroupMatch(EPIC, 'orch-304'));
  assert.ok(!G.liveGroupMatch(EPIC, 'weekly'));
  const b = wall.liveWallBands(SESSIONS, [], 'mail page', [EPIC]);
  assert.deepEqual(b.need.map(s => s.id), ['t_ep'], 'the group tile, not ORCH-302 alone');
  assert.equal(b.total, 3, 'a group counts as one tile');
});

test('wall: the group sits in Needs you first and is pinned by its main helper', () => {
  const b = wall.liveWallBands(SESSIONS, [], '', [EPIC]);
  assert.deepEqual(b.need.map(s => s.id), ['t_ep', 't_zz', 't_ot']);
  assert.deepEqual(b.queue, [], 'the helper in line stays inside the group');
  const p = wall.liveWallBands(SESSIONS, ['t_ep'], '', [EPIC]);
  assert.deepEqual(p.pin.map(s => s.id), ['t_ep']);
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livewall.js'), 'utf8');
  assert.match(src.slice(src.indexOf('function liveWallGroupTile'), src.indexOf('function liveWallTile(')), /liveWallPin\(s, pinned\)/, 'a group tile has the pin button of its main helper');
  assert.deepEqual(wall.liveWallBands(SESSIONS, [], '').need.map(s => s.id), ['t_mp', 't_zz', 't_ep', 't_tx', 't_ot'], 'without groups the wall is as before');
});

test('bar: the group is one chip whose number is the helper count of its tile', () => {
  const rows = liveBarRows(SESSIONS, ['t_ep'], [EPIC]);
  const g = rows.find(r => r.group === 't_ep');
  assert.equal(g.id, 't_mp', 'the chip opens the helper that needs you');
  assert.equal(g.n, G.liveGroupCounts(EPIC).helpers);
  assert.equal(g.s, 'wait');
  assert.equal(g.pin, true);
  assert.deepEqual(g.members, ['t_ep', 't_tx', 't_mp', 't_st', 't_ck']);
  assert.equal(g.line, G.liveGroupLine(EPIC));
  assert.equal(rows.length, 3);
  assert.equal(liveBarRows(SESSIONS, []).length, 6, 'without groups every session is its own chip');
});

test('switcher rows: tree order, small helpers under their helper, the shown one marked', () => {
  const rows = G.liveGroupRows(EPIC, 't_tx');
  assert.deepEqual(rows.map(r => [r.type, r.title, r.depth]), [
    ['helper', 'Autumn newsletter', 0], ['helper', 'Write the texts', 1], ['small', 'Draft intro', 2], ['small', 'Draft offers', 2],
    ['helper', 'Build the mail page', 1], ['helper', 'Send a test to the team', 1], ['helper', 'Check the links', 1]]);
  assert.equal(rows.find(r => r.cur).id, 't_tx');
  assert.equal(rows[0].main, true);
  assert.equal(rows[2].of, 't_tx', 'a small helper opens its helper');
  assert.equal(rows[4].word, 'Needs you');
  assert.equal(rows[6].word, 'In line');
});

test('the message box names who receives it', () => {
  assert.equal(G.liveMsgTo({id:'t_tx', key:'ORCH-301', title:'Write the texts'}, EPIC), 'Message to: Write the texts (ORCH-301). Only this helper gets it.');
  assert.equal(G.liveMsgTo({id:'t_ep', key:'ORCH-300', title:'Autumn newsletter'}, EPIC), 'Message to: Autumn newsletter (ORCH-300), the main helper.');
  assert.equal(G.liveMsgTo({id:'t_ot', key:'ORCH-12', title:'Other'}, null), 'Message to: Other (ORCH-12).');
  assert.equal(G.liveMsgTo(null, EPIC), '');
});

test('the switcher swaps the session of its own pane (pages/live-layer.js)', () => {
  const source = fs.readFileSync(path.join(WEB, 'pages/live-layer.js'), 'utf8');
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(source.slice(0, source.indexOf('// --- the page ---')) + '\nthis.step = liveLayerStep;', ctx);
  const s = {mode:'bottom', last:'bottom', back:'bottom', panes:['t_ot', 't_ep'], cur:'t_ot', menu:''};
  const a = ctx.step(s, {type:'swap', from:'t_ep', key:'t_tx'});
  assert.deepEqual([...a.panes], ['t_ot', 't_tx'], 'the pane of the group shows the other helper, the other pane stays');
  assert.equal(a.cur, 't_tx');
  const b = ctx.step({...s, panes:['t_tx', 't_ep']}, {type:'swap', from:'t_ep', key:'t_tx'});
  assert.deepEqual([...b.panes], ['t_tx'], 'shown already: the two panes become one');
  assert.equal(ctx.step(s, {type:'swap', from:'t_gone', key:'t_tx'}), s);
  const c = ctx.step({...s, mode:'bar'}, {type:'swap', from:'t_ep', key:'t_tx'});
  assert.equal(c.mode, 'bottom', 'a swap opens the layer again');
});

test('loaded and served like the other page modules; its look lives in the kit', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  assert.ok(index.indexOf('pages/livegroups.js') > index.indexOf('pages/livesessions.js'));
  assert.ok(index.indexOf('pages/livegroups.js') < index.indexOf('pages/live-layer.js'));
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /\|livegroups\|/);
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  for (const cls of ['.gtree{', '.gtree-row{', '.live-gwrap{', '.live-msg{', '.live-to{', '.lbar-n{', '.gtree[data-mode=strip]']) assert.ok(css.includes(cls), cls);
  const src = fs.readFileSync(path.join(WEB, 'pages/livegroups.js'), 'utf8');
  assert.doesNotMatch(src, /#[0-9a-f]{3,6}\b|style\s*=/i, 'no colours or inline styles in the page');
  assert.match(fs.readFileSync(path.join(KIT, 'gallery.html'), 'utf8'), /id="live-groups"/);
});
