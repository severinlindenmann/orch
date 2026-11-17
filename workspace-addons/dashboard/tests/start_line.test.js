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
  vm.runInContext(between(home, 'function loginTicketLinks', 'async function checkLogins')
    + between(home, '// Tickets waiting in line for a helper', '// Home: what needs the person first') + '\nthis.b = lineBanner;', c);
  return c.b();
}

test('busy computer: one banner with the reason and the waiting tickets', () => {
  const v = banner({waiting:['t_aaaaaa', 't_bbbbbb'], why:"the computer is very busy (54 'orch record tail' at once)", limit:null});
  assert.equal(v.attrs.role, 'status'); assert.equal(v.attrs['data-key'], 'start-line');
  assert.match(text(v), /No helper starts right now: the computer is very busy \(54 'orch record tail' at once\)\./);
  assert.match(text(v), /2 tickets wait in line and start by themselves when that passes:/);
  assert.deepEqual(all(v, n => n.tag === 'a').map(text), ['ORCH-21 Usage page', 'ORCH-22 Focus draft D']);
  assert.equal(all(v, n => n.attrs?.['data-key'] === 'start-line-limit').length, 0);
});

test('the helper limit: the banner offers one click to allow more', () => {
  const v = banner({waiting:['t_aaaaaa'], why:'3 helpers are working at once, the most you allowed', limit:3});
  assert.match(text(v), /1 ticket waits in line and starts by itself/);
  assert.equal(all(v, n => n.attrs?.href === '#settings/helper').length, 1);
});

test('no reason, nothing waiting, an unknown ticket or a snapshot: no banner', () => {
  assert.equal(banner(null), null);
  assert.equal(banner({waiting:['t_aaaaaa'], why:null, limit:null}), null);
  assert.equal(banner({waiting:[], why:'the computer is very busy', limit:null}), null);
  assert.equal(banner({waiting:['t_zzzzzz'], why:'the computer is very busy', limit:null}), null);
  assert.equal(banner({waiting:['t_aaaaaa'], why:'the computer is very busy', limit:null}, true), null);
});
