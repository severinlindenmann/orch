/* The helper's browser, live (ORCH-1493, watch only). The browser add-on's broker sends screen pictures of the
   helper's current page; the dashboard relays them (GET /api/browse/stream, server-sent events). This draws them
   on a canvas scaled to its box, shows the tabs and what the browser stopped as cards, and says the state.
   Placement (ticket, Browser page, small previews) and its words come with ORCH-1494.
     UI.browserView({label, onStop() -> Promise<{ok, text}>})  -> handle
       handle.el                        the element to put in the page
       handle.hello({generation})       a stream (re)started: the browser this view shows now
       handle.tabs([{title, url, current}])
       handle.frame({jpeg, w, h, at})   a picture (JPEG as base64); a slow page skips pictures, newest wins
       handle.clear()                   the view switched tabs: the old picture goes at once
       handle.event({text, site_text?}) something the browser stopped or closed (a card; site_text is the site's)
       handle.show('connecting'|'lost') while (re)connecting; the last picture stays, greyed
       handle.end({why, final})         the browser ended (final) or no browser is open (not final)
       handle.dispose()
   Pure parts for tests: UI.browserView.ageWords, UI.browserView.clip, UI.browserView.WORDS, UI.browserView.fit.
   Site text (titles, addresses, messages) only ever goes in as text, cut short; nothing is recorded: the newest
   picture is kept in memory while the view is open, nothing more. */
(() => {
  'use strict';
  const UI = (typeof window === 'object' ? (window.UI = window.UI || {}) : {});

  /* --- the pure part --- */
  const WORDS = {
    connecting: 'Connecting to the helper’s browser…',
    live: 'Watching the helper’s browser',
    lost: 'Connection lost. Trying again…',
    none: 'No browser is open for this ticket.',
    stop: 'Stop browser',
    stopping: 'Stopping…',
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
  browserView.ageWords = ageWords;
  browserView.clip = clip;
  browserView.fit = fit;
  browserView.WORDS = WORDS;
  UI.browserView = browserView;
  if (typeof module === 'object' && module.exports) module.exports = browserView;
})();
