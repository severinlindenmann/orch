// Click-through smoke of a running workspace dashboard, one screenshot per step and width. Run by dashboard-flow.ps1
// inside the Windows machine (Playwright there, so no port leaves the VM); it also runs on a Mac or Linux:
//   node dashboard-smoke.mjs <dashboard url> <screenshot folder> <ticket title> [<launch url with #launch=token>]
// With the launch url it also checks the page session: token -> cookie, a person op without a session is 403,
// a plain op and a proof op work from the page (recorded as human:).
// Prints "ok: <step>" or "FAIL: <step>: <why>" per step and exits 1 if any step failed. A step fails on a console
// error, an uncaught page error, an HTTP 4xx/5xx the page asked for, or (narrow widths) a page wider than the window.
import { chromium, request } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const [URL_, OUT, TITLE, LAUNCH] = process.argv.slice(2);
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


// ---- Page session and proof (#431): is Windows watch-only? Session from the launch token, a person op without a session is
// refused, one plain op and one proof op work from the page, each with a screenshot.
const act = (op, args) => page.evaluate(async ([op, args]) => {
  const r = await fetch('/api/act', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ op, args }) });
  return { status: r.status, text: (await r.text()).slice(0, 300) };
}, [op, args]);
const stateOf = () => page.evaluate(async () => (await fetch('/api/state')).json());
const findTicket = (st, title) => { let hit = null; (function walk(o) { if (hit || !o || typeof o !== 'object') return; if (o.title === title && typeof o.id === 'string' && o.id.startsWith('t_')) { hit = o; return; } for (const v of Object.values(o)) walk(v); })(st); return hit; };
let TID_ = null, CID_ = null;
if (LAUNCH) {
  await step('proof-1-launch-token-opens-a-session', async () => {
    await page.goto(LAUNCH);
    await page.waitForFunction(() => !location.hash.includes('launch='), null, { timeout: 15000 });
    await page.waitForTimeout(2000); // the page reloads once with its session (no networkidle: the page holds a stream open)
    const ckName = `orch_page_dashboard_${new URL(base).port}`; // per server, per port (pageproof.cookie_name)
    const ck = (await page.context().cookies()).find(c => c.name === ckName);
    if (!ck) throw new Error(`no ${ckName} session cookie after the launch URL`);
    if (!ck.httpOnly) throw new Error('the session cookie is not HttpOnly');
  });
  await step('proof-2-plain-op-from-the-page (check.add)', async () => {
    await page.goto(`${base}/#tickets`);
    TID_ = findTicket(await stateOf(), TITLE)?.id;
    if (!TID_) throw new Error('the smoke ticket is not in the state');
    const r = await act('check.add', { ticket: TID_, text: 'Plain op from the page' });
    if (r.status !== 200) throw new Error(`check.add -> ${r.status} ${r.text}`);
    const t = findTicket(await stateOf(), TITLE);
    const c = (t.checklist || []).find(x => /Plain op from the page/.test(JSON.stringify(x)));
    if (!c) throw new Error('the task is not on the ticket');
    CID_ = c.id;
    await page.goto(`${base}/#ticket/${TID_}`); await page.getByText('Plain op from the page').first().waitFor();
  });
  await step('proof-3-no-session-gets-403', async () => {
    const ctx = await request.newContext();
    const r = await ctx.post(`${base}/api/act`, { headers: { 'Content-Type': 'application/json', Origin: base }, data: { op: 'check.wont_do', args: { ticket: TID_, check: CID_, reason: 'no session' } } });
    if (r.status() !== 403) throw new Error(`a person op without a session got ${r.status()}, wanted 403`);
    const r2 = await ctx.post(`${base}/api/act`, { headers: { 'Content-Type': 'application/json', Origin: base }, data: { op: 'answer', args: { ticket: TID_, question: 'q1', answer: 'x' } } });
    if (r2.status() !== 403) throw new Error(`answer without a session got ${r2.status()}, wanted 403`);
    await ctx.dispose();
    problems = problems.filter(p => !p.includes('HTTP 403')); // the 403s above are the point, not page errors
  });
  await step('proof-4-proof-op-from-the-page (Won\'t do, recorded as the person)', async () => {
    const r = await act('check.wont_do', { ticket: TID_, check: CID_, reason: 'Not needed (smoke)' });
    if (r.status !== 200) throw new Error(`check.wont_do -> ${r.status} ${r.text}`);
    const t = findTicket(await stateOf(), TITLE);
    const hist = JSON.stringify(t.history || []);
    if (!/human:/.test(hist) || !/won.?t do|wont/i.test(hist + JSON.stringify(t.checklist))) throw new Error('not recorded as a person\'s Won\'t do: ' + hist.slice(-300));
    await page.goto(`${base}/#ticket/${TID_}`); await page.getByText('Plain op from the page').first().waitFor();
  });
  await step('proof-5-plain-op-new-ticket-from-the-page', async () => {
    const r = await act('ticket.new', { title: 'Made from the page (smoke)' });
    if (r.status !== 200) throw new Error(`ticket.new -> ${r.status} ${r.text}`);
    await page.goto(`${base}/#tickets`); await page.locator('a[href^="#ticket/"]', { hasText: 'Made from the page (smoke)' }).first().waitFor();
  });
}

await step('home', async () => {
  await page.goto(`${base}/#home`);
  await page.waitForTimeout(1500); // a plain wait: the page keeps a stream open, so it never reaches networkidle
  await page.getByRole('heading', { name: 'Today', exact: true }).first().waitFor();
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
// A hash change is same-document (networkidle returns at once) and an unknown page falls back to Home: wait for the
// page's own heading. General exists only once the phone sent texts that belong to no ticket.
const heading = name => page.getByRole('heading', { name, exact: true }).first().waitFor();
if (await page.locator('a[href="#general"]').count()) {
  await step('general', async () => { await page.goto(`${base}/#general`); await heading('General'); });
} else console.log('skip: general (no texts from the phone yet, so the page is not offered)');
await step('settings', async () => { await page.goto(`${base}/#settings`); await heading('Settings'); });
for (const width of [720, 390]) {
  await page.setViewportSize({ width, height: 800 });
  for (const [name, hash, title] of [['home', '#home', 'Today'], ['tickets', '#tickets', 'Tickets']]) {
    await step(`${name}-narrow`, async () => {
      await page.goto(`${base}/${hash}`);
      await heading(title);
      await fitsWidth();
    });
  }
}
await browser.close();
console.log(failed ? `smoke: ${failed} step(s) failed` : 'smoke: all steps ok'); // not "RESULT": that line is the flow's
process.exit(failed ? 1 : 0);
