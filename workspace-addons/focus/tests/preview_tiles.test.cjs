const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/../src/orch_focus/web/proof.js', 'utf8');
function setup(mime = 'text/plain', content = '<script>attack()</script>\n' + 'line\n'.repeat(600)) {
  const calls = [], nodes = [];
  function h(tag, attrs, ...children) {
    const node = {tag, attrs: attrs || {}, children: children.flat().filter(Boolean), replaceChildren(...kids) {this.children = kids;}};
    nodes.push(node); return node;
  }
  const context = {window: {}, URL, TextDecoder, Uint8Array, fetch: async url => {
    calls.push(url); return new Response(content, {headers: {'Content-Type': mime}});
  }};
  vm.runInNewContext(source, context);
  const proof = context.window.FocusProof.create({h, P: '', TID: 't_inv7c2ab'});
  function tile(ext) {return proof.tile({c: {text: 'Task'}, ev: {type: 'file', ref: '.orch/tickets/t_inv7c2ab/evidence/test.' + ext}}, () => {});}
  return {tile, nodes, calls};
}
const settled = () => new Promise(resolve => setTimeout(resolve, 30));
test('HTML, SVG, PDF, GIF and unknown tiles only get icons and badges', async () => {
  const {tile, nodes, calls} = setup();
  for (const ext of ['html', 'htm', 'svg', 'pdf', 'gif', 'bin']) tile(ext);
  await settled();
  assert.equal(calls.length, 0);
  assert.ok(!nodes.some(n => ['iframe', 'object', 'embed', 'img'].includes(n.tag)));
  assert.equal(nodes.filter(n => n.attrs.class === 'fx-pt-badge').length, 6);
});
test('text, code and table tiles use bounded text nodes and share requests', async () => {
  const {tile, nodes, calls} = setup();
  for (const ext of ['txt', 'py', 'csv', 'txt']) tile(ext);
  await settled();
  assert.equal(calls.length, 3);
  const excerpts = nodes.filter(n => n.tag === 'pre');
  assert.equal(excerpts.length, 4);
  for (const n of excerpts) {
    assert.ok(n.attrs.text.startsWith('<script>attack()</script>'));
    assert.ok(n.attrs.text.length <= 2048);
    assert.ok(n.attrs.text.split('\n').length <= 8);
    assert.equal(n.children.length, 0);
  }
  assert.ok(!nodes.some(n => ['iframe', 'script', 'img'].includes(n.tag)));
});
test('image extensions alone do not authorize image tiles', async () => {
  const {tile, nodes} = setup('image/svg+xml');
  for (const ext of ['png', 'jpg', 'webp']) tile(ext);
  await settled();
  assert.ok(!nodes.some(n => n.tag === 'img'));
});
test('PNG, JPEG and WebP API content types authorize image tiles', async () => {
  for (const [ext, mime] of [['png', 'image/png'], ['jpg', 'image/jpeg'], ['webp', 'image/webp']]) {
    const {tile, nodes} = setup(mime, 'image bytes'); tile(ext); await settled();
    const img = nodes.find(n => n.tag === 'img');
    assert.ok(img); assert.ok(img.src.startsWith('blob:')); img.attrs.onload();
  }
});
