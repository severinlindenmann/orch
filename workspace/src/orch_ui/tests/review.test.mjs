import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const read = f => readFileSync(new URL('../static/' + f, import.meta.url), 'utf8');

// A tiny DOM: enough for review.js to build its page, records and states.
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.style = {}; this.className = ''; this.own = ''; this.hidden = false; this.listeners = {}; }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  get classList() { const n = this; return {add: c => { if (!n.className.split(' ').includes(c)) n.className = (n.className + ' ' + c).trim(); }, contains: c => n.className.split(' ').includes(c)}; }
  get lastChild() { return this.children[this.children.length - 1]; }
  append(...c) { c.forEach(x => this.children.push(typeof x === 'string' ? Object.assign(new N('#text'), {own: x}) : x)); }
  replaceChildren(...c) { this.children = []; this.own = ''; this.append(...c); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  focus() {}
  showModal() { this.open = true; }
  fire(t, e = {}) { (this.listeners[t] || []).forEach(f => f({preventDefault() {}, ...e})); }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
  byClass(c) { return this.all(n => n.className.split(' ').includes(c)); }
  querySelector(sel) { const c = /\.([\w-]+)/.exec(sel)?.[1]; return c ? this.byClass(c)[0] || null : null; }
}

function load() {
  const toasts = [], decks = [];
  const UI = {
    toast: (m, u, k) => toasts.push({m, k}),
    state: o => { const n = new N('div'); n.className = 'state ' + o.kind; n.append(Object.assign(new N('strong'), {own: o.title || ''}), Object.assign(new N('p'), {own: o.text || ''})); n.opts = o; return n; },
    swipeDeck: (host, items, o) => { const d = {host, items, o, answers: {}, pins: {}, later: new Set(o.later || []), index: o.start || 0, busy: false}; decks.push(d); host.replaceChildren(); return d; },
  };
  const document = {createElement: t => new N(t), visibilityState: 'visible', body: new N('body')};
  const window = {UI};
  vm.runInNewContext(read('review.js'), {window, document, setInterval, clearInterval, setTimeout, clearTimeout, console});
  return {UI, toasts, decks, document};
}

const NOW = new Date(2026, 10, 15, 12, 0);
const card = (id, extra = {}) => ({
  id, ticket: 'T-1', key: 'DT-41', digest: 'd-' + id, since: new Date(2026, 10, 15, 9, 12).toISOString(),
  card: {kind: 'draft', title: 'Home block ' + id, why: 'Because', need: 'Blocks Home', then: 'The helper builds it.', ok_label: 'Build it',
    open: 'javascript:alert(1)', preview: {type: 'compare', before: {type: 'page', src: 'reviewed/abc123def456/before.html'}, after: {type: 'img', src: 'reviewed/abc123def456/after.png'}}},
  ...extra,
});
const fakeApi = (stacks, answer) => {
  let n = 0;
  return {stack: async () => stacks[Math.min(n++, stacks.length - 1)], answered: async () => [], answer: answer || (async () => ({ok: true})),
    fileUrl: (c, ref) => '/f/' + c.ticket + '/' + ref, calls: () => n};
};
const flush = () => new Promise(r => setTimeout(r, 5));
const mount = async (api, o = {}) => {
  const env = load(), host = new N('main');
  const page = env.UI.reviewPage(host, api, {poll: 0, now: NOW, hold: 0, ...o});
  await flush();
  return {...env, host, page};
};

test('mapCard maps a stack card to the widget item and turns file refs into urls', () => {
  const {UI} = load();
  const it = UI.review.mapCard(card('a'), fakeApi([[]]), NOW);
  assert.equal(it.id, 'a'); assert.equal(it.okLabel, 'Build it'); assert.equal(it.kindLabel, 'Draft');
  assert.equal(it.ticket, 'DT-41'); assert.equal(it.when, 'today 09:12'); assert.equal(it.digest, 'd-a');
  assert.equal(it.preview.before.src, '/f/T-1/reviewed/abc123def456/before.html');
  assert.equal(it.preview.after.src, '/f/T-1/reviewed/abc123def456/after.png');
  assert.equal(it.open, undefined, 'only http(s) links are kept');
});

test('mapCard carries the round and the task so the card can say About', () => {
  const {UI} = load();
  const it = UI.review.mapCard(card('x', {ticket: 't_abc', ticket_title: 'Home update', about: 'Draw the block', task: 'c1'}), fakeApi([[]]), NOW);
  assert.equal(it.about, 'Draw the block');
  assert.equal(it.ticketTitle, 'Home update');
  assert.equal(it.ticketId, 't_abc');
  assert.equal(UI.review.mapCard(card('y'), fakeApi([[]]), NOW).about, undefined);
});
test('ORCH-2182: mapCard carries If you wait and the facts, and leaves out what is empty or not text', () => {
  const {UI} = load();
  const it = UI.review.mapCard(card('f', {if_wait: 'The release waits.', facts: ['14 links point at it', '', 7, 'a', 'b', 'c']}), fakeApi([[]]), NOW);
  assert.equal(it.ifWait, 'The release waits.');
  assert.deepEqual([...it.facts], ['14 links point at it', 'a', 'b', 'c']);
  const none = UI.review.mapCard(card('g'), fakeApi([[]]), NOW);
  assert.equal(none.ifWait, ''); assert.equal(none.facts.length, 0);
});
test('ORCH-2186: mapCard carries the ideas (text only, at most 12); Save sends how they were sorted', async () => {
  const {UI} = load();
  const it = UI.review.mapCard(card('i', {ideas: ['Customer story', '', 7, ...Array.from({length: 14}, (_, n) => 'idea ' + n)]}), fakeApi([[]]), NOW);
  assert.equal(it.ideas.length, 12); assert.equal(it.ideas[0], 'Customer story');
  assert.equal(UI.review.mapCard(card('j'), fakeApi([[]]), NOW).ideas.length, 0);
  const sent = [];
  const {decks} = await mount(fakeApi([[card('a', {ideas: ['A', 'B', 'C']})]], async b => { sent.push(b); return {ok: true}; }));
  decks[0].o.onDecide(decks[0].items[0], 'ok', {ideas: {keep: [1], no: [3], later: []}});
  await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0])), {id: 'a', digest: 'd-a', verdict: 'ok', picked: null, note: {ideas: {keep: [1], no: [3], later: []}}});
});
test('ORCH-2183: mapCard carries the quote with its day; words taken away or changed are dropped', () => {
  const {UI} = load();
  const at = new Date(NOW.getTime() - 5 * 864e5);
  const it = UI.review.mapCard(card('s', {said: {who: 'person', name: 'Lea', src: 'chat', at: at.toISOString(), words: 'Keep it.', stale: null}}), fakeApi([[]]), NOW);
  assert.equal(it.said.who, 'person'); assert.equal(it.said.name, 'Lea'); assert.equal(it.said.words, 'Keep it.');
  assert.match(it.said.day, /^on \d+ [A-Z][a-z]{2}$/); assert.equal(it.said.stale, '');
  const today = UI.review.mapCard(card('t', {said: {who: 'you', src: 'history', at: NOW.toISOString(), words: 'x'}}), fakeApi([[]]), NOW);
  assert.equal(today.said.day, 'today');
  const gone = UI.review.mapCard(card('g', {said: {who: 'you', src: 'chat', at: NOW.toISOString(), words: 'old', stale: 'changed'}}), fakeApi([[]]), NOW);
  assert.equal(gone.said.words, ''); assert.equal(gone.said.stale, 'changed');
  assert.equal(UI.review.mapCard(card('n', {said: {who: 'agent', words: 'made up'}}), fakeApi([[]]), NOW).said, undefined);
  assert.equal(UI.review.mapCard(card('m'), fakeApi([[]]), NOW).said, undefined);
});
test('ORCH-1108: mapCard names a stuck card Stuck and keeps only a link inside the page as its Open', () => {
  const {UI} = load();
  const c = card('s', {href: '#ticket/t_abc123', answers: [{label: 'Nudge', picked: 'nudge'}]}); c.card = {kind: 'stuck', title: 'The helper is idle.'};
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.equal(it.kindLabel, 'Stuck'); assert.equal(it.icon, 'pause'); assert.equal(it.href, '#ticket/t_abc123');
  assert.deepEqual(JSON.parse(JSON.stringify(it.answers)), [{label: 'Nudge', picked: 'nudge'}]);
  for (const bad of ['javascript:alert(1)', 'https://x.example/t', '//evil', '#ticket/<b>']) assert.equal(UI.review.mapCard(card('b', {href: bad}), fakeApi([[]]), NOW).href, undefined, bad);
});
test('mapCard keeps option previews and picks a kind label', () => {
  const {UI} = load();
  const c = card('o'); c.card = {kind: 'choice', title: 'Which?', preview: {type: 'options', options: [{id: 'A', title: 'As today', preview: {type: 'page', src: 'reviewed/aa/a.html'}}, {id: 'B', title: 'New', suggested: true}]}};
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.equal(it.kindLabel, 'Choose'); assert.equal(it.preview.options[0].preview.src, '/f/T-1/reviewed/aa/a.html');
  assert.equal(it.preview.options[1].suggested, true);
});

test('mapCard carries the question text, the set, the suggestion and a choice\'s Today picture (ORCH-65)', () => {
  const {UI} = load();
  const c = card('o'); Object.assign(c, {text: 'Now: three counts. Proposal: one.', group: 'Home look', recommended: 'B'});
  c.card = {kind: 'choice', title: 'Which?', preview: {type: 'options', before: {type: 'img', src: 'reviewed/aa/t.png'}, options: [{id: 'A', title: 'One'}, {id: 'B', title: 'Two'}]}};
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.equal(it.text, 'Now: three counts. Proposal: one.'); assert.equal(it.group, 'Home look');
  assert.equal(it.preview.options[1].suggested, true); assert.equal(it.preview.options[0].suggested, false);
  assert.equal(it.preview.before.src, '/f/T-1/reviewed/aa/t.png'); assert.equal(it.suggest, undefined);
  const l = card('l'); l.links = [{label: 'Mockup', url: 'http://127.0.0.1:8780/a.html'}, {label: 'Bad', url: 'javascript:x'}]; l.card = {kind: 'draft', title: 'B'};
  assert.equal(JSON.stringify(UI.review.mapCard(l, fakeApi([[]]), NOW).links), JSON.stringify([{label: 'Mockup', url: 'http://127.0.0.1:8780/a.html'}]));
  const d = card('d'); d.recommended = 'ok'; d.card = {kind: 'draft', title: 'Block'};
  assert.equal(UI.review.mapCard(d, fakeApi([[]]), NOW).suggest, 'ok');
});

test('the deck is text only by default: voice is off', async () => {
  const {decks} = await mount(fakeApi([[card('a')]]));
  assert.equal(decks[0].o.voice, false);
  const w = read('widgets.js');
  assert.match(w, /if\(o\.voice\)voice\.append\(mic,wave\)/);
  assert.match(w, /if\(o\.voice&&!box\)sh\.append\(voice,clips\)/);  // the feedback box (o.attach) brings its own Record
  assert.match(w, /clips:o\.voice\?dr\.clips\.slice\(\):\[\]/);
});

test('an answer is sent with id, digest, verdict, picked and the words', async () => {
  const sent = [];
  const {decks} = await mount(fakeApi([[card('a')]], async b => { sent.push(b); return {ok: true}; }));
  const d = decks[0];
  d.o.onDecide(d.items[0], 'talk', {about: 'C', changes: {text: 'Bigger', clips: [], pins: [{x: 10, y: 20, on: 'after', text: 'here'}]}});
  await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0])), {id: 'a', digest: 'd-a', verdict: 'talk', picked: 'C', note: {text: 'Bigger', pins: [{n: 1, on: 'after', x: 10, y: 20, text: 'here'}]}});
  d.o.onDecide(d.items[0], 'ok', null);
  await flush();
  assert.equal(sent[1].verdict, 'ok'); assert.equal(sent[1].note, null);
});

test('ORCH-422: with api.attach the sheet gets the feedback box; files land on the ticket before the answer, named in the note', async () => {
  const sent = [], attached = [];
  const api = {...fakeApi([[card('a')]], async b => { sent.push(JSON.parse(JSON.stringify(b))); return {ok: true}; }),
    box: {voice: true, accept: ['png', 'webm']},
    attach: async ({ticket, files}) => { attached.push([ticket, files.map(f => f.name)]); return {ok: true, names: ['shot (2).png', 'voice-note-0931.webm']}; }};
  const {decks} = await mount(api);
  const d = decks[0];
  assert.equal(d.o.attach.voice, true, 'the comment sheet gets the box with Record');
  const files = [{name: 'shot.png', url: 'data:image/png;base64,iVBO'}, {name: 'voice-note-0931.webm', url: 'data:audio/webm;base64,GkXf'}];
  d.o.onDecide(d.items[0], 'talk', {changes: {text: 'Bigger', clips: [], pins: [], files}});
  await flush(); await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(attached)), [['T-1', ['shot.png', 'voice-note-0931.webm']]]);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].files, undefined, 'the files are never sent with the answer');
  assert.match(sent[0].note.text, /^Bigger\n\nI added 2 files to this ticket: shot \(2\)\.png, voice-note-0931\.webm\. Read them first\.$/);
  // files alone, no words: still a note naming them
  d.o.onDecide(d.items[0], 'talk', {changes: {text: '', clips: [], pins: [], files: files.slice(0, 1)}});
  await flush(); await flush();
  assert.match(sent[1].note.text, /^I added 2 files to this ticket/);
});

test('ORCH-422: files that could not be added: no answer is saved, the card comes back', async () => {
  const sent = [];
  const api = {...fakeApi([[card('a')]], async b => { sent.push(b); return {ok: true}; }), box: {voice: true},
    attach: async () => ({ok: false, error: {code: 'error', message: 'x.pdf: no'}})};
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'talk', {changes: {text: 'see', clips: [], pins: [], files: [{name: 'x.pdf', url: 'data:,x'}]}});
  await flush(); await flush();
  assert.equal(sent.length, 0);
  assert.equal(toasts[0].m, 'x.pdf: no'); assert.equal(toasts[0].k, 'error');
});

test('changed: toast, reload the stack and show the new version', async () => {
  const api = fakeApi([[card('a')], [card('a', {digest: 'd-new'})]], async () => ({ok: false, error: {code: 'changed', message: 'x'}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'ok', null);
  await flush(); await flush();
  assert.equal(toasts[0].m, 'This card changed. Showing the new version.');
  assert.equal(decks.length, 2);
  assert.equal(decks[1].items[0].digest, 'd-new');
});

test('needs_person: plain sign-in message, error toast, the card returns', async () => {
  const api = fakeApi([[card('a')]], async () => ({ok: false, error: {code: 'needs_person', message: 'x'}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'ok', null);
  await flush(); await flush();
  assert.match(toasts[0].m, /Sign in to answer: run orch review in your terminal/); assert.equal(toasts[0].k, 'error');
  assert.equal(decks.length, 2); assert.equal(decks[1].items.length, 1);
});

test('needs_person with the server sign-in words (dashboard): shows them, never the terminal (#1918)', async () => {
  const words = 'Sign in to do this: open the dashboard with a sign-in link from orch.';
  const api = fakeApi([[card('a')]], async () => ({ok: false, error: {code: 'needs_person', message: words}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'ok', null);
  await flush(); await flush();
  assert.equal(toasts[0].m, words); assert.equal(toasts[0].k, 'error');
  assert.doesNotMatch(toasts[0].m, /terminal/);
  assert.equal(decks.length, 2); assert.equal(decks[1].items.length, 1);
});

test('other errors show the message and bring the card back', async () => {
  const api = fakeApi([[card('a')]], async () => ({ok: false, error: {code: 'refused', message: 'Not allowed.'}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'no', null);
  await flush(); await flush();
  assert.equal(toasts[0].m, 'Not allowed.'); assert.equal(decks.length, 2);
});

test('ORCH-2182: the deck is drawn again when the decision-first switch changes (settings that came late too)', async () => {
  let on = false;
  const api = fakeApi([[card('a')]]);
  const {decks, page} = await mount(api, {decisionFirst: () => on});
  await page.tick(); await flush();
  assert.equal(decks.length, 1, 'same stack, same switch: no rebuild');
  on = true;
  await page.tick(); await flush();
  assert.equal(decks.length, 2, 'the switch turned on: drawn again');
  await page.tick(); await flush();
  assert.equal(decks.length, 2);
});
test('polling keeps the deck while nothing changed and while a sheet is open', async () => {
  const api = fakeApi([[card('a')], [card('a')], [card('a'), card('b')], [card('a'), card('b')]]);
  const {decks, page} = await mount(api);
  await page.tick(); await flush();
  assert.equal(decks.length, 1, 'same stack: no rebuild');
  decks[0].busy = true;
  await page.tick(); await flush();
  assert.equal(decks.length, 1, 'open sheet: the deck stays');
  decks[0].busy = false;
  await page.tick(); await flush();
  assert.equal(decks.length, 2); assert.equal(decks[1].items.length, 2);
});

test('empty stack, no sign-in and unreachable states', async () => {
  let m = await mount(fakeApi([[]]));
  assert.match(m.host.textContent, /You're up to date/);
  // ORCH-2094: the empty deck has one next step, See answers, which opens the Answered view
  const st = m.host.all(n => n.opts && n.opts.kind === 'empty')[0];
  assert.equal(st.opts.action.label, 'See answers');
  st.opts.action.onClick(); await flush();
  assert.equal(m.host.all(n => n.attrs['aria-label'] === 'Answered')[0].hidden, false);
  assert.equal(m.host.all(n => n.attrs['aria-label'] === 'Review deck')[0].hidden, true);
  m = await mount({...fakeApi([[]]), stack: async () => { throw Object.assign(new Error('x'), {code: 'needs_person'}); }});
  assert.match(m.host.textContent, /Sign in/); assert.match(m.host.textContent, /run orch review in your terminal/i);
  m = await mount({...fakeApi([[]]), stack: async () => { throw new Error('down'); }});
  assert.match(m.host.textContent, /Can't reach orch/);
});

const entry = (decision, extra = {}) => ({
  id: 'core:q:T-1:q4', ticket: 'T-1', by: 'Severin', via: 'phone', at: new Date(2026, 10, 15, 10, 42).toISOString(),
  card: {kind: 'choice', title: 'Home: which layout?', preview: {type: 'options', options: [{id: 'A', title: 'As today', preview: {type: 'page', src: 'reviewed/aa/a.html'}}, {id: 'C', title: 'Questions first', preview: {type: 'page', src: 'reviewed/aa/c.html'}}]}},
  shown: {digest: 'x', copy: 'reviewed/aa/', files: {'c.html': 'h'}},
  decision, ...extra,
});

test('answerRecord: a sent-back Check says what happens next', () => {
  const {UI} = load();
  const t = UI.answerRecord(entry({action: 'send_back', changes: ['Add shipping']}, {card: {kind: 'check', title: 'Result'}}), {now: NOW}).textContent;
  assert.match(t, /Your note went to the helper for a new version\./); assert.doesNotMatch(t, /Kept exactly/);
});

test('answerRecord: title, verdict words, by · via · time, taken option, pins and words', () => {
  const {UI} = load();
  const rec = UI.answerRecord(entry({action: 'use_with_changes', picked: 'C', changes: ['Put questions on top', 'Show the month'],
    words: {text: 'Take C, but questions on top.', voice: []}, pins: [{n: 1, on: 'option C', x: 30, y: 62, text: 'Show the month here'}]}), {fileUrl: (e, r) => '/f/' + r, now: NOW});
  const t = rec.textContent;
  assert.match(t, /Home: which layout\?/); assert.match(t, /Use C with 2 changes/);
  assert.match(t, /Severin · phone · today 10:42/);
  assert.match(t, /A · As today/); assert.match(t, /C · Questions first/);
  assert.equal(rec.byClass('taken').length, 1); assert.equal(rec.byClass('dim').length, 1);
  assert.equal(rec.byClass('taken')[0].children[0].byClass('swipe-pin').length, 1, 'the pin sits on the taken option');
  assert.match(t, /Take C, but questions on top\./); assert.match(t, /Spot 1 on option C: Show the month here/);
  assert.match(t, /View reviewed version/); assert.match(t, /Kept exactly as you saw it\./);
  const link = rec.byClass('btn').find(n => n.tag === 'a'); assert.equal(link.href, '/f/reviewed/aa/c.html');
  assert.ok(rec.byClass('decision-verdict')[0].className.includes('ok'));
});

test('answerRecord: a plain question (options without pictures) shows no empty tiles and no doubled names (ORCH-110)', () => {
  const {UI} = load();
  const plain = {kind: 'choice', title: 'Which name for the export?', preview: {type: 'options', options: [{id: 'Export', title: 'Export'}, {id: 'Download', title: 'Download'}]}};
  const rec = UI.answerRecord(entry({action: 'use', picked: 'Export'}, {card: plain, shown: null}), {now: NOW});
  assert.equal(rec.byClass('opt-thumb').length, 0); assert.equal(rec.byClass('decision-shown').length, 0);
  assert.match(rec.textContent, /Use Export/); assert.doesNotMatch(rec.textContent, /Export · Export/);
  assert.equal(UI.cardShown({card: plain, ticket: 'T-1'}), null, 'the ticket page shows no empty picture tiles either');
});

test('answerRecord: words per action, text via textContent, relation lines', () => {
  const {UI} = load();
  const w = (a, k) => UI.review.verdictWord({card: k || {kind: 'draft', ok_label: 'Build it'}, decision: a});
  assert.equal(w({action: 'approve'}), 'Build it'); assert.equal(w({action: 'send_back'}), 'Sent back for changes');
  assert.equal(w({action: 'dont'}), "Don't do"); assert.equal(w({action: 'dont'}, {kind: 'check'}), 'Sent back');
  assert.equal(w({action: 'none_of_these'}), 'None of these'); assert.equal(w({action: 'use', picked: 'B'}), 'Use B');
  const evil = '<img src=x onerror=alert(1)>';
  const rec = UI.answerRecord(entry({action: 'send_back', words: {text: evil}, replaced_by: 'q5'}), {now: NOW});
  assert.ok(rec.byClass('decision-words')[0].children[0].textContent === evil);
  assert.match(rec.textContent, /Replaced by a later answer\./); assert.ok(rec.classList.contains('replaced'));
  assert.ok(rec.byClass('decision-verdict')[0].className.includes('talk'));
  assert.match(UI.answerRecord(entry({action: 'approve', replaces: 'q3'}), {now: NOW}).textContent, /Replaces your earlier answer\./);
});

test('appliesNow: the newest answer nobody replaced, with its changes', () => {
  const {UI} = load();
  assert.equal(UI.appliesNow([]), null);
  const old = entry({action: 'send_back', summary: 'Sent back', replaced_by: 'q5'}, {at: new Date(2026, 10, 14, 9, 0).toISOString()});
  const cur = entry({action: 'use_with_changes', picked: 'C', summary: 'Use “Questions first” (C) with 2 changes', changes: ['One', 'Two']});
  const s = UI.appliesNow([old, cur], {});
  assert.match(s.textContent, /What applies now/); assert.match(s.textContent, /Use “Questions first” \(C\) with 2 changes/);
  assert.match(s.textContent, /One/); assert.doesNotMatch(s.textContent, /Sent back/);
});

test('reviewFetchApi: urls for files, 401 means sign in, answer errors are data', async () => {
  const {UI} = load();
  const calls = [];
  const f = async (u, init) => { calls.push([u, init]); if (u === '/api/stack') return {ok: false, status: 401, json: async () => ({})};
    if (u === '/api/answer') return {ok: false, status: 409, json: async () => ({ok: false, error: {code: 'changed', message: 'c'}})};
    return {ok: true, status: 200, json: async () => ({workspace: 'Demo', cards: [1]})}; };
  const api = UI.reviewFetchApi('', f);
  assert.equal(api.fileUrl({ticket: 'T 1'}, 'reviewed/abc123/a b.png'), '/api/file?t=T%201&c=abc123&n=a%20b.png');
  assert.equal(api.fileUrl({ticket: 'T'}, 'etc/passwd'), '');
  await assert.rejects(api.stack(), e => e.code === 'needs_person');
  assert.deepEqual(JSON.parse(JSON.stringify(await api.answer({id: 'a'}))), {ok: false, error: {code: 'changed', message: 'c'}});
  assert.equal(calls.at(-1)[1].method, 'POST');
  const f2 = async () => ({ok: true, status: 200, json: async () => ({workspace: 'Demo', cards: [1]})});
  const api2 = UI.reviewFetchApi('', f2); assert.deepEqual(await api2.stack(), [1]); assert.equal(api2.workspace, 'Demo');
});

test('review.html has no inline script, inline handler or external url', () => {
  const h = read('review.html') + read('review-boot.js');
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/.test(read('review.html')), 'no inline script');
  assert.ok(!/\son[a-z]+\s*=/.test(read('review.html')), 'no inline handlers');
  assert.ok(!/https?:\/\//.test(h.replace(/http:\/\/www\.w3\.org\/2000\/svg/g, '')), 'no external url');
});

test('onChange: called with the deck when it is built and after every move or answer (the dashboard side list)', async () => {
  const seen = [];
  const {decks} = await mount(fakeApi([[card('a'), card('b')]]), {onChange: d => seen.push(d.items.length)});
  assert.deepEqual(seen, [2]);
  decks[0].o.onChange();
  assert.deepEqual(seen, [2, 2]);
});

// ORCH-183 A2: Undo in the deck took the card back on screen while the answer was already saved. An answer now waits
// (o.hold) before it is sent; Undo in that time means nothing is saved; leaving the page saves what waits.
test('an answer waits before it is saved: Undo in that time sends nothing', async () => {
  const sent = [];
  const {decks, page} = await mount(fakeApi([[card('a'), card('b')]], async b => { sent.push(b); return {ok: true}; }), {hold: 40});
  const d = decks[0];
  d.o.onDecide(d.items[0], 'ok', null);
  await flush();
  assert.equal(sent.length, 0, 'not saved yet');
  assert.equal(d.o.canUndo(d.items[0]), true, 'the deck may offer Undo');
  d.o.onUndo(d.items[0]);
  await new Promise(r => setTimeout(r, 60));
  assert.equal(sent.length, 0, 'Undo took it back for real');
  assert.equal(d.o.canUndo(d.items[0]), false);
  assert.equal(page.held, 0);
});

test('a held answer is saved when its time is up, and Undo is no longer offered', async () => {
  const sent = [];
  const {decks} = await mount(fakeApi([[card('a')]], async b => { sent.push(b); return {ok: true}; }), {hold: 20});
  const d = decks[0];
  let synced = 0; d.syncUndo = () => { synced++; };
  d.o.onDecide(d.items[0], 'no', null);
  await new Promise(r => setTimeout(r, 40));
  assert.equal(sent.length, 1); assert.equal(sent[0].verdict, 'no');
  assert.equal(d.o.canUndo(d.items[0]), false, 'saved: no Undo');
  assert.equal(synced, 1, 'the deck is told to turn its Undo button off');
});

test('leaving the page saves every answer that still waits', async () => {
  const sent = [];
  const {decks, page} = await mount(fakeApi([[card('a'), card('b')]], async b => { sent.push(b); return {ok: true}; }), {hold: 60000});
  decks[0].o.onDecide(decks[0].items[0], 'ok', null);
  decks[0].o.onDecide(decks[0].items[1], 'talk', {changes: {text: 'Shorter', pins: []}});
  page.destroy();
  await flush();
  assert.deepEqual(sent.map(b => b.id).sort(), ['a', 'b']);
});

test('a held answer keeps its card out of a refreshed stack; after Undo the card may come back', async () => {
  const api = fakeApi([[card('a'), card('b')], [card('a'), card('b')], [card('a'), card('b'), card('c')]]);
  const {decks, page} = await mount(api, {hold: 60000});
  decks[0].answers.a = {verdict: 'ok', item: decks[0].items[0]}; decks[0].o.onDecide(decks[0].items[0], 'ok', null);  // as the deck does
  await page.tick(); await flush();
  assert.equal(decks.length, 1, 'same open cards: no rebuild');
  delete decks[0].answers.a; decks[0].o.onUndo(decks[0].items[0]);
  await page.tick(); await flush();
  assert.equal(decks.length, 2, 'a new card arrived');
  assert.deepEqual(decks[1].items.map(i => i.id), ['a', 'b', 'c'], 'the card taken back is waiting again');
});

// ORCH-183 A3: a Test results card shows its own files (a picture, a page) as tiles.
test('mapCard: the files of a Check card become tiles with urls; unknown types are plain files; no url, no tile', () => {
  const {UI} = load();
  const c = {id: 'core:review:t_x', ticket: 'T-1', key: 'review', digest: 'd', card: {kind: 'check', title: 'Done', then: 'x',
    files: [{name: 'Cover photo', type: 'img', ref: 'evidence/shop.png'}, {name: 'Result', type: 'page', ref: 'evidence/result.html'},
      {name: 'Catalogue', type: 'zip', ref: 'evidence/c.pdf'}, {name: '', type: 'img', ref: 'evidence/x.png'}, {name: 'Bad', ref: 7}]}};
  const it = UI.review.mapCard(c, {fileUrl: (k, ref) => ref === 'evidence/c.pdf' ? '' : '/f/' + ref}, NOW);
  assert.deepEqual(JSON.parse(JSON.stringify(it.files)), [{label: 'Cover photo', type: 'img', src: '/f/evidence/shop.png'}, {label: 'Result', type: 'page', src: '/f/evidence/result.html'}]);
  assert.equal(UI.review.mapCard(card('a'), fakeApi([[]]), NOW).files.length, 0);
});

test('mapCard: own answer buttons pass through (label and pick, at most 4)', () => {
  const {UI} = load();
  const it = UI.review.mapCard(card('a', {answers:[{label:'Not now', picked:'Not now'}, {label:'', picked:'x'}, {label:'Start', picked:7}, {label:'Start', picked:'Start'}]}), fakeApi([[]]), NOW);
  assert.equal(JSON.stringify(it.answers), JSON.stringify([{label:'Not now', picked:'Not now'}, {label:'Start', picked:'Start'}]));
  assert.equal(UI.review.mapCard(card('b'), fakeApi([[]]), NOW).answers.length, 0);
});

test('answerRecord: every card names its ticket and a title, never a bare "Answered" (ORCH-172)', () => {
  const {UI} = load();
  const untitled = {kind: 'choice', preview: {type: 'options', options: [{id: 'Yes', title: 'Yes'}, {id: 'No', title: 'No'}]}};
  const long = 'Which helper should the always-on session in Focus be? A: the Chat helper itself, shown in Focus with its screen and a terminal command, or B: a separate manager.';
  const rec = UI.answerRecord(entry({action: 'use', picked: 'No'}, {card: untitled, ticket_key: 'ORCH-147', ticket_title: 'Focus: always-on manager', text: long, shown: null}), {now: NOW, ticketHref: id => '#ticket/' + id});
  const h3 = rec.all(n => n.tag === 'h3')[0].textContent;
  assert.notEqual(h3, 'Answered'); assert.match(h3, /^Which helper should the always-on session/); assert.ok(h3.length <= 121 && h3.endsWith('…'));
  const link = rec.all(n => n.tag === 'a' && n.href === '#ticket/T-1')[0];
  assert.ok(link, 'the ticket key and title link to the ticket'); assert.equal(link.textContent, 'ORCH-147 · Focus: always-on manager');
  assert.equal(UI.answerRecord(entry({action: 'approve'}, {card: {}, ticket_title: 'Fix the date', shown: null}), {now: NOW}).all(n => n.tag === 'h3')[0].textContent, 'Fix the date');
  const own = UI.answerRecord(entry({action: 'approve'}, {ticket_key: 'ORCH-147', ticket_title: 'Focus'}), {now: NOW, showTicket: false});
  assert.doesNotMatch(own.textContent, /ORCH-147/, 'the ticket page does not repeat its own key');
});

test('answerRecord: a card with nothing to show gets no empty "Reviewed" tile (ORCH-172)', () => {
  const {UI} = load();
  const rec = UI.answerRecord(entry({action: 'approve'}, {card: {kind: 'draft', preview: {type: 'doc'}}, shown: null}), {now: NOW});
  assert.equal(rec.byClass('decision-shown').length, 0); assert.doesNotMatch(rec.textContent, /Reviewed/);
  const words = UI.answerRecord(entry({action: 'approve'}, {card: {kind: 'check', title: 'Done', preview: {type: 'doc', heading: 'What was done', paras: ['Fixed it.']}}, shown: null}), {now: NOW});
  assert.equal(words.byClass('decision-shot').length, 1, 'a words preview keeps its tile');
});

test('a click on a tile opens it large with the card\'s other tiles a step away (ORCH-172)', () => {
  const {UI, document} = load();
  const rec = UI.answerRecord(entry({action: 'approve'}, {card: {kind: 'draft', title: 'Tickets board', preview: {type: 'compare', before: {type: 'img', src: 'reviewed/aa/before.png'}, after: {type: 'img', src: 'reviewed/aa/after.png'}}}}), {fileUrl: (e, r) => '/f/' + r, now: NOW});
  const tiles = rec.byClass('decision-shot');
  assert.equal(tiles.length, 2); assert.equal(tiles[1].attrs['aria-label'], 'Open After large');
  assert.equal(tiles[0].children[0].children[0].alt, 'Before', 'every picture has a name');
  tiles[1].fire('click');
  const d = document.body.children.at(-1);
  assert.equal(d.tag, 'dialog'); assert.ok(d.open); assert.ok(d.className.includes('review-viewer'));
  assert.match(d.textContent, /After/); assert.match(d.textContent, /2 of 2/);
  assert.equal(d.byClass('review-viewer-body')[0].children[0].src, '/f/reviewed/aa/after.png');
  d.fire('keydown', {key: 'ArrowLeft'});
  assert.match(d.textContent, /1 of 2/); assert.equal(d.byClass('review-viewer-body')[0].children[0].src, '/f/reviewed/aa/before.png');
});

test('a words preview opens in full in the large view, not cut (ORCH-172)', () => {
  const {UI, document} = load();
  const paras = ['In short: helpers waiting for checks no longer take a place.', 'Merged on green with tests.', 'Third paragraph the tile does not show.'];
  const rec = UI.answerRecord(entry({action: 'approve'}, {card: {kind: 'check', title: 'Helpers waiting', preview: {type: 'doc', heading: 'What was done', paras}}, shown: null}), {now: NOW});
  assert.doesNotMatch(rec.textContent, /Third paragraph/);
  rec.byClass('decision-shot')[0].fire('click');
  const d = document.body.children.at(-1);
  paras.forEach(p => assert.ok(d.textContent.includes(p)));
});

test('the large view of a words box uses the card\'s own words box when the kit has it (steps, rows, status) (ORCH-183)', () => {
  const {UI, document} = load();
  let got = null;
  UI.docBox = (pv, tag) => { got = [pv, tag]; const n = document.createElement('div'); n.className = 'doc'; n.textContent = 'BOX'; return n; };
  const pv = {type: 'doc', heading: 'What goes out · 2 changes', rows: [{title: 'One', n: 1}], steps: ['a']};
  UI.reviewViewer([{label: 'Release', preview: pv}], 0, {title: 'Release 32'});
  const d = document.body.children.at(-1);
  assert.equal(got[0], pv); assert.equal(got[1], 'h3');
  assert.match(d.textContent, /BOX/);
});

// ORCH-477 (owner pick B): a result's PDF is a PDF tile (its first page shows), and every file opens large in the page:
// a PDF in the browser's own view without its toolbar, with "Open in new tab" inside the viewer.
test('mapCard: a PDF file is a pdf tile, by its type or its name', () => {
  const {UI} = load();
  const c = {id: 'core:review:t_x', ticket: 'T-1', key: 'review', digest: 'd', card: {kind: 'check', title: 'Done',
    files: [{name: 'Weekly report.pdf', type: 'file', ref: 'evidence/r.pdf'}, {name: 'Flyer', type: 'pdf', ref: 'evidence/f.pdf'}, {name: 'notes.md', type: 'file', ref: 'evidence/n.md'}]}};
  const it = UI.review.mapCard(c, {fileUrl: (k, ref) => '/f/' + ref}, NOW);
  assert.deepEqual(it.files.map(f => f.type), ['pdf', 'pdf', 'file']);
});
test('the large view shows a PDF in the browser\'s own view and keeps "Open in new tab" inside', () => {
  const {UI, document} = load();
  UI.reviewViewer([{label: 'Weekly report.pdf', src: '/f/r.pdf', open: '/f/r.pdf', preview: {type: 'pdf'}}, {label: 'notes.md', src: '/f/n.md', open: '/f/n.md', preview: {type: 'file'}}], 0, {title: 'Weekly report'});
  const d = document.body.children.at(-1), body = d.byClass('review-viewer-body')[0];
  assert.equal(body.children[0].tag, 'object'); assert.equal(body.children[0].type, 'application/pdf');
  const out = d.all(n => n.tag === 'a')[0];
  assert.equal(out.textContent, 'Open in new tab'); assert.equal(out.href, '/f/r.pdf'); assert.equal(out.target, '_blank'); assert.equal(out.hidden, false);
  d.fire('keydown', {key: 'ArrowRight'});
  assert.match(body.textContent, /cannot be shown here/); assert.equal(out.href, '/f/n.md');
});

// ORCH-848: Run it now cards in the deck
const runRow = (id, extra = {}) => card(id, {phone_run: true, run_last: {exit: 1, output: 'x', error: 'e'},
  card: {kind: 'run', title: 'Turn on the second look', ok_label: 'I ran it', no_label: 'Leave it off for now',
    run: {v: 1, command: 'orch config set workflow.reviewer_look on', argv: ['orch'], cwd: '~/w', class: 'orch', exe: 'orch', changes: 'c', undo: 'u'}}, ...extra});

test('a run card maps to a Run item with its command, its other answer and the phone flag', () => {
  const {UI} = load();
  const it = UI.review.mapCard(runRow('r'), fakeApi([[]]), NOW);
  assert.equal(it.kind, 'run'); assert.equal(it.kindLabel, 'Run'); assert.equal(it.icon, 'code');
  assert.equal(it.run.command, 'orch config set workflow.reviewer_look on');
  assert.equal(it.noLabel, 'Leave it off for now'); assert.equal(it.okLabel, 'I ran it');
  assert.equal(it.phoneRun, true); assert.equal(it.runLast.exit, 1);
  assert.equal(UI.review.mapCard(card('d'), fakeApi([[]]), NOW).run, undefined);
});

test('the deck gets api.run for a run card and an answer made by running is not sent again', async () => {
  const runs = [], answers = [];
  const api = fakeApi([[runRow('r')]], async b => { answers.push(b); return {ok: true}; });
  api.run = async x => { runs.push(x); return {ok: true, exit: 0, output: 'done'}; };
  const {decks} = await mount(api);
  const d = decks[0];
  const res = await d.o.onRun(d.items[0], {confirmed: true});
  assert.equal(res.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(runs)), [{id: 'r', digest: 'd-r', confirmed: true}]);
  d.o.onDecide(d.items[0], 'ok', {ran: true});
  await flush();
  assert.equal(answers.length, 0, 'Run it now already answered the card');
});

test('the other answer of a run card goes the usual way', async () => {
  const answers = [];
  const {decks} = await mount(fakeApi([[runRow('r')]], async b => { answers.push(b); return {ok: true}; }));
  decks[0].o.onDecide(decks[0].items[0], 'no', null);
  await flush();
  assert.equal(answers.length, 1); assert.equal(answers[0].verdict, 'no');
});

test('without api.run the card says it cannot run', async () => {
  const {decks} = await mount(fakeApi([[runRow('r')]]));
  const res = await decks[0].o.onRun(decks[0].items[0], {});
  assert.equal(res.ok, false);
});

test('UI.moreText: a text of more than three lines is cut; o.node (an editable field) is cut the same way (ORCH-1696)', () => {
  const {UI, document} = load();
  const short = UI.moreText('One line.');
  assert.ok(!short.classList.contains('clamped'));
  const lines = UI.moreText('a\nb\nc\nd');
  assert.ok(lines.classList.contains('clamped'), 'four short lines are cut');
  const field = document.createElement('button');
  const w = UI.moreText('x'.repeat(400), {node: field});
  assert.equal(w.children[0], field, 'the field shows, not a plain line');
  assert.ok(w.classList.contains('clamped'));
  assert.equal(w.children[1].textContent, 'Show more');
});
// ORCH-1847: orch marks a plain reversible question one_tap; the page passes it on and saves the tap as the usual answer
const plainQ = (extra = {}) => card('core:q:t_1:q1', {key: 'q1', ticket_key: 'PIL-2', recommended: 'Tuesday', one_tap: true, text: 'The supplier can deliver on Tuesday or Thursday. Which day?',
  card: {kind: 'choice', title: 'The supplier can deliver on Tuesday or Thursday. Which day?', preview: {type: 'options', options: [{id: 'Tuesday', title: 'Tuesday'}, {id: 'Thursday', title: 'Thursday'}]}}, ...extra});
test('one tap: mapCard passes one_tap only for a choice; the tap is saved once as the plain answer, after the Undo time', async () => {
  const {UI} = load();
  assert.equal(UI.review.mapCard(plainQ(), fakeApi([[]]), NOW).oneTap, true);
  assert.equal(UI.review.mapCard(plainQ({one_tap: 'yes'}), fakeApi([[]]), NOW).oneTap, false);
  assert.equal(UI.review.mapCard(card('a', {one_tap: true}), fakeApi([[]]), NOW).oneTap, false, 'not a choice: never one tap');
  const sent = [];
  const {decks} = await mount(fakeApi([[plainQ()]], async b => { sent.push(b); return {ok: true}; }), {hold: 20});
  decks[0].o.onDecide(decks[0].items[0], 'ok', {picked: 'Thursday'});
  await flush();
  assert.equal(sent.length, 0, 'held for Undo first');
  await new Promise(r => setTimeout(r, 40));
  assert.deepEqual(JSON.parse(JSON.stringify(sent)), [{id: 'core:q:t_1:q1', digest: 'd-core:q:t_1:q1', verdict: 'ok', picked: 'Thursday', note: null}]);
});
test('one tap on a question answered elsewhere (Home, the phone): says so and reloads; a stale one shows the new version', async () => {
  const api = fakeApi([[plainQ()], []], async () => ({ok: false, error: {code: 'decided', message: 'Answered already on Home by severin.'}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'ok', {picked: 'Thursday'});
  await flush(); await flush();
  assert.equal(toasts[0].m, 'Answered already on Home by severin.');
  const st = fakeApi([[plainQ()], [plainQ({digest: 'd-new'})]], async () => ({ok: false, error: {code: 'changed', message: 'x'}}));
  const b = await mount(st);
  b.decks[0].o.onDecide(b.decks[0].items[0], 'ok', {picked: 'Thursday'});
  await flush(); await flush();
  assert.equal(b.toasts[0].m, 'This card changed. Showing the new version.');
  assert.equal(b.decks[1].items[0].digest, 'd-new');
});

// Review overhaul (owner's picks 25 Nov 2026): the twelve card names, what holds up work first, the result card's title.
test('R3 B: a card shows the name orch gave its kind; a card without one gets its lane from its plain kind', () => {
  const {UI} = load();
  const q = UI.review.mapCard(card('q', {card_kind: {family: 'answer', kind: 'question', name: 'Question', lane: 'holds_up'}}), fakeApi([[]]), NOW);
  assert.equal(q.kindLabel, 'Question'); assert.equal(q.icon, 'comment'); assert.equal(q.lane, 'holds_up'); assert.equal(q.laneName, 'Holds up work now');
  const old = UI.review.mapCard(card('o'), fakeApi([[]]), NOW);
  assert.equal(old.kindLabel, 'Draft'); assert.equal(old.lane, 'look');
  const stuck = UI.review.mapCard(card('s', {card: {kind: 'stuck', title: 'x'}}), fakeApi([[]]), NOW);
  assert.equal(stuck.lane, 'holds_up');
  const bad = UI.review.mapCard(card('b', {card_kind: {name: 'X', lane: 'nowhere'}}), fakeApi([[]]), NOW);
  assert.equal(bad.lane, 'look', 'an unknown lane is never trusted');
});

test('Test results keeps its check icon with the current and legacy card kind', () => {
  const {UI} = load();
  for (const kind of ['test_results', 'check_result']) {
    const result = UI.review.mapCard(card('result', {card_kind: {family: 'look', kind, name: 'Test results', lane: 'look'}}), fakeApi([[]]), NOW);
    assert.equal(result.kindLabel, 'Test results');
    assert.equal(result.icon, 'check');
    assert.equal(result.lane, 'look');
  }
});

test('R2 A: the deck gets what holds up work first, the stack order inside a lane', async () => {
  const look = (id) => card(id, {card_kind: {family: 'look', kind: 'pictures', name: 'Pictures', lane: 'look'}});
  const ask = (id) => card(id, {card_kind: {family: 'answer', kind: 'question', name: 'Question', lane: 'holds_up'}});
  const live = (id) => card(id, {card_kind: {family: 'click', kind: 'put_live', name: 'Put it live', lane: 'click'}});
  const {decks} = await mount(fakeApi([[look('l1'), ask('a1'), live('p1'), look('l2'), ask('a2')]]));
  assert.deepEqual(decks.at(-1).items.map(i => i.id), ['a1', 'a2', 'p1', 'l1', 'l2']);
});

test('R6 A: a finished-work card says what changed as its title, the ticket stays in the quiet line', () => {
  const {UI} = load();
  const c = card('r', {ticket_title: 'Spring sale', card: {kind: 'check', title: 'Spring sale', preview: {type: 'doc', headline: 'The spring sale email is written, with a phone version.', paras: ['x']}}});
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.equal(it.title, 'The spring sale email is written, with a phone version.');
  assert.equal(it.ticketTitle, 'Spring sale');
  assert.equal(it.preview.headline, undefined, 'the headline is not shown twice');
});

test('Reviewer mode propose: the card carries the proposal and suggests its button', () => {
  const {UI} = load();
  const c = card('p', {recommended: 'ok', proposal: {verdict: 'accept', why: 'every part has evidence'}, card: {kind: 'check', title: 'T'}});
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.deepEqual({...it.proposal}, {verdict: 'accept', why: 'every part has evidence'});
  assert.equal(it.suggest, 'ok');
  assert.equal(UI.review.mapCard(card('z', {proposal: {verdict: 'merge'}}), fakeApi([[]]), NOW).proposal, undefined);
});

// ORCH-2184 (Focused review C): attention groups, tiles over the deck, rounds of up to 5, behind decisionFirst
const grp = (id, g, extra = {}) => card(id, {attention: {group: g, why: 'x'}, ...extra});
const mountTiles = async (stack, o = {}) => {
  const env = load(), host = new N('main');
  env.UI.attentionTiles = (groups, to) => { const n = new N('div'); n.className = 'attn-tiles'; n.groups = groups; n.pick = to.onPick; return n; };
  const answers = [];
  const api = fakeApi([stack], async b => { answers.push(b); return {ok: true}; });
  const page = env.UI.reviewPage(host, api, {poll: 0, now: NOW, hold: 0, decisionFirst: true, ...o});
  await flush();
  const attn = () => host.byClass('review-attn')[0];
  return {...env, host, page, attn, answers};
};
test('ORCH-2184: mapCard carries the group (unknown is a Short decision, never quick) and a real due time', () => {
  const {UI} = load(), m = c => JSON.parse(JSON.stringify(UI.review.mapCard(c, fakeApi([[]]), NOW)));
  assert.deepEqual(m(grp('a', 'quick')).attention, {group: 'quick', name: 'Quick look', why: 'x'});
  assert.equal(m(grp('a', 'fast')).attention.group, 'short');
  assert.equal(m(card('a')).attention.group, 'short');
  assert.equal(m(card('a', {due: '2026-11-16T08:00:00Z'})).due, '2026-11-16T08:00:00Z');
  assert.equal(m(card('a', {due: 'Friday'})).due, '');
  assert.equal(UI.review.fmtDue('2026-11-16T08:00:00', NOW), 'tomorrow 08:00');
});
test('ORCH-2184: more than 5 cards: three tiles over the deck; a tile starts a round of up to 5 of its group', async () => {
  const stack = [grp('q1', 'quick'), grp('q2', 'quick'), grp('s1', 'short'), grp('s2', 'short'), grp('s3', 'short'), grp('s4', 'short'), grp('s5', 'short'), grp('s6', 'short'),
    grp('t1', 'time', {due: '2026-11-16T08:00:00', card_kind: {family: 'answer', kind: 'question', name: 'Question', lane: 'holds_up'}})];
  const {decks, attn} = await mountTiles(stack);
  assert.equal(attn().hidden, false);
  assert.equal(decks.at(-1).items.length, 9, 'the deck and the list keep every card');
  const tiles = attn().byClass('attn-tiles')[0];
  assert.deepEqual(JSON.parse(JSON.stringify(tiles.groups.map(g => [g.group, g.count, g.hold]))), [['quick', 2, 0], ['short', 6, 0], ['time', 1, 1]]);
  assert.equal(tiles.groups[2].deadline, 'Next deadline: Home block t1 · tomorrow 08:00');
  tiles.pick('short');
  const d = decks.at(-1);
  assert.deepEqual([...d.items.map(i => i.id)], ['s1', 's2', 's3', 's4', 's5'], 'a round of 5');
  assert.match(attn().textContent, /Short decision.*Back to the start/);
  assert.match(attn().textContent, /Keys: the numbers answer, J next card, K card before, U undo, Esc close/);
  assert.equal(typeof d.o.onEscape, 'function');
  d.o.onEscape();
  assert.equal(decks.at(-1).items.length, 9, 'Esc: back to the start');
  assert.ok(attn().byClass('attn-tiles')[0]);
});
test('ORCH-2184: the round ends on What you decided, Still waiting and Next N; nothing is answered by itself', async () => {
  const stack = [grp('q1', 'quick'), grp('q2', 'quick'), grp('q3', 'quick'), grp('s1', 'short'), grp('s2', 'short'), grp('s3', 'short')];
  const {decks, attn, answers} = await mountTiles(stack);
  attn().byClass('attn-tiles')[0].pick('quick');
  const d = decks.at(-1);
  assert.equal(answers.length, 0, 'starting a round answers nothing');
  d.o.onDecide(d.items[0], 'ok'); d.o.onDecide(d.items[1], 'no'); d.o.onDecide(d.items[2], 'ok');
  await flush();
  assert.equal(answers.length, 3, 'only the three answers the person gave');
  const end = d.o.endView();
  assert.match(end.textContent, /^What you decided/);
  assert.deepEqual(end.byClass('attn-decided-row').map(r => r.textContent), ['Home block q1Build it', "Home block q2Don't do", 'Home block q3Build it']);
  assert.equal(end.byClass('attn-still')[0].textContent, 'Still waiting: 3 in Short decision');
  const [next, back] = end.byClass('attn-end-acts')[0].children;
  assert.equal(next.textContent, 'Next 3 in Short decision');
  assert.equal(back.textContent, 'Back to the start');
  next.onclick();
  assert.deepEqual(decks.at(-1).items.map(i => i.id), ['s1', 's2', 's3']);
});
test('ORCH-2184: 5 cards or fewer, or the switch off: no tiles, the deck as today', async () => {
  const few = await mountTiles([grp('a', 'quick'), grp('b', 'short')]);
  assert.equal(few.attn().hidden, true);
  const many = Array.from({length: 7}, (_, i) => grp('c' + i, 'short'));
  const off = await mountTiles(many, {decisionFirst: false});
  assert.equal(off.attn().hidden, true);
  assert.equal(off.decks.at(-1).items.length, 7);
});

test('ORCH-2316: the groups use the draft words, a card keeps its kind and the open parts of a result', () => {
  const {UI} = load();
  assert.equal(Object.values(UI.review.LANES).slice(0, 4).join('|'), 'Holds up work now|Put it live|Try it yourself|Look at the result');
  const live = UI.review.mapCard(card('l', {card: {kind: 'link', title: 'Release', ok_label: 'Merge'}, card_kind: {family: 'click', kind: 'put_live', name: 'Put it live', lane: 'click'}}), fakeApi([[]]), NOW);
  assert.equal(live.cardKind, 'put_live'); assert.equal(live.laneName, 'Put it live');
  const run = UI.review.mapCard(card('r', {card: {kind: 'run', title: 'Sign in'}}), fakeApi([[]]), NOW);
  assert.equal(run.lane, 'help', 'a plain run card sits with Try it yourself');
  const res = UI.review.mapCard(card('c', {card: {kind: 'check', title: 'x', blocked: 'open', open_parts: [{asked: 'Three widths', got: 'two'}, {asked: 5}]}}), fakeApi([[]]), NOW);
  assert.equal(JSON.stringify(res.openParts), JSON.stringify([{asked: 'Three widths', got: 'two'}]));
  assert.equal(UI.review.laneOf({card_kind: {name: 'Question', kind: 'question', lane: 'holds_up'}}), 'holds_up');
});
