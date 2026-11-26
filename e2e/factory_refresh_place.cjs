// ORCH-2046 (ORCH-1966 draft 2): a background update of the Factory page keeps your place. Real Factory web files and
// the master kit in Chromium (own browser, mock keychain), every request answered in memory, the page's clock faked
// (no 15-second sleep: the test moves the clock to the next update itself).
//   Tab to "Open order" of order A, then the workspace changes: order C appears above A and order B changes stage.
//   The page reads again in place: the same link of A keeps focus, its visible focus mark and its place on screen;
//   nothing is said; Enter opens A and the visit focuses A's heading. When A is gone, focus moves to the next order's
//   same link and the page says so once.
// usage: [PW_DIR=..] [SHOTS_DIR=..] [FACTORY_WEB=<web folder>] [FACTORY_BEFORE=1] node --test e2e/factory_refresh_place.cjs
// FACTORY_BEFORE=1 with FACTORY_WEB set to an older web folder only takes the pictures (no checks): the "before".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'factory-refresh-place');
const WEB = process.env.FACTORY_WEB || path.join(__dirname, '..', 'workspace-addons', 'factory', 'src', 'orch_factory', 'web');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const BEFORE = process.env.FACTORY_BEFORE === '1';
const BASE = 'http://factory.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png'};
const A = 't_aaaa0001', B = 't_bbbb0001', C = 't_cccc0001';

const line = (at, done = []) => ['draft', 'build', 'check', 'ship'].map(stage => ({stage, state: done.includes(stage) ? 'done' : undefined, stop: stage === 'ship'}));
const running = (id, title, stage, done, used) => ({id, title, phase: 'started', kind: 'run', stage, line: line(stage, done), budget: {used, cap: 120}, eta: '2026-11-25T18:30:00'});
function homeData() {
  return {orders: [
    {id: 't_prop0001', title: 'Newsletter sign-up', phase: 'proposed', owner_min: 5},
    {id: 't_stop0001', title: 'Team calendar', phase: 'started', stage: 'build', line: line('build', ['draft']), budget: {used: 30, cap: 120},
      open: {kind: 'stop', q: 'q1', text: 'Check at Build?', options: ['Looks good', 'Change'], data: {stage: 'build', items: [{title: 'Week view', tag: 'routine'}], checked: ['Week view'], not_checked: []}}},
    running(A, 'Online booking page', 'build', ['draft'], 40),
    running(B, 'Usage report', 'build', ['draft'], 25),
    {id: 't_save0001', title: 'Gift box supplier comparison', phase: 'parked'},
    {id: 't_save0002', title: 'Opening hours page', phase: 'parked'},
    ...['Spring menu', 'Staff rota', 'Supplier invoices', 'Feedback form', 'Press page', 'Holiday notice'].map((title, i) => ({id: 't_save010' + i, title, phase: 'parked'})),
  ]};
}
// the change the workspace makes: C appears above A, B moves on to Check; with gone=true A is no longer listed
function changed(data, gone = false) {
  const orders = data.orders.filter(o => !(gone && o.id === A)).map(o => o.id === B ? running(B, 'Usage report', 'check', ['draft', 'build'], 61) : o);
  orders.splice(orders.findIndex(o => o.id === A || o.id === B), 0, running(C, 'Gift card checkout', 'draft', [], 5));
  return {...data, orders};
}

async function open(viewport) {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const box = {home: homeData(), reads: 0, hold: null, skip: 0};
  const browser = await headless.launch(chromium);
  try {
    const context = await browser.newContext({viewport});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== BASE) return route.abort();
      if (url.pathname === '/api/home') { box.reads++; if (box.hold && box.skip-- <= 0) await box.hold; return json({...box.home, generated_at: String(box.reads)}); }
      const order = /^\/api\/order\/(t_[a-z0-9]+)$/.exec(url.pathname);
      if (order) {
        const o = box.home.orders.find(x => x.id === order[1]);
        return o ? json({crew: [], activity: [], stops: [], changes: [], drafts: [], ...o}) : route.fulfill({status: 404, body: '{}'});
      }
      if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: '{}'});
      const rel = url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, '');
      const kit = rel.startsWith('kit' + path.sep);
      const file = kit ? path.join(KIT, rel.slice(4)) : path.join(WEB, rel.replace(/^web[/\\]/, ''));
      if (!file.startsWith(kit ? KIT : WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
      let body = fs.readFileSync(file);
      if (rel === 'index.html') body = body.toString().replaceAll('__P__', '');
      return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream', body});
    });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(String(e)));
    await page.clock.install({time: new Date('2026-11-25T10:00:00')});
    await page.goto(BASE + '/');
    await page.getByRole('heading', {name: 'Running'}).waitFor();
    return {page, box, errors, browser};
  } catch (e) { await browser.close(); throw e; }
}

// Tab from the top of the page to A's "Open order"; the names of every stop on the way (the keyboard sequence)
async function tabToA(page) {
  const names = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const at = await page.evaluate(() => { const el = document.activeElement; return {name: el.getAttribute('aria-label') || el.textContent.trim().slice(0, 60), href: el.getAttribute('href') || '', text: el.textContent.trim()}; });
    names.push(at.name);
    if (at.href === '#/order/t_aaaa0001' && at.text === 'Open order') return names;
  }
  throw new Error('A\'s Open order never got focus: ' + names.join(' → '));
}

const focused = page => page.evaluate(() => {
  const el = document.activeElement, r = el.getBoundingClientRect();
  return {tag: el.tagName, href: el.getAttribute('href'), text: el.textContent.trim(), label: el.getAttribute('aria-label'),
    visible: el.matches(':focus-visible'), outline: getComputedStyle(el).outlineStyle, top: Math.round(r.top), y: Math.round(scrollY)};
});

// watch the page while it reads: a skeleton or "Reading" frame, a new focus on the heading, words in the live regions
const watch = page => page.evaluate(() => {
  const seen = window.__seen = {skeleton: false, notices: 0, said: 0, h1: false};
  new MutationObserver(list => { for (const m of list) for (const n of m.addedNodes) if (n.nodeType === 1 && (n.matches('.skeleton, .f-loading') || n.querySelector?.('.skeleton'))) seen.skeleton = true; })
    .observe(document.getElementById('factory-view'), {childList: true, subtree: true});
  new MutationObserver(() => { seen.notices++; }).observe(document.getElementById('notices'), {childList: true, subtree: true, characterData: true});
  const said = document.getElementById('factory-said');
  if (said) new MutationObserver(() => { seen.said++; }).observe(said, {childList: true, subtree: true, characterData: true});
  document.addEventListener('focusin', e => { if (e.target.tagName === 'H1') seen.h1 = true; });
});
const seen = page => page.evaluate(() => window.__seen);

// one update: the page's 15-second tick, then wait until both reads are answered and the page settled
async function tick(page, box, reads = 2) {
  const want = box.reads + reads;
  await page.clock.runFor(15000);
  await page.waitForFunction(() => document.getElementById('factory-view').getAttribute('aria-busy') !== 'true', null, {timeout: 10_000});
  const until = Date.now() + 10_000;
  while (box.reads < want && Date.now() < until) await new Promise(r => setTimeout(r, 25));
  await page.waitForTimeout(150);  // the page draws in the same task as its last answer; give it one beat
}

for (const [w, h] of [[1440, 800], [390, 844]]) {
  test(`an update keeps focus, name and place on A; Enter opens A (${w}x${h})`, {timeout: 120_000}, async () => {
    const {page, box, errors, browser} = await open({width: w, height: h});
    try {
      const keys = await tabToA(page);
      const before = await focused(page);
      fs.writeFileSync(path.join(OUT, `keys-${w}.txt`), keys.map((n, i) => `Tab ${i + 1}: ${n}`).join('\n') + '\n');
      await watch(page);
      box.home = changed(box.home);
      await tick(page, box);
      await page.getByRole('heading', {name: 'Gift card checkout'}).waitFor();
      const after = await focused(page);
      await page.screenshot({path: path.join(OUT, `${BEFORE ? 'before' : 'after'}-${w}x${h}.png`)});
      fs.writeFileSync(path.join(OUT, `${BEFORE ? 'before' : 'after'}-${w}x${h}.json`), JSON.stringify({before, after, seen: await seen(page)}, null, 1));
      if (BEFORE) return;
      assert.equal(after.tag, 'A'); assert.equal(after.href, '#/order/' + A); assert.equal(after.text, 'Open order');
      assert.equal(after.label, 'Open order: Online booking page', 'the focused link names its order');
      assert.ok(after.visible && after.outline !== 'none', 'the focus mark stays visible');
      assert.ok(Math.abs(after.top - before.top) <= 1, `A's link stays where it was on screen (${before.top} -> ${after.top})`);
      const s = await seen(page);
      assert.deepEqual(s, {skeleton: false, notices: 0, said: 0, h1: false}, 'no loading frame, nothing said, no jump to the heading');
      assert.equal(await page.locator('#factory-view').evaluate(v => v.getAnimations({subtree: true}).filter(a => a.playState === 'running').length), 0, 'no entry motion again');
      assert.equal(await page.getByRole('link', {name: 'Open order: Usage report'}).count(), 1);
      assert.match(await page.locator('[data-order="t_bbbb0001"] .f-stage [aria-current]').textContent(), /Check/);
      // a deliberate visit: Enter opens A and its heading takes focus
      await page.keyboard.press('Enter');
      await page.getByRole('heading', {level: 1, name: 'Online booking page'}).waitFor();
      await page.waitForFunction(() => document.activeElement.tagName === 'H1');
      assert.equal(await page.evaluate(() => location.hash), '#/order/' + A);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  });
}

test('A is gone: focus moves to the next order\'s same link and the page says so once', {timeout: 120_000, skip: BEFORE}, async () => {
  const {page, box, errors, browser} = await open({width: 1440, height: 800});
  try {
    await tabToA(page);
    const before = await focused(page);
    await watch(page);
    box.home = changed(box.home, true);
    await tick(page, box);
    const after = await focused(page);
    assert.equal(after.href, '#/order/' + B); assert.equal(after.label, 'Open order: Usage report');
    assert.ok(after.visible);
    assert.ok(Math.abs(after.top - before.top) <= 1, `the next order's link takes A's place on screen (${before.top} -> ${after.top})`);
    const said = () => page.locator('#factory-said').textContent();
    assert.equal(await said(), '“Online booking page” is no longer here. You are on “Usage report”.');
    assert.equal((await seen(page)).said, 1);
    await page.screenshot({path: path.join(OUT, 'after-gone-1440x800.png')});
    // the next update keeps B: nothing is said again
    box.home = {...box.home, orders: box.home.orders.map(o => o.id === B ? {...o, budget: {used: 70, cap: 120}} : o)};
    await tick(page, box);
    assert.equal((await focused(page)).href, '#/order/' + B);
    assert.equal((await seen(page)).said, 1, 'said once');
    assert.equal((await seen(page)).h1, false);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

test('typing in the idea box holds the update, also when you start while it reads; it lands later', {timeout: 120_000, skip: BEFORE}, async () => {
  const {page, box, errors, browser} = await open({width: 1440, height: 800});
  try {
    let release; box.hold = new Promise(r => { release = r; }); box.skip = 1;  // the tick's own read passes; the redraw's read waits
    box.home = changed(box.home);
    await page.clock.runFor(15000);  // the tick sees the change; the redraw's read waits on the server
    while (box.reads < 2) await new Promise(r => setTimeout(r, 25));
    await page.getByRole('textbox', {name: 'Your idea'}).fill('A page for the summer menu');  // you start typing
    release(); box.hold = null;
    await page.waitForTimeout(300);
    assert.equal(await page.getByRole('heading', {name: 'Gift card checkout'}).count(), 0, 'nothing redrawn under your typing');
    assert.equal(await page.getByRole('textbox', {name: 'Your idea'}).inputValue(), 'A page for the summer menu');
    await page.getByRole('textbox', {name: 'Your idea'}).fill('');
    await page.getByRole('link', {name: 'Open order: Online booking page'}).focus();  // a focused link never freezes it
    await tick(page, box);
    await page.getByRole('heading', {name: 'Gift card checkout'}).waitFor();
    assert.equal((await focused(page)).label, 'Open order: Online booking page');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
