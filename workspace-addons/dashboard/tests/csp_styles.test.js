'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEB = path.resolve(__dirname, '../src/orch_dashboard/web');
// CSSOM writes (including style.cssText) are allowed. Style attributes and
// inline style elements are not allowed by the dashboard's style-src 'self'.
const forbidden = [
  /\bsetAttribute\s*\(\s*['"`]style['"`]/i,
  /\sstyle\s*=\s*\\?['"]/i,
  // h() forwards arbitrary attributes to setAttribute, including style.
  /(?:[{,]\s*)(?:style|['"]style['"])\s*:/i,
  /<style\b/i,
  /\bcreateElement\s*\(\s*['"`]style['"`]/i,
];

function sources(dir) {
  return fs.readdirSync(dir, {withFileTypes:true}).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? sources(file) : /\.(?:[cm]?js|html|svg)$/.test(file) ? [file] : [];
  });
}

test('dashboard sources do not create CSP-blocked inline styles', () => {
  const violations = [];
  for (const file of sources(WEB)) {
    const source = fs.readFileSync(file, 'utf8');
    for (const pattern of forbidden) {
      const match = pattern.exec(source);
      if (match) violations.push(`${path.relative(WEB, file)}:${source.slice(0, match.index).split('\n').length}: ${match[0]}`);
    }
  }
  assert.deepEqual(violations, [], 'Move static styles to CSS classes; use CSSOM for dynamic values');
});
