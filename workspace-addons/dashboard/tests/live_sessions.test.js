// ORCH-359: the live sessions the new Focus reads (pages/livesessions.js): the words every place shares, the bar's rows,
// and that the bar and the panes read the sessions API, not the tickets and runs of the state.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ls = require('../src/orch_dashboard/web/pages/livesessions.js');

const WEB = path.join(__dirname, '../src/orch_dashboard/web');

test('open time and the idle close read right', () => {
  assert.equal(ls.liveDur(59), '0 min');
  assert.equal(ls.liveDur(25 * 60), '25 min');
  assert.equal(ls.liveDur(65 * 60), '1 h 5 min');
  assert.equal(ls.liveDur(120 * 60), '2 h');
  const idle = {status:'idle', tool:'Helper', model:'Opus', open_seconds:96 * 60, closes_in_seconds:42 * 60};
  assert.deepEqual(ls.liveMeta(idle), ['Helper · Opus', 'open 1 h 36 min', 'closes in 42 min if left idle']);
  assert.deepEqual(ls.liveMeta({status:'closed', model:'Sonnet'}), ['Sonnet', 'closed, the conversation is kept']);
  assert.equal(ls.liveWarm({status:'in-line'}), 'starts when a place is free');
  assert.equal(ls.liveWarm({status:'needs-you'}), 'stays warm while it waits for you');
});

test('what a session does now: the question, the detail, what it waits on', () => {
  assert.equal(ls.liveNow({status:'needs-you', question:'Keep the old name?', detail:'Your answer'}), 'Keep the old name?');
  assert.equal(ls.liveNow({status:'needs-you', detail:'Your OK on the screen'}), 'Your OK on the screen');
  assert.equal(ls.liveNow({status:'working', detail:'Running pytest'}), 'Running pytest');
  assert.equal(ls.liveNow({status:'working', word:'On hold', waiting_on:[{kind:'time', what:'until 18:00'}]}), 'Waiting until 18:00');
  // ORCH-1663: the sentence never repeats the status word (the tile said "Working / Working", "Open / Open")
  assert.equal(ls.liveNow({status:'working', word:'Working', waiting_on:[]}), 'No step started yet.');
  assert.equal(ls.liveNow({status:'working', word:'Open', kind:'terminal'}), 'A shell on this computer.');
  assert.equal(ls.liveNow({status:'idle', word:'Idle'}), 'Waits for your next message.');
  assert.equal(ls.liveNow({status:'working', word:'Stuck'}), '', 'its own word is on the status already');
  // ORCH-463: no detail and nothing waited on: the step it works on, else the plain word
  assert.equal(ls.liveNow({status:'working', word:'Working', waiting_on:[], step:'Put words on the buttons'}), 'Working on: Put words on the buttons');
  assert.equal(ls.liveNow({status:'working', detail:'Running pytest', step:'Test it'}), 'Running pytest', 'the core detail wins');
  assert.equal(ls.liveNow({status:'in-line'}), 'Waits in line for a free helper place.');
  assert.equal(ls.liveNow({status:'closed'}), 'No session right now.');
});

test('loaded before the layer and the bar, served as a page module, polled only where Focus runs', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const at = f => index.indexOf('pages/' + f);
  assert.ok(at('livesessions.js') > 0 && at('livesessions.js') < at('live-layer.js') && at('livesessions.js') < at('livebar.js'));
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /\|livesessions\|/);
  assert.match(server, /path == "\/api\/sessions"/);
  const src = fs.readFileSync(path.join(WEB, 'pages/livesessions.js'), 'utf8');
  assert.match(src, /liveFocusOn\(\)/);
  assert.match(src, /visibilityState === 'hidden'/, 'a hidden tab does not poll');
});

test('the bar and the panes read the sessions API, not the tickets and runs', () => {
  const bar = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  // the bar's own painting (after module.exports); the ticket's session button keeps the dashboard's state (liveTicketSession)
  assert.doesNotMatch(bar.slice(bar.indexOf('module.exports')), /state\.runs|helperState\(/);
  assert.match(bar, /LiveSessions/);
  const layer = fs.readFileSync(path.join(WEB, 'pages/live-layer.js'), 'utf8');
  assert.match(layer, /LiveSessions\?\.get\(/);
  assert.match(layer, /liveNow\(live\)/);
  assert.match(layer, /liveWarm\(live\)/, 'the status popover says how long it stays (ORCH-2199)');
  assert.doesNotMatch(layer, /come here next/);
});

test('the poll sends the list tag back itself and keeps the list on 304 (ORCH-1620)', () => {
  // the browser's own cache never sent If-None-Match: an idle Home tab got the full list every 3 s (660 KB a minute)
  const src = fs.readFileSync(path.join(WEB, 'pages/livesessions.js'), 'utf8');
  const read = src.slice(src.indexOf('async function read()'), src.indexOf('function tick()'));
  assert.match(read, /cache:'no-store'/);
  assert.match(read, /'If-None-Match': store\.etag/);
  assert.match(read, /if \(r\.status === 304\) return;/);
  assert.match(read, /store\.etag = .*get\?\.\('ETag'\)/);
});

test('an unchanged answer (304) is a quiet poll in the debug log, not an error (ORCH-1620)', async () => {
  const trail = require(path.join(__dirname, '../../../workspace/src/orch_ui/static/diagtrail.js'));
  const win = {
    fetch: async () => ({ok: false, status: 304}),
    location: {hash: ''}, navigator: {}, addEventListener: () => {}, innerWidth: 1280, innerHeight: 800,
    console: {error: () => {}}, document: {addEventListener: () => {}},
  };
  const t = trail.install(win);
  const before = t.queue.length;
  await win.fetch('/api/sessions?lines=8', {});
  assert.equal(t.queue.filter(e => e.kind === 'ui.fetch' || e.event === 'ui.fetch').length, 0);
  assert.equal(t.queue.length, before);
});
