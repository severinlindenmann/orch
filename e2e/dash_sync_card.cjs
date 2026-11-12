// Sync card (Settings › General) and the sync rows on Home › Needs you, in Chromium with the real dashboard web files
// (mockup: draft sync-card.html, Variant A). No server: every request is answered from the screenshot fixture
// (workspace-addons/dashboard/tests/fixtures/state-chat-settings.json), and /api/act plays the sync add-on's answers
// (`orch sync act status|set|now|check|use-public -- <target>`) from a small in-memory state.
// Flow: open Settings, see the card, pick "On this computer only", the review line, Save, the status line. Then
// screenshots of the card (synced, paused + public warning, add-on off), the Needs rows and the sign step at 1440 and
// 390 px, with no sideways scroll.
// usage: [PW_DIR=<node_modules holding playwright>] [SHOTS_DIR=<folder>] node --test e2e/dash_sync_card.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-sync-card');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures');
const BASE = 'http://dash.test';
const CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'";
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

function fixture() {
  const state = JSON.parse(fs.readFileSync(path.join(FIX, 'state-chat-settings.json'), 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  return state;
}

// The sync add-on as the dashboard sees it: one in-memory status, changed only by the person's clicks.
function fakeSync(start) {
  const sync = {mode: 'off', remote: null, interval: 15, shown: 'off', last_ok: null, last_try: null, last_error: null, paused_needs: 0,
    not_synced: [], public: null, remote_allowed: true, running: true, ...start};
  const calls = [];
  const answer = (op, args, state) => {
    calls.push({op, args});
    if (op === 'addon.set') { state.settings.addons.find(a => a.name === args.name).active = args.on; return null; }
    if (op !== 'addon.act' || args.addon !== 'sync') return null;
    if (args.verb === 'status') return {...sync};
    if (args.verb === 'check') return {ok: /^https:\/\/files\./.test(args.target)};
    if (args.verb === 'set') {
      if (args.target === 'off' || args.target === 'local') Object.assign(sync, {mode: args.target, remote: null, public: null, shown: args.target === 'off' ? 'off' : 'never'});
      else Object.assign(sync, {mode: 'remote', remote: args.target, interval: Number(args.value), shown: 'never'});
      return {mode: sync.mode, text: 'Saved.'};
    }
    if (args.verb === 'now') {
      if (sync.shown === 'paused') return {still_paused: sync.paused_needs, text: `Still paused: ${sync.paused_needs} things need you`};
      if (sync.public) return {choose_first: true, text: 'Not synced: choose a location above first'};
      Object.assign(sync, {shown: 'synced', last_ok: '2026-11-11T13:04:00'});
      return {text: 'Synced.'};
    }
    if (args.verb === 'use-public') { Object.assign(sync, {mode: 'remote', remote: sync.public, public: null}); return {mode: 'remote'}; }
    return {text: 'Done.'};
  };
  return {sync, calls, answer};
}

async function serve(context, state, fake) {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== BASE) return route.abort();
    if (url.pathname === '/api/state') return json(state);
    if (url.pathname === '/api/act') {
      const body = route.request().postDataJSON();
      const a = fake.answer(body.op, body.args || {}, state);
      return json(a ? {...state, act_answer: {addon: 'sync', answer: a}} : state);
    }
    if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
    if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
    const file = path.join(WEB, url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, ''));
    if (!file.startsWith(WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
    return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
      headers: {'Content-Security-Policy': CSP}, body: fs.readFileSync(file)});
  });
}

async function open(browser, width, start, mutate = s => s) {
  const context = await browser.newContext({viewport: {width, height: 900}, colorScheme: 'dark'});
  const state = mutate(fixture()), fake = fakeSync(start);
  await serve(context, state, fake);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(BASE + '/#settings');
  return {context, page, fake, state, errors};
}
const noSideways = page => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);

test('Sync card: open Settings, pick On this computer only, review, Save, status line; screenshots', {timeout: 180_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const browser = await chromium.launch();
  try {
    // 1. the flow (1440)
    {
      const {context, page, fake, errors} = await open(browser, 1440, {});
      const card = page.locator('#sync-card');
      await card.waitFor();
      await assert.doesNotReject(card.getByText('Where to keep a copy').waitFor());
      await page.locator('[data-key="sync-where-row-local"]').click();
      const review = page.locator('[data-key="sync-review"]');
      await review.waitFor();
      assert.equal((await review.locator('p').textContent()).trim(), 'Sync will keep a copy on this computer only.');
      await shot(page, card, 'flow-review-1440');
      await review.getByRole('button', {name: 'Save'}).click();
      await page.locator('[data-key="sync-status"]').filter({hasText: 'Not synced yet'}).waitFor();
      assert.equal(await review.count(), 0, 'the review line is gone after Save');
      assert.deepEqual(fake.calls.filter(c => c.args.verb === 'set').map(c => c.args), [{addon: 'sync', verb: 'set', target: 'local'}]);
      await shot(page, card, 'flow-saved-1440');
      assert.deepEqual(errors, []);
      await context.close();
    }
    for (const width of [1440, 390]) {
      // 2. synced, remote (Variant A)
      {
        const {context, page, errors} = await open(browser, width, {mode: 'remote', remote: 'https://files.example.org/mia/month-end', shown: 'synced',
          last_ok: '2026-11-11T10:15:00', not_synced: [{name: 'scans-march.zip', why: 'too big, stays on this computer'}, {name: 'payroll-access.txt', why: 'may contain a password or access key'}]});
        const card = page.locator('#sync-card');
        await page.locator('[data-key="sync-status"]').filter({hasText: 'Last synced 10:15'}).waitFor();
        await page.locator('[data-key="sync-skipped"]').click();
        await page.locator('#sync-details[open]').waitFor();
        await page.locator('[data-key="sync-check"]').click();
        await page.locator('[data-key="sync-check-res"]').filter({hasText: 'Connection works'}).waitFor();
        await shot(page, card, `A-${width}`);
        assert.equal(await noSideways(page), true, `A-${width}: no sideways scroll`);
        assert.deepEqual(errors, []);
        await context.close();
      }
      // 3. paused + public warning: Sync now is secondary and says what still needs the person
      {
        const {context, page, errors} = await open(browser, width, {mode: 'remote', remote: 'https://files.example.org/mia/month-end', shown: 'paused',
          paused_needs: 3, last_error: 'Not synced: tickets/t_q3x8k1.json: conflict', last_try: '2026-11-11T10:12:00', public: 'https://github.com/mia/orch'});
        const card = page.locator('#sync-card');
        const warn = page.locator('[data-key="sync-public"]');
        await warn.waitFor();
        assert.equal((await warn.locator('p').textContent()).trim(), 'This sync address is public. Anyone can read your tickets.');
        const now = page.locator('[data-key="sync-now"]');
        assert.match(await now.getAttribute('class'), /ghost/);
        await now.click();
        await page.locator('[data-key="sync-note"]').filter({hasText: 'Still paused: 3 things need you'}).waitFor();
        assert.equal((await page.locator('[data-key="sync-status"]').textContent()).trim(), 'Paused, review below');
        await shot(page, card, `A-paused-public-${width}`);
        await warn.getByRole('button', {name: 'Use public location'}).click();
        const dialog = page.locator('dialog.sign-step');
        await dialog.waitFor();
        await page.waitForTimeout(300);  // the 200 ms open animation (kit/motion.css) has ended
        assert.match(await dialog.textContent(), /Use a public location\?.*Anyone who knows the address can read your tickets\..*You sign this as me\./);
        await page.screenshot({path: path.join(OUT, `sign-public-${width}.png`)});
        await page.keyboard.press('Escape');
        assert.equal(await noSideways(page), true, `paused-${width}: no sideways scroll`);
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    // 4. add-on off: one switch row; the switch opens the add-on review, then the card
    {
      const {context, page, fake, errors} = await open(browser, 720, {}, s => { s.settings.addons.find(a => a.name === 'sync').active = false; return s; });
      const row = page.locator('#sync-card');
      await row.getByText('Keep a copy of my tickets').waitFor();
      await shot(page, row, 'off-720');
      await page.locator('[data-key="settings-switch-sync-off"]').click();
      const confirm = page.locator('dialog[open]');
      await confirm.getByRole('button', {name: 'Turn on'}).click();
      await page.locator('[data-key="sync-review"]').filter({hasText: 'Sync will keep a copy on this computer only.'}).waitFor();
      assert.deepEqual(fake.calls.find(c => c.op === 'addon.set').args, {name: 'sync', on: true});
      await shot(page, page.locator('#sync-card'), 'turned-on-720');
      assert.deepEqual(errors, []);
      await context.close();
    }
    // 5. Home › Needs you: the three sync rows and the sign step of Keep theirs
    for (const width of [1440, 390]) {
      const {context, page, fake, errors} = await open(browser, width, {});
      await page.goto(BASE + '/#home');
      await page.getByRole('button', {name: 'Show all'}).click();
      const rows = page.locator('.home-need.need-acts');
      await rows.first().waitFor();
      assert.equal(await rows.count(), 3);
      assert.deepEqual((await rows.locator('.sig').allTextContents()).map(t => t.trim()), ['Needs your signature', 'Needs your signature', 'Needs your signature']);
      await page.locator('#needs-you').screenshot({path: path.join(OUT, `needs-${width}.png`)});
      await rows.nth(0).getByRole('button', {name: 'Keep theirs'}).click();
      const dialog = page.locator('dialog.sign-step');
      await dialog.waitFor();
      await page.waitForTimeout(300);  // the 200 ms open animation (kit/motion.css) has ended
      assert.match(await dialog.textContent(), /Here:.*Other computer:.*You sign this as me\./);
      await page.screenshot({path: path.join(OUT, `sign-keep-theirs-${width}.png`)});
      await dialog.getByRole('button', {name: 'Sign'}).click();
      await page.waitForFunction(() => !document.querySelector('dialog.sign-step'));
      assert.deepEqual(fake.calls.at(-1), {op: 'addon.act', args: {addon: 'sync', verb: 'keep-theirs', target: 'tickets/t_q3x8k1.json', sign: true}});
      assert.equal(await noSideways(page), true, `needs-${width}: no sideways scroll`);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
});

async function shot(page, locator, name) {
  await locator.scrollIntoViewIfNeeded();
  await locator.screenshot({path: path.join(OUT, name + '.png')});
}
