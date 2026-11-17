// The list of dashboard features, read from the code (never typed by hand), and which click-through claims each.
//
// A feature is:
//   - an action the page can send: an op name of the server's action table (actions.py OPS, MOBILE_OPS, LOOK_OPS
//     and the ops actions.py/server.py answer by name) that the page code (web/**/*.js) really names, and
//   - a page of the dashboard: a kind the router (web/app.js pageRoute) returns, and each Settings tab.
// A new button that sends a new op, or a new page, lands on this list by itself. features/*.cjs claim features in
// `covers`; tests/clickthrough_catalogue.test.js (the `dashboard` CI job) fails when a feature has no claim, and
// run.cjs (the `page-smoke` CI job) fails when a click-through claims a feature it never really did.
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const DASH = path.join(__dirname, '..');
const SRC = path.join(DASH, 'src', 'orch_dashboard');
const WEB = path.join(SRC, 'web');
const FEATURES = path.join(__dirname, 'features');

// Router kinds that are not a page of their own: `page`, `addon` and `live` show an add-on's own page in a frame
// (each add-on tests its page itself, e.g. e2e/focus_insights_smoke.cjs).
const ADDON_FRAMES = new Set(['page', 'addon', 'live']);

const read = f => fs.readFileSync(f, 'utf8');
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);

/** Every op the server answers by name. */
function serverOps() {
  const ops = new Set();
  for (const f of ['actions.py', 'mobile.py', 'look.py']) {
    const s = read(path.join(SRC, f));
    for (const m of s.matchAll(/^(?:OPS|MOBILE_OPS|LOOK_OPS)\s*=\s*\{([\s\S]*?)^\}/gm)) {
      for (const k of m[1].matchAll(/^\s*"([a-z][a-z0-9_.-]*)":/gm)) ops.add(k[1]);
    }
  }
  const acts = read(path.join(SRC, 'actions.py'));
  for (const m of acts.matchAll(/op == "([a-z][a-z0-9_.-]*)"/g)) ops.add(m[1]);
  for (const m of acts.matchAll(/op in \(([^)]*)\)/g)) for (const k of m[1].matchAll(/"([a-z][a-z0-9_.-]*)"/g)) ops.add(k[1]);
  const srv = read(path.join(SRC, 'server.py'));
  for (const m of srv.matchAll(/body\.get\("op"\) == "([a-z][a-z0-9_.-]*)"/g)) ops.add(m[1]);
  return ops;
}

/** The ops the page code names (a quoted op name anywhere in web/**.js): the actions a person can trigger. */
function pageOps() {
  const web = walk(WEB).filter(f => f.endsWith('.js')).map(read).join('\n');
  return [...serverOps()].filter(op => new RegExp(`['"\`]${op.replace(/[.]/g, '\\.')}['"\`]`).test(web)).sort();
}

/** The dashboard's pages: router kinds (minus add-on frames) and Settings tabs, as `page:<kind>` / `page:settings/<tab>`. */
function pages() {
  const app = read(path.join(WEB, 'app.js'));
  const fn = /function pageRoute\(\)[\s\S]*?\n\}/.exec(app);
  if (!fn) throw new Error('pageRoute() not found in web/app.js: update clickthrough/catalogue.cjs');
  const kinds = new Set([...fn[0].matchAll(/kind:\s*'([a-z]+)'/g), ...fn[0].matchAll(/'#[a-z]+':'([a-z]+)'/g)].map(m => m[1]));
  const tabs = /#settings\(\?:\\\/\(([a-z|]+)/.exec(fn[0]);
  if (!tabs) throw new Error('the Settings tab list in pageRoute() changed: update clickthrough/catalogue.cjs');
  const alias = /\{(helper:'[a-z]+'(?:,\s*[a-z]+:'[a-z]+')*)\}/.exec(fn[0]);
  const aliased = new Set(alias ? [...alias[1].matchAll(/([a-z]+):'/g)].map(m => m[1]) : []);
  const out = [...kinds].filter(k => !ADDON_FRAMES.has(k) && k !== 'settings').map(k => `page:${k}`);
  for (const t of tabs[1].split('|')) if (!aliased.has(t)) out.push(`page:settings/${t}`);
  return out.sort();
}

/** Every feature: ops first, then pages. */
function features() { return [...pageOps(), ...pages()]; }

/** The click-through files: [{file, name, covers, ...}]. */
function clickthroughs() {
  return fs.readdirSync(FEATURES).filter(f => f.endsWith('.cjs')).sort().map(f => ({ file: f, ...require(path.join(FEATURES, f)) }));
}

/** {missing: features no click-through claims, unknown: claims that are no feature (renamed or gone)}. */
function coverage() {
  const all = new Set(features());
  const claimed = new Map();
  for (const c of clickthroughs()) for (const k of c.covers || []) claimed.set(k, [...(claimed.get(k) || []), c.file]);
  return {
    features: [...all],
    missing: [...all].filter(k => !claimed.has(k)),
    unknown: [...claimed.keys()].filter(k => !all.has(k)).map(k => `${k} (${claimed.get(k).join(', ')})`),
  };
}

module.exports = { serverOps, pageOps, pages, features, clickthroughs, coverage, FEATURES };

if (require.main === module) {
  const c = coverage();
  console.log(`${c.features.length} dashboard features, ${c.features.length - c.missing.length} with a click-through.`);
  if (c.missing.length) console.log('No click-through yet:\n' + c.missing.map(k => '  - ' + k).join('\n'));
  if (c.unknown.length) console.log('Claimed but no longer a feature:\n' + c.unknown.map(k => '  - ' + k).join('\n'));
}
