// ORCH-67: Settings' 'Open the style guide' lost its address because h() kept only # and http(s) links. h() now
// also keeps a path on this site (/x) and still drops everything that leaves it (//x, /\x, javascript:, data:).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const source = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const hSource = source.slice(source.indexOf('function h(tag'), source.indexOf('const fragment ='));

function hrefOf(value) {
  const node = {dataset:{}, attrs:{}, setAttribute(k, v) { this.attrs[k] = v; }};
  const ctx = {document:{createElement:() => node}, append:n => n};
  vm.createContext(ctx); vm.runInContext(hSource, ctx);
  return ctx.h('a', {href:value}).attrs.href;
}

test('h() keeps routes, web addresses and paths on this site', () => {
  for (const ok of ['#settings', 'https://github.com/x', 'http://127.0.0.1:1/', '/styleguide', '/api/file?t=t_a&k=files&n=x']) {
    assert.equal(hrefOf(ok), ok, ok);
  }
});

test('h() drops addresses that leave the site or run code', () => {
  for (const bad of ['//evil.example/x', '/\\evil.example', 'javascript:alert(1)', 'JAVASCRIPT:x', 'data:text/html,x', 'vbscript:x', 'kit/x.html']) {
    assert.equal(hrefOf(bad), undefined, bad);
  }
});

test("Settings' style guide button opens /styleguide in a new tab", () => {
  const settings = fs.readFileSync(path.join(WEB, 'pages/settings.js'), 'utf8');
  const line = settings.split('\n').find(l => l.includes("'data-key':'settings-style-guide'"));
  assert.ok(line && line.includes("href:'/styleguide'") && line.includes("target:'_blank'") && line.includes("rel:'noopener'"));
});
