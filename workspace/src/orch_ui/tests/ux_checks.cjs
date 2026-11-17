#!/usr/bin/env node
// UX checks: the cheap automatic items of the UX/UI checklist (skill orch-ux-checklist, DESIGN.md "UX/UI checklist"),
// run in headless Chromium on the master gallery (every component in every state). CI: job `page-smoke`, started at
// the end of e2e/focus_insights_smoke.cjs. Fails on:
//   I1/H9  page sideways scroll at 1280, 390 or 320 px wide;
//   H5     a control smaller than 24x24 CSS px (inline links inside a sentence are exempt, WCAG 2.5.8);
//   H4     a control that shows no focus mark (outline or ring) when reached with the Tab key;
//   H10    an animation or transition still running when the person asked for reduced motion;
//   H1     text below 4.5:1 (3:1 at 24 px, or 18.66 px bold) against the colour behind it (logo tiles .li exempt);
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
  const label = el => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''} "${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30)}"`;
  const inSentence = el => el.tagName === 'A' && [...(el.parentElement ? el.parentElement.childNodes : [])]
    .some(n => n !== el && n.nodeType === 3 && n.textContent.trim().length > 1);
  const controls = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=switch], [role=checkbox], [role=menuitem]';
  // WCAG 2.5.8: a target under 24x24 still passes when a 24 px circle on its centre touches no other target. A control
  // inside a <label> counts with its label; visually hidden native controls (1-2 px, the custom select) are skipped.
  const box = el => { const lab = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
    return (lab && shown(lab) ? lab : el).getBoundingClientRect(); };
  const targets = [...document.querySelectorAll(controls)].filter(el => shown(el) && !el.classList.contains('skip-link'))
    .map(el => ({ el, r: box(el) })).filter(t => t.r.width > 2 && t.r.height > 2);
  const near = (r, o) => { const cx = r.left + r.width / 2; const cy = r.top + r.height / 2;
    const dx = Math.max(o.left - cx, 0, cx - o.right); const dy = Math.max(o.top - cy, 0, cy - o.bottom);
    return Math.hypot(dx, dy) < 12; };
  for (const t of targets) {
    const { el, r } = t;
    if (inSentence(el) || (r.width >= 23.5 && r.height >= 23.5)) continue;
    const crowded = targets.some(o => o !== t && !o.el.contains(el) && !el.contains(o.el) && near(r, o.r));
    if (crowded) out.push(`target ${Math.round(r.width)}x${Math.round(r.height)} px under 24x24 with another target too close: ${label(el)}`);
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

async function run(root, pages) {
  const { chromium } = playwright();
  const srv = await serve(root);
  const base = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch();
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
const SELFTEST = ['sideways', 'target', 'focus mark', 'reduced motion', 'contrast', 'console error'];

(async () => {
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
  console.log(`ux checks ok: ${PAGES.join(', ')} at ${WIDTHS.join('/')} px, focus, reduced motion, contrast`);
})().catch(e => { console.error(e); process.exit(1); });
