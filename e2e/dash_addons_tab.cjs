// Settings › Add-ons draws its rows, and "Report a problem" saves the page the person was looking at (ORCH-1117,
// report r-1120-2034-ws: the picture showed an empty Add-ons tab, the saved page the whole list).
// Chromium with the real dashboard web files and no server: /api/state comes from the screenshot fixture
// (workspace-addons/dashboard/tests/fixtures/state-chat-settings.json) with twelve add-ons, Contacts among them,
// and a new revision on every read, so the page redraws as it does at home.
// Flow, at 1366 and 390 px: open Settings, Add-ons tab, the heading and every row are on screen; About, then the
// browser's Back to Add-ons, the rows again. Then the report: open it, the page redraws behind the dialog, Create,
// and the saved page is the one from before the change, with the window size on its first line.
// usage: [PW_DIR=<node_modules holding playwright>] node --test e2e/dash_addons_tab.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};
const ADDONS = [['automation', 'Automation', true], ['dashboard-tester', 'Dashboard-tester', false], ['factory', 'Factory', true], ['focus', 'Focus', true],
  ['insights', 'Insights', true], ['lessons', 'Lessons', true], ['publish', 'Shared links', true], ['pull-requests', 'Pull requests', true],
  ['relay', 'Contacts', true], ['services', 'Services', true], ['sync', 'Sync', true], ['usage', 'Usage', true]];

function fixture() {
  const state = JSON.parse(fs.readFileSync(path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json'), 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  const dash = state.settings.addons.find(a => a.name === 'dashboard');
  state.settings.addons = [dash, ...ADDONS.map(([name, label, active]) => ({name, label, active, description: label + ' in one plain line.',
    ...(name === 'publish' || name === 'relay' ? {detail: {connected: true, address: 'https://' + name + '.example.org'}} : {})}))];
  state.addons = ADDONS.filter(a => a[2]).map(([name, label]) => ({name, dashboard: name === 'relay' ? {panel: 'phone', label} : name === 'automation' ? {panel: 'repeats', label} : {label}}));
  return state;
}

async function open(browser, width) {
  const context = await browser.newContext({viewport: {width, height: 869}, colorScheme: 'dark', timezoneId: 'UTC'});
  const state = fixture(), reports = [];
  let rev = 0;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== BASE) return route.abort();
    if (url.pathname === '/api/state') return json({...state, rev: 'r' + (++rev)});
    if (url.pathname === '/api/diag/report') { reports.push(route.request().postDataJSON()); return json({ref: 'r-1121-0000-ws', about: 'problem'}); }
    if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
    if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
    const rel = url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, '');
    const kit = rel.startsWith('kit' + path.sep);
    const file = kit ? path.join(KIT, rel.slice(4)) : path.join(WEB, rel);
    if (!file.startsWith(kit ? KIT : WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
    return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream', body: fs.readFileSync(file)});
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(BASE + '/#settings');
  await page.locator('#settings-tab-general').waitFor();
  return {context, page, state, reports, errors};
}

// Every row drawn: in the page, not hidden, with a size and its name readable at its own spot on screen.
async function rowsOnScreen(page) {
  const panel = page.locator('#settings-panel-addons');
  await panel.getByRole('heading', {name: 'Installed add-ons'}).waitFor();
  const rows = panel.locator('.ad-row');
  assert.equal(await rows.count(), ADDONS.length);
  for (const [, label] of ADDONS) {
    const row = panel.locator('.ad-row', {has: page.getByRole('heading', {name: label, exact: true})});
    await row.evaluate(el => el.scrollIntoView({block: 'center'}));  // the middle: the phone's bottom bar is fixed over the lowest lines
    const box = await row.boundingBox();
    assert.ok(box && box.height > 20 && box.width > 200, label + ': the row has a size');
    // the element on screen at the row's own spot is the row (or inside it); else name what covers it
    const hit = await row.evaluate(el => { const b = el.getBoundingClientRect(), top = document.elementFromPoint(b.left + 24, b.top + b.height / 2);
      return top && el.contains(top) ? true : top ? top.outerHTML.slice(0, 120) : 'nothing drawn'; });
    assert.equal(hit, true, label + ': nothing covers the row');
  }
}

test('Settings › Add-ons shows its rows; the report saves the page as it was when opened', {timeout: 180_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  const browser = await headless.launch(chromium);
  try {
    for (const width of [1366, 390]) {
      const {context, page, state, reports, errors} = await open(browser, width);
      await page.locator('#settings-tab-addons').click();
      await rowsOnScreen(page);
      await page.waitForTimeout(2500);  // at least one redraw from a new revision
      await rowsOnScreen(page);
      await page.locator('#settings-tab-about').click();
      await page.locator('#settings-panel-about').waitFor();
      await page.goBack();  // the person's way back in the report: no tab click
      assert.match(page.url(), /#settings\/addons$/);
      await rowsOnScreen(page);
      if (width === 1366) {
        await page.locator('#report-problem').click();
        const dialog = page.locator('dialog.report-dialog');
        await dialog.waitFor();
        // the page redraws behind the open dialog with a renamed add-on; the report must keep what the person saw
        state.settings.addons.find(a => a.name === 'usage').label = 'Usage renamed later';
        await page.locator('#settings-panel-addons').getByRole('heading', {name: 'Usage renamed later'}).waitFor({state: 'attached'});
        await dialog.getByRole('button', {name: 'Create report'}).click();
        await page.locator('[data-key="report-saved"]').waitFor();
        assert.equal(reports.length, 1);
        const saved = reports[0].page;
        assert.match(saved.split('\n')[1], /^<!-- orch: the page when Report a problem was opened, .*; window 1366x869 px, scrolled \d+,\d+, zoom \d+% -->$/);
        assert.ok(saved.includes('>Usage<') && !saved.includes('Usage renamed later'), 'the saved page is the one from when the dialog opened');
        assert.ok(!saved.includes('report-dialog'), 'the dialog itself is not in it');
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
  }
});
