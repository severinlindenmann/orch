#!/usr/bin/env node
// Earlier chats in the Focus "This session" panel, at 1280, 1920 and 390 wide. node e2e/focus_old_sessions/shots.cjs [outDir]
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { start, playwright, settle } = require('../focus_insights_shots.cjs');

const OUT = path.resolve((process.argv[2] || path.join(os.homedir(), 'orch-dev/state/e2e-shots')).replace(/^~/, os.homedir()));
const SIZES = [[1280, 900], [1920, 1080], [390, 844]];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const { chromium } = playwright();
  const srv = await start('workspace-addons/focus', 'e2e/focus_old_sessions/server.py', 'focus-oldsess');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'fos-prof-'));
  const ctx = await chromium.launchPersistentContext(profile, { args: ['--use-mock-keychain', '--password-store=basic'], viewport: { width: 1280, height: 900 } });
  let failed = 0;
  try {
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(e.message));
    await page.goto(srv.base + '/t/t_pil1aaaa');
    await page.waitForSelector('button.fx-live', { state: 'attached', timeout: 20000 });
    await settle(page, 2500);
    for (const [w, h] of SIZES) {
      try {
        await page.setViewportSize({ width: w, height: h });
        await settle(page, 500);
        const panel = page.locator('#fx-session, [aria-labelledby=fx-session-title], .fx-session').first();
        if (await page.locator('#fx-session[hidden]').count()) {
          await page.locator('button.fx-live').first().click({ timeout: 5000 });
        }
        await page.waitForSelector('text=Earlier conversations', { timeout: 10000 }).catch(async e => { await page.screenshot({ path: path.join(OUT, 'debug.png') }); console.log(await page.evaluate(() => document.querySelector('#fx-session')?.outerHTML.slice(0, 600))); throw e; });
        const show = page.locator('button:has-text("Show")').first();
        if (!(await page.locator('text=Helper:').count())) await show.click();
        await page.waitForSelector('text=Helper:', { timeout: 5000 });
        await page.screenshot({ path: path.join(OUT, `old-sessions-${w}.png`), fullPage: true });
        console.log(`${w}: ok${errs.length ? ' (page errors: ' + errs.join(' | ').slice(0, 200) + ')' : ''}`);
      } catch (e) { failed++; console.log(`${w}: FAILED ${String(e.message).split('\n')[0]}`); }
    }
  } finally { await ctx.close(); srv.stop(); fs.rmSync(profile, { recursive: true, force: true }); }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
