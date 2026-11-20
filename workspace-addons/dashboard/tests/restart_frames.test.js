// ORCH-1055: after an add-on is added or removed in Settings the dashboard restarts. Its frame passes are kept in
// memory only, so the page must forget the ones it holds and open the shown add-on page again with a fresh pass,
// also when the pass request failed while the dashboard was down (it used to wait for a change that never came).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8');

function noteBootEnv() {
  const src = read('../src/orch_dashboard/web/app.js');
  const fn = /function noteBoot\(res\) \{[\s\S]*?\n\}\n/.exec(src)[0];
  const env = {forgets:0};
  env.api = new Function('framesForget', 'let serverBoot = null;\n' + fn + '\nreturn {noteBoot, boot: () => serverBoot};')(() => { env.forgets++; });
  env.answer = boot => env.api.noteBoot({headers:{get:n => (n === 'X-Orch-Boot' ? boot : null)}});
  return env;
}

test('a new run of the dashboard makes the page forget its frame passes, the same run does not', () => {
  const env = noteBootEnv();
  assert.equal(env.answer('b1'), false);  // the first answer: nothing to compare with
  assert.equal(env.answer('b1'), false);
  assert.equal(env.answer(null), false);  // an answer without the header keeps the run known
  assert.equal(env.api.boot(), 'b1');
  assert.equal(env.forgets, 0);
  assert.equal(env.answer('b2'), true);  // restarted
  assert.equal(env.forgets, 1);
  assert.equal(env.answer('b2'), false);
  assert.equal(env.forgets, 1);
});

test('refresh and the click answers both note the run of the dashboard', () => {
  const src = read('../src/orch_dashboard/web/app.js');
  assert.ok(!/serverBoot = res\.headers/.test(src.replace(/function noteBoot\(res\) \{[\s\S]*?\n\}\n/, '')));
  assert.match(src, /const restarted = noteBoot\(res\);/);
  assert.match(src, /if \(restarted\) render\(\);/);  // an unchanged state still draws the page again
});

function passEnv() {
  const src = read('../src/orch_dashboard/web/pages/settings.js');
  const maps = /const framePasses = new Map\(\), framePassAsks = new Map\(\), framePassFailed = new Map\(\), frameFresh = new Map\(\);/.exec(src)[0];
  const fp = /function framePass\(name\) \{[\s\S]*?\n\}\n/.exec(src)[0];
  const forget = /function framesForget\(\) \{[\s\S]*?\n\}\n/.exec(src)[0];
  const env = {calls:0, renders:0, ok:false};
  const fetch = () => { env.calls++; return env.ok ? Promise.resolve({ok:true, json:() => ({pass:'p'.repeat(43), file:'f'.repeat(43)})}) : Promise.reject(new Error('down')); };
  env.api = new Function('fetch', 'render', 'frameChanNew', 'let frameKeep = {id:"insights"};\n' + maps + '\n' + fp + '\n' + forget +
    '\nreturn {framePass, framesForget, framePasses, kept: () => frameKeep, asks: framePassAsks};')(fetch, () => { env.renders++; }, () => 'c'.repeat(32));
  env.settle = () => Promise.all([...env.api.asks.values()]);
  return env;
}

test('a pass asked for while the dashboard was down is asked for again once it is back', async () => {
  const env = passEnv();
  assert.equal(env.api.framePass('insights'), null);
  await env.settle();
  assert.equal(env.calls, 1);
  assert.equal(env.api.framePass('insights'), null);  // failed a moment ago: not asked again at once
  assert.equal(env.calls, 1);
  env.ok = true;
  env.api.framesForget();  // the new run of the dashboard answered
  assert.equal(env.api.kept(), null);
  assert.equal(env.api.framePass('insights'), null);
  await env.settle();
  assert.equal(env.calls, 2);
  assert.equal(env.renders, 1);  // drawn again with the new pass: the frame loads
  assert.equal(env.api.framePass('insights').pass, 'p'.repeat(43));
});

test('the old pass is dropped after a restart, so the frame address changes and loads again', async () => {
  const env = passEnv();
  env.ok = true;
  env.api.framePass('insights');
  await env.settle();
  env.api.framePasses.set('insights', {pass:'o'.repeat(43), file:'f'.repeat(43), chan:'c'.repeat(32)});
  env.api.framesForget();
  assert.equal(env.api.framePass('insights'), null);
  await env.settle();
  assert.equal(env.api.framePass('insights').pass, 'p'.repeat(43));
});
