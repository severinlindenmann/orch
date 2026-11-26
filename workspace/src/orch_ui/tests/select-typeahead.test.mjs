// ORCH-2051: type to jump in the master select works like a native select: keys typed close together form one
// prefix, one key pressed again cycles, a pause starts over. Before, every key searched alone from the top, so typing
// "SALES-097" stayed on the first S item.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

function load() {
  globalThis.window = {addEventListener() {}};
  globalThis.document = {addEventListener() {}};
  delete require.cache[require.resolve('../static/select.js')];
  require('../static/select.js');
  return window.UI.select.typeahead;
}

const labels = ['Choose a ticket', 'SALES-120 Sales call', 'SALES-110 Sample order', 'SALES-099 Safety check',
  'SALES-098 Preisliste_Herbstmesse', 'SALES-097 Prepare the regional sales handover', 'SALES-009 Salary review',
  'Coop offer'];

function typer(clock = {t: 0}) {
  const ta = load()(1000, () => clock.t);
  let cur = 0;
  const type = (keys, gap = 80) => { for (const k of keys) { clock.t += gap; const i = ta.find(k, labels, cur); if (i >= 0) cur = i; } return labels[cur]; };
  return {ta, type, clock, at: i => { cur = i; }};
}

test('a whole key typed quickly lands on that ticket among similar keys', () => {
  assert.equal(typer().type('SALES-097'), 'SALES-097 Prepare the regional sales handover');
  assert.equal(typer().type('sales-009'), 'SALES-009 Salary review');
});

test('one key again and again cycles through the items starting with it, and wraps', () => {
  const {type} = typer();
  assert.equal(type('S'), 'SALES-120 Sales call');
  assert.equal(type('S'), 'SALES-110 Sample order');
  assert.equal(type('SSSSS'), 'SALES-120 Sales call');
});

test('a pause starts a new search; no match leaves the focus where it is', () => {
  const {type, clock} = typer();
  type('SALES-09');
  clock.t += 1500;
  assert.equal(type('C'), 'Coop offer');
  clock.t += 1500;
  assert.equal(type('C'), 'Choose a ticket');
  clock.t += 1500;
  assert.equal(type('X'), 'Choose a ticket');
});

test('reset (Escape, arrows, closing) forgets the typed keys', () => {
  const {ta, type} = typer();
  type('SA');
  ta.reset();
  assert.equal(ta.typing(), false);
  assert.equal(type('C'), 'Coop offer');
});
