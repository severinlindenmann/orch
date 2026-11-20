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
  const env = {forgets:0, later:[]};
  env.api = new Function('framesForget', 'render', 'setTimeout', 'let serverBoot = null;\n' + fn + '\nreturn {noteBoot, boot: () => serverBoot};')(
    () => { env.forgets++; }, () => { env.renders = (env.renders || 0) + 1; }, f => env.later.push(f));
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
  env.later.forEach(f => f());
  assert.equal(env.renders, 1);  // drawn again by noteBoot itself: a failed click's answer may be the one that noticed
  assert.equal(env.answer('b2'), false);
  assert.equal(env.forgets, 1);
});

test('refresh and the click answers both note the run of the dashboard', () => {
  const src = read('../src/orch_dashboard/web/app.js');
  assert.ok(!/serverBoot = res\.headers/.test(src.replace(/function noteBoot\(res\) \{[\s\S]*?\n\}\n/, '')));
  assert.equal((src.match(/\bnoteBoot\(res\);/g) || []).length, 2);  // /api/state and /api/act
});

function passEnv() {
  const src = read('../src/orch_dashboard/web/pages/settings.js');
  const maps = /const framePasses = new Map\(\), framePassAsks = new Map\(\), framePassFailed = new Map\(\), frameFresh = new Map\(\);/.exec(src)[0];
  const fp = /function framePass\(name\) \{[\s\S]*?\n\}\n/.exec(src)[0];
  const forget = /function framesForget\(\) \{[\s\S]*?\n\}\n/.exec(src)[0];
  const env = {calls:0, renders:0, ok:false, removed:0};
  env.frame = {remove:() => { env.removed++; env.frame = null; }};
  const fetch = () => { env.calls++; return env.ok ? Promise.resolve({ok:true, json:() => ({pass:'p'.repeat(43), file:'f'.repeat(43)})}) : Promise.reject(new Error('down')); };
  env.api = new Function('fetch', 'render', 'frameChanNew', 'frameRetries', 'frameShown', 'let frameKeep = {id:"insights"};\n' + maps + '\n' + fp + '\n' + forget +
    '\nreturn {framePass, framesForget, framePasses, kept: () => frameKeep, asks: framePassAsks};')(fetch, () => { env.renders++; }, () => 'c'.repeat(32), new Map(), () => env.frame);
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
  assert.equal(env.removed, 1);  // the shown frame goes: the next drawing makes a new one that loads
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

// The starting page's message: the dashboard page opens a new frame, only for the shown frame, at most FRAME_RETRIES.
function retryEnv() {
  const src = read('../src/orch_dashboard/web/pages/settings.js');
  const chunk = /const FRAME_RETRY_MS = [\s\S]*?\n\}\);\n/.exec(src)[0];
  const env = {listener:null, timers:[], replaced:0, hash:'#addon/insights'};
  env.skeletons = [];
  env.loaded = new Set(['/addon/insights/#orch-frame=x']);
  const classes = new Set();
  env.frame = {isConnected:true, contentWindow:{}, classes, classList:{add:c => classes.add(c)}, getAttribute:() => '/addon/insights/#orch-frame=x',
    before:n => env.skeletons.push(n), replaceWith:() => { env.replaced++; }};
  const document = {querySelector:() => env.skeletons[0] || null, querySelectorAll:() => ({forEach:f => { env.skeletons.splice(0).forEach(f); }})};
  new Function('globalThis', 'snapshot', 'frameShown', 'route', 'pageFrame', 'setTimeout', 'document', 'framesLoaded', 'skeletonFor', chunk)(
    {addEventListener:(n, f) => { if (n === 'message') env.listener = f; }}, false, () => env.frame,
    () => ({kind:'page', id:'insights', path:'', hash:env.hash}), () => ({}), f => env.timers.push(f), document, env.loaded,
    () => ({dataset:{}, remove() {}}));
  env.send = (data, opts = {}) => env.listener({origin:opts.origin || 'null', source:opts.source || env.frame.contentWindow, data});
  env.tick = () => { const t = env.timers.splice(0); t.forEach(f => f()); };
  return env;
}

test('the starting page makes the dashboard open a new frame in a moment', () => {
  const env = retryEnv();
  env.send({orch:'frame-starting'});
  assert.equal(env.replaced, 0);  // not at once
  assert.equal(env.skeletons.length, 1);  // the skeleton shows meanwhile, the empty starting page is hidden
  assert.ok(env.frame.classes.has('embed-loading'));
  assert.equal(env.loaded.size, 0);  // the new frame gets its skeleton until it really loaded
  env.send({orch:'frame-starting'});
  assert.equal(env.skeletons.length, 1);  // never two
  env.tick();
  assert.equal(env.replaced, 1);
  assert.equal(env.skeletons.length, 0);  // the new frame brings its own
});

test('only the shown frame asks, and nothing happens once the person moved on', () => {
  const env = retryEnv();
  env.send({orch:'frame-starting'}, {source:{}});  // another window
  env.send({orch:'frame-starting'}, {origin:'http://evil.example'});
  env.send({orch:'frame-go'});
  assert.equal(env.timers.length, 0);
  env.send({orch:'frame-starting'});
  env.hash = '#addon/focus';  // another page now
  env.tick();
  assert.equal(env.replaced, 0);
});

test('the frame is opened again at most 30 times for one address', () => {
  const env = retryEnv();
  for (let i = 0; i < 40; i++) { env.frame = {...env.frame}; env.send({orch:'frame-starting'}); env.tick(); }  // a new frame each time
  assert.equal(env.replaced, 30);
});
