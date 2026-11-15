// A settings-only add-on page (place = "settings", the Lessons view): no nav entry, opened from Settings › Add-ons,
// Edit opens the addon.prompt dialog, Save sends the add-on's verb with the new text, Delete is one click.
// Real dashboard web files in Chromium (own browser, mock keychain), every request answered in memory; the view is
// the contract example. usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_lessons.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-lessons');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const VIEW = path.join(__dirname, '..', 'contracts', 'examples', 'addon-view', 'valid-lessons-page.json');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

test('Lessons: no nav entry, row in Settings, list page, Edit dialog, Delete', {timeout: 120_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const view = JSON.parse(fs.readFileSync(VIEW, 'utf8'));
  const state = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  const dash = {label: 'Lessons', icon: 'book', order: 50, place: 'settings', title: 'Lessons', subtitle: 'What your helpers learned.'};
  state.addons.push({name: 'lessons', dashboard: dash});
  state.settings.addons.push({name: 'lessons', label: 'Lessons', description: 'Keeps short notes the next helper should know.', active: true});
  const calls = [];
  let refuse = true;
  const browser = await chromium.launch({args: ['--use-mock-keychain', '--password-store=basic']});
  try {
    const context = await browser.newContext({viewport: {width: 1280, height: 800}});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== BASE) return route.abort();
      if (url.pathname === '/api/state') return json(state);
      if (url.pathname === '/api/addon/lessons') return json({state: 'ok', view});
      if (url.pathname === '/api/act') {
        const body = route.request().postDataJSON(); calls.push(body);
        const a = body.args || {};
        if (a.addon === 'lessons' && a.verb === 'edit' && refuse) { refuse = false; return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({error: 'Write between 1 and 200 characters.'})}); }
        if (a.addon === 'lessons' && a.verb === 'rm') view.blocks[0].items = view.blocks[0].items.filter(i => !JSON.stringify(i).includes(a.target));
        return json(state);
      }
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
    await page.goto(BASE + '/#settings/addons');
    await page.getByRole('link', {name: 'Lessons settings'}).waitFor();
    assert.equal(await page.locator('#side-nav a, #side-addons a').filter({hasText: 'Lessons'}).count(), 0, 'no nav entry');
    await page.screenshot({path: path.join(OUT, 'lessons-settings-addons.png')});
    await page.getByRole('link', {name: 'Lessons settings'}).click();
    await page.getByRole('link', {name: /^Open Lessons/}).click();
    await page.getByText('Run the web tests with npm run test:web').first().waitFor();
    assert.equal(await page.locator('#side-nav a, #side-addons a').filter({hasText: 'Lessons'}).count(), 0, 'still no nav entry');
    await page.screenshot({path: path.join(OUT, 'lessons-page.png')});
    await page.locator('.acc summary').first().click();   // a row opens with one click: Edit and Delete sit inside
    await page.screenshot({path: path.join(OUT, 'lessons-page-open.png')});
    await page.getByRole('button', {name: 'Edit'}).first().click();
    const dlg = page.locator('dialog[open]');
    await dlg.waitFor();
    const input = dlg.locator('input');
    assert.match(await input.inputValue(), /^Run the web tests/);
    await input.fill('');
    assert.equal(await dlg.getByRole('button', {name: 'Save'}).isDisabled(), true);
    await input.fill('x'.repeat(201));
    assert.equal(await dlg.getByRole('button', {name: 'Save'}).isDisabled(), true);
    await input.fill('Run the web tests with npm run test:web.');
    await page.waitForTimeout(250);
    await page.screenshot({path: path.join(OUT, 'lessons-edit-dialog.png')});
    await dlg.getByRole('button', {name: 'Save'}).click();
    await dlg.getByText('Write between 1 and 200 characters.').waitFor();   // the add-on's refusal stays in the dialog
    await dlg.getByRole('button', {name: 'Save'}).click();
    await page.locator('dialog[open]').waitFor({state: 'detached'});
    assert.deepEqual(calls.filter(c => c.args.verb === 'edit').at(-1), {op: 'addon.act', args: {addon: 'lessons', verb: 'edit', target: 'l_k2m9q4', value: 'Run the web tests with npm run test:web.'}});
    if (!(await page.getByRole('button', {name: 'Delete'}).first().isVisible())) await page.locator('.acc summary').first().click();
    await page.getByRole('button', {name: 'Delete'}).first().click();
    await page.waitForFunction(() => document.querySelectorAll('[data-addon-prompt]').length === 1);
    assert.deepEqual(calls.at(-1).args, {addon: 'lessons', verb: 'rm', target: 'l_k2m9q4'});
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
