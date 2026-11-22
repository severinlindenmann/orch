/* The helper's browser, live (ORCH-1493, watch only). The browser add-on's broker sends screen pictures of the
   helper's current page; the dashboard relays them (GET /api/browse/stream, server-sent events). This draws them
   on a canvas scaled to its box, shows the tabs and what the browser stopped as cards, and says the state.
   ORCH-1494 puts it in the ticket (next to the steps), adds Hide, pinch to zoom on a touch screen (the real
   1280-wide picture scaled to the width, never a re-flowed phone page) and the small live preview below.
     UI.browserView({label, onStop() -> Promise<{ok, text}>, onHide()})  -> handle
       handle.el                        the element to put in the page
       handle.hello({generation})       a stream (re)started: the browser this view shows now
       handle.tabs([{title, url, current}])
       handle.frame({jpeg, w, h, at})   a picture (JPEG as base64); a slow page skips pictures, newest wins
       handle.clear()                   the view switched tabs: the old picture goes at once
       handle.event({text, site_text?}) something the browser stopped or closed (a card; site_text is the site's)
       handle.show('connecting'|'lost') while (re)connecting; the last picture stays, greyed
       handle.end({why, final})         the browser ended (final) or no browser is open (not final)
       handle.dispose()
   Pure parts for tests: UI.browserView.ageWords, UI.browserView.clip, UI.browserView.WORDS, UI.browserView.fit,
   UI.browserView.zoom (one pinch step: scale 1..4 around the fingers, the picture never leaves its box).
     UI.browserPeek({onOpen, wide, compact})  -> handle   the small live preview (compact: one row, for a pane or a chat): the ONE way into the live view (ORCH-1494)
       a button with a small picture (at most one new picture every 1.5 s), "The helper is browsing <site>", the
       newest time and one "Helper is driving"; an ended browser is only a quiet line with its time; hidden until
       the stream says hello or end. handle.hello/tabs/frame/clear/end(e, at)/hide()/open(bool)/dispose().
   Site text (titles, addresses, messages) only ever goes in as text, cut short; nothing is recorded: the newest
   picture is kept in memory while the view is open, nothing more.
   Take over and give back (ORCH-1495, desktop first; a phone may tap and pinch). With opts.control = {take(), give(),
   cancel(), stop(), send(events)} (each a Promise of {ok, text}) the view gets Take over and the owner states:
       handle.control({state: 'helper'|'finishing'|'person'|'paused', mine, asking?})   from the stream
   helper: Take over in the bar (asking: one line "The helper needs you" with Take over); finishing (mine): "The
   helper is finishing its step…" with Stop its step now; person (mine): the view fills the window with one fixed
   bar (Give back to the helper, Back to the ticket, Stop browser), keyboard focus on the picture, mouse, wheel,
   keys and pasted text go to the site (Esc goes to the site too; F6 moves to the buttons); paused: Take over again
   or Give back. Input is batched (moves merged, at most every 40 ms) and never kept. Pure parts: UI.browserView.
   toPicture (page point -> picture pixels, null outside the picture), keyOf (a key -> an input event), WORDS. */
(() => {
  'use strict';
  const UI = (typeof window === 'object' ? (window.UI = window.UI || {}) : {});

  /* --- the pure part --- */
  const WORDS = {
    connecting: 'Connecting to the helper’s browser…',
    live: 'Helper is driving',
    lost: 'Connection lost. Trying again…',
    none: 'No browser is open for this ticket.',
    stop: 'Stop browser',
    stopping: 'Stopping…',
    hide: 'Hide',
    browsing: 'The helper is browsing ',
    browsingNone: 'The helper is opening a page',
    watch: 'Open',
    openLabel: 'Open the helper’s browser',
    ended: 'The helper’s browser ended',
    // take over and give back (ORCH-1495)
    take: 'Take over',
    takeAgain: 'Take over again',
    give: 'Give back to the helper',
    back: 'Back to the ticket',
    full: 'Full view',
    stepNow: 'Stop its step now',
    sayFinishing: 'Helper is finishing its step',
    sayYou: 'You are in control',
    sayOther: 'A person is in control',
    sayPaused: 'The helper is paused',
    sayAsking: 'Waiting for you',
    asking: 'The helper needs you in its browser.',
    finishing: 'The helper is finishing its step…',
    finishingMore: 'Then you are in control.',
    you: 'You are in control.',
    youMore: 'The helper is paused. What you type goes to the site, not to orch.',
    youAfter: 'When you give back, the helper starts on a fresh page; what you signed in to stays.',
    youKeys: 'Keys go to the site. F6 moves to these buttons.',
    other: 'A person is in control from another page.',
    otherMore: 'The helper is paused.',
    paused: 'The helper is paused.',
    pausedMore: 'Nobody is in control: the page that had it went away. The helper waits until you give it back.',
    finishingOther: 'Someone is taking over from another page.',
  };
  /* The keys that go to the site (the broker has the same list) and the modifier bits. */
  const KEYS = ['Enter', 'Tab', 'Backspace', 'Delete', 'Escape', 'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'];
  const SHORTCUTS = ['a', 'z', 'y'];
  const mods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  /* One key event -> the input event for the site, 'leave' (F6: to the buttons), 'paste' (let the paste come), or
     null (not sent). A printable character is text (keydown only); IME composition is left alone (desktop first). */
  function keyOf(e, type) {
    if (!e || e.isComposing || e.key === 'Dead' || e.key === 'Process' || typeof e.key !== 'string') return null;
    if (e.key === 'F6') return type === 'down' ? 'leave' : null;
    const cmd = e.ctrlKey || e.metaKey;
    if (KEYS.includes(e.key)) return {t: 'key', type, key: e.key, mod: mods(e)};
    if (cmd && e.key.toLowerCase() === 'v') return 'paste';
    if (cmd && SHORTCUTS.includes(e.key.toLowerCase())) return {t: 'key', type, key: e.key.toLowerCase(), mod: mods(e)};
    if (!cmd && [...e.key].length === 1) return type === 'down' ? {t: 'text', text: e.key} : null;
    return null;
  }
  /* A point on the page -> picture pixels of a fw x fh picture drawn in box r (object-fit contain: letterboxed),
     null outside the picture (never moved to its edge). */
  function toPicture(cx, cy, r, fw, fh) {
    if (!r || !r.width || !r.height || !fw || !fh) return null;
    const k = Math.min(r.width / fw, r.height / fh), ox = (r.width - fw * k) / 2, oy = (r.height - fh * k) / 2;
    const x = (cx - r.left - ox) / k, y = (cy - r.top - oy) / k;
    if (!(x >= 0 && y >= 0 && x < fw && y < fh)) return null;
    return {x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10};
  }
  const SEND_EVERY = 40;  // ms between two input batches
  const SEND_MAX = 30;  // events in one batch (the broker takes 40)
  const clip = (s, n) => { const t = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t; };
  /* How old the newest picture is, in plain words ('' while it is fresh). A quiet page sends no new pictures:
     that is still live, so this never says "lost". */
  function ageWords(at, now) {
    const s = Math.max(0, Math.round((now - at * 1000) / 1000));
    if (!at || s < 10) return '';
    if (s < 60) return 'Last change ' + s + ' s ago';
    const m = Math.round(s / 60);
    return 'Last change ' + m + ' min ago';
  }
  /* The picture's size inside a box of width bw, keeping its shape. */
  const fit = (w, h, bw) => (!w || !h || !bw) ? {w: 0, h: 0} : {w: Math.round(bw), h: Math.round(h * bw / w)};
  /* One pinch (or wheel) step on a picture of box size bw x bh: z = {s, x, y} (scale, then shift in px, applied as
     translate(x, y) scale(s) from the top left). The point under (cx, cy) stays under the fingers; scale 1..4; the
     picture always covers its box, so it never slides out of sight. */
  const ZOOM_MAX = 4;
  function zoom(z, factor, cx, cy, bw, bh) {
    const s = Math.min(ZOOM_MAX, Math.max(1, z.s * factor));
    const k = s / z.s;
    let x = cx - (cx - z.x) * k, y = cy - (cy - z.y) * k;
    x = Math.min(0, Math.max(bw - bw * s, x)); y = Math.min(0, Math.max(bh - bh * s, y));
    return s === 1 ? {s: 1, x: 0, y: 0} : {s, x, y};
  }
  /* The site of an address, for one plain line ('' when it is not one). */
  function site(url) { try { return new URL(String(url)).hostname.replace(/^www\./, ''); } catch (e) { return ''; } }

  /* --- the element --- */
  const make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  function browserView(opts) {
    const o = opts || {};
    const el = make('section', 'bview');
    el.setAttribute('aria-label', o.label || 'The helper’s browser');
    el.dataset.state = 'connecting';
    const bar = make('div', 'bview-bar');
    const say = make('span', 'bview-say meta', WORDS.connecting);
    say.setAttribute('role', 'status');
    const age = make('span', 'bview-age meta');
    const stop = make('button', 'btn sm', WORDS.stop);
    stop.type = 'button';
    stop.hidden = true;
    const take = make('button', 'btn outline sm', WORDS.take);
    take.type = 'button';
    take.hidden = true;
    bar.append(say, age, stop);
    if (o.onHide) { const hide = make('button', 'btn ghost sm', WORDS.hide); hide.type = 'button'; hide.addEventListener('click', () => o.onHide()); bar.append(hide); }
    if (o.control) bar.insertBefore ? bar.insertBefore(take, stop) : bar.append(take);  // Take over before Stop
    const tabs = make('ol', 'bview-tabs');
    tabs.setAttribute('aria-label', 'Tabs');
    tabs.hidden = true;
    const cards = make('div', 'bview-cards');
    const screen = make('div', 'bview-screen');
    const canvas = make('canvas', 'bview-canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Picture of the helper’s browser');
    const state = make('p', 'bview-state meta');
    state.hidden = true;
    screen.append(canvas, state);
    /* The owner bar (ORCH-1495): one fixed bar while taking over, in control, paused or asked for. */
    const ctl = make('div', 'bview-ctl');
    ctl.hidden = true;
    const ctlText = make('div', 'bview-ctl-text');
    const ctlLine = make('p', 'bview-ctl-line');
    ctlLine.setAttribute('role', 'status');
    const ctlMore = make('p', 'bview-ctl-more meta');
    const ctlNote = make('p', 'bview-ctl-note meta');
    ctlNote.setAttribute('role', 'status');
    ctlText.append(ctlLine, ctlMore, ctlNote);
    const ctlActs = make('div', 'bview-ctl-acts');
    ctl.append(ctlText, ctlActs);
    el.append(bar, tabs, cards, screen, ctl);  // the owner bar shows first (CSS order); last in the tree

    /* Pinch to zoom (touch) and Ctrl + wheel: only the picture zooms, inside its box; a double tap goes back. */
    let z = {s: 1, x: 0, y: 0};
    const touches = new Map();
    let pinch = null, lastTap = 0;
    const applyZoom = next => {
      z = next;
      canvas.style.transform = z.s === 1 ? '' : 'translate(' + z.x + 'px,' + z.y + 'px) scale(' + z.s + ')';
      if (z.s === 1) delete screen.dataset.zoomed; else screen.dataset.zoomed = 'true';
    };
    const box = () => { const r = screen.getBoundingClientRect ? screen.getBoundingClientRect() : {left: 0, top: 0, width: 0, height: 0}; return r; };
    const mid = () => { const p = [...touches.values()]; return {x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2, d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1}; };
    screen.addEventListener('pointerdown', e => {
      if (e.pointerType !== 'touch') return;
      touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
      if (touches.size === 2) pinch = mid();
      else if (touches.size === 1) {
        const now = Date.now();
        if (now - lastTap < 300) applyZoom({s: 1, x: 0, y: 0});
        lastTap = now;
      }
    });
    screen.addEventListener('pointermove', e => {
      const was = touches.get(e.pointerId);
      if (!was) return;
      const r = box();
      touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
      if (touches.size === 2 && pinch) {
        const m = mid();
        const next = zoom(z, m.d / pinch.d, m.x - r.left, m.y - r.top, r.width, r.height);
        next.x = Math.min(0, Math.max(r.width - r.width * next.s, next.x + m.x - pinch.x));
        next.y = Math.min(0, Math.max(r.height - r.height * next.s, next.y + m.y - pinch.y));
        applyZoom(next.s === 1 ? {s: 1, x: 0, y: 0} : next);
        pinch = m;
      } else if (touches.size === 1 && z.s > 1) {  // one finger moves a zoomed picture
        applyZoom({s: z.s, x: Math.min(0, Math.max(r.width - r.width * z.s, z.x + e.clientX - was.x)), y: Math.min(0, Math.max(r.height - r.height * z.s, z.y + e.clientY - was.y))});
      }
    });
    const up = e => { touches.delete(e.pointerId); if (touches.size < 2) pinch = null; };
    screen.addEventListener('pointerup', up);
    screen.addEventListener('pointercancel', up);
    screen.addEventListener('wheel', e => {
      if (!e.ctrlKey) return;  // a plain wheel scrolls the page
      e.preventDefault();
      const r = box();
      applyZoom(zoom(z, e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top, r.width, r.height));
    }, {passive: false});

    let generation = '', lastAt = 0, pending = null, decoding = false, disposed = false, ended = false, epoch = 0;
    const setState = (s, words) => { el.dataset.state = s; say.textContent = words || WORDS[s] || ''; };

    async function draw() {
      if (decoding || !pending || disposed) return;
      decoding = true;
      const f = pending; pending = null;
      const mine = epoch;
      try {
        const bytes = Uint8Array.from(atob(f.jpeg), c => c.charCodeAt(0));
        const img = await createImageBitmap(new Blob([bytes], {type: 'image/jpeg'}));
        if (!disposed && !pending && mine === epoch) {  // a newer picture, a tab switch or the end came meanwhile: skip it
          canvas.width = img.width; canvas.height = img.height;
          canvas.getContext('2d').drawImage(img, 0, 0);
        }
        if (img.close) img.close();
      } catch (e) { /* a broken picture: the next one comes */ }
      decoding = false;
      if (pending) draw();
    }
    const tick = setInterval(() => { age.textContent = ended ? '' : ageWords(lastAt, Date.now()); }, 5000);

    stop.addEventListener('click', async () => {
      if (!o.onStop) return;
      stop.disabled = true; stop.textContent = WORDS.stopping;
      const r = await o.onStop(generation);
      if (!r || !r.ok) { stop.disabled = false; stop.textContent = WORDS.stop; }
    });

    /* --- take over and give back --- */
    const c = o.control || null;
    let ctlState = {state: 'helper', mine: false}, full = false, live = false, frameW = 0, frameH = 0;
    const queue = [], downKeys = new Map();
    let sendTimer = 0, sending = false;
    const driving = () => !!c && live && ctlState.state === 'person' && ctlState.mine;
    const btn = (words, cls, fn) => { const b = make('button', 'btn sm ' + cls, words); b.type = 'button'; b.addEventListener('click', async () => { b.disabled = true; try { await fn(); } finally { b.disabled = false; } }); return b; };
    const note = r => { ctlNote.textContent = r && !r.ok && r.text ? clip(r.text, 160) : r && r.ok && r.text ? clip(r.text, 200) : ''; };
    const act = async fn => { const r = await fn(); note(r); return r; };
    const setFull = on => {
      full = !!on && driving();
      if (full) el.dataset.full = 'true'; else delete el.dataset.full;
      paint();
      if (full && canvas.focus) canvas.focus();
    };
    function flush() {
      sendTimer = 0;
      if (sending || !queue.length || !driving()) { if (!driving()) queue.length = 0; return; }
      const batch = queue.splice(0, SEND_MAX);
      sending = true;
      Promise.resolve(c.send(batch, {w: frameW, h: frameH})).then(r => { if (r && !r.ok) note(r); }, () => {}).finally(() => {
        sending = false;
        if (queue.length && !sendTimer) sendTimer = setTimeout(flush, SEND_EVERY);
      });
    }
    function push(ev) {
      if (!driving() || !frameW) return;
      const last = queue[queue.length - 1];
      if (ev.t === 'move' && last && last.t === 'move') queue[queue.length - 1] = ev;  // only the newest move
      else if (ev.t === 'text' && last && last.t === 'text' && last.text.length + ev.text.length <= 2000) last.text += ev.text;
      else queue.push(ev);
      if (!sendTimer) sendTimer = setTimeout(flush, SEND_EVERY);
    }
    const at = e => toPicture(e.clientX, e.clientY, canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : null, frameW, frameH);
    const BTN = ['left', 'middle', 'right'];
    let tap = null;
    canvas.addEventListener('pointerdown', e => {
      if (!driving()) return;
      if (canvas.focus) canvas.focus();
      const p = at(e);
      if (!p) return;
      if (e.pointerType === 'touch') { tap = touches.size <= 1 ? {p, x: e.clientX, y: e.clientY, t: Date.now()} : null; return; }
      if (e.preventDefault) e.preventDefault();
      push({t: 'down', x: p.x, y: p.y, button: BTN[e.button] || 'left', count: Math.min(3, Math.max(1, e.detail || 1)), mod: mods(e)});
    });
    canvas.addEventListener('pointermove', e => {
      if (!driving() || e.pointerType === 'touch') { if (tap && Math.hypot(e.clientX - tap.x, e.clientY - tap.y) > 10) tap = null; return; }
      const p = at(e);
      if (p) push({t: 'move', x: p.x, y: p.y, mod: mods(e)});
    });
    canvas.addEventListener('pointerup', e => {
      if (!driving()) return;
      if (e.pointerType === 'touch') {  // a tap on a phone: one click where the finger was (pinch stays zoom)
        if (tap && touches.size === 0 && Date.now() - tap.t < 500) push({t: 'down', x: tap.p.x, y: tap.p.y, button: 'left', count: 1}), push({t: 'up', x: tap.p.x, y: tap.p.y, button: 'left'});
        tap = null; return;
      }
      const p = at(e) || null;
      if (p) push({t: 'up', x: p.x, y: p.y, button: BTN[e.button] || 'left', mod: mods(e)});
    });
    canvas.addEventListener('contextmenu', e => { if (driving() && e.preventDefault) e.preventDefault(); });
    canvas.addEventListener('wheel', e => {
      if (!driving() || e.ctrlKey) return;  // Ctrl + wheel still zooms the picture
      e.preventDefault();
      const p = at(e);
      if (p) push({t: 'wheel', x: p.x, y: p.y, dx: Math.max(-5000, Math.min(5000, e.deltaX)), dy: Math.max(-5000, Math.min(5000, e.deltaY)), mod: mods(e)});
    }, {passive: false});
    const onKey = type => e => {
      if (!driving()) return;
      const k = keyOf(e, type);
      if (k === 'leave') { e.preventDefault(); const first = ctlActs.querySelector ? ctlActs.querySelector('button') : ctlActs.children[0]; if (first && first.focus) first.focus(); return; }
      if (!k || k === 'paste') return;
      e.preventDefault();
      if (k.t === 'key') { if (type === 'down') downKeys.set(k.key, k.mod); else downKeys.delete(k.key); }
      push(k);
    };
    canvas.addEventListener('keydown', onKey('down'));
    canvas.addEventListener('keyup', onKey('up'));
    canvas.addEventListener('paste', e => {
      if (!driving()) return;
      e.preventDefault();
      const text = e.clipboardData ? e.clipboardData.getData('text') : '';
      if (text) push({t: 'paste', text: text.slice(0, 2000)});
    });
    canvas.addEventListener('blur', () => {  // focus left the picture: let go of the keys it held
      for (const [key, mod] of downKeys) push({t: 'key', type: 'up', key, mod});
      downKeys.clear();
    });
    take.addEventListener('click', () => act(c.take));

    function paint() {
      const st = ctlState.state, mine = !!ctlState.mine, asking = st === 'helper' && ctlState.asking;
      take.hidden = !c || !live || st !== 'helper' || !!asking;
      canvas.tabIndex = driving() ? 0 : -1;
      el.dataset.control = st;
      if (!live) { ctl.hidden = true; return; }
      const acts = [];
      let line = '', more = '', lead = '';
      if (asking && c) { lead = WORDS.asking; line = clip(ctlState.asking, 200); acts.push(btn(WORDS.take, 'primary', () => act(c.take))); }
      else if (st === 'finishing') { lead = mine ? WORDS.finishing : WORDS.finishingOther; line = mine ? WORDS.finishingMore : ''; if (mine && c) acts.push(btn(WORDS.stepNow, 'outline', () => act(c.cancel))); }
      else if (st === 'person' && mine) {
        lead = WORDS.you; line = WORDS.youMore; more = full ? WORDS.youAfter + ' ' + WORDS.youKeys : WORDS.youAfter;
        if (c) acts.push(btn(WORDS.give, 'primary', () => act(c.give)), full ? btn(WORDS.back, 'ghost', () => setFull(false)) : btn(WORDS.full, 'outline', () => setFull(true)));
        if (c && full && o.onStop) acts.push(btn(WORDS.stop, 'ghost', () => o.onStop(generation)));
      } else if (st === 'person') { lead = WORDS.other; line = WORDS.otherMore; }
      else if (st === 'paused') { lead = WORDS.paused; line = WORDS.pausedMore; if (c) acts.push(btn(WORDS.give, 'primary', () => act(c.give)), btn(WORDS.takeAgain, 'outline', () => act(c.take))); }
      ctl.hidden = !lead;
      ctl.dataset.kind = asking ? 'needs' : st;
      const b = make('b', '', lead);
      ctlLine.replaceChildren(b, document.createTextNode(line ? ' ' + line : ''));
      ctlMore.textContent = more; ctlMore.hidden = !more;
      ctlActs.replaceChildren(...acts);
      if (st === 'finishing' && mine) { const sp = make('span', 'spinner'); sp.setAttribute('aria-hidden', 'true'); ctlLine.prepend(sp); }
      const words = asking ? WORDS.sayAsking : st === 'finishing' ? WORDS.sayFinishing : st === 'person' ? (mine ? WORDS.sayYou : WORDS.sayOther) : st === 'paused' ? WORDS.sayPaused : WORDS.live;
      if (el.dataset.state === 'live') say.textContent = words;
    }
    const setControl = next => {
      const was = driving();
      ctlState = Object.assign({state: 'helper', mine: false}, next || {});
      if (!driving()) { queue.length = 0; downKeys.clear(); }
      if (driving() && !was) { note(null); full = true; el.dataset.full = 'true'; }
      if (!driving() && full) { full = false; delete el.dataset.full; }
      paint();
      if (driving() && !was && canvas.focus) canvas.focus();
    };

    return {
      el,
      hello(h) { generation = (h && h.generation) || ''; ended = false; live = true; state.hidden = true; stop.hidden = !o.onStop; stop.disabled = false; stop.textContent = WORDS.stop; setState('live'); paint(); },
      control(next) { setControl(next); },
      tabs(list) {
        tabs.replaceChildren(...(Array.isArray(list) ? list : []).slice(0, 20).map(t => {
          const li = make('li', 'bview-tab', clip(t.title || t.url || 'New tab', 40));
          li.title = clip(t.url, 200);
          if (t.current) li.setAttribute('aria-current', 'true');
          return li;
        }));
        tabs.hidden = tabs.children.length < 2;
      },
      frame(f) { if (!f || typeof f.jpeg !== 'string') return; lastAt = f.at || 0; frameW = f.w || 0; frameH = f.h || 0; age.textContent = ageWords(lastAt, Date.now()); pending = f; if (el.dataset.state !== 'live') { setState('live'); paint(); } draw(); },
      clear() { pending = null; epoch += 1; const c = canvas.getContext && canvas.getContext('2d'); if (c) c.clearRect(0, 0, canvas.width, canvas.height); },
      event(ev) {
        if (!ev || !ev.text) return;
        const card = make('div', 'bview-card');
        card.append(make('span', '', clip(ev.text, 160)));
        if (ev.site_text) { const q = make('q', 'bview-site', clip(ev.site_text, 160)); card.append(q); }
        cards.prepend(card);
        while (cards.children.length > 3) cards.lastChild.remove();
      },
      show(s) { if (!ended) { setState(s === 'lost' ? 'lost' : 'connecting'); setControl(null); } },
      end(e) {
        const why = clip((e && e.why) || WORDS.none, 160);
        ended = true; live = false; stop.hidden = true; pending = null; epoch += 1; setControl(null);
        setState((e && e.final) ? 'ended' : 'none', why);  // said once, in the line on top
        tabs.hidden = true; state.hidden = true;
      },
      dispose() { disposed = true; clearInterval(tick); clearTimeout(sendTimer); el.remove(); },
    };
  }

  /* --- the small live preview (ORCH-1494) --- */
  const PEEK_EVERY = 1500;  // ms between two pictures in the small preview: it only needs to show that it moves
  function browserPeek(opts) {
    const o = opts || {};
    const el = make('div', 'bpeek' + (o.wide ? ' wide' : o.compact ? ' compact' : ''));
    el.hidden = true;
    const btn = make('button', 'bpeek-btn');
    btn.type = 'button';
    btn.setAttribute('aria-expanded', 'false');
    const pic = make('span', 'bpeek-pic');
    const canvas = make('canvas', 'bpeek-canvas');
    canvas.setAttribute('aria-hidden', 'true');
    pic.append(canvas);
    const text = make('span', 'bpeek-text');
    const what = make('span', 'bpeek-what', WORDS.browsingNone);
    const when = make('span', 'bpeek-when meta');
    text.append(what, when);
    const foot = make('span', 'bpeek-foot');
    const mkPill = (kind, words) => (UI.helperPill ? UI.helperPill(kind, words) : make('span', 'pill', words));
    let pill = mkPill('working', WORDS.live);
    const go = make('span', 'bpeek-go', WORDS.watch);
    foot.append(pill, go);
    btn.append(pic, text, foot);
    const ended = make('p', 'bpeek-ended meta');
    ended.hidden = true;
    el.append(btn, ended);
    btn.addEventListener('click', () => { if (o.onOpen) o.onOpen(); });

    let pending = null, busy = false, last = 0, timer = 0, disposed = false, epoch = 0, host = '';
    const clock = at => (UI.clock ? UI.clock(new Date(at * 1000)) : '');
    const label = () => btn.setAttribute('aria-label', WORDS.openLabel + ': ' + (host ? WORDS.browsing + host : WORDS.browsingNone) + (when.textContent ? ', ' + when.textContent : ''));
    async function draw() {
      if (busy || !pending || disposed) return;
      const wait = PEEK_EVERY - (Date.now() - last);
      if (wait > 0) { clearTimeout(timer); timer = setTimeout(draw, wait); return; }
      busy = true; last = Date.now();
      const f = pending; pending = null;
      const mine = epoch;
      try {
        const bytes = Uint8Array.from(atob(f.jpeg), c => c.charCodeAt(0));
        const img = await createImageBitmap(new Blob([bytes], {type: 'image/jpeg'}));
        if (!disposed && mine === epoch) { canvas.width = img.width; canvas.height = img.height; canvas.getContext('2d').drawImage(img, 0, 0); }
        if (img.close) img.close();
      } catch (e) { /* a broken picture: the next one comes */ }
      busy = false;
      if (pending) draw();
    }
    const live = () => { el.hidden = false; btn.hidden = false; ended.hidden = true; el.dataset.state = 'live'; };
    label();
    return {
      el,
      hello() { live(); },
      tabs(list) {
        const cur = (Array.isArray(list) ? list : []).find(t => t && t.current) || (Array.isArray(list) ? list[0] : null);
        host = clip(site(cur && cur.url), 60);
        if (el.dataset.control === 'asking') { label(); return; }  // the helper's question stays
        if (host) { const b = make('span', 'bpeek-site', host); what.replaceChildren(document.createTextNode(WORDS.browsing), b); }
        else what.textContent = WORDS.browsingNone;
        label();
      },
      frame(f) {
        if (!f || typeof f.jpeg !== 'string') return;
        if (el.dataset.state !== 'live') live();
        if (f.at) when.textContent = clock(f.at);  // the newest time, always (fix 8)
        label();
        pending = f; draw();
      },
      clear() { pending = null; epoch += 1; },
      /* An ended browser: no picture any more, one quiet line with the time it ended (seconds since 1970). */
      end(e, at) {
        pending = null; epoch += 1; clearTimeout(timer);
        btn.hidden = true; ended.hidden = false; el.hidden = false; el.dataset.state = 'ended';
        ended.textContent = WORDS.ended + (at ? ' at ' + clock(at) : '') + '.';
      },
      hide() { el.hidden = true; delete el.dataset.state; pending = null; epoch += 1; },
      /* Who drives (ORCH-1495): the pill says it; the helper asking for a person is "Waiting for you" with its why. */
      control(c) {
        const st = (c && c.state) || 'helper', asking = st === 'helper' && c && c.asking;
        const [kind, words] = asking ? ['you', WORDS.sayAsking] : st === 'finishing' ? ['working', WORDS.sayFinishing] :
          st === 'person' ? ['working', c.mine ? WORDS.sayYou : WORDS.sayOther] : st === 'paused' ? ['waiting', WORDS.sayPaused] : ['working', WORDS.live];
        const next = mkPill(kind, words);
        pill.replaceWith ? pill.replaceWith(next) : foot.replaceChildren(next, go);
        pill = next;
        el.dataset.control = asking ? 'asking' : st;
        if (asking) what.textContent = WORDS.asking + ' ' + clip(c.asking, 120);
        else if (what.textContent.startsWith(WORDS.asking)) what.textContent = host ? WORDS.browsing + host : WORDS.browsingNone;
        label();
      },
      open(on) { btn.setAttribute('aria-expanded', String(!!on)); go.hidden = !!on; },
      dispose() { disposed = true; clearTimeout(timer); el.remove(); },
    };
  }
  browserPeek.PEEK_EVERY = PEEK_EVERY;
  browserPeek.site = site;
  UI.browserPeek = browserPeek;

  browserView.zoom = zoom;
  browserView.ageWords = ageWords;
  browserView.clip = clip;
  browserView.fit = fit;
  browserView.WORDS = WORDS;
  browserView.toPicture = toPicture;
  browserView.keyOf = keyOf;
  browserView.KEYS = KEYS;
  UI.browserView = browserView;
  if (typeof module === 'object' && module.exports) module.exports = browserView;
})();
