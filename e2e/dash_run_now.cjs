// Automation page: a schedule made here has "Run now"; a schedule that came by sync has "Allow on this computer",
// which opens the sign step of sync's Allow for that ticket. Real dashboard web files in Chromium (own browser, mock
// keychain), every request answered in memory. usage: VIEW=<view.json> [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_run_now.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-run-now');
const WEB = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'src', 'orch_dashboard', 'web');
const FIX = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'tests', 'fixtures', 'state-chat-settings.json');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

test('Run now for own schedule, Allow on this computer for a synced one', {timeout: 120_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const view = JSON.parse(fs.readFileSync(process.env.VIEW, 'utf8'));
  const state = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  state.settings.addons.find(a => a.name === 'automation').dashboard = {};
  const calls = [];
  const browser = await chromium.launch({args: ['--use-mock-keychain', '--password-store=basic']});
  try {
    const context = await browser.newContext({viewport: {width: 1280, height: 800}});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== BASE) return route.abort();
      if (url.pathname === '/api/state') return json(state);
      if (url.pathname === '/api/addon/automation') return json({state: 'ok', view});
      if (url.pathname === '/api/act') {
        const body = route.request().postDataJSON(); calls.push(body);
        const a = body.args || {};
        if (a.addon === 'sync' && a.review) return json({...state, act_answer: {addon: 'sync', answer: {target: 'sync:allow:t_sync0001:automation:' + 'a'.repeat(64),
          review: {title: 'Allow automation to use this change on t_sync0001?', body: 'The change from the other computer is used here.', value: '{"cron":"0 8 * * 1","recurring":true} (40 bytes)'}}}});
        return json(state);
      }
      if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
      if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
      const file = path.join(WEB, url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, ''));
      if (!file.startsWith(WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
        headers: {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'"}, body: fs.readFileSync(file)});
    });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(String(e)));
    await page.goto(BASE + '/#addon/automation');
    await page.getByRole('button', {name: 'Run now'}).waitFor();
    await page.getByRole('button', {name: 'Allow on this computer'}).waitFor();
    await page.screenshot({path: path.join(OUT, 'automation-rows.png')});
    await page.getByRole('button', {name: 'Run now'}).click();
    assert.deepEqual(calls.at(-1), {op: 'addon.act', args: {addon: 'automation', verb: 'run', target: 't_made0001'}});
    await page.getByRole('button', {name: 'Allow on this computer'}).click();
    const dialog = page.locator('dialog.sign-step');
    await dialog.waitFor();
    await page.waitForTimeout(300);
    assert.deepEqual(calls.at(-1).args, {addon: 'sync', verb: 'allow', target: 't_sync0001:automation', review: true});
    assert.match(await dialog.textContent(), /Allow automation to use this change.*The change from the other computer is used here\..*You sign this as/);
    await page.screenshot({path: path.join(OUT, 'allow-sign-step.png')});
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
