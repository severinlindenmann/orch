// ORCH-1004: the dashboard keeps an add-on page's pass only while the server still takes it. A page opened later
// (the server ends a pass after its life) gets a new pass first, so its first call never answers 401; the frame on
// screen keeps the pass it has (a new one would load it again).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
const fn = /function framePass\(name\) \{[\s\S]*?\n\}\n/.exec(src)[0];

function env(life) {
  const e = {asks: 0, now: 1_000_000, shownSrc: null, renders: 0, pending: []};
  const framePasses = new Map(), framePassAsks = new Map(), framePassFailed = new Map();
  let n = 0;
  const fetch = () => { e.asks++; const i = ++n; return Promise.resolve({ok: true, json: () => ({pass: 'p' + i, file: 'f' + i, act: true, ...(life === undefined ? {} : {life})})}); };
  const Date_ = {now: () => e.now};
  const frameShown = () => (e.shownSrc ? {getAttribute: () => e.shownSrc} : null);
  e.framePass = new Function('framePasses', 'framePassAsks', 'framePassFailed', 'fetch', 'Date', 'frameShown', 'frameChanNew', 'render',
    fn + '\nreturn framePass;')(framePasses, framePassAsks, framePassFailed, fetch, Date_, frameShown, () => 'c'.repeat(32), () => { e.renders++; });
  e.get = async name => { let p = e.framePass(name); if (p) return p; await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0)); return e.framePass(name); };
  return e;
}

test('a pass is reused while it lives, and asked for again before the server ends it', async () => {
  const e = env(900);
  const a = await e.get('insights');
  assert.equal(a.pass, 'p1');
  e.now += 800 * 1000;  // 13 min later: still good
  assert.equal((await e.get('insights')).pass, 'p1');
  e.now += 60 * 1000;  // 14 min 20 s: within the last minute of its life, so a page opened now gets a new one
  assert.equal((await e.get('insights')).pass, 'p2');
  assert.equal(e.asks, 2);
});

test('the frame on screen keeps its pass after its time (no reload while the person looks at it)', async () => {
  const e = env(900);
  const a = await e.get('factory');
  e.shownSrc = '/addon/factory/#orch-frame=' + a.pass + '&orch-file=' + a.file + '&orch-chan=' + a.chan;
  e.now += 1000 * 1000;
  assert.equal(e.framePass('factory').pass, a.pass);
  e.shownSrc = '/addon/focus/#orch-frame=other&orch-file=x&orch-chan=y';  // another page now: a new pass for factory
  assert.equal((await e.get('factory')).pass, 'p2');
});

test('a short life keeps half of it; an answer without a life counts as 15 minutes', async () => {
  const e = env(20);
  await e.get('focus');
  e.now += 9 * 1000;
  assert.equal((await e.get('focus')).pass, 'p1');
  e.now += 2 * 1000;
  assert.equal((await e.get('focus')).pass, 'p2');
  const old = env(undefined);
  await old.get('focus');
  old.now += 830 * 1000;
  assert.equal((await old.get('focus')).pass, 'p1');
  old.now += 20 * 1000;
  assert.equal((await old.get('focus')).pass, 'p2');
});

test('the pass life counts from the ask, not from a late answer', async () => {
  const e = env(900);
  const first = e.framePass('insights');  // asked now
  assert.equal(first, null);
  e.now += 120 * 1000;  // the answer arrives 2 min later
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  e.now += 730 * 1000;  // 14 min 10 s after the ask (12 min 10 s after the answer): within its last minute
  assert.equal((await e.get('insights')).pass, 'p2');
});
