const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', name), 'utf8');
const source = read('pages/newticket.js');

// Small DOM harness: use the production dialog lifecycle, including its close/render listener.
class Node {
  constructor(tag, cls = '', text = '') { this.tag = tag; this.className = cls; this.textContent = text; this.children = []; this.listeners = {}; this.dataset = {}; this.value = ''; this.isConnected = true; }
  append(...nodes) { for (const n of nodes) { n.parent?.children.splice(n.parent.children.indexOf(n), 1); n.parent = this; this.children.push(n); } }
  prepend(...nodes) { const old = [...this.children]; for (const n of old) n.parent = null; this.children = []; this.append(...nodes, ...old); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  get firstChild() { return this.children[0]; }
  setAttribute(k, v) { this[k] = v; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  async fire(k, extra = {}) { const e = {preventDefault() { this.prevented = true; }, ...extra}; for (const fn of this.listeners[k] || []) await fn(e); return e; }
  click() { return this.fire('click'); }
  setCustomValidity(s) { this.validity = s; }
  reportValidity() { return !walk(this).some(n => n.validity || (n.required && !n.value)); }
  focus() {}
  dispatchEvent(e) { return this.fire(e.type); }
  contains(n) { return walk(this).includes(n); }
  remove() { this.isConnected = false; this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}
const walk = n => [n, ...n.children.flatMap(walk)];
function setup() { return setupWith(null); }
// ORCH-1852: Start now is offered only when the workspace has a helper.
const HELPER = {agents:[{name:'claude', label:'Claude'}]};
const startNow = s => walk(s.d).find(n => n.textContent === 'Start now');
const saveBtn = s => walk(s.d).find(n => n.type === 'submit');
const text = n => walk(n).map(x => x.textContent).join('');
// Press Start now and wait until the submit it causes has finished.
async function pressStart(s) { const button = startNow(s), real = s.form.requestSubmit; s.form.requestSubmit = () => {}; await button.click(); s.form.requestSubmit = real; await s.form.fire('submit'); return button; }
const ONE_HELPER = HELPER;
function setupWith(settings, extra = {}) {
  const body = new Node('body'), calls = [], revoked = [], toasts = [], items = [];
  const c = {Blob, TextDecoder, Uint8Array, btoa, serial:0, locks:new Set(), mounts:new Map(), nodeKey:() => '', clean:x => x,
    el:(...args) => new Node(...args), document:{body, activeElement:null}, render:() => { c.renders++; }, renders:0,
    sizeText:n => n + ' B', URL:{createObjectURL:() => 'blob:test', revokeObjectURL:x => revoked.push(x)},
    FileReader:class { readAsDataURL() { this.result = 'data:image/png;base64,YQ=='; this.onload(); } },
    tickets:() => items, ticketOf:() => null, refresh:async () => {}, location:{hash:''}, href:id => '#ticket/' + id,
    act:async (op, args) => { calls.push({op, args}); if (op === 'ticket.new') items.push({id:'new', title:args.title}); return {ok:true, state:{attached:{failed:['bad.txt']}}}; },
    window:{DashHelpers:{scrubText:x => x}, orch:{open:d => { d.open = true; }, close:async d => { d.open = false; await d.fire('close'); }, toast:(...x) => toasts.push(x)}, ...extra}};
  c.button = (text, cls, fn) => { const b = c.el('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; };
  if (settings) c.state = {settings};
  vm.createContext(c);
  const app = read('app.js');
  vm.runInContext(app.slice(app.indexOf('function dialog('), app.indexOf("document.getElementById('new-ticket')")), c);
  vm.runInContext(source, c); c.ticketForm();
  const d = body.children[0], nodes = walk(d), input = nodes.find(n => n.name === 'text'), form = nodes.find(n => n.tag === 'form');
  const picker = nodes.find(n => n.type === 'file');
  const paste = text => input.fire('paste', {clipboardData:{getData:() => text}});
  const drop = files => form.fire('drop', {dataTransfer:{files}});
  const chips = () => walk(d).filter(n => n.className.includes('new-ticket-file-main'));
  return {c, body, d, input, form, picker, paste, drop, chips, calls, revoked, toasts};
}
test('file validation, first nonempty title, and base64 stripping', () => {
  const c = setup().c;
  for (const ext of ['txt','md','csv','tsv','json','log','yml','yaml','toml','ini','png','jpg','jpeg','gif','webp']) assert.ok(c.ticketFileType('X.' + ext.toUpperCase()));
  assert.equal(c.ticketFileError({name:'x.html',size:1}, []), 'x.html: only text files and pictures');
  assert.equal(c.ticketFileError({name:'x.md',size:25*1024*1024+1}, []), 'x.md is over 25 MB');
  assert.equal(c.ticketFileError({name:'x.md',size:20*1024*1024}, []), '');
  assert.equal(c.ticketFileError({name:'x.md',size:1}, Array(12).fill({size:1})), '');  // no file-count limit
  assert.equal(c.ticketFileError({name:'x.md',size:25*1024*1024}, [{size:80*1024*1024}]), 'Files are over 100 MB');
  assert.equal(c.ticketTextTitle('\n  hello\r\nworld', 3), 'he…');
  assert.equal(c.ticketTextTitle('let me add like a "Release" Tag to the properties of a ticket and then for e.g. on the ticket page group them', 80), 'let me add like a "Release" Tag to the properties of a ticket…');  // ORCH-62
  assert.equal(c.ticketTextTitle('  \n ', 80), '');
  assert.equal(c.ticketBase64('data:image/png;base64,YQ=='), 'YQ==');
});
test('long paste appends, previews safely, closes independently, and submits full text', async () => {
  const s = setup(), text = '<script>no</script>\n' + 'x'.repeat(210000);
  assert.equal((await s.paste(text)).prevented, true);
  await s.paste('y'.repeat(1501));
  assert.equal(s.input.value, ''); assert.equal(s.input.required, false);
  s.input.value = 'Extra sentence'; await s.input.fire('input');
  await s.chips()[0].click();
  const preview = s.body.children[1];
  assert.equal(walk(preview).find(n => n.tag === 'pre').textContent, text.slice(0, 200000));
  await walk(preview).find(n => n.textContent === 'Close').click();
  assert.equal(s.body.children.length, 1); assert.equal(s.d.open, true); assert.equal(s.c.renders, 1);
  assert.equal(s.input.value, 'Extra sentence'); assert.equal(s.chips().length, 1);
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.long_text, text + '\n\n' + 'y'.repeat(1501));
  assert.equal(s.calls[0].args.title, 'Extra sentence');
  assert.equal(s.calls[0].args.note, undefined);
  assert.equal(s.calls.length, 1, 'no helper: nothing is prepared or started');
  assert.ok(s.toasts.some(x => x[0] === 'The ticket was created. Not saved: bad.txt' && x[1] === 'error'));
});
test('typed long text becomes note.md and removal restores required validity', async () => {
  const s = setup(); await s.paste('x'.repeat(1501));
  await walk(s.d).find(n => n['aria-label'] === 'Remove pasted text').click();
  assert.equal(s.input.required, true); assert.equal(s.form.reportValidity(), false);
  s.input.value = '\n' + 'a'.repeat(1800); await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title.length, 80); assert.equal(s.calls[0].args.long_text, '\n' + 'a'.repeat(1800));
  assert.equal(s.calls[0].args.note, undefined);
});
test('file reads finish before submission; previews and URL cleanup work', async () => {
  const s = setup();
  await s.drop([{name:'readme.md',size:10,arrayBuffer:async () => new TextEncoder().encode('<b>raw</b>').buffer}, {name:'photo.png',size:1}]);
  // Drain the file-reading queue using a submit that is blocked after reads.
  walk(s.d).find(n => n.type === 'submit').disabled = true;
  await s.form.fire('submit');
  assert.equal(s.chips().length, 2);
  await s.chips()[1].click();
  const preview = s.body.children[1];
  assert.equal(walk(preview).find(n => n.tag === 'img').src, 'blob:test');
  await walk(preview).find(n => n.textContent === 'Close').click();
  assert.deepEqual(s.revoked, []);
  walk(s.d).find(n => n.type === 'submit').disabled = false;
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title, 'readme');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].args.files)), [{name:'readme.md',text:'<b>raw</b>'},{name:'photo.png',data:'YQ=='}]);
  assert.deepEqual(s.revoked, ['blob:test']);
});
test('short paste and text drops use browser defaults; rejected files stay inline', async () => {
  const s = setup(); assert.equal((await s.paste('short')).prevented, undefined);
  assert.equal((await s.drop([])).prevented, undefined);
  await s.drop([{name:'bad.exe',size:1}]); await s.form.fire('submit');
  assert.match(walk(s.d).find(n => n.className.includes('new-ticket-file-error')).textContent, /only text files and pictures/);
  assert.equal(s.calls.length, 0);
});
test('textarea title takes priority when typed long text follows a pasted note', async () => {
  const s = setup(); await s.paste('Original\n' + 'a'.repeat(1501));
  s.input.value = 'New title\n' + 'b'.repeat(1501); await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title, 'New title');
  assert.equal(s.calls[0].args.long_text, 'Original\n' + 'a'.repeat(1501) + '\n\nNew title\n' + 'b'.repeat(1501));
});
test('a text file that is not UTF-8 is sent as base64, unaltered; a body over 139 MB is refused plainly', async () => {
  const s = setup();
  await s.drop([{name:'latin.txt', size:3, arrayBuffer:async () => new Uint8Array([0x63, 0xe9, 0x66]).buffer}]);
  await s.form.fire('submit');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].args.files)), [{name:'latin.txt', data:btoa('c\xe9f')}]);
  const big = setup(); await big.paste('x'.repeat(1501));
  big.input.value = 'y'.repeat(145 * 1024 * 1024); await big.input.fire('input');
  await big.form.fire('submit');
  assert.equal(big.calls.length, 0);
});
test('the agent writes the title for long or multi-line text, a short one-liner is its own title', async () => {
  const a = setup(); await a.paste('x'.repeat(1501)); await a.form.fire('submit');
  assert.equal(a.calls[0].args.title_auto, true);
  const b = setup(); b.input.value = 'Fix the login page'; await b.input.fire('input'); await b.form.fire('submit');
  assert.equal(b.calls[0].args.title_auto, false);
  const c = setup(); c.input.value = 'Fix it\nand more'; await c.input.fire('input'); await c.form.fire('submit');
  assert.equal(c.calls[0].args.title_auto, false);  // the first line is the title the person typed
  assert.equal(c.calls[0].args.title, 'Fix it');
  const d = setup(); d.input.value = 'y'.repeat(120); await d.input.fire('input'); await d.form.fire('submit');
  assert.equal(d.calls[0].args.title_auto, true);  // a long first line is clipped: the agent may write a title
});
test('a typed title stays: with a 20 KB paste or files title_auto is false and the title is kept', async () => {
  const s = setup(); s.input.value = 'Fix the login page'; await s.input.fire('input'); await s.paste('p'.repeat(20000));
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title, 'Fix the login page');
  assert.equal(s.calls[0].args.title_auto, false);
  assert.equal(s.calls[0].args.long_text.length >= 20000, true);
  const u = setup(); await u.paste('p'.repeat(20000)); await u.form.fire('submit');  // nothing typed: the title comes from the paste
  assert.equal(u.calls[0].args.title_auto, true);
});

test('Show me the plan first is a plain box; Start now creates a plan-first ticket and starts it', async () => {
  const s = setupWith(HELPER);
  s.form.requestSubmit = () => s.form.fire('submit');
  s.input.value = 'Make a plan'; await s.input.fire('input');
  const box = walk(s.d).find(n => n.name === 'plan_first');
  assert.equal(box.type, 'checkbox');
  box.checked = true;
  await pressStart(s);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls[0].op, 'ticket.new');
  assert.equal(s.calls[0].args.plan_first, true);
  assert.equal(JSON.stringify(s.calls[1]), JSON.stringify({op:'run.start', args:{ticket:'new'}}));
  const saved = setupWith(HELPER);  // with a helper, Save ticket keeps the plan choice for Start
  saved.input.value = 'Make a plan'; await saved.input.fire('input');
  walk(saved.d).find(n => n.name === 'plan_first').checked = true;
  await saved.form.fire('submit');
  assert.equal(saved.calls[0].args.plan_first, undefined);
  const none = setup();  // no helper: the ticket remembers it for when it starts
  none.input.value = 'Make a plan'; await none.input.fire('input');
  walk(none.d).find(n => n.name === 'plan_first').checked = true;
  await none.form.fire('submit');
  assert.equal(none.calls[0].args.plan_first, true);
});

test('Human review needed is ticked by default; unticking it sends human_review false (ORCH-424)', async () => {
  const s = setup();
  s.input.value = 'Spring campaign'; await s.input.fire('input');
  const box = walk(s.d).find(n => n.name === 'human_review');
  assert.equal(box.type, 'checkbox');
  assert.equal(box.checked, true);
  await s.form.fire('submit');
  assert.equal(s.calls[0].op, 'ticket.new');
  assert.equal(s.calls[0].args.human_review, undefined);  // on is the default: nothing to send
  const u = setup();
  u.input.value = 'Spring campaign'; await u.input.fire('input');
  walk(u.d).find(n => n.name === 'human_review').checked = false;
  await u.form.fire('submit');
  assert.equal(u.calls[0].args.human_review, false);
});

test('with the Auto Reviewer on, Human review needed starts unticked; ticking it sends human_review true (ORCH-424)', async () => {
  const s = setupWith({auto_reviewer_on:true});
  s.input.value = 'Spring campaign'; await s.input.fire('input');
  const box = walk(s.d).find(n => n.name === 'human_review');
  assert.equal(box.checked, false);
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.human_review, undefined);  // the workspace default: nothing to send
  const u = setupWith({auto_reviewer_on:true});
  u.input.value = 'Spring campaign'; await u.input.fire('input');
  walk(u.d).find(n => n.name === 'human_review').checked = true;
  await u.form.fire('submit');
  assert.equal(u.calls[0].args.human_review, true);
});

test('long typed text moved to a chip on submit shrinks the text box back', async () => {
  const s = setup();
  s.input.style = {};
  Object.defineProperty(s.input, 'scrollHeight', {get() { return this.value ? 1000 : 0; }});
  s.input.value = 'y'.repeat(1600); await s.input.fire('input');
  assert.equal(s.input.style.height, '480px');
  await s.form.fire('submit');
  assert.equal(s.input.value, '');
  assert.equal(s.input.style.height, 'auto');
});

test('Save ticket is the one filled button; Start now sits beside it only with a helper; neither sends plan_first by default', async () => {
  const labels = d => walk(d).filter(n => n.tag === 'button' && /btn|outline|primary/.test(n.className)).map(n => n.textContent);
  assert.deepEqual(labels(setup().d).filter(x => /Save|Start/.test(x)), ['Save ticket'], 'no helper: no Start that could only fail');
  const h = setupWith(HELPER);
  assert.deepEqual(labels(h.d).filter(x => /Save|Start/.test(x)), ['Save ticket', 'Start now']);
  assert.match(saveBtn(h).className, /primary/); assert.doesNotMatch(startNow(h).className, /primary/);  // the costly one is never the filled default
  for (const label of ['Save ticket', 'Start now']) {
    const s = setupWith(HELPER);
    s.form.requestSubmit = () => s.form.fire('submit');
    s.input.value = 'Work'; await s.input.fire('input');
    if (label === 'Start now') await pressStart(s); else { await saveBtn(s).click(); await s.form.fire('submit'); }
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(s.calls[0].args.plan_first, undefined);
    assert.equal(s.calls.length, 2);
    // ORCH-738: Start now starts the helper; Save ticket only asks for the ticket to be prepared
    assert.equal(JSON.stringify(s.calls[1]), JSON.stringify({op:'run.start', args:label === 'Start now' ? {ticket:'new'} : {ticket:'new', prepare:true}}));
  }
});

test('attach is a link, drops land anywhere on the form, pasted text reads in pages', async () => {
  const s = setup();
  assert.ok(walk(s.d).some(n => n.textContent === '＋ Add files' && n.className.includes('new-ticket-attach')));
  assert.equal(s.input.rows, 3);
  assert.equal((await s.form.fire('drop', {dataTransfer:{files:[{name:'plan.md', size:3, arrayBuffer:async () => new TextEncoder().encode('abc').buffer}]}})).prevented, true);
  await s.paste('x'.repeat(9000));
  walk(s.d).find(n => n.type === 'submit').disabled = true; await s.form.fire('submit');
  const labels = s.chips().map(n => n.children.map(c => c.textContent).join('|'));
  assert.deepEqual(labels, ['MD|Pasted text (about 3 pages)', 'MD|plan.md|3 B']);  // ORCH-2162: each chip says its kind
  assert.equal(s.c.pastedLabel('x'.repeat(100)), 'Pasted text (about 1 page)');
});

test('helper choice: only the helpers this workspace has, by name only, distinct labels, default first', () => {
  const c = setup().c;
  const hs = c.ticketHelpers({agents:[{name:'claude', label:'Helper', found:true}, {name:'codex', label:'Helper', chosen:true, found:true, description:'Builds code'}, {name:'gone', found:false}, {name:'copilot', label:'Copilot', status:'not found'}, {name:'claude', label:'Helper'}]});
  assert.deepEqual([...hs.map(h => h.name)], ['codex', 'claude']);
  assert.equal(new Set(hs.map(h => h.label.toLowerCase())).size, 2);
  assert.equal(hs[0].description, undefined, 'owner, 25 Nov: no "good at" line');
  assert.equal(c.ticketHelpers(null).length, 0);
});
test('several helpers: a short list, each once, no "good at" line; a non-default choice is the owner and names the lines. One helper: its name. None: no box', async () => {
  const s = setupWith({agents:[{name:'claude', label:'Claude', chosen:true}, {name:'codex', label:'Codex', description:'Websites and code'}, {name:'copilot', label:'Copilot', found:false}]});
  const radios = walk(s.d).filter(n => n.name === 'helper');
  assert.deepEqual(radios.map(r => r.value), ['claude', 'codex'], 'a helper not found here is not offered');
  assert.equal(radios[0].checked, true);
  const box = walk(s.d).find(n => n.className.includes('new-ticket-helper'));
  assert.doesNotMatch(text(box), /Websites and code/);
  assert.match(text(box), /^HelperClaudeDefaultCodex$/);
  const lines = () => walk(s.d).filter(n => n.className.includes('new-ticket-what')).map(n => n.textContent);
  assert.deepEqual(lines(), ['Goes to Tickets. Claude may prepare a short plan; no work starts.', 'Claude begins at once. This may cost money.']);
  radios[0].checked = false; radios[1].checked = true; await radios[1].fire('change');
  assert.deepEqual(lines(), ['Goes to Tickets. Codex may prepare a short plan; no work starts.', 'Codex begins at once. This may cost money.']);
  assert.match(text(walk(s.d).find(n => n.className.includes('new-ticket-plan'))), /Codex waits for your OK before work begins\./);
  s.input.value = 'Work'; await s.input.fire('input'); await s.form.fire('submit');
  assert.equal(s.calls[0].args.owner, 'agent:codex');
  const one = setupWith({agents:[{name:'claude', label:'Claude'}]});
  assert.equal(walk(one.d).some(n => n.name === 'helper'), false);
  assert.equal(walk(one.d).find(n => n.className === 'new-ticket-helper-fixed').textContent, 'Claude');
  const same = setupWith({agents:[{name:'helper', label:'Helper'}]});
  assert.equal(walk(same.d).some(n => n.className === 'new-ticket-helper-fixed' || n.className.includes('new-ticket-helper')), false, 'no dead Helper / Helper row');
  assert.match(text(walk(same.d).find(n => n.className.includes('new-ticket-what'))), /^Goes to Tickets\. Your helper may prepare/);
  const none = setupWith({agents:[]});
  assert.equal(walk(none.d).some(n => n.name === 'helper' || n.className === 'new-ticket-helper-fixed'), false);
  assert.match(text(walk(none.d).find(n => n.className.includes('new-ticket-what'))), /No helper is set up yet, so nothing starts/);
  assert.equal(walk(none.d).find(n => n.textContent === 'Set up a helper').href, '#settings/helper');
});
test('due date uses the shared date picker; the chosen day is sent with the ticket', async () => {
  const seen = [], s = setupWith(ONE_HELPER, {UI:{date:(value, toggle) => seen.push([value, toggle])}});
  const toggle = walk(s.d).find(n => n.className.includes('new-ticket-date-toggle'));
  assert.equal(toggle.textContent, '▦ No date');
  assert.deepEqual(seen.map(([value, t]) => [value.type, value.name, t === toggle]), [['hidden', 'due', true]]);
  seen[0][0].value = '2026-11-20';
  s.input.value = 'Work'; await s.input.fire('input'); await s.form.fire('submit');
  assert.equal(s.calls[0].args.due, '2026-11-20');
  assert.ok(setup().d, 'without the shared picker the window still opens');
});
test('window closes through the shared overlay; an empty submit shows the plain message', async () => {
  const s = setup();
  await s.form.fire('submit');
  assert.equal(walk(s.d).find(n => n.role === 'alert' && n.className === 'bad').textContent, 'Describe what needs doing before you continue.');
  assert.equal(s.calls.length, 0);
  assert.ok(!walk(s.d).some(n => /^Close/.test(n['aria-label'] || '')), 'the Close button comes from the shared overlay, not from the page');
  assert.match(s.d.className, /ui-bottom-close/, 'the dialog has its own Cancel at the bottom, so the overlay adds no top Close');
  await s.c.window.orch.close(s.d); assert.equal(s.d.open, false);
});

// Owner feedback 14 Nov (sweep d-new-ticket): the box starts small and grows; Start opens the new ticket, Save stays on the list.
test('the text box starts at 3 rows; Start now and Save ticket both open the new ticket', async () => {
  assert.equal(setup().input.rows, 3);
  for (const label of ['Start now', 'Save ticket']) {
    const s = setupWith(HELPER);
    s.form.requestSubmit = () => s.form.fire('submit');
    s.input.value = 'Work'; await s.input.fire('input');
    if (label === 'Start now') await pressStart(s); else { await saveBtn(s).click(); await s.form.fire('submit'); }
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(s.c.location.hash, '#ticket/new', label);
    if (label !== 'Start now') assert.ok(s.toasts.some(x => /^Saved/.test(x[0])), 'Save ticket says it saved');
  }
});

test('a pasted screenshot becomes a chip and goes into ticket.new; short text paste is not intercepted', async () => {
  const shot = {name:'Screenshot 18-30.png', size:3};
  const s = setupWith(ONE_HELPER, {UI:{pastedFiles:e => Array.from(e.clipboardData.files || [])}});
  const e = await s.input.fire('paste', {clipboardData:{files:[shot], getData:() => ''}});
  assert.equal(e.prevented, true);
  walk(s.d).find(n => n.type === 'submit').disabled = true; await s.form.fire('submit');  // drain the read queue
  assert.equal(s.chips().length, 1);
  walk(s.d).find(n => n.type === 'submit').disabled = false; await s.form.fire('submit');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].args.files)), [{name:'Screenshot 18-30.png', data:'YQ=='}]);
  const t = setupWith(ONE_HELPER, {UI:{pastedFiles:e => Array.from(e.clipboardData.files || [])}});
  assert.equal((await t.input.fire('paste', {clipboardData:{files:[], getData:() => 'short'}})).prevented, undefined);
});

test('UI.pastedFiles gives pasted image.png a readable unique name and leaves other files alone', () => {
  const root = path.join(__dirname, '../../../workspace/src/orch_ui/static/components.js');
  class F { constructor(parts, name, o = {}) { this.name = name; this.type = o.type; } }
  const w = {}, c = {window:w, document:{addEventListener() {}, querySelector() {}, querySelectorAll() { return []; }}, File:F, navigator:{}, setTimeout, clearTimeout};
  vm.createContext(c); vm.runInContext(fs.readFileSync(root, 'utf8'), c);
  const ev = files => ({clipboardData:{files}});
  const a = new F([], 'image.png', {type:'image/png'}), b = new F([], 'image.png', {type:'image/png'}), doc = new F([], 'notes.txt');
  const out = w.UI.pastedFiles(ev([a, b, doc]));
  assert.match(out[0].name, /^Screenshot \d\d-\d\d\.png$/);
  assert.match(out[1].name, /^Screenshot \d\d-\d\d \(2\)\.png$/);
  assert.equal(out[2], doc);
  assert.equal(w.UI.pastedFiles({clipboardData:{getData: () => 'x'}}).length, 0);
});
test('b4: Save ticket says Saving… at once, then the ticket opens', async () => {
  const s = setup();
  s.form.requestSubmit = () => s.form.fire('submit');
  let release; const hold = new Promise(r => { release = r; });
  const base = s.c.act; s.c.act = async (op, args) => { if (op === 'ticket.new') await hold; return base(op, args); };
  s.input.value = 'Work'; await s.input.fire('input');
  const node = saveBtn(s);
  await node.click(); const pending = s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(node.textContent, 'Saving…');
  assert.equal(node.disabled, true);
  release(); await pending; await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.c.location.hash, '#ticket/new');
});
test('ORCH-8: the new ticket opens by the id in the reply, even when orch changed its title', async () => {
  const s = setup();
  // Cut to 80 characters right after a space, with a file: the dialog used to look for "… this " and find nothing.
  s.c.act = async (op, args) => { s.calls.push({op, args}); if (op === 'ticket.new') s.c.tickets().push({id:'t_new123', title:args.title.trim() + ' (renamed)'}); return {ok:true, state:{created:{id:'t_new123'}}}; };
  await s.drop([{name:'Screenshot 08-19.png',size:1}]);
  s.input.value = 'add a option that when a user does first orch init it adds a default task, this default task'; await s.input.fire('input');
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls[0].args.title, 'add a option that when a user does first orch init it adds a default task, this…');  // ORCH-62: a cut ends with …
  assert.equal(s.c.location.hash, '#ticket/t_new123');
  assert.ok(!walk(s.d).some(n => /could not be found/.test(n.textContent)));
});
test('ORCH-8: an older reply without the id still finds the ticket by its title (no trailing space)', async () => {
  const s = setup();
  s.c.act = async (op, args) => { s.calls.push({op, args}); if (op === 'ticket.new') s.c.tickets().push({id:'t_old1', title:args.title}); return {ok:true, state:{}}; };
  await s.drop([{name:'photo.png',size:1}]);
  s.input.value = 'x'.repeat(79) + ' and more words after the cut'; await s.input.fire('input');
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls[0].args.title, 'x'.repeat(79) + '…');  // ORCH-62: a cut ends with …
  assert.equal(s.c.location.hash, '#ticket/t_old1');
});

// ORCH-14: several tickets at once. The box is the main ticket; each step becomes a ticket under it with its own files.
const stepBoxes = s => walk(s.d).filter(n => n.className.split(' ').includes('new-ticket-step'));
const addStepButton = s => walk(s.d).find(n => n.className.includes('new-ticket-add-step'));
test('ORCH-14: Make it an epic adds numbered ticket boxes; Remove takes one out and renumbers', async () => {
  const s = setup();
  const help = walk(s.d).find(n => /Each part becomes its own ticket inside this one/.test(n.textContent));
  assert.equal(stepBoxes(s).length, 0); assert.equal(help.hidden, true);
  assert.equal(addStepButton(s).textContent, '＋ Split into parts');
  await addStepButton(s).click(); await addStepButton(s).click(); await addStepButton(s).click();
  assert.deepEqual(stepBoxes(s).map(b => walk(b).find(n => n.className.includes('new-ticket-step-name')).textContent), ['Part 1', 'Part 2', 'Part 3']);  // ORCH-2162: one word, part
  assert.equal(help.hidden, false); assert.equal(addStepButton(s).textContent, '＋ Add another part');
  await walk(stepBoxes(s)[0]).find(n => n['aria-label'] === 'Remove part 1').click();
  assert.deepEqual(stepBoxes(s).map(b => walk(b).find(n => n.tag === 'textarea')['aria-label']), ['Part 1: what needs doing?', 'Part 2: what needs doing?']);
  // the first press sits beside Add files; with parts, "Add another part" follows the last part
  assert.ok(addStepButton(s).parent.className.includes('new-ticket-step-foot'));
  await walk(stepBoxes(s)[0]).find(n => n['aria-label'] === 'Remove part 1').click(); await walk(stepBoxes(s)[0]).find(n => n['aria-label'] === 'Remove part 1').click();
  assert.ok(addStepButton(s).parent.className.includes('new-ticket-file-bar'));
});
test('ORCH-14: Start now makes the epic, then one ticket inside it per box with its own files; only the epic starts', async () => {
  const s = setupWith(HELPER, {UI:{pastedFiles:e => Array.from(e.clipboardData.files || [])}});
  s.form.requestSubmit = () => s.form.fire('submit');
  s.c.act = async (op, args) => { s.calls.push({op, args}); if (op === 'ticket.new') { const id = 't_' + s.calls.length; s.c.tickets().push({id, title:args.title}); return {ok:true, state:{created:{id}}}; } return {ok:true}; };
  s.input.value = 'Dashboard fixes'; await s.input.fire('input');
  await addStepButton(s).click(); await addStepButton(s).click(); await addStepButton(s).click();
  const [one, two, empty] = stepBoxes(s);
  walk(one).find(n => n.tag === 'textarea').value = 'Fix the header\nIt overlaps the menu';
  await one.fire('drop', {dataTransfer:{files:[{name:'header.png', size:1}]}, stopPropagation() { this.stopped = true; }});
  const twoText = walk(two).find(n => n.tag === 'textarea'); twoText.value = 'Larger buttons';
  assert.equal((await twoText.fire('paste', {clipboardData:{files:[{name:'Screenshot 09-13.png', size:1}], getData:() => ''}})).prevented, true);
  assert.equal(walk(empty).find(n => n.tag === 'textarea').value, '');
  await walk(empty).find(n => n.textContent === 'Remove').click();  // ORCH-156: an empty box is refused, not skipped
  await pressStart(s);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.calls.map(c => c.op), ['ticket.new', 'ticket.new', 'ticket.new', 'run.start']);
  assert.equal(s.calls[0].args.title, 'Dashboard fixes'); assert.equal(s.calls[0].args.epic, true); assert.equal(s.calls[0].args.parent, undefined); assert.equal(s.calls[0].args.files, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[1].args)), {title:'Fix the header', title_auto:false, note:'Fix the header\nIt overlaps the menu', files:[{name:'header.png', data:'YQ=='}], parent:'t_1'});
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[2].args)), {title:'Larger buttons', title_auto:false, files:[{name:'Screenshot 09-13.png', data:'YQ=='}], parent:'t_1'});
  assert.equal(s.calls[3].args.ticket, 't_1');
  assert.equal(s.c.location.hash, '#ticket/t_1');
  assert.ok(s.toasts.some(x => x[0] === 'Ticket and its parts created'));
});
test('ORCH-14: a long ticket text is kept as its note.md; a ticket over 139 MB is refused before anything is made', async () => {
  const s = setup();
  s.input.value = 'Main'; await s.input.fire('input');
  await addStepButton(s).click();
  walk(stepBoxes(s)[0]).find(n => n.tag === 'textarea').value = 'z'.repeat(2000);
  await s.form.fire('submit');
  assert.equal(s.calls[1].args.long_text, 'z'.repeat(2000)); assert.equal(s.calls[1].args.note, undefined); assert.equal(s.calls[1].args.title_auto, true);
  const big = setup();
  big.input.value = 'Main'; await big.input.fire('input');
  await addStepButton(big).click(); await addStepButton(big).click();
  walk(stepBoxes(big)[0]).find(n => n.tag === 'textarea').value = 'small';
  walk(stepBoxes(big)[1]).find(n => n.tag === 'textarea').value = 'y'.repeat(145 * 1024 * 1024);
  await big.form.fire('submit');
  assert.equal(big.calls.length, 0);
  assert.match(walk(big.d).find(n => n.role === 'alert' && n.className === 'bad').textContent, /^Part 2 is too big/);
});
test('ORCH-14: a ticket that fails keeps the window open; pressing again sends only that one, not the epic twice', async () => {
  const s = setupWith(HELPER);
  s.form.requestSubmit = () => s.form.fire('submit');
  let failOnce = true;
  s.c.act = async (op, args) => {
    s.calls.push({op, args});
    if (op === 'ticket.new' && args.title === 'Second' && failOnce) { failOnce = false; return {ok:false, text:'busy'}; }
    if (op === 'ticket.new') { const id = 't_' + s.calls.length; s.c.tickets().push({id, title:args.title}); return {ok:true, state:{created:{id}}}; }
    return {ok:true};
  };
  s.input.value = 'Main'; await s.input.fire('input');
  await addStepButton(s).click(); await addStepButton(s).click();
  walk(stepBoxes(s)[0]).find(n => n.tag === 'textarea').value = 'First';
  walk(stepBoxes(s)[1]).find(n => n.tag === 'textarea').value = 'Second';
  const start = await pressStart(s);
  assert.equal(s.d.open, true);
  assert.equal(start.hidden, true, 'the epic exists: only the retry is left');
  assert.match(walk(s.d).find(n => n.role === 'alert' && n.className === 'bad').textContent, /not all of its parts\. Part 1: busy/);
  assert.equal(stepBoxes(s).length, 1, 'the step that was made left the list');
  assert.equal(walk(s.d).find(n => n.type === 'submit').textContent, 'Send the rest');
  await saveBtn(s).click(); await s.form.fire('submit');  // the retry keeps the first choice: Start now
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.calls.map(c => c.op + ':' + (c.args.title || c.args.ticket)), ['ticket.new:Main', 'ticket.new:First', 'ticket.new:Second', 'ticket.new:Second', 'run.start:t_1']);
  assert.equal(s.calls[3].args.parent, 't_1');
  assert.equal(s.d.open, false);
});
test('ORCH-156: an empty ticket box is refused with a plain message; nothing is made until it is filled or removed', async () => {
  const s = setup();
  s.input.value = 'Just one'; await s.input.fire('input');
  await addStepButton(s).click();
  await s.form.fire('submit');
  assert.deepEqual(s.calls, []);
  const error = walk(s.d).find(n => n.className === 'bad' && n.role === 'alert');
  assert.equal(error.textContent, 'Part 1 is empty. Write what needs doing in it, or remove it.');
  assert.equal(s.d.open, true);
  await walk(s.d).find(n => n.textContent === 'Remove').click();  // removed: a plain ticket, as before
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.epic, undefined);
  assert.deepEqual(s.calls.map(c => c.op), ['ticket.new']);
});
test('ORCH-156: the second of two boxes empty names Ticket 2; a filled one alone still makes the epic', async () => {
  const s = setup();
  s.input.value = 'Epic'; await s.input.fire('input');
  await addStepButton(s).click(); await addStepButton(s).click();
  const boxes = walk(s.d).filter(n => n.name === 'step');
  boxes[0].value = 'First';
  await s.form.fire('submit');
  assert.deepEqual(s.calls, []);
  assert.match(walk(s.d).find(n => n.className === 'bad').textContent, /^Part 2 is empty/);
  boxes[1].value = 'Second';
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.epic, true);
  assert.deepEqual(s.calls.filter(c => c.op === 'ticket.new').length, 3);
});
test('ORCH-156: parentChoices keeps the current parent even when it is closed', () => {
  const helpers = require('../src/orch_dashboard/web/helpers.js');
  const all = [{id:'t_a', status:'done'}, {id:'t_b', status:'done'}, {id:'t_me', parent:'t_a', status:'open'}];
  assert.deepEqual(helpers.parentChoices(all, all[2]).map(x => x.id), ['t_a']);
});

test('ORCH-185: a first line over 200 characters keeps every word; a one-sentence wish stays in the note', () => {
  const c = setup().c;
  const long = 'Please make the report page faster because the people in sales wait too long for it to open every morning ' + 'and again '.repeat(20) + 'THE-END';
  const a = c.ticketFromText(long, long, '', []);
  assert.ok(a.title.length <= 80 && a.title.endsWith('…') && a.title_auto === true);
  assert.equal(a.note, long);  // nothing dropped
  const wish = c.ticketFromText('Add a dark mode to the settings page for night work', 'Add a dark mode to the settings page for night work', '', []);
  assert.equal(wish.note, 'Add a dark mode to the settings page for night work');
  assert.equal(c.ticketFromText('Fix login', 'Fix login', '', []).note, undefined);  // a short label is only the title
});
test('ORCH-185: Cancel, Esc or Back keep the typed text; the next New ticket brings it back; a sent ticket clears it', async () => {
  const s = setup(), {c} = s;
  s.input.value = 'Draft that must not be lost'; await s.input.fire('input');
  await c.window.orch.close(s.d);  // Cancel, Esc, backdrop and Back all end here
  c.ticketForm();
  const d2 = c.document.body.children.at(-1), input2 = walk(d2).find(n => n.name === 'text');
  assert.equal(input2.value, 'Draft that must not be lost');
  assert.ok(walk(d2).some(n => n.className.includes('new-ticket-draft')));
  walk(d2).find(n => n.textContent === 'Discard').click();
  assert.equal(input2.value, '');
  await c.window.orch.close(d2);  // empty: nothing kept
  c.ticketForm();
  assert.equal(walk(c.document.body.children.at(-1)).find(n => n.name === 'text').value, '');
});
test('ORCH-185: an added picture shows a thumbnail in its chip; a text file does not', () => {
  const c = setup().c;
  const img = walk(c.ticketFileChip({name:'hero.png', type:'image', size:99, url:'blob:x'}, () => {}));
  assert.ok(img.some(n => n.tag === 'img' && n.className === 'thumbnail' && n.src === 'blob:x'));
  assert.ok(!walk(c.ticketFileChip({name:'a.txt', type:'text', size:1, text:'x'}, () => {})).some(n => n.tag === 'img'));
});
async function epicSetup(reply) {
  const s = setupWith(ONE_HELPER, {UI:{pastedFiles:e => Array.from(e.clipboardData.files || [])}});
  s.c.act = async (op, args) => { s.calls.push({op, args}); if (op === 'ticket.new') { s.c.tickets().push({id:'t_epic', title:args.title}); return {ok:true, state:{created:{id:'t_epic'}, ...reply(args)}}; } return {ok:true}; };
  s.input.value = 'Dashboard fixes'; await s.input.fire('input');
  await addStepButton(s).click(); await addStepButton(s).click();
  const [one, two] = stepBoxes(s);
  walk(one).find(n => n.tag === 'textarea').value = 'Fix the header';
  walk(two).find(n => n.tag === 'textarea').value = 'Larger buttons';
  return s;
}
test('ORCH-185: an epic and its tickets go in ONE request, none of them naming a parent', async () => {
  const s = await epicSetup(args => ({steps:{made:args.steps.map((_, index) => ({index})), failed:[]}}));
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.calls.map(c => c.op), ['ticket.new'], 'Save ticket: an epic is neither prepared nor started');
  assert.equal(s.calls[0].args.epic, true);
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].args.steps.map(x => [x.title, 'parent' in x]))), [['Fix the header', false], ['Larger buttons', false]]);
  assert.ok(s.toasts.some(x => /^Saved\. The ticket and its parts are open/.test(x[0])));
});
test('ORCH-185: when one ticket of the epic is not made, the window says which and pressing again sends only that one', async () => {
  const s = await epicSetup(args => ({steps:{made:[{index:0}], failed:[{index:1, message:'Too long'}]}}));
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stepBoxes(s).length, 1, 'the ticket that was made left the list');
  const err = walk(s.d).find(n => n.className === 'bad');
  assert.match(err.textContent, /not all of its parts\. Part 2: Too long/);
  s.calls.length = 0;
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.calls.map(c => c.op).slice(0, 1), ['ticket.new']);
  assert.equal(s.calls[0].args.parent, 't_epic');
  assert.equal(s.calls[0].args.title, 'Larger buttons');
});

// ORCH-1037: New ticket is its own page (#new). The form is built into the page's host, and Start shows the starting
// steps (UI.launch) before the address moves to the new ticket.
function pageSetup({fail = false, helper = true, prepare, settings} = {}) {
  const host = new Node('div'), calls = [], toasts = [], items = [], launches = [];
  const launch = o => { const l = {o, el:new Node('div', 'launch'), steps:[], finished:'', failed:false}; l.step = i => l.steps.push(i); l.warn = (i, t) => { l.warned = [i, t]; }; l.finish = t => { l.finished = t; }; l.fail = () => { l.failed = true; }; launches.push(l); return l; };
  const c = {Blob, TextDecoder, Uint8Array, btoa, setTimeout, Event, serial:0, locks:new Set(), mounts:new Map(), nodeKey:() => '', clean:x => x,
    el:(...args) => new Node(...args), document:{body:new Node('body'), activeElement:null, querySelector:() => null}, render:() => {},
    sizeText:n => n + ' B', URL:{createObjectURL:() => 'blob:test', revokeObjectURL:() => {}},
    tickets:() => items, ticketOf:() => null, refresh:async () => {}, location:{hash:'#new'}, href:id => '#ticket/' + id,
    act:async (op, args) => { calls.push({op, args}); if (op === 'ticket.new') { if (fail) return {ok:false, status:500, text:'Disk full'}; items.push({id:'new', title:args.title}); return {ok:true, state:{created:{id:'new'}}}; } return {ok:true}; },
    window:{DashHelpers:{scrubText:x => x}, matchMedia:() => ({matches:true}), UI:{launch}, orch:{toast:(...x) => toasts.push(x)}}};
  c.button = (text, cls, fn) => { const b = c.el('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; };
  c.h = (tag, props, ...kids) => { const n = new Node(tag, props?.className || ''); Object.assign(n.dataset, props || {}); n.append(...kids.filter(Boolean)); return n; };
  const settings_ = settings !== undefined ? settings : helper ? {...HELPER, ...(prepare === undefined ? {} : {prepare_on_save:prepare})} : null;
  if (settings_) c.state = {settings:settings_};
  vm.createContext(c);
  vm.runInContext(source, c);
  const mounted = c.ticketForm(null, {host});
  const d = host.children[0], nodes = walk(d), input = nodes.find(n => n.name === 'text'), form = nodes.find(n => n.tag === 'form');
  form.requestSubmit = () => form.fire('submit');
  return {c, host, d, input, form, mounted, calls, toasts, launches};
}
test('ORCH-1037: New ticket is built on its own page, not in a window', () => {
  const s = pageSetup();
  assert.equal(s.d.tag, 'section'); assert.match(s.d.className, /new-ticket-on-page/);
  assert.equal(walk(s.d).find(n => n.tag === 'h1').textContent, 'New ticket');
  assert.equal(s.c.document.body.children.length, 0);  // nothing opened over the page
  assert.equal(typeof s.mounted.destroy, 'function');
});
test('ORCH-1037: Start now shows the starting steps, starts the helper, then opens the new ticket', async () => {
  const s = pageSetup();
  s.input.value = 'Plan the autumn newsletter'; await s.input.fire('input');
  await pressStart(s);
  assert.deepEqual(s.calls.map(x => x.op), ['ticket.new', 'run.start']);
  const l = s.launches[0];
  assert.deepEqual([...l.o.steps], ['Creating the ticket', 'Starting your helper', 'Opening it']);
  assert.equal(l.o.sub, 'Plan the autumn newsletter');
  assert.deepEqual([...l.steps], [1, 2]); assert.equal(l.finished, 'Started');
  assert.equal(s.form.hidden, true);
  assert.equal(s.c.location.hash, '#ticket/new');
  assert.deepEqual(s.toasts, []);  // the animation says it; no extra toasts
});
test('ORCH-1037: Save ticket skips the helper step and only asks for it to be prepared', async () => {
  const s = pageSetup();
  s.input.value = 'Later'; await s.input.fire('input');
  await saveBtn(s).click(); await s.form.fire('submit');
  assert.deepEqual(s.calls.map(x => x.op + (x.args.prepare ? ':prepare' : '')), ['ticket.new', 'run.start:prepare']);
  assert.deepEqual([...s.launches[0].o.steps], ['Creating the ticket', 'Opening it']);
  assert.equal(s.launches[0].finished, 'Saved');
  assert.equal(s.c.location.hash, '#ticket/new');
});
test('ORCH-1037: a refused ticket brings the form back with the reason, the text kept', async () => {
  const s = pageSetup({fail:true});
  s.input.value = 'Plan it'; await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.launches[0].failed, true);
  assert.equal(s.form.hidden, false);
  assert.equal(s.input.value, 'Plan it');
  assert.ok(walk(s.d).some(n => n.textContent === 'Disk full'));
  assert.equal(s.c.location.hash, '#new');
});
test('ORCH-1037: Cancel goes back to the page it came from; leaving keeps the unsent text', async () => {
  const s = pageSetup();
  s.c.location.hash = '#tickets'; s.c.openNewTicket();
  assert.equal(s.c.location.hash, '#new');
  s.input.value = 'Half typed';
  await walk(s.d).find(n => n.textContent === 'Cancel').click();
  assert.equal(s.c.location.hash, '#tickets');
  await s.mounted.destroy();
  assert.equal(vm.runInContext('ticketDraft', s.c).text, 'Half typed');
});
test('ORCH-1037: a helper that does not start ends on "Saved" with the reason, still on the new ticket', async () => {
  const s = pageSetup();
  const act = s.c.act; s.c.act = async (op, args) => op === 'run.start' ? (s.calls.push({op}), {ok:false, text:'No helper'}) : act(op, args);
  s.input.value = 'Plan it'; await s.input.fire('input');
  await pressStart(s);
  assert.equal(s.launches[0].finished, 'Saved');
  assert.equal(s.launches[0].warned.join('|'), '1|Helper not started. Your ticket is saved.');
  assert.ok(s.toasts.some(x => /did not start: No helper/.test(x[0]) && x[1] === 'error'));
  assert.equal(s.c.location.hash, '#ticket/new');
});
test('ORCH-1037: a form left while saving never moves the person later', async () => {
  const s = pageSetup();
  let release; const act = s.c.act;
  s.c.act = async (op, args) => { if (op === 'ticket.new') await new Promise(r => { release = r; }); return act(op, args); };
  s.input.value = 'Plan it'; await s.input.fire('input');
  const sent = s.form.fire('submit');
  await new Promise(r => setTimeout(r, 0));
  await s.mounted.destroy();  // the person left; then came back to #new (a fresh form)
  release(); await sent;
  assert.equal(s.c.location.hash, '#new');
  assert.ok(s.toasts.some(x => x[0] === 'Ticket created'));
});

// ORCH-1842 / ORCH-1852 / ORCH-2162 (option A): capture first. The request, its files and parts; then Save ticket and
// Start now side by side, one line under each; the helper and the optional settings in their own boxes.
const requestRow = s => walk(s.d).find(n => n.className === 'new-ticket-buttons');
const buttonsOf = n => walk(n).filter(b => b.tag === 'button' && /btn|outline|primary|ghost/.test(b.className)).map(b => b.textContent);
const whatOf = s => walk(s.d).find(n => n.className.includes('new-ticket-what'));
test('ORCH-1852: with no helper, one sentence and Save ticket make exactly one ticket; nothing optional comes first', async () => {
  const s = pageSetup({helper:false});
  const kinds = s.form.children.map(n => n.className.split(' ').find(c => /^new-ticket-(main|helper|go|more)$/.test(c)) || n.className);
  assert.deepEqual(kinds.slice(0, 3), ['new-ticket-main', 'new-ticket-go', 'new-ticket-more'], 'request, its buttons, then the options; no helper box');
  assert.match(s.form.className, /no-helper/, 'the options take the whole right column');
  const [main, go, more] = s.form.children, row = requestRow(s);
  assert.ok(walk(main).includes(s.input), 'the request comes first');
  assert.ok(walk(main).some(n => n.className.includes('new-ticket-add-step')) && walk(main).some(n => n.type === 'file'), 'files and parts sit right under the request');
  assert.deepEqual(buttonsOf(row), ['Save ticket', 'Cancel']);
  assert.match(saveBtn(s).className, /primary/);
  assert.ok(walk(go).includes(whatOf(s)), 'what Save does sits under its button');
  for (const name of ['plan_first', 'human_review', 'done_when', 'due']) assert.ok(walk(more).some(n => n.name === name), name + ' is with the options');
  assert.equal(walk(more).find(n => n.tag === 'h2').textContent, 'Optional');
  assert.match(text(whatOf(s)), /^Goes to Tickets\. No helper is set up yet, so nothing starts\./);
  assert.equal(startNow(s), undefined);
  s.input.value = 'Plan the spring campaign launch'; await s.input.fire('input');
  await saveBtn(s).click(); await s.form.fire('submit');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls)), [{op:'ticket.new', args:{title:'Plan the spring campaign launch', title_auto:false}}]);
  assert.equal(s.launches[0].finished, 'Saved');
  assert.equal(s.c.location.hash, '#ticket/new');
});
test('ORCH-1852: no helper: Cmd+Enter saves one ticket and asks for no run', async () => {
  const s = pageSetup({helper:false});
  s.input.value = 'Order the cake'; await s.input.fire('input');
  s.form.requestSubmit = () => s.form.fire('submit');
  await s.form.fire('keydown', {key:'Enter', metaKey:true});
  await new Promise(done => setTimeout(done, 20));
  assert.deepEqual(s.calls.map(x => x.op), ['ticket.new']);  // saved, never prepared or started
  assert.deepEqual([...s.launches[0].o.steps], ['Creating the ticket', 'Opening it']);
});
test('ORCH-1852: with a helper, Start now stays explicit with its cost said; Save ticket stays the default', async () => {
  const s = pageSetup({prepare:true});
  const [saveCell, startCell] = requestRow(s).children;
  assert.deepEqual([saveCell, startCell].map(cell => cell.children.map(n => n.textContent)), [
    ['Save ticket', 'Goes to Tickets. Claude may prepare a short plan; no work starts.'],
    ['Start now', 'Claude begins at once. This may cost money.', '']], 'each button with its own line right under it');
  assert.ok(walk(startCell).some(n => n.name === 'plan_first'), 'Show me the plan first sits under Start now');
  assert.deepEqual(buttonsOf(requestRow(s)), ['Save ticket', 'Start now', 'Cancel'], 'side by side: the filled default first, the costly choice outlined beside it, Cancel last');
  assert.doesNotMatch(startNow(s).className, /primary/);
  assert.equal(saveBtn(s).type, 'submit');  // Enter with Cmd or Ctrl saves; it never starts the helper
  s.input.value = 'Plan it'; await s.input.fire('input');
  let asked = 0; s.form.requestSubmit = () => { asked++; };
  await s.form.fire('keydown', {key:'Enter', metaKey:true});
  assert.equal(asked, 1);
  await s.form.fire('submit');  // what the browser does next: a submit with no Start now press
  assert.deepEqual(s.calls.map(x => x.op + (x.args.prepare ? ':prepare' : '')), ['ticket.new', 'run.start:prepare']);
  const off = pageSetup({prepare:false});
  assert.match(text(whatOf(off)), /^Goes to Tickets as you wrote it\. Nothing starts\./);
});
test('ORCH-1852: the text box has the focus on the page; restored text is saved as one ticket', async () => {
  const focused = [];
  const s = pageSetup();
  s.input.value = 'Draft for the newsletter'; await s.input.fire('input');
  await s.mounted.destroy();
  const host = new Node('div');
  const origFocus = Node.prototype.focus; Node.prototype.focus = function () { focused.push(this); };
  try { s.c.ticketForm(null, {host}); } finally { Node.prototype.focus = origFocus; }
  const d = host.children[0], input = walk(d).find(n => n.name === 'text'), form = walk(d).find(n => n.tag === 'form');
  assert.equal(focused.at(-1), input);
  assert.equal(input.value, 'Draft for the newsletter');
  assert.deepEqual(buttonsOf(walk(d).find(n => n.className === 'new-ticket-buttons')), ['Save ticket', 'Start now', 'Cancel']);
  s.calls.length = 0;
  await form.fire('submit');
  assert.deepEqual(s.calls.filter(x => x.op === 'ticket.new').map(x => x.args.title), ['Draft for the newsletter']);
});
test('ORCH-1852: a refused Save keeps the text; pressing Save again makes one ticket, not two', async () => {
  const s = pageSetup({helper:false});
  let refuse = true; const act = s.c.act;
  s.c.act = async (op, args) => { if (op === 'ticket.new' && refuse) { refuse = false; s.calls.push({op, args}); return {ok:false, status:500, text:'Disk full'}; } return act(op, args); };
  s.input.value = 'Plan it'; await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.input.value, 'Plan it'); assert.equal(saveBtn(s).textContent, 'Save ticket'); assert.equal(saveBtn(s).disabled, false);
  assert.equal(s.form.hidden, false);
  await s.form.fire('submit');
  assert.equal(s.c.tickets().length, 1);
  assert.deepEqual(s.calls.map(x => x.op), ['ticket.new', 'ticket.new']);
  assert.equal(s.c.location.hash, '#ticket/new');
});
