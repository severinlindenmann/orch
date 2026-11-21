// Saved places (places.js, ORCH-1273): the list kept in this browser, what may arrive in a link, removing, duplicates
// and the limits. A crafted link must never plant or change a place by itself.
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../src/orch_dashboard/web/places.js');

const NOW = 1_800_000_000_000, DAY = 24 * 3600 * 1000;
const rand = undefined;  // real ids
const memory = () => { const m = new Map(); return {getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v)}; };
const addOk = (list, input, now = NOW) => { const r = P.add(list, input, now, rand); assert.equal(r.ok, true, r.why); return r; };

test('only web addresses are saved, in one form', () => {
  assert.deepEqual(P.address('https://ws-orch.internal.severin.io/#tickets'), {ok: true, url: 'https://ws-orch.internal.severin.io'});
  assert.equal(P.address('http://127.0.0.1:64381/#home').url, 'http://127.0.0.1:64381');
  assert.equal(P.address('relay.example.ch/admin/').url, 'https://relay.example.ch/admin');
  assert.equal(P.address('127.0.0.1:8790').url, 'http://127.0.0.1:8790');
  for (const bad of ['javascript:alert(1)', 'data:text/html,hi', 'ftp://x.example', 'file:///etc/passwd', '', '   ', 'https://user:pw@x.example', 'https://' + 'a'.repeat(400) + '.ch']) {
    const r = P.address(bad);
    assert.equal(r.ok, false, bad);
    assert.ok(r.why && !/undefined/.test(r.why));
  }
});

test('local addresses are known as local and never passed on', () => {
  for (const u of ['http://127.0.0.1:64381', 'http://localhost:8790', 'http://a.localhost', 'http://127.1.2.3']) assert.equal(P.isLocal(u), true, u);
  for (const u of ['https://ws-orch.internal.severin.io', 'http://10.20.0.14:8790', 'https://127.0.0.1.evil.example']) assert.equal(P.isLocal(u), false, u);
  let list = addOk([], {url: 'http://127.0.0.1:64381', name: 'Notebook'}).list;
  list = addOk(list, {url: 'https://fs.office.example.ch', name: 'Fernscout'}).list;
  const sent = P.unpack(P.pack(list, NOW), NOW);
  assert.deepEqual(sent.map(p => p.name), ['Fernscout']);
});

test('add refuses a duplicate address and keeps names short and clean', () => {
  let r = addOk([], {url: 'https://fs.office.example.ch/', name: '  Fern‮scout  ' + 'x'.repeat(60), kind: 'workspace'});
  assert.equal(r.place.name.length, P.NAME_MAX);
  assert.ok(!r.place.name.includes('‮'));
  const again = P.add(r.list, {url: 'https://fs.office.example.ch#home'}, NOW, rand);
  assert.equal(again.ok, false);
  assert.match(again.why, /already saved/);
  const relay = addOk(r.list, {url: 'https://relay.example.ch/admin', kind: 'relay'});
  assert.equal(relay.place.kind, 'relay');
  assert.equal(relay.place.name, 'relay.example.ch');  // no name typed: the host
  assert.equal(addOk([], {url: 'https://x.example', kind: 'other'}).place.kind, 'workspace');
});

test('at most 50 places', () => {
  let list = [];
  for (let i = 0; i < P.MAX; i++) list = addOk(list, {url: `https://p${i}.example`, name: `P${i}`}).list;
  const r = P.add(list, {url: 'https://one-more.example'}, NOW, rand);
  assert.equal(r.ok, false);
  assert.match(r.why, /up to 50/);
  const big = Array.from({length: 80}, (_, i) => ({id: 'id' + String(i).padStart(8, '0'), url: `https://q${i}.example`, name: 'Q', changed: NOW - i}));
  assert.equal(P.live(P.tidy(big, NOW)).length, P.MAX);
});

test('a removed place stays removed for 90 days and does not come back from another list', () => {
  let r = addOk([], {url: 'https://fs.office.example.ch', name: 'Fernscout'});
  const other = r.list;  // another dashboard still has it
  const mine = P.remove(r.list, r.place.id, NOW + 1000);
  assert.equal(P.live(mine).length, 0);
  const merged = P.arrive(mine, P.unpack(P.pack(other, NOW), NOW), NOW + 2000);
  assert.equal(P.live(merged.list).length, 0);
  assert.equal(merged.fresh.length, 0);
  // the removal reaches the other dashboard
  const there = P.arrive(other, P.unpack(P.pack(mine, NOW + 1000), NOW + 1000), NOW + 3000);
  assert.equal(P.live(there.list).length, 0);
  // after 90 days the mark is gone
  assert.equal(P.tidy(mine, NOW + 91 * DAY).length, 0);
  // undo brings it back
  assert.equal(P.live(P.restore(mine, r.place, NOW + 5000)).length, 1);
});

test('new places from a link wait for the keep question; a link never changes a saved address', () => {
  let mine = addOk([], {url: 'https://fs.office.example.ch', name: 'Fernscout'}).list;
  const id = mine[0].id;
  const crafted = [
    {id, url: 'https://fs.office.example.ch.evil.example', name: 'Fernscout', changed: NOW + 10},  // look-alike on a known id
    {id: 'aaaaaaaaaaaa', url: 'https://pilatus.example.ch', name: 'Pilatus', changed: NOW},
    {id: 'bbbbbbbbbbbb', url: 'javascript:alert(1)', name: 'x', changed: NOW},
    {id: 'cccccccccccc', url: 'http://127.0.0.1:9999', name: 'local', changed: NOW},
    {id: '../../x', url: 'https://bad-id.example', name: 'x', changed: NOW},
  ];
  const packed = Buffer.from(JSON.stringify(crafted)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const got = P.arrive(mine, P.unpack(packed, NOW), NOW + 20);
  assert.equal(P.live(got.list).length, 1);
  assert.equal(got.list[0].url, 'https://fs.office.example.ch');
  assert.deepEqual(got.fresh.map(p => p.name), ['Pilatus']);
  mine = P.keep(got.list, got.fresh, NOW + 30);
  assert.deepEqual(P.live(mine).map(p => p.name).sort(), ['Fernscout', 'Pilatus']);
});

test('broken or oversize links give nothing', () => {
  for (const bad of ['', '%%%', 'not base64 !', 'a'.repeat(9000), Buffer.from('{"x":1}').toString('base64'), Buffer.from('[1,2').toString('base64')]) assert.deepEqual(P.unpack(bad, NOW), []);
});

test('one workspace under two addresses is one row; https is never replaced by http', () => {
  const list = P.tidy([
    {id: 'aaaaaaaaaaaa', url: 'https://ws.example.ch', name: 'Orch', wsid: 'ws_1234', changed: NOW, opened: NOW - DAY},
    {id: 'bbbbbbbbbbbb', url: 'http://ws.example.ch', name: 'Orch', wsid: 'ws_1234', changed: NOW, opened: NOW},
  ], NOW);
  assert.equal(P.live(list).length, 1);
  assert.equal(list[0].url, 'https://ws.example.ch');
  const two = P.tidy([
    {id: 'aaaaaaaaaaaa', url: 'https://a.example.ch', name: 'Orch', wsid: 'ws_1234', changed: NOW, opened: NOW - DAY},
    {id: 'bbbbbbbbbbbb', url: 'https://b.example.ch', name: 'Orch', wsid: 'ws_1234', changed: NOW, opened: NOW},
  ], NOW);
  assert.deepEqual(P.live(two).map(p => p.url), ['https://b.example.ch']);  // the one that last worked
});

test('a page describes itself: name, colour and workspace id update its row', () => {
  let r = addOk([], {url: 'https://fs.office.example.ch', name: 'typed name'});
  const list = P.describe(r.list, 'https://fs.office.example.ch/#home', {wsid: 'ws_fern', name: 'Fernscout', color: 'teal', icon: 'mountain'}, NOW + 5);
  assert.equal(list[0].name, 'Fernscout');
  assert.equal(list[0].color, 'teal');
  assert.equal(list[0].wsid, 'ws_fern');
  assert.equal(list[0].signed, true);
  assert.equal(list[0].opened, NOW + 5);
  const bad = P.describe(list, 'https://fs.office.example.ch', {name: '', color: 'url(javascript:x)', icon: '<svg>'}, NOW + 6);
  assert.equal(bad[0].name, 'Fernscout');
  assert.equal(bad[0].color, 'teal');
  assert.equal(bad[0].icon, undefined);
});

test('the list leaves the address bar on arrival', () => {
  assert.deepEqual(P.takeFromHash('#home&places=abc_-1'), {hash: '#home', packed: 'abc_-1'});
  assert.deepEqual(P.takeFromHash('#places=abc'), {hash: '', packed: 'abc'});
  assert.deepEqual(P.takeFromHash('#tickets?view=board&places=abc'), {hash: '#tickets?view=board', packed: 'abc'});
  assert.deepEqual(P.takeFromHash('#tickets'), {hash: '#tickets', packed: ''});
});

test('relay and publish places never get the list; a dashboard does', () => {
  let list = addOk([], {url: 'https://fs.office.example.ch', name: 'Fernscout'}).list;
  const relay = addOk(list, {url: 'https://relay.example.ch/admin', kind: 'relay'});
  list = relay.list;
  assert.equal(P.openUrl(relay.place, list, NOW), 'https://relay.example.ch/admin');
  const ws = list.find(p => p.name === 'Fernscout');
  assert.match(P.openUrl(ws, list, NOW), /^https:\/\/fs\.office\.example\.ch\/#home&places=[A-Za-z0-9_-]+$/);
  assert.match(P.shareUrl('https://ws-orch.internal.severin.io/', list, NOW), /^https:\/\/ws-orch\.internal\.severin\.io\/#home&places=/);
});

test('storage: saved and read back; a broken or refusing store gives an empty list', () => {
  const store = memory();
  const list = addOk([], {url: 'https://fs.office.example.ch', name: 'Fernscout'}).list;
  assert.equal(P.save(store, list, NOW), true);
  assert.deepEqual(P.load(store, NOW), list);
  assert.deepEqual(P.load({getItem: () => '{broken'}, NOW), []);
  assert.deepEqual(P.load({getItem: () => { throw new Error('blocked'); }}, NOW), []);
  assert.equal(P.save({setItem: () => { throw new Error('full'); }}, list, NOW), false);
});

test('arrival: the list leaves the address bar and is kept for this tab through sign-in', () => {
  const list = addOk([], {url: 'https://pilatus.example.ch', name: 'Pilatus'}).list;
  const packed = P.pack(list, NOW);
  const session = memory();
  session.removeItem = k => session.setItem(k, null);
  let replaced = null;
  const win = {location: {hash: '#home&places=' + packed, pathname: '/', search: ''}, history: {replaceState: (_, __, u) => { replaced = u; }}, sessionStorage: session};
  assert.equal(P.stash(win, NOW), true);
  assert.equal(replaced, '/#home');
  assert.deepEqual(P.incoming(session, NOW).map(p => p.name), ['Pilatus']);
  // nothing in the address: nothing happens
  assert.equal(P.stash({location: {hash: '#tickets', pathname: '/', search: ''}}, NOW), false);
  P.clearIncoming(session);
  assert.deepEqual(P.incoming(session, NOW), []);
});
