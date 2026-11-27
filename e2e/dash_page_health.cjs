// Page health (ORCH-80; ORCH-310 adds tap size and the one-row top bar; CI job page-smoke runs it on every pull request): every main dashboard page at 1280, 1920, 390 and 320 px and at 150% zoom (960x600), on fake
// data, before a release.
// The same checks the daily Dashboard tester role runs on the real workspace: no page error, the page shows its
// content (the loading shape goes away), nothing scrolls sideways at phone width, no button or link is cut off at
// the right edge, no word from the never-list (docs/wording.md) on buttons, tabs, headings or labels, and no program
// value (undefined, NaN, null, [object Object]) in the page text. At phone width the open menu (More) is checked too:
// top-bar items do not overlap and every menu row can be scrolled above the bottom bar; at 150% zoom the icon rail
// does not draw its list under its foot (report r-1117-1256-ws-2). The state is the crowded case: a development build,
// phone mode on, a full add-on list and a result with a Done-when part that has no task.
// Real dashboard web files in Chromium (own browser, mock keychain), every request answered in memory.
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_page_health.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-page-health');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const VIEW = path.join(__dirname, '..', 'contracts', 'examples', 'addon-view', 'valid-lessons-page.json');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

const WIDTHS = [{name: 'desktop', width: 1280, height: 800}, {name: 'wide', width: 1920, height: 1080}, {name: 'phone', width: 390, height: 844},
  {name: 'small phone', width: 320, height: 700}, {name: 'zoom 150%', width: 960, height: 600}].map(v => ({...v, label: `${v.name} ${v.width}px`}));
// Smallest tap target at phone width, in CSS px (the master --touch size; WCAG 2.5.8 asks 24 x 24).
const TAP_MIN = 44;
const PHONE = vp => vp.width <= 720;
// The never-list comes from its one source, docs/wording.md (last column of the table). Entries that only make sense
// in a sentence (with a note in brackets, quotes or a placeholder) are left to the wording test in brand/.
const WORDING = path.join(__dirname, '..', 'docs', 'wording.md');
function neverList() {
  const words = new Set();
  for (const line of fs.readFileSync(WORDING, 'utf8').split('\n')) {
    const cells = line.split('|').map(c => c.trim());
    if (cells.length < 6 || !cells[1] || /^-+$/.test(cells[1]) || cells[1] === 'Thing') continue;
    for (const w of cells[cells.length - 2].split(',').map(x => x.trim())) {
      if (w && !/[()"'<>`]/.test(w) && w !== '-') words.add(w);
    }
  }
  return [...words];
}
const LEAK = String.raw`\b(undefined|NaN|null)\b|\[object Object\]`;

function pages(state) {
  const by = s => state.tickets.find(t => t.status === s)?.id;
  return ['#home', '#tickets', '#review', '#chat', '#settings', '#settings/agent', '#settings/phone', '#settings/addons', '#settings/about',
    '#ticket/' + by('active'), '#ticket/' + by('review'), '#ticket/' + by('waiting'), '#addon/lessons'];
}

// Runs in the page: what a person would see as broken.
function look({never, leak, phone, tapMin}) {
  const vw = window.innerWidth, out = {tiny: [], rows: 0, sideways: document.documentElement.scrollWidth - vw, cut: [], words: [], leaks: [], text: 0};
  const main = document.querySelector('main');
  out.text = main ? main.innerText.trim().length : 0;
  const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inScroller = el => { for (let q = el.parentElement; q && q !== document.body; q = q.parentElement) { const o = getComputedStyle(q).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  for (const el of document.querySelectorAll('main button, main a, main h1, main h2, main h3, main label, main input, main [role=tab], header button, header a')) {
    if (!shown(el)) continue;
    if (el.getBoundingClientRect().right > vw + 2 && !inScroller(el)) out.cut.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40));
  }
  // The top bar stays on one row: every shown item sits at about the same height.
  const bar = [...document.querySelectorAll('.topbar > *, .topbar-actions > *')].filter(e => !e.matches('.topbar-actions') && shown(e)).map(e => { const r = e.getBoundingClientRect(); return (r.top + r.bottom) / 2; });
  if (bar.length) out.rows = Math.max(...bar) - Math.min(...bar);
  // Tap size at phone width: buttons, tabs and form fields (a link inside running text is exempt, as in WCAG 2.5.8).
  if (phone) for (const el of document.querySelectorAll('main button, main a, main input:not([type=hidden]), main select, main [role=tab], header button, header a, #tabbar button, #tabbar a')) {
    if (!shown(el)) continue;
    if (el.matches('a') && el.closest('p, li, td, dd') && el.parentElement && el.parentElement.childNodes.length > 1 && !el.matches('.btn, [role=button]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 2) continue;  // a native select kept behind its own control
    // a checkbox or radio is tapped through its label or row: that is the target
    if (el.matches('input[type=checkbox], input[type=radio]')) { const t = el.closest('label, li, tr, .row') ; if (t && t.getBoundingClientRect().height >= tapMin) continue; }
    if (r.width < tapMin - 0.5 || r.height < tapMin - 0.5) out.tiny.push(`${(el.innerText || el.getAttribute('aria-label') || el.tagName).trim().replace(/\s+/g, ' ').slice(0, 30)} (${Math.round(r.width)}x${Math.round(r.height)})`);
  }
  const chrome = [...document.querySelectorAll('button, [role=tab], nav a, h1, h2, h3, label, th')].filter(shown).map(e => (e.innerText || '').trim()).filter(Boolean);
  for (const w of never) {
    const re = new RegExp('(^|[^A-Za-z])' + w.replace(/-/g, '\\-') + '([^A-Za-z]|$)');
    const hit = chrome.find(t => re.test(t.replace(/\bSign in\b/g, '')));  // the page login keeps its words (docs/wording.md)
    if (hit) out.words.push(w + ' in "' + hit.slice(0, 60) + '"');
  }
  const re = new RegExp(leak);
  for (const line of (main ? main.innerText : '').split('\n')) if (re.test(line)) out.leaks.push(line.trim().slice(0, 80));
  return out;
}

// Runs in the page with the phone menu open: overlapping top-bar items, menu rows the bottom bar keeps covering.
function menuLook() {
  const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const out = {overlap: [], covered: [], sideways: document.documentElement.scrollWidth - window.innerWidth};
  const top = [...document.querySelectorAll('.topbar > *, .topbar-actions > *')].filter(e => !e.matches('.topbar-actions') && shown(e));
  for (let i = 0; i < top.length; i++) for (let j = i + 1; j < top.length; j++) {
    const a = top[i].getBoundingClientRect(), b = top[j].getBoundingClientRect();
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1)
      out.overlap.push((top[i].innerText || top[i].getAttribute('aria-label') || top[i].id).trim().slice(0, 30) + ' / ' + (top[j].innerText || top[j].getAttribute('aria-label') || top[j].id).trim().slice(0, 30));
  }
  window.scrollTo(0, document.documentElement.scrollHeight);
  const bar = document.getElementById('tabbar')?.getBoundingClientRect().top ?? window.innerHeight;
  for (const el of document.querySelectorAll('.sidebar[data-open=true] :is(a.nav-item, summary.nav-item, .mm-toggle, .person-switch)')) {
    if (shown(el) && el.getBoundingClientRect().bottom > bar + 1) out.covered.push((el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 30));
  }
  window.scrollTo(0, 0);
  return out;
}

// Runs in the page at 150% zoom: the rail list must end above its foot, or scroll.
function railLook() {
  const list = document.querySelector('.sidebar-scroll'), foot = document.querySelector('.side-foot');
  if (!list || !foot || !foot.getClientRects().length) return {under: []};
  const scrolls = ['auto', 'scroll'].includes(getComputedStyle(list).overflowY);
  const top = foot.getBoundingClientRect().top;
  const under = scrolls ? [] : [...list.querySelectorAll('.nav-item')].filter(e => e.getClientRects().length && e.getBoundingClientRect().bottom > top + 1).map(e => e.getAttribute('aria-label') || e.innerText.trim());
  return {under};
}

test('page health: every main page at 1280, 1920 and 390 px', {timeout: 300_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const view = JSON.parse(fs.readFileSync(VIEW, 'utf8'));
  const state = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  state.addons.push({name: 'lessons', dashboard: {label: 'Lessons', icon: 'book', order: 50, title: 'Lessons', subtitle: 'What your helpers learned.'}});
  // the crowded case of report r-1117-1256-ws-2: every add-on in the menu, the build badge, phone mode on, an uncovered Done-when part
  for (const [name, icon] of [['contacts', 'phone'], ['factory', 'pen'], ['focus', 'target'], ['insights', 'chart'], ['sync', 'cloud'], ['publish', 'link']])
    state.addons.push({name, dashboard: name === 'contacts' ? {label: 'Relay', icon, panel: 'phone'} : {label: name[0].toUpperCase() + name.slice(1), icon}});
  state.build = 'development';
  state.mobile_mode = {...state.mobile_mode, on: true, ends_at: new Date(Date.now() + 3 * 3600e3).toISOString()};
  const result = state.tickets.find(t => t.status === 'review');
  result.proof = {...(result.proof || {}), uncovered: ['The owner has approved the result']};
  const never = neverList();
  assert.ok(never.length > 20, 'never-list read from docs/wording.md');
  const problems = [];
  const browser = await headless.launch(chromium);
  try {
    for (const vp of WIDTHS) {
      const context = await browser.newContext({viewport: {width: vp.width, height: vp.height}});
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
        if (url.origin !== BASE) return route.abort();
        if (url.pathname === '/api/state') return json(state);
        if (url.pathname === '/api/addon/lessons') return json({state: 'ok', view});
        if (url.pathname === '/api/act') return json(state);
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
      let here = '';
      page.on('pageerror', e => problems.push(`${vp.label} ${here}: page error ${String(e).slice(0, 120)}`));
      for (const hash of pages(state)) {
        here = hash;
        await page.goto('about:blank');
        await page.goto(BASE + '/' + hash);
        const ready = await page.waitForFunction(() => {
          const m = document.querySelector('main');
          return m && !m.querySelector('.skeleton-page[aria-busy="true"]') && m.innerText.trim().length > 20;
        }, null, {timeout: 15_000}).then(() => true, () => false);
        await page.waitForTimeout(300);
        await page.screenshot({path: path.join(OUT, `${vp.name.replace(/\W+/g, "-")}-${hash.replace(/\W+/g, '-').replace(/^-/, '')}.png`)});
        if (!ready) { problems.push(`${vp.label} ${hash}: shows nothing within 15 s`); continue; }
        const o = await page.evaluate(look, {never, leak: LEAK, phone: PHONE(vp), tapMin: TAP_MIN});
        if (PHONE(vp) && o.sideways > 4) problems.push(`${vp.label} ${hash}: scrolls sideways (${o.sideways} px too wide)`);
        if (o.rows > 12) problems.push(`${vp.label} ${hash}: top bar on two rows (${Math.round(o.rows)} px apart)`);
        for (const t of o.tiny) problems.push(`${vp.label} ${hash}: tap target too small: ${t}`);
        for (const c of o.cut) problems.push(`${vp.label} ${hash}: cut off at the right edge: ${c}`);
        for (const w of o.words) problems.push(`${vp.label} ${hash}: never-list word ${w}`);
        for (const l of o.leaks) problems.push(`${vp.label} ${hash}: program value on screen: ${l}`);
        if (vp.name === 'zoom 150%') for (const n of (await page.evaluate(railLook)).under) problems.push(`${vp.label} ${hash}: menu item under the menu foot: ${n}`);
        if (PHONE(vp) && hash === '#home') {
          await page.click('#tabbar [data-tab="more"]');
          await page.waitForTimeout(300);
          await page.screenshot({path: path.join(OUT, `${vp.name.replace(/\W+/g, '-')}-menu.png`)});
          const m = await page.evaluate(menuLook);
          if (m.sideways > 4) problems.push(`${vp.label} menu: scrolls sideways (${m.sideways} px too wide)`);
          for (const x of m.overlap) problems.push(`${vp.label} menu: top-bar items overlap: ${x}`);
          for (const x of m.covered) problems.push(`${vp.label} menu: behind the bottom bar: ${x}`);
          const report = await page.locator('#report-problem').isVisible();
          if (!report) problems.push(`${vp.label} menu: no Report a problem`);
          await page.click('#tabbar [data-tab="more"]');
        }
      }
      await context.close();
    }
  } finally { await browser.close(); }
  assert.deepEqual([...new Set(problems)], [], 'screenshots in ' + OUT);
});
