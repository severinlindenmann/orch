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
    const I = (d) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + "</svg>";
    const ICONS = {
      link: I('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
      clock: I('<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>'),
      file: I('<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/>'),
      lock: I('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
    };
    function show(icon, title, msg, ok) {
      $("icon").innerHTML = ICONS[icon];
      $("title").textContent = title;
      $("msg").textContent = msg;
      $("extra").textContent = "";
      $("note").hidden = !ok;
      clearTimeout(slow);
    }
    function retryButton() {
      const b = document.createElement("button");
      b.className = "primary";
      b.textContent = "Try again";
      b.addEventListener("click", function () {
        b.setAttribute("aria-busy", "true");
        main();
      });
      $("extra").appendChild(b);
    }
    let slow;
    function size(n) {
      return n < 1024 ? n + (n === 1 ? " byte" : " bytes") : n < 1048576 ? (n / 1024).toFixed(1).replace(/\.0$/, "") + " KB" : (n / 1048576).toFixed(1).replace(/\.0$/, "") + " MB";
    }
    function kind(t) {
      t = String(t || "");
      if (t.startsWith("text/")) return "Text file";
      if (t.startsWith("image/")) return "Image";
      if (t === "application/pdf") return "PDF";
      if (t.startsWith("video/")) return "Video";
      if (t.startsWith("audio/")) return "Audio";
      if (t.indexOf("zip") >= 0) return "Archive";
      return "File";
    }
    async function main() {
      clearTimeout(slow);
      slow = setTimeout(function () {
        if ($("title").textContent !== "Opening your file…") return;
        $("title").textContent = "Preparing your file…";
        $("msg").textContent = "This is taking longer than usual. Large files can take a minute. You can leave and come back to this link.";
      }, 10000);
      const m = /^#k=([A-Za-z0-9_-]+)$/.exec(location.hash);
      if (!m) {
        return show("link", "This link is incomplete", "Ask the sender to copy the full link again.");
      }
      if (!globalThis.crypto || !globalThis.crypto.subtle) {
        return show("lock", "This browser can’t open the file", "Open the link in an up-to-date browser, over a secure (https) address.");
      }
      const id = location.pathname.split("/").filter(Boolean)[1];
      let res;
      try {
        res = await fetch("/f/" + encodeURIComponent(id) + "/blob", { cache: "no-store" });
      } catch (e) {
        show("link", "Couldn’t load the file", "You may be offline. Check your connection and try again.");
        return retryButton();
      }
      if (res.status === 410) return show("clock", "This file has expired", "It is no longer available. Ask the sender to share it again.");
      if (!res.ok) return show("link", "This file isn’t available", "Check the link or ask the sender for a new one.");
      const blob = new Uint8Array(await res.arrayBuffer());
      let r;
      try {
        r = await decryptBlob(blob, m[1]);
      } catch (e) {
        return show("link", "This link doesn’t open the file", "It may have been cut short or changed. Ask the sender for a new link.");
      }
      show("file", String(r.header.name || "File"), "Shared with you.", true);
      const meta = document.createElement("div");
      meta.className = "file-meta";
      const a = document.createElement("span");
      a.textContent = kind(r.header.type) + " · " + size(r.content.length);
      meta.appendChild(a);
      const btn = document.createElement("button");
      btn.className = "primary";
      btn.textContent = "Download file";
      btn.addEventListener("click", function () {
        const url = URL.createObjectURL(new Blob([r.content], { type: "application/octet-stream" }));
        const l = document.createElement("a");
        l.href = url;
        l.download = String(r.header.name || "file").replace(/[\\/]/g, "_");
        document.body.appendChild(l);
        l.click();
        l.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        done.textContent = "Downloaded. Look in your Downloads folder.";
      });
      const done = document.createElement("p");
      done.className = "download-note";
      done.setAttribute("role", "status");
      $("extra").append(meta, btn, done);
    }
    main();
  })();
}
