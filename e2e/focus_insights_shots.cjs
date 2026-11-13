#!/usr/bin/env node
// Focus + Insights screenshots: the kept-in-repo substitute for a mockup. EVERY UI PR that changes a Focus or
// Insights screen MUST update this file (add or adjust a SCREENS entry, and e2e/focus_insights/draft_refs.json).
//
//   node e2e/focus_insights_shots.cjs [outDir] [--only name,name]
//
// Starts the fake-orch-backed Focus server (e2e/focus_insights/server.py: fixture workspace in a temp folder under
// ~/.orch-test, run through `env -i`, never a real workspace, home or key) and shoots every screen at 1280 and 390
// wide. Default outDir: ~/orch-dev/state/drafts-to-build/02-livemap-insights/shots/current/
// Needs: node, `playwright` (npm, global or local) with a Chromium, and `uv`.
//
// The Insights driver appends its own entries to SCREENS (overview, lists, settings) and, if it needs another
// server, adds a second start() call; each screen is { name, url, setup(page), ... } and runs once per width.
// Draft reference pictures: e2e/focus_insights/draft_refs.json (screen name -> draft/final image).
'use strict';
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

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

/** Start a fixture server (default: Focus); resolves { base, stop }. Kills only the process it started. */
async function start(project = 'workspace-addons/focus', script = 'e2e/focus_insights/server.py', tag = 'focus-shots') {
  fs.mkdirSync(path.join(os.homedir(), '.orch-test'), { recursive: true });
  const dir = fs.mkdtempSync(path.join(os.homedir(), `.orch-test/${tag}-`));
  const port = await freePort();
  const env = { HOME: dir, PATH: process.env.PATH, UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache/uv') };
  const child = spawn('env', ['-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`),
    'uv', 'run', '--project', project, 'python', script, dir, String(port)],
  { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  child.stderr.on('data', d => { log += d; });
  await new Promise((ok, no) => {
    child.stdout.on('data', d => { if (String(d).includes('ready')) ok(); });
    child.once('exit', c => no(new Error(`server exited (${c}): ${log.slice(-800)}`)));
    setTimeout(() => no(new Error('server did not start: ' + log.slice(-800))), 120000);
  });
  const stop = () => {
    try { process.kill(child.pid); } catch (e) { /* already gone */ }
    try { if (dir.includes(`/.orch-test/${tag}-`)) fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  };
  return { base: `http://127.0.0.1:${port}`, stop };
}

const settle = (page, ms = Number(process.env.FOCUS_SHOTS_SETTLE_MS) || 4500) => page.waitForTimeout(ms); // polls run every 1.5-5 s

// Add a screen here. setup(page, base) runs after the page loaded; return value is ignored. `server: 'insights'`
// puts the screen on the Insights fixture server (e2e/focus_insights/insights_server.py); default is Focus.
const INS = { server: 'insights' };
const insTab = tab => async p => { await settle(p, 800); await p.click(`#tab-${tab}`); await settle(p, 800); };
const SCREENS = [
  { name: 'start', url: '/', wait: '.fx-ln-card', setup: p => settle(p) }, // strip + Live now + same-file line
  { name: 'start-areas', url: '/', wait: '.fx-areas button', async setup(p) {
    await settle(p);
    await p.click('.fx-areas button');
    await p.waitForSelector('dialog[open]');
  } },
  { name: 'ticket-steps', url: '/t/t_pil2bbbb', wait: '.fx-tab', async setup(p) { await settle(p); await p.click('details.fx-history summary'); } },
  { name: 'ticket-used', url: '/t/t_pil2bbbb', wait: '.fx-tab', async setup(p) { await settle(p); await p.click('#fx-t-used'); } },
  { name: 'ticket-files', url: '/t/t_pil2bbbb', wait: '.fx-tab', async setup(p) { await settle(p); await p.click('#fx-t-files'); } },
  { name: 'ticket-helpers', url: '/t/t_pil2bbbb', wait: '.fx-tab', async setup(p) {
    await settle(p);
    if (!(await p.locator('.fx-agent').first().isVisible())) await p.click('.fx-mobile-tasks'); // the rail is folded on a phone
    await p.click('.fx-agent >> nth=1');
  } },
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
];

async function main() {
  const args = process.argv.slice(2);
  const onlyAt = args.indexOf('--only');
  const only = onlyAt >= 0 ? args.splice(onlyAt, 2)[1].split(',') : null;
  const out = path.resolve((args[0] || DEFAULT_OUT).replace(/^~/, os.homedir()));
  fs.mkdirSync(out, { recursive: true });
  const { chromium } = playwright();
  const wanted = SCREENS.filter(x => !only || only.includes(x.name));
  const servers = { focus: await start() };
  if (wanted.some(x => x.server === 'insights')) {
    servers.insights = await start('workspace-addons/insights', 'e2e/focus_insights/insights_server.py', 'insights-shots');
  }
  const browser = await chromium.launch();
  let failed = 0;
  try {
    for (const s of wanted) {
      const srv = servers[s.server || 'focus'];
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
          if (problems.length) { if (s.server === 'insights') failed++; console.log(`${s.name} ${w}: CONSOLE ERRORS${s.server === 'insights' ? '' : ' (not failing: Focus screens are checked by the Focus smoke test)'} ${problems.join(' | ').slice(0, 400)}`); }
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

module.exports = { SCREENS, start, playwright, settle }; // e2e/focus_insights_smoke.cjs loads every screen from here
if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
