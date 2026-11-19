/* The helper's real screen in a page (ORCH-744, Focus draft D feature 5), on the terminal bridge (ORCH-743).
   A real terminal: xterm.js 5.5.0 with its WebGL renderer, vendored next to this file (xterm.js,
   xterm-addon-webgl.js, xterm-addon-fit.js; licence and checksums in LICENSE-xterm.txt). The WebGL renderer is loaded
   before the terminal opens, so xterm adds no <style> element and the page's style-src 'self' stays as it is.
   Watching only by default: the terminal takes no input until the person turns on "Let me type"; the server decides
   again (the workspace setting and the sign-in). Select and copy like in the Terminal app; Copy copies the selection
   or the whole screen; a paste with a line end asks once. While typing the helper's screen follows the size of its
   box (onSize); while watching it keeps the helper's own size and scrolls.
     UI.term({label, onInput(data) -> Promise<{ok, status, text}>, onSize({cols, rows}), onTyping(on)})  -> handle
       handle.el                          the element to put in the page
       handle.hello({typing_allowed})     the bridge's first word: may this workspace type at all
       handle.screen({cols, rows, data})  the whole screen (data: base64 terminal bytes), first and after a gap
       handle.write(b64)                  more bytes the program wrote
       handle.size({cols, rows})          the helper's screen has a new size
       handle.end(state)                  the screen closed ('none', 'oneshot', 'notmux', ...)
       handle.show('loading'|'error')     while (re)connecting
       handle.setTyping(on) / handle.typing()
       handle.back()                      put the keyboard back after the page drew the pane again
       handle.dispose()                   free the terminal (its WebGL context)
   Pure parts for tests: UI.term.pasteAsk, UI.term.lineCount, UI.term.bytes, UI.term.clamp, UI.term.WORDS.
   No screen text ever goes in as markup: xterm draws it on a canvas. A program cannot write the clipboard (no OSC 52
   handler), change the page title (not listened to) or open a link other than http/https (opened with noopener). */
(() => {
  'use strict';
  const UI = (typeof window === 'object' ? (window.UI = window.UI || {}) : {});

  /* --- the pure part --- */
  /* Lines in a paste (a line end at the very end counts as Enter, not as a line); 0 for no text. */
  const lineCount = text => { const t = String(text || '').replace(/\r\n?/g, '\n'); return t ? t.replace(/\n$/, '').split('\n').length : 0; };
  /* What a paste with a line end asks first; '' = it goes in without asking (no line end in it). */
  function pasteAsk(text) {
    const t = String(text || '').replace(/\r\n?/g, '\n');
    if (!t.includes('\n')) return '';
    const n = lineCount(t);
    return n === 1 ? 'Paste 1 line and press Enter in the helper’s screen?' : 'Paste ' + n + ' lines into the helper’s screen?';
  }
  /* base64 from the bridge -> the bytes xterm writes (it decodes UTF-8 itself, also across two messages) */
  function bytes(b64) {
    try {
      const s = atob(String(b64 || ''));
      const out = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
      return out;
    } catch (e) { return new Uint8Array(0); }
  }
  /* a size the bridge takes (cols 10-500, rows 3-300); null when it is not a size */
  function clamp(z) {
    const ok = v => typeof v === 'number' && Number.isFinite(v) && v > 0;
    if (!z || !ok(z.cols) || !ok(z.rows)) return null;
    const c = Math.floor(z.cols), r = Math.floor(z.rows);
    return {cols: Math.max(10, Math.min(500, c)), rows: Math.max(3, Math.min(300, r))};
  }
  const MAX_INPUT = 60000;  // characters in one typing request (the bridge takes 64 K)

  /* --- the element --- */
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'className') n.className = v; else if (k === 'text') n.textContent = v; else n.setAttribute(k, v === true ? '' : String(v));
    }
    kids.forEach(c => c != null && n.append(c));
    return n;
  }
  const WORDS = {
    watch: 'Watching · select text to copy it',
    type: 'Typing: your keys go to the helper · Shift+Tab stops',
    off: 'Watching only · typing is off in Settings',
    loading: 'Connecting to the helper’s screen…',
    error: 'The screen stopped updating. orch keeps trying; the helper keeps working.',
    ended: 'The helper’s screen has closed.',
    none: 'No helper screen right now.',
    oneshot: 'This helper works one step at a time; it has no live screen.',
    notmux: 'This computer cannot show the helper’s screen.',
    nogl: 'This browser cannot draw the terminal. The chat view shows what the helper does.'
  };
  /* the screen's colours from the tokens of the page (xterm needs colour values, so they are read, never written) */
  function theme(node) {
    const cs = typeof getComputedStyle === 'function' ? getComputedStyle(node) : null;
    const t = name => (cs ? cs.getPropertyValue(name).trim() : '') || undefined;
    const base = {black: t('--surface-3'), red: t('--danger'), green: t('--success'), yellow: t('--warning'), blue: t('--info'),
      magenta: t('--brand'), cyan: t('--working'), white: t('--text')};
    return Object.assign({background: t('--sidebar'), foreground: t('--text'), cursor: t('--text'), cursorAccent: t('--sidebar'),
      selectionBackground: t('--brand-soft'), selectionForeground: t('--text')}, base,
    {brightBlack: t('--text-faint'), brightRed: base.red, brightGreen: base.green, brightYellow: base.yellow, brightBlue: base.blue,
      brightMagenta: base.magenta, brightCyan: base.cyan, brightWhite: base.white});
  }
  const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hasGL = () => {
    try {
      const c = document.createElement('canvas').getContext('webgl2');
      if (c && typeof c.getExtension === 'function') { const x = c.getExtension('WEBGL_lose_context'); if (x) x.loseContext(); }  // only a probe
      return !!c;
    } catch (e) { return false; }
  };

  function term(opts) {
    const o = opts || {};
    const label = o.label || 'the helper';
    const say = el('span', {className: 'meta term-say', role: 'status'});
    const sw = el('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': 'false', 'aria-label': 'Let me type into the screen of ' + label, 'data-key': 'term-type'});
    const swRow = el('label', {className: 'term-sw', hidden: true}, sw, el('span', {text: 'Let me type'}));
    const copy = el('button', {type: 'button', className: 'btn xs ghost', 'data-key': 'term-copy', text: 'Copy', title: 'Copy the selected text, or all of the terminal\u2019s text', hidden: true});
    const bar = el('div', {className: 'term-bar'}, say, el('span', {className: 'term-tools'}, swRow, copy));
    const askText = el('span', {});
    const askGo = el('button', {type: 'button', className: 'btn xs primary', 'data-key': 'term-paste-go', text: 'Paste'});
    const askNo = el('button', {type: 'button', className: 'btn xs ghost', 'data-key': 'term-paste-no', text: 'Cancel'});
    const ask = el('div', {className: 'term-ask', role: 'alert', hidden: true}, askText, askGo, askNo);
    const host = el('div', {className: 'term-host'});
    const screen = el('div', {className: 'term-screen', role: 'group', 'aria-label': 'Screen of ' + label}, host);
    const loading = el('div', {className: 'term-state'}, el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line short'}));
    const note = el('p', {className: 'term-state meta', hidden: true});
    const root = el('div', {className: 'term', 'data-typing': 'off', 'data-state': 'loading'}, bar, ask, screen, loading, note);

    let state = 'loading', live = false, typing = false, allowed = false, canType = true, held = null;
    let out = '', timer = null, chain = Promise.resolve(), gen = 0, sizeTimer = null, sent = '', lastFocus = null;
    let xt = null, fit = null, tried = false, cols = 80, rows = 24, watcher = null;

    /* xterm is made with the first screen (it measures its font in the page) */
    function make() {
      if (xt || tried) return !!xt;
      tried = true;
      const T = window.Terminal, GL = window.WebglAddon && window.WebglAddon.WebglAddon, Fit = window.FitAddon && window.FitAddon.FitAddon;
      if (typeof T !== 'function' || typeof GL !== 'function' || !hasGL()) { state = 'nogl'; words(); return false; }
      const cs = typeof getComputedStyle === 'function' ? getComputedStyle(screen) : null;
      xt = new T({cols, rows, disableStdin: true, cursorBlink: false, scrollback: 2000,
        fontFamily: (cs && cs.fontFamily) || 'monospace', fontSize: Math.round(parseFloat(cs && cs.fontSize) || 13), lineHeight: 1.2,
        theme: theme(root), screenReaderMode: false,
        linkHandler: {allowNonHttpProtocols: false, activate: (e, uri) => { if (/^https?:\/\//i.test(uri)) window.open(uri, '_blank', 'noopener,noreferrer'); }}});
      const gl = new GL();
      try { xt.loadAddon(gl); } catch (e) { xt.dispose(); xt = null; state = 'nogl'; words(); return false; }
      gl.onContextLoss(() => {  // the graphics card took the drawing back: stop typing, draw again with the next screen
        setTyping(false);
        if (xt) { xt.dispose(); xt = null; }
        host.textContent = ''; tried = false; live = false; state = 'loading'; words();
      });
      if (typeof Fit === 'function') { fit = new Fit(); xt.loadAddon(fit); }
      try { xt.open(host); } catch (e) { xt.dispose(); xt = null; state = 'nogl'; words(); return false; }
      xt.onData(d => { if (typing) { out += d; schedule(); } });  // watching: xterm takes no input at all (disableStdin)
      xt.attachCustomKeyEventHandler(keyFilter);
      return true;
    }
    /* keys xterm must leave alone: Shift+Tab stops typing; Ctrl+C or Cmd+C with a selection copies it; other Cmd keys */
    function keyFilter(e) {
      if (e.type !== 'keydown') return true;
      if (typing && e.key === 'Tab' && e.shiftKey) { e.preventDefault(); setTyping(false); return false; }
      const k = String(e.key || '').toLowerCase();
      if ((e.ctrlKey || e.metaKey) && !e.altKey && k === 'c' && xt && xt.hasSelection()) { copyText(xt.getSelection()); e.preventDefault(); return false; }
      if (e.metaKey) return false;
      return true;
    }
    function words() {
      const w = !live ? WORDS[state] || WORDS.none : typing ? WORDS.type : allowed && canType ? WORDS.watch : WORDS.off;
      if (say.textContent !== w) say.textContent = w;
      swRow.hidden = !(live && allowed && canType);
      sw.setAttribute('aria-checked', String(typing));
      root.dataset.typing = typing ? 'on' : 'off';
      root.dataset.state = live ? 'live' : state;
      screen.hidden = !(live || ((state === 'error' || state === 'loading') && xt));  // the last screen stays while it reconnects
      loading.hidden = live || state !== 'loading' || !!xt;
      note.hidden = live || state === 'loading' || state === 'error';
      note.textContent = note.hidden ? '' : WORDS[state] || WORDS.none;
      copy.hidden = !live;
    }
    function hello(h) { allowed = !!(h && h.typing_allowed === true); if (typing && !allowed) setTyping(false); words(); }
    function screenNow(s) {
      if (!make()) return;
      const z = clamp(s);
      xt.reset();
      if (z) { cols = z.cols; rows = z.rows; xt.resize(cols, rows); }
      xt.write(bytes(s && s.data));
      live = true; state = 'live'; words();
      if (typing) measure(true);
    }
    function write(b64) { if (xt && live) xt.write(bytes(b64)); }
    function size(z) {
      const n = clamp(z);
      if (!n || !xt) return;
      cols = n.cols; rows = n.rows; sent = cols + 'x' + rows;
      xt.resize(cols, rows);
    }
    function end(why) {
      if (typing) setTyping(false);
      state = live || state === 'ended' ? 'ended' : (why in WORDS ? why : 'none');
      live = false; words();
    }
    /* the stream is (re)connecting or failed: nothing can be typed until a new hello and screen arrive, and typing
       needs the person's switch again */
    function show(next) {
      setTyping(false);
      live = false; allowed = false; state = next; words();
    }
    function setTyping(on) {
      if (!on && held) { held = null; ask.hidden = true; }
      const want = !!on && live && allowed && canType && !!xt;
      if (want === typing) { words(); return; }
      typing = want; sent = '';
      if (!typing) { out = ''; clearTimeout(timer); timer = null; clearTimeout(sizeTimer); sizeTimer = null; gen++; }  // nothing typed before goes out later
      if (xt) { xt.options.disableStdin = !typing; xt.options.cursorBlink = typing && !reduced(); }
      words();
      if (typing) { xt.focus(); measure(true); }
      if (typeof o.onTyping === 'function') o.onTyping(typing);
    }
    /* what xterm hands over goes out in order, one request at a time */
    function schedule() { if (!timer) timer = setTimeout(() => { timer = null; chain = chain.then(flush, flush); }, 20); }
    async function flush() {
      const mine = gen;
      while (out && typing && mine === gen) {
        let n = Math.min(out.length, MAX_INPUT);
        if (n < out.length && /[\ud800-\udbff]/.test(out[n - 1])) n--;  // never one half of a letter in each request
        const data = out.slice(0, n);
        out = out.slice(data.length);
        const r = typeof o.onInput === 'function' ? await o.onInput(data) : {ok: false, status: 0};
        if (mine !== gen) return;  // typing was turned off while this was out
        if (r && r.ok) continue;
        if (r && r.status === 403) { if (/is off/.test(r.text || '')) allowed = false; else canType = false; }
        setTyping(false);
        return;
      }
    }
    /* a paste: nothing while watching; with a line end it asks first; then xterm sends it (bracketed when the
       program asked for that) */
    root.addEventListener('paste', e => {
      if (!screen.contains(e.target)) return;
      const t = (e.clipboardData && e.clipboardData.getData('text')) || '';
      if (!typing) { e.preventDefault(); e.stopPropagation(); return; }
      const q = pasteAsk(t);
      if (!q) return;  // one line: xterm pastes it itself
      e.preventDefault(); e.stopPropagation();
      held = t; askText.textContent = q; ask.hidden = false; askGo.focus();
    }, true);
    const unask = () => { held = null; ask.hidden = true; if (typing && xt) xt.focus(); };
    askGo.addEventListener('click', () => { const t = held; unask(); if (t && typing && xt) xt.paste(t); });
    askNo.addEventListener('click', unask);
    ask.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); unask(); } });
    sw.addEventListener('click', e => { e.preventDefault(); setTyping(!typing); });
    async function copyText(text) {
      let ok = false;
      try { await navigator.clipboard.writeText(text); ok = true; } catch (err) { ok = false; }
      copy.textContent = ok ? 'Copied' : 'Select and press Ctrl+C';
      setTimeout(() => { copy.textContent = 'Copy'; }, 1600);
    }
    function allText() {
      if (!xt) return '';
      const b = xt.buffer.active, lines = [];
      for (let i = 0; i < b.length; i++) { const l = b.getLine(i); lines.push(l ? l.translateToString(true) : ''); }
      return lines.join('\n').replace(/\n+$/, '');
    }
    copy.addEventListener('click', () => copyText(xt && xt.hasSelection() ? xt.getSelection() : allText()));
    /* the size: while typing, the helper's screen follows the box (sent once it stays the same for a moment) */
    function measure(now) {
      if (!typing || !fit || typeof o.onSize !== 'function') return;
      clearTimeout(sizeTimer);
      sizeTimer = setTimeout(() => {
        sizeTimer = null;
        if (!typing) return;
        const z = clamp(fit.proposeDimensions());
        if (!z) return;
        const sig = z.cols + 'x' + z.rows;
        if (sig === sent || (z.cols === cols && z.rows === rows)) { sent = sig; return; }
        sent = sig;
        Promise.resolve(o.onSize(z)).then(r => { if (r && r.ok === false && sent === sig) sent = ''; });  // a size that did not go is tried again
      }, now ? 0 : 250);
    }
    if (typeof ResizeObserver === 'function') { watcher = new ResizeObserver(() => measure(false)); watcher.observe(screen); }
    root.addEventListener('focusin', e => { lastFocus = e.target; });
    root.addEventListener('focusout', e => { if (e.relatedTarget && !root.contains(e.relatedTarget)) lastFocus = null; });
    words();
    return {
      el: root, hello, screen: screenNow, write, size, end, show, setTyping,
      typing: () => typing,
      /* after the page drew the pane again: the keyboard goes back where it was in this terminal (the screen or the
         paste question), and only when nothing else on the page has it now */
      back() {
        const a = document.activeElement;
        if (!(typing || !ask.hidden) || !lastFocus || !root.contains(lastFocus) || (a && a !== document.body && !root.contains(a))) return;
        if (a !== lastFocus) lastFocus.focus({preventScroll: true});
      },
      dispose() { setTyping(false); if (watcher) watcher.disconnect(); if (xt) { xt.dispose(); xt = null; } }
    };
  }
  term.pasteAsk = pasteAsk; term.lineCount = lineCount; term.bytes = bytes; term.clamp = clamp; term.WORDS = WORDS;
  UI.term = term;
  if (typeof module === 'object' && module.exports) module.exports = term;
})();
