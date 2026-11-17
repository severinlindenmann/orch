// Automation page: "Allow this script" on a waiting script row. The real button is clicked in Chromium on the real
// dashboard web files; every request is answered in memory. It must show "Checking…", ask the add-on first
// (review:true), open a confirm window with the command, and send the shown key back on Allow.
// usage: [PW_DIR=..] node --test e2e/dash_allow_script.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const WEB = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'src', 'orch_dashboard', 'web');
const FIX = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};
const KEY = 'b'.repeat(64);
const view = {schema: 'orch.addon-view/1', generated_at: '2026-11-17T00:00:00Z', blocks: [{type: 'table',
  columns: [{key: 'schedule', label: 'Ticket', type: 'text'}, {key: 'repeats', label: 'Repeats', type: 'text'}],
  rows: [{cells: {schedule: 'ORCH-114 · Role', repeats: 'Every 3 hours'}, link: 't_script001', subtitle: 'Runs dev-expert',
    toggle: {on: true, label: 'Role on or off', action: {op: 'addon.act', args: {verb: 'toggle', target: 't_script001'}}},
    actions: [{label: 'Allow this script', action: {op: 'addon.act', args: {verb: 'allow-script', target: 't_script001', review: true}}},
      {label: 'Edit', action: {op: 'addon.edit', args: {target: 't_script001'}}}]}]}]};

test('Allow this script: Checking…, confirm window with the command, Allow sends the shown key', {timeout: 120_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
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
        if (a.review) { await new Promise(r => setTimeout(r, 1200));   // the real check takes seconds
          return json({...state, act_answer: {addon: 'automation', answer: {target: 'automation:t_script001:' + KEY,
            review: {title: 'Allow this script on this computer?', value: 'python3 dev-expert.py --run', body: 'Each time the repeat is due, orch runs this command here.'}}}}); }
        return json(state);
      }
      if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
      if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
      const kit = url.pathname.startsWith('/kit/');
      const root = kit ? KIT : WEB;
      const rel = kit ? url.pathname.slice(5) : url.pathname === '/' ? 'index.html' : url.pathname;
      const file = path.join(root, path.normalize(rel).replace(/^[/\\]+/, ''));
      if (!file.startsWith(root) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
      return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
        headers: {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'"}, body: fs.readFileSync(file)});
    });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(String(e)));
    await page.goto(BASE + '/#addon/automation');
    const button = page.getByRole('button', {name: 'Allow this script'});
    await button.waitFor();
    await button.click();
    await page.getByRole('button', {name: 'Checking…'}).waitFor({timeout: 1000});
    const dialog = page.locator('dialog[open]');
    await dialog.waitFor({timeout: 6000});
    assert.match(await dialog.textContent(), /python3 dev-expert\.py --run/);
    assert.deepEqual(calls.at(-1).args, {addon: 'automation', verb: 'allow-script', target: 't_script001', review: true});
    await dialog.getByRole('button', {name: 'Allow', exact: true}).click({timeout: 6000});
    await page.waitForTimeout(500);
    assert.deepEqual(calls.at(-1).args, {addon: 'automation', verb: 'allow-script', target: 't_script001', value: KEY});
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
