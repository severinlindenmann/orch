import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// ORCH-848: UI.runCard states, run/confirm/no flow, and that card text is only ever set with textContent.
const read = f => readFileSync(new URL('../static/' + f, import.meta.url), 'utf8');

class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.style = {}; this.className = ''; this.own = ''; this.hidden = false; this.disabled = false; this.innerHTMLSets = 0; }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this.innerHTMLSets++; this.own = ''; }
  get lastChild() { return this.children[this.children.length - 1]; }
  append(...c) { c.forEach(x => this.children.push(typeof x === 'string' ? Object.assign(new N('#text'), {own: x}) : x)); }
  replaceChildren(...c) { this.children = []; this.own = ''; this.append(...c); }
  setAttribute(k, v) { this.attrs[k] = v; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
  byClass(c) { return this.all(n => n.className.split(' ').includes(c)); }
  byAct(a) { return this.all(n => n.dataset.act === a)[0]; }
  btns() { return this.all(n => n.tag === 'button').map(b => b.textContent); }
  click() { return this.onclick && this.onclick(); }
}
const tick = () => new Promise(r => setTimeout(r, 0));

function load() {
  const toasts = [], innerSets = [];
  const document = {createElement: t => new N(t), createElementNS: (_, t) => { const n = new N(t); innerSets.push(n); return n; }};
  const UI = {toast: (m, u, k) => toasts.push({m, k}), copyText: async () => true};
  vm.runInNewContext(read('widgets.js'), {window: {UI}, document, setTimeout, clearTimeout, console});
  return {UI, toasts};
}
const item = (cls = 'orch', extra = {}) => ({kind: 'run', no_label: 'Leave it off for now', ok_label: 'I ran it',
  run: {command: 'orch config set workflow.reviewer_look on', cwd: '~/workspace-orch', class: cls, changes: 'Release walks run', undo: 'orch config set workflow.reviewer_look off', ...extra}});
const NOW = new Date(2026, 10, 19, 14, 32);

test('waiting: Run it now is filled on Review, outlined elsewhere, and names the folder', () => {
  const {UI} = load();
  const a = UI.runCard(item(), {primary: true}), b = UI.runCard(item(), {});
  assert.equal(a.dataset.state, 'waiting');
  assert.match(a.byAct('run').className, /\bprimary\b/);
  assert.match(b.byAct('run').className, /\boutline\b/);
  assert.ok(a.btns().includes('Run it now') && a.btns().includes('Leave it off for now'));
  assert.match(a.textContent, /Runs in ~\/workspace-orch/);
});

test('a click runs it: Running…, then Done with the result line and what it printed', async () => {
  const {UI} = load();
  let release, got, done;
  const c = UI.runCard(item(), {now: NOW, run: x => { got = x; return new Promise(r => { release = r; }); }, onDone: r => { done = r; }});
  c.byAct('run').click();
  assert.equal(c.dataset.state, 'running');
  assert.equal(c.byAct('run').disabled, true);
  assert.match(c.byAct('run').textContent, /Running…/);
  assert.equal(JSON.stringify(got), '{"confirmed":false}');
  release({ok: true, exit: 0, output: 'github.release_walks = on'});
  await tick();
  assert.equal(c.dataset.state, 'done');
  assert.match(c.textContent, /I ran it · You ran it at 14:32/);
  assert.match(c.textContent, /github\.release_walks = on/);
  assert.equal(c.byAct('run'), undefined);
  assert.equal(done.ok, true);
});

test('done with no output says so', async () => {
  const {UI} = load();
  const c = UI.runCard(item(), {now: NOW, run: async () => ({ok: true, exit: 0, output: ''})});
  c.byAct('run').click(); await tick();
  assert.match(c.textContent, /\(it printed nothing\)/);
});

test('failed: error line and output stay, the button says Run it again', async () => {
  const {UI} = load();
  const c = UI.runCard(item(), {run: async () => ({ok: false, exit: 1, output: 'orch: refused', error: 'It ended with exit code 1.'})});
  c.byAct('run').click(); await tick();
  assert.equal(c.dataset.state, 'failed');
  assert.equal(c.byAct('run').textContent, 'Run it again');
  assert.match(c.textContent, /It ended with exit code 1\./);
  assert.match(c.textContent, /orch: refused/);
  assert.equal(c.byClass('run-error')[0].attrs.role, 'alert');
});

test('a refusal or a lost connection is the error line', async () => {
  const {UI} = load();
  const a = UI.runCard(item(), {run: async () => ({ok: false, error: 'The card changed after you saw it.'})});
  a.byAct('run').click(); await tick();
  assert.match(a.textContent, /changed after you saw it/);
  const b = UI.runCard(item(), {run: () => Promise.reject(new Error('x'))});
  b.byAct('run').click(); await tick();
  assert.match(b.textContent, /Could not reach orch\./);
});

test('a failed try from before shows at once with orch\'s own error words', () => {
  const {UI} = load();
  const c = UI.runCard(item(), {last: {at: 'x', by: 'you', exit: 1, output: 'boom', error: 'It ended with exit code 1.'}});
  assert.equal(c.dataset.state, 'failed');
  assert.match(c.textContent, /It ended with exit code 1\./);
  assert.equal(c.byAct('run').textContent, 'Run it again');
});

test('a command that is not orch\'s own: first click confirms, one way out, then runs confirmed', async () => {
  const {UI} = load();
  const calls = [];
  const c = UI.runCard(item('other', {command: 'brew install gh'}), {run: async x => { calls.push(x); return {ok: true, output: ''}; }});
  c.byAct('run').click();
  assert.equal(c.dataset.state, 'confirm');
  assert.equal(calls.length, 0);
  assert.match(c.textContent, /This is not an orch command/);
  assert.match(c.byClass('run-confirm')[0].textContent, /brew install gh/);
  assert.ok(!c.btns().includes('Leave it off for now'), 'the other answer is hidden while confirming');
  assert.ok(c.btns().includes('Cancel'));
  c.byAct('cancel').click();
  assert.equal(c.dataset.state, 'waiting');
  c.byAct('run').click();
  c.byAct('confirmed').click(); await tick();
  assert.equal(JSON.stringify(calls), '[{"confirmed":true}]');
  assert.equal(c.dataset.state, 'done');
});

test('login and copy cards: Copy only, no Run it now, their own line', () => {
  const {UI} = load();
  const l = UI.runCard(item('login', {command: 'codex login'}), {primary: true});
  assert.equal(l.dataset.state, 'login');
  assert.equal(l.byAct('run'), undefined);
  assert.match(l.textContent, /This is a sign-in: run it in your terminal\./);
  assert.ok(l.btns().includes('Copy'));
  const c = UI.runCard(item('copy', {command: 'git log -5', changes: 'x', undo: 'y'}), {});
  assert.equal(c.byAct('run'), undefined);
  assert.match(c.textContent, /orch did not check this command\. Read it before you run it in your terminal\./);
  assert.equal(c.byClass('run-facts').length, 0, 'a copy card has no Changes or Undo rows');
});

test('phone: copy only with the reason, unless the phone may run it', () => {
  const {UI} = load();
  const p = UI.runCard(item('other', {command: 'brew install gh'}), {phone: true, phoneRun: false});
  assert.equal(p.dataset.state, 'phone');
  assert.equal(p.byAct('run'), undefined);
  assert.match(p.textContent, /The phone runs only orch’s own commands\. Run this one at your computer\./);
  const q = UI.runCard(item(), {phone: true, phoneRun: true});
  assert.ok(q.byAct('run'));
});

test('the other answer goes through o.no and shows the answer', async () => {
  const {UI} = load();
  let n = 0, said = 0;
  const c = UI.runCard(item(), {now: NOW, no: async () => { n++; return {ok: true}; }, onNo: () => { said++; }});
  c.byAct('no').click(); await tick();
  assert.equal(n, 1); assert.equal(said, 1);
  assert.equal(c.dataset.state, 'left');
  assert.match(c.textContent, /Leave it off for now/);
});

test('a refused other answer keeps the card and toasts', async () => {
  const {UI, toasts} = load();
  const c = UI.runCard(item(), {no: async () => ({ok: false, error: 'Sign in to answer'})});
  c.byAct('no').click(); await tick();
  assert.equal(c.dataset.state, 'waiting');
  assert.equal(toasts[0].m, 'Sign in to answer');
});

test('card text is set with textContent, never as HTML', () => {
  const {UI} = load();
  const evil = '<img src=x onerror=alert(1)>';
  const c = UI.runCard(item('orch', {command: evil, cwd: evil, changes: evil, undo: evil}), {});
  assert.ok(c.textContent.includes(evil));
  const all = c.all(() => true);
  assert.ok(all.every(n => n.innerHTMLSets === 0 || n.tag === 'svg'), 'innerHTML only on the fixed status icons');
  const src = read('widgets.js'), a = src.indexOf('UI.runCard='), b = src.indexOf('/* Helpers list (ORCH-61)');
  assert.doesNotMatch(src.slice(a, b), /innerHTML|insertAdjacentHTML/);
});

// ORCH-865: a sign-in whose Run it now opens the Focus terminal; the card answers itself later (never here).
test('a sign-in without the terminal keeps Copy only', () => {
  const {UI} = load();
  const c = UI.runCard(item('login', {command: 'codex login'}), {});
  assert.equal(c.dataset.state, 'login');
  assert.equal(c.byAct('run'), undefined);
  assert.ok(c.btns().includes('Copy'));
});

test('a sign-in with the terminal: Run it now opens it, then the card waits for the sign-in', async () => {
  const {UI} = load();
  let release, shown = null, done = false;
  const c = UI.runCard(item('login', {command: 'codex login'}), {terminal: true, run: () => new Promise(r => { release = r; }),
    show: id => { shown = id; }, onDone: () => { done = true; }});
  assert.equal(c.dataset.state, 'waiting');
  assert.match(c.textContent, /Opens the terminal in Focus and starts the sign-in there/);
  c.byAct('run').click();
  assert.match(c.byAct('run').textContent, /Opening…/);
  release({ok: true, signing: true, terminal: 't_term01', answered: false});
  await tick();
  assert.equal(c.dataset.state, 'signing');
  assert.equal(done, false);  // not answered: only the terminal's sign-in and its green check answer it
  assert.doesNotMatch(c.textContent, /I ran it ·/);
  assert.match(c.textContent, /answers itself once the sign-in ended and its login check is green/);
  c.byAct('show').click();
  assert.equal(shown, 't_term01');
});

test('a sign-in under way stays shown as signing after a reload; a failed try shows its error', () => {
  const {UI} = load();
  const s = UI.runCard(item('login', {command: 'codex login'}), {terminal: true, signing: {at: 'x', state: 'running', terminal: 't_term01'}});
  assert.equal(s.dataset.state, 'signing');
  const f = UI.runCard(item('login', {command: 'codex login'}), {terminal: true,
    last: {exit: 0, output: '', error: 'The sign-in ended, but its login check is not green. Nothing was marked as done.'}});
  assert.equal(f.dataset.state, 'failed');
  assert.match(f.textContent, /login check is not green/);
  assert.ok(f.btns().includes('Run it again'));
});
