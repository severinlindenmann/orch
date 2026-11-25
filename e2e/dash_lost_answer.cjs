// ORCH-580: New ticket whose answer is lost on the way (ERR_CONTENT_LENGTH_MISMATCH over the remote address). Real
// dashboard web files in Chromium (own browser, mock keychain), every request answered in memory: the server makes
// the ticket, the browser loses the answer. The page asks whether it went through and ends on the made ticket; when
// it did not go through, it says so and the next press sends the same click id (never a second ticket).
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_lost_answer.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-lost-answer');
const WEB = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'src', 'orch_dashboard', 'web');
const FIX = path.join(__dirname, '..', 'workspace-addons', 'dashboard', 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

async function run(width, arrives) {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const state = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  const made = new Map();  // click id -> ticket id: what the server did
  const posts = [];
  const browser = await headless.launch(chromium);
  try {
    const context = await browser.newContext({viewport: {width, height: 800}});
    await context.route('**/*', async route => {
      const req = route.request();
      const url = new URL(req.url());
      // X-Orch-Boot: the run of the dashboard (the page tells "not done" from "forgotten after a restart" by it)
      const json = body => route.fulfill({status: 200, contentType: 'application/json', headers: {'X-Orch-Boot': 'e2eboot01'}, body: JSON.stringify(body)});
      if (url.origin !== BASE) return route.abort();
      if (url.pathname === '/api/state') return json(state);
      if (url.pathname === '/api/act/status') {
        const tid = made.get(url.searchParams.get('id'));
        return json(tid ? {state: 'done', op: 'ticket.new', status: 200, reply: {created: {id: tid}}, boot: 'e2eboot01'} : {state: 'unknown', boot: 'e2eboot01'});
      }
      if (url.pathname === '/api/act') {
        const body = req.postDataJSON();
        const id = req.headers()['x-orch-act-id'];
        posts.push({op: body.op, id});
        if (body.op !== 'ticket.new') return json(state);
        if (!arrives && posts.filter(p => p.op === 'ticket.new').length === 1) return route.abort('failed');  // never got there
        if (!made.has(id)) {  // the server runs an id once
          const tid = 't_lost' + String(made.size + 1).padStart(3, '0');
          made.set(id, tid);
          state.tickets = [{...state.tickets[0], id: tid, key: 'ORCH-' + (600 + made.size), title: body.args.title, status: 'open', checklist: [], questions: []}, ...state.tickets];
        }
        if (posts.filter(p => p.op === 'ticket.new').length === 1) return route.abort('failed');  // the answer is lost on the way
        return json({...state, created: {id: made.get(id)}});
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
    await page.goto(BASE + '/#home');
    await page.locator('#content').waitFor();
    await page.waitForTimeout(300);
    await page.keyboard.press('n');  // New ticket on every width (the top-bar button is hidden on a phone)
    const dialog = page.locator('.new-ticket');  // ORCH-1037: the New ticket page (#new), no longer a window
    await dialog.waitFor();
    await dialog.getByRole('textbox', {name: 'What needs doing?'}).fill('Check the invoice export');
    await dialog.getByRole('button', {name: 'Save ticket'}).click();
    return {page, dialog, posts, made, errors, browser};
  } catch (e) { await browser.close(); throw e; }
}

for (const width of [1280, 390]) {
  test(`made, answer lost: the page ends on the made ticket, one ticket (${width})`, {timeout: 120_000}, async () => {
    const {page, posts, made, errors, browser} = await run(width, true);
    try {
      await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, {timeout: 20_000});
      assert.equal(await page.evaluate(() => decodeURIComponent(location.hash)), '#ticket/t_lost001');
      assert.equal(made.size, 1);
      assert.equal(posts.filter(p => p.op === 'ticket.new').length, 1, 'not sent again by itself');
      await page.locator('.new-ticket').waitFor({state: 'detached'});
      await page.screenshot({path: path.join(OUT, `made-${width}.png`)});
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  });

  test(`not arrived: a plain message, and the next press makes exactly one ticket (${width})`, {timeout: 120_000}, async () => {
    const {page, dialog, posts, made, errors, browser} = await run(width, false);
    try {
      await dialog.getByText('it was not done. Nothing was saved, try again.', {exact: false}).waitFor({timeout: 20_000});
      await page.screenshot({path: path.join(OUT, `not-done-${width}.png`)});
      assert.equal(made.size, 0);
      await dialog.getByRole('button', {name: 'Save ticket'}).click();
      await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, {timeout: 20_000});
      const sent = posts.filter(p => p.op === 'ticket.new');
      assert.equal(sent.length, 2);
      assert.equal(sent[0].id, sent[1].id, 'the retry carries the same click id');
      assert.equal(made.size, 1);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  });
}
