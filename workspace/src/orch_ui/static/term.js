/* The helper's real screen in a page (ORCH-744, Focus draft D feature 5).
   Watching only by default: the person turns on "Let me type" and only then do keys go to the helper; the server
   decides again (the workspace setting and the sign-in). Select and copy work like in any page; Copy copies the
   selection or the whole screen; paste goes in as typed text while typing is on. While typing, the screen follows the
   size of its box (onSize); while watching it keeps the helper's own size and scrolls.
     UI.term({label, onKeys(items) -> Promise<{ok, status, text}>, onSize({cols, rows}), onTyping(on)})  -> handle
       handle.el                      the element to put in the page
       handle.update(snap)            a screen from the bridge: {state, screen, cx, cy, cols, rows, cursor, scrolled,
                                      typing_allowed}; state 'live' draws it, 'none' / 'oneshot' / 'notmux' say why not
       handle.show('loading'|'error'|'ended')
       handle.setTyping(on)           on only when the screen is live and typing is allowed
       handle.typing()                is typing on
       handle.back()                  put the keyboard back after the page drew the pane again
   Pure parts for tests: UI.term.paint, UI.term.toItem, UI.term.merge, UI.term.pasteItems, UI.term.fit, UI.term.plain.
   Text only ever goes in with textContent. Colours are classes on tokens (term.css), never colour values. */
(() => {
  'use strict';
  const UI = (typeof window === 'object' ? (window.UI = window.UI || {}) : {});

  /* --- the pure part --- */
  const FG = {30: 0, 31: 1, 32: 2, 33: 3, 34: 4, 35: 5, 36: 6, 37: 7, 90: 8, 91: 9, 92: 10, 93: 11, 94: 12, 95: 13, 96: 14, 97: 15};
  const BG = {40: 0, 41: 1, 42: 2, 43: 3, 44: 4, 45: 5, 46: 6, 47: 7, 100: 8, 101: 9, 102: 10, 103: 11, 104: 12, 105: 13, 106: 14, 107: 15};
  const CSI = /^\x1b\[([0-9;:?]*)([@-~])/;
  /* a program's own sequences (links, clipboard writes, window title: OSC; DCS, APC, PM) are dropped, never drawn or run */
  const OSC = /^\x1b[\]P_^][\s\S]*?(?:\x07|\x1b\\|$)/;
  const fresh = () => ({fg: null, bg: null, bold: false, dim: false, it: false, ul: false, rev: false});
  function sgr(st, list) {
    const codes = (list || '0').split(/[;:]/).map(x => (x === '' ? 0 : Number(x)));
    for (let k = 0; k < codes.length; k++) {
      const n = codes[k];
      if (n === 0) Object.assign(st, fresh());
      else if (n === 1) st.bold = true; else if (n === 2) st.dim = true; else if (n === 3) st.it = true;
      else if (n === 4) st.ul = true; else if (n === 7) st.rev = true;
      else if (n === 22) { st.bold = false; st.dim = false; } else if (n === 23) st.it = false;
      else if (n === 24) st.ul = false; else if (n === 27) st.rev = false;
      else if (n === 39) st.fg = null; else if (n === 49) st.bg = null;
      else if (n in FG) st.fg = FG[n]; else if (n in BG) st.bg = BG[n];
      else if (n === 38 || n === 48) {  // 256 colours: the first 16 are the base set; the rest and true colour keep the default
        if (codes[k + 1] === 5) { const c = codes[k + 2]; if (c >= 0 && c < 16) st[n === 38 ? 'fg' : 'bg'] = c; k += 2; }
        else if (codes[k + 1] === 2) k += 4;
      }
    }
  }
  const cls = (st, cur) => ['t-seg'].concat(st.fg != null ? ['t-c' + st.fg] : [], st.bg != null ? ['t-g' + st.bg] : [],
    st.bold ? ['t-b'] : [], st.dim ? ['t-d'] : [], st.it ? ['t-i'] : [], st.ul ? ['t-u'] : [], st.rev ? ['t-r'] : [], cur ? ['t-cur'] : []).join(' ');
  /* The screen tmux hands over, as rows of segments {t, c} (text, classes). The blank rows under the last line that
     says something are not drawn (unless the cursor is there). The cursor is a segment of its own. */
  function paint(text, cx, cy, showCursor) {
    const lines = String(text || '').split('\n');
    const blank = l => !l.replace(/\x1b\[[0-9;:?]*[@-~]/g, '').trim();
    while (lines.length > 1 && lines.length - 1 > (showCursor ? cy : -1) && blank(lines[lines.length - 1])) lines.pop();
    const st = fresh(), out = [];
    lines.forEach((line, y) => {
      const row = [];
      let col = 0, buf = '';
      const flush = () => { if (buf) { row.push({t: buf, c: cls(st, false)}); buf = ''; } };
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '\x1b') {
          const m = CSI.exec(line.slice(i));
          if (m) { i += m[0].length - 1; if (m[2] === 'm') { flush(); sgr(st, m[1]); } continue; }
          const x = OSC.exec(line.slice(i));
          if (x) { i += x[0].length - 1; continue; }
          continue;  // a lone escape is never drawn
        }
        if (ch < ' ' && ch !== '\t') continue;
        if (showCursor && y === cy && col === cx) { flush(); row.push({t: ch, c: cls(st, true)}); col++; continue; }
        buf += ch; col++;
      }
      flush();
      if (showCursor && y === cy && col <= cx) {
        if (cx > col) row.push({t: ' '.repeat(cx - col), c: 't-seg'});
        row.push({t: ' ', c: 't-seg t-cur'});
      }
      out.push(row);
    });
    return out;
  }
  const plain = text => String(text || '').replace(/\x1b[\]P_^][\s\S]*?(?:\x07|\x1b\\|$)/gm, '').replace(/\x1b\[[0-9;:?]*[@-~]/g, '').replace(/\x1b/g, '').split('\n').map(l => l.replace(/\s+$/, '')).join('\n').replace(/\n+$/, '');

  /* A key becomes one item for the server: literal text, or a name from its list. null = not ours (the browser keeps
     it: Cmd and Alt shortcuts, Ctrl+C with a selection = copy, Shift+Tab = stop typing, Ctrl+V = paste). */
  const NAMES = {Enter: 'Enter', Backspace: 'BSpace', Tab: 'Tab', Escape: 'Escape', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left',
    ArrowRight: 'Right', Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown'};
  function toItem(e, hasSelection) {
    if (e.metaKey || e.altKey || e.isComposing) return null;
    if (e.ctrlKey) {
      const k = String(e.key || '').toLowerCase();
      if (e.shiftKey || (k === 'c' && hasSelection)) return null;
      return k === 'c' || k === 'd' ? {k: 'C-' + k} : null;
    }
    if (e.key === 'Tab' && e.shiftKey) return null;
    if (NAMES[e.key]) return {k: NAMES[e.key]};
    return typeof e.key === 'string' && [...e.key].length === 1 ? {t: e.key} : null;
  }
  const MAX_T = 2000;
  /* Letters typed fast go in one item; at most 2000 characters each (the server's limit). */
  const merge = items => items.reduce((acc, it) => {
    const last = acc[acc.length - 1];
    if (it.t && last && last.t && last.t.length + it.t.length <= MAX_T) last.t += it.t; else acc.push({...it});
    return acc;
  }, []);
  /* Pasted text: line ends as \n, no control characters (the server refuses them), in pieces of 2000. */
  function pasteItems(text) {
    const t = String(text || '').replace(/\r\n?/g, '\n').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '');
    const out = [];
    for (let i = 0; i < t.length; i += MAX_T) out.push({t: t.slice(i, i + MAX_T)});
    return out;
  }
  /* Lines in a paste (a line end at the very end counts as Enter, not as a line); 0 for no text. */
  const lineCount = text => { const t = String(text || '').replace(/\r\n?/g, '\n'); return t ? t.replace(/\n$/, '').split('\n').length : 0; };
  /* What a paste with a line end asks first; '' = it goes in without asking (no line end in it). */
  function pasteAsk(text) {
    const t = String(text || '').replace(/\r\n?/g, '\n');
    if (!t.includes('\n')) return '';
    const n = lineCount(t);
    return n === 1 ? 'Paste 1 line and press Enter in the helper\u2019s screen?' : 'Paste ' + n + ' lines into the helper\u2019s screen?';
  }
  /* How many columns and rows fit a box of w x h pixels with cells of cw x ch; null when it cannot tell. */
  function fit(w, h, cw, ch) {
    if (!(w > 0 && h > 0 && cw > 0 && ch > 0)) return null;
    return {cols: Math.max(20, Math.min(500, Math.floor(w / cw))), rows: Math.max(5, Math.min(200, Math.floor(h / ch)))};
  }

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
    notmux: 'This computer cannot show the helper’s screen.'
  };
  function term(opts) {
    const o = opts || {};
    const label = o.label || 'the helper';
    const say = el('span', {className: 'meta term-say', role: 'status'});
    const sw = el('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': 'false', 'aria-label': 'Let me type into the screen of ' + label, 'data-key': 'term-type'});
    const swRow = el('label', {className: 'term-sw', hidden: true}, sw, el('span', {text: 'Let me type'}));
    const copy = el('button', {type: 'button', className: 'btn xs ghost', 'data-key': 'term-copy', text: 'Copy', title: 'Copy the selected text, or the whole screen'});
    const bar = el('div', {className: 'term-bar'}, say, el('span', {className: 'term-tools'}, swRow, copy));
    const rows = el('div', {className: 'term-rows'});
    const screen = el('div', {className: 'term-screen', tabindex: '0', role: 'log', 'aria-label': 'Screen of ' + label, 'aria-live': 'off'}, rows);
    const probe = el('span', {className: 'term-probe', 'aria-hidden': 'true', text: 'MMMMMMMMMM'});
    const loading = el('div', {className: 'term-state'}, el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line'}), el('span', {className: 'skeleton line short'}));
    const note = el('p', {className: 'term-state meta', hidden: true});
    /* a paste of more than one line asks once, so a copied command with a hidden line end does not run by itself */
    const askText = el('span', {});
    const askGo = el('button', {type: 'button', className: 'btn xs primary', 'data-key': 'term-paste-go', text: 'Paste'});
    const askNo = el('button', {type: 'button', className: 'btn xs ghost', 'data-key': 'term-paste-no', text: 'Cancel'});
    const ask = el('div', {className: 'term-ask', role: 'alert', hidden: true}, askText, askGo, askNo);
    let held = null;
    const root = el('div', {className: 'term', 'data-typing': 'off', 'data-state': 'loading'}, bar, ask, screen, loading, note, probe);

    let state = 'loading', snap = null, typing = false, allowed = false, canType = true, keys = [], timer = null, chain = Promise.resolve();
    let drawn = [], focused = false, sent = '';
    const hasSel = () => {
      const s = typeof window.getSelection === 'function' ? window.getSelection() : null;
      return !!(s && !s.isCollapsed && screen.contains(s.anchorNode));
    };
    function words() {
      const w = state !== 'live' ? WORDS[state] || WORDS.none : typing ? WORDS.type : allowed && canType ? WORDS.watch : WORDS.off;
      if (say.textContent !== w) say.textContent = w;
      swRow.hidden = !(state === 'live' && allowed && canType);
      sw.setAttribute('aria-checked', String(typing));
      root.dataset.typing = typing ? 'on' : 'off';
      root.dataset.state = state;
      screen.hidden = !(state === 'live' || (state === 'error' && snap));
      loading.hidden = state !== 'loading';
      note.hidden = state === 'live' || state === 'loading' || state === 'error';
      note.textContent = note.hidden ? '' : WORDS[state] || WORDS.none;
      copy.hidden = !snap;
    }
    /* Only rows that changed are written again, so a selection in the others stays. */
    function draw() {
      if (!snap) { rows.replaceChildren(); drawn = []; return; }
      const cur = typing && focused && snap.cursor !== false && !snap.scrolled;
      const model = paint(snap.screen, snap.cx, snap.cy, cur);
      const end = screen.scrollHeight - screen.scrollTop - screen.clientHeight < 8;
      model.forEach((row, i) => {
        const sig = row.map(s => s.c + '\u0001' + s.t).join('\u0002');
        if (drawn[i] === sig && rows.children[i]) return;
        const line = el('div', {className: 't-ln'});
        row.forEach(s => line.append(el('span', {className: s.c, text: s.t})));
        if (!row.length) line.append(el('span', {className: 't-seg', text: ' '}));  // an empty row keeps its height
        if (rows.children[i]) rows.children[i].replaceWith(line); else rows.append(line);
        drawn[i] = sig;
      });
      while (rows.children.length > model.length) rows.lastChild.remove();
      drawn.length = model.length;
      if (end) screen.scrollTop = screen.scrollHeight;
    }
    function update(next) {
      const s = next || {};
      if (s.state !== 'live') {
        const was = state;
        if (typing) setTyping(false);
        snap = null; drawn = []; rows.replaceChildren();
        state = was === 'live' || was === 'ended' ? 'ended' : (s.state in WORDS ? s.state : 'none');
        words(); return;
      }
      snap = s; state = 'live';
      allowed = s.typing_allowed === true;
      if (typing && !allowed) setTyping(false);
      words(); draw();
    }
    function show(next) {
      if (next === 'error' && state === 'error') return;
      if (next !== 'loading' && typing) setTyping(false);
      state = next; words();
    }
    function setTyping(on) {
      if (!on && held) { held = null; ask.hidden = true; }
      const want = !!on && state === 'live' && allowed && canType;
      if (want === typing) { words(); return; }
      typing = want; sent = '';
      words(); draw();
      if (typing) { screen.focus({preventScroll: true}); measure(true); }
      if (typeof o.onTyping === 'function') o.onTyping(typing);
    }
    /* keys go out in small batches, one batch at a time, in the order they were typed */
    function schedule() { if (!timer) timer = setTimeout(() => { timer = null; chain = chain.then(flush, flush); }, 25); }
    async function flush() {
      const all = merge(keys.splice(0, keys.length));
      while (all.length && typing) {
        const items = [];
        while (all.length && items.length < 40) items.push(all.shift());
        const r = typeof o.onKeys === 'function' ? await o.onKeys(items) : {ok: false, status: 0};
        if (r && r.ok) continue;
        if (r && r.status === 403) { if (/is off/.test(r.text || '')) allowed = false; else canType = false; }
        setTyping(false); words();
        return;
      }
    }
    screen.addEventListener('keydown', e => {
      if (!typing) return;
      if (e.key === 'Tab' && e.shiftKey) { e.preventDefault(); setTyping(false); return; }
      const it = toItem(e, hasSel());
      if (!it) return;
      e.preventDefault(); e.stopPropagation();
      keys.push(it); schedule();
    });
    screen.addEventListener('paste', e => {
      e.preventDefault();
      if (!typing) return;
      const t = (e.clipboardData && e.clipboardData.getData('text')) || '';
      const q = pasteAsk(t);
      if (!q) { keys.push(...pasteItems(t)); schedule(); return; }
      held = t; askText.textContent = q; ask.hidden = false; askGo.focus();
    });
    const unask = () => { held = null; ask.hidden = true; if (typing) screen.focus({preventScroll: true}); };
    askGo.addEventListener('click', () => { const t = held; unask(); if (t && typing) { keys.push(...pasteItems(t)); schedule(); } });
    askNo.addEventListener('click', unask);
    ask.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); unask(); } });
    screen.addEventListener('focus', () => { focused = true; draw(); });
    screen.addEventListener('blur', () => { focused = false; draw(); });
    sw.addEventListener('click', e => { e.preventDefault(); setTyping(!typing); });
    copy.addEventListener('click', async () => {
      const s = typeof window.getSelection === 'function' ? window.getSelection() : null;
      const text = hasSel() ? String(s) : plain(snap ? snap.screen : '');
      let ok = false;
      try { await navigator.clipboard.writeText(text); ok = true; } catch (err) { ok = false; }
      copy.textContent = ok ? 'Copied' : 'Select and press Ctrl+C';
      setTimeout(() => { copy.textContent = 'Copy'; }, 1600);
    });
    /* the size: while typing, the helper's screen follows the box (sent once it stays the same for a moment) */
    let sizeTimer = null;
    function measure(now) {
      if (!typing || typeof o.onSize !== 'function') return;
      clearTimeout(sizeTimer);
      sizeTimer = setTimeout(() => {
        const box = screen.getBoundingClientRect(), cell = probe.getBoundingClientRect();
        const cs = typeof getComputedStyle === 'function' ? getComputedStyle(screen) : null;
        const padX = cs ? parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) : 0, padY = cs ? parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) : 0;
        const size = fit(box.width - padX, box.height - padY, cell.width / 10, cell.height);
        if (!size) return;
        const sig = size.cols + 'x' + size.rows;
        if (sig === sent || (snap && snap.cols === size.cols && snap.rows === size.rows)) { sent = sig; return; }
        sent = sig;
        o.onSize(size);
      }, now ? 0 : 250);
    }
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => measure(false)).observe(screen);
    words();
    return {
      el: root, update, show, setTyping,
      typing: () => typing,
      back() { if (typing && document.activeElement !== screen) screen.focus({preventScroll: true}); }
    };
  }
  term.paint = paint; term.toItem = toItem; term.merge = merge; term.pasteItems = pasteItems; term.fit = fit; term.plain = plain; term.lineCount = lineCount; term.pasteAsk = pasteAsk;
  term.WORDS = WORDS;
  UI.term = term;
  if (typeof module === 'object' && module.exports) module.exports = term;
})();
