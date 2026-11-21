'use strict';
// ORCH-817: Stop and End session for every session of the live page (pages/live-end.js): what each does for a
// ticket's helper and the four sessions without a ticket, the one question before End, the idle note.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const web = path.join(__dirname, '../src/orch_dashboard/web');
const source = fs.readFileSync(path.join(web, 'pages/live-end.js'), 'utf8');
const {liveEndModel, liveEndWords, liveEndIdleText, liveEndLogin} = require(path.join(web, 'pages/live-end.js'));
const plain = x => JSON.parse(JSON.stringify(x));

test('a ticket helper: Stop is run.interrupt, End is run.stop, Start again is run.start', () => {
  const m = liveEndModel({id:'t_abc123', kind:'', status:'working', lines:[]});
  assert.equal(m.on, true); assert.equal(m.stop, true); assert.equal(m.busy, true); assert.equal(m.hung, false);
  assert.deepEqual(plain(m.stopOp), ['run.interrupt', {ticket:'t_abc123'}]);
  assert.deepEqual(plain(m.endOp), ['run.stop', {ticket:'t_abc123'}]);
  assert.deepEqual(plain(m.startOp), ['run.start', {ticket:'t_abc123'}]);
});

for (const kind of ['manager', 'empty', 'chat']) {
  test(`the ${kind} session: Stop is run.interrupt on its hidden ticket, End is session.end ${kind}`, () => {
    const m = liveEndModel({id:'t_hid123', kind, status:'needs-you', lines:[]});
    assert.equal(m.on && m.stop && m.busy, true);
    assert.deepEqual(plain(m.stopOp), ['run.interrupt', {ticket:'t_hid123'}]);
    assert.deepEqual(plain(m.endOp), ['session.end', {kind}]);
    assert.deepEqual(plain(m.startOp), ['session.new', {kind}]);
  });
}

test('the plain terminal: no Stop (no step), End is session.end terminal while it is open', () => {
  const m = liveEndModel({id:'t_ter123', kind:'terminal', status:'idle', lines:[]});
  assert.equal(m.on, true); assert.equal(m.stop, false); assert.equal(m.hung, false);
  assert.deepEqual(plain(m.endOp), ['session.end', {kind:'terminal'}]);
  assert.equal(liveEndModel({id:'t_ter123', kind:'terminal', status:'closed'}).on, false);
});

test('an ended or never started session has neither; an idle helper has End and Start again, Stop greyed', () => {
  assert.equal(liveEndModel({id:'t_abc123', status:'closed'}).on, false);
  assert.equal(liveEndModel({id:'t_abc123', status:'in-line'}).on, false);
  assert.equal(liveEndModel(null).on, false);
  const idle = liveEndModel({id:'t_abc123', kind:'manager', status:'idle', lines:['⏺ done']});
  assert.equal(idle.on && idle.stop && idle.hung, true); assert.equal(idle.busy, false);
});

test('a helper whose login changed counts as hung even while it says working', () => {
  assert.equal(liveEndLogin(['  ⎿ API Error: 401 · Please run /login']), true);
  assert.equal(liveEndLogin(['Invalid API key · Fix external API key']), true);
  assert.equal(liveEndLogin(['⏺ Bash(pytest)', '  ⎿ 12 passed']), false);
  const m = liveEndModel({id:'t_abc123', kind:'chat', status:'working', lines:['Please run /login']});
  assert.equal(m.hung && m.login, true); assert.equal(m.busy, false);
});

test('the one question before End, in plain words; the terminal keeps nothing', () => {
  assert.deepEqual(liveEndWords('Manager', 'manager'), {ask:'End Manager?', why:'It stops now. Its conversation is kept: continue it later, or reopen it from History.', done:'Manager ended. Its conversation is in History.'});
  assert.deepEqual(liveEndWords('', 'terminal'), {ask:'End the plain terminal?', why:'The terminal closes. Its output is not kept.', done:'Plain terminal closed.'});
  assert.equal(liveEndWords('', '').ask, 'End this session?');
});

test('the idle note says what is going on and what to type', () => {
  assert.deepEqual(liveEndIdleText({login:false}, 'Nothing running for 3 min'), {head:'Nothing running for 3 min.', tail:'Type a message below to give it work. If it hangs, start it again.'});
  assert.match(liveEndIdleText({login:true}, 'x').head, /login changed/);
  assert.equal(liveEndIdleText({login:false}, '').head, 'Idle. Nothing is running.');
});

test('End asks once; Start again ends then starts; a closed terminal pane goes away', () => {
  assert.match(source, /'data-live-end':'yes'[^\n]*'End session'\)/);
  assert.match(source, /'data-live-end':'no'[^\n]*'Keep it'\)/);
  assert.match(source, /what === 'restart'\) \{\n\s+const r = await liveEndRun\(id, m\.endOp\), r2 = r\.ok \? await liveEndRun\(id, m\.startOp\) : r;/);
  assert.match(source, /m\.kind === 'terminal' && typeof liveLayerDo === 'function'\) liveLayerDo\(\{type:'close', key:id\}\)/);
});

test('a choice in a narrow pane\'s More closes More first; the pane header follows a login change', () => {
  assert.match(source, /b\.closest\('#live-dock'\)[\s\S]{0,160}const menu = liveLayerModel\(\)\.menu;\n\s+if \(menu\) liveLayerDo\(\{type:'menu', menu\}\);/);
  const layer = fs.readFileSync(path.join(web, 'pages/live-layer.js'), 'utf8');
  assert.match(layer, /\(m => \[m\.busy, m\.hung\]\)\(liveEndModel\(x\.live\)\)/);
});

test('the pane, the wall and the bar all use it, and the page loads it before the layer', () => {
  const index = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const at = index.indexOf('pages/live-end.js');
  assert.ok(at > 0 && at < index.indexOf('pages/live-layer.js'));
  assert.match(fs.readFileSync(path.join(web, '../server.py'), 'utf8'), /live-end\|/);
  assert.match(fs.readFileSync(path.join(web, 'pages/livewall.js'), 'utf8'), /window\.liveEndMore\(s\.id, 'tile', liveWallLabel\(s\)\)/);
  const bar = fs.readFileSync(path.join(web, 'pages/livebar.js'), 'utf8');
  assert.match(bar, /window\.liveEndMore\(o\.id, 'bar', label\(o\)\)/);
  assert.match(bar, /addEventListener\('contextmenu'[\s\S]{0,200}window\.liveEndShow\('bar:' \+ c\.dataset\.lbarOpen\)/);
});
