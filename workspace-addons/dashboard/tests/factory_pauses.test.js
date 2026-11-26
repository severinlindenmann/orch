'use strict';
// ORCH-2065: Factory's Pauses row says what the record says today and saves nothing. Its one action, Change in Chat,
// opens Chat with a suggestion (orch.say); the dashboard side (chat.test.js) keeps a typed draft and never sends.
// Runs the real factory.js on a small element shim with sample records only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const SRC = fs.readFileSync(path.join(__dirname, '../../factory/src/orch_factory/web/factory.js'), 'utf8');

class El {
  constructor(tag) {
    Object.assign(this, {tagName:tag.toUpperCase(), children:[], attrs:{}, dataset:{}, style:{}, listeners:{}, hidden:false, className:'', _text:''});
    this.classList = {add:c => { this.className = (this.className + ' ' + c).trim(); }, remove(){}, contains:c => this.className.split(' ').includes(c)};
  }
  append(...k) { for (const c of k) this.children.push(typeof c === 'string' ? Object.assign(new El('#text'), {_text:c}) : c); }
  prepend(...k) { this.children.unshift(...k); }
  replaceChildren(...k) { this.children = []; this.append(...k); }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn({preventDefault(){}}); }
  focus() {}
  get childNodes() { return this.children; }
  all() { return [this, ...this.children.flatMap(c => c.all())]; }
  querySelectorAll(sel) {
    const m = /^\.([\w-]+)$/.exec(sel), t = /^([a-z0-9]+)$/.exec(sel);
    return this.all().slice(1).filter(e => m ? e.classList.contains(m[1]) : t ? e.tagName === t[1].toUpperCase() : false);
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

async function page(home, embedded = true) {
  const els = {'factory-view':new El('div'), notices:new El('div'), content:new El('main')};
  const posts = [], fetched = [];
  const win = {addEventListener(){}, parent:null, OrchFrame:{chan:'c1'}};
  win.parent = {postMessage:(m, o) => posts.push([m, o])};
  win.top = embedded ? {} : win;
  const c = {window:win, document:{documentElement:{dataset:{prefix:''}}, getElementById:id => els[id] || null, createElement:t => new El(t),
      createTextNode:t => Object.assign(new El('#text'), {_text:t}), querySelector:s => s === '.skip-link' ? new El('a') : null, visibilityState:'visible', title:'', activeElement:null},
    location:{hash:'', origin:'http://x'}, fetch:async (u, o = {}) => { fetched.push([u, o.method || 'GET']); return {ok:true, json:async () => home}; },
    AbortController:class { constructor() { this.signal = {}; } abort(){} }, setTimeout, clearTimeout, setInterval:() => 0, crypto:globalThis.crypto, Date, Math, Number, JSON, URL};
  vm.createContext(c);
  vm.runInContext(SRC, c);
  await new Promise(r => setTimeout(r, 20));
  const row = els['factory-view'].querySelector('.f-pauses');
  return {row, posts, fetched, view:els['factory-view']};
}
const until = new Date(Date.now() + 3 * 864e5).toISOString();
const sample = auto => ({orders:[{id:'t_sample01', title:'Opening hours page', phase:'draft'}], autopilot:auto, watcher:true, workspace:'Sample'});

test('no Autopilot: the row says Factory waits at every pause, with one secondary Change in Chat button and no switch', async () => {
  const {row, view} = await page(sample(null));
  assert.match(row.textContent, /^PausesFactory waits for your OK at every pause\.Opens Chat\. Nothing is sent until you press Send\.Change in Chat$/);
  assert.equal(view.querySelectorAll('input').length, 0, 'no switch that only looks like a setting');
  const [button] = row.querySelectorAll('button');
  assert.equal(button.type, 'button', 'a real button: Enter and Space both press it');
  assert.equal(button.className, 'btn outline sm f-btn', 'secondary, never the filled main action');
  assert.equal(button.getAttribute('aria-describedby'), 'f-pauses-hint');
});

test('an ended Autopilot reads as no Autopilot', async () => {
  const {row} = await page(sample({on:false, until:'2026-11-01T10:00:00Z', decided_today:0}));
  assert.match(row.textContent, /Factory waits for your OK at every pause\./);
  assert.doesNotMatch(row.textContent, /Autopilot may/);
});

test('an active Autopilot keeps its limits: routine pauses only, until its end; putting it live still waits', async () => {
  const {row, view} = await page(sample({on:true, until, decided_today:2}));
  assert.match(row.textContent, /Autopilot may answer routine pauses until .+\./);
  assert.match(row.textContent, /Putting it live, and anything that can't be undone, still waits for your OK\./);
  assert.doesNotMatch(view.textContent, /run to the end|without pauses|every order/i);
  assert.equal(view.textContent.split('routine pauses').length - 1, 1, 'said once on the page, not again in the Autopilot card');
});

test('Change in Chat only asks the dashboard to open Chat with a suggestion; it saves and sends nothing', async () => {
  for (const [auto, words] of [[null, 'Factory: I would like Autopilot to answer routine pauses. What would it cover?'],
    [{on:true, until, decided_today:0}, 'Factory: I would like to be asked at every pause again.']]) {
    const {row, posts, fetched} = await page(sample(auto));
    const before = row.textContent;
    row.querySelector('button').click();
    assert.deepEqual(JSON.parse(JSON.stringify(posts)), [[{type:'orch.say', text:words, chan:'c1'}, 'http://x']]);
    assert.ok(fetched.every(([, method]) => method === 'GET'), 'no write');
    assert.equal(row.textContent, before, 'the row does not flip: nothing changed');
  }
});

test('outside the dashboard Change in Chat is a link to Chat, not a dead button', async () => {
  const {row, posts} = await page(sample(null), false);
  const a = row.querySelector('a');
  assert.equal(a.href, '/#chat'); assert.equal(a.target, '_top'); assert.equal(a.textContent, 'Change in Chat');
  assert.equal(posts.length, 0);
});
