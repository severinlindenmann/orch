// Browser side of /f/<id>: fetch the encrypted blob, decrypt with WebCrypto (crypto.md, OPF1), show a preview
// by file type (docs/publish.md "Previews") and offer the download.
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

// ---- folder bundle (crypto.md "Folder bundle") ----------------------------------------------------

const BUNDLE_TYPE = "application/vnd.orch.bundle";
const BROKEN = "broken file";

// bytes: Uint8Array. Returns {entry, files: [{path, type, bytes}]}. Throws Error(BROKEN).
function unbundle(bytes) {
  try {
    if (bytes.length < 4) throw new Error("short");
    const m = new DataView(bytes.buffer, bytes.byteOffset, 4).getUint32(0, false);
    if (m < 1 || m > 1048576 || 4 + m > bytes.length) throw new Error("index length");
    const idx = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(4, 4 + m)));
    if (!idx || idx.v !== 1 || typeof idx.entry !== "string" || !/\.html?$/i.test(idx.entry) || !Array.isArray(idx.files)) throw new Error("index");
    if (idx.files.length < 1 || idx.files.length > 2000) throw new Error("count");
    const seen = new Set();
    const files = [];
    let pos = 4 + m;
    for (const f of idx.files) {
      const p = f && f.path;
      if (typeof p !== "string" || p.length < 1 || p.length > 255 || /[\\\0]/.test(p)) throw new Error("path");
      if (p.split("/").some((s) => s === "" || s === "." || s === "..")) throw new Error("segment");
      if (seen.has(p) || !Number.isInteger(f.size) || f.size < 0) throw new Error("dup or size");
      seen.add(p);
      files.push({ path: p, type: String(f.type || ""), bytes: bytes.subarray(pos, pos + f.size) });
      pos += f.size;
    }
    if (pos !== bytes.length || !seen.has(idx.entry)) throw new Error("sizes");
    return { entry: idx.entry, files };
  } catch (e) {
    throw new Error(BROKEN);
  }
}

// ---- what to show ---------------------------------------------------------------------------------

const EXT = {
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", avif: "image", bmp: "image", ico: "image",
  svg: "svg", pdf: "pdf",
  mp4: "video", webm: "video", mov: "video", m4v: "video",
  mp3: "audio", m4a: "audio", wav: "audio", ogg: "audio", oga: "audio", flac: "audio", aac: "audio", opus: "audio",
  md: "markdown", markdown: "markdown", csv: "csv", tsv: "tsv", json: "json", geojson: "json",
  html: "html", htm: "html",
};
const CODE = ("txt text log py js mjs cjs ts tsx jsx yaml yml toml sh bash zsh fish ps1 swift rs go sql css scss xml " +
  "ini cfg conf env properties c h cc cpp hpp java kt rb php lua r pl diff patch gradle tf vue svelte").split(" ");
const MIME = {
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp", avif: "image/avif",
  bmp: "image/bmp", ico: "image/x-icon", svg: "image/svg+xml", pdf: "application/pdf",
  mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime", m4v: "video/mp4",
  mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", ogg: "audio/ogg", oga: "audio/ogg", flac: "audio/flac",
  aac: "audio/aac", opus: "audio/ogg",
};

function extOf(name) {
  const n = String(name || "").toLowerCase().split("/").pop();
  if (/^(dockerfile|makefile|readme|license)$/.test(n) || /^\.env(\..*)?$/.test(n)) return "txt";
  const i = n.lastIndexOf(".");
  return i > 0 ? n.slice(i + 1) : "";
}

// Returns {kind, ext}; kind is one of image svg pdf video audio markdown csv tsv json code html bundle, or "" (card only).
function previewKind(name, type) {
  if (type === BUNDLE_TYPE) return { kind: "bundle", ext: "" };
  const ext = extOf(name);
  if (EXT[ext]) return { kind: EXT[ext], ext };
  if (CODE.indexOf(ext) >= 0) return { kind: "code", ext };
  if (!ext && /^text\/plain\b/.test(String(type || ""))) return { kind: "code", ext: "txt" };
  return { kind: "", ext };
}

// ---- tiny renderers: every byte of the file is escaped; only our own tags are produced ----------

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const KW = {
  py: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self",
  js: "async await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield interface type enum implements readonly",
  sh: "if then else elif fi for in do done while until case esac function return local export echo set unset exit",
  rs: "as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false",
  swift: "class let var func if else guard return import struct enum case switch for in while protocol extension self true false nil init public private static try catch throw throws async await",
  sql: "select from where and or not insert into values update set delete create table index view drop alter join left right inner outer on group by order having limit as null is in like distinct union primary key",
  yaml: "true false null yes no on off",
  json: "true false null",
};
const FAMILY = {
  py: "py", r: "py", rb: "py", pl: "py", js: "js", mjs: "js", cjs: "js", ts: "js", tsx: "js", jsx: "js", vue: "js", svelte: "js",
  java: "js", kt: "js", c: "js", h: "js", cc: "js", cpp: "js", hpp: "js", php: "js", gradle: "js", css: "css", scss: "css",
  sh: "sh", bash: "sh", zsh: "sh", fish: "sh", ps1: "sh", env: "sh", tf: "sh",
  rs: "rs", go: "go", swift: "swift", sql: "sql", lua: "sql", yaml: "yaml", yml: "yaml", toml: "yaml", ini: "yaml",
  cfg: "yaml", conf: "yaml", properties: "yaml", json: "json", xml: "xml", html: "xml",
};

// Light syntax highlighting: comments, strings, numbers, keywords. Returns HTML.
function highlight(text, ext) {
  const fam = FAMILY[ext] || "";
  if (!fam) return esc(text);
  const comment = {
    py: "#.*", sh: "#.*", yaml: "[#;].*", sql: "--.*", css: "\\/\\*[\\s\\S]*?\\*\\/", xml: "<!--[\\s\\S]*?-->",
    json: "(?!)",
  }[fam] || "\\/\\/.*|\\/\\*[\\s\\S]*?\\*\\/";
  const str = fam === "py" ? "\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'"
    : fam === "js" ? "`(?:\\\\.|[^`\\\\])*`|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'"
    : "\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'";
  const words = (KW[fam] || "").split(" ").filter(Boolean);
  const kw = words.length ? "\\b(?:" + words.join("|") + ")\\b" : "(?!)";
  const re = new RegExp("(" + comment + ")|(" + str + ")|(\\b\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)|(" + kw + ")", fam === "sql" ? "gi" : "g");
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m[0] === "") { re.lastIndex++; continue; }
    out += esc(text.slice(last, m.index));
    let cls = m[1] ? "tk-c" : m[2] ? "tk-s" : m[3] ? "tk-n" : "tk-k";
    if (m[2] && fam === "json" && /^\s*:/.test(text.slice(re.lastIndex))) cls = "tk-p";
    out += '<span class="' + cls + '">' + esc(m[0]) + "</span>";
    last = re.lastIndex;
  }
  return out + esc(text.slice(last));
}

function mdInline(s) {
  const codes = [];
  // \u0000 and \u0001 mark placeholders below: drop them from the input so text can never forge one
  let t = String(s).replace(/[\u0000\u0001]/g, "").replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
  t = esc(t);
  // images and links become placeholders too, so emphasis never runs inside their attributes
  const tags = [];
  const keep = (html) => { tags.push(html); return "\u0001" + (tags.length - 1) + "\u0001"; };
  // url and alt: no placeholder may sit inside an attribute; both are already HTML-escaped (esc above)
  t = t.replace(/!\[([^\]\u0000\u0001]*)\]\(([^)\s\u0000\u0001]+)[^)]*\)/g, (_, alt, url) =>
    /^https:\/\//i.test(url) ? keep('<img src="' + url + '" alt="' + alt + '" loading="lazy" referrerpolicy="no-referrer">') : "[" + (alt || "image") + "]");
  t = t.replace(/\[([^\]]+)\]\(([^)\s\u0000\u0001]+)[^)]*\)/g, (all, label, url) =>
    /^(https?:|mailto:)/i.test(url) ? keep('<a href="' + url + '" target="_blank" rel="noopener noreferrer nofollow">') + label + keep("</a>") : label);
  t = t.replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => "<strong>" + (a || b) + "</strong>");
  t = t.replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\*)/g, "$1<em>$2</em>").replace(/(^|\W)_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  t = t.replace(/\u0001(\d+)\u0001/g, (m, i) => (+i < tags.length ? tags[+i] : ""));
  return t.replace(/\u0000(\d+)\u0000/g, (m, i) => (+i < codes.length ? "<code>" + esc(codes[+i]) + "</code>" : ""));
}

// Markdown subset to HTML: headings, paragraphs, lists, task lists, quotes, code fences, tables, rules.
// Raw HTML in the source is shown as text, never run.
function renderMarkdown(src) {
  const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  const isBlock = (l) => /^(#{1,6}\s|```|~~~|>|\s*([-*+]|\d+[.)])\s|\s*([-*_])(\s*\3){2,}\s*$)/.test(l);
  const isSep = (l) => /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(l) && l.indexOf("-") >= 0;
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => mdInline(c.trim()));
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    let m;
    if ((m = /^\s*(```|~~~)\s*([\w+-]*)/.exec(l))) {
      const fence = m[1];
      const body = [];
      i++;
      while (i < lines.length && lines[i].trim().indexOf(fence) !== 0) body.push(lines[i++]);
      i++;
      out.push('<pre class="code"><code>' + highlight(body.join("\n"), (m[2] || "").toLowerCase()) + "</code></pre>");
    } else if ((m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(l))) {
      out.push("<h" + m[1].length + ">" + mdInline(m[2]) + "</h" + m[1].length + ">");
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) {
      out.push("<hr>");
      i++;
    } else if (/^\s*>/.test(l)) {
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push("<blockquote>" + renderMarkdown(q.join("\n")) + "</blockquote>");
    } else if ((m = /^\s*([-*+]|\d+[.)])\s+/.exec(l))) {
      const ordered = /\d/.test(m[1]);
      const items = [];
      while (i < lines.length && lines[i].trim() !== "") {
        const im = /^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (im) items.push(im[2]);
        else if (items.length && !isBlock(lines[i])) items[items.length - 1] += " " + lines[i].trim();
        else break;
        i++;
      }
      const li = items.map((t) => {
        const tm = /^\[([ xX])\]\s+(.*)$/.exec(t);
        return tm ? '<li class="task">' + (tm[1] === " " ? "☐ " : "☑ ") + mdInline(tm[2]) + "</li>" : "<li>" + mdInline(t) + "</li>";
      });
      out.push((ordered ? "<ol>" : "<ul>") + li.join("") + (ordered ? "</ol>" : "</ul>"));
    } else if (l.indexOf("|") >= 0 && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(l);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].indexOf("|") >= 0 && lines[i].trim() !== "") rows.push(cells(lines[i++]));
      out.push('<div class="table-wrap"><table><thead><tr>' + head.map((c) => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => "<td>" + c + "</td>").join("") + "</tr>").join("") + "</tbody></table></div>");
    } else if (l.trim() === "") {
      i++;
    } else {
      const p = [];
      while (i < lines.length && lines[i].trim() !== "" && !(p.length && isBlock(lines[i]))) p.push(lines[i++].trim());
      out.push("<p>" + mdInline(p.join(" ")) + "</p>");
    }
  }
  return out.join("\n");
}

// CSV/TSV to rows (quotes, doubled quotes, newlines in quotes). Stops after maxRows rows.
function parseCsv(text, sep, maxRows) {
  const rows = [];
  let row = [];
  let cell = "";
  let q = false;
  let i = 0;
  for (; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"' && cell === "") q = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
      if (rows.length >= maxRows) return { rows, more: i + 1 < text.length };
    } else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return { rows, more: false };
}

// A zip with stored (not compressed) entries, for "Download files" of a folder bundle.
function crc32(b) {
  let c;
  let crc = -1;
  for (let i = 0; i < b.length; i++) {
    c = (crc ^ b[i]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ -1) >>> 0;
}
function zipStore(files) {
  const enc = new TextEncoder();
  const parts = [];
  const central = [];
  let off = 0;
  for (const f of files) {
    const name = enc.encode(f.path);
    const crc = crc32(f.bytes);
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true);
    h.setUint32(14, crc, true); h.setUint32(18, f.bytes.length, true); h.setUint32(22, f.bytes.length, true);
    h.setUint16(26, name.length, true);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true);
    c.setUint32(16, crc, true); c.setUint32(20, f.bytes.length, true); c.setUint32(24, f.bytes.length, true);
    c.setUint16(28, name.length, true); c.setUint32(42, off, true);
    parts.push(new Uint8Array(h.buffer), name, f.bytes);
    central.push(new Uint8Array(c.buffer), name);
    off += 30 + name.length + f.bytes.length;
  }
  const size = central.reduce((n, p) => n + p.length, 0);
  const e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true);
  e.setUint32(12, size, true); e.setUint32(16, off, true);
  return new Blob(parts.concat(central, [new Uint8Array(e.buffer)]), { type: "application/zip" });
}

// The sender's note (crypto.md): optional, text only, one line, at most 280 characters. Anything else is ignored.
const NOTE_MAX = 280;
function cleanNote(header) {
  const n = header && header.note;
  if (typeof n !== "string") return "";
  return Array.from(n.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim()).slice(0, NOTE_MAX).join("");
}

// "until Thu 19 Nov" in the viewer's own time zone (locale and tz are for tests); "" without an expiry.
function expiryLabel(iso, locale, tz) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const o = { weekday: "short", day: "numeric", month: "short" };
  if (tz) o.timeZone = tz;
  return "until " + d.toLocaleDateString(locale, o).replace(",", "");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { decryptBlob, b64urlToBytes, FAIL, unbundle, BROKEN, BUNDLE_TYPE, previewKind, highlight, renderMarkdown, parseCsv, esc, crc32, cleanNote, expiryLabel, NOTE_MAX };
}

if (typeof document !== "undefined") {
  (function () {
    const $ = (id) => document.getElementById(id);
    const I = (d) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + "</svg>";
    const ICONS = {
      link: I('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
      clock: I('<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>'),
      file: I('<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13h5M10 17h5"/>'),
      lock: I('<rect x="6" y="10" width="12" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>'),
      down: I('<path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/>'),
      chain: I('<path d="m10 14 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>'),
      full: I('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>'),
      copy: I('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>'),
    };
    const TEXT_CAP = 1048576;
    const CSV_ROWS = 500;
    const LANG = { py: "Python", js: "JavaScript", mjs: "JavaScript", cjs: "JavaScript", ts: "TypeScript", tsx: "TypeScript",
      jsx: "JavaScript", json: "JSON", geojson: "JSON", yaml: "YAML", yml: "YAML", toml: "TOML", sh: "Shell", bash: "Shell",
      zsh: "Shell", swift: "Swift", rs: "Rust", go: "Go", sql: "SQL", css: "CSS", scss: "SCSS", xml: "XML", ini: "INI",
      env: "Settings", txt: "Text", log: "Log", md: "Markdown", markdown: "Markdown", rb: "Ruby", java: "Java", kt: "Kotlin",
      c: "C", h: "C", cpp: "C++", php: "PHP", lua: "Lua", r: "R" };
    const OTHER = { doc: "Word file", docx: "Word file", xls: "Excel file", xlsx: "Excel file", ppt: "PowerPoint file",
      pptx: "PowerPoint file", key: "Keynote file", pages: "Pages file", numbers: "Numbers file", zip: "ZIP archive",
      gz: "Archive", tgz: "Archive", tar: "Archive", "7z": "Archive", rar: "Archive", dmg: "Disk image", exe: "Program", pkg: "Installer" };
    let slow;

    function show(icon, title, msg) {
      $("icon").innerHTML = ICONS[icon];
      $("title").textContent = title;
      $("msg").textContent = msg;
      $("extra").textContent = "";
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
    function size(n) {
      return n < 1024 ? n + (n === 1 ? " byte" : " bytes") : n < 1048576 ? (n / 1024).toFixed(1).replace(/\.0$/, "") + " KB" : (n / 1048576).toFixed(1).replace(/\.0$/, "") + " MB";
    }
    function el(tag, cls, text) {
      const e = document.createElement(tag);
      if (cls) e.className = cls;
      if (text !== undefined) e.textContent = text;
      return e;
    }
    function button(icon, text, cls) {
      const b = el("button", cls || "");
      b.type = "button";
      b.innerHTML = ICONS[icon];
      b.appendChild(el("span", "lbl", text));
      return b;
    }
    function blobUrl(bytes, type) {
      return URL.createObjectURL(new Blob([bytes], { type }));
    }
    function decodeText(bytes) {
      const cut = bytes.length > TEXT_CAP;
      return { text: new TextDecoder("utf-8").decode(cut ? bytes.subarray(0, TEXT_CAP) : bytes), cut };
    }
    function copyButton(label, text, done) {
      const b = button(label === "Copy link" ? "chain" : "copy", label, "small");
      b.addEventListener("click", async function () {
        try {
          await navigator.clipboard.writeText(text());
          b.lastChild.textContent = "Copied";
        } catch (e) {
          b.lastChild.textContent = "Copy didn’t work";
        }
        setTimeout(function () { b.lastChild.textContent = label; }, 2000);
        if (done) done();
      });
      return b;
    }
    // A bar above or below the preview: text on the left (name, dim detail), buttons on the right.
    function bar(cls, name, detail, buttons) {
      const b = el("div", "viewer-bar " + cls);
      const t = el("span", "bar-text");
      if (name) t.appendChild(el("span", "bar-name", name));
      if (detail) t.appendChild(el("span", "dim", (name ? " · " : "") + detail));
      b.appendChild(t);
      const right = el("div", "bar-actions");
      (buttons || []).forEach((x) => right.appendChild(x));
      b.appendChild(right);
      return b;
    }

    // HTML and folder pages run in a sandboxed frame (opaque origin: no access to this page, the #k= key,
    // cookies or storage). It gets the decrypted files by postMessage; see web/frame.js.
    function htmlFrame(pkg, name) {
      const f = document.createElement("iframe");
      f.setAttribute("sandbox", "allow-scripts");
      f.setAttribute("referrerpolicy", "no-referrer");
      f.setAttribute("title", "Preview of " + name);
      f.src = "/_/frame.html";
      window.addEventListener("message", function onReady(e) {
        if (e.source !== f.contentWindow || !e.data || e.data.orchFrame !== "ready") return;
        window.removeEventListener("message", onReady);
        f.contentWindow.postMessage({ entry: pkg.entry, files: pkg.files.map((x) => ({ path: x.path, type: x.type, bytes: x.bytes.slice() })) }, "*");
      });
      return f;
    }
    // Full screen of the viewer: the browser's own full screen where there is one (not on iPhone), else a fixed layer.
    function fullControl(pane) {
      const b = button("full", "Full screen", "pf-btn icon");
      b.id = "fullscreen";
      b.title = "Full screen (F)";
      b.setAttribute("aria-pressed", "false");
      b.setAttribute("aria-label", "Full screen");
      const mark = function (on) {
        pane.classList.toggle("full", on);
        document.body.classList.toggle("no-scroll", on);
        b.setAttribute("aria-pressed", String(on));
        b.setAttribute("aria-label", on ? "Leave full screen" : "Full screen");
      };
      const set = async function (on) {
        if (on) {
          try { await pane.requestFullscreen(); } catch (e) { /* no element full screen here: the fixed layer is enough */ }
          mark(true);
        } else {
          if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (e) { /* already out */ } }
          mark(false);
        }
      };
      document.addEventListener("fullscreenchange", function () { if (!document.fullscreenElement) mark(false); });
      b.addEventListener("click", function () { set(!pane.classList.contains("full")); });
      document.addEventListener("keydown", function (e) {
        if (e.metaKey || e.ctrlKey || e.altKey || (e.target.closest && e.target.closest("input,textarea,select"))) return;
        if (e.key === "Escape" && pane.classList.contains("full")) { set(false); b.focus(); }
        else if (e.key === "f" || e.key === "F") set(!pane.classList.contains("full"));
      });
      return b;
    }
    function codeView(text, ext) {
      const lines = text.split("\n");
      if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
      const wrap = el("div", "code-wrap");
      const gutter = el("pre", "gutter", lines.map((_, i) => i + 1 + ".").join("\n"));
      gutter.setAttribute("aria-hidden", "true");
      const pre = el("pre", "code");
      const code = el("code");
      code.innerHTML = highlight(lines.join("\n"), ext);
      pre.appendChild(code);
      wrap.append(gutter, pre);
      return { node: wrap, lines: lines.length };
    }

    // Builds the viewer. Returns the pane, or null when this kind has no preview. info(text) fills the small
    // detail at the right of the footer (pages, pixels, lines ...).
    function preview(r, k, name, info) {
      const c = r.content;
      const pane = el("section", "pf-viewer");
      pane.id = "preview";
      pane.setAttribute("aria-label", "Preview of " + name);
      if (k.kind === "image" || k.kind === "svg") {
        const box = el("div", "media-box");
        const img = el("img");
        img.alt = name;
        img.src = blobUrl(c, MIME[k.ext] || "image/png");
        box.appendChild(img);
        img.addEventListener("load", function () {
          info(k.kind === "svg" ? "SVG image" : img.naturalWidth + " × " + img.naturalHeight);
        });
        pane.classList.add("media");
        pane.append(box);
      } else if (k.kind === "pdf" && String.fromCharCode.apply(null, c.subarray(0, 5)) === "%PDF-") { // else: download card
        const f = document.createElement("iframe");
        f.title = name;
        f.src = blobUrl(c, "application/pdf");
        const head = new TextDecoder("latin1").decode(c.subarray(0, Math.min(c.length, 4194304)));
        const pages = (head.match(/\/Type\s*\/Page(?![s\w])/g) || []).length;
        if (pages) info(pages + (pages === 1 ? " page" : " pages"));
        pane.classList.add("doc");
        pane.append(f);
      } else if (k.kind === "video" || k.kind === "audio") {
        const v = el(k.kind);
        v.controls = true;
        v.preload = "metadata";
        v.src = blobUrl(c, MIME[k.ext]);
        v.addEventListener("loadedmetadata", function () {
          const s = Math.round(v.duration);
          if (isFinite(s)) info(Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"));
        });
        const box = el("div", "media-box");
        box.appendChild(v);
        pane.classList.add(k.kind === "video" ? "media" : "sound");
        pane.append(box);
      } else if (k.kind === "markdown") {
        const t = decodeText(c);
        const d = el("article", "md");
        d.innerHTML = renderMarkdown(t.text);
        pane.append(bar("head", "", "Markdown", [copyButton("Copy", () => t.text)]), d);
        if (t.cut) info("first 1 MB");
      } else if (k.kind === "csv" || k.kind === "tsv") {
        const t = decodeText(c);
        const p = parseCsv(t.text, k.kind === "tsv" ? "\t" : ",", CSV_ROWS + 1);
        const rows = p.rows;
        const wrap = el("div", "table-wrap");
        const table = el("table", "sheet");
        const cols = rows.reduce((n, row) => Math.max(n, row.length), 0);
        rows.forEach((row, i) => {
          const tr = el("tr");
          tr.appendChild(el(i === 0 ? "th" : "td", "rownum", i === 0 ? "#" : String(i)));
          row.forEach((cell) => tr.appendChild(el(i === 0 ? "th" : "td", "", cell)));
          table.appendChild(tr);
        });
        wrap.appendChild(table);
        const n = Math.max(rows.length - 1, 0);
        const more = p.more || t.cut;
        info((more ? "first " + n + " rows" : n + (n === 1 ? " row" : " rows")) + " · " + cols + (cols === 1 ? " column" : " columns"));
        pane.append(wrap);
      } else if (k.kind === "json" || k.kind === "code") {
        const t = decodeText(c);
        let text = t.text;
        if (k.kind === "json" && !t.cut) {
          try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (e) { /* show as it is */ }
        }
        const v = codeView(text, k.ext);
        info((t.cut ? "first " : "") + v.lines + (v.lines === 1 ? " line" : " lines"));
        pane.append(bar("head", "", LANG[k.ext] || "Text", [copyButton("Copy", () => text)]), v.node);
      } else if (k.kind === "html" || k.kind === "bundle") {
        const pkg = k.kind === "html" ? { entry: "index.html", files: [{ path: "index.html", type: "text/html", bytes: c }] } : r.bundle;
        const chip = el("span", "chip", k.kind === "html" ? "Web page" : "Website · " + pkg.files.length + (pkg.files.length === 1 ? " file" : " files"));
        const pages = pkg.files.map((x) => x.path).filter((p) => /\.html?$/i.test(p));
        const tools = [chip];
        let frame = htmlFrame(pkg, name);
        if (pages.length > 1) { // several pages: a small switcher, the first page by name (or index.html) is shown
          const pick = el("select", "page-pick");
          pick.id = "page-pick";
          pick.setAttribute("aria-label", "Page");
          pages.forEach((p) => {
            const o = el("option", "", p);
            o.value = p;
            o.selected = p === pkg.entry;
            pick.appendChild(o);
          });
          pick.addEventListener("change", function () {
            const next = htmlFrame({ entry: pick.value, files: pkg.files }, name);
            frame.replaceWith(next);
            frame = next;
          });
          tools.unshift(pick);
        }
        const head = bar("head safe", "", "", tools);
        const t = head.querySelector(".bar-text");
        t.innerHTML = ICONS.lock;
        t.appendChild(document.createTextNode("Runs in a safe frame"));
        pane.classList.add("doc");
        pane.append(head, frame);
      } else {
        return null;
      }
      return pane;
    }

    function download(r, status) {
      const name = String(r.header.name || "file").replace(/[\\/]/g, "_");
      const isBundle = !!r.bundle;
      const url = URL.createObjectURL(isBundle ? zipStore(r.bundle.files) : new Blob([r.content], { type: "application/octet-stream" }));
      const l = document.createElement("a");
      l.href = url;
      l.download = isBundle ? name + ".zip" : name;
      document.body.appendChild(l);
      l.click();
      l.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      status.textContent = "Downloaded. Look in your Downloads folder.";
    }

    // The page (draft-v3 public-file): one slim header line, the note on one small line, the viewer filling the
    // rest of the height, a tiny footer. No inline styles or scripts (CSP).
    function render(r, k, expires) {
      const name = String(r.header.name || "File");
      const status = el("span", "", "Only people with this link can open the file.");
      status.id = "file-status";
      status.setAttribute("role", "status");
      const infoEl = el("span", "pf-info");
      const dl = button("down", r.bundle ? "Download files" : "Download", "pf-btn");
      dl.id = "download";
      dl.setAttribute("aria-label", r.bundle ? "Download files" : "Download");
      dl.addEventListener("click", function () { download(r, status); });
      const copy = copyButton("Copy link", () => location.href);
      copy.classList.add("pf-btn");
      copy.id = "copy-link";
      copy.setAttribute("aria-label", "Copy link");

      const page = el("div", "pf");
      const head = el("header", "pf-head");
      const logo = el("a", "pf-logo");
      logo.href = "/";
      logo.setAttribute("aria-label", "orch");
      logo.appendChild(document.querySelector(".public-brand .brand svg").cloneNode(true));
      const title = el("div", "pf-title");
      title.append(el("h1", "", name), el("span", "pf-meta", [size(r.content.length), expiryLabel(expires)].filter(Boolean).join(" · ")));
      const actions = el("div", "pf-actions");
      actions.append(dl, copy);
      head.append(logo, title, actions);
      page.appendChild(head);

      const note = cleanNote(r.header);
      if (note) {
        const d = el("details", "pf-note");
        d.appendChild(el("summary", "", note));
        page.appendChild(d);
      }

      const pane = preview(r, k, name, function (t) { infoEl.textContent = t; });
      if (pane) {
        actions.appendChild(fullControl(pane));
        page.appendChild(pane);
      } else {
        const ext = (name.split(".").pop() || "").toLowerCase();
        const what = OTHER[ext] || (name.indexOf(".") > 0 ? ext.toUpperCase() + " file" : "File");
        const box = el("section", "pf-viewer pf-other");
        const card = el("div", "card other-card");
        const ic = el("div", "file-icon");
        ic.innerHTML = ICONS.file;
        const big = button("down", "Download file", "primary");
        big.addEventListener("click", function () { download(r, status); });
        card.append(ic, el("h2", "", name), el("p", "", what + " · " + size(r.content.length)), el("p", "no-preview", "No preview for " + (OTHER[ext] ? what.replace(/ file$/, "") + " files" : "this kind of file") + " yet"), big);
        box.appendChild(card);
        page.appendChild(box);
      }
      page.appendChild(el("footer", "pf-foot")).append(status, infoEl);
      document.title = name + " · orch";
      document.body.className = "pf-body";
      document.querySelector(".shell").replaceWith(page);
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
      if (globalThis.OrchLook) globalThis.OrchLook.fileHeader(id);
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
      clearTimeout(slow);
      let k = previewKind(r.header.name, r.header.type);
      if (k.kind === "bundle") {
        try {
          r.bundle = unbundle(r.content);
        } catch (e) {
          k = { kind: "", ext: "" };
        }
      }
      render(r, k, res.headers.get("x-orch-expires-at"));
    }
    main();
  })();
}
