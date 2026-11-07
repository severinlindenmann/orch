import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { lintText } from './lint.mjs';

const CONTROL = 'button, a[href], input, select, textarea, [role=switch], [role=tab], [role=button], summary';
const firstLine = e => String(e?.message || e).split('\n')[0];
const height = w => w === 390 ? 844 : w === 720 ? 900 : 800;
// This function runs in the page for both census and action attribution.
function describe(el, pageName) {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute('role') || ({ a: 'link', button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button' }[tag]) || (tag === 'input' ? ({ checkbox: 'checkbox', radio: 'radio', button: 'button', submit: 'button' }[el.type] || 'textbox') : tag);
  const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ');
  const name = clean(labelled || el.getAttribute('aria-label') || Array.from(el.labels || []).map(x => x.textContent).join(' ') || (tag === 'input' && ['submit', 'button'].includes(el.type) ? el.value : '') || (tag === 'input' || tag === 'textarea' || tag === 'select' ? '' : el.innerText) || el.querySelector('img[alt]')?.getAttribute('alt') || el.getAttribute('title'));
  const fallback = clean(el.getAttribute('placeholder') || el.id || (el.href ? new URL(el.href, location.href).pathname : ''));
  const norm = (name || fallback).split(' · ')[0].split(';')[0].split(': ')[0].replace(/\d{3,}/g, '#').replace(/ \d+$/, '').slice(0, 60);
  return { key: `${pageName}|${role}|${norm}`, role, name, unnamed: !name, href: tag === 'a' ? el.href : null };
}
function substitute(value, env) {
  if (typeof value === 'string') return value.replace(/\{\{([^}]+)\}\}/g, (_, key) => {
    const v = key.startsWith('url:') ? env.urls[key.slice(4)] : env.vars?.[key];
    if (v === undefined) throw new Error(`Unknown variable: ${key}`);
    return String(v);
  });
  if (Array.isArray(value)) return value.map(v => substitute(v, env));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, env)]));
  return value;
}
export function parseArgs(args) {
  const opts = {};
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (key === '--census-only') opts.censusOnly = true;
    else if (['--lane', '--env', '--out', '--only', '--viewports'].includes(key) && args[i + 1] && !args[i + 1].startsWith('--')) opts[key.slice(2)] = args[++i];
    else throw new Error(`Invalid argument: ${key}`);
  }
  if (!opts.lane || !opts.env || !opts.out) throw new Error('--lane, --env and --out are required');
  return opts;
}
export async function run(opts) {
  const start = Date.now();
  const lane = JSON.parse(await readFile(opts.lane, 'utf8'));
  const env = JSON.parse(await readFile(opts.env, 'utf8'));
  if (!lane.lane || !Array.isArray(lane.steps) || !env.urls?.[lane.base]) throw new Error('Invalid lane or environment');
  env.vars = { stamp: String(Date.now()).slice(-6), ...(env.vars || {}) };
  const base = new URL(env.urls[lane.base]);
  const widths = opts.viewports ? opts.viewports.split(',').map(Number) : lane.viewports || [1280, 720, 390];
  if (!widths.length || widths.some(w => !Number.isInteger(w) || w < 1)) throw new Error('Invalid viewports');
  const ids = new Set(lane.steps.map(s => s.id));
  if (ids.size !== lane.steps.length || [...ids].some(id => !/^[\w-]+$/.test(id))) throw new Error('Step IDs must be unique safe filenames');
  const only = opts.only ? opts.only.split(',') : null;
  if (only?.some(id => !ids.has(id))) throw new Error('Unknown --only step');
  const steps = lane.steps.filter(s => !only || only.includes(s.id)).map(s => ({ ...s, actions: s.actions || [] }));
  const out = resolve(opts.out);
  await mkdir(join(out, 'shots'), { recursive: true });
  const result = { lane: lane.lane, started: new Date(start).toISOString(), ms: 0, steps: [], census: {}, coverage: {} };
  const unclickable = new Set(), covered = new Set(), patterns = new Set(), skipped = new Set();
  const skipRegexes = (lane.census_skip || []).map(x => new RegExp(x, 'i'));
  const allowedOrigins = new Set(Object.values(env.urls).map(u => new URL(u).origin));
  const browser = await chromium.launch({ headless: true });
  let context, current, blocked;
  try {
    context = await browser.newContext({ viewport: { width: widths[0], height: height(widths[0]) }, ignoreHTTPSErrors: true, serviceWorkers: 'block', extraHTTPHeaders: env.headers?.[lane.base] || {} });
    await context.route('**/*', route => allowedOrigins.has(new URL(route.request().url()).origin) ? route.continue() : route.abort('blockedbyclient'));
    await context.addInitScript(() => window.addEventListener('unhandledrejection', e => console.error(`Unhandled rejection: ${String(e.reason)}`)));
    // Playwright traces store typed values (admin keys): only with STEPPER_TRACE=1, never in an unattended run
    if (process.env.STEPPER_TRACE) await context.tracing.start({ screenshots: true, snapshots: false, sources: false });
    const page = await context.newPage();
    page.on('dialog', dialog => dialog.dismiss().catch(() => {}));
    page.on('console', msg => { if (current && msg.type() === 'error' && !current.expected.console.some(s => msg.text().includes(s))) current.console.push(msg.text()); });
    page.on('pageerror', e => { if (current && !current.expected.console.some(s => e.message.includes(s))) current.console.push(e.message); });
    page.on('response', r => { if (current && r.status() >= 400 && !current.expected.http.some(s => r.url().includes(s))) current.http_errors.push({ method: r.request().method(), url: r.url(), status: r.status() }); });
    page.on('requestfailed', r => { if (current && r.failure()?.errorText !== 'net::ERR_ABORTED' && !current.expected.http.some(s => r.url().includes(s))) current.http_errors.push({ method: r.method(), url: r.url(), status: null, error: r.failure()?.errorText }); });
    const locator = (sel, frame) => { const root = frame ? page.frameLocator(frame) : page; return sel.startsWith('label=') ? root.getByLabel(sel.slice(6)) : root.locator(sel); };
    const ck = k => k.slice(k.indexOf('|') + 1);
    const isCovered = key => covered.has(ck(key)) || [...patterns].some(p => p.endsWith('|*') ? key.startsWith(p.slice(0, -1)) : p === key);
    async function census(pageName, id) {
      const items = [];
      // while a dialog is open only its own controls count (a click behind it would close it)
      const modal = page.locator('dialog[open], [role=dialog], [aria-modal=true]').filter({ visible: true }).first();
      const scope = (await modal.count()) ? modal.locator(CONTROL) : page.locator(CONTROL);
      for (const el of await scope.all()) {
        if (!await el.isVisible()) continue;
        const item = await el.evaluate(describe, pageName);
        const map = result.census[pageName] ||= {};
        const entry = map[item.key] ||= { role: item.role, name: item.name, visible_in_steps: [], ...(item.unnamed ? { unnamed: true } : {}) };
        if (!entry.visible_in_steps.includes(id)) entry.visible_in_steps.push(id);
        entry.clicked = isCovered(item.key);
        items.push({ ...item, el });
      }
      return items;
    }
    async function clickCensus(pageName, step, timeout) {
      for (let pass = 0; pass < 3; pass++) {
        const before = covered.size + unclickable.size;
        await clickCensusOnce(pageName, step, timeout);
        if (covered.size + unclickable.size === before) break;
      }
      if (await modalOpen()) await page.keyboard.press('Escape');  // a dialog a census click opened: close it for the next step
    }
    const settle = async () => { try { await page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})))); await page.waitForTimeout(150); } catch { /* page navigating */ } };
    const modalOpen = async () => (await page.locator('dialog[open], [role=dialog], [aria-modal=true]').filter({ visible: true }).count()) > 0;
    async function clickCensusOnce(pageName, step, timeout) {
      const items = await census(pageName, step.id);
      const restore = substitute(step.actions.find(a => a.do === 'goto')?.path || page.url(), env);
      for (const item of items) {
        if (process.env.STEPPER_DEBUG) console.error('census', pageName, item.key, isCovered(item.key) ? 'covered' : 'todo');
        if (isCovered(item.key)) continue;
        if (/\b(delete|remove|sign out|reset|stop|wipe|leave|disconnect)\b/i.test(item.name) || skipRegexes.some(r => r.test(item.key)) || (item.href && new URL(item.href).origin !== base.origin)) { skipped.add(item.key); continue; }
        // Resolve again after navigation, since earlier locator indexes may have changed.
        const fresh = (await census(pageName, step.id)).find(x => x.key === item.key);
        if (!fresh) { if (process.env.STEPPER_DEBUG) console.error('  vanished', item.key); continue; }
        const before = page.url();
        try { await fresh.el.click({ timeout: Math.min(timeout, 2500) }); covered.add(ck(item.key)); } catch (e) {
          try { await fresh.el.click({ timeout: 1500, force: true }); covered.add(ck(item.key)); } catch (e2) { unclickable.add(ck(item.key)); if (!(await modalOpen())) await page.keyboard.press('Escape'); continue; }
        }
        if (!(await modalOpen())) await page.keyboard.press('Escape');
        if (page.url() !== before) await page.goto(new URL(restore, base).href, { waitUntil: 'domcontentloaded', timeout });
      }
    }
    async function action(a, step, record) {
      const timeout = a.timeout ?? 5000;
      page.setDefaultTimeout(timeout); page.setDefaultNavigationTimeout(timeout);
      let el = a.sel ? locator(a.sel, a.frame) : null, key;
      if (['click', 'fill', 'select', 'check', 'press', 'hover'].includes(a.do)) {
        if (!el && a.do === 'press') el = page.locator(':focus');
        if (el && await el.count()) key = (await el.first().evaluate(describe, step.page || '')).key;
      }
      switch (a.do) {
        case 'goto': {
          try { await page.goto(new URL(a.path, base).href, { waitUntil: 'domcontentloaded', timeout }); }
          catch (e) { if (/net::ERR_|NS_ERROR|ECONNREFUSED/.test(String(e))) blocked = `Unreachable goto: ${a.path}: ${firstLine(e)}`; throw e; }
          const t = Date.now(); await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {}); record.load_ms = Date.now() - t; break;
        }
        case 'click': await el.click({ timeout, force: !!a.force }); break;
        case 'fill': await el.fill(a.value, { timeout }); break;
        case 'select': await el.selectOption(a.value, { timeout }); break;
        case 'check': await el.check({ timeout, force: !!a.force }); break;
        case 'hover': await el.hover({ timeout }); break;
        case 'press': if (a.sel) await el.press(a.key, { timeout }); else await page.keyboard.press(a.key); break;
        case 'wait': await page.waitForTimeout(a.ms); break;
        case 'wait_for': await el.waitFor({ state: a.state || 'visible', timeout }); break;
        case 'expect_visible': await el.waitFor({ state: 'visible', timeout }); break;
        case 'expect_text': await (a.frame ? page.frameLocator(a.frame) : page).getByText(a.text, { exact: false }).filter({ visible: true }).first().waitFor({ state: 'visible', timeout }); break;
        case 'expect_no_text': await page.waitForFunction(t => !document.body.innerText.includes(t), a.text, { timeout }); break;
        case 'expect_url': await page.waitForURL(u => u.href.includes(a.contains), { timeout }); break;
        case 'reload': await page.reload({ waitUntil: 'domcontentloaded', timeout }); break;
        case 'back': await page.goBack({ waitUntil: 'domcontentloaded', timeout }); break;
        case 'eval': {
          const value = await page.evaluate(a.js);
          if (a.store) (env.vars ||= {})[a.store] = value;
          if (a.expect_contains !== undefined && !String(value).includes(a.expect_contains)) throw new Error(`eval did not contain ${a.expect_contains}`);
          break;
        }
        case 'shell': { const { execFileSync } = await import('node:child_process'); execFileSync(a.cmd, a.args || [], { timeout: 30000, stdio: 'pipe' }); break; }  // trusted lane files only: the harness writes the commands (env.json vars) it allows
        case 'shot': await shot(step, page.viewportSize().width); break;
        case 'expect_status': {
          const url = new URL(a.path, base);
          if (!allowedOrigins.has(url.origin)) throw new Error(`URL outside environment: ${url.origin}`);
          const r = await context.request.fetch(url.href, { method: a.method || 'GET', headers: a.headers, data: a.body, timeout, maxRedirects: 0 });
          const status = r.status(); await r.dispose();
          if (!(Array.isArray(a.status) ? a.status : [a.status]).includes(status)) throw new Error(`Unexpected HTTP status ${status}`);
          break;
        }
        case 'click_all_census': await clickCensus(a.page || step.page, step, timeout); break;
        default: throw new Error(`Unknown action: ${a.do}`);
      }
      if (key) covered.add(ck(key));
      for (const p of a.covers ? [].concat(a.covers) : []) { patterns.add(p); if (!p.endsWith('|*')) covered.add(p.split('|').slice(-2).join('|')); }
    }
    async function shot(step, width) {
      if (step.noshot) return;
      const file = `shots/${step.id}-${current.shots.length + 1}-${width}.png`;
      await page.screenshot({ path: join(out, file), fullPage: true, timeout: 5000 });
      current.shots.push({ vp: width, file, hscroll: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1) });
    }
    if (opts.censusOnly) {
      await page.goto(new URL('/', base).href, { waitUntil: 'domcontentloaded' });
      const links = await page.locator('nav a[href], [role=navigation] a[href], header a[href]').evaluateAll(els => els.map(e => ({ href: e.href, name: e.innerText.trim() })));
      const destinations = [{ href: new URL('/', base).href, name: 'home' }, ...links.filter(l => new URL(l.href).origin === base.origin)];
      await mkdir(join(out, 'census'), { recursive: true });
      const visited = new Set();
      for (const dest of destinations) {
        if (visited.has(dest.href)) continue;
        visited.add(dest.href);
        await page.goto(dest.href, { waitUntil: 'domcontentloaded' });
        const name = dest.name || new URL(dest.href).pathname;
        await census(name, 'census');
        await writeFile(join(out, 'census', `${encodeURIComponent(name)}.json`), JSON.stringify(result.census[name], null, 2));
      }
    } else for (const step of steps) {
      const t = Date.now();
      const entry = { id: step.id, name: step.name || '', status: 'pass', error: '', ms: 0, actions: [], shots: [], console: [], http_errors: [], axe: [], lint: [], unnamed_controls: [], page: step.page };
      result.steps.push(entry);
      if (blocked) { entry.status = 'blocked'; entry.error = blocked; continue; }
      current = entry; current.expected = { http: step.expect_errors?.http || [], console: step.expect_errors?.console || [] };
      const attempts = [];
      for (let attempt = 0; attempt <= Math.min(step.retry || 0, 1); attempt++) {
        let failure = '';
        const consoleStart = entry.console.length, httpStart = entry.http_errors.length;
        try {
          for (const a of step.actions) {
            const at = Date.now(), record = { do: a.do, ...(a.sel ? { sel: a.sel } : {}), ms: 0, load_ms: null, status: 'ok', error: '' };
            entry.actions.push(record);
            try { await action(substitute(a, env), step, record); }
            catch (e) { record.status = a.optional ? 'skip' : 'fail'; record.error = firstLine(e); if (!a.optional) failure ||= record.error; }
            finally { record.ms = Date.now() - at; }
            if (blocked) break;
          }
          await page.setViewportSize({ width: widths[0], height: height(widths[0]) });
          const lintInput = await page.evaluate(() => {
            const clone = document.body.cloneNode(true);
            const original = [document.body, ...document.body.querySelectorAll('*')];
            const copied = [clone, ...clone.querySelectorAll('*')];
            original.forEach((el, i) => { if (getComputedStyle(el).display === 'none' || getComputedStyle(el).visibility === 'hidden') copied[i].remove(); });
            clone.querySelectorAll('[data-user-content], .agent-text, pre, code, textarea, input').forEach(el => el.remove());
            clone.style.position = 'fixed'; clone.style.left = '-100000px'; document.body.appendChild(clone);
            const text = clone.innerText; clone.remove(); return text;
          });
          entry.lint = lintText(lintInput, { allow: step.lint_allow || lane.lint_allow || [] });
          await settle();  // page fade-in animations make axe see half-transparent text
          const axe = await new AxeBuilder({ page }).analyze();
          entry.axe = axe.violations.filter(v => ['serious', 'critical'].includes(v.impact) && !(step.allow_axe || []).includes(v.id)).map(v => ({ id: v.id, impact: v.impact, help: v.help, count: v.nodes.length, selector: v.nodes[0]?.target?.[0] }));
          if (lane.axe_fail && entry.axe.length) failure ||= 'Accessibility violations';
          for (const width of widths) { await page.setViewportSize({ width, height: height(width) }); await page.waitForTimeout(250); await settle(); await shot(step, width); }
          await page.setViewportSize({ width: widths[0], height: height(widths[0]) });
          await page.waitForTimeout(250);
          await shot(step, widths[0]);
        } catch (e) { failure ||= firstLine(e); }
        try {
          await page.setViewportSize({ width: widths[0], height: height(widths[0]) });
          if (step.page) entry.unnamed_controls = (await census(step.page, step.id)).filter(x => x.unnamed).map(({ el, ...x }) => x);
        } catch (e) { failure ||= firstLine(e); }
        if (entry.console.length > consoleStart || entry.http_errors.length > httpStart) failure ||= 'Unexpected browser errors';
        attempts.push({ status: failure ? 'fail' : 'pass', error: failure });
        entry.error = attempts.find(a => a.error)?.error || '';
        entry.status = failure ? 'fail' : attempt ? 'flaky' : entry.actions.every(a => a.status === 'skip') && entry.actions.length ? 'skipped' : 'pass';
        if (!failure || blocked) break;
      }
      if (attempts.length > 1) entry.attempts = attempts;
      entry.ms = Date.now() - t; delete entry.expected; current = null;
    }
    const allKeys = [...new Set(Object.values(result.census).flatMap(map => Object.keys(map)).map(ck))];
    const allowlisted = allKeys.filter(k => skipRegexes.some(r => r.test('x|' + k)));
    const keys = allKeys.filter(k => !allowlisted.includes(k) && ![...skipped].some(x => ck(x) === k));
    for (const map of Object.values(result.census)) for (const [key, value] of Object.entries(map)) value.clicked = isCovered(key);
    const clicked = keys.filter(k => covered.has(k) || isCovered('x|' + k)).length;
    result.coverage = opts.censusOnly ? { found: keys.length } : { found: keys.length, clicked, percent: keys.length ? 100 * clicked / keys.length : 100, uncovered: keys.filter(k => !(covered.has(k) || isCovered('x|' + k))), skipped_destructive: [...new Set([...skipped].map(ck))], unclickable: [...unclickable], allowlisted };
  } finally {
    if (context) await (process.env.STEPPER_TRACE ? context.tracing.stop({ path: join(out, 'trace.zip') }) : Promise.resolve()).finally(() => browser.close());
    else await browser.close();
  }
  result.ms = Date.now() - start;
  await writeFile(join(out, 'result.json'), JSON.stringify(result, null, 2));
  return result;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  Promise.resolve().then(() => run(parseArgs(process.argv.slice(2)))).catch(e => { console.error(firstLine(e)); process.exitCode = 2; });
}
