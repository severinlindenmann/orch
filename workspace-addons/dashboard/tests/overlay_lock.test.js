// Owner feedback 14 Nov fb27: a modal dialog that leaves the page without a close event (a re-render removes it)
// must not leave the page locked (no scrolling) for good.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  class FakeDialog {
    constructor() { this.open = false; this.isConnected = true; this.dataset = {}; this.classList = {add() {}, remove() {}, contains() { return false; }}; this.listeners = {}; }
    setAttribute() {} hasAttribute() { return true; } querySelector() { return null; } prepend() {}
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
    showModal() { this.open = true; }
    close() { this.open = false; for (const fn of this.listeners.close || []) fn(); }
    remove() { this.isConnected = false; }  // no close event, like a node taken out by a re-render
  }
  const observers = [];
  const html = {style:{overflow:''}};
  const win = {addEventListener() {}};
  const ready = [];
  const ctx = vm.createContext({
    window:win, HTMLDialogElement:FakeDialog, matchMedia:() => ({matches:true}), setTimeout:fn => { fn(); return 1; },
    MutationObserver:class { constructor(fn) { observers.push(fn); } observe() {} },
    document:{documentElement:html, addEventListener:(type, fn) => { if (type === 'DOMContentLoaded') ready.push(fn); }, querySelectorAll:() => [], createElement:() => new FakeDialog(), querySelector:() => null, activeElement:null, body:{}},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/kit/overlay.js'), 'utf8'), ctx);
  ready.forEach(fn => fn());  // the page is loaded: the watcher on the document is started
  return {FakeDialog, html, observers};
}

test('a dialog closed the normal way gives the page its scrolling back', () => {
  const {FakeDialog, html} = setup();
  const d = new FakeDialog(); d.showModal();
  assert.equal(html.style.overflow, 'hidden');
  d.close();
  assert.equal(html.style.overflow, '');
});

test('a dialog taken out of the page while open gives the page its scrolling back', () => {
  const {FakeDialog, html, observers} = setup();
  const d = new FakeDialog(); d.showModal();
  assert.equal(html.style.overflow, 'hidden');
  d.remove();
  observers.forEach(fn => fn([]));
  assert.equal(html.style.overflow, '');
});

test('a dead dialog left in the list never blocks the next one from restoring the page', () => {
  const {FakeDialog, html} = setup();
  const a = new FakeDialog(); a.showModal(); a.remove();
  const b = new FakeDialog(); b.showModal();
  b.close();
  assert.equal(html.style.overflow, '');
});
