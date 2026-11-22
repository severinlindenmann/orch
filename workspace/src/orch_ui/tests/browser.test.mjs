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

/* ---- take over and give back (ORCH-1495) ---- */
const words = n => n.textContent;
const buttons = n => (n.tag === 'button' && !n.hidden ? [n] : []).concat(...n.children.map(buttons));
const fire = (n, type, e) => { for (const f of n.listeners[type] || []) f({preventDefault() { e.prevented = true; }, ...e}); };

test('pure: a page point becomes picture pixels, letterboxed, null outside', () => {
  const tp = UI.browserView.toPicture;
  assert.deepEqual(tp(110, 60, {left: 10, top: 10, width: 640, height: 400}, 1280, 800), {x: 200, y: 100});
  // a box taller than the picture: the picture sits in the middle (object-fit contain)
  assert.deepEqual(tp(10, 110, {left: 10, top: 10, width: 640, height: 600}, 1280, 800), {x: 0, y: 0});
  assert.equal(tp(10, 105, {left: 10, top: 10, width: 640, height: 600}, 1280, 800), null);
  assert.equal(tp(650, 60, {left: 10, top: 10, width: 640, height: 400}, 1280, 800), null);  // right edge: outside
  assert.equal(tp(20, 20, {left: 0, top: 0, width: 0, height: 0}, 1280, 800), null);
});

test('pure: keys from the fixed list, letters as text, Ctrl+V left to the paste, F6 leaves', () => {
  const k = UI.browserView.keyOf;
  assert.deepEqual(k({key: 'Enter'}, 'down'), {t: 'key', type: 'down', key: 'Enter', mod: 0});
  assert.deepEqual(k({key: 'Escape'}, 'up'), {t: 'key', type: 'up', key: 'Escape', mod: 0});
  assert.deepEqual(k({key: 'ä'}, 'down'), {t: 'text', text: 'ä'});
  assert.equal(k({key: 'ä'}, 'up'), null);
  assert.deepEqual(k({key: 'A', metaKey: true}, 'down'), {t: 'key', type: 'down', key: 'a', mod: 4});
  assert.equal(k({key: 'v', ctrlKey: true}, 'down'), 'paste');
  assert.equal(k({key: 'w', ctrlKey: true}, 'down'), null);
  assert.equal(k({key: 'F5'}, 'down'), null);
  assert.equal(k({key: 'F6'}, 'down'), 'leave');
  assert.equal(k({key: 'a', isComposing: true}, 'down'), null);
  assert.deepEqual(UI.browserView.KEYS.slice(0, 3), ['Enter', 'Tab', 'Backspace']);
});

function controlled() {
  const calls = [];
  const c = {take: async () => { calls.push('take'); return {ok: true}; }, give: async () => { calls.push('give'); return {ok: true, text: 'Given back to the helper.'}; },
    cancel: async () => { calls.push('cancel'); return {ok: true}; }, send: async (ev, size) => { calls.push(['send', ev, size]); return {ok: true}; },
    allowSends: async site => { calls.push(['allow', site]); return site === 'evil.test' ? {ok: false, text: 'Pick a site from this ticket’s list.'} : {ok: true}; }};
  const v = UI.browserView({label: 'B', control: c, onStop: async () => ({ok: true})});
  v.hello({generation: '0123456789abcdef'});
  v.frame({jpeg: Buffer.from('x').toString('base64'), w: 1280, h: 800, at: Date.now() / 1000});
  return {v, calls, c};
}

test('watching: Take over in the bar; the helper asking shows its why with one Take over', async () => {
  const {v, calls} = controlled();
  v.control({state: 'helper', epoch: 0, mine: false});
  const take = buttons(find(v.el, 'bview-bar')).find(b => b.textContent === 'Take over');
  assert.ok(take);
  assert.equal(find(v.el, 'bview-ctl').hidden, true);
  await take.click();
  assert.deepEqual(calls, ['take']);
  v.control({state: 'helper', epoch: 0, mine: false, asking: 'Please sign in to the portal'});
  const ctl = find(v.el, 'bview-ctl');
  assert.equal(ctl.hidden, false);
  assert.equal(ctl.dataset.kind, 'needs');
  assert.match(words(ctl), /The helper needs you in its browser\. Please sign in to the portal/);
  assert.equal(buttons(find(v.el, 'bview-bar')).some(b => b.textContent === 'Take over'), false);  // one Take over
  assert.equal(buttons(ctl).filter(b => b.className.includes('primary')).length, 1);
  assert.equal(words(find(v.el, 'bview-say')), 'Waiting for you');
  v.dispose();
});

test('finishing: the spinner line and Stop its step now; another page taking over shows no buttons', async () => {
  const {v, calls} = controlled();
  v.control({state: 'finishing', epoch: 1, mine: true});
  const ctl = find(v.el, 'bview-ctl');
  assert.match(words(ctl), /The helper is finishing its step… Then you are in control\./);
  assert.ok(find(ctl, 'spinner'));
  await buttons(ctl).find(b => b.textContent === 'Stop its step now').click();
  assert.deepEqual(calls, ['cancel']);
  v.control({state: 'finishing', epoch: 1, mine: false});
  assert.equal(buttons(ctl).length, 0);
  assert.equal(v.el.dataset.full, undefined);
  v.dispose();
});

test('in control: full view, honest words, the picture takes mouse and keys, Esc goes to the site', async () => {
  const {v, calls} = controlled();
  const canvas = find(v.el, 'bview-canvas');
  let focused = 0;
  canvas.focus = () => { focused += 1; };
  canvas.getBoundingClientRect = () => ({left: 0, top: 0, width: 640, height: 400});
  v.control({state: 'person', epoch: 2, mine: true});
  assert.equal(v.el.dataset.full, 'true');
  assert.equal(canvas.tabIndex, 0);
  assert.ok(focused >= 1, 'keyboard focus goes to the picture');
  const ctl = find(v.el, 'bview-ctl');
  assert.match(words(ctl), /You are in control\. The helper is paused\. What you type goes to the site, not to orch\./);
  assert.match(words(ctl), /starts on a fresh page and can see what the site itself shows .*orch kept nothing you typed/);
  assert.deepEqual(buttons(ctl).map(b => b.textContent), ['Give back to the helper', 'Back to the ticket', 'Stop browser']);
  fire(canvas, 'pointerdown', {pointerType: 'mouse', clientX: 100, clientY: 50, button: 0, detail: 1});
  fire(canvas, 'pointermove', {pointerType: 'mouse', clientX: 101, clientY: 50});
  fire(canvas, 'pointermove', {pointerType: 'mouse', clientX: 102, clientY: 50});
  fire(canvas, 'pointerup', {pointerType: 'mouse', clientX: 102, clientY: 50, button: 0});
  const esc = {key: 'Escape'};
  fire(canvas, 'keydown', esc);
  assert.ok(esc.prevented);
  fire(canvas, 'keydown', {key: 'h'});
  fire(canvas, 'keydown', {key: 'i'});
  fire(canvas, 'pointerdown', {pointerType: 'mouse', clientX: 700, clientY: 50, button: 0});  // outside: nothing
  await new Promise(r => setTimeout(r, 80));
  const sent = calls.filter(x => x[0] === 'send');
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0][2], {w: 1280, h: 800});
  assert.deepEqual(sent[0][1].map(e => e.t), ['down', 'move', 'up', 'key', 'text']);  // moves merged, letters joined
  assert.deepEqual(sent[0][1][0], {t: 'down', x: 200, y: 100, button: 'left', count: 1, mod: 0});
  assert.equal(sent[0][1][4].text, 'hi');
  assert.equal(v.el.dataset.control, 'person', 'Esc never gives back');
  // F6 moves to the buttons
  let barFocus = 0;
  buttons(ctl)[0].focus = () => { barFocus += 1; };
  ctl.children[1].querySelector = () => buttons(ctl)[0];
  fire(canvas, 'keydown', {key: 'F6'});
  assert.equal(barFocus, 1);
  // Back to the ticket keeps control; Full view comes back
  await buttons(ctl).find(b => b.textContent === 'Back to the ticket').click();
  assert.equal(v.el.dataset.full, undefined);
  assert.ok(buttons(ctl).some(b => b.textContent === 'Full view'));
  await buttons(ctl).find(b => b.textContent === 'Give back to the helper').click();
  assert.ok(calls.includes('give'));
  assert.match(words(find(ctl, 'bview-ctl-note')), /Given back/);
  v.control({state: 'helper', epoch: 3, mine: false});
  assert.equal(v.el.dataset.full, undefined);
  assert.equal(canvas.tabIndex, -1);
  fire(canvas, 'keydown', {key: 'x'});
  await new Promise(r => setTimeout(r, 60));
  assert.equal(calls.filter(x => x[0] === 'send').length, 1, 'no input once control is gone');
  v.dispose();
});

test('paused: Give back and Take over again; another page in control: no buttons', async () => {
  const {v, calls} = controlled();
  v.control({state: 'paused', epoch: 4, mine: false});
  const ctl = find(v.el, 'bview-ctl');
  assert.match(words(ctl), /The helper is paused\. Nobody is in control/);
  assert.deepEqual(buttons(ctl).map(b => b.textContent), ['Give back to the helper', 'Take over again']);
  await buttons(ctl)[1].click();
  assert.deepEqual(calls, ['take']);
  v.control({state: 'person', epoch: 5, mine: false});
  assert.match(words(ctl), /A person is in control from another page/);
  assert.equal(buttons(ctl).length, 0);
  assert.equal(v.el.dataset.full, undefined);
  v.end({why: 'stopped by a person', final: true});
  assert.equal(find(v.el, 'bview-ctl').hidden, true);
  v.dispose();
});

test('the small preview says who drives and what the helper asks', () => {
  window.UI.helperPill = (kind, w) => { const n = document.createElement('span'); n.className = 'pill'; n.dataset.state = kind; n.textContent = w; return n; };
  const p = UI.browserPeek({onOpen() {}});
  p.hello({});
  p.tabs([{title: 'Shop', url: 'https://shop.example/', current: true}]);
  p.control({state: 'helper', asking: 'Please sign in'});
  assert.match(p.el.textContent, /The helper needs you in its browser\. Please sign in/);
  assert.match(p.el.textContent, /Waiting for you/);
  p.tabs([{title: 'Shop', url: 'https://shop.example/a', current: true}]);
  assert.match(p.el.textContent, /Please sign in/, 'a tab change keeps the question');
  p.control({state: 'person', mine: true});
  assert.match(p.el.textContent, /You are in control/);
  assert.match(p.el.textContent, /The helper is browsing shop\.example/);
  p.control({state: 'paused'});
  assert.match(p.el.textContent, /The helper is paused/);
  delete window.UI.helperPill;
});

test('a button let go outside the picture is still let go (at the last point inside)', async () => {
  const {v, calls} = controlled();
  const canvas = find(v.el, 'bview-canvas');
  canvas.getBoundingClientRect = () => ({left: 0, top: 0, width: 640, height: 400});
  v.control({state: 'person', epoch: 2, mine: true});
  fire(canvas, 'pointerdown', {pointerType: 'mouse', clientX: 100, clientY: 50, button: 0, detail: 1, pointerId: 1});
  fire(canvas, 'pointerup', {pointerType: 'mouse', clientX: 900, clientY: 50, button: 0});
  fire(canvas, 'pointerdown', {pointerType: 'mouse', clientX: 10, clientY: 10, button: 2, detail: 1});
  fire(canvas, 'blur', {});
  await new Promise(r => setTimeout(r, 80));
  const evs = calls.filter(x => x[0] === 'send').flatMap(x => x[1]);
  assert.deepEqual(evs.map(e => e.t + ':' + (e.button || '')), ['down:left', 'up:left', 'down:right', 'up:right']);
  assert.deepEqual([evs[1].x, evs[1].y], [200, 100]);
  v.dispose();
});

test('in control: "Forms may go to" picks one site of the list, none first; only for the page in control', async () => {
  const {v, calls} = controlled();
  v.control({state: 'person', epoch: 2, mine: true, sites: ['portal.example', 'login.example']});
  const ctl = find(v.el, 'bview-ctl');
  const sends = find(ctl, 'bview-ctl-sends');
  assert.equal(sends.hidden, false);
  const sel = find(ctl, 'bview-send');
  assert.equal(sel.tag, 'select');
  assert.deepEqual(sel.children.map(o => [o.value, o.textContent]), [['', 'No site (look and click only)'], ['portal.example', 'portal.example'], ['login.example', 'login.example']]);
  assert.equal(sel.value, '');
  assert.match(words(sends), /To sign in, pick the site first: until then nothing you send leaves the browser\./);
  sel.value = 'portal.example';
  for (const f of sel.listeners.change) await f({});
  assert.deepEqual(calls.at(-1), ['allow', 'portal.example']);
  v.control({state: 'person', epoch: 2, mine: true, sites: ['portal.example', 'login.example'], send_site: 'portal.example'});
  assert.match(words(find(ctl, 'bview-ctl-sends')), /Forms you send to portal\.example go through while you are in control; each one is noted on the ticket\./);
  assert.equal(find(ctl, 'bview-send').value, 'portal.example');
  // a refusal puts the old value back and says why
  const sel2 = find(ctl, 'bview-send');
  sel2.value = 'evil.test';
  for (const f of sel2.listeners.change) await f({});
  assert.equal(sel2.value, 'portal.example');
  assert.match(words(find(ctl, 'bview-ctl-note')), /Pick a site/);
  // no list: the choice is off and says how to get one
  v.control({state: 'person', epoch: 2, mine: true, sites: []});
  assert.equal(find(ctl, 'bview-send').disabled, true);
  assert.match(words(find(ctl, 'bview-ctl-sends')), /add the site to this ticket’s list first/);
  // another page in control, paused, the helper: no choice
  for (const s of [{state: 'person', epoch: 3, mine: false}, {state: 'paused', epoch: 4}, {state: 'helper', epoch: 5}]) {
    v.control(s);
    assert.equal(find(ctl, 'bview-ctl-sends').hidden, true);
  }
  v.dispose();
});
