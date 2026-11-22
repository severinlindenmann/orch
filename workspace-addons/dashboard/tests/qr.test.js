'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const qr = require('../../../workspace/src/orch_ui/static/qr.js');

// Generated offline with cached Segno 1.6.6, no repository dependencies.
// segno.make(text, error=ecc, mode="byte", encoding="utf-8", micro=False,
//            boost_error=False, mask=mask).matrix
// Fixed masks allow full-symbol penalty selection (Segno scores before format bits).
// These payloads fill their data capacity; this avoids Segno 1.6.6 adding an
// extra zero padding byte when the terminated byte stream is already aligned.
const vectors = [
  {
    "text": "https://example.com/places",
    "ecc": "M",
    "version": 2,
    "mask": 2,
    "rows": [
      "1111111000110100101111111",
      "1000001000100111101000001",
      "1011101010000010001011101",
      "1011101011100111001011101",
      "1011101011110100101011101",
      "1000001010010011001000001",
      "1111111010101010101111111",
      "0000000011001010100000000",
      "1011111001001100001111100",
      "0111110010000100010100010",
      "0001101010011111100101011",
      "0001010101100011101100001",
      "1101011011011111011010111",
      "1110000000101010100101010",
      "1000001010100001001111011",
      "1010100000111001111110001",
      "1010111010100110111110100",
      "0000000011110101100011000",
      "1111111001100010101010111",
      "1000001010100000100011000",
      "1011101011001111111110100",
      "1011101011110001011011111",
      "1011101010100001000001101",
      "1000001000011010110111001",
      "1111111011101110011111111"
    ]
  },
  {
    "text": "Zürich ✓ ab",
    "ecc": "M",
    "version": 1,
    "mask": 5,
    "rows": [
      "111111100111101111111",
      "100000101111101000001",
      "101110101010001011101",
      "101110101101001011101",
      "101110100010101011101",
      "100000100110101000001",
      "111111101010101111111",
      "000000001100000000000",
      "100000101100111001110",
      "000101000110001000101",
      "011010100011100101011",
      "001101010011111000001",
      "100010100111110100010",
      "000000001010000011010",
      "111111100111101000110",
      "100000100110100101100",
      "101110100010110101011",
      "101110100100011010100",
      "101110100101111011011",
      "100000100111001101100",
      "111111101100110110010"
    ]
  },
  {
    "text": "abcdefghijklmnopq",
    "ecc": "L",
    "version": 1,
    "mask": 6,
    "rows": [
      "111111101110001111111",
      "100000100001101000001",
      "101110100011001011101",
      "101110100101001011101",
      "101110100101001011101",
      "100000100110101000001",
      "111111101010101111111",
      "000000001000000000000",
      "110110100111001000001",
      "111101000100000000100",
      "100101100010101001011",
      "000001011000110100110",
      "111010100100010011011",
      "000000001000010010110",
      "111111100101100011000",
      "100000100000111001111",
      "101110101100000001001",
      "101110101001001000110",
      "101110100100110011111",
      "100000101011001101111",
      "111111101000011010000"
    ]
  }
];

for (const vector of vectors) {
  test(`reference matrix: ${vector.text}, ECC ${vector.ecc}`, () => {
    const result = qr.matrix(vector.text, {ecc: vector.ecc});
    assert.equal(result.size, vector.version*4+17);
    assert.deepEqual(result.modules, vector.rows.map(row => [...row].map(bit => bit === '1')));
  });
}

// Larger reference symbols cover version bits, 16-bit counts, unequal blocks,
// the special version-32 alignment spacing and the version-40 limit.
const largeVectors = [
  {
    "ecc": "L",
    "version": 7,
    "length": 154,
    "mask": 1,
    "sha256": "352966e01ad8fe9a2c9d24665dc81182846f7c4ac4db5ea182736065cb67a75d"
  },
  {
    "ecc": "L",
    "version": 10,
    "length": 271,
    "mask": 1,
    "sha256": "69c2f47c1a79c2b7e2f1e16c89f303b1b8752f069bced3200722e7afd24a9356"
  },
  {
    "ecc": "L",
    "version": 32,
    "length": 1952,
    "mask": 2,
    "sha256": "4cf46ef92b90d1c2eded24fb1e2a9795dfed1309b35622e35fc049ed0f505859"
  },
  {
    "ecc": "L",
    "version": 40,
    "length": 2953,
    "mask": 1,
    "sha256": "6620e9cef6a5e3b03c0500f72006c3c2537d18a0cc202b02d9849ab0c1f46afb"
  },
  {
    "ecc": "M",
    "version": 7,
    "length": 122,
    "mask": 1,
    "sha256": "e2c80e80b235a56bb02f503ebc95807d91ae2a2d08244b1eba15e14dd8f28df4"
  },
  {
    "ecc": "M",
    "version": 10,
    "length": 213,
    "mask": 1,
    "sha256": "15c53ebe74e54b2f32a635ec5b999ccda1b81ec289efabf34d863cb4e6cd8c1d"
  },
  {
    "ecc": "M",
    "version": 32,
    "length": 1538,
    "mask": 2,
    "sha256": "a2187dd04d9f897ef397402aa9cfa6d7340a9d10c7105f662c1b6885464cb798"
  },
  {
    "ecc": "M",
    "version": 40,
    "length": 2331,
    "mask": 1,
    "sha256": "233dc26632b8135df6638fdf3f1b98d4ea03dbedb9524bf9dec62cc182549fbc"
  }
];

for (const vector of largeVectors) {
  test(`reference digest: version ${vector.version}, ECC ${vector.ecc}`, () => {
    const result = qr.matrix('a'.repeat(vector.length), {ecc: vector.ecc});
    assert.equal(result.size, vector.version*4+17);
    const rows = result.modules.map(row => row.map(Number).join('')).join('\n');
    assert.equal(createHash('sha256').update(rows).digest('hex'), vector.sha256);
  });
}

test('capacity and smallest version use UTF-8 byte counts', () => {
  assert.equal(qr.matrix('a'.repeat(14)).size, 21);
  assert.equal(qr.matrix('a'.repeat(15)).size, 25);
  assert.equal(qr.matrix('a'.repeat(17), {ecc: 'L'}).size, 21);
  assert.equal(qr.matrix('a'.repeat(18), {ecc: 'L'}).size, 25);
  assert.equal(qr.matrix('✓'.repeat(4)).size, 21);
  assert.equal(qr.matrix('✓'.repeat(5)).size, 25);
  assert.equal(qr.matrix('').size, 21);
  assert.deepEqual(qr.matrix('Zürich ✓'), qr.matrix('Zürich ✓', {ecc: 'M'}));
  const large = qr.matrix('a'.repeat(2000), {ecc: 'L'});
  assert.ok(large.size <= 177);
  assert.ok(qr.fits('a'.repeat(2000), {ecc: 'L'}));
  for (const [ecc, limit] of [['L', 2953], ['M', 2331]]) {
    assert.equal(qr.matrix('a'.repeat(limit), {ecc}).size, 177);
    assert.equal(qr.fits('a'.repeat(limit+1), {ecc}), false);
    assert.equal(qr.matrix('a'.repeat(3000), {ecc}), null);
    assert.equal(qr.fits('a'.repeat(3000), {ecc}), false);
    assert.equal(qr.svg('a'.repeat(3000), {ecc}), null);
  }
});

test('finder patterns, separators and alternating timing patterns', () => {
  const {size, modules} = qr.matrix('https://example.com');
  for (const [left, top] of [[0,0], [size-7,0], [0,size-7]]) {
    for (let y = 0; y < 7; y++) for (let x = 0; x < 7; x++) {
      const expected = x === 0 || y === 0 || x === 6 || y === 6 ||
        (x >= 2 && x <= 4 && y >= 2 && y <= 4);
      assert.equal(modules[top+y][left+x], expected);
    }
  }
  for (let i = 0; i < 8; i++) {
    assert.equal(modules[7][i], false);
    assert.equal(modules[i][7], false);
    assert.equal(modules[7][size-1-i], false);
    assert.equal(modules[size-1-i][7], false);
  }
  for (let i = 8; i < size-8; i++) {
    assert.equal(modules[6][i], i%2 === 0);
    assert.equal(modules[i][6], i%2 === 0);
  }
  assert.equal(modules[size-8][8], true);
  assert.ok(modules.every(row => row.length === size && row.every(bit => typeof bit === 'boolean')));
});

test('browser SVG uses namespace elements, one currentColor path and quiet zone', () => {
  const document = {
    createElementNS(ns, name) {
      return {
        ns, name, attrs: {}, children: [],
        setAttribute(key, value) { this.attrs[key] = String(value); },
        appendChild(child) { this.children.push(child); },
        set innerHTML(value) { assert.fail('SVG must not use innerHTML'); }
      };
    }
  };
  const context = {window: {}, document, TextEncoder};
  vm.runInNewContext(fs.readFileSync(require.resolve('../../../workspace/src/orch_ui/static/qr.js'), 'utf8'), context);
  const api = context.window.OrchQR;
  const label = '<Link to Zürich & places>';
  const svg = api.svg('https://example.com', {label});
  assert.equal(svg.ns, 'http://www.w3.org/2000/svg');
  assert.equal(svg.name, 'svg');
  assert.deepEqual(svg.attrs, {viewBox: '0 0 33 33', class: 'qr', role: 'img', 'aria-label': label});
  assert.equal(svg.children.length, 1);
  const path = svg.children[0];
  assert.equal(path.name, 'path');
  assert.equal(path.ns, svg.ns);
  assert.equal(path.attrs.fill, 'currentColor');
  const commands = [...path.attrs.d.matchAll(/M(\d+) (\d+)h1v1h-1z/g)];
  assert.equal(commands.map(match => match[0]).join(''), path.attrs.d);
  const result = qr.matrix('https://example.com');
  const expected = [];
  result.modules.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) expected.push([x+4, y+4]);
  }));
  assert.deepEqual(commands.map(match => [+match[1], +match[2]]), expected);
  assert.equal(api.svg('orch').attrs['aria-label'], 'QR code');
  assert.equal(api.svg('a'.repeat(3000)), null);
});

test('unsupported ECC and non-string input fail explicitly', () => {
  assert.throws(() => qr.matrix('orch', {ecc: 'H'}), RangeError);
  assert.throws(() => qr.fits(123), TypeError);
});
