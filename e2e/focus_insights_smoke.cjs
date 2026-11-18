#!/usr/bin/env node
// Page smoke test (CI job `page-smoke`): loads EVERY screen of e2e/focus_insights_shots.cjs (SCREENS: start, areas
// dialog, ticket tabs, helper tree, ... Insights and dashboard screens are appended there) in headless Chromium
// at 1280 wide against the fake-orch fixture server, and FAILS on:
//   - any console error or uncaught exception (pageerror),
//   - any failed request (script, stylesheet, fetch) or HTTP status >= 400,
//   - a missing window global the pages need (EXPECT_GLOBALS), e.g. window.FocusHelpers when helpers.js throws at load.
// A page that throws at load must never reach develop (#525 lost holdText; nothing caught it).
// Then it runs the UX checks of the master gallery (workspace/src/orch_ui/tests/ux_checks.cjs: self-test first, then
// sideways scroll, target size, focus mark, reduced motion, text contrast), and the click-through of the new Focus
// (e2e/focus_d/clickthrough.cjs: its ready steps at three widths), and the six dashboard browser tests (e2e/dash_*.cjs:
// Lessons, Run now, Allow script, Sync card, page health at 1280/1920/390/320, same numbers on every page), and the
// dashboard click-throughs (workspace-addons/dashboard/clickthrough: every dashboard feature done, reloaded and checked
// on a seeded demo workspace with the real server; a feature nobody clicked fails by name). They run here because the CI job
// `page-smoke` is the one that has Chromium and the bot cannot add a workflow file.
//
//   node e2e/focus_insights_smoke.cjs        (exit 0 = all screens clean)
'use strict';
const { SCREENS, start, startExtra, playwright } = require('./focus_insights_shots.cjs');

process.env.FOCUS_SHOTS_SETTLE_MS = process.env.FOCUS_SHOTS_SETTLE_MS || '2500';
// Globals every Focus page must have after load (the ticket and start screens both use them).
const EXPECT_GLOBALS = ['FocusStore', 'FocusHelpers'];

// Every dashboard feature's click-through (ORCH-308) runs alongside everything below from the start, in its own
// throw-away home with its own server, and is waited for at the end: one after the other they no longer fit the job.
const clickRun = (() => {
  const sp = require('node:child_process');
  const PW_DIR = process.env.PW_DIR || sp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
  const c = sp.spawn(process.execPath, [require('node:path').join(__dirname, '..', 'workspace-addons', 'dashboard', 'clickthrough', 'run.cjs')],
    { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PW_DIR } });
  let out = '';
  c.stdout.on('data', d => { out += d; });
  c.stderr.on('data', d => { out += d; });
  process.on('exit', () => { if (c.exitCode === null) { process.stdout.write(out); c.kill(); } });
  return new Promise(ok => c.on('close', code => ok({ code, out })));
})();

(async () => {
  const { chromium } = playwright();
  const servers = { focus: await start(), ...(await startExtra(SCREENS)) };
  const browser = await chromium.launch();
  const problems = [];
  try {
    for (const s of SCREENS) {
      const srv = servers[s.server || 'focus'];
      const page = await browser.newPage({ viewport: { width: s.smokeWidth || 1280, height: 900 } });
      const note = what => problems.push(`${s.name}: ${what}`);
      page.on('console', m => { if (m.type() === 'error') note(`console error: ${m.text().slice(0, 300)}`); });
      page.on('pageerror', e => note(`uncaught exception: ${String(e.message).slice(0, 300)}`));
      page.on('requestfailed', r => note(`request failed: ${r.url().replace(srv.base, '')} (${r.failure() && r.failure().errorText})`));
      page.on('response', r => { if (r.status() >= 400) note(`HTTP ${r.status()}: ${r.url().replace(srv.base, '')}`); });
      try {
        await page.goto(srv.base + s.url);
        if (s.wait) await page.waitForSelector(s.wait, { timeout: 20000 });
        await s.setup(page, srv.base);
        for (const g of s.server ? [] : EXPECT_GLOBALS) { // the Focus pages' globals; Insights has its own page
          if (!(await page.evaluate(name => typeof window[name] !== 'undefined', g))) note(`window.${g} is missing`);
        }
      } catch (e) {
        note(`screen did not load: ${String(e.message).split('\n')[0]}`);
      } finally { await page.close(); }
      console.log(`${s.name}: ${problems.some(p => p.startsWith(s.name + ':')) ? 'PROBLEM' : 'ok'}`);
    }
  } finally { await browser.close(); Object.values(servers).forEach(x => x.stop()); }
  if (problems.length) {
    console.error('\nPAGE SMOKE FAILED:\n' + [...new Set(problems)].map(p => '  - ' + p).join('\n'));
    process.exit(1);
  }
  console.log(`page smoke ok: ${SCREENS.length} screens`);
  const ux = require('node:path').join(__dirname, '../workspace/src/orch_ui/tests/ux_checks.cjs');
  for (const extra of [['--selftest'], []]) {
    const r = require('node:child_process').spawnSync(process.execPath, [ux, ...extra], { stdio: 'inherit' });
    if (r.status !== 0) process.exit(1);
  }
  // The click-through of the new Focus (draft D, e2e/focus_d): every ready step at 1280, 1920 and 390.
  const out = require('node:fs').mkdtempSync(require('node:path').join(require('node:os').tmpdir(), 'focus-d-'));
  const ct = require('node:child_process').spawnSync(process.execPath, [require('node:path').join(__dirname, 'focus_d', 'clickthrough.cjs'), '--out', out], { stdio: 'inherit' });
  require('node:fs').rmSync(out, { recursive: true, force: true });
  if (ct.status !== 0) process.exit(1);
  // The six dashboard tests (node --test files). They find Playwright through PW_DIR: the global install of the job.
  const sp = require('node:child_process');
  const PW_DIR = process.env.PW_DIR || sp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
  const shots = require('node:fs').mkdtempSync(require('node:path').join(require('node:os').tmpdir(), 'dash-e2e-'));
  const failed = [];
  for (const name of ['dash_lessons', 'dash_run_now', 'dash_allow_script', 'dash_sync_card', 'dash_page_health', 'dash_same_numbers']) {
    const r = sp.spawnSync(process.execPath, ['--test', require('node:path').join(__dirname, name + '.cjs')],
      { stdio: 'inherit', env: { ...process.env, PW_DIR, SHOTS_DIR: require('node:path').join(shots, name) } });
    if (r.status !== 0) failed.push(name);
  }
  require('node:fs').rmSync(shots, { recursive: true, force: true });
  if (failed.length) { console.error('DASHBOARD E2E FAILED: ' + failed.join(', ')); process.exit(1); }
  // Every dashboard feature's click-through (ORCH-308), on a seeded workspace with the real dashboard server.
  const click = await clickRun;
  process.stdout.write('\n--- dashboard click-throughs (ran alongside the checks above) ---\n' + click.out);
  if (click.code !== 0) { console.error('DASHBOARD CLICK-THROUGHS FAILED (see above)'); process.exit(1); }
})().catch(e => { console.error(e); process.exit(1); });
