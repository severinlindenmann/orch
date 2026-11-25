// The pull-requests add-on's Pull requests page and a ticket's live pull request state, in the real dashboard web files.
// Chromium (own browser, mock keychain), every request answered in memory from e2e/fixtures/pull-requests-page.json
// (made by the add-on's own code: workspace-addons/pull-requests/tests/dash_fixture.py). Screenshots at 1280, 1920, 390, 320.
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_pull_requests.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-pull-requests');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const GH = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'pull-requests-page.json'), 'utf8'));
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};
const SIZES = [[1280, 800], [1920, 1080], [390, 844], [320, 640]];

function state() {
  const s = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete s._note; delete s.chat_activity; delete s.act_answer;
  s.addons.push(GH.addon);
  s.tickets.push(GH.ticket);
  return s;
}

async function withPage(chromium, size, viewName, fn) {
  const s = state();
  const browser = await headless.launch(chromium);
  try {
    const context = await browser.newContext({viewport: {width: size[0], height: size[1]}});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== BASE) return route.abort();
      if (url.pathname === '/api/state') return json(s);
      if (url.pathname === '/api/addon/pull-requests') return json({state: 'ok', view: GH.views[viewName]});
      if (url.pathname === '/api/act') return json(s);
      if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
      if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
      const rel = url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, '');
      const kit = rel.startsWith('kit' + path.sep);
      const file = kit ? path.join(KIT, rel.slice(4)) : path.join(WEB, rel);
      if (!file.startsWith(kit ? KIT : WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
        headers: {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'"}, body: fs.readFileSync(file)});
    });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(String(e)));
    await fn(page);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    assert.equal(wide, false, `no sideways scroll at ${size[0]}`);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
}

test('Pull requests page: nav entry, open pull requests with ticket, checks and merge state', {timeout: 240_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  for (const size of SIZES) {
    await withPage(chromium, size, 'loaded', async page => {
      await page.goto(BASE + '/#addon/pull-requests');
      await page.getByText('Add CSV export for invoices').first().waitFor();
      await page.getByRole('heading', {name: 'Pull requests', level: 1}).waitFor();
      for (const word of ['Checks failed', 'Draft', 'Open pull requests', 'Merge queue: acme/billing', 'Group of 2',
                         'checks running 12 min', 'Being checked', 'In line', 'Merged lately', '1st in line, paused',
                         'tries again by itself in 6 min', '29 min', 'groups of up to 5', 'Opened and merged per day',
                         'How the merge queue went'])
        assert.ok(await page.getByText(word).first().count(), word);
      // the merge queue first, each pull request a chip that opens it on GitHub (ORCH-746, draft B)
      const first = page.locator('.addon-page .blk, main .blk').first();
      assert.ok(await first.locator('.flow-stage').count(), 'the page starts with the merge queue');
      const chip = page.locator('a.flow-chip', {hasText: '#421'}).first();
      assert.equal(await chip.getAttribute('href'), 'https://github.com/acme/billing/pull/421');
      assert.equal(await chip.getAttribute('target'), '_blank');
      // the PR number in the table opens GitHub; the ticket key opens the ticket
      const num = page.locator('.blk-table a.cell-link', {hasText: '#418'}).first();
      assert.equal(await num.getAttribute('href'), 'https://github.com/acme/billing/pull/418');
      assert.match(await page.locator('.blk-table a.cell-ref').first().getAttribute('href'), /^#ticket\/t_/);
      if (size[0] >= 1280) {   // a chart column says its numbers on hover
        await page.locator('.blk-chart .chart-col').last().hover();
        await page.locator('.blk-chart .chart-tip:not([hidden])').first().waitFor();
        await page.screenshot({path: path.join(OUT, `pull-requests-${size[0]}.png`), fullPage: true});
        await page.mouse.move(0, 0);
      } else await page.screenshot({path: path.join(OUT, `pull-requests-${size[0]}.png`), fullPage: true});
      // a tab shows only its rows
      await page.getByRole('tab', {name: /^Checks failed/}).click();
      const shown = await page.locator('.blk-table tbody tr:not([hidden])').count();
      assert.equal(shown, 1, 'one pull request with failed checks');
      await page.getByRole('tab', {name: /^All/}).click();
    });
  }
  for (const name of ['empty', 'stopped']) {
    await withPage(chromium, SIZES[0], name, async page => {
      await page.goto(BASE + '/#addon/pull-requests');
      await page.getByRole('heading', {name: 'Pull requests', level: 1}).waitFor();
      await page.getByText(name === 'empty' ? 'No pull requests yet' : 'not being read right now').first().waitFor();
      if (name === 'stopped') assert.ok(await page.getByRole('button', {name: 'Start reading'}).count());
      await page.screenshot({path: path.join(OUT, `pull-requests-${name}-1280.png`), fullPage: true});
    });
  }
});

// ORCH-1859: the same failed pull request with only the run read changed: no helper running, one running, not known
test('Pull requests page: a failed check says whether a helper runs on its ticket, the rest stays put', {timeout: 180_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  const words = {loaded: 'No helper running on BIL-1. Open the ticket to fix it.',
                 helper_live: 'A helper is running on BIL-1, maybe not on this check.',
                 helper_unknown: 'Helper status on BIL-1 could not be checked; tries again by itself.'};
  const seen = {};
  for (const [name, text] of Object.entries(words)) {
    await withPage(chromium, SIZES[0], name, async page => {
      await page.goto(BASE + '/#addon/pull-requests');
      const row = page.locator('.blk-table tbody tr', {hasText: '#418'}).first();
      await row.waitFor();
      assert.ok(await row.getByText(text).count(), `${name}: ${text}`);
      for (const other of Object.values(words).filter(w => w !== text)) assert.equal(await row.getByText(other).count(), 0);
      assert.equal(await row.locator('a.cell-ref').getAttribute('href'), '#ticket/t_inv012');
      assert.equal(await row.locator('a.cell-link', {hasText: '#418'}).getAttribute('href'), 'https://github.com/acme/billing/pull/418');
      const order = await page.locator('.blk-table tbody tr td:first-child').allInnerTexts();
      const tabs = await page.getByRole('tab').allInnerTexts();
      // keyboard: the Checks failed tab is reached and chosen with the keyboard, and keeps the row
      const tab = page.getByRole('tab', {name: /^Checks failed/});
      await tab.focus(); await page.keyboard.press('Enter');
      assert.equal(await page.locator('.blk-table tbody tr:not([hidden])').count(), 1);
      assert.ok(await page.locator('.blk-table tbody tr:not([hidden])').getByText(text).count());
      seen[name] = JSON.stringify([order, tabs]);
    });
  }
  assert.equal(seen.helper_live, seen.loaded, 'same rows, order and tabs');
  assert.equal(seen.helper_unknown, seen.loaded, 'same rows, order and tabs');
});

test('Ticket page: the pull request link and Details show the live state', {timeout: 120_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  for (const size of [SIZES[0], SIZES[2]]) {
    await withPage(chromium, size, 'loaded', async page => {
      await page.goto(BASE + '/#ticket/' + GH.ticket.id);
      await page.getByText('Invoice CSV export').first().waitFor();
      await page.getByText('Checks failed', {exact: true}).first().waitFor();   // the link's live state
      const fields = page.locator('.addon-fields');
      for (const word of ['#418', 'Failed', 'Blocked']) await fields.getByText(word, {exact: true}).waitFor();
      await page.screenshot({path: path.join(OUT, `ticket-${size[0]}.png`), fullPage: true});
    });
  }
});
