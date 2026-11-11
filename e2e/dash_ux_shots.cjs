// Dashboard UX shots (owner pass 11 Nov): renders the real dashboard web files with the screenshot fixtures
// (workspace-addons/dashboard/tests/fixtures/state-chat-settings.json + chat-day-pilatus-2026-11-11.json) in
// Chromium, no server: every request is answered from the files. Chat (Today, Earlier, one past day) and Settings
// at 1280, 720 and 390 px; checks no horizontal scroll, nothing cut off at the right edge, one header row on a
// narrow screen and the 4 h / 8 h / 12 h / 24 h choice on one line. Settings at 1280 and 390 px also shows one review
// step open (Clean up now) and checks the keyboard moves into it and Escape closes it.
// usage: [PW_DIR=<node_modules holding playwright>] [SHOTS_DIR=<folder>] node --test e2e/dash_ux_shots.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-ux-shots');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures');
const BASE = 'http://dash.test';
const CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'";
const OPTIONAL = new Set(['/api/notices', '/api/handoffs', '/api/update-status']);
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

function fixtures() {
  const state = JSON.parse(fs.readFileSync(path.join(FIX, 'state-chat-settings.json'), 'utf8'));
  const day = JSON.parse(fs.readFileSync(path.join(FIX, 'chat-day-pilatus-2026-11-11.json'), 'utf8'));
  const activity = state.chat_activity;
  delete state._note; delete state.chat_activity;
  const past = {schema: day.schema, day: '2026-11-10', messages: day.messages.slice(0, 2).map(m => ({...m, day: '2026-11-10', at: m.at.replace('2026-11-11', '2026-11-10')}))};
  const days = [{day: '2026-11-11', count: day.messages.length, last: day.messages.at(-1).text},
    {day: '2026-11-10', count: past.messages.length, last: past.messages.at(-1).text.split('\n')[0]},
    {day: '2026-11-09', count: 2, last: 'Thanks, all set for Monday.'}];
  state.chat = {helper: 'pilatus helper', day: day.day, messages: day.messages, activity, days, running: false, human_pending_ids: []};
  return {state, days, past};
}

async function serve(context, data) {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== BASE) return route.abort();
    if (url.pathname === '/api/state') return json(data.state);
    if (url.pathname === '/api/chat/days') return json(data.days);
    if (url.pathname === '/api/chat/day/2026-11-10') return json(data.past);
    if (url.pathname === '/api/chat/contacts') return json([]);
    if (url.pathname === '/api/act') return json(data.state);  // the page only syncs here; nothing changes
    if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
    if (OPTIONAL.has(url.pathname)) return route.fulfill({status: 404, body: ''});  // other features, not on these pages
    if (url.pathname.startsWith('/api/')) return route.fulfill({status: 400, body: 'Not in the screenshot fixture.'});
    const file = path.join(WEB, url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, ''));
    if (!file.startsWith(WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
    return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
      headers: {'Content-Security-Policy': CSP}, body: fs.readFileSync(file)});
  });
}

// What a person would notice: a sideways scroll, something cut off at the right edge, a header in two rows.
function layoutFacts() {
  const vw = document.documentElement.clientWidth;
  const inScroller = el => { for (let p = el.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p); if (['auto', 'scroll', 'hidden'].includes(s.overflowX) && p.scrollWidth > p.clientWidth + 1 && s.overflowX !== 'hidden') return true; } return false; };
  const cut = [...document.querySelectorAll('body *')].filter(el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && r.right > vw + 1 && !inScroller(el) && !el.closest('dialog:not([open])');
  }).slice(0, 8).map(el => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').join('.') : '') + ' ' + Math.round(el.getBoundingClientRect().right));
  // one row = no header item starts below the bottom of another
  const bar = document.querySelector('.topbar'), kids = [...bar.children].filter(k => k.getBoundingClientRect().width > 0).map(k => k.getBoundingClientRect());
  const lowest = Math.min(...kids.map(r => r.bottom));
  return {scrollX: document.documentElement.scrollWidth > window.innerWidth, cut,
    headerRows: kids.some(r => r.top >= lowest) ? 2 : 1, headerHeight: Math.round(bar.getBoundingClientRect().height)};
}

test('dashboard UX shots: Chat (Today, Earlier, a past day) and Settings at 1280, 720 and 390 px', {timeout: 180000}, async t => {
  let chromium;
  try { ({chromium} = require(path.join(PW, 'playwright'))); } catch (e) { t.skip('playwright not found at ' + PW + ' (set PW_DIR)'); return; }
  fs.mkdirSync(OUT, {recursive: true});
  const data = fixtures(), report = {}, browser = await chromium.launch();
  try {
    for (const [w, h] of [[1280, 800], [720, 900], [390, 844]]) {
      const context = await browser.newContext({viewport: {width: w, height: h}, deviceScaleFactor: 1});
      await serve(context, data);
      const page = await context.newPage(), errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('console', m => { if (m.type() === 'error' && !/^Failed to load resource/.test(m.text())) errors.push(m.text()); });
      page.on('response', r => { const p = new URL(r.url()).pathname; if (r.status() >= 400 && !OPTIONAL.has(p)) errors.push(r.status() + ' ' + p); });
      const shot = async (name, check = true, full = false) => {
        await page.waitForTimeout(250);
        await page.screenshot({path: path.join(OUT, `${name}-${w}.png`), fullPage: full});
        if (check) report[`${name}-${w}`] = await page.evaluate(layoutFacts);
      };
      await page.goto(BASE + '/#chat');
      await page.waitForSelector('.chat-page .chat-log');
      await shot('chat-today');
      // the helper's long answer with its ticket cards
      await page.locator('[data-message-id="m_6l6w8wqwpgvrlsvr"]').scrollIntoViewIfNeeded();
      await shot('chat-today-cards', false);
      report[`text-chat-${w}`] = await page.evaluate(() => {
        const t = s => [...document.querySelectorAll(s)].filter(n => n.getClientRects().length).map(n => n.innerText.replace(/\s+/g, ' ').trim());
        return {topbar: t('.topbar'), head: t('.chat-thread-head'), list: t('.chat-list-row'), cards: t('.chat-ticket').slice(0, 4), times: t('.chat-message-time').slice(0, 3)};
      });
      await page.click('.chat-thread-head [data-chat-action="history"]');
      await page.waitForSelector('[data-key="day-2026-11-10"]');
      await shot('chat-earlier');
      report[`text-earlier-${w}`] = await page.evaluate(() => document.querySelector('[data-key=history-list]').innerText.replace(/\s+/g, ' ').trim());
      report[`chat-earlier-${w}`].hasToday = await page.locator('[data-key="day-2026-11-11"]').count();
      report[`chat-earlier-${w}`].searchBoxes = await page.locator('.chat-page input[type=search]:visible').count();
      await page.click('[data-key="day-2026-11-10"]');
      await page.waitForSelector('.chat-archive-banner');
      await shot('chat-day');
      report[`chat-day-${w}`].banner = await page.textContent('.chat-archive-banner');
      await page.goto(BASE + '/#settings');
      await page.waitForSelector('[data-key="settings-copies"]');
      await shot('settings', true, true);
      const hours = await page.$$eval('[data-testid^="mobile-mode-hours-"]', n => n.map(b => Math.round(b.getBoundingClientRect().top)));
      report[`settings-${w}`].hoursOneLine = hours.length === 4 && new Set(hours).size === 1;
      report[`text-settings-${w}`] = await page.evaluate(() => [...document.querySelectorAll('[data-key=settings-copies],[data-key=settings-workspace],[data-key=settings-workflow],[data-key=settings-mobile-mode],.settings-nav')]
        .map(n => n.innerText.replace(/\s+/g, ' ').trim()));
      await page.click('[data-key="settings-copies-details"] summary');
      await page.locator('[data-key="settings-copies-details"]').scrollIntoViewIfNeeded();
      await shot('settings-copies-details');
      if (w !== 720) {
        // the review step before a change: shown in place with [Clean up] [Cancel], the keyboard in it, Escape closes it
        await page.click('[data-key="settings-copies-clean"]');
        await page.waitForSelector('[data-key="settings-review-copies-clean"]');
        await page.locator('[data-key="settings-review-copies-clean"]').scrollIntoViewIfNeeded();
        await shot('settings-review');
        report[`settings-review-${w}`].review = await page.evaluate(() => {
          const p = document.querySelector('.settings-review');
          return {inPanel: document.activeElement === p, text: p.innerText.replace(/\s+/g, ' ').trim(), buttons: [...p.querySelectorAll('button')].map(b => b.textContent)};
        });
        await page.keyboard.press('Escape');
        report[`settings-review-${w}`].afterEscape = await page.evaluate(() => ({open: !!document.querySelector('.settings-review'), at: document.activeElement?.dataset?.key || ''}));
      }
      if (w === 390) {
        await page.click('#menu-toggle');
        await page.waitForSelector('#mm-toggle:visible');
        await shot('menu-open', false);
        report['menu-390'] = {menuLabel: await page.textContent('#menu-toggle'), phoneSwitch: await page.textContent('#mm-toggle')};
      }
      report[`errors-${w}`] = errors;
      await context.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  for (const [name, facts] of Object.entries(report)) {
    if (name.startsWith('errors-')) { assert.deepEqual(facts, [], name); continue; }
    if (name.startsWith('text-') || !('scrollX' in facts)) continue;
    assert.equal(facts.scrollX, false, name + ': no sideways scroll');
    assert.deepEqual(facts.cut, [], name + ': nothing cut off at the right edge');
    assert.equal(facts.headerRows, 1, name + ': one header row');
    assert.ok(facts.headerHeight <= 64, name + ': header height ' + facts.headerHeight);
  }
  for (const w of [1280, 720, 390]) {
    assert.equal(report[`settings-${w}`].hoursOneLine, true, `settings-${w}: the hours choice is on one line`);
    assert.equal(report[`chat-earlier-${w}`].hasToday, 0, 'today is not repeated in Earlier');
    assert.equal(report[`chat-earlier-${w}`].searchBoxes, 1, 'one search box');
    assert.match(report[`chat-day-${w}`].banner, /you can read, not reply.*Back to today/);
  }
  for (const w of [1280, 390]) {
    const r = report[`settings-review-${w}`];
    assert.equal(r.review.inPanel, true, `settings-review-${w}: the keyboard is in the review`);
    assert.deepEqual(r.review.buttons, ['Clean up', 'Cancel']);
    assert.match(r.review.text, /will be removed now\..*Your own files are not touched\./);
    assert.deepEqual(r.afterEscape, {open: false, at: 'settings-copies-clean'}, `settings-review-${w}: Escape closes it and goes back to the button`);
  }
  assert.match(report['menu-390'].menuLabel, /^Menu · \d+$/);
  assert.match(report['menu-390'].phoneSwitch, /Send questions to my phone/);
});
