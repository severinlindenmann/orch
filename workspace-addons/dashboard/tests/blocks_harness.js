// Tiny fake DOM: enough to run web/blocks.js and dump what it builds. Usage: node blocks_harness.js blocks.js view.json
const fs = require('fs');
class N {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this._text = ''; this.className = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set href(v) { this.attrs.href = v; } set target(v) { this.attrs.target = v; } set rel(v) { this.attrs.rel = v; }
  set scope(v) { this.attrs.scope = v; } set dateTime(v) { this.attrs.datetime = v; }
  set textContent(v) { this._text = String(v); this.kids = []; }
  append(...c) { for (const x of c) this.kids.push(typeof x === 'string' ? Object.assign(new N('#text'), {_text: x}) : x); }
  get childNodes() { return this.kids; }
  replaceChildren(...c) { this.kids = []; this.append(...c); }
}
global.document = {createElement: t => new N(t), createElementNS: (_, t) => new N(t), createDocumentFragment: () => new N('#frag')};
const B = require(process.argv[2]);
const dump = n => ({tag: n.tag, cls: n.className, text: n._text, attrs: n.attrs, kids: n.kids.map(dump)});
const view = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(dump(B.render(view.blocks))));
