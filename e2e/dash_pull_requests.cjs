// The pull-requests add-on's Pull requests page and a ticket's live pull request state, in the real dashboard web files.
// Chromium (own browser, mock keychain), every request answered in memory from e2e/fixtures/pull-requests-page.json
// (made by the add-on's own code: workspace-addons/pull-requests/tests/dash_fixture.py). Screenshots at 1280, 1920, 390, 320.
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_pull_requests.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

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
  const browser = await chromium.launch({args: ['--use-mock-keychain', '--password-store=basic']});
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
      for (const word of ['Failed: lint', 'Ready to merge', 'Has a conflict', 'Running (2 left)', 'Draft', 'acme/website'])
        assert.ok(await page.getByText(word).first().count(), word);
      await page.screenshot({path: path.join(OUT, `pull-requests-${size[0]}.png`), fullPage: true});
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

test('Ticket page: the pull request link and Details show the live state', {timeout: 120_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  for (const size of [SIZES[0], SIZES[2]]) {
    await withPage(chromium, size, 'loaded', async page => {
      await page.goto(BASE + '/#ticket/' + GH.ticket.id);
      await page.getByRole('heading', {name: 'Invoice CSV export'}).first().waitFor();
      await page.getByText('Checks failed', {exact: true}).first().waitFor();   // the link's live state
      const fields = page.locator('.addon-fields');
      for (const word of ['#418', 'Failed', 'Blocked']) await fields.getByText(word, {exact: true}).waitFor();
      await page.screenshot({path: path.join(OUT, `ticket-${size[0]}.png`), fullPage: true});
    });
  }
});
