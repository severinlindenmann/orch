import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// UI.swipeDeck (widgets.js) on a tiny DOM: enough to build the deck, press its buttons and read what it shows.
// ORCH-183 (persona test 17 Nov): Send back on a Check card opens the text box, Undo is only offered while it works,
// a Check card shows its own files.
class N {
  constructor(tag) { Object.assign(this, {tag, children: [], parent: null, attrs: {}, dataset: {}, className: '', own: '', hidden: false, inert: false, listeners: {}, style: {setProperty() {}}, clientWidth: 0, clientHeight: 0, offsetWidth: 0, value: ''}); }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this.children = []; }
  get content() { return this._frag ||= new N('#fragment'); }
  get classList() { const n = this, list = () => n.className.split(' ').filter(Boolean);
    return {add: (...c) => { n.className = [...new Set([...list(), ...c])].join(' '); }, remove: (...c) => { n.className = list().filter(x => !c.includes(x)).join(' '); },
      contains: c => list().includes(c), toggle: (c, f) => { const on = f ?? !list().includes(c); on ? n.classList.add(c) : n.classList.remove(c); return on; }}; }
  get offsetParent() { return this.hidden ? null : {}; }
  get lastChild() { return this.children[this.children.length - 1]; }
  get firstChild() { return this.children[0]; }
  adopt(c) { if (!(c instanceof N)) c = Object.assign(new N("#text"), {own: String(c)}); if (c.tag === '#fragment') return c.children.splice(0).flatMap(x => { x.parent = null; return this.adopt(x); }); c.parent?.children.splice(c.parent.children.indexOf(c), 1); c.parent = this; return [c]; }
  append(...c) { c.forEach(x => this.children.push(...this.adopt(x))); }
  prepend(...c) { c.reverse().forEach(x => this.children.unshift(...this.adopt(x))); }
  replaceChildren(...c) { this.children.forEach(x => { x.parent = null; }); this.children = []; this.own = ''; this.append(...c); }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  removeEventListener() {}
  focus() { doc.activeElement = this; }
  setPointerCapture() {}
  getBoundingClientRect() { return {left: 0, top: 0, width: 0, height: 0}; }
  click() { if (this.disabled) return; this.onclick?.({stopPropagation() {}, detail: 1}); (this.listeners.click || []).forEach(f => f({stopPropagation() {}})); }
  matches(sel) { return sel.split(',').some(one => { const last = one.trim().split(/\s+/).pop().replace(/:not\([^)]*\)/g, '');
    const tag = /^[a-z]+/.exec(last)?.[0], cls = [...last.matchAll(/\.([\w-]+)/g)].map(m => m[1]), at = [...last.matchAll(/\[([\w-]+)\]/g)].map(m => m[1]);
    return (!tag || this.tag === tag) && cls.every(c => this.classList.contains(c)) && at.every(a => a in this.attrs || (a === 'href' && this.href)); }); }
  querySelectorAll(sel) { const out = []; const walk = n => n.children.forEach(c => { if (c.matches(sel)) out.push(c); walk(c); }); walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) { let n = this; while (n) { if (n.matches?.(sel)) return n; n = n.parent; } return null; }
}
const doc = {createElement: t => new N(t), createElementNS: (_, t) => new N(t), createDocumentFragment: () => new N('#fragment'), activeElement: null, body: new N('body')};

function deck(items, o = {}) {
  const toasts = [], UI = {toast: (m, undo) => toasts.push({m, undo}), statusIcon: () => new N('span')};
  const window = {UI};
  vm.runInNewContext(readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8'), {window, document: doc, setTimeout, clearTimeout, performance, console, Promise});
  const host = new N('section'), decided = [];
  const d = UI.swipeDeck(host, items, {mode: 'desk', voice: false, onDecide: (it, v, note) => decided.push({id: it.id, v, note}), ...o});
  const [top, , acts] = host.children, [noBtn, talkBtn, okBtn] = acts.children, undoBtn = top.children[4], note = top.children[1];
  return {d, host, decided, toasts, noBtn, talkBtn, okBtn, undoBtn, note};
}
const wait = ms => new Promise(r => setTimeout(r, ms));
const check = (id, extra = {}) => ({id, kind: 'check', kindLabel: 'Check', title: 'Spring catalogue ' + id, okLabel: 'Looks good', preview: {type: 'doc', heading: 'What was done', paras: ['In short: done.']}, ...extra});
const draft = id => ({id, kind: 'draft', kindLabel: 'Draft', title: 'Home block ' + id, preview: {type: 'doc', heading: 'Words', paras: ['x']}});

test('a Check card: Send back opens the text box (nothing is sent without words), no second Comment button', async () => {
  const {d, host, decided, noBtn, talkBtn} = deck([check('a'), check('b')]);
  assert.equal(noBtn.textContent.includes('Send back'), true);
  assert.equal(talkBtn.hidden, true, 'Comment would open the same box: left out on a Check card');
  noBtn.click();
  const sheet = host.querySelector('.swipe-sheet');
  assert.ok(sheet, 'the text box opens');
  assert.equal(d.busy, true);
  assert.equal(decided.length, 0, 'nothing sent yet');
  const ta = sheet.querySelector('textarea'), send = sheet.querySelectorAll('button').find(b => b.textContent === 'Send back for changes');
  assert.equal(send.disabled, true, 'no words: cannot send');
  ta.value = 'Use the new logo'; ta.listeners.input.forEach(f => f());
  assert.equal(send.disabled, false);
  send.click(); await wait(260);
  assert.equal(decided.length, 1);
  assert.equal(decided[0].v, 'talk');
  assert.equal(decided[0].note.changes.text, 'Use the new logo');
});

test('a draft card keeps Don\'t do (sent at once) and its own Comment button', async () => {
  const {decided, noBtn, talkBtn} = deck([draft('a'), draft('b')]);
  assert.equal(talkBtn.hidden, false);
  assert.match(noBtn.textContent, /Don't do/);
  noBtn.click(); await wait(160);
  assert.deepEqual(decided.map(x => x.v), ['no']);
});

test('Undo is offered only while canUndo says the answer can still be taken back', async () => {
  let open = true; const undone = [];
  const {d, undoBtn, okBtn, toasts} = deck([check('a'), check('b')], {canUndo: () => open, onUndo: it => undone.push(it.id)});
  assert.equal(undoBtn.disabled, true, 'nothing to undo yet');
  okBtn.click(); await wait(160);
  assert.equal(undoBtn.disabled, false, 'held: Undo works');
  open = false; d.syncUndo();
  assert.equal(undoBtn.disabled, true, 'saved: Undo is off');
  d.undo();
  assert.deepEqual(undone, [], 'a saved answer is not taken back on screen only');
  assert.equal(toasts.length, 0, 'no floating box: what happened shows in the deck top row');
  open = true; d.syncUndo(); undoBtn.click();
  assert.deepEqual(undone, ['a']);
  assert.equal(d.index, 0, 'back on the card');
});

test('a Check card shows its own files as tiles that open them', () => {
  const {host} = deck([check('a', {files: [{label: 'Cover photo', type: 'img', src: '/api/file?t=t_x&k=evidence&n=shop.png'}, {label: 'Result', type: 'page', src: '/view/t_x/evidence/result.html'}, {label: 'No src', type: 'img', src: ''}]})]);
  const tiles = host.querySelectorAll('.swipe-file');
  assert.deepEqual(tiles.map(t => t.href), ['/api/file?t=t_x&k=evidence&n=shop.png', '/view/t_x/evidence/result.html']);
  assert.deepEqual(tiles.map(t => t.target), ['_blank', '_blank']);
  assert.equal(tiles[0].querySelector('img').src, '/api/file?t=t_x&k=evidence&n=shop.png');
  assert.equal(tiles[1].querySelector('iframe').getAttribute('sandbox'), '', 'a page only in a sandboxed frame');
  assert.equal(deck([check('b')]).host.querySelector('.swipe-files'), null, 'no files: no empty row');
});

test('a card with its own answers (a Factory start): its buttons in place of the three, all outlined, each answers with its pick', async () => {
  const fac = {id:'f', kind:'choice', kindLabel:'Choose', title:"Start 'Loyalty card'?", preview:{type:'doc'}, answers:[{label:'Not now', picked:'Not now'}, {label:'Change it', picked:'Edit'}, {label:'Start', picked:'Start'}]};
  const {host, decided, noBtn, talkBtn, okBtn} = deck([fac, draft('b')]);
  assert.deepEqual([noBtn.hidden, talkBtn.hidden, okBtn.hidden], [true, true, true]);
  const own = host.querySelector('.swipe-own');
  assert.equal(own.hidden, false);
  const btns = own.children;
  assert.deepEqual(btns.map(b => b.textContent), ['Not now', 'Change it', 'Start']);
  assert.ok(btns.every(b => b.className === 'swipe-act own'), 'the same answer button as every card, none filled: starting a helper is never the easiest click');
  host.listeners.keydown.forEach(f => f({key:'ArrowRight', target:host, preventDefault() {}}));
  await wait(160);
  assert.equal(decided.length, 0, 'the arrow keys do not pick for the person');
  btns[1].click(); await wait(160);
  assert.deepEqual(JSON.parse(JSON.stringify(decided)), [{id:'f', v:'ok', note:{picked:'Edit'}}]);
  assert.equal(own.hidden, true, 'the next card has the usual three answers');
});

test('ORCH-1108: a stuck card has only its own buttons (Nudge, Start fresh) and an Open link in the page; none at all is still no Looks good', async () => {
  const stuck = {id:'s', kind:'stuck', kindLabel:'Stuck', title:'The checks of step 2 failed 3 times.', href:'#ticket/t_abc123', preview:{type:'doc'}, answers:[{label:'Nudge', picked:'nudge'}, {label:'Start fresh', picked:'fresh'}]};
  const bare = {id:'p', kind:'stuck', kindLabel:'Stuck', title:'The helper waits for your OK on its screen.', href:'#ticket/t_abc124', preview:{type:'doc'}};
  const {host, decided, noBtn, talkBtn, okBtn} = deck([stuck, bare]);
  assert.deepEqual([noBtn.hidden, talkBtn.hidden, okBtn.hidden], [true, true, true]);
  const open = host.querySelectorAll('.swipe-here').find(a => !a.closest('.swipe-card').className.includes('under'));
  assert.equal(open.href, '#ticket/t_abc123');
  assert.equal(open.target, undefined, 'the ticket opens in the same tab');
  const own = host.querySelector('.swipe-own');
  assert.deepEqual(own.children.map(b => b.textContent), ['Nudge', 'Start fresh']);
  host.listeners.keydown.forEach(f => f({key:'ArrowRight', target:host, preventDefault() {}}));
  await wait(160);
  assert.equal(decided.length, 0, 'the arrow keys do not nudge for the person');
  own.children[0].click(); await wait(160);
  assert.deepEqual(JSON.parse(JSON.stringify(decided)), [{id:'s', v:'ok', note:{picked:'nudge'}}]);
  assert.deepEqual([noBtn.hidden, talkBtn.hidden, okBtn.hidden, own.hidden], [true, true, true, true], 'no buttons of its own: Open and Later only');
  host.listeners.keydown.forEach(f => f({key:'ArrowRight', target:host, preventDefault() {}}));
  await wait(160);
  assert.equal(decided.length, 1, 'no Looks good by key either');
});

test('a merge card box: the checks as a status pill, rows with key and number, a small footer (ORCH-183)', () => {
  const pv = {type:'doc', heading:'What goes out · 2 changes', status:{tone:'failed', text:'1 check failed: lint · checked 11:02'},
    paras:['Merging now would put work live that failed a check.'], rows:[{title:'Bigger pictures', n:1168, key:'ORCH-172'}, {title:'and 1 other commit'}], foot:'Exact version: 89984e4'};
  const {host} = deck([{id:'m', kind:'link', kindLabel:'Publish', title:'Release 32', okLabel:'Merge', preview:pv}]);
  const box = host.querySelector('.swipe-preview .doc');
  const st = box.querySelector('.doc-status');
  assert.ok(st.classList.contains('failed'), 'a failed check is red');
  assert.match(st.textContent, /1 check failed: lint/);
  const rows = box.querySelectorAll('.doc-row');
  assert.deepEqual(rows.map(r => r.querySelector('.doc-row-title').textContent), ['Bigger pictures', 'and 1 other commit']);
  assert.equal(rows[0].querySelector('.doc-row-key').textContent, 'ORCH-172');
  assert.equal(rows[0].querySelector('.doc-row-n').textContent, '#1168');
  assert.equal(rows[1].querySelector('.doc-row-key'), null);
  assert.equal(box.querySelector('.doc-foot').textContent, 'Exact version: 89984e4');
  assert.equal(box.children[0], st, 'the checks come first');
});

test('ORCH-246: on a question with options the words box sends my answer, not "Send back for changes"', () => {
  const q = {id: 'q', kind: 'choice', kindLabel: 'Choice', title: 'Which layout?', preview: {type: 'options', options: [{id: 'A', title: 'One'}, {id: 'B', title: 'Two'}]}};
  const {host, talkBtn} = deck([q]);
  talkBtn.click();
  const labels = host.querySelector('.swipe-sheet').querySelectorAll('button').map(b => b.textContent);
  assert.ok(labels.includes('Send my answer'));
  assert.ok(!labels.includes('Send back for changes'));
});

test('ORCH-295: Add note saves the words, answers nothing, and keeps the card; Send back stays its own button', async () => {
  const notes = [];
  const {d, host, decided, talkBtn} = deck([draft('a'), draft('b')], {onNote: async (it, text) => { notes.push({id: it.id, text}); return {ok: true}; }});
  talkBtn.click();
  const sheet = host.querySelector('.swipe-sheet'), ta = sheet.querySelector('textarea');
  const add = sheet.querySelectorAll('button').find(b => b.textContent === 'Add note');
  const back = sheet.querySelectorAll('button').find(b => b.textContent === 'Send back for changes');
  assert.ok(add && back && add !== back, 'two different buttons');
  assert.equal(add.disabled, true, 'no words: no note');
  ta.value = 'Please also check the footer'; ta.listeners.input.forEach(f => f());
  add.click(); await wait(20);
  assert.deepEqual(notes, [{id: 'a', text: 'Please also check the footer'}]);
  assert.equal(decided.length, 0, 'no verdict: the card is not answered');
  assert.equal(host.querySelector('.swipe-sheet'), null, 'the sheet closes');
  assert.equal(d.index, 0, 'the same card stays on top');
});

test('ORCH-295: a failed note keeps the sheet and the words', async () => {
  const {host, decided, talkBtn} = deck([draft('a')], {onNote: async () => ({ok: false, error: {message: 'Could not save the note.'}})});
  talkBtn.click();
  const sheet = host.querySelector('.swipe-sheet'), ta = sheet.querySelector('textarea');
  ta.value = 'hello'; ta.listeners.input.forEach(f => f());
  sheet.querySelectorAll('button').find(b => b.textContent === 'Add note').click(); await wait(20);
  assert.ok(host.querySelector('.swipe-sheet'), 'still open');
  assert.equal(ta.value, 'hello');
  assert.equal(decided.length, 0);
});

test('ORCH-295: without onNote there is no Add note button', () => {
  const {host, talkBtn} = deck([draft('a')]);
  talkBtn.click();
  assert.equal(host.querySelectorAll('button').some(b => b.textContent === 'Add note'), false);
});
test('what just happened is one line in the top row, a long title goes by its ticket, never cut mid-word (ORCH-421)', async () => {
  const long = {...check('a'), title: 'Move every summer and autumn product photo to the new picture service and check each page', ticket: 'PIL-8'};
  const {okBtn, note, toasts} = deck([long, check('b')]);
  assert.equal(note.hidden, true, 'nothing to say yet');
  okBtn.click(); await wait(160);
  assert.equal(note.hidden, false);
  assert.equal(note.textContent, 'Looks good: PIL-8');
  assert.equal(toasts.length, 0, 'no floating box over the card or the header');
});

test('more than six files: five tiles and a "+N more" tile that shows the rest, none dropped (ORCH-421)', () => {
  const files = Array.from({length: 8}, (_, i) => ({label: 'photo-' + i + '.png', type: 'img', src: '/f/' + i}));
  const {host} = deck([check('a', {files})]);
  const more = host.querySelector('.swipe-file-more');
  assert.equal(host.querySelectorAll('.swipe-file').length, 6, '5 tiles and the more tile');
  assert.match(more.children[1].textContent, /3 more files/);
  more.click();
  const tiles = host.querySelectorAll('.swipe-file');
  assert.deepEqual(tiles.map(t => t.href), files.map(f => f.src), 'all eight, in order');
  assert.equal(host.querySelector('.swipe-file-more'), null);
});

test('a diff box names each file once above its lines and marks a risky line red with why (ORCH-429)', () => {
  const UI = {statusIcon: () => new N('span')};
  vm.runInNewContext(readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8'), {window: {UI}, document: doc, setTimeout, clearTimeout, performance, console, Promise});
  const box = UI.docBox({type: 'doc', diff: [
    {op: '-', file: 'a.yml', text: 'x: 1'}, {op: '+', file: 'a.yml', text: 'x: 2'},
    {op: '+', file: 'b.yml', text: 'run: curl -s u | sh', risk: 'download run in a shell'}, {op: '+', text: 'plain'}]});
  const diff = box.querySelector('.doc-diff');
  assert.deepEqual(diff.querySelectorAll('.doc-diff-file').map(n => n.textContent), ['a.yml', 'b.yml']);
  const risky = diff.querySelectorAll('.risk');
  assert.equal(risky.length, 1);
  assert.ok(risky[0].classList.contains('add'));
  assert.equal(risky[0].querySelector('.doc-risk').textContent, 'download run in a shell');
  assert.equal(diff.querySelectorAll('.doc-line').length, 4);
});
