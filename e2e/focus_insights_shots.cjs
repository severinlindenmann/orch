#!/usr/bin/env node
// Insights and dashboard screenshots: the kept-in-repo substitute for a mockup. EVERY UI PR that changes an Insights
// screen MUST update this file (add or adjust a SCREENS entry, and e2e/focus_insights/draft_refs.json).
//
//   node e2e/focus_insights_shots.cjs [outDir] [--only name,name]
//
// Starts the fixture servers its screens name (e2e/focus_insights/*_server.py: fixture workspace in a temp folder under
// ~/.orch-test, run through `env -i`, never a real workspace, home or key) and shoots every screen at 1280 and 390
// wide. Default outDir: ~/orch-dev/state/drafts-to-build/02-livemap-insights/shots/current/
// Needs: node, `playwright` (npm, global or local) with a Chromium, and `uv`.
//
// Each screen is { name, url, server, setup(page), ... } and runs once per width. (The new Focus is drawn by the
// dashboard and has its own click-through, e2e/focus_d.)
// Draft reference pictures: e2e/focus_insights/draft_refs.json (screen name -> draft/final image).
'use strict';
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const REPO = path.resolve(__dirname, '..');
const WIDTHS = [[1280, 900], [390, 844]];
const DEFAULT_OUT = path.join(os.homedir(), 'orch-dev/state/drafts-to-build/02-livemap-insights/shots/current');

function playwright() {
  try { return require('playwright'); } catch (e) { /* fall through */ }
  const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
  return require(path.join(root, 'playwright'));
}

const freePort = () => new Promise((ok, no) => {
  const s = net.createServer();
  s.once('error', no);
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); });
});

/** Start a fixture server; resolves { base, stop }. Kills only the process it started. */
async function start(project, script, tag) {
  fs.mkdirSync(path.join(os.homedir(), '.orch-test'), { recursive: true });
  const dir = fs.mkdtempSync(path.join(os.homedir(), `.orch-test/${tag}-`));
  const port = await freePort();
  const env = { HOME: dir, USERPROFILE: dir, ORCH_HOME: path.join(dir, 'orch'), ORCH_HOME_STRICT: '1', PATH: process.env.PATH, UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache/uv') };
  const child = spawn('env', ['-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`),
    'uv', 'run', '--project', project, 'python', script, dir, String(port)],
  // its own process group: stop() ends uv AND the python it starts (uv runs python as a child, not in its place)
  { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  let log = '';
  child.stderr.on('data', d => { log += d; });
  // The start-up timer is cleared once the server is ready: left running it kept a `node --test` file alive for two
  // more minutes after its test passed and pushed the page-smoke job past its 10 minutes (ORCH-1557).
  let timer;
  await new Promise((ok, no) => {
    child.stdout.on('data', d => { if (String(d).includes('ready')) ok(); });
    child.once('exit', c => no(new Error(`server exited (${c}): ${log.slice(-800)}`)));
    timer = setTimeout(() => no(new Error('server did not start: ' + log.slice(-800))), 120000);
  }).finally(() => clearTimeout(timer));
  // Ends the whole group it started, so no python is left behind (ORCH-1558), and lets go of the pipes and the child.
  const stop = () => {
    const kill = sig => { try { process.kill(-child.pid, sig); } catch (e) { try { process.kill(child.pid, sig); } catch (e2) { /* already gone */ } } };
    kill('SIGTERM');
    setTimeout(() => kill('SIGKILL'), 3000).unref();
    child.stdout.destroy(); child.stderr.destroy(); child.unref(); // nothing of the server keeps this process alive
    try { if (dir.includes(`/.orch-test/${tag}-`)) fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  };
  return { base: `http://127.0.0.1:${port}`, stop };
}

// The fixture servers a screen names with `server:`.
const EXTRA = {
  insights: ['workspace-addons/insights', 'e2e/focus_insights/insights_server.py', 'insights-shots'],
  dashboard: ['workspace-addons/dashboard', 'e2e/focus_insights/dashboard_server.py', 'dashboard-shots'],
};
async function startExtra(screens) {
  const out = {};
  for (const name of Object.keys(EXTRA)) if (screens.some(x => x.server === name)) out[name] = await start(...EXTRA[name]);
  return out;
}

const settle = (page, ms = Number(process.env.FOCUS_SHOTS_SETTLE_MS) || 4500) => page.waitForTimeout(ms); // polls run every 1.5-5 s

// Add a screen here. setup(page, base) runs after the page loaded; return value is ignored. `server: 'insights'`
// puts the screen on the Insights fixture server (e2e/focus_insights/insights_server.py).
const INS = { server: 'insights' };
const DASH = { server: 'dashboard' }; // the real dashboard server (e2e/focus_insights/dashboard_server.py)
const STYLE_GUIDE_SECTIONS = ['kit', 'foundations', 'controls', 'results', 'states', 'overlays', 'motion'];
const insTab = tab => async p => { await settle(p, 800); await p.click(`#tab-${tab}`); await settle(p, 800); };
const SCREENS = [
  { name: 'insights-overview', url: '/', ...INS, wait: '#rows tr[data-name]', setup: p => settle(p, 800) }, // metrics + skill use + What helpers use table
  { name: 'insights-connections', url: '/', ...INS, wait: '#rows tr[data-name]', setup: insTab('connections') },
  { name: 'insights-keys', url: '/', ...INS, wait: '#rows tr[data-name]', setup: insTab('keys') },
  { name: 'insights-detail', url: '/', ...INS, wait: '#rows tr[data-name]', async setup(p) {
    await settle(p, 800);
    // the redesigned page has no side panel: the numbers sit in the table row and the services block under it
    await p.locator('#services').scrollIntoViewIfNeeded();
    await settle(p, 500);
  } },
  { name: 'insights-settings', url: '/', ...INS, wait: '#rows tr[data-name]', async setup(p) {
    await settle(p, 800);
    await p.click('#settings-link');
    await p.waitForSelector('#settings-body *', { timeout: 20000 });
    await settle(p, 800);
  } },
  // ORCH-67: Settings' 'Open the style guide' opens /styleguide/ in a new tab with every section, clean (the real button
  // on the real dashboard server, files only). The style guide tab is checked here; the smoke test checks Settings.
  { name: 'dashboard-style-guide', url: '/#settings/about', ...DASH, wait: '[data-key="settings-style-guide"]', async setup(p, base) {
    const [tab] = await Promise.all([p.waitForEvent('popup', { timeout: 15000 }), p.click('[data-key="settings-style-guide"]')]);
    const problems = [];
    tab.on('pageerror', e => problems.push(`uncaught: ${e.message}`));
    tab.on('console', m => { if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 200)}`); });
    tab.on('requestfailed', r => problems.push(`request failed: ${r.url().replace(base, '')}`));
    tab.on('response', r => { if (r.status() >= 400) problems.push(`HTTP ${r.status()}: ${r.url().replace(base, '')}`); });
    await tab.waitForLoadState('load');
    await tab.reload({ waitUntil: 'networkidle' }); // again with the listeners on from the first request
    const url = new URL(tab.url());
    if (url.pathname !== '/styleguide/') problems.push(`opened ${url.pathname}, not /styleguide/`);
    const seen = await tab.evaluate(() => [...document.querySelectorAll('section.spec-section')].map(x => x.id));
    for (const id of STYLE_GUIDE_SECTIONS) if (!seen.includes(id)) problems.push(`style guide has no ${id} section`);
    await tab.close();
    if (problems.length) throw new Error('style guide tab: ' + problems.join(' | '));
  } },
];

async function main() {
  const args = process.argv.slice(2);
  const onlyAt = args.indexOf('--only');
  const only = onlyAt >= 0 ? args.splice(onlyAt, 2)[1].split(',') : null;
  const out = path.resolve((args[0] || DEFAULT_OUT).replace(/^~/, os.homedir()));
  fs.mkdirSync(out, { recursive: true });
  const { chromium } = playwright();
  const wanted = SCREENS.filter(x => !only || only.includes(x.name));
  const servers = await startExtra(wanted);
  const browser = await headless.launch(chromium);
  let failed = 0;
  try {
    for (const s of wanted) {
      const srv = servers[s.server];
      for (const [w, h] of WIDTHS) {
        const page = await browser.newPage({ viewport: { width: w, height: h } });
        const problems = [];
        page.on('pageerror', e => problems.push(`uncaught: ${e.message}`));
        page.on('console', m => { if (m.type() === 'error') problems.push(`console: ${m.text()}`); });
        try {
          await page.goto(srv.base + s.url);
          if (s.wait) await page.waitForSelector(s.wait, { timeout: 20000 });
          await s.setup(page, srv.base);
          await page.waitForTimeout(400);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
          await page.screenshot({ path: path.join(out, `${s.name}-${w}.png`), fullPage: true });
          console.log(`${s.name} ${w}: ok${overflow ? ' (HORIZONTAL OVERFLOW)' : ''}`);
          if (overflow) failed++;
          if (problems.length) { failed++; console.log(`${s.name} ${w}: CONSOLE ERRORS ${problems.join(' | ').slice(0, 400)}`); }
        } catch (e) {
          failed++;
          console.log(`${s.name} ${w}: FAILED ${String(e.message).split('\n')[0]}`);
        } finally { await page.close(); }
      }
    }
  } finally { await browser.close(); Object.values(servers).forEach(x => x.stop()); }
  console.log(`shots in ${out}`);
  process.exit(failed ? 1 : 0);
}

module.exports = { SCREENS, start, startExtra, playwright, settle }; // e2e/focus_insights_smoke.cjs loads every screen from here
if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
