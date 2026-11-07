const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
globalThis.window = globalThis;
require("./look-data.js");
const L = require("./look.js");
const v = JSON.parse(fs.readFileSync(path.join(__dirname, "../../contracts/vectors/look-v1.json"), "utf8"));

test("default colour and letter replay the vectors", () => {
  for (const d of v.default) {
    assert.strictEqual(L.djb2(d.name), d.djb2_32, d.name);
    assert.strictEqual(L.defaultColor(d.name), d.color, d.name);
    assert.strictEqual(L.letter(d.name), d.letter, d.name);
  }
});

test("render falls back to letter and automatic colour", () => {
  for (const r of v.render) {
    const s = L.resolve(r.name, r.icon, r.color);
    assert.strictEqual(s.icon, r.shown.icon, r.why);
    assert.strictEqual(s.color, r.shown.color, r.why);
    assert.strictEqual(s.letter, r.shown.letter, r.why);
  }
});

test("prototype names are not icons or colours", () => {
  for (const k of ["__proto__", "constructor", "toString", "hasOwnProperty"]) {
    const s = L.resolve("Finance", k, k);
    assert.strictEqual(s.icon, null, k);
    assert.strictEqual(s.color, L.defaultColor("Finance"), k);
  }
});
