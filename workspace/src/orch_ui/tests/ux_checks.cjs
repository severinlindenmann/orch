#!/usr/bin/env node
// UX checks: the cheap automatic items of the UX/UI checklist (skill orch-ux-checklist, DESIGN.md "UX/UI checklist"),
// run in headless Chromium on the master gallery (every component in every state). CI: job `page-smoke`, started at
// the end of e2e/focus_insights_smoke.cjs. Fails on:
//   I1/H9  page sideways scroll at 1280, 390 or 320 px wide, and a .sidebar (the rail) that scrolls sideways;
//   H5     a control smaller than 24x24 CSS px (inline links inside a sentence are exempt, WCAG 2.5.8);
//   H4     a control that shows no focus mark (outline or ring) when reached with the Tab key;
//   H10    an animation or transition still running when the person asked for reduced motion;
//   H6     a control whose aria-label does not contain its visible text (label in name, WCAG 2.5.3);
//   H1     text below 4.5:1 (3:1 at 24 px, or 18.66 px bold) against the colour behind it (logo tiles .li exempt);
//   H6     a control with no name (an icon-only button needs aria-label);
//   H3     the keyboard path: a modal dialog takes focus, keeps Tab and Shift+Tab inside, shows the focus mark there,
//          closes on Escape and gives focus back to the button that opened it; a menu opens with Enter, moves into its
//          items with the arrow keys, closes on Escape (focus back on its button) and on Tab; arrow keys move between tabs;
//   a console error, an uncaught exception or a failed request.
// Token contrast is checked without a browser in brand/tests/test_contrast.py; page-local colours by
// scripts/check_style.py (A1). Everything else on the checklist is checked by eye (DESIGN.md says which).
//
//   node workspace/src/orch_ui/tests/ux_checks.cjs              (exit 0 = clean)
//   node workspace/src/orch_ui/tests/ux_checks.cjs --page gallery.html --page demo.html
//   node workspace/src/orch_ui/tests/ux_checks.cjs --selftest   (fixtures/ux_checks/bad.html must trip every check)
'use strict';
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
// Run from the repository only (CI job page-smoke, helpers): the keychain options come from the e2e helper (ORCH-615).
const headless = require(path.join(__dirname, '..', '..', '..', '..', 'e2e', 'headless.cjs'));
const { execFileSync } = require('node:child_process');

const STATIC = path.resolve(__dirname, '../static');
const args = process.argv.slice(2);
const PAGES = args.flatMap((a, i) => (a === '--page' ? [args[i + 1]] : []));
if (!PAGES.length) PAGES.push('gallery.html');
const WIDTHS = [1280, 390, 320];
const TAB_STOPS = 60; // focus is checked on the first 60 Tab stops of each page

function playwright() {
  try { return require('playwright'); } catch (e) { /* fall through */ }
  const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
  return require(path.join(root, 'playwright'));
}

const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.json': 'application/json', '.md': 'text/markdown', '.woff2': 'font/woff2' };

function serve(dir) {
  const srv = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '');
    const file = path.resolve(dir, rel);
    if (!file.startsWith(dir + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404); return res.end();
    }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(ok => srv.listen(0, '127.0.0.1', () => ok(srv)));
}

// Runs in the page: sideways scroll, small targets and low text contrast.
function layoutProblems() {
  const out = [];
  const de = document.documentElement;
  if (de.scrollWidth > window.innerWidth + 1) out.push(`page scrolls sideways (${de.scrollWidth} px wide content in ${window.innerWidth} px)`);
  const shown = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden],[inert],dialog:not([open])'); };
  // the narrow rail must hold its foot (person switch, state) without scrolling sideways (ORCH-1636, ORCH-1638)
  for (const sb of document.querySelectorAll('.sidebar')) if (shown(sb) && sb.scrollWidth > sb.clientWidth + 1) out.push(`sidebar scrolls sideways (${sb.scrollWidth} px of content in ${sb.clientWidth} px)`);
  const label = el => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''} "${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30)}"`;
  const inSentence = el => el.tagName === 'A' && [...(el.parentElement ? el.parentElement.childNodes : [])]
    .some(n => n !== el && n.nodeType === 3 && n.textContent.trim().length > 1);
  const controls = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=switch], [role=checkbox], [role=menuitem]';
  // WCAG 2.5.8: a target under 24x24 still passes when a 24 px circle on its centre touches no other target. A control
  // inside a <label> counts with its label; visually hidden native controls (1-2 px, the custom select) are skipped.
  const box = el => { const lab = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
    return (lab && shown(lab) ? lab : el).getBoundingClientRect(); };
  // The part of a neighbour a person can see and hit: a link cut off by its cell (overflow hidden, "Show the in…")
  // does not reach under the next cell's link, though its own box does (the gallery's pull request table with
  // Linux fonts, merge queue group #3413). Only the neighbour is cut; a target's own size stays its full box.
  const cutBox = (el, r) => { let { left, top, right, bottom } = r;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p); const c = p.getBoundingClientRect();
      if (/hidden|clip/.test(s.overflowX)) { left = Math.max(left, c.left); right = Math.min(right, c.right); }
      if (/hidden|clip/.test(s.overflowY)) { top = Math.max(top, c.top); bottom = Math.min(bottom, c.bottom); }
    }
    return { left, top, right, bottom, gone: right <= left || bottom <= top }; };
  const targets = [...document.querySelectorAll(controls)].filter(el => shown(el) && !el.classList.contains('skip-link'))
    .map(el => ({ el, r: box(el) })).filter(t => t.r.width > 2 && t.r.height > 2).map(t => ({ ...t, v: cutBox(t.el, t.r) }));
  const near = (r, o) => { const cx = r.left + r.width / 2; const cy = r.top + r.height / 2;
    const dx = Math.max(o.left - cx, 0, cx - o.right); const dy = Math.max(o.top - cy, 0, cy - o.bottom);
    return Math.hypot(dx, dy) < 12; };
  for (const t of targets) {
    const { el, r } = t;
    if (inSentence(el) || (r.width >= 23.5 && r.height >= 23.5)) continue;
    const crowded = targets.some(o => o !== t && !o.el.contains(el) && !el.contains(o.el) && !o.v.gone && near(r, o.v));
    if (crowded) out.push(`target ${Math.round(r.width)}x${Math.round(r.height)} px under 24x24 with another target too close: ${label(el)}`);
  }
  // H6 label in name (WCAG 2.5.3): a control whose aria-label does not hold the words on it can't be said by voice control.
  const words = v => String(v || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const seenText = el => { let txt = ''; const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) if (!n.parentElement.closest('svg,[aria-hidden=true],.sr-only,.visually-hidden')) txt += ' ' + n.textContent;
    return words(txt); };
  // Older master parts still to fix (#2873); remove a selector when its fix lands. Every other control is checked.
  const LABEL_IN_NAME_LATER = '.dl-conn-b,.wall-open,.wall-lopen,.bpeek-btn,.decision-shot,.lbar-cnt,.parts-bar,.live-pt,.live-edge,[aria-label="Open Focus where it was last"]';
  for (const { el } of targets) {
    if (!el.hasAttribute('aria-label') || el.matches('input,select,textarea') || el.matches(LABEL_IN_NAME_LATER)) continue;
    const vis = seenText(el);
    if (vis.length > 1 && !words(el.getAttribute('aria-label')).includes(vis)) out.push(`label in name: "${el.getAttribute('aria-label').slice(0, 40)}" does not hold the text on it "${vis.slice(0, 40)}": ${label(el)}`);
  }
  // Text contrast against the first opaque colour behind it; skipped where a picture, gradient or see-through layer is behind.
  const rgb = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const behind = el => { for (let n = el; n; n = n.parentElement) { const s = getComputedStyle(n);
      if (s.backgroundImage !== 'none' || parseFloat(s.opacity) < 1 || s.filter !== 'none') return null;
      const c = rgb(s.backgroundColor); if (c && c.a >= 1) return c; if (c && c.a > 0) return null; }
    return rgb(getComputedStyle(document.body).backgroundColor); };
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const el = t.parentElement;
    if (!t.textContent.trim() || !el || seen.has(el) || !shown(el) || el.closest('svg,[aria-hidden=true],.sr-only,.visually-hidden,.li')) continue;
    seen.add(el);
    const s = getComputedStyle(el);
    if (el.closest(':disabled,[aria-disabled=true],.disabled')) continue; // WCAG 1.4.3: inactive controls are exempt
    const fg = rgb(s.color); const bg = behind(el);
    if (!fg || !bg || fg.a < 1) continue;
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    const ratio = (a + 0.05) / (b + 0.05);
    const px = parseFloat(s.fontSize); const large = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700);
    if (ratio < (large ? 3 : 4.5) - 0.01) out.push(`text contrast ${ratio.toFixed(2)}:1 under ${large ? 3 : 4.5}:1: ${label(el)}`);
  }
  // H6: every control has a name: its text, aria-label(ledby), a <label>, title or placeholder. Icons (aria-hidden) are no name.
  const named = el => {
    const by = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (by.some(id => (document.getElementById(id)?.textContent || '').trim())) return true;
    if (['aria-label', 'title', 'placeholder', 'alt'].some(a => (el.getAttribute(a) || '').trim())) return true;
    if (el.labels && [...el.labels].some(l => l.textContent.trim())) return true;
    if (el.tagName === 'INPUT' && ['submit', 'reset', 'button'].includes(el.type) && el.value.trim()) return true;
    const text = n => [...n.childNodes].some(c => (c.nodeType === 3 && c.textContent.trim()) || (c.nodeType === 1
      && c.getAttribute('aria-hidden') !== 'true' && ((c.tagName === 'IMG' && (c.alt || '').trim()) || text(c))));
    return text(el);
  };
  for (const el of document.querySelectorAll(controls)) {
    if (!shown(el) || el.closest('[aria-hidden=true]') || el.tabIndex < 0 && !el.matches('[role=tab]')) continue;
    if (!named(el)) out.push(`control has no name (icon-only? add aria-label): ${el.outerHTML.slice(0, 80)}`);
  }
  return out;
}

// Runs in the page: what the focused element shows.
function focusMark() {
  const el = document.activeElement;
  if (!el || el === document.body || el.tagName === 'IFRAME') return null; // inside a frame the frame's page shows the mark
  const s = getComputedStyle(el);
  const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  // The mark may sit on the element or on a part inside it (the round swipe buttons ring their circle).
  const ring = [el, ...el.querySelectorAll('*')].slice(0, 20).some(n => { const c = getComputedStyle(n);
    return (c.boxShadow && c.boxShadow !== 'none') || (n !== el && c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0); });
  const name = `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''} "${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30)}"`;
  return { name, ok: outline || ring };
}

// H3: the keyboard path through dialogs, menus and tabs, by real key presses.
const KEY_WAIT = 260; // the overlay closes after its 100 ms fade
async function keyboardPath(page, note) {
  const where = () => page.evaluate(() => { const a = document.activeElement; return a ? a.outerHTML.slice(0, 60) : 'nothing'; });
  // Dialogs: a button opens each closed dialog with Enter, as a person would.
  const dialogs = await page.evaluate(() => { const ds = [...document.querySelectorAll('dialog')].filter(d => !d.open);
    ds.forEach((d, i) => { d.dataset.uxcDialog = i; }); return ds.map(d => d.getAttribute('aria-label') || d.id || d.className || 'dialog'); });
  for (let i = 0; i < Math.min(dialogs.length, 8); i++) {
    const name = `dialog "${dialogs[i]}"`;
    await page.evaluate(i => { const b = document.createElement('button'); b.type = 'button'; b.id = 'uxc-opener'; b.textContent = 'Open';
      b.onclick = () => document.querySelector(`[data-uxc-dialog="${i}"]`)?.showModal(); document.body.prepend(b); b.focus(); }, i);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(KEY_WAIT);
    const inside = () => page.evaluate(i => { const d = document.querySelector(`[data-uxc-dialog="${i}"]`); return !!d && d.open && d.contains(document.activeElement); }, i);
    if (!(await inside())) note(`${name}: focus did not move into the dialog when it opened (on ${await where()})`);
    if (!(await page.evaluate(i => !!document.querySelector(`[data-uxc-dialog="${i}"]`), i))) { await page.evaluate(() => document.getElementById('uxc-opener')?.remove()); continue; }
    const stops = await page.evaluate(i => document.querySelector(`[data-uxc-dialog="${i}"]`).querySelectorAll('button,a[href],input,textarea,select,summary,[tabindex]').length, i);
    for (const key of [...Array(Math.min(stops + 2, 24)).fill('Tab'), 'Shift+Tab', 'Shift+Tab']) {
      await page.keyboard.press(key);
      if (!(await inside())) { note(`${name}: ${key} let focus leave the open dialog (focus trap) to ${await where()}`); break; }
      const f = await page.evaluate(focusMark);
      if (f && !f.ok) { note(`${name}: no focus mark on ${f.name}`); break; }
    }
    await page.keyboard.press('Escape');
    await page.waitForTimeout(KEY_WAIT);
    const after = await page.evaluate(i => ({ open: document.querySelector(`[data-uxc-dialog="${i}"]`)?.open,
      back: document.activeElement === document.getElementById('uxc-opener') }), i);
    if (after.open) note(`${name}: Escape did not close the dialog`);
    else if (!after.back) note(`${name}: Escape did not give focus back to the button that opened the dialog (on ${await where()})`);
    await page.evaluate(i => { const d = document.querySelector(`[data-uxc-dialog="${i}"]`); if (d?.open) HTMLDialogElement.prototype.close.call(d); document.getElementById('uxc-opener')?.remove(); }, i);
    await page.waitForTimeout(KEY_WAIT);
  }
  // Menus: details with a .menu / .menu-pop (the master's menu button).
  const menus = await page.evaluate(() => { const ms = [...document.querySelectorAll('details')].filter(d => !d.open && d.querySelector(':scope>summary')
      && (d.querySelector('.menu,.menu-pop') || d.matches('.dropdown,.menu')) && d.querySelector(':scope>summary').getClientRects().length
      && d.querySelector(':scope>summary').tabIndex >= 0 && d.querySelector(':scope>summary').getAttribute('aria-disabled') !== 'true');
    ms.forEach((d, i) => { d.dataset.uxcMenu = i; }); return ms.map(d => d.querySelector(':scope>summary').textContent.trim().slice(0, 30) || d.className); });
  for (let i = 0; i < Math.min(menus.length, 10); i++) {
    const name = `menu "${menus[i]}"`;
    // a page that draws itself again may replace the menu mid-check: then there is nothing left to check
    const state = () => page.evaluate(i => { const d = document.querySelector(`[data-uxc-menu="${i}"]`); if (!d) return { gone: true }; const s = d.querySelector(':scope>summary');
      return { open: d.open, inItem: d.contains(document.activeElement) && document.activeElement !== s, onButton: document.activeElement === s }; }, i);
    const open = async () => { const on = await page.evaluate(i => { const s = document.querySelector(`[data-uxc-menu="${i}"]>summary`); s?.focus(); return !!s && document.activeElement === s; }, i);
      if (!on) return { gone: true }; // never press Enter on whatever else has focus
      await page.keyboard.press('Enter'); await page.waitForTimeout(50); await page.keyboard.press('ArrowDown'); await page.waitForTimeout(50); return state(); };
    let s = await open();
    if (s.gone) continue;
    // a menu the page fills only when it opens (the board's Move menu) has nothing to check in the gallery
    const items = await page.evaluate(i => [...document.querySelectorAll(`[data-uxc-menu="${i}"] :is(a[href],button,input,select,textarea)`)]
      .filter(n => !n.disabled && n.getClientRects().length).length, i);
    if (!items) { await page.evaluate(i => { const d = document.querySelector(`[data-uxc-menu="${i}"]`); if (d) d.open = false; }, i); continue; }
    if (!s.open || !s.inItem) { note(`${name}: Enter then ArrowDown did not move focus into the open menu (on ${await where()})`); }
    else {
      const f = await page.evaluate(focusMark);
      if (f && !f.ok) note(`${name}: no focus mark on ${f.name}`);
      await page.keyboard.press('Escape'); await page.waitForTimeout(50); s = await state();
      if (!s.gone && (s.open || !s.onButton)) note(`${name}: Escape did not close the menu and give focus back to its button`);
      s = await open();
      if (s.inItem) { await page.keyboard.press('Tab'); await page.waitForTimeout(50); s = await state();
        if (!s.gone && s.open && !s.inItem) note(`${name}: Tab moved focus out of the menu but left it open`); }
    }
    await page.evaluate(i => { const d = document.querySelector(`[data-uxc-menu="${i}"]`); if (d) d.open = false; }, i);
  }
  // Tabs: the arrow keys move to the next tab and choose it.
  const lists = await page.evaluate(() => { const ls = [...document.querySelectorAll('[role=tablist]')].filter(l => l.querySelectorAll('[role=tab]').length > 1 && l.getClientRects().length);
    ls.forEach((l, i) => { l.dataset.uxcTabs = i; }); return ls.length; });
  for (let i = 0; i < Math.min(lists, 6); i++) {
    const ok = await page.evaluate(i => { const l = document.querySelector(`[data-uxc-tabs="${i}"]`); if (!l) return null; const t = l.querySelector('[role=tab][aria-selected=true]') || l.querySelector('[role=tab]');
      t.focus(); window.__uxcTab = t; return document.activeElement === t; }, i);
    if (ok === null) continue;
    if (!ok) { note(`tabs ${i + 1}: the chosen tab cannot take focus`); continue; }
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(50);
    const moved = await page.evaluate(() => { const a = document.activeElement; return a !== window.__uxcTab && a?.getAttribute('role') === 'tab' && a.getAttribute('aria-selected') === 'true'; });
    if (!moved) note(`tabs ${i + 1}: ArrowRight did not move to and choose the next tab`);
    await page.evaluate(() => { window.__uxcTab?.click(); });
  }
}

async function run(root, pages) {
  const { chromium } = playwright();
  const srv = await serve(root);
  const base = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await headless.launch(chromium);
  const problems = [];
  try {
    for (const p of pages) {
      for (const width of WIDTHS) {
        const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 800 } });
        const page = await ctx.newPage();
        const note = what => problems.push(`${p} @${width}: ${what}`);
        page.on('console', m => { if (m.type() === 'error') note(`console error: ${m.text().slice(0, 200)}`); });
        page.on('pageerror', e => note(`uncaught exception: ${String(e.message).slice(0, 200)}`));
        page.on('requestfailed', r => note(`request failed: ${r.url().replace(base, '')}`));
        page.on('response', r => { if (r.status() >= 400) note(`HTTP ${r.status()}: ${r.url().replace(base, '')}`); });
        await page.goto(base + p, { waitUntil: 'load' });
        await page.waitForTimeout(400);
        for (const what of await page.evaluate(layoutProblems)) note(what);
        if (width === 1280) {
          const seen = new Set();
          for (let i = 0; i < TAB_STOPS; i++) {
            await page.keyboard.press('Tab');
            const f = await page.evaluate(focusMark);
            if (!f || seen.has(f.name)) continue;
            seen.add(f.name);
            if (!f.ok) note(`no focus mark on ${f.name}`);
          }
          await keyboardPath(page, note);
        }
        await ctx.close();
      }
      // H10: with reduced motion asked for, nothing may still move.
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
      const page = await ctx.newPage();
      await page.goto(base + p, { waitUntil: 'load' });
      await page.waitForTimeout(400);
      const moving = await page.evaluate(() => document.getAnimations()
        .filter(a => a.playState === 'running' && a.effect && a.effect.getTiming().duration > 0)
        .map(a => { const t = a.effect.target; return `${a.animationName || a.transitionProperty || 'animation'} on ${t ? t.tagName.toLowerCase() + (t.className && typeof t.className === 'string' ? '.' + t.className.trim().split(/\s+/).join('.') : '') : '?'}`; }));
      for (const m of new Set(moving)) problems.push(`${p} reduced motion: still moving: ${m}`);
      await ctx.close();
    }
  } finally { await browser.close(); srv.close(); }
  return [...new Set(problems)];
}

// --selftest: a page with one known fault of each kind must trip every check (a check that finds nothing is broken).
const SELFTEST = ['sideways', 'sidebar', 'target', 'focus mark', 'reduced motion', 'contrast', 'label in name', 'console error', 'no name',
  'focus trap', 'into the open menu', 'tabs'];

module.exports = { layoutProblems, focusMark, keyboardPath };
if (require.main === module) (async () => {
  if (args.includes('--selftest')) {
    const found = (await run(path.join(__dirname, 'fixtures/ux_checks'), ['bad.html'])).join('\n');
    const missed = SELFTEST.filter(k => !found.includes(k));
    if (missed.length) { console.error(`UX CHECKS SELFTEST FAILED: not caught: ${missed.join(', ')}\n${found}`); process.exit(1); }
    console.log(`ux checks selftest ok: caught ${SELFTEST.join(', ')}`);
    return;
  }
  const unique = await run(STATIC, PAGES);
  if (unique.length) {
    console.error(`UX CHECKS FAILED (${unique.length}):\n` + unique.map(x => '  - ' + x).join('\n'));
    process.exit(1);
  }
  console.log(`ux checks ok: ${PAGES.join(', ')} at ${WIDTHS.join('/')} px, focus, names, label in name, keyboard path, reduced motion, contrast`);
})().catch(e => { console.error(e); process.exit(1); });
