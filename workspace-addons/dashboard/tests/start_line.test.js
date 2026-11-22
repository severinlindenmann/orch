// ORCH-266: Home says why no helper starts while tickets wait in line (the computer looked busy and nothing said so).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const home = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/home.js'), 'utf8');
const between = (src, a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
function node(tag, attrs = {}, children = []) { return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false)}; }
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
const TICKETS = [{id:'t_aaaaaa', key:'ORCH-21', title:'Usage page'}, {id:'t_bbbbbb', key:'ORCH-22', title:'Focus draft D'}];

function banner(line, snapshot = false) {
  const c = vm.createContext({h:(tag, attrs, ...kids) => node(tag, attrs || {}, kids), array:v => Array.isArray(v) ? v : [],
    clean:v => String(v ?? ''), snapshot, state:{start_line:line}, tickets:() => TICKETS, href:id => '#ticket/' + id});
  vm.runInContext(between(home, '// Tickets waiting in line for a helper', '// Home: what needs the person first') + '\nthis.b = lineBanner;', c);
  return c.b();
}

test('busy computer: one short line, no list of the waiting tickets (ORCH-1100)', () => {
  const v = banner({waiting:['t_aaaaaa', 't_bbbbbb'], why:"the computer is very busy (54 'orch record tail' at once)", limit:null});
  assert.equal(v.attrs.role, 'status'); assert.equal(v.attrs['data-key'], 'start-line');
  assert.equal(text(v), 'Computer too busy to start more work.');
  assert.equal(all(v, n => n.tag === 'a').length, 0);
});

test('the helper limit: a short line and one click to allow more', () => {
  const v = banner({waiting:['t_aaaaaa', 't_bbbbbb'], why:'10 helpers are working at once, the most you allowed', limit:10});
  assert.equal(text(v), 'Helper limit reached. Allow more helpers');
  assert.deepEqual(all(v, n => n.tag === 'a').map(n => n.attrs.href), ['#settings/helper']);
  assert.doesNotMatch(text(v), /ORCH-2/);
});

test('usage limit, full disk and any other reason: short words', () => {
  assert.equal(text(banner({waiting:['t_aaaaaa'], why:'the usage limit is reached until 22:00', limit:null})), 'Usage limit reached.');
  assert.equal(text(banner({waiting:['t_aaaaaa'], why:'the disk is almost full', limit:null})), 'Disk almost full.');
  assert.equal(text(banner({waiting:['t_aaaaaa'], why:'something new holds them', limit:null})), 'Something new holds them.');
});

test('no reason, nothing waiting, an unknown ticket or a snapshot: no banner', () => {
  assert.equal(banner(null), null);
  assert.equal(banner({waiting:['t_aaaaaa'], why:null, limit:null}), null);
  assert.equal(banner({waiting:[], why:'the computer is very busy', limit:null}), null);
  assert.equal(banner({waiting:['t_zzzzzz'], why:'the computer is very busy', limit:null}), null);
  assert.equal(banner({waiting:['t_aaaaaa'], why:'the computer is very busy', limit:null}, true), null);
});
