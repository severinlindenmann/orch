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
  replaceChildren(...c) { this.children = []; this.append(...c); }
  get lastChild() { return this.children[this.children.length - 1]; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  async click() { for (const f of this.listeners.click || []) await f({}); }
  getContext() { return {clearRect() {}, drawImage() {}}; }
}
globalThis.window = {};
globalThis.document = {createElement: t => new Node_(t)};
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
