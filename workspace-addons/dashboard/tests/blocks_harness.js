// Tiny fake DOM: enough to run web/blocks.js and dump what it builds. Usage: node blocks_harness.js blocks.js view.json
const fs = require('fs');
class N {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this._text = ''; this.className = ''; this.dataset = {}; this.style = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set href(v) { this.attrs.href = v; } set target(v) { this.attrs.target = v; } set rel(v) { this.attrs.rel = v; }
  set scope(v) { this.attrs.scope = v; } set dateTime(v) { this.attrs.datetime = v; }
  set textContent(v) { this._text = String(v); this.kids = []; }
  append(...c) { for (const x of c) this.kids.push(typeof x === 'string' ? Object.assign(new N('#text'), {_text: x}) : x); }
  get childNodes() { return this.kids; }
  replaceChildren(...c) { this.kids = []; this.append(...c); }
  addEventListener(ev, fn) { (this._on = this._on || {})[ev] = fn; }
}
global.document = {createElement: t => new N(t), createElementNS: (_, t) => new N(t), createDocumentFragment: () => new N('#frag')};
const B = require(process.argv[2]);
const dump = n => ({tag: n.tag, cls: n.className, text: n._text, attrs: n.attrs, data: n.dataset, style: n.style, ...(n.hidden ? {hidden: true} : {}), kids: n.kids.map(dump)});
const view = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const urls = process.argv[4] ? JSON.parse(process.argv[4]) : {};
const tree = B.render(view.blocks, {links: process.env.LINKS === '1', addonUrl: n => urls[n] || null, self: process.argv[5] || undefined, inApp: process.argv[6] === 'inapp' ? n => p => '#open/' + n + '/' + String(p).replace(/^\/+/, '') : undefined});
// CLICK="label|label": press the buttons with these words in turn (first text child), as a person would.
const words = n => n.kids.filter(k => k.tag === '#text').map(k => k._text).join('') || n._text;
const find = (n, w) => (n.tag === 'button' && words(n) === w && n._on && n._on.click) ? n : n.kids.map(k => find(k, w)).find(Boolean);
for (const w of (process.env.CLICK || '').split('|').filter(Boolean)) { const b = find(tree, w); if (b) b._on.click(); }
console.log(JSON.stringify(dump(tree)));
