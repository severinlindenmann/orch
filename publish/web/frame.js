// /_/frame.html: runs inside <iframe sandbox="allow-scripts"> on the file page (opaque origin, so it cannot
// reach the parent page, its #k= key, cookies or storage). The parent posts the decrypted files once:
// {entry, files: [{path, type, bytes}]}. Relative URLs in the page, its CSS and fetch()/XHR calls are
// served from those files via blob: URLs. Links to other .html files of the folder open them in place.
"use strict";
(function () {
  if (window.parent === window) return;
  const TYPES = {
    html: "text/html", htm: "text/html", css: "text/css", js: "text/javascript", mjs: "text/javascript",
    json: "application/json", svg: "image/svg+xml", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
    gif: "image/gif", webp: "image/webp", avif: "image/avif", ico: "image/x-icon", woff: "font/woff",
    woff2: "font/woff2", ttf: "font/ttf", otf: "font/otf", mp4: "video/mp4", webm: "video/webm", mp3: "audio/mpeg",
    wav: "audio/wav", ogg: "audio/ogg", txt: "text/plain", csv: "text/csv", xml: "application/xml",
  };
  const files = Object.create(null);
  const urls = Object.create(null);
  let done = false;

  const dir = (p) => p.slice(0, p.lastIndexOf("/") + 1);
  const ext = (p) => p.slice(p.lastIndexOf(".") + 1).toLowerCase();

  // A reference from the file `base` to a file of the folder, or null (other site, data:, missing).
  function resolve(base, ref) {
    if (!ref || /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(ref)) return null;
    ref = ref.split("#")[0].split("?")[0];
    const out = [];
    (ref.charAt(0) === "/" ? ref.slice(1) : dir(base) + ref).split("/").forEach(function (s) {
      if (s === "..") out.pop();
      else if (s !== "." && s !== "") out.push(s);
    });
    let p;
    try { p = decodeURIComponent(out.join("/")); } catch (e) { return null; }
    return p in files ? p : null;
  }
  function css(base, text) {
    return text
      .replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, function (m, q, ref) { const p = resolve(base, ref); return p ? 'url("' + url(p) + '")' : m; })
      .replace(/@import\s+(['"])([^'"]+)\1/g, function (m, q, ref) { const p = resolve(base, ref); return p ? '@import "' + url(p) + '"' : m; });
  }
  function url(p) {
    if (urls[p] === undefined) {
      urls[p] = "";
      const f = files[p];
      const body = ext(p) === "css" ? css(p, new TextDecoder().decode(f.bytes)) : f.bytes;
      urls[p] = URL.createObjectURL(new Blob([body], { type: TYPES[ext(p)] || "application/octet-stream" }));
    }
    return urls[p];
  }

  // fetch() and XHR: the document URL is /_/frame.html, so "data.json" arrives as /_/data.json (or under <base>).
  const here = new URL(location.href);
  function inBundle(u) {
    let abs;
    try { abs = new URL(typeof u === "string" ? u : (u && u.url) || String(u), document.baseURI); } catch (e) { return null; }
    if (abs.protocol !== here.protocol || abs.host !== here.host || abs.pathname.indexOf("/_/") !== 0) return null;
    let p;
    try { p = decodeURIComponent(abs.pathname.slice(3)); } catch (e) { return null; }
    return p in files ? p : null;
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const p = inBundle(input);
    if (!p) return realFetch(input, init);
    return Promise.resolve(new Response(new Blob([files[p].bytes]), { status: 200, headers: { "content-type": TYPES[ext(p)] || "application/octet-stream" } }));
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, u) {
    const p = inBundle(u);
    const args = Array.prototype.slice.call(arguments);
    if (p) args[1] = url(p);
    return open.apply(this, args);
  };

  function rewrite(path) {
    const doc = new DOMParser().parseFromString(new TextDecoder().decode(files[path].bytes), "text/html");
    const attr = function (sel, a) {
      doc.querySelectorAll(sel).forEach(function (n) {
        const p = resolve(path, n.getAttribute(a));
        if (p) n.setAttribute(a, url(p));
      });
    };
    attr("script[src],img[src],source[src],audio[src],video[src],track[src],embed[src],input[src]", "src");
    attr("link[href]", "href");
    attr("video[poster]", "poster");
    attr("object[data]", "data");
    doc.querySelectorAll("img[srcset],source[srcset]").forEach(function (n) {
      n.setAttribute("srcset", n.getAttribute("srcset").split(",").map(function (part) {
        const bits = part.trim().split(/\s+/);
        const p = resolve(path, bits[0]);
        if (p) bits[0] = url(p);
        return bits.join(" ");
      }).join(", "));
    });
    doc.querySelectorAll("style").forEach(function (n) { n.textContent = css(path, n.textContent); });
    doc.querySelectorAll("[style]").forEach(function (n) { n.setAttribute("style", css(path, n.getAttribute("style"))); });
    doc.querySelectorAll("a[href]").forEach(function (n) {
      const p = resolve(path, n.getAttribute("href"));
      if (p && /\.html?$/i.test(p)) n.setAttribute("data-orch-page", p);
    });
    if (dir(path) && !doc.querySelector("base")) {
      const b = doc.createElement("base");
      b.setAttribute("href", "/_/" + dir(path));
      doc.head.insertBefore(b, doc.head.firstChild);
    }
    return "<!doctype html>" + doc.documentElement.outerHTML;
  }
  function render(path) {
    const html = rewrite(path);
    document.open();
    document.write(html);
    document.close();
    document.addEventListener("click", function (e) {
      const a = e.target && e.target.closest ? e.target.closest("a[data-orch-page]") : null;
      if (!a) return;
      e.preventDefault();
      render(a.getAttribute("data-orch-page"));
    });
  }

  window.addEventListener("message", function (e) {
    if (done || e.source !== window.parent || !e.data || !Array.isArray(e.data.files)) return;
    done = true;
    e.data.files.forEach(function (f) {
      if (f && typeof f.path === "string" && f.bytes instanceof Uint8Array) files[f.path] = f;
    });
    if (e.data.entry in files) render(e.data.entry);
  });
  window.parent.postMessage({ orchFrame: "ready" }, "*");
})();
