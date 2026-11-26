// Look options at a taste stop (#949) as picture cards, on a tiny DOM. Run: node --test tests/look-cards-dom.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const js = readFileSync(new URL('../src/orch_factory/web/factory.js', import.meta.url), 'utf8');

class Node_ {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = ''; this.textContent = ''; this.style = {}; }
  append(...c) { this.children.push(...c); }
  replaceChildren(...c) { this.children = c; }
  replaceWith() {}
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  click() { (this.listeners.click || []).forEach(f => f({})); }
  get classList() { const n = this; return {add: c => { n.className = (n.className + ' ' + c).trim(); }, contains: c => n.className.split(' ').includes(c)}; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c instanceof Node_ && c.all(pred, out)); return out; }
  words() { return [this.textContent, ...this.children.map(c => (c instanceof Node_ ? c.words() : String(c)))].filter(Boolean).join(' '); }
}

// Everything the page defines before the stop page, then lookCards out of the closure. Nothing renders or fetches.
function kit({embedded = true} = {}) {
  const posted = [], opened = [];
  const top = {};
  const win = {
    addEventListener() {}, postMessage: m => posted.push(m),
    UI: {resultOverlay: (items, i) => opened.push([items, i])},
    OrchFrame: {url: u => u + '?f=1', chan: 'c1'},
  };
  win.top = embedded ? top : win;
  win.parent = win;
  const doc = {documentElement: {dataset: {prefix: '/a/factory'}}, getElementById: () => new Node_('div'), createElement: t => new Node_(t), createTextNode: t => t};
  const head = js.slice(js.indexOf("'use strict';") + 13, js.indexOf('  function stopPage('));
  const make = new Function('window', 'document', 'location', 'setTimeout', head + '\nreturn {lookCards};');
  return {...make(win, doc, {origin: 'http://x', hash: ''}, () => 0), posted, opened};
}

const ORDER = 't_abc1234';
const item = {title: 'Page colour', tag: 'taste', looks: [{title: 'Calm', picture: 'calm.png'}, {title: 'Bold', picture: 's1/bold.png'}, {title: 'Warm', picture: 'warm.png'}]};
const question = {q: 'q7', text: 'Which look for the page?', options: ['Calm', 'Bold', 'Warm'], recommended: null};

test('three looks show as three picture cards that open big', () => {
  const {lookCards, opened} = kit();
  const out = lookCards({id: ORDER, questions: [question]}, item);
  assert.equal(out[0].textContent, 'Pick a look');
  const grid = out[1];
  assert.equal(grid.className, 'decision-shown');
  const shots = grid.children;
  assert.equal(shots.length, 3);
  assert.deepEqual(shots.map(s => s.className), ['decision-shot', 'decision-shot', 'decision-shot']);
  assert.deepEqual(shots.map(s => s.children[1].textContent), ['Look A: Calm', 'Look B: Bold', 'Look C: Warm']);
  const img = shots[1].all(n => n.tag === 'img')[0];
  assert.equal(img.src, '/a/factory/api/order/' + ORDER + '/file/s1/bold.png?f=1');
  assert.equal(img.alt, 'Look B: Bold');
  shots[2].click();
  assert.equal(opened.length, 1);
  assert.equal(opened[0][1], 2);
  assert.deepEqual(opened[0][0].map(x => x.name), ['Look A: Calm', 'Look B: Bold', 'Look C: Warm']);
});

test('Choose a look opens the dashboard question card of the matching question, never answers', () => {
  const {lookCards, posted} = kit();
  const out = lookCards({id: ORDER, questions: [{q: 'q2', options: ['Yes', 'No']}, question]}, item);
  const button = out[2].all(n => n.tag === 'button')[0];
  assert.equal(button.textContent, 'Choose a look');
  assert.ok(!button.className.includes('primary'), 'the stop answer stays the one filled button');
  button.click();
  assert.deepEqual(posted, [{type: 'orch.question', ticket: ORDER, question: 'q7', chan: 'c1'}]);
});

test('without the matching question the cards still show and say how to pick', () => {
  const {lookCards} = kit();
  const out = lookCards({id: ORDER, questions: [{q: 'q2', options: ['Calm', 'Bold']}]}, item);
  assert.equal(out[1].children.length, 3);
  assert.equal(out[2].tag, 'p');
  assert.equal(out[2].textContent, 'Say which look you want when you answer this pause.');
});

test('a bad picture name never becomes an address, and one look alone is no choice', () => {
  const {lookCards} = kit();
  const out = lookCards({id: ORDER, questions: []}, {...item, looks: [{title: 'Calm', picture: '../x.png'}, {title: 'Bold', picture: 'https://e.x/b.png'}]});
  assert.deepEqual(out[1].children.map(c => c.words()), ['Look A: Calm Picture unavailable.', 'Look B: Bold Picture unavailable.']);
  assert.equal(out[1].all(n => n.tag === 'img').length, 0);
  assert.deepEqual(lookCards({id: ORDER}, {...item, looks: [item.looks[0]]}), []);
});
