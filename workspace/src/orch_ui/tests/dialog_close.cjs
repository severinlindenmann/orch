#!/usr/bin/env node
// ORCH-2060: the one dialog close lifecycle of the master (overlay.js + motion.js), in headless Chromium on
// fixtures/dialog_close.html (real master scripts and styles). Whoever awaits orch.close(dialog) must find the dialog
// closed for real, out of the overlay stack, the page scrollable again and focus back on the opener, with motion on and
// with reduced motion. Cancel and Escape, nested dialogs, a trigger taken out of the page, the next dialog opened right
// after the await, a rapid second close, Tab straight after closing and the file viewer. No timing thresholds: every
// check reads the state at the moment the promise settles. CI: job page-smoke, after the UX checks.
//
//   node workspace/src/orch_ui/tests/dialog_close.cjs        (PW_DIR=<node_modules with playwright> optional)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const headless = require(path.join(__dirname, '..', '..', '..', '..', 'e2e', 'headless.cjs'));

function playwright() {
  if (process.env.PW_DIR) return require(path.join(process.env.PW_DIR, 'playwright'));
  try { return require('playwright'); } catch (e) { /* fall through */ }
  return require(path.join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'playwright'));
}

const ROOT = path.resolve(__dirname, '..');
const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' };
function serve() {
  return http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/api/file') { res.writeHead(200, { 'content-type': 'text/plain' }); return res.end('Survey notes'); }
    if (url.pathname.startsWith('/api/')) { res.writeHead(204); return res.end(); }
    const file = path.resolve(ROOT, decodeURIComponent(url.pathname).replace(/^\/+/, ''));
    if (!file.startsWith(ROOT + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(fs.readFileSync(file));
  });
}

// The state the moment the close promise settles (the same promise a second close returns while the dialog fades).
const settled = (page, id) => page.evaluate(async id => {
  const d = (window[id] instanceof HTMLDialogElement && window[id]) || document.getElementById(id) || document.querySelector(id);
  await window.UI.overlay.close(d);
  const a = document.activeElement;
  return { open: d.open, closing: d.classList.contains('ui-closing'), top: window.UI.overlay.top()?.id || null,
    lock: document.documentElement.style.overflow, active: a?.id || a?.tagName.toLowerCase(), visible: a?.matches(':focus-visible') };
}, id);
const active = page => page.evaluate(() => document.activeElement?.id || document.activeElement?.tagName.toLowerCase());
const openA = async page => { await page.focus('#before'); await page.keyboard.press('Tab'); await page.keyboard.press('Enter'); await page.waitForFunction(() => document.getElementById('a').open); };

let browser, server, base;
test.before(async () => {
  server = serve(); await new Promise(r => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}/tests/fixtures/dialog_close.html`;
  browser = await headless.launch(playwright().chromium, { headless: true });
});
test.after(async () => { await browser?.close(); server?.close(); });

for (const motion of ['no-preference', 'reduce']) {
  const on = motion === 'no-preference';
  const fresh = async t => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: motion, colorScheme: 'dark' });
    t.after(() => ctx.close());
    const page = await ctx.newPage(); const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    t.after(() => assert.deepEqual(errors, [], 'no page errors'));
    await page.goto(base); return page;
  };
  const label = on ? 'motion on' : 'reduced motion';

  test(`${label}: Cancel settles closed, unlocked and focused on the opener; repeats share one close`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await openA(page);
    await page.focus('#a-cancel');
    const r = await page.evaluate(async () => {
      const d = document.getElementById('a'); let closes = 0; d.addEventListener('close', () => closes++);
      const closeEvent = new Promise(r => d.addEventListener('close', r, { once: true }));
      const p = window.orch.close(d), again = window.orch.close(d), viaDialog = d.close();
      const during = { open: d.open, anim: getComputedStyle(d).animationDuration,
        token: getComputedStyle(document.documentElement).getPropertyValue('--dur-exit').trim() };
      await p; const a = document.activeElement.id, open = d.open, top = window.UI.overlay.top() || null;
      await closeEvent;
      return { same: p === again && p === viaDialog, during, open, top, a, closes, lock: document.documentElement.style.overflow };
    });
    // Reduced motion closes at once, so the repeats find a closed dialog and get an already settled promise.
    if (on) assert.equal(r.same, true, 'orch.close, a repeat and dialog.close() share one promise');
    assert.equal(r.during.open, on, on ? 'still open while it fades' : 'reduced motion: closed at once');
    if (on) assert.equal(parseFloat(r.during.anim) * 1000, parseFloat(r.during.token), 'the fade is the exit token');
    assert.deepEqual([r.open, r.top, r.a, r.lock], [false, null, 'open-a', '']);
    assert.equal(r.closes, 1, 'one close event');
  });

  test(`${label}: Cancel by keyboard and Escape end the same way, with the focus mark on the opener`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    for (const how of ['cancel', 'escape']) {
      await openA(page);
      if (how === 'cancel') { await page.focus('#a-cancel'); await page.keyboard.press('Enter'); } else await page.keyboard.press('Escape');
      const s = await settled(page, 'a');
      assert.deepEqual(s, { open: false, closing: false, top: null, lock: '', active: 'open-a', visible: true }, how);
      const ring = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
      assert.notEqual(ring, 'none', `${how}: the master focus ring shows`);
    }
  });

  test(`${label}: Tab straight after Escape reaches the next control, Shift+Tab the opener`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await openA(page);
    await page.keyboard.press('Escape'); await page.keyboard.press('Tab');
    await settled(page, 'a');
    assert.equal(await active(page), 'after');
    await page.keyboard.press('Shift+Tab');
    assert.equal(await active(page), 'open-a');
  });

  test(`${label}: nested dialogs close one at a time, then both at once with two quick Escapes`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await openA(page);
    await page.focus('#open-b'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.getElementById('b').open);
    await page.keyboard.press('Escape');
    const inner = await settled(page, 'b');
    assert.deepEqual([inner.open, inner.top, inner.active, inner.lock], [false, 'a', 'open-b', 'hidden']);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.getElementById('a').contains(document.activeElement)), true, 'Tab stays in the open dialog');
    await page.focus('#open-b'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.getElementById('b').open);
    await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
    await settled(page, 'b');
    const outer = await settled(page, 'a');
    assert.deepEqual([outer.open, outer.top, outer.active, outer.lock], [false, null, 'open-a', '']);
  });

  test(`${label}: a trigger taken out of the page hands focus to the control after it`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await page.focus('#open-gone'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.getElementById('stop').open);
    await page.focus('#stop-ok'); await page.keyboard.press('Enter');
    const s = await settled(page, 'stop');
    assert.equal(await page.evaluate(() => !!document.getElementById('open-gone')), false);
    assert.deepEqual([s.open, s.top, s.active], [false, null, 'after-gone']);
  });

  test(`${label}: a dialog opened right after the await keeps focus when the old close event arrives`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await openA(page);
    const oldClose = page.evaluate(() => new Promise(r => document.getElementById('a').addEventListener('close', r, { once: true })));
    await page.focus('#a-save'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.getElementById('c').open);
    await oldClose;
    await page.evaluate(() => new Promise(requestAnimationFrame));
    const r = await page.evaluate(() => ({ inC: document.getElementById('c').contains(document.activeElement), a: document.getElementById('a').open, top: window.UI.overlay.top()?.id }));
    assert.deepEqual(r, { inC: true, a: false, top: 'c' });
    await page.keyboard.press('Escape');
    assert.equal((await settled(page, 'c')).active, 'open-a', 'the second dialog hands focus back where the first one did');
  });

  // O-02 (owner, 28 Nov): a click beside a dialog does nothing, so typed text is never lost; Esc still closes it.
  test(`${label}: a click beside a dialog, a sheet or the file viewer leaves it open with what was typed`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await openA(page);
    await page.evaluate(() => { const i = document.createElement('input'); i.id = 'typed'; i.className = 'input'; i.setAttribute('aria-label', 'Name'); document.getElementById('a').prepend(i); });
    await page.fill('#typed', 'Weekly newsletter');
    for (const [x, y] of [[8, 8], [1270, 400], [640, 790], [8, 400]]) await page.mouse.click(x, y);
    await page.waitForTimeout(200);  // longer than the exit fade: a close would have finished
    assert.deepEqual(await page.evaluate(() => ({ open: document.getElementById('a').open, top: window.UI.overlay.top()?.id, typed: document.getElementById('typed').value })),
      { open: true, top: 'a', typed: 'Weekly newsletter' });
    await page.keyboard.press('Escape');
    assert.equal((await settled(page, 'a')).open, false, 'Esc still closes it');
    await page.focus('#after-gone'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('dialog.fv')?.open);
    await page.mouse.click(4, 4); await page.waitForTimeout(200);
    assert.equal(await page.evaluate(() => document.querySelector('dialog.fv')?.open), true, 'the viewer stays open too');
  });

  test(`${label}: the file viewer closes through the same lifecycle and is gone when it settles`, {timeout: 30000}, async t => {
    const page = await fresh(t);
    await page.focus('#after-gone'); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('dialog.fv')?.open);
    await page.evaluate(() => { window.viewer = document.querySelector('dialog.fv'); });
    await page.keyboard.press('Escape');
    const s = await settled(page, 'viewer');
    assert.deepEqual([s.open, s.top, s.lock, s.active], [false, null, '', 'after-gone']);
    assert.equal(await page.evaluate(() => document.querySelector('dialog.fv')), null, 'the viewer is out of the page');
  });
}
