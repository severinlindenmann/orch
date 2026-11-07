// Click-through smoke of a running workspace dashboard, one screenshot per step and width. Run by dashboard-flow.ps1
// inside the Windows machine (Playwright there, so no port leaves the VM); it also runs on a Mac or Linux:
//   node dashboard-smoke.mjs <dashboard url> <screenshot folder> <ticket title>
// Prints "ok: <step>" or "FAIL: <step>: <why>" per step and exits 1 if any step failed. A step fails on a console
// error, an uncaught page error, an HTTP 4xx/5xx the page asked for, or (narrow widths) a page wider than the window.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const [URL_, OUT, TITLE] = process.argv.slice(2);
if (!URL_ || !OUT || !TITLE) { console.error('usage: node dashboard-smoke.mjs <url> <out> <ticket title>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });
const base = URL_.replace(/\/$/, '');
let n = 0, failed = 0, problems = [];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on('console', m => { if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 200)}`); });
page.on('pageerror', e => problems.push(`page error: ${String(e).slice(0, 200)}`));
page.on('response', r => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url().replace(base, '')}`); });

async function shot(name) {
  const file = `${String(++n).padStart(2, '0')}-${name}-${page.viewportSize().width}.png`;
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  return file;
}
async function step(name, fn) {
  problems = [];
  try {
    await fn();
    await page.waitForTimeout(300); // late console errors of the page just shown
    const file = await shot(name);
    if (problems.length) throw new Error(problems.join('; '));
    console.log(`ok: ${name} (${file})`);
  } catch (e) {
    failed++;
    let file = '';
    try { file = await shot(`${name}-fail`); } catch {}
    console.log(`FAIL: ${name}: ${String(e.message || e).split('\n')[0].slice(0, 400)} (${file})`);
  }
}
async function fitsWidth() {
  const [sw, iw] = await page.evaluate(() => [document.scrollingElement.scrollWidth, window.innerWidth]);
  if (sw > iw + 1) throw new Error(`page is ${sw}px wide in a ${iw}px window (scrolls sideways)`);
}

await step('home', async () => {
  await page.goto(`${base}/#home`);
  await page.waitForLoadState('networkidle');
});
await step('tickets', async () => {
  await page.goto(`${base}/#tickets`);
  await page.locator('a[href^="#ticket/"]', { hasText: TITLE }).first().waitFor();
});
await step('ticket', async () => {
  await page.locator('a[href^="#ticket/"]', { hasText: TITLE }).first().click();
  await page.waitForFunction(() => location.hash.startsWith('#ticket/'));
  await page.getByText(TITLE).first().waitFor();
});
for (const [name, hash] of [['general', '#general'], ['settings', '#settings']]) {
  await step(name, async () => {
    await page.goto(`${base}/${hash}`);
    await page.waitForLoadState('networkidle');
  });
}
for (const width of [720, 390]) {
  await page.setViewportSize({ width, height: 800 });
  for (const [name, hash] of [['home', '#home'], ['tickets', '#tickets']]) {
    await step(`${name}-narrow`, async () => {
      await page.goto(`${base}/${hash}`);
      await page.waitForLoadState('networkidle');
      await fitsWidth();
    });
  }
}
await browser.close();
console.log(failed ? `smoke: ${failed} step(s) failed` : 'smoke: all steps ok'); // not "RESULT": that line is the flow's
process.exit(failed ? 1 : 0);
