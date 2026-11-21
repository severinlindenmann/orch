'use strict';
// ORCH-696: voice into the message box of the new Focus (pages/livevoice.js). The microphone shows only with the relay
// on and connected; the words go after what is typed, inside the box's limit; the words on screen are plain sentences.
const test = require('node:test');
const assert = require('node:assert/strict');
const V = require('../src/orch_dashboard/web/pages/livevoice.js');

const relay = (active, connected) => ({settings:{addons:[{name:'relay', active, detail:connected == null ? null : {connected}}]}});

test('the microphone shows only while the relay add-on is on and connected', () => {
  assert.equal(V.liveVoiceOn(relay(true, true), false), true);
  assert.equal(V.liveVoiceOn(relay(false, true), false), false, 'add-on off');
  assert.equal(V.liveVoiceOn(relay(true, false), false), false, 'not connected');
  assert.equal(V.liveVoiceOn(relay(true, null), false), false, 'never connected');
  assert.equal(V.liveVoiceOn({settings:{addons:[{name:'publish', active:true, detail:{connected:true}}]}}, false), false, 'publish is not the relay');
  assert.equal(V.liveVoiceOn({}, false), false, 'no settings (a watch-only page)');
  assert.equal(V.liveVoiceOn(relay(true, true), true), false, 'a snapshot never listens');
});
test('spoken words go after what is typed, on the same line, inside the limit', () => {
  assert.equal(V.liveVoiceJoin('', 'Keep the old name.'), 'Keep the old name.');
  assert.equal(V.liveVoiceJoin('Thanks.  ', ' Keep the old name. '), 'Thanks. Keep the old name.');
  assert.equal(V.liveVoiceJoin('Typed', '   '), 'Typed', 'nothing heard changes nothing');
  assert.equal(V.liveVoiceJoin('x'.repeat(1990), 'y'.repeat(50)).length, 2000);
  assert.equal(V.liveVoiceJoin('x'.repeat(1490), 'y'.repeat(50), 1500).length, 1500, 'the box\'s own limit wins');
});
test('the clock reads like the draft', () => {
  assert.equal(V.liveVoiceClock(4), '0:04');
  assert.equal(V.liveVoiceClock(75), '1:15');
  assert.equal(V.liveVoiceClock(-1), '0:00');
});
test('every refusal is one plain sentence; at most two minutes, the relay limit', () => {
  for (const t of Object.values(V.LIVE_VOICE_SAY)) assert.match(t, /^[A-Z][^.]*\.$/);
  assert.equal(V.LIVE_VOICE_DONE, 'From your voice. Check the words, change what is wrong, then send.');
  assert.equal(V.LIVE_VOICE_MAX_SECS, 120);
});
