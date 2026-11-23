// ORCH-522: the Part of choices are worked out in one pass; the answer is the same as the old way (every ticket's
// parent looked up in the whole list, a few million comparisons at 1,600 open tickets).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const WEB = path.join(__dirname, '..', 'src', 'orch_dashboard', 'web');
const helpers = require(path.join(WEB, 'helpers.js'));

// the old way, kept here as the reference
const arr = v => Array.isArray(v) ? v : [];
const matches = (ref, t) => !!ref && (ref === t.id || (!!t.key && String(ref).toLowerCase() === String(t.key).toLowerCase()));
const parentOf = (all, t) => arr(all).find(p => p && p.id !== t.id && matches(t.parent, p)) || arr(all).find(p => p && p.id !== t.id && arr(p.children).includes(t.id)) || null;
const keyNumber = c => Number(String(c && c.key || '').split('-').pop()) || 0;
const creationOrder = (x, y) => keyNumber(x) - keyNumber(y) || (Date.parse(x.created_at) || 0) - (Date.parse(y.created_at) || 0) || String(x.id).localeCompare(String(y.id));
function oldChoices(all, t) {
  const list = arr(all).filter(x => x && x.id), inside = new Set([t.id]);
  for (let grew = true; grew;) {
    grew = false;
    for (const x of list) if (!inside.has(x.id) && list.some(p => inside.has(p.id) && matches(x.parent, p))) { inside.add(x.id); grew = true; }
  }
  const current = parentOf(list, t), holds = new Set(list.map(x => (parentOf(list, x) || {}).id).filter(Boolean));
  const rank = x => x.release ? 0 : x.epic ? 1 : holds.has(x.id) ? 2 : 3;
  return list.filter(x => !inside.has(x.id) && (!['done', 'dropped'].includes(x.status) || (current && x.id === current.id)))
    .sort((x, y) => rank(x) - rank(y) || creationOrder(y, x));
}

function rng(seed) { return () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }; }

function tickets(n, rand) {
  const statuses = ['open', 'active', 'waiting', 'review', 'done', 'dropped'];
  const list = [];
  for (let i = 0; i < n; i++) {
    const t = {id: 't_' + String(i).padStart(6, '0'), key: rand() < 0.9 ? 'ORCH-' + (i + 1) : '', status: statuses[Math.floor(rand() * statuses.length)],
      created_at: new Date(Date.UTC(2026, 10, 1) + i * 60000).toISOString()};
    if (rand() < 0.05) t.release = true; else if (rand() < 0.05) t.epic = true;
    list.push(t);
  }
  for (const t of list) {
    const r = rand();
    const other = list[Math.floor(rand() * n)];
    if (r < 0.3) t.parent = other.id;                                   // by id (a loop or itself sometimes)
    else if (r < 0.45 && other.key) t.parent = rand() < 0.5 ? other.key.toLowerCase() : other.key;  // by key, any case
    else if (r < 0.5) t.parent = 't_gone00';                            // a parent that is not in the list
    if (rand() < 0.1) other.children = [...arr(other.children), t.id];  // the other way round: a children list
  }
  if (n > 3) list.push({...list[2]});                                    // a ticket listed twice
  return list;
}

test('the Part of choices are the same as the old way on random trees', () => {
  for (let seed = 1; seed <= 40; seed++) {
    const rand = rng(seed), all = tickets(5 + Math.floor(rand() * 60), rand);
    for (const t of all.slice(0, 12)) {
      assert.deepEqual(helpers.parentChoices(all, t).map(x => x.id), oldChoices(all, t).map(x => x.id), `seed ${seed} ticket ${t.id}`);
    }
  }
});

test('a ticket that is not in the list still gets its choices', () => {
  const all = tickets(30, rng(7));
  const outside = {id: 't_zzzzzz', key: 'ORCH-999', status: 'open'};
  assert.deepEqual(helpers.parentChoices(all, outside).map(x => x.id), oldChoices(all, outside).map(x => x.id));
});

test('1,600 open tickets: the choices take well under a second', () => {
  const all = tickets(1600, rng(3));
  const began = Date.now();
  helpers.parentChoices(all, all[10]);
  assert.ok(Date.now() - began < 300, `took ${Date.now() - began} ms`);
});
