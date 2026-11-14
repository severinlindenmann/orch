// fb17: the terminal renderer and the key mapping of term.js, run on a tiny fake DOM.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function el(tag) {
  const n = {tag, className: '', kids: [], get childNodes() { return this.kids; }, textContent: '', append(...k) { for (const x of k) this.kids.push(x); }};
  return n;
}
function load() {
  const registered = {};
  const context = vm.createContext({
    window: {FocusStore: {h: (tag, attrs, ...kids) => { const n = el(tag); n.className = (attrs && attrs.class) || ''; n.textContent = (attrs && attrs.text) || ''; n.append(...kids.flat()); return n; }, TID: 't_term0001', register: (k, v) => { registered[k] = v; }}},
    document: {}, setInterval: () => {},
  });
  const file = path.join(__dirname, '../src/orch_focus/web/term.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), context, {filename: file});
  return registered.term;
}
const flat = rows => rows.map(r => r.kids.map(s => s.className + '|' + s.textContent));

test('colours, bold and reverse come out as classes, the cursor as one block', () => {
  const T = load();
  const rows = T.paint('\x1b[31mred\x1b[0m plain\n\x1b[1;32mok\x1b[0m', 1, 0, true);
  const first = flat(rows)[0];
  assert.ok(first.some(s => s.startsWith('t-seg t-c1') && s.endsWith('|r')), first.join());  /* "r" is split off by the cursor */
  assert.ok(first.some(s => s.includes('t-cur') && s.endsWith('|e')));
  assert.ok(flat(rows)[1].some(s => s.includes('t-c2') && s.includes('t-b') && s.endsWith('|ok')));
});

test('an empty line keeps its height and text is never parsed as markup', () => {
  const T = load();
  const rows = T.paint('<b>x</b>\n\n', 0, 5, false);
  assert.equal(rows.length, 3);
  assert.equal(rows[0].kids[0].textContent, '<b>x</b>');
  assert.equal(rows[1].kids[0].textContent, ' ');
});

test('keys: text is literal, names come from the list, Shift+Tab and other chords are not ours', () => {
  const T = load();
  assert.deepEqual({...T.toItem({key: 'a'})}, {t: 'a'});
  assert.deepEqual({...T.toItem({key: 'Enter'})}, {k: 'Enter'});
  assert.deepEqual({...T.toItem({key: 'Backspace'})}, {k: 'BSpace'});
  assert.deepEqual({...T.toItem({key: 'c', ctrlKey: true})}, {k: 'C-c'});
  assert.equal(T.toItem({key: 'v', ctrlKey: true}), null);
  assert.equal(T.toItem({key: 'Tab', shiftKey: true}), null);
  assert.equal(T.toItem({key: 'a', metaKey: true}), null);
  assert.equal(T.toItem({key: 'F5'}), null);
});

test('typed letters are merged into one text item, other keys stay apart', () => {
  const T = load();
  const out = T.merge([{t: 'h'}, {t: 'i'}, {k: 'Enter'}, {t: '!'}]);
  assert.deepEqual(JSON.parse(JSON.stringify(out)), [{t: 'hi'}, {k: 'Enter'}, {t: '!'}]);
});

test('typing state, ordered sends, batch limits and the waiting line are in term.js', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_focus/web/term.js'), 'utf8');
  assert.match(src, /Typing into the helper’s session/);
  assert.match(src, /chain = chain\.then\(flush, flush\)/);
  assert.match(src, /items\.length < 40 && size \+ \(all\[0\]\.t \|\| ''\)\.length <= 12000/);
  assert.match(src, /Your helper is waiting for an answer in its session/);
  assert.match(src, /status === 409/);
});
