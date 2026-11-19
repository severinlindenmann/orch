// The menu before the first state (report r-1118-2330, ORCH-692): right after 'orch start' the first state can take
// seconds on a busy machine, and the menu was empty until then (a walk read only "Home" and "Settings", the brand link
// and the empty Settings landmark). Home, Tickets and Review show at once and the sidebar says it is loading.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');

function slice(name) {
  const start = app.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name + ' is in app.js');
  const end = app.indexOf('\n}\n', start);
  return app.slice(start, end + 2);
}

function load() {
  const attrs = {};
  const sideMenu = {setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: k => { delete attrs[k]; }};
  const nav = {children: []};
  const ctx = {
    NAV_ICON: {home: 1, tickets: 1, review: 1},
    navIcon: g => ({icon: g}), iconEl: g => ({icon: g}),
    h: (tag, props, ...kids) => ({tag, props, kids}),
    fragment: (...kids) => kids.filter(Boolean),
    reconcile: (target, kids) => { target.children = kids; },
    nav,
    document: {getElementById: id => (id === 'side-menu' ? sideMenu : null)},
  };
  vm.createContext(ctx);
  vm.runInContext(slice('navEntry') + slice('startNav'), ctx);
  return {ctx, nav, attrs};
}
const labels = nav => nav.children.map(a => a.props['aria-label']);
const current = nav => nav.children.filter(a => a.props['aria-current'] === 'page').map(a => a.props.href);

test('before the state the menu has Home, Tickets and Review and the sidebar is busy', () => {
  const {ctx, nav, attrs} = load();
  ctx.startNav('');
  assert.deepEqual(labels(nav), ['Home', 'Tickets', 'Review']);
  assert.deepEqual(current(nav), ['#home']);
  assert.equal(attrs['aria-busy'], 'true');
});

test('the page in the address is marked, a ticket marks Tickets', () => {
  const {ctx, nav} = load();
  for (const [hash, want] of [['#home', '#home'], ['#tickets?view=board', '#tickets'], ['#ticket/t_abc', '#tickets'], ['#review', '#review'], ['#settings/about', null], ['#addon/focus', null]]) {
    ctx.startNav(hash);
    assert.deepEqual(current(nav), want ? [want] : [], hash);
  }
});

test('the start draws it before the first state and render ends the loading', () => {
  const start = app.indexOf('main.replaceChildren(skeletonFor(hashKind(location.hash)));');
  assert.ok(start > 0);
  assert.ok(app.indexOf('startNav(location.hash);', start) > start, 'the start draws the menu');
  assert.ok(app.indexOf('startNav(location.hash);', start) < app.indexOf('refresh();', start), 'before the first state is asked for');
  assert.match(app, /if \(!state && !snapshot\) startNav\(location\.hash\);[^\n]*\n  render\(\);/, 'a click before the first state moves the mark');
  assert.match(slice('render'), /getElementById\('side-menu'\)\?\.removeAttribute\('aria-busy'\)/);
  assert.match(slice('render'), /navLink = \(url, text, glyph, tail = null\) => navEntry\(here, url, text, glyph, tail\)/);
});
