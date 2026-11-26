// Renew from the warning (ORCH-46): the button a warning row gets, and the window's steps.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const SRC = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/renew.js'), 'utf8');

// A tiny DOM: enough for buttons, a dialog and text.
function node(tag) {
  const n = {tag, children:[], dataset:{}, attrs:{}, listeners:{}, hidden:false, disabled:false, value:'', open:false, className:'',
    append(...c) { this.children.push(...c.filter(x => x != null)); }, replaceChildren(...c) { this.children = c.filter(x => x != null); },
    setAttribute(k, v) { this.attrs[k] = String(v); }, addEventListener(t, f) { (this.listeners[t] ||= []).push(f); },
    focus() {}, click() { (this.listeners.click || []).forEach(f => f({})); },
    showModal() { this.open = true; }, get firstChild() { return this.children[0]; },
    get text() { return [this.textContent || '', ...this.children.map(c => typeof c === 'string' ? c : c.text)].join(''); }};
  return n;
}
function context(answers, status = () => 200) {
  const calls = [];
  const h = (tag, attrs = {}, ...kids) => { const n = node(tag); for (const [k, v] of Object.entries(attrs)) { if (k === 'className' || k === 'hidden') n[k] = v; else n.attrs[k] = v; } n.append(...kids.flat().map(k => typeof k === 'string' ? Object.assign(node('#text'), {textContent:k}) : k)); return n; };
  const button = (text, cls, click) => { const b = node('button'); b.textContent = text; b.className = 'btn ' + cls; b.addEventListener('click', click); return b; };
  const dialogs = [];
  const dialog = (title, cls) => { const d = node('dialog'); d.title = title; d.className = cls; const actions = node('div'); actions.append(button('Cancel', 'ghost', () => { d.open = false; (d.listeners.close || []).forEach(f => f()); })); dialogs.push(d); return {d, actions}; };
  const fetch = async (url, opts) => {
    const body = JSON.parse(opts.body);
    calls.push(body);
    const a = answers(body), code = status(body);
    return {status:code, json:async () => ({renew_result:a}), text:async () => code === 200 ? '' : String(a)};
  };
  const c = vm.createContext({h, button, dialog, fetch, snapshot:false, setTimeout:(f) => 0, clearTimeout() {},
    window:{DashHelpers:require('../src/orch_dashboard/web/helpers.js'), orch:{close:d => { d.open = false; (d.listeners.close || []).forEach(f => f()); }}, UI:{stamp:v => 'on ' + v.slice(0, 10)}}, JSON});
  vm.runInContext(SRC, c);
  return {c, calls, dialogs};
}
const flush = () => new Promise(r => setImmediate(r));

test('a row gets Renew, Replace or nothing', () => {
  const {c} = context(() => ({state:'none'}));
  const renew = c.renewButton({name:'claude', label:'Claude Code', renew:true});
  assert.equal(renew.textContent, 'Renew');
  assert.equal(renew.dataset.renew, 'claude');
  assert.match(renew.className, /primary sm/);
  assert.match(c.renewButton({name:'claude', label:'Claude Code', renew:true}, {quiet:true}).className, /ghost sm/);
  const replace = c.renewButton({name:'payments', label:'Payments key', key:'PAY'});
  assert.equal(replace.textContent, 'Replace');
  assert.equal(c.renewButton({name:'gh', label:'GitHub'}), null);  // the row keeps its own Check again
  assert.equal(c.renewButton(null), null);
  c.snapshot = true;
  assert.equal(c.renewButton({name:'claude', label:'Claude Code', renew:true}), null);  // a shared copy: no clicks
});

test('Renew starts the sign-in, shows its link, passes a code and says when it is done', async () => {
  let state = 'link';
  const {c, calls, dialogs} = context(b => b.op === 'logins.code' ? (state = 'done', {state:'checking'})
    : b.op === 'logins.status' ? (state === 'done' ? {state:'done', ends_at:'2026-12-17T00:00:00Z', went_on:['A-1']} : {state:'link', link:'https://claude.com/x'})
    : {state:'link', link:'https://claude.com/x'});
  c.renewButton({name:'claude', label:'Claude Code', renew:true}).click();
  await flush();
  const d = dialogs[0];
  assert.equal(d.title, 'Renew the Claude Code login');
  assert.equal(d.className, 'dialog ui-bottom-close');  // one way out: Cancel or Done, no second × Close
  assert.match(d.text, /orch never sees or keeps your password/);
  const find = (n, t) => n.tag === t.tag && (!t.text || n.text === t.text) ? n : n.children.map(k => typeof k === 'object' && find(k, t)).find(Boolean);
  const open = find(d, {tag:'a', text:'Open the sign-in page'});
  assert.equal(open.attrs.href, 'https://claude.com/x');
  assert.equal(open.attrs.target, '_blank');
  (open.listeners.click || []).forEach(f => f());
  assert.match(d.text, /Does the page show a code\? Paste it here\./);
  const input = find(d, {tag:'input'});
  input.value = 'code-123';
  find(d, {tag:'button', text:'Continue'}).click();
  await flush();
  assert.deepEqual(calls.find(x => x.op === 'logins.code').args, {name:'claude', value:'code-123'});
  assert.equal(input.value, '');  // nothing kept in the page
  await c.renewCall('logins.status', {name:'claude'});
  assert.equal(c.renewDoneText({label:'Claude Code'}, {state:'done', ends_at:'2026-12-17T00:00:00Z', went_on:['A-1']}),
    'Claude Code login renewed. Good until on 2026-12-17. Helpers go on with 1 ticket.');
  calls.length = 0;
  find(d, {tag:'button', text:'Cancel'}).click();  // closing the window ends the sign-in
  await flush();
  assert.deepEqual(calls.map(x => x.op), ['logins.cancel']);
});

test('Replace sends the key once and never keeps it', async () => {
  const {c, calls, dialogs} = context(() => ({state:'works', went_on:[]}));
  c.renewButton({name:'payments', label:'Payments key', key:'PAY'}).click();
  const d = dialogs[0];
  assert.equal(d.title, 'Replace the Payments key');
  assert.equal(d.className, 'dialog ui-bottom-close');
  const find = (n, t) => n.tag === t.tag && (!t.text || n.text === t.text) ? n : n.children.map(k => typeof k === 'object' && find(k, t)).find(Boolean);
  const input = find(d, {tag:'input'});
  assert.equal(input.attrs.type, 'password');
  input.value = 'new-key-value';
  find(d, {tag:'button', text:'Save key'}).click();
  await flush();
  assert.deepEqual(calls[0], {op:'logins.replace', args:{name:'payments', value:'new-key-value'}});
  assert.equal(input.value, '');
  assert.match(d.text, /Payments key replaced\./);
});

test('a code the tool did not take brings the code field back with one plain line', async () => {
  const seq = [{state:'checking', link:'https://claude.com/x'}, {state:'link', link:'https://claude.com/x', again:true}];
  const {c, dialogs} = context(b => b.op === 'logins.status' ? (seq.length ? seq.shift() : {state:'link', link:'https://claude.com/x', again:true})
    : b.op === 'logins.code' ? {state:'link', link:'https://claude.com/x', again:true} : {state:'link', link:'https://claude.com/x'});
  c.renewButton({name:'claude', label:'Claude Code', renew:true}).click();
  await flush();
  const d = dialogs[0];
  const find = (n, t) => n.tag === t.tag && (!t.text || n.text === t.text) ? n : n.children.map(k => typeof k === 'object' && find(k, t)).find(Boolean);
  (find(d, {tag:'a', text:'Open the sign-in page'}).listeners.click || []).forEach(f => f());
  find(d, {tag:'input'}).value = 'half';
  find(d, {tag:'button', text:'Continue'}).click();
  await flush();
  assert.match(d.text, /Checking the login/);
  // the stale 'again' in the code answer is ignored; it counts only after the tool took the new code
  await c.renewCall('logins.status', {name:'claude'});
  assert.doesNotMatch(d.text, /not taken/);
});

const CHECK = {name:'db-dev', label:'Databricks dev', kind:'login', state:'unreachable', approve:'new',
  runs:'databricks current-user me --profile dev', hash:'0123456789abcdef0123456789abcdef'};

test('a check file that waits for the person gets Approve, never Renew; a broken one or a shared copy gets none', () => {
  const {c} = context(() => ({}));
  const b = c.renewButton(CHECK);
  assert.equal(b.textContent, 'Approve');
  assert.equal(b.dataset.approve, 'db-dev');
  assert.equal(b.attrs['aria-label'], 'Approve the Databricks dev check');
  assert.match(b.className, /primary sm/);
  assert.equal(c.renewButton({...CHECK, approve:'broken', runs:undefined, hash:undefined}), null);
  assert.equal(c.renewButton({...CHECK, hash:'not-a-hash'}), null);  // nothing to send back: no button
  c.snapshot = true;
  assert.equal(c.renewButton(CHECK), null);
});

test('Approve shows what the check runs, then sends the CLI\'s own approve with the hash shown', async () => {
  const {c, calls, dialogs} = context(() => ({}));
  c.renewButton(CHECK).click();
  const d = dialogs[0];
  assert.equal(d.title, 'Approve the Databricks dev check?');
  assert.equal(d.className, 'dialog ui-bottom-close');
  assert.match(d.text, /This check is new in this workspace\./);
  assert.match(d.text, /orch runs this to see whether it works: databricks current-user me --profile dev/);
  assert.match(d.text, /If the check file changes, it waits for you again\./);
  const find = (n, t) => n.tag === t.tag && (!t.text || n.text === t.text) ? n : n.children.map(k => typeof k === 'object' && find(k, t)).find(Boolean);
  assert.equal(calls.length, 0);  // opening the window changes nothing
  find(d, {tag:'button', text:'Approve'}).click();
  await flush();
  assert.deepEqual(calls, [{op:'checks.approve', args:{name:'db-dev', hash:CHECK.hash}}]);
  assert.match(d.text, /Approved\. orch checks Databricks dev from now on\./);
  find(d, {tag:'button', text:'Done'}).click();
  assert.equal(d.open, false);
});

test('a check file that changed after the page showed it is not approved and the rows are read again', async () => {
  const {c, calls, dialogs} = context(b => b.op === 'checks.approve' ? 'db-dev changed since you looked at it; nothing approved.' : {},
    b => b.op === 'checks.approve' ? 400 : 200);
  c.renewButton({...CHECK, approve:'changed'}).click();
  const d = dialogs[0];
  assert.match(d.text, /This check changed since you last approved it\./);
  const find = (n, t) => n.tag === t.tag && (!t.text || n.text === t.text) ? n : n.children.map(k => typeof k === 'object' && find(k, t)).find(Boolean);
  find(d, {tag:'button', text:'Approve'}).click();
  await flush();
  assert.match(d.text, /The check changed after this page showed it\. Nothing was approved\. Open Approve again/);
  assert.deepEqual(calls.map(x => x.op), ['checks.approve', 'logins.check']);
  assert.ok(find(d, {tag:'button', text:'Close'}));
});
