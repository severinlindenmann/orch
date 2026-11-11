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
  // `last` as the server sends it (orch chat.days: the last message's whole text, clipped at 120); the page makes the preview line
  const days = [{day: '2026-11-11', count: day.messages.length, last: day.messages.at(-1).text.slice(0, 120)},
    {day: '2026-11-10', count: past.messages.length, last: past.messages.at(-1).text.slice(0, 120)},
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
      // Every ticket card: a plain title (no ids), its status chip, nothing under a closed Details. The title row of the
      // thread header is one row with Earlier on the right; the header is two rows at most. "Open helper" is a Menu item
      // only where the header has no room for its button.
      report[`chat-facts-${w}`] = await page.evaluate(() => {
        const visible = n => !!n && n.getClientRects().length > 0;
        const cards = [...document.querySelectorAll('.chat-log .chat-ticket')].map(card => ({
          title: card.querySelector('.chat-ticket-title').innerText.trim(), status: !!card.querySelector('.chat-status'),
          band: Math.round(card.getBoundingClientRect().bottom - card.querySelector('.chat-ticket-more > summary').getBoundingClientRect().bottom)}));
        const top = document.querySelector('.chat-head-top'), kids = [...top.children].filter(visible).map(k => k.getBoundingClientRect());
        const earlier = top.querySelector('[data-chat-action="history"]').getBoundingClientRect();
        const text = s => document.querySelector(s)?.innerText.trim();
        return {cards, title: text('.chat-page [data-key="chat-title"]'), rowTitle: text('.chat-list [data-key="row-chat"] .chat-row-text > strong'), titleRowOne: Math.max(...kids.map(r => r.top)) < Math.min(...kids.map(r => r.bottom)),
          earlierGap: Math.round(top.getBoundingClientRect().right - earlier.right),
          headRows: [...document.querySelector('.chat-thread-head').children].filter(visible).length,
          menuHelperShown: getComputedStyle(document.querySelector('#side-nav .nav-helper')).display !== 'none',
          topbarHelperShown: visible(document.getElementById('open-agent'))};
      });
      await page.click('.chat-thread-head [data-chat-action="history"]');
      await page.waitForSelector('[data-key="day-2026-11-10"]');
      await shot('chat-earlier');
      report[`text-earlier-${w}`] = await page.evaluate(() => document.querySelector('[data-key=history-list]').innerText.replace(/\s+/g, ' ').trim());
      report[`chat-earlier-${w}`].hasToday = await page.locator('[data-key="day-2026-11-11"]').count();
      report[`chat-earlier-${w}`].searchBoxes = await page.locator('.chat-page input[type=search]:visible').count();
      // previews end on content, not on a colon; a group is live (Groups) or finished (Earlier), never both
      Object.assign(report[`chat-earlier-${w}`], await page.evaluate(() => ({
        previews: [...document.querySelectorAll('.chat-day-row small, .chat-list-row small')].map(n => n.textContent.trim()),
        live: [...document.querySelectorAll('.chat-list [data-key^="row-g_"]')].map(n => n.dataset.id),
        finished: [...document.querySelectorAll('[data-key^="history-g_"]')].map(n => n.dataset.id)})));
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
      // Shared pages: the words and the switch on one row, switch right; a closed Details has nothing under its line
      Object.assign(report[`settings-${w}`], await page.evaluate(() => {
        const row = document.querySelector('[data-key="lk-shared-row"]').getBoundingClientRect();
        const words = document.querySelector('[data-key="lk-shared-row"] > .grow').getBoundingClientRect();
        const sw = document.querySelector('[data-key="lk-shared"]').getBoundingClientRect();
        const details = document.querySelector('[data-key="settings-copies-details"]');
        return {sharedOneRow: sw.top < words.bottom && words.top < sw.bottom && sw.left >= words.right, sharedSwitchGap: Math.round(row.right - sw.right),
          closedBand: Math.round(details.getBoundingClientRect().bottom - details.querySelector('summary').getBoundingClientRect().bottom)};
      }));
      await page.click('[data-key="settings-copies-details"] summary');
      await page.locator('[data-key="settings-copies-details"]').scrollIntoViewIfNeeded();
      await shot('settings-copies-details');
      // "When": the unselected choice is outlined like the hours choice; stacked = each choice full width
      report[`settings-${w}`].when = await page.evaluate(() => {
        const box = document.querySelector('.copies-choices'), buttons = [...box.querySelectorAll('.btn')].map(b => b.getBoundingClientRect());
        const ghost = box.querySelector('.btn.ghost'), hours = document.querySelector('.mm-hours .btn.ghost');
        const stacked = buttons[1].top >= buttons[0].bottom;
        return {stacked, fullWidth: !stacked || buttons.every(r => Math.abs(r.width - box.getBoundingClientRect().width) <= 1),
          sameOutline: getComputedStyle(ghost).borderTopColor === getComputedStyle(hours).borderTopColor && getComputedStyle(ghost).color === getComputedStyle(hours).color};
      });
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
        report['menu-390'] = {menuLabel: await page.textContent('#menu-toggle'), phoneSwitch: await page.textContent('#mm-toggle'),
          ...await page.evaluate(() => {
            // the switcher is one row: badge, name with its sub-label, chevron right
            const box = document.querySelector('.workspace.ws-switch'), parts = [...box.children].map(k => k.getBoundingClientRect());
            const helper = document.querySelector('#side-nav .nav-helper');
            return {switcherOneRow: Math.max(...parts.map(r => r.top)) < Math.min(...parts.map(r => r.bottom)),
              chevronRight: Math.round(box.getBoundingClientRect().right - parts.at(-1).right) <= 12,
              openHelper: helper && helper.getClientRects().length ? helper.textContent.trim() : ''};
          })};
        await page.click('#side-nav .nav-helper');
        await page.waitForSelector('.chat-page [data-key="chat-title"]');
        report['menu-390'].afterOpenHelper = {title: await page.textContent('.chat-page [data-key="chat-title"]'),
          menuOpen: await page.getAttribute('#menu-toggle', 'aria-expanded')};
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
    const chat = report[`chat-facts-${w}`], earlier = report[`chat-earlier-${w}`], settings = report[`settings-${w}`];
    assert.ok(chat.cards.length >= 8, `chat-${w}: the ticket cards are there`);
    for (const card of chat.cards) {
      assert.doesNotMatch(card.title, /\bmwb[a-z0-9]+\b|\[\d+\]|PIL-\d+/, `chat-${w}: no id in the card title "${card.title}"`);
      assert.equal(card.status, true, `chat-${w}: "${card.title}" has its status`);
      assert.ok(card.band <= 1, `chat-${w}: nothing under the closed Details of "${card.title}" (${card.band}px)`);
    }
    // owner: the Chat thread title and its row in the list are the workspace name; "helper" only in body text and labels
    assert.equal(chat.title, 'Pilatus', `chat-${w}: the thread title is the workspace name`);
    assert.equal(chat.rowTitle, 'Pilatus', `chat-${w}: the Chat row title is the workspace name`);
    assert.equal(chat.titleRowOne, true, `chat-${w}: the thread title row is one row`);
    assert.ok(chat.earlierGap <= 1, `chat-${w}: Earlier is right on the title row (${chat.earlierGap}px)`);
    assert.ok(chat.headRows <= 2, `chat-${w}: thread header rows ${chat.headRows}`);
    assert.equal(chat.menuHelperShown, w <= 720, `chat-${w}: Open helper is a Menu item only on a narrow screen`);
    assert.equal(chat.topbarHelperShown, w > 720, `chat-${w}: the header button is there when it fits`);
    assert.deepEqual(earlier.previews.filter(p => /:$/.test(p)), [], `chat-earlier-${w}: no preview ends on a colon`);
    assert.ok(earlier.finished.length >= 1 && earlier.live.length >= 1, `chat-earlier-${w}: live and finished groups`);
    assert.deepEqual(earlier.live.filter(id => earlier.finished.includes(id)), [], `chat-earlier-${w}: no group is live and finished`);
    assert.equal(settings.sharedOneRow, true, `settings-${w}: Shared pages words and switch on one row`);
    assert.ok(settings.sharedSwitchGap <= 24, `settings-${w}: the Shared pages switch is right (${settings.sharedSwitchGap}px)`);
    assert.ok(settings.closedBand <= 1, `settings-${w}: nothing under the closed Details (${settings.closedBand}px)`);
    assert.equal(settings.when.sameOutline, true, `settings-${w}: the unselected When choice is outlined like the hours`);
    assert.equal(settings.when.fullWidth, true, `settings-${w}: stacked When choices are full width`);
  }
  assert.equal(report['settings-390'].when.stacked, true, 'settings-390: the When choices stack');
  for (const w of [1280, 390]) {
    const r = report[`settings-review-${w}`];
    assert.equal(r.review.inPanel, true, `settings-review-${w}: the keyboard is in the review`);
    assert.deepEqual(r.review.buttons, ['Clean up', 'Cancel']);
    assert.match(r.review.text, /will be removed now\..*Your own files are not touched\./);
    assert.deepEqual(r.afterEscape, {open: false, at: 'settings-copies-clean'}, `settings-review-${w}: Escape closes it and goes back to the button`);
  }
  assert.match(report['menu-390'].menuLabel, /^Menu · \d+$/);
  assert.match(report['menu-390'].phoneSwitch, /Send questions to my phone/);
  assert.equal(report['menu-390'].switcherOneRow, true, 'menu-390: the workspace switcher is one row');
  assert.equal(report['menu-390'].chevronRight, true, 'menu-390: the chevron is on the right');
  assert.equal(report['menu-390'].openHelper, 'Open helper', 'menu-390: Open helper is in the Menu');
  assert.deepEqual(report['menu-390'].afterOpenHelper, {title: 'New conversation with your helper', menuOpen: 'false'});
});
