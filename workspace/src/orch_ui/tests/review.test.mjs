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
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
  byClass(c) { return this.all(n => n.className.split(' ').includes(c)); }
}

function load() {
  const toasts = [], decks = [];
  const UI = {
    toast: (m, u, k) => toasts.push({m, k}),
    state: o => { const n = new N('div'); n.className = 'state ' + o.kind; n.append(Object.assign(new N('strong'), {own: o.title || ''}), Object.assign(new N('p'), {own: o.text || ''})); n.opts = o; return n; },
    swipeDeck: (host, items, o) => { const d = {host, items, o, answers: {}, pins: {}, later: new Set(o.later || []), index: o.start || 0, busy: false}; decks.push(d); host.replaceChildren(); return d; },
  };
  const document = {createElement: t => new N(t), visibilityState: 'visible'};
  const window = {UI};
  vm.runInNewContext(read('review.js'), {window, document, setInterval, clearInterval, console});
  return {UI, toasts, decks};
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
  const page = env.UI.reviewPage(host, api, {poll: 0, now: NOW, ...o});
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

test('mapCard keeps option previews and picks a kind label', () => {
  const {UI} = load();
  const c = card('o'); c.card = {kind: 'choice', title: 'Which?', preview: {type: 'options', options: [{id: 'A', title: 'As today', preview: {type: 'page', src: 'reviewed/aa/a.html'}}, {id: 'B', title: 'New', suggested: true}]}};
  const it = UI.review.mapCard(c, fakeApi([[]]), NOW);
  assert.equal(it.kindLabel, 'Choose'); assert.equal(it.preview.options[0].preview.src, '/f/T-1/reviewed/aa/a.html');
  assert.equal(it.preview.options[1].suggested, true);
});

test('the deck is text only by default: voice is off', async () => {
  const {decks} = await mount(fakeApi([[card('a')]]));
  assert.equal(decks[0].o.voice, false);
  const w = read('widgets.js');
  assert.match(w, /if\(o\.voice\)voice\.append\(mic,wave\)/);
  assert.match(w, /if\(o\.voice\)sh\.append\(voice,clips\)/);
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

test('other errors show the message and bring the card back', async () => {
  const api = fakeApi([[card('a')]], async () => ({ok: false, error: {code: 'refused', message: 'Not allowed.'}}));
  const {decks, toasts} = await mount(api);
  decks[0].o.onDecide(decks[0].items[0], 'no', null);
  await flush(); await flush();
  assert.equal(toasts[0].m, 'Not allowed.'); assert.equal(decks.length, 2);
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
  assert.match(m.host.textContent, /Nothing waits for you/);
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
