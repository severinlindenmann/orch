const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { decryptBlob, FAIL } = require("./file.js");

const v = JSON.parse(fs.readFileSync(path.join(__dirname, "../../contracts/vectors/publish-blob-v1.json"), "utf8"));
const hex = (h) => Uint8Array.from(Buffer.from(h, "hex"));

test("good vector decrypts to header and content", async () => {
  const r = await decryptBlob(hex(v.good.blob_hex), v.good.key_b64url);
  assert.strictEqual(JSON.stringify(r.header), v.good.header_json);
  assert.strictEqual(Buffer.from(r.content).toString("utf8"), v.good.content_utf8);
});

for (const c of v.must_fail) {
  test("must fail: " + c.name, async () => {
    await assert.rejects(decryptBlob(hex(c.blob_hex), c.key_b64url), { message: FAIL });
  });
}

test("bad magic, short blob and bad key text fail", async () => {
  const good = hex(v.good.blob_hex);
  const bad = good.slice();
  bad[0] = 0x58;
  await assert.rejects(decryptBlob(bad, v.good.key_b64url), { message: FAIL });
  await assert.rejects(decryptBlob(good.slice(0, 20), v.good.key_b64url), { message: FAIL });
  await assert.rejects(decryptBlob(good, "not a key!"), { message: FAIL });
  await assert.rejects(decryptBlob(good, "AAAA"), { message: FAIL });
});

test("flipped ciphertext byte fails the tag", async () => {
  const b = hex(v.good.blob_hex);
  b[20] ^= 1;
  await assert.rejects(decryptBlob(b, v.good.key_b64url), { message: FAIL });
});

// ---- previews ----
const P = require("./file.js");
const bv = JSON.parse(fs.readFileSync(path.join(__dirname, "../../contracts/vectors/publish-bundle-v1.json"), "utf8"));

test("bundle vector unpacks to its files", () => {
  const b = P.unbundle(hex(bv.good.bundle_hex));
  assert.strictEqual(b.entry, "index.html");
  const got = Object.fromEntries(b.files.map((f) => [f.path, Buffer.from(f.bytes).toString("utf8")]));
  assert.deepStrictEqual(got, Object.fromEntries(bv.good.files.map((f) => [f.path, f.content_utf8])));
});

for (const c of bv.must_fail) {
  test("bundle must fail: " + c.name, () => {
    assert.throws(() => P.unbundle(hex(c.bundle_hex)), { message: P.BROKEN });
  });
}

test("preview kind by name, never by the sender's type alone", () => {
  const k = (n, t) => P.previewKind(n, t || "").kind;
  assert.strictEqual(k("a.PNG"), "image");
  assert.strictEqual(k("logo.svg"), "svg");
  assert.strictEqual(k("r.pdf"), "pdf");
  assert.strictEqual(k("v.mov"), "video");
  assert.strictEqual(k("s.m4a"), "audio");
  assert.strictEqual(k("README.md"), "markdown");
  assert.strictEqual(k("x.csv"), "csv");
  assert.strictEqual(k("x.tsv"), "tsv");
  assert.strictEqual(k("x.json"), "json");
  assert.strictEqual(k("main.py"), "code");
  assert.strictEqual(k("app.ts", "video/mp2t"), "code");
  assert.strictEqual(k(".env.local"), "code");
  assert.strictEqual(k("page.html"), "html");
  assert.strictEqual(k("site", P.BUNDLE_TYPE), "bundle");
  assert.strictEqual(k("report.docx"), "");
  assert.strictEqual(k("a.zip"), "");
  assert.strictEqual(k("evil.exe", "text/html"), "");
});

test("markdown never lets raw HTML or javascript: links through", () => {
  const h = P.renderMarkdown('# Hi <img src=x onerror=alert(1)>\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1)) [ok](https://e.example/a?b="c")\n\n- [x] done\n\n| a | b |\n|---|---|\n| 1 | <b>2</b> |\n\n```py\nprint("<b>")\n```');
  assert.ok(!/<script|<img|<b>|onerror=|javascript:/i.test(h.replace(/&lt;[^&]*&gt;/g, "")), h);
  assert.ok(h.includes("&lt;script&gt;"));
  assert.ok(h.includes('<a href="https://e.example/a?b=&quot;c&quot;" target="_blank" rel="noopener noreferrer nofollow">ok</a>'));
  assert.ok(h.includes("<h1>") && h.includes("<table>") && h.includes("☑") && h.includes('class="tk-s"'));
});

test("highlight escapes and marks tokens", () => {
  const h = P.highlight('def f(x):  # <c>\n    return "a<b" + 42', "py");
  assert.ok(h.includes('<span class="tk-k">def</span>'));
  assert.ok(h.includes('<span class="tk-c"># &lt;c&gt;</span>'));
  assert.ok(h.includes('<span class="tk-s">&quot;a&lt;b&quot;</span>'));
  assert.ok(h.includes('<span class="tk-n">42</span>'));
  assert.strictEqual(P.highlight("<x>", "unknown"), "&lt;x&gt;");
});

test("csv: quotes, newlines in cells, row cap", () => {
  const r = P.parseCsv('a,"b ""q""",c\n1,"two\nlines",3\n4,5,6\n7,8,9\n', ",", 3);
  assert.deepStrictEqual(r.rows, [["a", 'b "q"', "c"], ["1", "two\nlines", "3"], ["4", "5", "6"]]);
  assert.strictEqual(r.more, true);
  assert.deepStrictEqual(P.parseCsv("x\ty", "\t", 10).rows, [["x", "y"]]);
});

test("crc32 matches the zip reference value", () => {
  assert.strictEqual(P.crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
});

test("bundle without index.html opens its first page by name", () => {
  const b = P.unbundle(hex(bv.good_no_index.bundle_hex));
  assert.strictEqual(b.entry, bv.good_no_index.entry);
  assert.deepStrictEqual(b.files.map((f) => f.path), bv.good_no_index.files.map((f) => f.path));
});

test("markdown shows https images only, escaped", () => {
  const h = P.renderMarkdown('![chart "q"](https://e.example/c.png) ![x](http://e.example/a.png) ![y](javascript:alert(1))');
  assert.ok(h.includes('<img src="https://e.example/c.png" alt="chart &quot;q&quot;" loading="lazy" referrerpolicy="no-referrer">'), h);
  assert.ok(h.includes("[x]") && h.includes("[y]") && !h.includes("javascript:alert"));
});

test("markdown emphasis never lands inside link attributes", () => {
  const h = P.renderMarkdown("see [my_file_name](https://e.example/a_b_c/*x*) and _this_");
  assert.ok(h.includes('<a href="https://e.example/a_b_c/*x*" target="_blank" rel="noopener noreferrer nofollow">my_file_name</a>'), h);
  assert.ok(h.includes("<em>this</em>"));
});
