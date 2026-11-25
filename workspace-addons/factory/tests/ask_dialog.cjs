'use strict';
// ORCH-2062: the Factory "Ask another workspace" dialog in a real browser. The page is the real web/factory.js with the
// master kit, framed by a small parent that stands in for the dashboard: it records the target of each orch.ask the
// dialog sends and answers "delivered". Every API answer comes from FIXTURE (made by test_ask.py with the real pageapi
// on the fake workspace); the test then runs the add-on's ask act with the recorded targets and checks what arrived.
// usage: FIXTURE=<json> [PW_DIR=..] [SHOTS_DIR=..] [SHOT_WIDTHS=390x844,1440x800] [FACTORY_JS=<file>] node ask_dialog.cjs
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('../../../e2e/headless.cjs');  // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const WEB = path.join(__dirname, '..', 'src', 'orch_factory', 'web');
const KIT = path.join(__dirname, '..', '..', '..', 'workspace', 'src', 'orch_ui', 'static');
const FIX = JSON.parse(fs.readFileSync(process.env.FIXTURE, 'utf8'));
const BASE = 'http://factory.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png'};
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const PARENT = '<!doctype html><meta charset="utf-8"><title>Dashboard</title><style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>'
  + '<iframe id="f" title="Factory"></iframe><script>window.targets=[];addEventListener("message",e=>{const d=e.data;'
  + 'if(!d||d.type!=="orch.ask")return;window.targets.push(d.target);e.source.postMessage({type:"orch.ask.done",id:d.id,state:"delivered"},location.origin);});'
  + 'document.getElementById("f").src="/addon/factory/#/order/' + FIX.order_id + '/stop/1";</script>';

async function open(browser, {width = 1280, height = 800, scan = 'scan', hold = false} = {}) {
  const context = await browser.newContext({viewport: {width, height}, reducedMotion: 'reduce'});
  let release = () => {};
  const held = new Promise(r => { release = r; });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== BASE) return route.abort();
    const p = url.pathname;
    if (p === '/') return route.fulfill({status: 200, contentType: 'text/html', body: PARENT});
    if (p === '/addon/factory/') {
      const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8').replaceAll('__P__', '/addon/factory');
      return route.fulfill({status: 200, contentType: 'text/html', body: html});
    }
    if (p === '/addon/factory/web/factory.js') return route.fulfill({status: 200, contentType: TYPES['.js'], body: fs.readFileSync(process.env.FACTORY_JS || path.join(WEB, 'factory.js'))});
    const web = /^\/addon\/factory\/(web|kit)\/([a-z.-]+)$/.exec(p);
    if (web) {
      const file = path.join(web[1] === 'web' ? WEB : KIT, web[2]);
      return fs.existsSync(file) ? route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'text/plain', body: fs.readFileSync(file)}) : route.fulfill({status: 404, body: ''});
    }
    if (p === '/addon/factory/api/home') return json(FIX.home);
    if (p === '/addon/factory/api/reach') return json(FIX.reach);
    if (p === '/addon/factory/api/order/' + FIX.order_id) return json(FIX.order);
    if (p === '/addon/factory/api/order/' + FIX.order_id + '/stop/1/scan') {
      if (hold) await held;
      return scan === 'fail' ? route.fulfill({status: 503, contentType: 'application/json', body: '{"error":"busy"}'}) : json(FIX[scan]);
    }
    if (p.startsWith('/addon/factory/api/order/' + FIX.order_id + '/file/')) return route.fulfill({status: 200, contentType: 'image/png', body: PNG});
    return route.fulfill({status: 404, body: ''});
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(BASE + '/');
  const frame = page.frameLocator('#f');
  const ask = frame.getByRole('button', {name: 'Ask another workspace'}).first();
  await ask.waitFor();
  return {context, page, frame, ask, errors, release};
}

// what the dialog says and shows, read the way a person and a screen reader get it
async function look(frame) {
  const dialog = frame.locator('dialog[open]');
  return dialog.evaluate(d => {
    const status = d.querySelector('[role=status]');
    return {
      status_role: !!status,
      status: status ? [...status.children].filter(c => !c.hidden).map(c => c.textContent.trim()).filter(Boolean) : [],
      banners: [...d.querySelectorAll('.banner')].map(b => b.textContent.trim()),
      boxes: [...d.querySelectorAll('input[type=checkbox]')].map(b => ({checked: b.checked, disabled: b.disabled, label: b.closest('label').textContent.trim()})),
      send_disabled: d.querySelector('.btn.primary').disabled,
      sideways: d.scrollWidth > d.clientWidth + 1 || document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      text: d.innerText,
    };
  });
}
const settled = frame => frame.locator('dialog[open]').filter({hasNotText: 'Checking for passwords'}).waitFor();

async function main() {
  const {chromium} = require(path.join(PW, 'playwright'));
  const browser = await headless.launch(chromium, {headless: true});
  const out = {};
  try {
    // pictures of the excluded-item preview (draft evidence, before the checks so an older page still gets them), never into git
    if (process.env.SHOTS_DIR) {
      fs.mkdirSync(process.env.SHOTS_DIR, {recursive: true});
      for (const size of (process.env.SHOT_WIDTHS || '390x844,1440x800,1280x800,1920x1080').split(',')) {
        const [width, height] = size.split('x').map(Number);
        const s = await open(browser, {width, height});
        await s.ask.click(); await settled(s.frame);
        // the ticked items and the check's words in view (the dialog scrolls on a small screen)
        await s.frame.locator('dialog[open] .check-label').first().evaluate(el => el.scrollIntoView({block: 'start'}));
        await s.page.waitForTimeout(150);
        await s.page.screenshot({path: path.join(process.env.SHOTS_DIR, (process.env.SHOT_NAME || 'ask') + '-' + size + '.png')});
        await s.context.close();
      }
    }
    // 1. the excluded item, by keyboard only: open, read the status, untick and tick the good item, Send
    {
      const s = await open(browser);
      await s.ask.focus(); await s.page.keyboard.press('Enter');
      await s.frame.locator('dialog[open]').waitFor();
      await s.frame.locator('dialog[open] .banner').waitFor();
      const after = await look(s.frame);
      // Tab to the good item's box (the disabled one is skipped), Space unticks it, Space ticks it again
      let label = '';
      for (let i = 0; i < 8 && !/Window/.test(label); i++) {
        await s.page.keyboard.press('Tab');
        label = await s.frame.locator(':focus').evaluate(el => (el.closest('label') || el).textContent.trim()).catch(() => '');
      }
      await s.page.keyboard.press('Space');
      const none = await look(s.frame);
      await s.page.keyboard.press('Space');
      const back = await look(s.frame);
      for (let i = 0; i < 4; i++) {
        await s.page.keyboard.press('Tab');
        if (await s.frame.locator(':focus').evaluate(el => el.textContent.trim() === 'Send')) break;
      }
      await s.page.keyboard.press('Enter');
      await s.frame.locator('dialog[open]').waitFor({state: 'detached'});
      out.keyboard = {after, focused_box: label, none, back, targets: await s.page.evaluate(() => window.targets), errors: s.errors};
      await s.context.close();
    }
    // 2. no item ticked: the person unticks the good item with a click; Send still sends title, line and question
    {
      const s = await open(browser);
      await s.ask.click(); await settled(s.frame);
      await s.frame.locator('dialog[open] input[type=checkbox]:not([disabled])').uncheck();
      const seen = await look(s.frame);
      await s.frame.getByRole('button', {name: 'Send'}).click();
      await s.frame.locator('dialog[open]').waitFor({state: 'detached'});
      out.none = {seen, targets: await s.page.evaluate(() => window.targets)};
      await s.context.close();
    }
    // 3. could not check (the picture is missing): told apart from a hit; Cancel and Escape send nothing
    {
      const s = await open(browser, {scan: 'scan_unchecked'});
      await s.ask.click(); await settled(s.frame);
      await s.frame.locator('dialog[open] .banner').waitFor();
      const seen = await look(s.frame);
      await s.frame.getByRole('button', {name: 'Cancel'}).click();
      const closed = await s.frame.locator('dialog[open]').waitFor({state: 'detached', timeout: 3000}).then(() => 0, () => 1);
      await s.ask.click(); await s.frame.locator('dialog[open]').waitFor();
      await s.page.keyboard.press('Escape');
      const escaped = await s.frame.locator('dialog[open]').waitFor({state: 'detached', timeout: 3000}).then(() => true, () => false);
      out.unchecked = {seen, closed_by_cancel: closed === 0, closed_by_escape: escaped,
        targets: await s.page.evaluate(() => window.targets)};
      await s.context.close();
    }
    // 4. pending, then failed: Send waits for the check, then sends what is ticked (Send checks again)
    {
      const s = await open(browser, {scan: 'fail', hold: true});
      await s.ask.click(); await s.frame.locator('dialog[open]').waitFor();
      const pending = await look(s.frame);
      s.release(); await settled(s.frame);
      const failed = await look(s.frame);
      await s.frame.getByRole('button', {name: 'Send'}).click();
      await s.frame.locator('dialog[open]').waitFor({state: 'detached'});
      out.pending_failed = {pending, failed, targets: await s.page.evaluate(() => window.targets)};
      await s.context.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
}
main().catch(e => { console.error(e); process.exit(1); });
