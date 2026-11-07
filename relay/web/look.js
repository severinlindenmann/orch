// Workspace look (contracts/look.md): badge (icon or letter, colour) and the admin picker.
// Source copy: publish/web/look.js; scripts/gen_look_web.py copies it to relay/web/look.js. Needs look-data.js first.
// Never builds markup from wire strings: drawings come from the bundled list by id, text goes in with textContent.
"use strict";
(function () {
  const D = window.ORCH_LOOK_DATA;
  const NS = "http://www.w3.org/2000/svg";
  const colorById = {};
  D.colors.forEach((c) => (colorById[c.id] = c));
  const iconById = {};
  D.icons.forEach((i) => (iconById[i.id] = i));

  function clean(name) {
    return String(name || "").normalize("NFC").replace(/^\p{White_Space}+|\p{White_Space}+$/gu, "");
  }
  function djb2(name) {
    let h = 5381;
    for (const b of new TextEncoder().encode(clean(name))) h = (Math.imul(h, 33) + b) >>> 0;
    return h;
  }
  function defaultColor(name) {
    return D.colors[djb2(name) % D.colors.length].id;
  }
  function letter(name) {
    for (const ch of clean(name)) {
      if (/^[\p{L}\p{N}]$/u.test(ch)) {
        const up = ch.toUpperCase();
        return [...up].length === 1 ? up : ch;
      }
    }
    return "?";
  }
  function hexRgb(h) {
    return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  function mix(fg, bg, a) {
    const f = hexRgb(fg), b = hexRgb(bg);
    return "rgb(" + f.map((v, i) => Math.round(v * a + b[i] * (1 - a))).join(",") + ")";
  }
  function isLight(theme) {
    return theme ? theme === "light" : !!(window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches);
  }
  // Unknown icon id or colour token: letter / Automatic colour (never blank, never written back).
  function resolve(name, icon, color) {
    return {
      icon: icon && iconById[icon] ? icon : null,
      color: color && colorById[color] ? color : defaultColor(name),
      letter: letter(name),
    };
  }
  function drawing(id, size) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    for (const [tag, attrs] of D.drawings[id] || []) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      svg.appendChild(e);
    }
    return svg;
  }
  // A rounded square: colour tone at 18 % (dark) / 14 % (light) over the surface, icon or letter in the tone.
  function badge(name, icon, color, size, theme) {
    size = size || 32;
    const r = resolve(name, icon, color);
    const light = isLight(theme);
    const tone = colorById[r.color][light ? "light" : "dark"];
    const t = light ? D.badge.tint_light : D.badge.tint_dark;
    const el = document.createElement("span");
    el.className = "look-badge";
    el.style.cssText = "";
    el.style.display = "inline-flex";
    el.style.alignItems = "center";
    el.style.justifyContent = "center";
    el.style.flex = "none";
    el.style.width = el.style.height = size + "px";
    el.style.borderRadius = Math.round(size * 0.28) + "px";
    el.style.background = mix(tone, t.surface, t.alpha);
    el.style.color = tone;
    if (r.icon) {
      el.appendChild(drawing(r.icon, Math.round(size * (size <= 20 ? 0.75 : 0.52))));
    } else {
      const s = document.createElement("span");
      s.textContent = r.letter;
      s.style.fontWeight = "700";
      s.style.fontSize = Math.round(size * 0.46) + "px";
      s.style.lineHeight = "1";
      el.appendChild(s);
    }
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", clean(name) || "Workspace");
    return el;
  }

  // Picker B (small): category chips + search, icon grid, 12 colours + Automatic. Calls onChange({icon, color}) per click.
  function picker(opts) {
    const st = { icon: opts.icon || null, color: opts.color || null, cat: "all", q: "" };
    const root = document.createElement("div");
    root.className = "look-picker";
    const bar = document.createElement("div");
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "Search icons";
    search.setAttribute("aria-label", "Search icons");
    const grid = document.createElement("div");
    grid.setAttribute("role", "listbox");
    grid.setAttribute("aria-label", "Icons");
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = "repeat(auto-fill,minmax(40px,1fr))";
    grid.style.gap = "6px";
    grid.style.maxHeight = "220px";
    grid.style.overflow = "auto";
    const colors = document.createElement("div");
    colors.style.display = "flex";
    colors.style.flexWrap = "wrap";
    colors.style.gap = "6px";
    const preview = document.createElement("div");
    function chip(label, on, fn) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.addEventListener("click", fn);
      return b;
    }
    function emit() {
      opts.onChange && opts.onChange({ icon: st.icon, color: st.color });
      paint();
    }
    function paint() {
      bar.replaceChildren(
        chip("All", st.cat === "all", () => ((st.cat = "all"), paint())),
        ...D.categories.map((c) => chip(c.label, st.cat === c.id, () => ((st.cat = c.id), paint())))
      );
      bar.appendChild(search);
      const q = st.q.toLowerCase();
      grid.replaceChildren(
        ...D.icons
          .filter((i) => (st.cat === "all" || i.category === st.cat) && (!q || (i.label + " " + i.keywords.join(" ")).toLowerCase().includes(q)))
          .map((i) => {
            const b = document.createElement("button");
            b.type = "button";
            b.title = i.label;
            b.setAttribute("aria-label", i.label);
            b.setAttribute("role", "option");
            b.setAttribute("aria-selected", st.icon === i.id ? "true" : "false");
            b.appendChild(badge(opts.name, i.id, st.color, 32));
            b.addEventListener("click", () => ((st.icon = i.id), emit()));
            return b;
          })
      );
      colors.replaceChildren(
        chip("Automatic", st.color === null, () => ((st.color = null), emit())),
        ...D.colors.map((c) => {
          const b = chip(c.label, st.color === c.id, () => ((st.color = c.id), emit()));
          return b;
        })
      );
      const none = chip("Letter only", st.icon === null, () => ((st.icon = null), emit()));
      preview.replaceChildren(badge(opts.name, st.icon, st.color, 48), none);
    }
    search.addEventListener("input", () => ((st.q = search.value), paint()));
    root.append(preview, bar, grid, colors);
    paint();
    return root;
  }

  // File page header: the sharing workspace's badge and name above the file, unless the owner switched it off.
  // The name goes in with textContent only; nothing from the response becomes markup.
  async function fileHeader(id) {
    try {
      const r = await fetch("/f/" + encodeURIComponent(id) + "/meta", { cache: "no-store", referrer: "no-referrer" });
      if (!r.ok) return;
      const w = (await r.json()).workspace;
      const host = document.querySelector(".public-brand");
      if (!w || !host || typeof w.name !== "string") return;
      const box = document.createElement("span");
      box.className = "look-ws";
      box.style.display = "inline-flex";
      box.style.alignItems = "center";
      box.style.gap = "8px";
      const nm = document.createElement("span");
      nm.textContent = w.name;
      box.append(badge(w.name, w.icon, w.color, 24), nm);
      host.appendChild(box);
    } catch (e) {
      /* the header is decoration */
    }
  }

  window.OrchLook = { fileHeader, defaultColor, letter, resolve, badge, picker, clean, djb2, data: D };
  if (typeof module !== "undefined") module.exports = window.OrchLook;
})();
