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

function deck(items, o = {}, extra = {}) {
  const toasts = [], viewed = [], UI = {toast: (m, undo) => toasts.push({m, undo}), statusIcon: () => new N('span'), reviewViewer: (shots, i, vo) => viewed.push({shots, i, vo})};
  const window = {UI, ...extra};
  vm.runInNewContext(readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8'), {window, document: doc, setTimeout, clearTimeout, performance, console, Promise});
  const host = new N('section'), decided = [];
  const d = UI.swipeDeck(host, items, {mode: 'desk', voice: false, onDecide: (it, v, note) => decided.push({id: it.id, v, note}), ...o});
  // round 2: the bar is the consequence line over one row (Later left, the answers right), so find the buttons by name
  const [top] = host.children, noBtn = host.querySelector('.swipe-act.no'), talkBtn = host.querySelector('.swipe-act.talk'), okBtn = host.querySelector('.swipe-act.ok'), undoBtn = top.children[4], note = top.children[1];
  return {d, host, decided, toasts, viewed, noBtn, talkBtn, okBtn, undoBtn, note};
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

// ORCH-477 (owner pick B): a tile opens the file large inside the page (UI.reviewViewer), never a new tab; the viewer
// steps to the card's other files and keeps "Open in new tab" inside it.
test('a Check card shows its own files as tiles that open them large in the page', () => {
  const {host, viewed} = deck([check('a', {files: [{label: 'Cover photo', type: 'img', src: '/api/file?t=t_x&k=evidence&n=shop.png'}, {label: 'Result', type: 'page', src: '/view/t_x/evidence/result.html'}, {label: 'No src', type: 'img', src: ''}]})]);
  const tiles = host.querySelectorAll('.swipe-file');
  assert.deepEqual(tiles.map(t => t.dataset.src), ['/api/file?t=t_x&k=evidence&n=shop.png', '/view/t_x/evidence/result.html']);
  assert.deepEqual(tiles.map(t => t.tag), ['button', 'button'], 'no link to a new tab');
  assert.ok(tiles.every(t => t.target === undefined));
  tiles[1].click();
  assert.equal(viewed.length, 1); assert.equal(viewed[0].i, 1);
  assert.deepEqual(viewed[0].shots.map(s => [s.label, s.preview.type, s.open]), [['Cover photo', 'img', '/api/file?t=t_x&k=evidence&n=shop.png'], ['Result', 'page', '/view/t_x/evidence/result.html']]);
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

// ORCH-477 (owner pick B): tick two cards (or two options of one choice) to see them side by side, each with its own
// answers; the filled button is the suggested answer only, never "the left one"; Close goes back to one card.
const choice = {id: 'c', kind: 'choice', kindLabel: 'Choose', title: 'Which layout?', then: 'The helper builds it.', preview: {type: 'options', options: [
  {id: 'A', title: 'As today', preview: {type: 'img', src: '/a.png'}}, {id: 'B', title: 'Changes first', suggested: true, preview: {type: 'img', src: '/b.png'}}, {id: 'C', title: 'Plain'}]}};
const panes = host => host.querySelectorAll('.swipe-pair-pane');
const filled = host => host.querySelectorAll('.btn').filter(b => b.classList.contains('primary'));
test('Compare mode: off by default; two ticked wait for Compare, each side has its own answers, the shared bar steps aside', async () => {
  const {d, host, decided} = deck([check('a', {then: 'Done.'}), check('b'), draft('x')]);
  assert.equal(d.picking, false, 'no ticks until Compare is pressed');
  d.setPicking(true); assert.equal(d.picking, true);
  d.tick('a'); assert.equal(d.comparing, false, 'one tick: still one card');
  d.tick('b'); assert.equal(d.comparing, false, 'two ticks: they wait for the Compare button');
  d.showPair(); assert.equal(d.comparing, true);
  assert.equal(host.querySelector('.swipe-actions').hidden, true, 'no shared bar: each side answers itself');
  assert.equal(panes(host).length, 2);
  assert.match(panes(host)[0].querySelector('.swipe-then').textContent, /If it looks good: Done\./);
  d.tick('x'); assert.deepEqual([...d.ticked], ['a', 'b'], 'a third tick is refused');
  const ok = panes(host)[1].querySelector('.swipe-pair-ok'); ok.click();
  assert.deepEqual(decided.map(x => [x.id, x.v]), [['b', 'ok']]);
  assert.equal(d.comparing, false, 'one side answered: back to one card');
  assert.equal(d.items[d.index].id, 'a', 'the other side shows'); assert.deepEqual([...d.ticked], ['a']);
  d.tick('x'); assert.equal(d.comparing, false, 'a new second tick waits for Compare again');
});
test('Cancel ends picking and clears the ticks; Close in the side by side view ends it too', () => {
  const {d, host} = deck([check('a'), check('b')]);
  const list = new N('div'); d.drawList(list);
  const btns = () => list.querySelectorAll('button').map(b => b.textContent);
  assert.deepEqual(btns().slice(0, 1), ['Compare'], 'one Compare button in the header');
  assert.equal(list.querySelectorAll('.review-tick-box').length, 0, 'no tick box on a row by default');
  list.querySelector('.review-list-compare').click(); d.drawList(list);
  assert.equal(list.querySelectorAll('.review-tick-box').length, 2, 'Compare mode: a tick beside each card');
  const go = () => list.querySelector('.review-list-compare');
  assert.equal(go().disabled, true); assert.equal(go().classList.contains('primary'), false, 'not filled before two are ticked');
  d.tick('a'); d.tick('b'); d.drawList(list);
  assert.equal(go().classList.contains('primary'), true, 'filled once two are ticked');
  list.querySelector('.review-list-cancel').click();
  assert.equal(d.picking, false); assert.deepEqual([...d.ticked], []);
  d.compare(['a', 'b']); assert.equal(d.picking, true);
  host.querySelector('.swipe-pair-close').click();
  assert.equal(d.comparing, false); assert.equal(d.picking, false, 'Close goes back to one card and ends picking');
});
test('the list: a group header is the ticket name with the count only when more than one waits; none when it repeats the title', () => {
  const items = [check('a', {ticketTitle: 'Spring sale', title: 'Spring sale'}), check('b', {ticketTitle: 'Weekly report'}), check('c', {ticketTitle: 'Weekly report'}), check('d', {ticketTitle: 'Survey', need: 'Sends Friday 08:00'})];
  const {d} = deck(items);
  const list = new N('div'); d.drawList(list);
  const heads = list.querySelectorAll('.review-group-head').map(h => h.textContent);
  assert.deepEqual(heads, ['Weekly report2 waiting', 'Survey'], 'no header that repeats the title, no "1 of 1 waiting"');
  const rows = list.querySelectorAll('.review-row');
  assert.equal(rows.length, 4);
  assert.equal(rows[0].classList.contains('is-current'), true, 'the card on screen: tinted, no "Now" pill');
  assert.doesNotMatch(list.textContent, /Now/);
  assert.equal(rows[3].querySelector('.review-row-sub').textContent, 'Sends Friday 08:00', 'the deadline under the title');
  assert.equal(rows[1].querySelector('.review-row-sub'), null, 'no deadline: no second line');
  rows[2].click(); assert.equal(d.index, 2, 'a row opens its card');
});
test('the card head: title first, then one quiet line (type · deadline · ticket key), no time stamp', () => {
  const {host} = deck([check('a', {need: 'Sends Friday 08:00', ticket: 'DT-53', when: 'today 09:40', group: 'Spring', suggest: 'ok'})]);
  const head = host.querySelector('.swipe-head');
  assert.equal(head.children[0].tag, 'h3'); assert.equal(head.children[1].className, 'swipe-meta');
  assert.deepEqual(head.children[1].children.map(c => c.textContent), ['Check', 'Sends Friday 08:00', 'DT-53']);
  assert.doesNotMatch(head.textContent, /09:40|Spring$|Suggested:/);
});
test('two options of one choice side by side: Use B is the one filled button (the suggested option)', () => {
  const {d, host, decided} = deck([choice, check('b')]);
  assert.deepEqual(d.optionRefs(choice).map(x => x.label), ['A: As today', 'B: Changes first'], 'only options with a picture');
  d.compare(['c\nA', 'c\nB']);
  assert.match(host.querySelector('.swipe-pair-of').textContent, /3 options of “Which layout\?”/);
  assert.deepEqual(filled(host).map(b => b.textContent), ['Use B']);
  assert.deepEqual(host.querySelector('.swipe-pair-switch').querySelectorAll('button').map(b => b.textContent), ['A: As today', 'B: Changes first'], 'the phone switch names both in full');
  panes(host)[0].querySelector('.btn').click();
  assert.deepEqual(decided.map(x => [x.id, x.v, x.note.picked]), [['c', 'ok', 'A']]);
  assert.equal(d.comparing, false);
});
test('no suggestion, or both sides suggested: every answer outlined (never "the left one")', () => {
  const {d, host} = deck([check('a'), check('b')]);
  d.compare(['a', 'b']); assert.equal(filled(host).length, 0);
  const two = deck([check('a', {suggest: 'ok'}), check('b', {suggest: 'ok'})]);
  two.d.compare(['a', 'b']); assert.equal(filled(two.host).length, 0);
  const one = deck([check('a'), check('b', {suggest: 'ok'})]);
  one.d.compare(['a', 'b']); assert.deepEqual(filled(one.host).map(b => b.dataset.item), ['b']);
});
test('Send back on one side opens the words box for that card; Close goes back to one card', async () => {
  const {d, host, decided} = deck([check('a'), check('b')]);
  d.compare(['a', 'b']);
  panes(host)[1].querySelectorAll('.btn').find(b => /Send back/.test(b.textContent)).click();
  const sheet = host.querySelector('.swipe-sheet');
  assert.ok(sheet); assert.equal(sheet.children[2].textContent, 'Spring catalogue b');
  host.querySelector('.swipe-sheet textarea').value = 'Shorter'; host.querySelector('.swipe-sheet textarea').listeners.input[0]();
  sheet.querySelectorAll('button').find(b => b.textContent === 'Send back for changes').click(); await wait(260);
  assert.deepEqual(decided.map(x => [x.id, x.v]), [['b', 'talk']]);
  const e = deck([check('a'), check('b')]); e.d.compare(['a', 'b']);
  e.host.querySelector('.swipe-pair-close').click();
  assert.equal(e.d.comparing, false); assert.deepEqual([...e.d.ticked], []);
});
test('the phone\'s full list: the same rows; ticks in Compare mode, Compare once two are ticked; Close returns focus to its opener', () => {
  const {d, host} = deck([check('a'), choice]);
  const opener = host.querySelector('.swipe-jump-all'); opener.focus();
  d.openOverview();
  assert.equal(host.querySelectorAll('.review-tick-box').length, 0, 'no ticks by default');
  assert.equal(host.querySelector('.swipe-overview').querySelectorAll('.review-row').length, 2);
  host.querySelector('.swipe-overview').querySelector('.review-list-compare').click();
  const boxes = host.querySelectorAll('.review-tick-box');
  assert.deepEqual(boxes.map(b => b.dataset.ref), ['a', 'c', 'c\nA', 'c\nB'], 'the options of a choice show under it only in this mode');
  boxes[2].listeners.change[0](); boxes[3].listeners.change[0]();
  assert.equal(d.comparing, false);
  assert.equal(boxes[0].disabled, true, 'two ticked: the others wait');
  const go = host.querySelector('.swipe-overview').querySelector('.review-list-compare');
  assert.equal(go.classList.contains('primary'), true);
  go.click(); assert.equal(d.comparing, true); assert.equal(host.querySelector('.swipe-overview'), null);
  d.compare([]); d.openOverview(); opener.focus(); d.openOverview();
  host.querySelector('.swipe-overview').querySelector('.btn.icon').click();
  assert.equal(doc.activeElement, opener, 'focus back on the button that opened the list');
});
test('a phone shows "All cards · 1 of N" with ← → above the card', () => {
  const {d, host} = deck([check('a'), check('b'), check('c')]);
  const jump = host.querySelector('.swipe-jump');
  assert.match(jump.textContent, /All cards1 of 3/);
  jump.children[2].click(); assert.equal(d.index, 1);
  assert.match(jump.textContent, /2 of 3/);
});
test('a PDF tile shows its first page through the browser\'s own PDF view (FileViewer.thumb), and opens large', () => {
  const asked = [];
  const {host, viewed} = deck([check('a', {files: [{label: 'Weekly report.pdf', type: 'pdf', src: '/api/file?n=r.pdf'}]})], {}, {FileViewer: {thumb: f => { asked.push(f); return new N('span'); }}});
  assert.deepEqual(asked.map(f => [f.src, f.name]), [['/api/file?n=r.pdf', 'Weekly report.pdf']]);
  host.querySelector('.swipe-file').click();
  assert.equal(viewed[0].shots[0].preview.type, 'pdf');
});
test('the "If you approve" line is in the pinned answers bar, not at the card\'s end', () => {
  const {host} = deck([check('a', {then: 'The ticket is done.'})]);
  const bar = host.querySelector('.swipe-actions');
  assert.match(bar.querySelector('.swipe-bar-then').textContent, /If it looks good: The ticket is done\./);
  assert.equal(host.querySelector('.swipe-card').querySelector('.swipe-then'), null);
});

test('more than six files: five tiles and a "+N more" tile that shows the rest, none dropped (ORCH-421)', () => {
  const files = Array.from({length: 8}, (_, i) => ({label: 'photo-' + i + '.png', type: 'img', src: '/f/' + i}));
  const {host} = deck([check('a', {files})]);
  const more = host.querySelector('.swipe-file-more');
  assert.equal(host.querySelectorAll('.swipe-file').length, 6, '5 tiles and the more tile');
  assert.match(more.children[1].textContent, /3 more files/);
  more.click();
  const tiles = host.querySelectorAll('.swipe-file');
  assert.deepEqual(tiles.map(t => t.dataset.src), files.map(f => f.src), 'all eight, in order');
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

// ORCH-1847: a plain, reversible question (orch marks it one_tap) is answered with one tap on its named answer, as on
// Home; a deck of one card drops the count, bar, All and "1 of 1" row; many cards keep them.
const supplier = (id = 's', extra = {}) => ({id, kind: 'choice', kindLabel: 'Choose', ticket: 'PIL-2', ticketTitle: 'Answer the supplier about the delivery date', oneTap: true, title: 'The supplier can deliver on Tuesday or Thursday. Which day?',
  preview: {type: 'options', options: [{id: 'Tuesday', title: 'Tuesday', suggested: true}, {id: 'Thursday', title: 'Thursday'}]}, ...extra});
const optOf = (host, id) => host.querySelector('.swipe-card').querySelectorAll('.swipe-opt').find(b => b.dataset.opt === id);
const tap = (host, id) => { const c = host.querySelector('.swipe-card'), t = optOf(host, id);
  c.listeners.pointerdown.forEach(f => f({pointerId: 1, clientX: 50, clientY: 50, button: 0, target: t}));
  c.listeners.pointerup.forEach(f => f({pointerId: 1, clientX: 50, clientY: 50})); };
test('one plain question: one tap on Thursday answers it once; no Pick one, no 1 of 1, Undo while it works', async () => {
  const undone = [];
  const {d, host, decided, okBtn, noBtn, talkBtn, undoBtn} = deck([supplier()], {canUndo: () => true, onUndo: it => undone.push(it.id)});
  const [top] = host.children;
  assert.equal(top.hidden, true, 'no "0 answered · 1 waiting", bar, All or "1 of 1" for one card');
  assert.equal(okBtn.hidden, true, 'the answers are the buttons: no Pick one');
  const side = new N('div'); side.append(new N('p')); d.drawList(side);
  assert.equal(side.children.length, 0, 'one card: no All cards list beside it (an empty list hides its aside)');
  assert.deepEqual([noBtn.hidden, talkBtn.hidden], [false, false], 'None of these and Comment stay');
  assert.equal(host.querySelector('.swipe-later').hidden, false, 'Later stays');
  assert.equal(host.querySelector('.swipe-bar-then').textContent, 'One tap answers. You can undo it.');
  assert.equal(optOf(host, 'Tuesday').getAttribute('aria-label'), 'Answer Tuesday (suggested)');
  assert.equal(host.querySelector('.swipe-card').querySelector('.swipe-ticket').textContent, 'Answer the supplier about the delivery date', 'which ticket, without opening it');
  tap(host, 'Thursday'); tap(host, 'Thursday');
  await wait(160);
  assert.deepEqual(JSON.parse(JSON.stringify(decided)), [{id: 's', v: 'ok', note: {picked: 'Thursday'}}], 'a rapid double tap answers once');
  assert.equal(top.hidden, false); assert.equal(undoBtn.hidden, false); assert.equal(undoBtn.disabled, false);
  assert.equal(host.querySelector('.swipe-note').textContent, 'Answered Thursday: PIL-2');
  undoBtn.click();
  assert.deepEqual(undone, ['s']); assert.equal(d.index, 0);
  assert.equal(host.querySelector('.swipe-card').dataset.item, 's', 'back on the question');
  assert.equal(okBtn.hidden, true, 'still one tap after Undo');
});
test('one plain question: Enter on an answer answers it; the right arrow only says to tap an answer', async () => {
  const {host, decided} = deck([supplier()]);
  host.listeners.keydown.forEach(f => f({key: 'ArrowRight', target: host, preventDefault() {}}));
  await wait(160);
  assert.equal(decided.length, 0);
  assert.equal(host.querySelector('.swipe-note').textContent, 'Tap the answer you want.');
  optOf(host, 'Thursday').onclick({stopPropagation() {}, detail: 0});
  await wait(160);
  assert.deepEqual(decided.map(x => [x.id, x.note.picked]), [['s', 'Thursday']]);
});
test('many cards keep the count, bar and "1 of N"; a tap on the next card right after an answer is not an answer', async () => {
  const {d, host, decided} = deck([supplier('a'), supplier('b'), check('c')]);
  const [top] = host.children;
  assert.equal(top.hidden, false);
  assert.equal(top.children[0].hidden, false); assert.match(top.children[0].textContent, /0 answered · 3 waiting/);
  assert.equal(host.querySelector('.swipe-jump').hidden, false); assert.match(host.querySelector('.swipe-jump').textContent, /1 of 3/);
  const list = new N('div'); d.drawList(list);
  assert.equal(list.querySelectorAll('.review-row').length, 3, 'many cards: the All cards list stays');
  tap(host, 'Thursday'); await wait(130);
  assert.equal(d.index, 1, 'the next question is on top');
  tap(host, 'Thursday'); await wait(160);
  assert.deepEqual(decided.map(x => x.id), ['a'], 'the second tap of a double tap does not answer the next card');
  await wait(260); tap(host, 'Tuesday'); await wait(160);
  assert.deepEqual(decided.map(x => [x.id, x.note.picked]), [['a', 'Thursday'], ['b', 'Tuesday']]);
});
test('a question not marked one tap keeps tap an option, then Use it; one card with option pictures keeps its top row', async () => {
  const {host, decided, okBtn} = deck([supplier('p', {oneTap: false})]);
  tap(host, 'Thursday'); await wait(160);
  assert.equal(decided.length, 0, 'a tap only picks');
  assert.equal(okBtn.hidden, false); assert.match(okBtn.textContent, /Use Thursday/);
  okBtn.click(); await wait(160);
  assert.deepEqual(decided.map(x => x.note.picked), ['Thursday']);
  const pics = deck([{...choice, oneTap: true}]);
  assert.equal(pics.host.children[0].hidden, false, 'options with pictures can be compared: the row and its All stay');
  assert.equal(pics.okBtn.hidden, false, 'not plain options: no one tap');
});
