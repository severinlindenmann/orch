'use strict';
// ORCH-1104: the Record a call page's model (record.js). A fake speech service and a fake add-on stand in for the
// dashboard: each piece's words land once, in order; a busy service is tried again; a refusal stops and keeps the
// pieces for Try again.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
require(path.join(__dirname, '../src/orch_dashboard/web/record.js'));
const M = globalThis.RecordModel;

function fake({words = {}, busy = 0, refuse = null} = {}) {
  const acts = [], heard = [];
  let busyLeft = busy;
  const res = (status, body) => ({ok:status < 300, status, text:async () => body});
  async function fetch(url, o) {
    if (url === '/api/voice/words') {
      heard.push(o.headers['Content-Type']);
      if (busyLeft > 0) { busyLeft--; return res(429, 'Speech to text is busy. Try again in a moment.'); }
      const t = words[o.body.n];
      return t === undefined ? res(422, 'No words were heard.') : res(200, JSON.stringify({text:t}));
    }
    const args = JSON.parse(o.body).args;
    if (refuse && refuse(args)) return res(409, JSON.stringify({error:'This recording was deleted. Start it again from Meetings.'}));
    acts.push(args);
    return res(200, JSON.stringify({ok:true, result:{id:'m1'}}));
  }
  return {fetch, acts, heard};
}
const blob = n => ({n, type:'audio/webm;codecs=opus'});
const info = n => ({n, secs:100, at:'2026-11-25T10:15:00.000Z'});
const open = (f, more) => M.session({fetch:f.fetch, sleep:async () => {}, addon:'personal', rec:'browser-x', started:'2026-11-25T11:15:00+01:00', consentAt:'2026-11-25T11:14:50+01:00', meetingAudio:true, ...more});

test('the page only records for an add-on named in its address', () => {
  assert.equal(M.target('#for=personal'), 'personal');
  assert.equal(M.target('#for=../x'), null);
  assert.equal(M.target(''), null);
});

test('the consent and each piece’s words go to the meeting, in order, then the end', async () => {
  const f = fake({words:{1:'Wir starten.', 2:'Dann die Offerte.'}});
  const s = open(f);
  assert.equal((await s.begin()).kind, 'ok');
  s.piece(blob(1), info(1)); s.piece(blob(2), info(2)); s.piece(blob(3), info(3));
  await s.idle();
  await s.finish(250, false);
  assert.deepEqual(f.heard, ['audio/webm', 'audio/webm', 'audio/webm'], 'the plain sound type, as the dashboard takes it');
  assert.deepEqual(f.acts.map(a => [a.n, a.text, a.done]), [[undefined, undefined, undefined], [1, 'Wir starten.', undefined], [2, 'Dann die Offerte.', undefined], [3, '', undefined], [undefined, undefined, true]]);
  assert.equal(f.acts[0].consent_at, '2026-11-25T11:14:50+01:00');
  assert.equal(f.acts[0].meeting_audio, true);
  assert.equal(f.acts[4].minutes, 4);
  assert.equal(s.view().written, 3);
});

test('a busy speech service is tried again; the piece still lands', async () => {
  const f = fake({words:{1:'Hallo.'}, busy:2});
  const s = open(f);
  await s.begin(); await s.piece(blob(1), info(1));
  assert.equal(f.heard.length, 3);
  assert.equal(s.view().written, 1);
});

test('a refusal stops, keeps the pieces, and Try again writes them once allowed', async () => {
  let refusing = true;
  const f = fake({words:{1:'Eins.', 2:'Zwei.'}, refuse:a => refusing && a.n !== undefined});
  const seen = [];
  const s = open(f, {onChange:v => seen.push(v)});
  await s.begin();
  s.piece(blob(1), info(1)); s.piece(blob(2), info(2));
  await s.idle();
  assert.equal(s.view().failed, 2);
  assert.match(s.view().stopped, /deleted/);
  assert.equal(f.heard.length, 1, 'no more sound is sent once stopped');
  refusing = false;
  await s.again();
  assert.deepEqual(f.acts.filter(a => a.n).map(a => a.text), ['Eins.', 'Zwei.']);
  assert.equal(s.view().failed, 0);
  await s.finish(200, true);
  assert.equal(f.acts.at(-1).missing, 0);
});

test('the dashboard’s answers: words, nothing heard, wait, or stop', () => {
  assert.deepEqual(M.wordsAnswer(200, '{"text":" ja "}'), {kind:'words', text:'ja'});
  assert.deepEqual(M.wordsAnswer(422, ''), {kind:'words', text:''});
  assert.equal(M.wordsAnswer(429, 'busy').kind, 'again');
  assert.equal(M.wordsAnswer(503, '<html>').text, 'The words could not be written down right now.');
  assert.match(M.wordsAnswer(403, '').text, /Sign in/);
  assert.equal(M.wordsAnswer(409, 'Turn on the relay first.').kind, 'stop');
});

test('long words go in parts at a space, none over the limit', () => {
  const text = ('wort '.repeat(1000)).trim();
  const parts = M.splitText(text, 1800);
  assert.ok(parts.length === 3 && parts.every(p => p.length <= 1800 && !p.startsWith(' ')));
  assert.equal(parts.join(' '), text);
});
