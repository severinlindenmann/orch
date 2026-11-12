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
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  get firstChild() { return this.children[0]; }
  setAttribute(k, v) { this[k] = v; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  async fire(k, extra = {}) { const e = {preventDefault() { this.prevented = true; }, ...extra}; for (const fn of this.listeners[k] || []) await fn(e); return e; }
  click() { return this.fire('click'); }
  setCustomValidity(s) { this.validity = s; }
  reportValidity() { return !walk(this).some(n => n.validity || (n.required && !n.value)); }
  focus() {}
  contains(n) { return walk(this).includes(n); }
  remove() { this.isConnected = false; this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}
const walk = n => [n, ...n.children.flatMap(walk)];
function setup() {
  const body = new Node('body'), calls = [], revoked = [], toasts = [], items = [];
  const c = {Blob, TextDecoder, Uint8Array, btoa, serial:0, locks:new Set(), mounts:new Map(), nodeKey:() => '', clean:x => x,
    el:(...args) => new Node(...args), document:{body, activeElement:null}, render:() => { c.renders++; }, renders:0,
    sizeText:n => n + ' B', URL:{createObjectURL:() => 'blob:test', revokeObjectURL:x => revoked.push(x)},
    FileReader:class { readAsDataURL() { this.result = 'data:image/png;base64,YQ=='; this.onload(); } },
    tickets:() => items, ticketOf:() => null, refresh:async () => {},
    act:async (op, args) => { calls.push({op, args}); if (op === 'ticket.new') items.push({id:'new', title:args.title}); return {ok:true, state:{attached:{failed:['bad.txt']}}}; },
    window:{DashHelpers:{scrubText:x => x}, orch:{open:d => { d.open = true; }, close:async d => { d.open = false; await d.fire('close'); }, toast:(...x) => toasts.push(x)}}};
  c.button = (text, cls, fn) => { const b = c.el('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; };
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
  assert.equal(c.ticketFileError({name:'x.md',size:2097153}, []), 'x.md is over 2 MB');
  assert.equal(c.ticketFileError({name:'x.md',size:2097152}, []), '');
  assert.equal(c.ticketFileError({name:'x.md',size:1}, Array(4).fill({size:1})), 'At most 4 files');
  assert.equal(c.ticketFileError({name:'x.md',size:2*1024*1024}, [{size:2*1024*1024}]), 'Files are over 3.5 MB');
  assert.equal(c.ticketTextTitle('\n  hello\r\nworld', 3), 'hel');
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
  assert.equal(s.calls[1].op, 'run.start');
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
test('overview file chips preview artifacts and are absent in snapshots or without files', async () => {
  const s = setup(), previews = [];
  s.c.snapshot = false; s.c.array = x => x || [];
  s.c.h = (tag, attrs, ...children) => { const n = new Node(tag); Object.assign(n, attrs); n.append(...children.map(x => typeof x === 'string' ? new Node('text', '', x) : x)); return n; };
  s.c.window.DashHelpers.plainFileName = x => x.split('/').pop();
  s.c.previewFile = (...args) => previews.push(args);
  const ticket = read('pages/ticket.js');
  vm.runInContext('const artifactData = new Map();\n' + ticket.slice(ticket.indexOf('// One file = one entry'), ticket.indexOf('function ticketResultCard(')) + ticket.slice(ticket.indexOf('function ticketFiles('), ticket.indexOf('async function previewFile(')), s.c);
  assert.equal(s.c.ticketFiles({id:'t'}), null);
  vm.runInContext("artifactData.set('t', {data:{files:[{name:'folder/note.md',size:20000}]}})", s.c);
  const section = s.c.ticketFiles({id:'t'});
  assert.equal(walk(section).find(n => n.tag === 'span').textContent, 'folder/note.md');
  await walk(section).find(n => n.tag === 'button').click();
  assert.deepEqual(previews, [['t','artifacts','folder/note.md']]);
  s.c.snapshot = true; assert.equal(s.c.ticketFiles({id:'t'}), null);
});
test('textarea title takes priority when typed long text follows a pasted note', async () => {
  const s = setup(); await s.paste('Original\n' + 'a'.repeat(1501));
  s.input.value = 'New title\n' + 'b'.repeat(1501); await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title, 'New title');
  assert.equal(s.calls[0].args.long_text, 'Original\n' + 'a'.repeat(1501) + '\n\nNew title\n' + 'b'.repeat(1501));
});
test('a text file that is not UTF-8 is sent as base64, unaltered; a body over 4.9 MB is refused plainly', async () => {
  const s = setup();
  await s.drop([{name:'latin.txt', size:3, arrayBuffer:async () => new Uint8Array([0x63, 0xe9, 0x66]).buffer}]);
  await s.form.fire('submit');
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].args.files)), [{name:'latin.txt', data:btoa('c\xe9f')}]);
  const big = setup(); await big.paste('x'.repeat(1501));
  big.input.value = 'y'.repeat(5000000); await big.input.fire('input');
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

test('Show me the plan first is a box in More options; Start creates a plan-first ticket and starts it', async () => {
  const s = setup();
  s.form.requestSubmit = () => s.form.fire('submit');
  s.input.value = 'Make a plan'; await s.input.fire('input');
  const options = walk(s.d).find(n => n.className === 'new-ticket-options');
  const box = walk(options).find(n => n.name === 'plan_first');
  assert.equal(box.type, 'checkbox');
  box.checked = true;
  await s.form.fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.calls[0].op, 'ticket.new');
  assert.equal(s.calls[0].args.plan_first, true);
  assert.equal(s.calls[1].op, 'run.start');
  assert.equal(s.calls[1].args.ticket, 'new');
});

test('one Start button; Create without starting is a text link; neither sends plan_first by default', async () => {
  const labels = walk(setup().d).filter(n => n.tag === 'button' && /btn/.test(n.className)).map(n => n.textContent);
  assert.ok(labels.includes('Start') && !labels.includes('Create & Start') && !labels.includes('Show plan first'));
  for (const label of ['Create without starting', 'Start']) {
    const s = setup();
    s.form.requestSubmit = () => s.form.fire('submit');
    s.input.value = 'Work'; await s.input.fire('input');
    const node = walk(s.d).find(n => n.textContent === label);
    if (label === 'Start') { await node.click(); await s.form.fire('submit'); } else { assert.equal(node.className, 'new-ticket-link'); await node.click(); }
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(s.calls[0].args.plan_first, undefined);
    assert.equal(s.calls.length, label === 'Start' ? 2 : 1);
  }
});

test('attach is a link, drops land anywhere on the form, pasted text reads in pages', async () => {
  const s = setup();
  assert.ok(walk(s.d).some(n => n.textContent === 'Attach file' && n.className === 'new-ticket-attach'));
  assert.equal(s.input.rows, 4);
  assert.equal((await s.form.fire('drop', {dataTransfer:{files:[{name:'plan.md', size:3, arrayBuffer:async () => new TextEncoder().encode('abc').buffer}]}})).prevented, true);
  await s.paste('x'.repeat(9000));
  walk(s.d).find(n => n.type === 'submit').disabled = true; await s.form.fire('submit');
  const labels = s.chips().map(n => n.children.map(c => c.textContent).join('|'));
  assert.deepEqual(labels, ['Pasted text (about 3 pages)', 'plan.md']);
  assert.equal(s.c.pastedLabel('x'.repeat(100)), 'Pasted text (about 1 page)');
});
