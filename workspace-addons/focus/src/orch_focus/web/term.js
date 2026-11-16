// The helper's screen in the dashboard: watch it above the message box or in the Screen tab; typing only with "Let me type" (fb17).
// A small renderer for the screen text tmux hands over (colours, bold, reverse, cursor); textContent only.
// Reading is open to the dashboard page; typing is for the person's dashboard session (the server decides).
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, TID} = S;

  /* the 16 base colours come from the master tokens (classes in focus.css); anything else keeps the default */
  const SGR_FG = {30: 0, 31: 1, 32: 2, 33: 3, 34: 4, 35: 5, 36: 6, 37: 7, 90: 8, 91: 9, 92: 10, 93: 11, 94: 12, 95: 13, 96: 14, 97: 15};
  function paint(text, cx, cy, showCursor) {
    const lines = String(text || '').split('\n');
    while (lines.length > 1 && lines.length - 1 > cy && !lines[lines.length - 1].replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').trim()) lines.pop();  /* the blank rows under the last line are not drawn */
    const out = [];
    let st = {fg: null, bold: false, rev: false, dim: false};
    lines.forEach((line, y) => {
      const row = h('div', {class: 't-ln'});
      let col = 0, buf = '';
      const flush = () => {
        if (!buf) return;
        const cls = ['t-seg'].concat(st.fg != null ? ['t-c' + st.fg] : [], st.bold ? ['t-b'] : [], st.dim ? ['t-d'] : [], st.rev ? ['t-r'] : []).join(' ');
        row.append(h('span', {class: cls, text: buf})); buf = '';
      };
      const put = ch => {
        if (showCursor && y === cy && col === cx) { flush(); const cls = ['t-seg', 't-cur'].concat(st.fg != null ? ['t-c' + st.fg] : []).join(' '); row.append(h('span', {class: cls, text: ch})); col++; return; }
        buf += ch; col++;
      };
      for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (c === '\x1b' && line[i + 1] === '[') {
          const m = /^\x1b\[([0-9;]*)([A-Za-z])/.exec(line.slice(i));
          if (m) {
            i += m[0].length - 1;
            if (m[2] === 'm') {
              flush();
              const codes = (m[1] || '0').split(';').map(Number);
              for (let k = 0; k < codes.length; k++) {
                const n = codes[k];
                if (n === 0) st = {fg: null, bold: false, rev: false, dim: false};
                else if (n === 1) st.bold = true; else if (n === 2) st.dim = true; else if (n === 7) st.rev = true;
                else if (n === 22) { st.bold = false; st.dim = false; } else if (n === 27) st.rev = false;
                else if (n === 39) st.fg = null; else if (n in SGR_FG) st.fg = SGR_FG[n];
                else if (n === 38 || n === 48) k += codes[k + 1] === 5 ? 2 : codes[k + 1] === 2 ? 4 : 0;  /* 256 / true colour: skipped */
              }
            }
            continue;
          }
        }
        put(c);
      }
      if (showCursor && y === cy && col <= cx) { flush(); row.append(h('span', {class: 't-seg', text: ' '.repeat(cx - col)}), h('span', {class: 't-seg t-cur', text: ' '})); }
      flush();
      if (!row.childNodes.length) row.append(h('span', {class: 't-seg', text: ' '}));  /* an empty line keeps its height */
      out.push(row);
    });
    return out;
  }

  const KEYS = {Enter: 'Enter', Backspace: 'BSpace', Tab: 'Tab', Escape: 'Escape', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown'};
  /* a key event becomes one item for the server: literal text, or a name from its list; null = not ours */
  function toItem(e) {
    if (e.metaKey || e.altKey) return null;
    if (e.ctrlKey) return !e.shiftKey && (e.key === 'c' || e.key === 'd') ? {k: 'C-' + e.key} : null;
    if (e.key === 'Tab' && e.shiftKey) return null;  /* Shift+Tab leaves the terminal */
    if (KEYS[e.key]) return {k: KEYS[e.key]};
    return e.key.length === 1 ? {t: e.key} : null;
  }
  const merge = items => items.reduce((acc, it) => { const last = acc[acc.length - 1]; if (it.t && last && last.t && last.t.length + it.t.length <= 2000) last.t += it.t; else acc.push({...it}); return acc; }, []);

  /* The strip's one line: the screen's last line that says something (not a frame, not a bare prompt). */
  const stripAnsi = t => String(t || '').replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
  const sayings = text => stripAnsi(text).split('\n').map(l => l.replace(/[│┃║╭╮╰╯─━═┌┐└┘├┤┬┴┼]/g, ' ').replace(/\s+/g, ' ').trim()).filter(l => /[\p{L}\p{N}]/u.test(l));
  function lastLine(text) {
    const all = sayings(text), line = all[all.length - 1] || '';
    return line.length > 160 ? line.slice(0, 159) + '…' : line;
  }
  /* what the helper asks on its screen: the newest question-like line of the last few */
  function questionLine(text) {
    const tail = sayings(text).slice(-6).reverse();
    const q = tail.find(l => /\?|\(y\/n\)|\[y\/n\]|press enter|do you want/i.test(l)) || tail[0] || '';
    return q.length > 160 ? q.slice(0, 159) + '…' : q;
  }

  /* One screen, two ways in: the dock above the message box (a one-line strip, or a panel) and the Screen tab hold
     the same element, so there is one poller, one painter and one set of states. */
  function mount(stage) {
    const OPEN = 'focus-screen-open', HEIGHT = 'focus-screen-height';
    const keep = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* not kept */ } };
    const kept = k => { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } };
    const last = h('span', {class: 'session-dock-last', text: 'Connecting to the helper’s screen…'});
    const typingSwitch = h('input', {class: 'switch', type: 'checkbox', role: 'switch', 'aria-label': 'Let me type into the helper’s screen'});
    const typingLabel = h('label', {hidden: true}, typingSwitch, ' Let me type');
    const whole = h('button', {class: 'btn ghost icon sm', type: 'button', icon: 'expand', title: 'Use the whole page', 'aria-label': 'Use the whole page'});
    const chev = h('span', {class: 'dock-chev', 'aria-hidden': 'true', icon: 'chevron-down'});
    const toggle = h('button', {class: 'btn ghost icon sm', type: 'button', title: 'Show (Ctrl+`)', 'aria-label': 'Show the helper’s screen', 'aria-expanded': 'false'}, chev);
    const tools = h('span', {class: 'session-dock-tools'}, typingLabel, whole);
    const head = h('div', {class: 'session-dock-h'}, h('span', {class: 'live-dot', 'aria-hidden': 'true'}), h('b', {text: 'Helper’s screen'}), last, h('span', {class: 'grow'}), tools, toggle);
    const askText = h('span', {class: 'ask-text'});
    const ask = h('div', {class: 'ask-line', role: 'status', hidden: true}, askText);
    const body = h('div', {class: 'session-dock-b', tabindex: '0', role: 'group', 'data-term': '', 'aria-label': 'Live screen of the helper'});
    const loading = h('div', {class: 'session-dock-state', hidden: true}, h('span', {class: 'skeleton line'}), h('span', {class: 'skeleton line'}), h('span', {class: 'skeleton line short'}));
    const retry = h('button', {class: 'btn sm', type: 'button', text: 'Try again now'});
    const failed = h('div', {class: 'session-dock-state', hidden: true}, h('span', {text: 'The screen stopped updating. orch keeps trying; the helper keeps working.'}), h('span', {}, retry));
    const ended = h('div', {class: 'session-dock-state', hidden: true}, h('span', {text: 'The helper’s screen has closed. Its steps stay in Live.'}));
    const foot = h('div', {class: 'session-dock-foot'}, h('span', {text: 'Watching. Your messages go through the box below.'}));
    const dock = h('section', {class: 'session-dock peek', 'aria-label': 'The helper’s screen', hidden: true}, head, ask, body, loading, failed, ended, foot);
    S.els.dock = dock;
    /* the Screen tab: the same dock moves in while the tab is open, and back above the message box otherwise */
    const dot = h('span', {class: 'live-dot', 'aria-hidden': 'true', hidden: true});
    const tab = h('button', {class: 'fx-tab', role: 'tab', id: 'fx-t-screen', 'aria-controls': 'fx-p-screen', 'aria-selected': 'false', tabindex: '-1', title: 'The helper’s screen', hidden: true}, dot, h('span', {text: 'Screen'}));
    const pane = h('div', {class: 'fx-pane', id: 'fx-p-screen', role: 'tabpanel', 'aria-labelledby': 'fx-t-screen', hidden: true});
    S.els.screenTab = tab; S.els.paneScreen = pane;
    const live = S.els.tabs[0];
    live.after(tab); S.els.stage.querySelector('.fx-pane').after(pane);
    stage.insertBefore(dock, S.els.compose);

    let status = 'loading', everLive = false, open = kept(OPEN) === 'open', inTab = false, typing = false, typingAllowed = false, canType = true;
    let waiting = false, queue = [], timer = null, busy = false, key = '', fails = 0;
    const rows = h('div');
    body.append(rows);
    const setOpen = on => {
      open = on; keep(OPEN, on ? 'open' : 'peek');
      layout();
    };
    function layout() {
      const full = inTab || open;
      dock.classList.toggle('peek', !full);
      dock.style.height = !inTab && open && kept(HEIGHT) ? kept(HEIGHT) + 'px' : '';
      toggle.hidden = whole.hidden = inTab;
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Hide the helper’s screen' : 'Show the helper’s screen'); toggle.title = open ? 'Hide (Ctrl+`)' : 'Show (Ctrl+`)';
      key = '';
      if (status === 'live') paintNow();
    }
    function show(next) {
      status = next;
      body.hidden = next !== 'live'; loading.hidden = next !== 'loading'; failed.hidden = next !== 'error'; ended.hidden = next !== 'ended';
      foot.hidden = next !== 'live'; ask.hidden = !(next === 'live' && waiting);
      typingLabel.hidden = !(next === 'live' && typingAllowed && canType);
      if (next !== 'live') last.textContent = next === 'loading' ? 'Connecting to the helper’s screen…' : next === 'error' ? 'The screen stopped updating.' : 'The screen has closed.';
      const visible = next === 'ended' ? everLive : next !== 'none';
      dock.hidden = !visible;
      if (S.els.screenTab) {
        const was = tab.hidden; tab.hidden = !visible;
        if (!visible && tab.getAttribute('aria-selected') === 'true') S.els.tabs[0].click();
        if (was && visible && kept('focus-tab') === 'screen') tab.click();
      }
    }
    function setTyping(on) {
      typing = on && typingAllowed && canType && status === 'live';
      typingSwitch.checked = typing;
      dock.classList.toggle('typing', typing);
      foot.firstChild.textContent = typing ? 'Your keys go straight to the helper’s screen. Turn “Let me type” off or press Shift+Tab to stop.' : 'Watching. Your messages go through the box below.';
      key = '';
      if (typing) { if (!inTab && !open) setOpen(true); body.focus(); } else if (document.activeElement === body) S.els.msg.focus();
      if (status === 'live') paintNow();
    }
    let snapNow = null;
    function paintNow() {
      if (!snapNow || dock.classList.contains('peek')) return;
      const k = JSON.stringify([snapNow.screen, snapNow.cx, snapNow.cy, snapNow.cursor, typing && document.activeElement === body]);
      if (k === key) return;
      key = k;
      rows.replaceChildren(...paint(snapNow.screen, snapNow.cx, snapNow.cy, snapNow.cursor && !snapNow.scrolled && typing && document.activeElement === body));
    }
    const render = snap => {
      fails = 0;
      if (snap.state === 'live') {
        everLive = true; snapNow = snap;
        typingAllowed = snap.typing_allowed === true;
        const q = snap.waiting_input ? questionLine(snap.screen) : '';
        const asks = !!snap.waiting_input;
        if (asks !== waiting) { waiting = asks; S.state.screenWaiting = asks; if (S.poll) S.poll(); }
        askText.textContent = asks ? 'Helper asks on its screen: “' + q + '” Answer in the message box below.' : '';
        last.textContent = lastLine(snap.screen) || 'Working…';
        if (!typingAllowed && typing) setTyping(false);
        show('live'); paintNow();
        return;
      }
      if (waiting) { waiting = false; S.state.screenWaiting = false; if (S.poll) S.poll(); }
      setTyping(false); snapNow = null;
      show(everLive ? 'ended' : 'none');
    };
    async function poll() {
      if (busy || document.hidden || !TID) return;
      busy = true;
      try {
        const r = await fetch('/api/term?ticket=' + TID);
        if (r.ok) render(await r.json()); else throw new Error('status');
      } catch (e) { fails++; if (status !== 'error' && (everLive || fails > 1)) { setTyping(false); show('error'); } }
      busy = false;
    }
    retry.addEventListener('click', () => { show('loading'); poll(); });
    toggle.addEventListener('click', e => { e.stopPropagation(); setOpen(!open); });
    head.addEventListener('click', e => { if (!inTab && !e.target.closest('button,label,input')) setOpen(!open); });
    whole.addEventListener('click', e => { e.stopPropagation(); tab.click(); });
    typingSwitch.addEventListener('change', () => setTyping(typingSwitch.checked));
    document.addEventListener('keydown', e => {
      if (e.ctrlKey && !e.metaKey && !e.altKey && (e.key === '`' || e.code === 'Backquote') && !dock.hidden && !inTab) { e.preventDefault(); setOpen(!open); }
    });
    /* drag the top edge of the open panel to change its height; it is remembered */
    let drag = null;
    const nearTop = e => !inTab && open && e.clientY - dock.getBoundingClientRect().top < 6;
    dock.addEventListener('pointermove', e => { if (!drag) dock.style.cursor = nearTop(e) ? 'ns-resize' : ''; });
    dock.addEventListener('pointerdown', e => { if (nearTop(e)) { drag = {y: e.clientY, h: dock.getBoundingClientRect().height}; dock.setPointerCapture(e.pointerId); e.preventDefault(); } });
    dock.addEventListener('pointermove', e => { if (drag) { const max = Math.max(160, stage.getBoundingClientRect().height - 160); dock.style.height = Math.round(Math.min(max, Math.max(120, drag.h + drag.y - e.clientY))) + 'px'; } });
    dock.addEventListener('pointerup', () => { if (drag) { drag = null; keep(HEIGHT, String(Math.round(dock.getBoundingClientRect().height))); } });
    /* typing: only with the switch on, and only when the setting allows it (the server checks that again) */
    let chain = Promise.resolve();
    const schedule = () => { if (!timer) timer = setTimeout(() => { timer = null; chain = chain.then(flush, flush); }, 25); };
    async function flush() {
      const all = merge(queue.splice(0, queue.length));
      let secret = ''; try { secret = localStorage.getItem('orch_page_secret') || sessionStorage.getItem('orch_page_secret') || ''; } catch (e) { /* none */ }
      while (all.length) {
        const items = []; let size = 0;
        while (all.length && items.length < 40 && size + (all[0].t || '').length <= 12000) { size += (all[0].t || '').length; items.push(all.shift()); }
        if (!items.length) items.push(all.shift());
        try {
          const r = await fetch('/api/term/keys', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Orch-Page': secret}, body: JSON.stringify({ticket: TID, items})});
          if (r.status === 403) {
            const text = (await r.text()).slice(0, 200);
            if (/is off/.test(text)) typingAllowed = false; else canType = false;
            setTyping(false); show(status); S.toast(text || 'Sign in to type here: open the dashboard with a sign-in link from orch.', 'error'); return;
          }
          if (r.status === 409) { S.toast('The helper’s screen has closed; those keys were not sent.', 'error'); return; }
          if (!r.ok) { S.toast((await r.text()).slice(0, 120) || 'The screen did not take that. Try again.', 'error'); return; }
        } catch (e) { return; }
      }
      setTimeout(poll, 120);
    }
    body.addEventListener('keydown', e => {
      if (!typing) return;
      if (e.key === 'Tab' && e.shiftKey) { e.preventDefault(); setTyping(false); return; }  /* Shift+Tab leaves */
      const it = toItem(e);
      if (!it) return;
      e.preventDefault(); e.stopPropagation();
      queue.push(it);
      schedule();
    });
    body.addEventListener('paste', e => {
      const t = (e.clipboardData && e.clipboardData.getData('text')) || '';
      e.preventDefault();
      if (!typing || !t) return;
      for (let i = 0; i < t.length; i += 2000) queue.push({t: t.slice(i, i + 2000).replace(/\r\n?/g, '\n').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '')});
      schedule();
    });
    body.addEventListener('focus', () => { key = ''; paintNow(); });
    body.addEventListener('blur', () => { key = ''; paintNow(); });
    /* where the dock sits: above the message box, or inside the Screen tab */
    function place(tabOpen) {
      if (tabOpen === inTab) return;
      inTab = tabOpen;
      if (inTab) pane.append(dock); else stage.insertBefore(dock, S.els.compose);
      layout();
    }
    S.subscribe(v => { dot.hidden = !v.run.running; if (!everLive && status === 'none' && v.run.running) poll(); });
    let tick = 0;  /* a stopped screen is tried again every 3 s, a running helper's every second */
    setInterval(() => { tick++; if ((S.state.view && S.state.view.run.running) || (status === 'error' && tick % 3 === 0)) poll(); }, 1000);
    show('loading'); dock.hidden = true; tab.hidden = true;
    layout();
    poll();
    return {poll, place};
  }

  S.register('term', {mount, paint, toItem, merge, lastLine, questionLine});
})();
