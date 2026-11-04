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
