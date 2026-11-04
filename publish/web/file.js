// Browser side of /f/<id>: fetch the encrypted blob, decrypt with WebCrypto (crypto.md, OPF1), offer the download.
// The pure functions at the top are also loaded by node --test (web/file.test.js).
"use strict";

function b64urlToBytes(s) {
  if (!/^[A-Za-z0-9_-]+$/.test(s)) throw new Error("bad key");
  const b = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(b);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const FAIL = "wrong key or broken file";

// blob: Uint8Array, keyB64: base64url key. Returns {header, content}. Throws Error(FAIL) on any problem.
async function decryptBlob(blob, keyB64, subtle) {
  subtle = subtle || globalThis.crypto.subtle;
  try {
    const key = b64urlToBytes(keyB64);
    if (key.length !== 32) throw new Error("key length");
    if (blob.length < 32) throw new Error("short");
    if (String.fromCharCode(blob[0], blob[1], blob[2], blob[3]) !== "OPF1") throw new Error("magic");
    const iv = blob.slice(4, 16);
    const aad = blob.slice(0, 4);
    const k = await subtle.importKey("raw", key, { name: "AES-GCM" }, false, ["decrypt"]);
    const plain = new Uint8Array(
      await subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad, tagLength: 128 }, k, blob.slice(16))
    );
    if (plain.length < 4) throw new Error("short plaintext");
    const n = new DataView(plain.buffer, plain.byteOffset, 4).getUint32(0, false);
    if (n < 1 || n > 65536 || 4 + n > plain.length) throw new Error("header length");
    const header = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plain.slice(4, 4 + n)));
    const content = plain.slice(4 + n);
    if (header === null || typeof header !== "object" || header.size !== content.length) throw new Error("size");
    return { header, content };
  } catch (e) {
    throw new Error(FAIL);
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { decryptBlob, b64urlToBytes, FAIL };
}

if (typeof document !== "undefined") {
  (function () {
    const $ = (id) => document.getElementById(id);
    function show(icon, title, msg) {
      $("icon").textContent = icon;
      $("title").textContent = title;
      $("msg").textContent = msg;
      $("extra").textContent = "";
    }
    function size(n) {
      return n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
    }
    async function main() {
      const m = /^#k=([A-Za-z0-9_-]+)$/.exec(location.hash);
      if (!m) {
        return show("⌐", "This link is missing its key", "You need the complete sharing link to open this file. Ask the sender to copy it again, including the part after #.");
      }
      if (!globalThis.crypto || !globalThis.crypto.subtle) {
        return show("⌐", "This browser cannot open the file", "Open the link in a current browser over a secure (https) connection.");
      }
      const id = location.pathname.split("/").filter(Boolean)[1];
      let res;
      try {
        res = await fetch("/f/" + encodeURIComponent(id) + "/blob", { cache: "no-store" });
      } catch (e) {
        return show("⌐", "Could not load the file", "Check your connection and try again.");
      }
      if (res.status === 410) return show("◷", "This file has expired", "The file is no longer available. Ask the sender to share a new link.");
      if (!res.ok) return show("⌐", "This file does not exist", "The link may be wrong, or the file was deleted.");
      const blob = new Uint8Array(await res.arrayBuffer());
      let r;
      try {
        r = await decryptBlob(blob, m[1]);
      } catch (e) {
        return show("⌐", "This key doesn’t open the file", "The link may have been changed or cut short. Ask the sender for the complete link, including the part after #.");
      }
      show("▤", String(r.header.name || "file"), "Decrypted in your browser.");
      const meta = document.createElement("div");
      meta.className = "file-meta";
      const a = document.createElement("span");
      a.textContent = (r.header.type || "file") + " · " + size(r.content.length);
      meta.appendChild(a);
      const btn = document.createElement("button");
      btn.className = "primary";
      btn.textContent = "↓ Download file";
      btn.addEventListener("click", function () {
        const url = URL.createObjectURL(new Blob([r.content], { type: "application/octet-stream" }));
        const l = document.createElement("a");
        l.href = url;
        l.download = String(r.header.name || "file").replace(/[\\/]/g, "_");
        document.body.appendChild(l);
        l.click();
        l.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      });
      $("extra").append(meta, btn);
    }
    main();
  })();
}
