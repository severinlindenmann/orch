'use strict';
// O-22 (owner 28 Nov): beside the right panel the Documentation map squeezed five cards into a row and cut their
// names. Under 900 px of page area the overview is a plain list of topics (one part under the other, each topic one
// full-width row with its name and "Related n"); the map with its lines stays for a wide page.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const node = (tag, attrs = {}, children = []) => ({tag, attrs: {...attrs}, dataset: {}, children: children.flat(Infinity).filter(c => c != null && c !== false),
  setAttribute(k, v) { this.attrs[k] = String(v); }, scrollIntoView() { this.scrolled = true; }});
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();

const DATA = {groups: [{id: 'orch', label: 'orch'}, {id: 'builtin', label: 'Turn on when needed'}, {id: 'addon', label: 'Add-ons'}],
  pages: [
    {id: 'relay-phone', title: 'Relay: your phone', group: 'builtin', related: ['chat']},
    {id: 'new-ticket', title: 'From an idea to a finished ticket', group: 'orch', one: 'You write what you want; a helper does it.', related: ['review', 'chat']},
    {id: 'review', title: 'Review: what waits for you', group: 'orch', related: ['new-ticket', 'pull-requests']},
    {id: 'chat', title: 'Chat', group: 'orch', related: []},
    {id: 'pull-requests', title: 'Pull requests', group: 'addon', related: [], on: false},
    {id: 'a-very-long-topic', title: 'What the admin shares with every connected workspace and why that matters', group: 'addon', related: []},
  ]};

function page({windowWidth = 1440, room = 1440, at = ''} = {}) {
  const env = {windowWidth, room}, drawn = [], heard = {};
  const host = {classes: new Set(), kids: [], classList: {add: c => host.classes.add(c), remove: c => host.classes.delete(c)},
    replaceChildren(...k) { host.kids = k; }, querySelector(sel) { const id = /^#(.+)$/.exec(sel)?.[1]; return id ? all({children: host.kids}, n => n.attrs?.id === id)[0] || null : null; }};
  const c = vm.createContext({
    window: {addEventListener: (type, fn) => { heard[type] = fn; }, UI: {
      pageRoom: Object.assign(() => env.room, {under: px => env.windowWidth < px || env.room < px}),
      shortRow: r => node('div', {className: 'short-row', 'data-key': r.dataKey}, [node('a', {className: 'short-title', href: r.href}, [r.title]), r.fact ? node('span', {className: 'short-fact'}, [r.fact]) : null]),
      docs: (h, data, opts) => { drawn.push(opts.at); host.classes.add('ui-docs'); return {destroy() { drawn.push('destroyed'); }}; },
      state: o => node('div', {className: 'state'}, [o.title || o.kind]),
    }},
    h: (tag, attrs, ...children) => node(tag, attrs || {}, children), fragment: (...children) => node('fragment', {}, children),
    heading: (t, sub) => node('header', {}, [node('h1', {}, [t]), node('p', {}, [sub])]),
    array: v => Array.isArray(v) ? v : [], clean: v => String(v ?? ''), mounts: new Map(), CSS: {escape: s => s},
    route: () => ({kind: 'docs', at}), main: {querySelectorAll: () => [host], querySelector: () => host},
    fetch: async () => ({ok: true, json: async () => DATA}), setTimeout: () => 1, render() {}, Date,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/docs.js'), 'utf8') + '\nthis.setData = d => { docsData = d; docsAt = Date.now(); };', c);
  c.setData(DATA);
  c.mountDocs(c.main, {kind: 'docs', at});
  return {c, env, host, drawn, heard};
}
const parts = host => all({children: host.kids}, n => /^docs-part-/.test(n.attrs?.['data-key'] || '')).map(s => [text(all(s, n => n.tag === 'h2')[0]), all(s, n => n.attrs?.className === 'short-row').map(r => text(r))]);

test('beside the right panel (617 and 785 px) and in a small window the overview is a list of topics in four parts', () => {
  for (const [windowWidth, room] of [[1440, 617], [1440, 785], [1920, 880], [768, 704], [390, 390], [320, 320]]) {
    const {host, drawn} = page({windowWidth, room});
    assert.deepEqual(drawn, [], `no map at ${windowWidth}/${room}`);
    assert.equal(host.classes.has('ui-docs'), false);
    assert.equal(text(all({children: host.kids}, n => n.tag === 'h1')[0]), 'Documentation');
    assert.deepEqual(parts(host), [
      ['Start here', ['From an idea to a finished ticket You write what you want; a helper does it. · Related 2']],
      ['orch', ['Review: what waits for you Related 2', 'Chat Related 2']],
      ['Turn on when needed', ['Relay: your phone Related 1']],
      ['Add-ons', ['Pull requests Related 1 · Off', 'What the admin shares with every connected workspace and why that matters']],
    ]);
    // every row is a link to its topic and a list item; the long name is whole (the row wraps, nothing is cut)
    const rows = all({children: host.kids}, n => n.attrs?.className === 'short-row');
    assert.ok(rows.every(r => r.attrs.role === 'listitem'));
    assert.equal(all(rows[1], n => n.tag === 'a')[0].attrs.href, '#docs/review');
  }
});

test('a wide page keeps the map with its lines', () => {
  for (const [windowWidth, room] of [[1440, 1208], [1920, 1688], [1280, 1048], [1440, 900]]) {
    const {host, drawn} = page({windowWidth, room});
    assert.deepEqual(drawn, ['']);
    assert.equal(parts(host).length, 0);
  }
});

test('a topic page is never the list, and #docs/g-<group> opens the list at that part', () => {
  assert.deepEqual(page({room: 617, at: 'review'}).drawn, ['review']);
  const {host} = page({room: 617, at: 'g-addon'});
  assert.equal(parts(host).length, 4);
  assert.equal(all({children: host.kids}, n => n.attrs?.id === 'docs-part-addon')[0].scrolled, true);
});

test('opening and closing the panel swaps the map and the list, once per crossing', () => {
  const {env, host, drawn, heard} = page({room: 1208});
  assert.deepEqual(drawn, ['']);
  env.room = 617; heard['orch:page-room']();
  assert.deepEqual(drawn, ['', 'destroyed']);
  assert.equal(parts(host).length, 4);
  assert.equal(host.classes.has('ui-docs'), false);
  heard.resize(); heard['orch:page-room']();   // still narrow: nothing is drawn again
  assert.deepEqual(drawn, ['', 'destroyed']);
  env.room = 1208; heard['orch:page-room']();
  assert.deepEqual(drawn, ['', 'destroyed', '']);
});
