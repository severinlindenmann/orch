const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* The composer with a tiny fake DOM: draws the waiting-message pin and runs its Take back button. */
function composer(actResult) {
  const mk = (tag, attrs, ...kids) => {
    const n = {tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), dataset: {}, style: {}, handlers: {}, hidden: !!(attrs && attrs.hidden), value: '', scrollHeight: 10, disabled: false,
      addEventListener(e, f) { this.handlers[e] = f; }, replaceChildren(...k) { this.kids = k; }, before() {}, prepend() {}, append(...k) { this.kids.push(...k); }, focus() {}};
    return n;
  };
  const text = n => !n || typeof n !== 'object' ? '' : [n.attrs.text || '', ...n.kids.map(text)].join(' ');
  const toasts = [], acts = [];
  const els = {msg: mk('textarea'), form: mk('form'), compose: mk('div')};
  let pinned = null;
  els.form.classList = {toggle() {}};
  els.form.before = n => { pinned = n; };
  els.form.querySelector = () => mk('button');
  const ctx = vm.createContext({window: {}, document: {addEventListener() {}}, FileReader: class {}});
  const S = {h: mk, TID: 't_x1', toast: (t, k) => toasts.push([t, k]), els, act: async (op, a) => { acts.push([op, a]); return actResult; }, register: (n, m) => { S.views[n] = m; }, views: {}, root: mk('div')};
  ctx.window.FocusStore = S;
  const file = path.join(__dirname, '../src/orch_focus/web/compose.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  S.views.compose.mount();
  return {S, els, toasts, acts, text, pin: () => pinned, draw: v => S.views.compose.renderWaiting(v)};
}
const view = list => ({run: {waiting_input: list}});
const msg = {id: 'p_abc12345', text: 'Use the spring photo', at: '2026-11-15T10:00:00Z'};

test('a waiting message is pinned above the box with one Take back button', () => {
  const c = composer({ok: true});
  c.draw(view([msg]));
  assert.equal(c.pin().hidden, false);
  assert.match(c.text(c.pin()), /Use the spring photo/);
  assert.match(c.text(c.pin()), /Helper reads this after the current step/);
  assert.match(c.text(c.pin()), /Take back/);
  c.draw(view([]));
  assert.equal(c.pin().hidden, true);
});

test('Take back puts the text back into the box and says so', async () => {
  const c = composer({ok: true});
  c.draw(view([msg]));
  c.els.msg.value = 'and more';
  const btn = c.pin().kids[0].kids[1].kids[1];
  await btn.handlers.click();
  assert.equal(JSON.stringify(c.acts), JSON.stringify([['run.take_back', {ticket: 't_x1', id: 'p_abc12345'}]]));
  assert.equal(c.els.msg.value, 'Use the spring photo\nand more');
  assert.deepEqual(c.toasts, [['Taken back. The helper never saw it.', 'ok']]);
});

test('a refusal shows the sentence and keeps the pin and the box', async () => {
  const sentence = 'The helper already read this message; send a correction instead.';
  const c = composer({ok: false, status: 422, message: sentence});
  c.draw(view([msg]));
  const btn = c.pin().kids[0].kids[1].kids[1];
  await btn.handlers.click();
  assert.deepEqual(c.toasts, [[sentence, 'error']]);
  assert.equal(c.els.msg.value, '');
  assert.equal(btn.disabled, false);
});
