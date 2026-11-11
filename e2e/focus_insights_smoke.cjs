#!/usr/bin/env node
// Page smoke test (CI job `page-smoke`): loads EVERY screen of e2e/focus_insights_shots.cjs (SCREENS: start, areas
// dialog, ticket tabs, helper tree, ... Insights screens are appended there by their driver) in headless Chromium
// at 1280 wide against the fake-orch fixture server, and FAILS on:
//   - any console error or uncaught exception (pageerror),
//   - any failed request (script, stylesheet, fetch) or HTTP status >= 400,
//   - a missing window global the pages need (EXPECT_GLOBALS), e.g. window.FocusHelpers when helpers.js throws at load.
// A page that throws at load must never reach develop (#525 lost holdText; nothing caught it).
//
//   node e2e/focus_insights_smoke.cjs        (exit 0 = all screens clean)
'use strict';
const { SCREENS, start, playwright } = require('./focus_insights_shots.cjs');

process.env.FOCUS_SHOTS_SETTLE_MS = process.env.FOCUS_SHOTS_SETTLE_MS || '2500';
// Globals every Focus page must have after load (the ticket and start screens both use them).
const EXPECT_GLOBALS = ['FocusStore', 'FocusHelpers'];

(async () => {
  const { chromium } = playwright();
  const srv = await start();
  const browser = await chromium.launch();
  const problems = [];
  try {
    for (const s of SCREENS) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const note = what => problems.push(`${s.name}: ${what}`);
      page.on('console', m => { if (m.type() === 'error') note(`console error: ${m.text().slice(0, 300)}`); });
      page.on('pageerror', e => note(`uncaught exception: ${String(e.message).slice(0, 300)}`));
      page.on('requestfailed', r => note(`request failed: ${r.url().replace(srv.base, '')} (${r.failure() && r.failure().errorText})`));
      page.on('response', r => { if (r.status() >= 400) note(`HTTP ${r.status()}: ${r.url().replace(srv.base, '')}`); });
      try {
        await page.goto(srv.base + s.url);
        if (s.wait) await page.waitForSelector(s.wait, { timeout: 20000 });
        await s.setup(page, srv.base);
        for (const g of EXPECT_GLOBALS) {
          if (!(await page.evaluate(name => typeof window[name] !== 'undefined', g))) note(`window.${g} is missing`);
        }
      } catch (e) {
        note(`screen did not load: ${String(e.message).split('\n')[0]}`);
      } finally { await page.close(); }
      console.log(`${s.name}: ${problems.some(p => p.startsWith(s.name + ':')) ? 'PROBLEM' : 'ok'}`);
    }
  } finally { await browser.close(); srv.stop(); }
  if (problems.length) {
    console.error('\nPAGE SMOKE FAILED:\n' + [...new Set(problems)].map(p => '  - ' + p).join('\n'));
    process.exit(1);
  }
  console.log(`page smoke ok: ${SCREENS.length} screens`);
})().catch(e => { console.error(e); process.exit(1); });
