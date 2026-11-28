// Soft page changes (ORCH-336): wherever Focus runs, links to this dashboard page change the address instead of loading
// the page again, a dialog in the keep place survives a page change, Back and Forward land where the person was, and a
// page that cannot be drawn loads once the normal way. In a shared copy (no Focus) nothing changes.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const softSource = fs.readFileSync(path.join(WEB, 'pages/soft.js'), 'utf8');
const app = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

function load(focus = true, extra = {}) {
  const listeners = {};
  const keep = {contains: n => n.inKeep === true};
  const ctx = {
    liveFocusOn: () => focus, URL, Map, JSON, Date, CustomEvent: class { constructor(type, o) { this.type = type; this.detail = o.detail; } },
    requestAnimationFrame: fn => fn(),
    document: {getElementById: id => (id === 'keep' ? keep : null), querySelectorAll: () => extra.dialogs || [], addEventListener: (t, fn) => { listeners['doc:' + t] = fn; }},
    history: extra.history || {state:null, replaceState(s) { this.state = s; }},
    location: {href:'http://127.0.0.1:8781/#home', origin:'http://127.0.0.1:8781', pathname:'/', search:'', hash:'#home', reload() { ctx.reloaded = (ctx.reloaded || 0) + 1; }},
    sessionStorage: extra.store || new Map(),
    scrollX: 0, scrollY: 0, ...extra,
  };
  ctx.window = ctx;
  ctx.addEventListener = (t, fn) => { listeners['win:' + t] = fn; };
  ctx.dispatchEvent = e => { (ctx.events = ctx.events || []).push(e); };
  if (ctx.sessionStorage instanceof Map) { const m = ctx.sessionStorage; ctx.sessionStorage = {getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v)}; }
  vm.createContext(ctx);
  vm.runInContext(softSource + '\nthis.SoftNav = SoftNav;', ctx);
  return {ctx, soft: ctx.SoftNav, listeners, keep};
}
const anchor = (href, attrs = {}) => ({getAttribute: k => (k === 'href' ? href : attrs[k] ?? null), hasAttribute: k => k in attrs});
const click = (mods = {}) => ({button:0, defaultPrevented:false, ...mods});

test('a link to this same dashboard page goes softly to its address; everything else stays the browser\'s', () => {
  const {soft, ctx} = load();
  const at = href => soft.softHash(click(), anchor(href), ctx.location);
  assert.equal(at('/#tickets'), '#tickets');
  assert.equal(at('/'), '#home', 'the bare page is Home');
  assert.equal(at('/index.html#review'), '#review');
  assert.equal(at('http://127.0.0.1:8781/#ticket/t_abc'), '#ticket/t_abc');
  assert.equal(at('#tickets'), null, 'a plain #address is soft already');
  assert.equal(at('/styleguide/'), null, 'another page of this server loads normally');
  assert.equal(at('/addon/focus/'), null);
  assert.equal(at('/?x=1#home'), null, 'another query is another page');
  assert.equal(at('https://github.com/x/y'), null, 'another site');
  assert.equal(soft.softHash(click(), anchor('/#tickets', {target:'_blank'}), ctx.location), null, 'a new tab');
  assert.equal(soft.softHash(click(), anchor('/#tickets', {download:''}), ctx.location), null, 'a download');
  for (const mod of [{metaKey:true}, {ctrlKey:true}, {shiftKey:true}, {altKey:true}, {button:1}, {defaultPrevented:true}]) {
    assert.equal(soft.softHash(click(mod), anchor('/#tickets'), ctx.location), null, JSON.stringify(mod) + ' stays the browser\'s');
  }
});

test('the click handler acts only where Focus runs', () => {
  for (const focus of [true, false]) {
    const {ctx, listeners} = load(focus);
    let prevented = false;
    const a = anchor('/#tickets');
    listeners['doc:click']({...click(), target:{closest: () => a}, preventDefault() { prevented = true; }});
    assert.equal(prevented, focus);
    assert.equal(ctx.location.hash, focus ? '#tickets' : '#home');
  }
});

test('a page change closes the open dialogs except the ones in the keep place, and only where Focus runs', () => {
  const modal = {id:'modal'}, layer = {id:'layer', inKeep:true};
  const on = load(true, {dialogs:[modal, layer]});
  assert.deepEqual([...on.soft.dialogsToClose().map(d => d.id)], ['modal']);
  const off = load(false, {dialogs:[modal, layer]});
  assert.deepEqual([...off.soft.dialogsToClose().map(d => d.id)], ['modal', 'layer'], 'a shared copy: every dialog closes');
});

test('Back and Forward land where the person was; a new page starts at the top', () => {
  const hist = {state:null, replaceState(s) { this.state = s; }};
  const {soft, ctx} = load(true, {history:hist});
  ctx.scrollY = 640; soft.remember();
  const first = hist.state.softNav;
  assert.ok(first, 'the entry got its own name');
  hist.state = null;  // a new entry (a link): the top
  assert.deepEqual([...soft.scrollAfterChange()], [0, 0]);
  soft.hold(true); ctx.scrollY = 5; soft.remember(); soft.hold(false);
  assert.equal(hist.state, null, 'a scroll while the page changes belongs to no entry');
  hist.state = {softNav:first};  // Back
  assert.deepEqual([...soft.scrollAfterChange()], [0, 640]);
  const off = load(false, {history:{state:{softNav:first}, replaceState() {}}});
  assert.deepEqual([...off.soft.scrollAfterChange()], [0, 0], 'a shared copy: the top');
});

test('a page that cannot be drawn loads once the normal way, never in a loop, never in a shared copy', () => {
  const store = new Map();
  const {soft, ctx} = load(true, {store});
  assert.equal(soft.fallBack('#tickets', ctx.sessionStorage, ctx.location, 1000), true);
  assert.equal(ctx.reloaded, 1);
  assert.equal(soft.fallBack('#tickets', ctx.sessionStorage, ctx.location, 30000), false, 'the same address again within a minute');
  assert.equal(ctx.reloaded, 1);
  assert.equal(soft.fallBack('#tickets', ctx.sessionStorage, ctx.location, 70000), true, 'a minute later it may try again');
  const off = load(false);
  assert.equal(off.soft.fallBack('#tickets', off.ctx.sessionStorage, off.ctx.location, 1000), false);
  assert.equal(off.ctx.reloaded, undefined);
});

test('every page change is said once as orch:page with from, to and kind', () => {
  const {soft, ctx} = load();
  soft.said('#home', '#tickets', 'tickets');
  assert.equal(ctx.events.length, 1);
  assert.equal(ctx.events[0].type, 'orch:page');
  assert.deepEqual({...ctx.events[0].detail}, {from:'#home', to:'#tickets', kind:'tickets'});
});

test('the keep place sits outside <main> and the page, and window.orchKeep mounts into it', () => {
  assert.match(index, /<div class="shell-body">[\s\S]*<\/main>\s*<div id="keep" data-keep><\/div>\s*<\/div>/, 'one keep place right after main in the page column, outside main');
  assert.equal((index.match(/id="keep"/g) || []).length, 1);
  assert.ok(index.indexOf('pages/soft.js') > index.indexOf('pages/live.js') && index.indexOf('pages/soft.js') < index.indexOf('src="app.js"'));
  const {ctx, keep} = load();
  const kids = [];
  keep.append = n => { kids.push(n); n.parentNode = keep; };
  const node = {parentNode:null};
  assert.equal(ctx.orchKeep.mount(node), node);
  ctx.orchKeep.mount(node);
  assert.deepEqual(kids, [node], 'mounting twice keeps one copy');
  assert.equal(ctx.orchKeep.el(), keep);
});

test('the router uses it: dialogs, scroll, the page-change event and the fallback go through SoftNav', () => {
  const hashchange = app.slice(app.indexOf("window.addEventListener('hashchange'"), app.indexOf('// Prefetch: resting'));
  assert.match(hashchange, /soft\.dialogsToClose\(\)/);
  assert.match(hashchange, /soft\?\.hold\(true\)/);
  const render = app.slice(app.indexOf('function render('), app.indexOf("document.addEventListener('pointerover'"));
  assert.match(render, /SoftNav\.fallBack\(r\.hash\)/);
  assert.match(render, /soft\.scrollAfterChange\(\)/);
  assert.match(render, /soft\.said\(/);
  assert.doesNotMatch(render, /getElementById\('keep'\)/, 'render never draws the keep place');
});

test('many page changes keep only the last places, not one per change forever (ORCH-340)', () => {
  const {soft, ctx} = load();
  for (let i = 0; i < soft.KEEP_SCROLLS + 50; i++) { ctx.history.state = {softNav:'e' + i}; ctx.scrollY = i; soft.remember(); }
  assert.equal(soft.scrolls.size, soft.KEEP_SCROLLS);
  assert.equal(soft.scrolls.has('e0'), false, 'the oldest place went first');
  assert.deepEqual([...soft.scrolls.get('e' + (soft.KEEP_SCROLLS + 49))], [0, soft.KEEP_SCROLLS + 49]);
  ctx.history.state = {softNav:'e50'}; ctx.scrollY = 7; soft.remember();
  ctx.history.state = {softNav:'new'}; soft.remember();
  assert.equal(soft.scrolls.has('e50'), true, 'a place used again counts as new');
});

test('a page change always lets scrolls be remembered again, even when the page was not drawn yet', () => {
  assert.match(app, /render\(\);\n {2}soft\?\.hold\(false\);/);
});

test('a new page takes the keyboard place at its heading and says its title once (#1350)', () => {
  const {soft} = load(false);  // also without Focus: every dashboard page change
  const live = {textContent:'old'};
  const doc = {getElementById: id => (id === 'page-said' ? live : null)};
  const h1 = {attrs:{}, hasAttribute(k) { return k in this.attrs; }, setAttribute(k, v) { this.attrs[k] = v; }, focus(o) { this.focused = o; }};
  const main = {querySelector: s => (s === 'h1' ? h1 : null), focus(o) { this.focused = o; }};
  assert.equal(soft.arrive(main, 'Tickets', doc), h1);
  assert.equal(h1.focused.preventScroll, true, 'focus without a jump: the scroll is set after');
  assert.equal(h1.attrs.tabindex, '-1', 'a heading can take focus but stays out of the Tab order');
  assert.equal(live.textContent, 'Tickets');
  const bare = {querySelector: () => null, focus(o) { this.focused = o; }};
  assert.equal(soft.arrive(bare, 'Chat', doc), bare, 'no heading yet: <main> takes the focus');
  assert.equal(live.textContent, 'Chat');
  assert.equal(soft.arrive(null, 'x', doc), null);
});

test('the router moves focus on a page change of another kind or when the focus went with the old page', () => {
  const render = app.slice(app.indexOf('function render('), app.indexOf("document.addEventListener('pointerover'"));
  assert.match(render, /changed && !document\.querySelector\('dialog\[open\]'\) && \(r\.kind !== renderedKind \|\| lost\)\) soft\.arrive\(main, title\)/);
  assert.match(index, /<p id="page-said" class="sr-only" role="status" aria-live="polite"><\/p>\s*<main id="content"/, 'one polite status line outside <main>, so a redraw never clears it');
});
