// ORCH-555: components.js menus() gives menuitem roles only inside a real menu. A pop that is not a menu (the Start
// choice is a group, Triage is a dialog) keeps its buttons as buttons, also when it is drawn with its body already in it
// (a redraw while open), and its trigger does not announce a menu.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM: enough selectors for menus() (tag, .class, tag.class, tag[attr], [attr=value], comma lists).
class N {
  constructor(tag, cls = '', attrs = {}) { Object.assign(this, {tagName: tag.toUpperCase(), className: cls, attrs: {...attrs}, children: [], parent: null, dataset: {}, listeners: {}, open: false, disabled: false}); }
  append(...c) { c.forEach(x => { x.parent = this; this.children.push(x); }); return this; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  getClientRects() { return [1]; }
  one(sel) {
    return sel.split(',').some(s => {
      const m = /^([a-z]*)(?:\.([\w-]+))?(?:\[([\w-]+)(?:=([\w-]+))?\])?$/.exec(s.trim());
      if (!m) throw new Error('selector not handled: ' + s);
      const [, tag, cls, attr, val] = m;
      return (!tag || this.tagName === tag.toUpperCase()) && (!cls || this.className.split(' ').includes(cls))
        && (!attr || (attr in this.attrs && (val == null || this.attrs[attr] === val)));
    });
  }
  matches(sel) { return this.one(sel); }
  querySelectorAll(sel) { const out = []; const walk = n => n.children.forEach(c => { if (c.one(sel)) out.push(c); walk(c); }); walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  contains(n) { for (; n; n = n.parent) if (n === this) return true; return false; }
}

function load() {
  const body = new N('body');
  let ready = null, observed = null;
  globalThis.window = {};
  globalThis.document = Object.assign(body, {body, activeElement: null, addEventListener(t, f) { if (t === 'DOMContentLoaded') ready = f; }});
  globalThis.MutationObserver = class { constructor(f) { observed = f; } observe() {} };
  delete require.cache[require.resolve('../static/components.js')];
  require('../static/components.js');
  ready();
  return {body, redraw: () => observed()};
}

const pop = (cls, attrs, ...buttons) => new N('div', cls, attrs).append(...buttons.map(b => new N('button', '', {'aria-label': b})));
const details = (...kids) => new N('details', 'menu').append(new N('summary'), ...kids);

test('a pop with no role becomes a menu and its buttons menuitems', () => {
  const {body, redraw} = load();
  const d = details(pop('menu-pop', {}, 'Stop', 'Move'));
  body.append(d);
  redraw();
  assert.equal(d.children[1].getAttribute('role'), 'menu');
  assert.deepEqual(d.children[1].children.map(b => b.getAttribute('role')), ['menuitem', 'menuitem']);
  assert.equal(d.children[0].getAttribute('aria-haspopup'), 'menu');
});

test('a details that is itself the menu still gets menuitems', () => {
  const {body, redraw} = load();
  const d = new N('details', 'dropdown').append(new N('summary'), new N('button'));
  body.append(d);
  redraw();
  assert.equal(d.children[1].getAttribute('role'), 'menuitem');
});

test('the Start choice (a group) drawn with its body already in it keeps its buttons and announces no menu', () => {
  const {body, redraw} = load();
  const d = details(pop('menu-pop start-pop', {role: 'group'}, 'Fresh start on ORCH-12', 'Claude Code'));
  d.open = true;
  body.append(d);
  redraw();
  assert.deepEqual(d.children[1].children.map(b => b.getAttribute('role')), [null, null]);
  assert.equal(d.children[0].hasAttribute('aria-haspopup'), false);
});

test('a dialog pop keeps its buttons and its trigger says dialog', () => {
  const {body, redraw} = load();
  const d = details(pop('menu-pop', {role: 'dialog'}, 'Start triage'));
  body.append(d);
  redraw();
  assert.equal(d.children[1].children[0].getAttribute('role'), null);
  assert.equal(d.children[0].getAttribute('aria-haspopup'), 'dialog');
});

test('focus that leaves an open menu (Tab) closes it; focus moving inside keeps it open', () => {
  const {body, redraw} = load();
  const d = details(pop('menu-pop', {}, 'Stop', 'Move'));
  const outside = new N('button');
  body.append(d, outside);
  redraw();
  const leave = to => d.listeners.focusout.forEach(f => f({relatedTarget: to}));
  d.open = true;
  leave(d.children[1].children[1]);
  assert.equal(d.open, true);
  leave(null); // the window lost focus: the menu stays as it was
  assert.equal(d.open, true);
  leave(outside);
  assert.equal(d.open, false);
});
