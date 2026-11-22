#!/usr/bin/env node
// Page smoke test (CI job `page-smoke`): loads EVERY screen of e2e/focus_insights_shots.cjs (SCREENS: the Insights
// and dashboard screens) in headless Chromium at 1280 wide against its fixture server, and FAILS on:
//   - any console error or uncaught exception (pageerror),
//   - any failed request (script, stylesheet, fetch) or HTTP status >= 400,
// A page that throws at load must never reach develop (#525 lost holdText; nothing caught it).
// Then it runs the UX checks of the master gallery (workspace/src/orch_ui/tests/ux_checks.cjs: self-test first, then
// sideways scroll, target size, focus mark, reduced motion, text contrast), and the click-through of the new Focus
// (e2e/focus_d/clickthrough.cjs: its ready steps at three widths), and the six dashboard browser tests (e2e/dash_*.cjs:
// Lessons, Run now, Allow script, Sync card, page health at 1280/1920/390/320, same numbers on every page). They run here
// because the CI job `page-smoke` is the one that has Chromium. The dashboard click-throughs (every dashboard feature)
// have their own job, `dashboard-clickthroughs` (they no longer fit in this job's 10 minutes).
//
//   node e2e/focus_insights_smoke.cjs        (exit 0 = all screens clean)
'use strict';
const { SCREENS, startExtra, playwright } = require('./focus_insights_shots.cjs');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

process.env.FOCUS_SHOTS_SETTLE_MS = process.env.FOCUS_SHOTS_SETTLE_MS || '2500';

(async () => {
  const { chromium } = playwright();
  const servers = await startExtra(SCREENS);
  const browser = await headless.launch(chromium);
  const problems = [];
  try {
    for (const s of SCREENS) {
      const srv = servers[s.server];
      const page = await browser.newPage({ viewport: { width: s.smokeWidth || 1280, height: 900 } });
      const note = what => problems.push(`${s.name}: ${what}`);
      page.on('console', m => { if (m.type() === 'error') note(`console error: ${m.text().slice(0, 300)}`); });
      page.on('pageerror', e => note(`uncaught exception: ${String(e.message).slice(0, 300)}`));
      page.on('requestfailed', r => {
        const err = r.failure() && r.failure().errorText;
        // A poll that sends its tag back (If-None-Match) and gets 304 shows in headless Chromium as
        // net::ERR_ABORTED, not as a response (ORCH-1620 sessions poll, ORCH-1640): unchanged, not a failure.
        if (err === 'net::ERR_ABORTED' && r.headers()['if-none-match']) return;
        note(`request failed: ${r.url().replace(srv.base, '')} (${err})`);
      });
      page.on('response', r => { if (r.status() >= 400) note(`HTTP ${r.status()}: ${r.url().replace(srv.base, '')}`); });
      try {
        await page.goto(srv.base + s.url);
        if (s.wait) await page.waitForSelector(s.wait, { timeout: 20000 });
        await s.setup(page, srv.base);
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
})().catch(e => { console.error(e); process.exit(1); });
