// ORCH-1008: the dashboard page keeps each add-on's frame pass, but the server forgets a pass after its life (15 min)
// or when the dashboard restarts. Opening the add-on page again with such a pass made its first call answer 401 (the
// frame then asked for new passes). Now the page asks for a new pass before it opens a page with an old one.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');

function env({now = 1000000, boot = 'b1', shownSrc = null, answer} = {}) {
  const chunk = /const framePasses = new Map\(\)[\s\S]*?\n}\n(?=\/\/ A per-frame code)/.exec(src)[0];
  const e = {now, shownSrc, asks:[], renders:0};
  const fetch = (url, opts) => {
    e.asks.push(JSON.parse(opts.body).addon);
    const j = answer || {pass:'p'.repeat(43), file:'f'.repeat(43), act:true, life:900, boot:'b1'};
    return Promise.resolve({ok:true, json:() => Promise.resolve(j)});
  };
  const DateFake = {now:() => e.now};
  const body = 'let serverBoot = boot();\n' + chunk + '\nreturn {framePass, framePasses, setBoot:v => { serverBoot = v; }};';
  const api = new Function('fetch', 'Date', 'render', 'frameChanNew', 'frameShown', 'boot', body)(
    fetch, DateFake, () => { e.renders++; }, () => 'c'.repeat(32),
    () => (e.shownSrc ? {getAttribute:() => e.shownSrc} : null), () => boot);
  e.api = api;
  e.ask = async name => { const p = api.framePass(name); await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0)); return p; };
  return e;
}

test('a new pass is kept with its end and the dashboard run that made it', async () => {
  const e = env();
  assert.equal(await e.ask('factory'), null);  // asked; the page shows a skeleton meanwhile
  const p = e.api.framePasses.get('factory');
  assert.equal(p.boot, 'b1');
  assert.equal(p.until, 1000000 + 900000 - 60000);  // a minute before the server forgets it
  assert.equal(e.api.framePass('factory'), p);  // still good: no new ask
  assert.deepEqual(e.asks, ['factory']);
});

test('a pass about to run out is asked anew before its page opens', async () => {
  const e = env();
  await e.ask('factory');
  e.now += 850000;  // 14 min 10 s later: within the last minute of its life
  assert.equal(e.api.framePass('factory'), null);
  assert.deepEqual(e.asks, ['factory', 'factory']);
});

test('a pass of a dashboard run that has ended is asked anew', async () => {
  const e = env();
  await e.ask('insights');
  e.api.setBoot('b2');  // /api/state now answers from a restarted dashboard (X-Orch-Boot)
  assert.equal(e.api.framePass('insights'), null);
  assert.deepEqual(e.asks, ['insights', 'insights']);
});

test('the page already showing keeps its pass (a new one would load it again)', async () => {
  const e = env({shownSrc:'/addon/factory/#orch-frame=x'});
  await e.ask('factory');
  e.now += 900000;
  const p = e.api.framePasses.get('factory');
  assert.equal(e.api.framePass('factory'), p);
  e.shownSrc = '/addon/insights/';  // another add-on is on screen: this old pass goes
  assert.equal(e.api.framePass('factory'), null);
});

test('an answer without life or boot (an older dashboard) keeps the 15 minutes and never compares runs', async () => {
  const e = env({answer:{pass:'p'.repeat(43), file:'f'.repeat(43), act:false}});
  await e.ask('factory');
  const p = e.api.framePasses.get('factory');
  assert.equal(p.boot, null);
  assert.equal(p.until, 1000000 + 840000);
  assert.equal(e.api.framePass('factory'), p);
});
