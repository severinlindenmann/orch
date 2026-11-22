'use strict';
// ORCH-1359: a toast never covers what a page marks [data-toast-clear] near the bottom of the screen (the Focus bar,
// a layer's message box). UI.toastPlace in the kit (workspace/src/orch_ui/static/components.js) moves it up.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const KIT = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.js'), 'utf8');
const VH = 800;
const rect = (top, height, width = 1000) => ({top, bottom:top + height, left:0, right:width, width, height});

// host: the toast stack (bottom 24 px by its CSS, 50 px high unless a page rule moved it up); marks: rects of the
// [data-toast-clear] elements.
function place(marks, {hostTop = VH - 24 - 50, inDialog = false} = {}) {
  const body = {};
  const host = {firstChild:{}, parentElement:inDialog ? {} : body, style:{bottom:''},
    getBoundingClientRect() { const b = parseFloat(this.style.bottom); return b ? rect(VH - b - 50, 50, 400) : rect(hostTop, 50, 400); }};
  const els = marks.map(r => ({getBoundingClientRect:() => r}));
  const document = {body, documentElement:{clientHeight:VH}, addEventListener() {},
    querySelector:s => s === '#ui-toasts' ? host : null,
    querySelectorAll:s => s === '[data-toast-clear]' ? els : []};
  const c = {window:{}, document, navigator:{}, setTimeout, clearTimeout, innerHeight:VH};
  vm.createContext(c); vm.runInContext(KIT, c);
  c.window.UI.toastPlace();
  return host.style.bottom;
}

test('the toast moves up above the Focus bar at the bottom', () => {
  assert.equal(place([rect(VH - 44, 44)]), 44 + 8 + 'px');
});

test('with the bottom panel open it moves above the whole panel', () => {
  assert.equal(place([rect(VH - 44, 44), rect(VH - 44 - 360, 360), rect(VH - 44 - 90, 80)]), 44 + 360 + 8 + 'px');
});

test('a full-height panel is left out: the toast goes just above the message box', () => {
  // full screen: the bar at the top, the panel fills the screen, the message box at the bottom
  assert.equal(place([rect(0, 44), rect(44, VH - 44), rect(VH - 110, 100)]), 110 + 8 + 'px');
});

test('nothing near the bottom, a toast at the top or in a dialog: it stays where its CSS puts it', () => {
  assert.equal(place([]), '');
  assert.equal(place([rect(VH / 2 - 20, 40)]), '', 'the side tab in the middle of the screen');
  assert.equal(place([rect(VH - 44, 44)], {hostTop:16}), '', 'a page rule put the toast at the top');
  assert.equal(place([rect(VH - 44, 44)], {inDialog:true}), '', 'a toast inside an open dialog');
});

test('the toast places itself when shown and when the window changes size', () => {
  assert.match(KIT, /host\.append\(box\);UI\.toastPlace\(\);/);
  assert.match(KIT, /addEventListener\('resize',\(\)=>UI\.toastPlace\(\)\)/);
});
