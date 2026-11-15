#!/usr/bin/env node
// #692 d2 screenshots: real Focus pages over fixture data (e2e/focus_692/server_d2.py), 1280 wide, own
// Chromium with a mock keychain and a temp profile. node e2e/focus692_d2_shots.cjs [outDir]
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { start, playwright, settle } = require('./focus_insights_shots.cjs');

const OUT = path.resolve((process.argv[2] || path.join(os.homedir(), 'orch-dev/state/e2e-shots')).replace(/^~/, os.homedir()));
const SCREENS = [{ name: 'results-cards', url: '/', wait: '.result-card', setup: p => settle(p, 2500) }];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const { chromium } = playwright();
  const srv = await start('workspace-addons/focus', 'e2e/focus_692/server_d2.py', 'focus692-d2');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'f692-prof-'));
  const ctx = await chromium.launchPersistentContext(profile, { args: ['--use-mock-keychain', '--password-store=basic'], viewport: { width: 1280, height: 900 } });
  let failed = 0;
  try {
    for (const s of SCREENS) {
      const page = await ctx.newPage();
      const errs = [];
      page.on('pageerror', e => errs.push(e.message));
      try {
        await page.goto(srv.base + s.url);
        await page.waitForSelector(s.wait, { timeout: 20000 });
        await settle(page, 2500);
        if (s.setup) await s.setup(page);
        await page.screenshot({ path: path.join(OUT, `focus692-d-${s.name}.png`), fullPage: true });
        console.log(`${s.name}: ok${errs.length ? ' (page errors: ' + errs.join(' | ').slice(0, 200) + ')' : ''}`);
      } catch (e) { failed++; console.log(`${s.name}: FAILED ${String(e.message).split('\n')[0]}`); } finally { await page.close(); }
    }
  } finally { await ctx.close(); srv.stop(); fs.rmSync(profile, { recursive: true, force: true }); }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
