#!/usr/bin/env node
// Page smoke test (CI job `page-smoke`): loads EVERY screen of e2e/focus_insights_shots.cjs (SCREENS: the Insights
// and dashboard screens) in headless Chromium at 1280 wide against its fixture server, and FAILS on:
//   - any console error or uncaught exception (pageerror),
//   - any failed request (script, stylesheet, fetch) or HTTP status >= 400,
// A page that throws at load must never reach develop (#525 lost holdText; nothing caught it).
// Then it runs the UX checks of the master gallery (workspace/src/orch_ui/tests/ux_checks.cjs: self-test first, then
// sideways scroll, target size, focus mark, reduced motion, text contrast), and the click-through of the new Focus
// (e2e/focus_d/clickthrough.cjs: its ready steps at three widths), and the six dashboard browser tests plus the Insights retry test (e2e/dash_*.cjs, e2e/focus_insights_retry.cjs:
// Lessons, Run now, Allow script, Sync card, page health at 1280/1920/390/320, same numbers on every page). They run here
// because the CI job `page-smoke` is the one that has Chromium. The dashboard click-throughs (every dashboard feature)
// have their own job, `dashboard-clickthroughs` (they no longer fit in this job's 10 minutes).
//
// CI runs it in three parts, each a job of its own (ORCH-1654: all in one job grew to its 10 minutes and was cancelled):
//   node e2e/focus_insights_smoke.cjs                  everything (exit 0 = all clean)
//   node e2e/focus_insights_smoke.cjs --part pages     the screens, the UX checks and the dashboard tests
//   node e2e/focus_insights_smoke.cjs --part focus-1   the first half of the Focus click-through (focus-2: the second)
// AXE_CORE_JS=<axe.min.js>: the Focus click-through also runs axe-core and fails on a serious or critical finding.
// SMOKE_BUDGET_S=<seconds>: stop with the page, test or click-through step that was running when the time is up, before
// the CI job's own limit cancels it without a word (a cancelled job gives develop no verdict).
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, execFileSync } = require('node:child_process');
const { SCREENS, startExtra, playwright } = require('./focus_insights_shots.cjs');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

process.env.FOCUS_SHOTS_SETTLE_MS = process.env.FOCUS_SHOTS_SETTLE_MS || '2500';
const FOCUS_PARTS = 2;
const PARTS = ['all', 'pages', ...Array.from({ length: FOCUS_PARTS }, (_, i) => `focus-${i + 1}`)];
const DASH_TESTS = ['dash_lessons', 'dash_run_now', 'dash_allow_script', 'dash_sync_card', 'dash_page_health', 'dash_same_numbers', 'focus_insights_retry'];

const argv = process.argv.slice(2);
const part = argv[0] === '--part' ? argv[1] : argv.length ? null : 'all';
if (!PARTS.includes(part) || argv.length > 2) {
  console.error(`usage: node e2e/focus_insights_smoke.cjs [--part ${PARTS.join('|')}]`);
  process.exit(2);
}

// The time guard: what runs now (a screen, a test file, a click-through step through SMOKE_PROGRESS), and the child
// to stop when the time is up.
const started = Date.now();
const progressFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'smoke-progress-')), 'now.txt');
process.on('exit', () => fs.rmSync(path.dirname(progressFile), { recursive: true, force: true }));
let now = 'starting';
let child = null;
let stopServers = () => {}; // the screens' fixture servers, while they run in this process
const budget = Number(process.env.SMOKE_BUDGET_S || 0);
if (budget > 0) {
  setTimeout(() => {
    let step = '';
    try { step = fs.readFileSync(progressFile, 'utf8').trim(); } catch { /* the child wrote none */ }
    console.error(`\nPAGE SMOKE OUT OF TIME: stopped after ${budget} s (SMOKE_BUDGET_S) in ${now}${step ? `, at ${step}` : ''}.`);
    // the child's whole process group: its fixture servers and its browser too, not only the node script
    // (Chromium ends by itself when its control pipe closes with the process that started it)
    if (child) try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
    try { stopServers(); } catch { /* exiting anyway */ }
    process.exit(1);
  }, budget * 1000).unref();
}
const at = what => {
  now = what;
  try { fs.rmSync(progressFile, { force: true }); } catch { /* only a hint */ }
};
const elapsed = () => `${Math.round((Date.now() - started) / 1000)} s`;

/** Runs a node script with the job's output; resolves to its exit code. */
function run(args, env) {
  return new Promise(resolve => {
    // a process group of its own (detached), so the time guard can stop everything it started
    child = spawn(process.execPath, args, { stdio: 'inherit', detached: process.platform !== 'win32', env: { ...process.env, SMOKE_PROGRESS: progressFile, ...env } });
    child.on('exit', code => { child = null; resolve(code === null ? 1 : code); });
  });
}

async function screens() {
  const { chromium } = playwright();
  const servers = await startExtra(SCREENS);
  stopServers = () => Object.values(servers).forEach(x => x.stop());
  const browser = await headless.launch(chromium);
  const problems = [];
  try {
    for (const s of SCREENS) {
      at(`screen ${s.name}`);
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
  } finally { await browser.close(); stopServers(); stopServers = () => {}; }
  if (problems.length) {
    console.error('\nPAGE SMOKE FAILED:\n' + [...new Set(problems)].map(p => '  - ' + p).join('\n'));
    return false;
  }
  console.log(`page smoke ok: ${SCREENS.length} screens`);
  const ux = path.join(__dirname, '../workspace/src/orch_ui/tests/ux_checks.cjs');
  for (const extra of [['--selftest'], []]) {
    at(`UX checks of the master gallery${extra.length ? ' (self-test)' : ''}`);
    if (await run([ux, ...extra]) !== 0) return false;
  }
  return true;
}

// The click-through of the new Focus (draft D, e2e/focus_d): every ready step at 1280, 1920 and 390; `shard` = k/n.
async function focus(shard) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'focus-d-'));
  at(`Focus click-through${shard ? ` part ${shard}` : ''}`);
  // AXE_CORE_JS (CI sets it): axe-core on every step and width too, a serious or critical finding fails (#2420)
  const axe = process.env.AXE_CORE_JS ? ['--axe', process.env.AXE_CORE_JS] : [];
  const code = await run([path.join(__dirname, 'focus_d', 'clickthrough.cjs'), '--out', out, ...(shard ? ['--shard', shard] : []), ...axe]);
  fs.rmSync(out, { recursive: true, force: true });
  return code === 0;
}

// The dashboard tests and the Insights retry test (node --test files). They find Playwright through PW_DIR: the global install of the job.
async function dashboard() {
  const PW_DIR = process.env.PW_DIR || execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
  const shots = fs.mkdtempSync(path.join(os.tmpdir(), 'dash-e2e-'));
  const failed = [];
  for (const name of DASH_TESTS) {
    at(`dashboard test e2e/${name}.cjs`);
    if (await run(['--test', path.join(__dirname, name + '.cjs')], { PW_DIR, SHOTS_DIR: path.join(shots, name) }) !== 0) failed.push(name);
  }
  fs.rmSync(shots, { recursive: true, force: true });
  if (failed.length) console.error('DASHBOARD E2E FAILED: ' + failed.join(', '));
  return !failed.length;
}

(async () => {
  let ok = true;
  if (part === 'all' || part === 'pages') ok = await screens();
  if (ok && part === 'all') ok = await focus(null);
  if (ok && part.startsWith('focus-')) ok = await focus(`${part.slice(6)}/${FOCUS_PARTS}`);
  if (ok && (part === 'all' || part === 'pages')) ok = await dashboard();
  console.log(`page smoke part ${part}: ${ok ? 'ok' : 'FAILED'} in ${elapsed()}`);
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(`${e && e.stack || e}\n(in ${now})`); process.exit(1); });
