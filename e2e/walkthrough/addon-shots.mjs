// Local only (no live servers): two dashboard screenshots for docs/workspace-addons.md.
// Usage: node addon-shots.mjs <out dir>. Needs `orch` installed from this checkout in a temp tool dir (done here).
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUT = path.resolve(process.argv[2] || path.join(REPO, 'docs/images'));
const REAL = os.homedir();
fs.mkdirSync(path.join(REAL, 'orch-dev'), { recursive: true });
const TMP = fs.mkdtempSync(path.join(REAL, 'orch-dev/.tf-shots-'));
const OHOME = fs.mkdtempSync(path.join(REAL, '.orch-e2e-')); // trusted ORCH_HOME: under the real home, no .git above
const env = { HOME: path.join(TMP, 'home'), PATH: `${path.join(TMP, 'bin')}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'en_US.UTF-8', ORCH_REPO: REPO,
  ORCH_HOME: OHOME, UV_TOOL_DIR: path.join(TMP, 'uvtools'), UV_TOOL_BIN_DIR: path.join(TMP, 'bin'), UV_CACHE_DIR: path.join(REAL, '.cache/uv') };
fs.mkdirSync(env.HOME, { recursive: true });
const ws = path.join(TMP, 'Pilatus'); fs.mkdirSync(ws);
const sh = (cmd, cwd = ws) => { const r = spawnSync('sh', ['-c', cmd], { cwd, env, encoding: 'utf8', timeout: 300000 }); if (r.status) throw new Error(cmd + ': ' + r.stderr); return r.stdout.trim(); };
let dash, browser;
try {
  sh(`uv tool install ${REPO}/workspace`, TMP);
  sh('git init -q -b main && orch init && orch addon add dashboard --yes');
  const ids = [];
  for (const t of ['Weekly report for the board', 'Check the nightly import', 'Update the onboarding notes'])
    ids.push(JSON.parse(sh(`orch ticket new "${t}" --json`)).id);
  const port = 18000 + Math.floor(Math.random() * 900);
  dash = spawn('orch', ['dashboard', 'serve', '--port', String(port)], { cwd: ws, env, stdio: 'ignore' });
  for (let i = 0; i < 60; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/`)).ok) break; } catch {} await new Promise(r => setTimeout(r, 250)); }
  browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 760 }, colorScheme: 'light' })).newPage();
  fs.mkdirSync(OUT, { recursive: true });
  await page.goto(`http://127.0.0.1:${port}/#tickets`); await page.waitForSelector('a.card');
  await page.screenshot({ path: path.join(OUT, 'addons-none.png') });
  sh('orch addon add scheduler --yes');
  sh(`orch scheduler repeat ${ids[0]} "0 7 * * 1"`);
  sh(`orch wait ${ids[1]} --until 2099-01-01T08:00:00Z`);
  await page.reload(); await page.waitForSelector('a[href="#addon/scheduler"]');
  await page.click('a[href="#addon/scheduler"]'); await page.waitForSelector('text=Repeating'); await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, 'addons-scheduler.png') });
  console.log('wrote', OUT);
} finally {
  if (browser) await browser.close();
  if (dash) dash.kill();
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.rmSync(OHOME, { recursive: true, force: true });
}
