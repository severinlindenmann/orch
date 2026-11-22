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
     UI.browserPeek({onOpen, wide})  -> handle   the small live preview: the ONE way into the live view (ORCH-1494)
       a button with a small picture (at most one new picture every 1.5 s), "The helper is browsing <site>", the
       newest time and one "Helper is driving"; an ended browser is only a quiet line with its time; hidden until
       the stream says hello or end. handle.hello/tabs/frame/clear/end(e, at)/hide()/open(bool)/dispose().
   Site text (titles, addresses, messages) only ever goes in as text, cut short; nothing is recorded: the newest
   picture is kept in memory while the view is open, nothing more. */
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
  };
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
    bar.append(say, age, stop);
    if (o.onHide) { const hide = make('button', 'btn ghost sm', WORDS.hide); hide.type = 'button'; hide.addEventListener('click', () => o.onHide()); bar.append(hide); }
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
    el.append(bar, tabs, cards, screen);

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

    return {
      el,
      hello(h) { generation = (h && h.generation) || ''; ended = false; state.hidden = true; stop.hidden = !o.onStop; stop.disabled = false; stop.textContent = WORDS.stop; setState('live'); },
      tabs(list) {
        tabs.replaceChildren(...(Array.isArray(list) ? list : []).slice(0, 20).map(t => {
          const li = make('li', 'bview-tab', clip(t.title || t.url || 'New tab', 40));
          li.title = clip(t.url, 200);
          if (t.current) li.setAttribute('aria-current', 'true');
          return li;
        }));
        tabs.hidden = tabs.children.length < 2;
      },
      frame(f) { if (!f || typeof f.jpeg !== 'string') return; lastAt = f.at || 0; age.textContent = ageWords(lastAt, Date.now()); pending = f; if (el.dataset.state !== 'live') setState('live'); draw(); },
      clear() { pending = null; epoch += 1; const c = canvas.getContext && canvas.getContext('2d'); if (c) c.clearRect(0, 0, canvas.width, canvas.height); },
      event(ev) {
        if (!ev || !ev.text) return;
        const card = make('div', 'bview-card');
        card.append(make('span', '', clip(ev.text, 160)));
        if (ev.site_text) { const q = make('q', 'bview-site', clip(ev.site_text, 160)); card.append(q); }
        cards.prepend(card);
        while (cards.children.length > 3) cards.lastChild.remove();
      },
      show(s) { if (!ended) setState(s === 'lost' ? 'lost' : 'connecting'); },
      end(e) {
        const why = clip((e && e.why) || WORDS.none, 160);
        ended = true; stop.hidden = true; pending = null; epoch += 1;
        setState((e && e.final) ? 'ended' : 'none', why);  // said once, in the line on top
        tabs.hidden = true; state.hidden = true;
      },
      dispose() { disposed = true; clearInterval(tick); el.remove(); },
    };
  }

  /* --- the small live preview (ORCH-1494) --- */
  const PEEK_EVERY = 1500;  // ms between two pictures in the small preview: it only needs to show that it moves
  function browserPeek(opts) {
    const o = opts || {};
    const el = make('div', 'bpeek' + (o.wide ? ' wide' : ''));
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
    const pill = (UI.helperPill ? UI.helperPill('working', WORDS.live) : make('span', 'pill', WORDS.live));
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
        what.textContent = host ? WORDS.browsing + host : WORDS.browsingNone;
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
  UI.browserView = browserView;
  if (typeof module === 'object' && module.exports) module.exports = browserView;
})();
