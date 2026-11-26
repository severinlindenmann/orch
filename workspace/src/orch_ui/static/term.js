/* The helper's real screen in a page (ORCH-744, Focus draft D feature 5), on the terminal bridge (ORCH-743).
   A real terminal: xterm.js 5.5.0 with its WebGL renderer, vendored next to this file (xterm.js,
   xterm-addon-webgl.js, xterm-addon-fit.js; licence and checksums in LICENSE-xterm.txt). The WebGL renderer is loaded
   before the terminal opens, so xterm adds no <style> element and the page's style-src 'self' stays as it is.
   ORCH-2199 (owner pick B a, M a): no switch. A click into the screen (or Enter on it) sends the keys there, Esc twice or
   a click outside stops, Shift+Tab goes to the helper like every other key; dragging still selects and copies. The
   server decides again (the workspace setting, so watch-only stays a setting, and the sign-in). Copy says what it
   copies: "Copy selection" or "Copy all". A paste goes in as one block without a question, and never presses Enter by
   itself (its last line ends are dropped). The helper's screen follows the size of its box (onSize):
   while typing, and while watching too when typing is allowed and no other page types (ORCH-1758, owner: the last
   page opened or resized sets the size). A screen of another size (another page set it, or typing is off in
   Settings) is drawn with a smaller font so its whole width fits (down to MIN_FONT, then it scrolls sideways), and
   the box follows the newest line and the cursor until the person scrolls away (ORCH-882). One page types at a time: when another page takes the typing,
   this one goes back to watching and says so (typingBy, ORCH-883).
     UI.term({label, plain, toolsOut, onInput(data) -> Promise<{ok, status, text}>, onSize({cols, rows}), onTyping(on)})  -> handle
       plain                              true for a plain terminal (no helper): the words say "this terminal"
       toolsOut                           the page puts handle.tools itself (a Focus pane header); else a slim row on top
       handle.el                          the element to put in the page
       handle.tools                       the typing sign (keyboard), Copy and Turn typing on
       handle.hello({typing_allowed})     the bridge's first word: may this workspace type at all
       handle.typingBy('you'|'other'|'none')  who types into this session now; 'other' stops typing here
       handle.screen({cols, rows, data})  the whole screen (data: base64 terminal bytes), first and after a gap
       handle.write(b64)                  more bytes the program wrote
       handle.size({cols, rows})          the helper's screen has a new size
       handle.end(state)                  the screen closed ('none', 'oneshot', 'notmux', ...)
       handle.show('loading'|'error')     while (re)connecting
       handle.setTyping(on) / handle.typing()
       handle.back()                      put the keyboard back after the page drew the pane again
       handle.dispose()                   free the terminal (its WebGL context)
   Pure parts for tests: UI.term.pasteText, UI.term.lineCount, UI.term.bytes, UI.term.clamp, UI.term.WORDS,
   UI.term.followTop, UI.term.plainText, UI.term.fitFont.
   No screen text ever goes in as markup: xterm draws it on a canvas. A program cannot write the clipboard (no OSC 52
   handler), change the page title (not listened to) or open a link other than http/https (opened with noopener). */
(() => {
  'use strict';
  const UI = (typeof window === 'object' ? (window.UI = window.UI || {}) : {});

  /* --- the pure part --- */
  /* Lines in a paste (a line end at the very end counts as Enter, not as a line); 0 for no text. */
  const lineCount = text => { const t = String(text || '').replace(/\r\n?/g, '\n'); return t ? t.replace(/\n$/, '').split('\n').length : 0; };
  /* Pasted text before it goes in: no control characters but tab and line ends (an escape could end the bracketed
     paste early and act as keys, Ctrl+C as a stop), and so no paste markers either. */
  const cleanPaste = text => String(text || '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, '');
  /* What a paste hands to the terminal (ORCH-2199, owner pick M a): no question; the line ends at its very end are
     dropped so it never presses Enter by itself. The terminal sends it as one block when the program asked for that. */
  const pasteText = text => cleanPaste(text).replace(/\r\n?/g, '\n').replace(/\n+$/, '');
  const ESC_TWICE = 500;  // ms: a second Esc within this stops typing; a single Esc goes to the helper after it
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
  /* Where the box scrolls while watching so the newest line and the cursor are in view (ORCH-882): the lower of the
     cursor row and the last row with text sits at the bottom of the box; the top when the screen fits. pad: the
     box's padding above (and as much below) the screen. */
  function followTop(f) {
    const row = Math.max(f.cursorRow | 0, f.lastRow | 0) + 1;
    const max = Math.max(0, f.height - f.view);
    return Math.max(0, Math.min(max, Math.ceil(row * f.rowPx + 2 * (f.pad || 0) - f.view)));
  }
  /* The font size that lets a screen of `cols` columns fit its box while watching (ORCH-1758): `fitCols` columns
     fit at font size `cur`; never larger than the page's font `base`, never under `min`, in half pixels. */
  const MIN_FONT = 8;
  function fitFont(f) {
    const base = +f.base || 13, min = Math.min(base, +f.min || MIN_FONT), cur = +f.cur || base;
    if (!(f.cols > 0) || !(f.fitCols > 0)) return base;
    const want = Math.floor(cur * f.fitCols / f.cols * 2) / 2;
    return Math.max(min, Math.min(base, want));
  }
  /* The terminal's lines as text for Copy: no trailing spaces (a program pads its lines with them), wrapped lines
     joined again, no empty lines at the end (ORCH-885). lines: [{text, wrapped}] */
  function plainText(lines) {
    const out = [];
    for (const l of lines) {
      const t = String(l.text || '');
      if (l.wrapped && out.length) out[out.length - 1] += t; else out.push(t);
    }
    return out.map(t => t.replace(/[ \t\u00a0]+$/, '')).join('\n').replace(/\n+$/, '');
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
    watch: 'Click the screen to type into it',
    type: 'Typing into the helper · Esc twice or a click outside stops',
    typePlain: 'Typing into this terminal · Esc twice or a click outside stops',
    off: 'Watch only · typing is off in Settings',
    offLink: 'Watch only',  // ORCH-1600: with the Turn typing on link beside it, the line says it once
    taken: 'Another page is typing here',
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
    /* only a state worth a word shows (watch only, another page types); the rest is the keyboard sign's tooltip */
    const say = el('span', {className: 'meta term-say', role: 'status'});
    /* the typing sign (owner pick B a): a keyboard, lit while your keys go to the screen; a click turns typing on or off */
    const sw = el('button', {type: 'button', className: 'btn xs ghost icon term-kbd', 'aria-pressed': 'false', 'aria-label': 'Type into the screen of ' + label, 'data-key': 'term-type', hidden: true});
    if (typeof window.icon === 'function') sw.innerHTML = window.icon('keyboard', 16); else sw.textContent = '\u2328';
    /* Copy: its icon and word; a narrow pane keeps the icon, the word stays its name and tooltip */
    const copyW = el('span', {className: 'term-copy-w', text: 'Copy all'});
    const copy = el('button', {type: 'button', className: 'btn xs ghost term-copy', 'data-key': 'term-copy', hidden: true});
    if (typeof window.icon === 'function') copy.innerHTML = window.icon('copy', 16);
    copy.append(copyW);
    /* ORCH-1600: "typing is off in Settings" takes the person straight to that switch (the page gives the address) */
    const turnOn = o.settingsHref ? el('a', {className: 'btn xs ghost', href: o.settingsHref, 'data-key': 'term-settings', text: 'Turn typing on', hidden: true}) : null;
    const tools = el('span', {className: 'term-tools', 'data-key': 'term-tools'}, say, turnOn, sw, copy);
    const bar = o.toolsOut ? null : el('div', {className: 'term-bar'}, tools);
    const host = el('div', {className: 'term-host'});
    const screen = el('div', {className: 'term-screen', role: 'group', 'aria-label': 'Screen of ' + label}, host);
    const loading = el('div', {className: 'term-state'}, el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line short'}));
    const note = el('p', {className: 'term-state meta', hidden: true});
    const root = el('div', {className: 'term', 'data-typing': 'off', 'data-state': 'loading'}, bar, screen, loading, note);

    let state = 'loading', live = false, typing = false, allowed = false, canType = true, taken = false, escAt = 0, escTimer = null;
    let stick = true, autoTop = -1, followAsked = false;
    let out = '', timer = null, chain = Promise.resolve(), gen = 0, sizeTimer = null, sent = '', lastFocus = null;
    let xt = null, fit = null, tried = false, cols = 80, rows = 24, watcher = null, baseFont = 13;
    let fresh = false, sizeNo = false, baseCell = null;  // fresh: the first screen after a hello sizes the window; sizeNo: refused (403)

    /* xterm is made with the first screen (it measures its font in the page) */
    function make() {
      if (xt || tried) return !!xt;
      tried = true;
      const T = window.Terminal, GL = window.WebglAddon && window.WebglAddon.WebglAddon, Fit = window.FitAddon && window.FitAddon.FitAddon;
      if (typeof T !== 'function' || typeof GL !== 'function' || !hasGL()) { state = 'nogl'; words(); return false; }
      const cs = typeof getComputedStyle === 'function' ? getComputedStyle(screen) : null;
      baseFont = Math.round(parseFloat(cs && cs.fontSize) || 13);
      xt = new T({cols, rows, disableStdin: true, cursorBlink: false, scrollback: 2000,
        fontFamily: (cs && cs.fontFamily) || 'monospace', fontSize: baseFont, lineHeight: 1.2,
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
      if (typeof xt.onSelectionChange === 'function') xt.onSelectionChange(copyWord);
      return true;
    }
    /* keys xterm must leave alone: Esc twice stops typing (a single Esc goes to the helper a moment later); Enter on the
       screen while not typing starts it; Ctrl+C or Cmd+C with a selection copies it; other Cmd keys. Shift+Tab is the
       helper's (ORCH-2199: it switches the helper's mode) and goes in like any key. */
    function keyFilter(e) {
      if (e.type !== 'keydown') return true;
      if (!typing && e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); setTyping(true); return false; }
      if (typing && e.key === 'Escape' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        const now = Date.now();
        clearTimeout(escTimer); escTimer = null;
        if (escAt && now - escAt < ESC_TWICE) { escAt = 0; setTyping(false); return false; }
        escAt = now;
        escTimer = setTimeout(() => { escTimer = null; escAt = 0; if (typing) { out += '\x1b'; schedule(); } }, ESC_TWICE);
        return false;
      }
      const k = String(e.key || '').toLowerCase();
      if ((e.ctrlKey || e.metaKey) && !e.altKey && k === 'c' && xt && xt.hasSelection()) { copyText(xt.getSelection()); e.preventDefault(); return false; }
      if (e.metaKey) return false;
      return true;
    }
    function words() {
      const w = !live ? WORDS[state] || WORDS.none : typing ? (o.plain ? WORDS.typePlain : WORDS.type)
        : allowed && canType ? (taken ? WORDS.taken : WORDS.watch) : turnOn && !allowed ? WORDS.offLink : WORDS.off;
      // no explaining line (owner pick H a): only a state worth a word (watch only, another page types, reconnecting)
      const shown = live ? (taken || !(allowed && canType) ? w : '') : (state === 'loading' || state === 'error') && xt ? w : '';
      if (say.textContent !== shown) say.textContent = shown;
      say.hidden = !shown;
      sw.hidden = !(live && allowed && canType && typing);  // lit only while your keys go there (owner pick B a)
      sw.setAttribute('title', w);
      if (turnOn) turnOn.hidden = !(live && !allowed);
      sw.setAttribute('aria-pressed', String(typing));
      root.dataset.typing = typing ? 'on' : 'off';
      root.dataset.state = live ? 'live' : state;
      screen.hidden = !(live || ((state === 'error' || state === 'loading') && xt));  // the last screen stays while it reconnects
      loading.hidden = live || state !== 'loading' || !!xt;
      note.hidden = live || state === 'loading' || state === 'error';
      note.textContent = note.hidden ? '' : WORDS[state] || WORDS.none;
      copy.hidden = !live;
      copyWord();
    }
    function hello(h) { allowed = !!(h && h.typing_allowed === true); taken = false; fresh = true; sizeNo = false; if (typing && !allowed) setTyping(false); words(); }
    /* who types into this session now: another page took it, so this one goes back to watching (ORCH-883) */
    function typingBy(by) {
      taken = by === 'other';
      if (taken && typing) setTyping(false, true); else words();
      if (by === 'none') measure(true);  // nobody types (the page that sized it may have left): size it again
    }
    /* while watching, the box keeps the newest line and the cursor in view, until the person scrolls away */
    function follow() {
      if (followAsked) return;
      followAsked = true;
      const run = () => {
        followAsked = false;
        if (!xt || !live || typing || !stick) return;
        const b = xt.buffer && xt.buffer.active;
        const scr = host.querySelector && host.querySelector('.xterm-screen');
        const height = scr ? scr.offsetHeight : 0;
        if (!b || !height || !rows) return;
        let last = 0;
        for (let i = rows - 1; i >= 0; i--) { const l = b.getLine(b.baseY + i); if (l && l.translateToString(true).trim()) { last = i; break; } }
        const pad = scr.getBoundingClientRect().top - screen.getBoundingClientRect().top + screen.scrollTop;
        const top = followTop({cursorRow: b.cursorY, lastRow: last, rowPx: height / rows, pad, view: screen.clientHeight, height: screen.scrollHeight});
        if (screen.scrollTop !== top) screen.scrollTop = top;
        autoTop = screen.scrollTop;
      };
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run); else run();
    }
    /* a scroll the person made away from where the box followed stops following; back at it, it follows again */
    screen.addEventListener('scroll', () => {
      if (autoTop < 0 || typing) return;
      stick = Math.abs(screen.scrollTop - autoTop) < 4 || screen.scrollTop + screen.clientHeight >= screen.scrollHeight - 4;
    });
    function screenNow(s) {
      if (!make()) return;
      const z = clamp(s);
      xt.reset();
      if (z) { cols = z.cols; rows = z.rows; xt.resize(cols, rows); }
      stick = true;
      xt.write(bytes(s && s.data), follow);
      live = true; state = 'live'; words();
      fitWidth();  // after words(): the box is shown now and can be measured
      if (typing || fresh) measure(true);  // a screen sent again after a gap does not take the size back
      fresh = false;
    }
    function write(b64) { if (xt && live) xt.write(bytes(b64), follow); }
    function size(z) {
      const n = clamp(z);
      if (!n || !xt) return;
      cols = n.cols; rows = n.rows; sent = cols + 'x' + rows;
      xt.resize(cols, rows);
      fitWidth();
      follow();
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
    function setTyping(on, byOther) {
      if (!on) { clearTimeout(escTimer); escTimer = null; escAt = 0; }
      const want = !!on && live && allowed && canType && !!xt;
      if (want) taken = false;
      if (want === typing) { words(); return; }
      typing = want; sent = '';
      if (!typing) { out = ''; clearTimeout(timer); timer = null; clearTimeout(sizeTimer); sizeTimer = null; gen++; }  // nothing typed before goes out later
      if (xt) { xt.options.disableStdin = !typing; xt.options.cursorBlink = typing && !reduced(); }
      words();
      fitWidth();
      if (typing) { xt.focus(); measure(true); } else follow();
      if (typeof o.onTyping === 'function') o.onTyping(typing, !!byOther);
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
        if (r && r.status === 409 && /Another page/.test(r.text || '')) taken = true;
        setTyping(false);
        return;
      }
    }
    /* a paste goes in as one block, no question, never with an Enter at its end (owner pick M a); a paste into the
       screen while watching turns typing on first, as a click would (xterm sends it bracketed when the program asked) */
    root.addEventListener('paste', e => {
      if (!screen.contains(e.target)) return;
      const t = pasteText((e.clipboardData && e.clipboardData.getData('text')) || '');
      e.preventDefault(); e.stopPropagation();  // every paste goes in cleaned, never as the browser hands it to xterm
      if (!t) return;
      if (!typing) setTyping(true);
      if (typing && xt) xt.paste(t);
    }, true);
    /* a click into the screen types there (owner pick B a); a drag selects text to copy and changes nothing */
    let downAt = null;
    screen.addEventListener('pointerdown', e => { downAt = e.button === 0 || e.button == null ? {x: e.clientX, y: e.clientY} : null; });
    screen.addEventListener('pointerup', e => {
      const d = downAt; downAt = null;
      if (!d || typing || Math.abs((e.clientX || 0) - (d.x || 0)) > 4 || Math.abs((e.clientY || 0) - (d.y || 0)) > 4) return;
      if (xt && xt.hasSelection()) return;
      setTyping(true);
    });
    /* a click anywhere outside the screen (and its tools) stops typing */
    const outside = e => { if (typing && !root.contains(e.target) && !tools.contains(e.target)) setTyping(false); };
    if (typeof document === 'object' && typeof document.addEventListener === 'function') document.addEventListener('pointerdown', outside, true);
    sw.addEventListener('click', e => { e.preventDefault(); setTyping(!typing); });
    /* Copy says what it copies (ORCH-2199): the selection when there is one, else all of the screen's text */
    const COPY_SEL = 'Copy selection', COPY_ALL = 'Copy all';
    let copyBusy = false;
    function copyWord() {
      if (copyBusy) return;
      const w = xt && xt.hasSelection() ? COPY_SEL : COPY_ALL;
      if (copyW.textContent !== w) copyW.textContent = w;
      copy.setAttribute('title', w);
      copy.setAttribute('aria-label', w);
    }
    async function copyText(text) {
      let ok = false;
      try { await navigator.clipboard.writeText(text); ok = true; } catch (err) { ok = false; }
      copyBusy = true;
      copyW.textContent = ok ? 'Copied' : 'Select and press Ctrl+C';
      setTimeout(() => { copyBusy = false; copyWord(); }, 1600);
    }
    function allText() {
      if (!xt) return '';
      const b = xt.buffer.active, lines = [];
      for (let i = 0; i < b.length; i++) { const l = b.getLine(i); lines.push({text: l ? l.translateToString(false) : '', wrapped: !!(l && l.isWrapped)}); }  // untrimmed: a space at a wrap stays
      return plainText(lines);
    }
    const trimSel = t => String(t).split('\n').map(l => l.replace(/[ \t\u00a0]+$/, '')).join('\n');
    copy.addEventListener('click', () => copyText(xt && xt.hasSelection() ? trimSel(xt.getSelection()) : allText()));
    /* while watching, the helper's whole width fits the box: a smaller font (ORCH-1758); typing uses the page's font,
       and its size then follows the box (measure) */
    function setFont(f) { if (xt.options.fontSize !== f) xt.options.fontSize = f; }
    /* one cell as drawn now (xterm rounds it to whole pixels, so it does not scale with the font) */
    function cell() {
      const scr = host.querySelector && host.querySelector('.xterm-screen');
      return scr && scr.offsetWidth && cols && rows ? {w: scr.offsetWidth / cols, h: scr.offsetHeight / rows} : null;
    }
    function fitWidth() {
      if (!xt) return;
      if (xt.options.fontSize === baseFont) baseCell = cell() || baseCell;
      if (typing || !fit) { setFont(baseFont); return; }
      const min = Math.min(baseFont, MIN_FONT);
      let p = fit.proposeDimensions();
      if (!p || !(p.cols > 0)) return;  // the box is not shown now; fitted again when it is (ResizeObserver)
      let f = fitFont({base: baseFont, cur: xt.options.fontSize, fitCols: p.cols, cols});
      setFont(f);
      for (let i = 0; i < 6 && f > min; i++) {  // a cell's width is rounded to whole pixels: smaller until it fits
        p = fit.proposeDimensions();
        if (!p || p.cols >= cols) return;
        f = Math.max(min, f - 0.5);
        setFont(f);
      }
    }
    /* the size: the helper's screen follows the box (sent once it stays the same for a moment) while typing, and
       while watching when typing is allowed and no other page types (ORCH-1758) */
    const sizer = () => typing || (live && allowed && canType && !taken && !sizeNo);
    function measure(now) {
      if (!sizer() || !fit || typeof o.onSize !== 'function') return;
      clearTimeout(sizeTimer);
      sizeTimer = setTimeout(() => {
        sizeTimer = null;
        if (!sizer()) return;
        const p = fit.proposeDimensions(), cur = xt.options.fontSize;
        // the columns at the page font, while the screen is drawn smaller: scaled, never the font changed for it
        const c = cur !== baseFont && baseCell && cell();
        const z = clamp(!p || cur === baseFont ? p : c ? {cols: Math.floor(p.cols * c.w / baseCell.w), rows: Math.floor(p.rows * c.h / baseCell.h)}
          : {cols: Math.floor(p.cols * cur / baseFont), rows: Math.floor(p.rows * cur / baseFont)});
        if (!z) return;
        const sig = z.cols + 'x' + z.rows;
        if (sig === sent || (z.cols === cols && z.rows === rows)) { sent = sig; return; }
        sent = sig;
        Promise.resolve(o.onSize(z)).then(r => {
          if (!(r && r.ok === false) || sent !== sig) return;
          sent = '';  // a size that did not go is tried again; meanwhile it is drawn to fit
          if (r.status === 403 && !typing) sizeNo = true;  // typing went off in Settings: no more sizes until a hello
          fitWidth();
        });
      }, now ? 0 : 250);
    }
    if (typeof ResizeObserver === 'function') { watcher = new ResizeObserver(() => { measure(false); if (!typing) { fitWidth(); follow(); } }); watcher.observe(screen, {box: 'border-box'}); }  // a scroll bar coming or going is no new size
    root.addEventListener('focusin', e => { lastFocus = e.target; });  // the screen's own text area
    root.addEventListener('focusout', e => { if (e.relatedTarget && !root.contains(e.relatedTarget)) lastFocus = null; });
    words();
    return {
      el: root, tools, hello, typingBy, screen: screenNow, write, size, end, show, setTyping,
      typing: () => typing,
      /* after the page drew the pane again: the keyboard goes back into the screen while typing, and only when nothing
         else on the page has it now */
      back() {
        const a = document.activeElement;
        if (!typing || !lastFocus || !root.contains(lastFocus) || (a && a !== document.body && !root.contains(a))) return;
        if (a !== lastFocus) lastFocus.focus({preventScroll: true});
      },
      dispose() {
        setTyping(false);
        if (typeof document === 'object' && typeof document.removeEventListener === 'function') document.removeEventListener('pointerdown', outside, true);
        if (watcher) watcher.disconnect();
        if (xt) { xt.dispose(); xt = null; }
      }
    };
  }
  term.followTop = followTop; term.plainText = plainText; term.fitFont = fitFont;
  term.pasteText = pasteText; term.cleanPaste = cleanPaste; term.lineCount = lineCount; term.bytes = bytes; term.clamp = clamp; term.WORDS = WORDS;
  UI.term = term;
  if (typeof module === 'object' && module.exports) module.exports = term;
})();
