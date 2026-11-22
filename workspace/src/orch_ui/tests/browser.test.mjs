import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM: enough for browser.js to build its element and take the stream's events. innerHTML is recorded so a
// test can prove that site text never goes in as markup.
const markup = [];
class Node_ {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = ''; this.hidden = false; this._text = ''; this.parentNode = null; this.title = ''; }
  set innerHTML(v) { markup.push(v); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...c) { for (const x of c) { x.parentNode = this; this.children.push(x); } }
  prepend(...c) { for (const x of c.reverse()) { x.parentNode = this; this.children.unshift(x); } }
  replaceChildren(...c) { this._text = ''; this.children = []; this.append(...c); }
  get lastChild() { return this.children[this.children.length - 1]; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  async click() { for (const f of this.listeners.click || []) await f({}); }
  getContext() { return {clearRect() {}, drawImage() {}}; }
}
globalThis.window = {};
globalThis.document = {createElement: t => new Node_(t), createTextNode: t => ({textContent: String(t), className: '', children: [], parentNode: null})};
const drawn = [];
globalThis.createImageBitmap = async blob => { drawn.push(blob.size); return {width: 1280, height: 800, close() {}}; };
globalThis.Blob = class { constructor(parts) { this.size = parts[0].length; } };
globalThis.atob = s => Buffer.from(s, 'base64').toString('binary');
require('../static/browser.js');
const UI = globalThis.window.UI;
const find = (n, cls) => n.className.split(' ').includes(cls) ? n : n.children.map(c => find(c, cls)).find(Boolean);

test('connecting, then live with a picture, then ended with the reason', async () => {
  const v = UI.browserView({label: 'Browser'});
  assert.equal(v.el.dataset.state, 'connecting');
  v.hello({generation: '0123456789abcdef'});
  assert.equal(v.el.dataset.state, 'live');
  v.frame({jpeg: Buffer.from('jpegbytes').toString('base64'), w: 1280, h: 800, at: Date.now() / 1000});
  await new Promise(r => setTimeout(r, 5));
  assert.ok(drawn.length >= 1);
  v.show('lost');
  assert.equal(v.el.dataset.state, 'lost');
  v.end({why: 'Closed after 15 minutes without a command', final: true});
  assert.equal(v.el.dataset.state, 'ended');
  assert.match(find(v.el, 'bview-say').textContent, /15 minutes/);
  assert.equal(find(v.el, 'bview-state').hidden, true);  // the reason is said once
  v.show('connecting');
  assert.equal(v.el.dataset.state, 'ended');  // an ended browser does not go back to connecting
  v.dispose();
});

test('site text goes in as text, cut short, never as markup', () => {
  const v = UI.browserView({});
  v.tabs([{title: '<img src=x onerror=alert(1)>' + 'x'.repeat(100), url: 'https://a.example/', current: true}, {title: 'B', url: 'b'}]);
  v.event({text: 'The page showed a message and it was closed. The message:', site_text: '<script>steal()</script>'});
  assert.equal(markup.length, 0);
  const tabs = find(v.el, 'bview-tabs');
  assert.equal(tabs.hidden, false);
  assert.ok(tabs.children[0].textContent.length <= 40);
  assert.equal(tabs.children[0].attrs['aria-current'], 'true');
  assert.match(find(v.el, 'bview-cards').textContent, /<script>steal/);
  v.dispose();
});

test('one tab hides the tab row; at most three cards stay', () => {
  const v = UI.browserView({});
  v.tabs([{title: 'Only', url: 'x', current: true}]);
  assert.equal(find(v.el, 'bview-tabs').hidden, true);
  for (let i = 0; i < 6; i++) v.event({text: 'Stopped ' + i});
  const cards = find(v.el, 'bview-cards');
  assert.equal(cards.children.length, 3);
  assert.match(cards.children[0].textContent, /Stopped 5/);
  v.dispose();
});

test('Stop names the browser generation and comes back when it failed', async () => {
  const seen = [];
  const v = UI.browserView({onStop: async gen => { seen.push(gen); return {ok: false}; }});
  v.hello({generation: 'abcdef0123456789'});
  const stop = v.el.children[0].children[2];
  assert.equal(stop.hidden, false);
  await stop.click();
  assert.deepEqual(seen, ['abcdef0123456789']);
  assert.equal(stop.disabled, false);
  v.end({why: 'stopped by a person', final: true});
  assert.equal(stop.hidden, true);
  v.dispose();
});

test('pure parts: age words, clip, fit', () => {
  const now = 1_000_000_000;
  assert.equal(UI.browserView.ageWords(now / 1000 - 3, now), '');
  assert.equal(UI.browserView.ageWords(now / 1000 - 30, now), 'Last change 30 s ago');
  assert.equal(UI.browserView.ageWords(now / 1000 - 600, now), 'Last change 10 min ago');
  assert.equal(UI.browserView.clip('  a   b  ', 10), 'a b');
  assert.equal(UI.browserView.clip('abcdefghij', 5), 'abcd…');
  assert.deepEqual(UI.browserView.fit(1280, 800, 640), {w: 640, h: 400});
});

test('a picture decoded after a tab switch is not drawn', async () => {
  let release;
  const drawnOn = [];
  globalThis.createImageBitmap = () => new Promise(r => { release = () => r({width: 1, height: 1, close() {}}); });
  const v = UI.browserView({});
  const ctx = {clearRect() {}, drawImage() { drawnOn.push('drawn'); }};
  v.el.children[3].children[0].getContext = () => ctx;
  v.hello({generation: 'g'});
  v.frame({jpeg: Buffer.from('old').toString('base64'), w: 1, h: 1, at: 1});
  v.clear();  // the view switched tabs while the old picture decoded
  release();
  await new Promise(r => setTimeout(r, 5));
  assert.deepEqual(drawnOn, []);
  v.dispose();
});

test('Hide sits in the bar only when the page gives it', async () => {
  let hidden = 0;
  const v = UI.browserView({onStop: async () => ({ok: true}), onHide: () => { hidden += 1; }});
  const hide = v.el.children[0].children[3];
  assert.equal(hide.textContent, 'Hide');
  await hide.click();
  assert.equal(hidden, 1);
  const plain = UI.browserView({});
  assert.equal(plain.el.children[0].children.length, 3);  // no Hide without onHide
  plain.dispose();
  v.dispose();
});

test('live words: one "Helper is driving" in the bar', () => {
  const v = UI.browserView({});
  v.hello({generation: 'g'});
  assert.equal(find(v.el, 'bview-say').textContent, 'Helper is driving');
  v.dispose();
});

test('pinch zoom: the point under the fingers stays, scale 1..4, the picture never leaves its box', () => {
  const zoom = UI.browserView.zoom;
  const z = zoom({s: 1, x: 0, y: 0}, 2, 100, 50, 400, 250);
  assert.equal(z.s, 2);
  assert.deepEqual([z.x, z.y], [-100, -50]);  // (100, 50) stays under the fingers
  assert.equal(zoom(z, 10, 0, 0, 400, 250).s, 4);
  assert.deepEqual(zoom(z, 0.1, 0, 0, 400, 250), {s: 1, x: 0, y: 0});
  const edge = zoom({s: 1, x: 0, y: 0}, 2, 400, 250, 400, 250);
  assert.ok(edge.x >= 400 - 800 && edge.x <= 0 && edge.y >= 250 - 500 && edge.y <= 0);
});

test('the small preview: hidden until the stream speaks, the site and the newest time, ended is one quiet line', async () => {
  globalThis.createImageBitmap = async () => ({width: 1280, height: 800, close() {}});
  window.UI.clock = d => String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0');
  let opened = 0;
  const p = UI.browserPeek({onOpen: () => { opened += 1; }});
  assert.equal(p.el.hidden, true);
  p.hello({generation: 'g'});
  assert.equal(p.el.hidden, false);
  p.tabs([{title: 'Partners', url: 'https://www.office-partners.example/find', current: true}]);
  assert.equal(find(p.el, 'bpeek-what').textContent, 'The helper is browsing office-partners.example');
  p.frame({jpeg: Buffer.from('x').toString('base64'), w: 1280, h: 800, at: Date.UTC(2026, 10, 22, 14, 2) / 1000});
  p.frame({jpeg: Buffer.from('y').toString('base64'), w: 1280, h: 800, at: Date.UTC(2026, 10, 22, 14, 6) / 1000});
  assert.equal(find(p.el, 'bpeek-when').textContent, '14:06');  // the newest time
  assert.match(p.el.children[0].attrs['aria-label'], /^Open the helper’s browser: The helper is browsing office-partners\.example, 14:06$/);
  assert.equal((p.el.textContent.match(/Helper is driving/g) || []).length, 1);
  await p.el.children[0].click();
  assert.equal(opened, 1);
  p.open(true);
  assert.equal(p.el.children[0].attrs['aria-expanded'], 'true');
  p.end({why: 'closed'}, Date.UTC(2026, 10, 22, 14, 20) / 1000);
  assert.equal(p.el.children[0].hidden, true);  // no picture of an ended browser
  assert.equal(find(p.el, 'bpeek-ended').textContent, 'The helper’s browser ended at 14:20.');
  p.hide();
  assert.equal(p.el.hidden, true);
  p.dispose();
});

test('the preview takes site text as text only', () => {
  const before = markup.length;
  const p = UI.browserPeek({});
  p.tabs([{title: '<img src=x>', url: 'javascript:alert(1)', current: true}]);
  assert.equal(find(p.el, 'bpeek-what').textContent, 'The helper is opening a page');
  assert.equal(markup.length, before);
  assert.equal(UI.browserPeek.site('https://a.b.example:8443/x'), 'a.b.example');
  p.dispose();
});

test('the preview has a wide (Browser page) and a compact (pane, chat) form', () => {
  for (const [o, cls] of [[{wide: true}, 'bpeek wide'], [{compact: true}, 'bpeek compact'], [{}, 'bpeek']]) {
    const p = UI.browserPeek(o);
    assert.equal(p.el.className, cls);
    p.dispose();
  }
});
