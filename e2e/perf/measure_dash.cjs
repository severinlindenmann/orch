// Dashboard at size (ORCH-518): per page the time until it is usable, the bytes it fetched, the bytes of an idle
// minute on Home and the browser memory, on a real dashboard started on a seeded workspace.
// usage: PW_DIR=<folder holding node_modules/playwright> node e2e/perf/measure_dash.cjs <sign-in link> <ticket id>
//          [--idle-seconds 60] [--out result.json]
// The sign-in link comes from `orch start --print-launch-url --no-open` in the seeded workspace (throwaway home).
// "Usable": the page's loading shape is gone and it shows text; for an add-on page the same inside its frame.
// Bytes: what came over the wire (encoded) and unpacked (decoded), counted with the browser's network events.
// Prints one table line per page and writes the rows as JSON to --out.
'use strict';
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const { chromium } = require(path.join(PW, 'playwright'));
const headless = require('../headless.cjs');  // the keychain options (ORCH-615)

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i < 0 ? dflt : args[i + 1]; };
const [launch, ticketId] = args;
const IDLE = Number(opt('--idle-seconds', '60'));
const OUT = opt('--out', '');
const LIMIT_MS = Number(opt('--timeout-ms', '120000'));
if (!launch || !ticketId) { console.error('usage: node measure_dash.cjs <sign-in link> <ticket id>'); process.exit(2); }
const base = launch.split('#')[0].replace(/\/$/, '');

const PAGES = [
  ['Home', '#home'],
  ['Tickets list', '#tickets?layout=list'],
  ['Tickets board', '#tickets?layout=board'],
  ['Search', '#tickets?q=invoice'],
  ['Review', '#review'],
  ['One ticket', '#ticket/' + ticketId],
  ['Focus', '#addon/focus'],
  ['Factory', '#addon/factory'],
  ['Insights', '#addon/insights'],
];

function meter(cdp) {
  const m = { enc: 0, dec: 0, reqs: 0, byPath: {}, reads: [], all: [] };
  const urls = new Map(), began = new Map();
  cdp.on('Network.requestWillBeSent', e => { urls.set(e.requestId, e.request.url); began.set(e.requestId, Date.now()); m.reqs++; });
  cdp.on('Network.dataReceived', e => { m.dec += e.dataLength; });
  cdp.on('Network.loadingFinished', e => {
    m.enc += e.encodedDataLength;
    const u = urls.get(e.requestId) || '';
    let p = u; try { p = new URL(u).pathname; } catch (_) { /* data: urls */ }
    m.byPath[p] = (m.byPath[p] || 0) + e.encodedDataLength;
    // when each read and page began and ended, so a slow page shows what it waited for (ORCH-2288)
    if (/^\/(api|addon)\//.test(p)) m.reads.push([p, began.get(e.requestId), Date.now()]);
    m.all.push([p, began.get(e.requestId), Date.now()]);  // the files too: a first load fetches every one (ORCH-2391)
  });
  cdp.on('Network.webSocketFrameReceived', e => { m.enc += (e.response.payloadData || '').length; m.dec += (e.response.payloadData || '').length; });
  // an event stream never finishes loading, so loadingFinished never counts it: count each message as it arrives
  cdp.on('Network.eventSourceMessageReceived', e => {
    const n = (e.data || '').length;
    m.dec += n; m.enc += n;
    let p = urls.get(e.requestId) || ''; try { p = new URL(p).pathname; } catch (_) { /* keep */ }
    m.byPath[p] = (m.byPath[p] || 0) + n;
    const t = Date.now();
    m.reads.push(['event ' + (e.eventName || '') + ' ' + (e.data || '').slice(0, 120), t, t]);  // what the page was told
  });
  return m;
}
const snap = m => ({ enc: m.enc, dec: m.dec, reqs: m.reqs, byPath: { ...m.byPath } });
const diff = (a, b) => {
  const byPath = {};
  for (const [k, v] of Object.entries(b.byPath)) { const d = v - (a.byPath[k] || 0); if (d > 0) byPath[k] = d; }
  return { enc: b.enc - a.enc, dec: b.dec - a.dec, reqs: b.reqs - a.reqs, byPath };
};

const SHOWN = () => {
  const m = document.querySelector('main') || document.body;
  return !!m && !m.querySelector('[aria-busy="true"]') && m.innerText.trim().length > 20;
};

async function usable(page, isAddon) {
  if (!isAddon) { await page.waitForFunction(SHOWN, null, { timeout: LIMIT_MS, polling: 50 }); return; }
  // An add-on page runs in a frame on its own port (another origin), or the dashboard draws it itself (Focus, the
  // live wall: no frame, ORCH-526 / ORCH-2271). Wait for whichever comes: a frame, or the page shown without one.
  const deadline = Date.now() + LIMIT_MS;
  const how = await page.waitForFunction(() => {  // SHOWN, plus the frame (a page function cannot call SHOWN)
    const m = document.querySelector('main') || document.body;
    if (m && m.querySelector('iframe.embed')) return 'frame';  // the add-on's frame, not a result preview on the wall
    return !!m && !m.querySelector('[aria-busy="true"]') && m.innerText.trim().length > 20 ? 'page' : false;
  }, null, { timeout: LIMIT_MS, polling: 50 });
  if ((await how.jsonValue()) === 'page') return;
  const handle = await page.$('main iframe.embed');
  if (!handle) throw new Error('the add-on frame went away');
  let frame = null;
  while (!frame && Date.now() < deadline) { frame = await handle.contentFrame(); if (!frame) await page.waitForTimeout(50); }
  if (!frame) throw new Error('the add-on frame never loaded');
  await frame.waitForFunction(SHOWN, null, { timeout: Math.max(1000, deadline - Date.now()), polling: 50 });
}

async function heapMb(cdp) {
  const r = await cdp.send('Runtime.getHeapUsage').catch(() => null);
  return r ? Math.round(r.usedSize / 1048576) : null;
}

(async () => {
  const browser = await headless.launch(chromium, {});
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Performance.enable');
  const m = meter(cdp);
  const rows = [];
  // first load: sign in, then the first Home with a cold cache
  let t0 = Date.now(), s0 = snap(m);
  let firstErr = null;
  try {
    await page.goto(launch);
    await page.waitForFunction(() => !location.hash.includes('launch='), null, { timeout: LIMIT_MS });
    await usable(page, false);
  } catch (e) { firstErr = String(e.message || e).split('\n')[0]; }
  // every request of the first load with when it began and ended (ms from the start), files included: the row
  // sat at its limit with nothing to show what it waited for (ORCH-2391)
  const firstMs = firstErr ? null : Date.now() - t0;
  const firstReads = m.all.filter(r => r[1] >= t0).map(([p, a, b]) => [p, a - t0, b - t0]);
  rows.push({ page: 'First load', ms: firstMs, err: firstErr, ...diff(s0, snap(m)), reads: firstReads, heapMb: await heapMb(cdp) });
  if (firstErr) {  // the state is still being built: wait for it once more, so the other pages measure a built state
    try { await usable(page, false); } catch (_) { /* the pages below report their own time */ }
  }
  for (const [name, hash] of PAGES) {
    // A fresh page each time: the time a person waits when opening it by its link. The page before is left
    // first, outside the time: going to the link from it and then reloading counted that page's own switch
    // and teardown (0.5 to 1.5 s after Tickets or Review at 10,000 tickets) on top of the load (ORCH-2289).
    await page.goto('about:blank').catch(() => {});
    s0 = snap(m); t0 = Date.now();
    let ms = null, err = null;
    try {
      await page.goto(base + '/' + hash);
      await usable(page, hash.startsWith('#addon/'));
      ms = Date.now() - t0;
    } catch (e) { err = String(e.message || e).split('\n')[0]; }
    await page.waitForTimeout(500);
    const reads = m.reads.filter(r => r[1] >= t0).map(([p, a, b]) => [p, a - t0, b - t0]);
    rows.push({ page: name, ms, err, ...diff(s0, snap(m)), reads, heapMb: await heapMb(cdp) });
  }
  // an idle minute on Home: nothing clicked, the tab shown (--idle-seconds 0: page times only, ORCH-2370)
  if (IDLE > 0) {
    await page.goto('about:blank').catch(() => {});
    await page.goto(base + '/#home');
    await usable(page, false).catch(() => {});
    await page.waitForTimeout(3000);
    s0 = snap(m);
    await page.waitForTimeout(IDLE * 1000);
    const idle = diff(s0, snap(m));
    const top = Object.entries(idle.byPath).sort((a, b) => b[1] - a[1]).slice(0, 5);
    rows.push({ page: `Idle Home ${IDLE} s`, ms: null, ...idle, byPath: Object.fromEntries(top), heapMb: await heapMb(cdp) });
  }
  await browser.close();
  const kb = n => (n / 1024).toFixed(0).padStart(8) + ' KB';
  for (const r of rows) {
    console.log(`${r.page.padEnd(18)} ${r.ms == null ? (r.err ? 'FAILED' : '   -   ').padStart(9) : (r.ms / 1000).toFixed(2).padStart(7) + ' s'}  wire ${kb(r.enc)}  unpacked ${kb(r.dec)}  ${String(r.reqs).padStart(4)} req  heap ${r.heapMb} MB${r.err ? '  ' + r.err : ''}`);
  }
  if (errors.length) console.log('page errors:', [...new Set(errors)].slice(0, 5).join(' | '));
  if (OUT) fs.writeFileSync(OUT, JSON.stringify({ rows, errors: [...new Set(errors)] }, null, 1));
})().catch(e => { console.error(e); process.exit(1); });
