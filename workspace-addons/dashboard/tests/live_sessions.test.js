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
  assert.equal(ls.liveNow({status:'working', word:'Working', waiting_on:[]}), 'Working');
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
  assert.match(layer, /liveMeta\(live\)/);
  assert.doesNotMatch(layer, /come here next/);
});
