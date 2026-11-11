// The real shell (app.js) and ticket page on a small DOM double: a poll that changes only the ticket's own fields
// (work, status, ...) must reach the open ticket page without navigation or reload.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');

function dom() {
  class Node {
    constructor() { this.parentNode = null; this.childNodes = []; }
    remove() { if (this.parentNode) { const kids = this.parentNode.childNodes; kids.splice(kids.indexOf(this), 1); this.parentNode = null; } }
    get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === doc.body; }
  }
  class Text extends Node {
    constructor(data) { super(); this.nodeType = 3; this.nodeName = '#text'; this.data = String(data); }
    get textContent() { return this.data; }
  }
  const selector = sel => sel.split(',').map(s => {
    const c = /^\s*\.([a-z0-9_-]+)\s*$/i.exec(s);  // .class (the page also asks for .sidebar and .dragging)
    if (c) return n => n.nodeType === 1 && String(n.className || '').split(/\s+/).includes(c[1]);
    const m = /^\s*([a-z0-9]*)(?:\[([a-z-]+)(?:="([^"]*)")?\])?\s*$/i.exec(s);
    if (!m) return () => false;  // a selector this fake does not know matches nothing, never throws
    return n => n.nodeType === 1 && (!m[1] || n.tagName === m[1].toUpperCase()) && (!m[2] || (n.hasAttribute(m[2]) && (m[3] === undefined || n.getAttribute(m[2]) === m[3])));
  });
  class El extends Node {
    constructor(tag, type = 1) {
      super();
      this.nodeType = type; this.tagName = this.nodeName = String(tag).toUpperCase(); this.attrs = new Map();
      const attr = k => 'data-' + k.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
      this.dataset = new Proxy({}, {
        get:(_, k) => typeof k === 'string' && this.attrs.has(attr(k)) ? this.attrs.get(attr(k)) : undefined,
        set:(_, k, v) => { this.attrs.set(attr(k), String(v)); return true; },
      });
      this.classList = {add:(...c) => { this.className = [...new Set([...this.className.split(' '), ...c])].filter(Boolean).join(' '); }, remove:(...c) => { this.className = this.className.split(' ').filter(x => !c.includes(x)).join(' '); }, contains:c => this.className.split(' ').includes(c)};
    }
    get attributes() { return [...this.attrs].map(([name, value]) => ({name, value})); }
    getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
    setAttribute(k, v) { this.attrs.set(k, String(v)); }
    hasAttribute(k) { return this.attrs.has(k); }
    removeAttribute(k) { this.attrs.delete(k); }
    get className() { return this.getAttribute('class') || ''; }
    set className(v) { this.setAttribute('class', v); }
    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }
    get hidden() { return this.hasAttribute('hidden'); }
    set hidden(v) { if (v) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); }
    get disabled() { return this.hasAttribute('disabled'); }
    set disabled(v) { if (v) this.setAttribute('disabled', ''); else this.removeAttribute('disabled'); }
    set innerHTML(_) { this.childNodes.forEach(n => { n.parentNode = null; }); this.childNodes = []; }
    get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
    set textContent(v) { this.replaceChildren(new Text(v)); }
    insertBefore(node, ref) {
      if (node.nodeType === 11) { for (const c of [...node.childNodes]) this.insertBefore(c, ref); return node; }
      node.remove(); node.parentNode = this;
      const at = ref ? this.childNodes.indexOf(ref) : -1;
      if (at < 0) this.childNodes.push(node); else this.childNodes.splice(at, 0, node);
      return node;
    }
    appendChild(node) { return this.insertBefore(node, null); }
    append(...kids) { for (const k of kids) this.appendChild(typeof k === 'string' ? new Text(k) : k); }
    replaceChildren(...kids) { this.childNodes.forEach(n => { n.parentNode = null; }); this.childNodes = []; this.append(...kids); }
    addEventListener() {}
    focus() {}
    contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
    matches(sel) { return selector(sel).some(f => f(this)); }
    closest(sel) { let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
    querySelectorAll(sel) { const fs = selector(sel), out = []; const walk = n => { for (const c of n.childNodes) { if (fs.some(f => f(c))) out.push(c); walk(c); } }; walk(this); return out; }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  }
  const doc = {body:new El('body'), activeElement:null, visibilityState:'visible', addEventListener() {},
    createElement:t => new El(t), createElementNS:(_, t) => new El(t), createTextNode:t => new Text(t), createDocumentFragment:() => new El('#document-fragment', 11)};
  for (const id of ['content', 'side-nav', 'side-settings', 'workspace-name', 'workspace-mode', 'crumb', 'new-ticket', 'open-agent', 'menu-toggle', 'connection']) {
    const n = new El(id === 'content' ? 'main' : 'div'); n.id = id; doc.body.appendChild(n);
  }
  const sidebar = new El('aside'); sidebar.className = 'sidebar'; doc.body.appendChild(sidebar);
  doc.getElementById = id => doc.body.querySelectorAll('[id="' + id + '"]')[0] || null;
  doc.querySelectorAll = sel => doc.body.querySelectorAll(sel);
  doc.querySelector = sel => doc.body.querySelector(sel);
  return {Node, doc};
}

function page(first) {
  const {Node, doc} = dom();
  const replies = [first];
  const window = {DashHelpers:helpers, icon:() => '<svg><path d=""/></svg>', scrollX:0, scrollY:0, scrollTo() {}, addEventListener() {}, dispatchEvent() {},
    orch:{toast() {}, enter() {}, needsIn() {}, close() {}, resolve() {}}};
  const ctx = {window, document:doc, Node, location:{hash:'#ticket/t_x'}, history:{replaceState() {}}, localStorage:{getItem:() => null, setItem() {}},
    CustomEvent:class { constructor(type, init) { this.type = type; this.detail = init?.detail; } }, MutationObserver:class { observe() {} disconnect() {} },
    setInterval:() => 0, clearInterval() {}, setTimeout:() => 0, clearTimeout() {}, addEventListener() {}, console,
    fetch:url => ['/api/state', '/api/act'].includes(url) ? Promise.resolve(replies.shift()).then(body => ({ok:true, status:200, json:async () => body})) : new Promise(() => {})};
  window.window = window;
  vm.createContext(ctx);
  vm.runInContext([...['home', 'tickets', 'ticket', 'newticket', 'settings', 'chat', 'notes'].map(p => read('pages/' + p + '.js')), read('app.js')].join('\n'), ctx);
  const main = doc.getElementById('content');
  return {
    main, replies,
    refresh:() => vm.runInContext('refresh()', ctx),
    act:(op, args) => ctx.window.orchAct(op, args),
    count:key => main.querySelectorAll('[data-key="' + key + '"]').length,
    text:() => main.textContent,
    poll:async next => { replies.push(next); await vm.runInContext('refresh()', ctx); },
  };
}
const ticket = (extra = {}) => ({id:'t_x', title:'Fix the login form', status:'active', checklist:[{id:'c1', text:'Look', state:'doing'}], questions:[], history:[], refs:[], sessions:[], updated_at:'2026-11-11T10:00:00Z', revision:4, ...extra});
const state = (t, extra = {}) => ({workspace:'demo', now:'2026-11-11T10:00:00Z', tickets:[t], needs:[], addons:[], runs:{t_x:{running:true, claim:{agent:'claude', mode:'run'}}}, rev:'a', ...extra});
const tick = () => new Promise(r => setImmediate(r));

test('the open ticket page shows the copy line when only tickets[id].work changes in a poll', async () => {
  const p = page(state(ticket()));
  await tick(); await tick();
  assert.ok(p.text().includes('Fix the login form'), 'the ticket page is shown');
  assert.equal(p.count('work-copy'), 0);
  await p.poll(state(ticket({work:{folders:[{branch:'orch/t_x', base:'abc', sub:'', host:'m'}]}}), {rev:'b'}));
  assert.equal(p.count('work-copy'), 1, 'no reload or navigation needed');
  assert.ok(p.text().includes('orch/t_x'));
});

test('a change notice that arrives while a state fetch is running is not lost', async () => {
  // load_state reads the tickets first and `orch run status` last: a fetch that started before the copy was recorded
  // answers with the new shared-folder line but the old ticket. The notice that came meanwhile must fetch again.
  const p = page(state(ticket()));
  await tick(); await tick();
  let answer;
  p.replies.push(new Promise(r => { answer = r; }));
  const running = p.refresh();                       // e.g. the run record changed (SSE "rev")
  const notice = p.refresh();                        // the ticket file got `work` while that fetch runs
  const shared = {t_x:{running:true, claim:{agent:'claude', mode:'run'}, shared_folder:{line:'"Other" is also changing this folder.'}}};
  p.replies.push(state(ticket({work:{folders:[{branch:'orch/t_x', base:'abc', sub:'', host:'m'}]}, revision:5}), {rev:'c', runs:shared}));
  answer(state(ticket(), {rev:'b', runs:shared}));
  await running; await notice; await tick(); await tick();
  assert.equal(p.count('shared-folder'), 1);
  assert.equal(p.count('work-copy'), 1, 'the second notice fetched the state again');
});

test('a change notice that arrives while a change is being saved fetches once more after it', async () => {
  const p = page(state(ticket()));
  await tick(); await tick();
  let answer;
  p.replies.push(new Promise(r => { answer = r; }));
  const saving = p.act('ticket.edit', {ticket:'t_x', note:'hi', if_revision:4});
  await p.refresh();                                  // dropped before: a write was under way
  p.replies.push(state(ticket({note:'hi', work:{folders:[{branch:'orch/t_x', base:'abc', sub:'', host:'m'}]}, revision:6}), {rev:'c'}));
  answer(state(ticket({note:'hi', revision:5}), {rev:'b'}));
  await saving; await tick(); await tick();
  assert.equal(p.count('work-copy'), 1);
});

test('status chip, shared folder line, copy line and agent bar all follow each new state', async () => {
  const p = page(state(ticket()));
  await tick(); await tick();
  const work = {folders:[{branch:'orch/t_x', base:'abc', sub:'', host:'m'}]};
  await p.poll(state(ticket({work}), {rev:'b'}));
  assert.equal(p.count('work-copy'), 1);
  assert.equal(p.count('agent-bar'), 1, 'the run/agent bar is there for a running ticket');
  await p.poll(state(ticket({status:'review', work}), {rev:'c', runs:{}}));
  assert.ok(p.text().includes('Ready for review'), 'the status chip follows the ticket');
  assert.equal(p.count('agent-bar'), 0, 'no agent bar in Review');
  await p.poll(state(ticket({status:'active'}), {rev:'d', runs:{t_x:{running:true, claim:{agent:'claude', mode:'run'}, shared_folder:{line:'"Other" is also changing this folder.'}}}}));
  assert.equal(p.count('work-copy'), 0, 'the copy line goes when the ticket no longer has one');
  assert.equal(p.count('shared-folder'), 1, 'the shared folder line follows state.runs');
  assert.equal(p.count('agent-bar'), 1);
});
