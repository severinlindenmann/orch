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
  const c = {Blob, serial:0, locks:new Set(), mounts:new Map(), nodeKey:() => '', clean:x => x,
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
  const drop = files => input.fire('drop', {dataTransfer:{files}});
  const chips = () => walk(d).filter(n => n.className.includes('new-ticket-file-main'));
  return {c, body, d, input, form, picker, paste, drop, chips, calls, revoked, toasts};
}
test('file validation, first nonempty title, and base64 stripping', () => {
  const c = setup().c;
  for (const ext of ['txt','md','csv','tsv','json','log','xml','yml','yaml','toml','ini','png','jpg','jpeg','gif','webp']) assert.ok(c.ticketFileType('X.' + ext.toUpperCase()));
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
  await walk(s.d).find(n => n['aria-label'] === 'Remove note.md').click();
  assert.equal(s.input.required, true); assert.equal(s.form.reportValidity(), false);
  s.input.value = '\n' + 'a'.repeat(1800); await s.input.fire('input');
  await s.form.fire('submit');
  assert.equal(s.calls[0].args.title.length, 80); assert.equal(s.calls[0].args.long_text, '\n' + 'a'.repeat(1800));
  assert.equal(s.calls[0].args.note, undefined);
});
test('file reads finish before submission; previews and URL cleanup work', async () => {
  const s = setup();
  await s.drop([{name:'readme.md',size:10,text:async () => '<b>raw</b>'}, {name:'photo.png',size:1}]);
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
test('home sends long notes intact and keeps short notes on the original path', async () => {
  for (const length of [1500, 1501]) {
    const s = setup(), calls = [];
    s.c.snapshot = false; s.c.changeUnavailable = () => false;
    s.c.h = (tag, attrs, text) => Object.assign(new Node(tag), attrs, {value:attrs.value || text || ''});
    s.c.act = async (op, args) => { calls.push(args); return {ok:true}; };
    const home = read('pages/home.js');
    vm.runInContext(home.slice(home.indexOf('function messageTicket('), home.indexOf('\nfunction ', home.indexOf('function messageTicket(') + 1)), s.c);
    const text = 'x'.repeat(length); s.c.messageTicket(text);
    await walk(s.body.children[1]).find(n => n.textContent === 'Create').click();
    assert.equal(calls[0][length > 1500 ? 'long_text' : 'note'], text);
    assert.equal(calls[0][length > 1500 ? 'note' : 'long_text'], undefined);
  }
});
test('overview file chips preview artifacts and are absent in snapshots or without files', async () => {
  const s = setup(), previews = [];
  s.c.snapshot = false; s.c.array = x => x || [];
  s.c.h = (tag, attrs, ...children) => { const n = new Node(tag); Object.assign(n, attrs); n.append(...children.map(x => typeof x === 'string' ? new Node('text', '', x) : x)); return n; };
  s.c.window.DashHelpers.plainFileName = x => x.split('/').pop();
  s.c.previewFile = (...args) => previews.push(args);
  const ticket = read('pages/ticket.js');
  vm.runInContext('const artifactData = new Map();\n' + ticket.slice(ticket.indexOf('function ticketFiles('), ticket.indexOf('async function previewFile(')), s.c);
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
