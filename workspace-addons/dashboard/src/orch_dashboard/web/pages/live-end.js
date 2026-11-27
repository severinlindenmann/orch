'use strict';
// ORCH-817: Stop and End session for every session of the new live page: a ticket's helper, the Manager, the empty
// helper, the chat helper and the plain terminal. The same two sit in the pane header (pages/live-layer.js), in the
// More menu of a wall tile (pages/livewall.js) and on the bar (pages/livebar.js: a list row's More, a right-click on a
// chip). Stop ends only the current step and the session stays (`run.interrupt` = `orch run interrupt`). End session
// asks once, then ends the process: a ticket's helper through `run.stop` (= `orch run stop`), a session without a
// ticket through `session.end` (= `orch session end <kind>`); a helper's conversation stays in History, the plain
// terminal just closes. A hung helper (nothing running, or its login changed) offers Start again: end, then start.

// --- the model (plain data, tested in tests/live_end.test.js) ---
const LIVE_END_KINDS = ['empty', 'chat', 'terminal', 'manager'];
// A helper whose screen says its login changed or ran out: it stopped and waits for a new login.
const LIVE_END_LOGIN = /\/login\b|login (?:has )?(?:changed|expired)|not logged in|invalid api key|please (?:log in|sign in)/i;
function liveEndLogin(lines) {
  return (Array.isArray(lines) ? lines : []).slice(-8).some(l => LIVE_END_LOGIN.test(String(l || '')));
}
// What Stop and End do for one session. s: a session of GET /api/sessions ({id, kind, status, lines}); kind '' is a
// ticket's helper. on: there is something to stop or end; stop: a helper (a plain terminal has no step); busy: a step
// runs now (Stop is greyed otherwise); hung: idle or the login changed, so the pane offers Start again.
function liveEndModel(s) {
  if (!s || typeof s.id !== 'string') return {on:false, stop:false, busy:false, hung:false, login:false, stuck:false, kind:''};
  const kind = LIVE_END_KINDS.includes(s.kind) ? s.kind : '', st = String(s.status || 'closed');
  const terminal = kind === 'terminal', on = terminal ? st !== 'closed' : ['working', 'needs-you', 'idle'].includes(st);
  const login = on && !terminal && liveEndLogin(s.lines);
  return {on, kind, stop:on && !terminal, busy:on && !terminal && !login && (st === 'working' || st === 'needs-you'),
    hung:on && !terminal && (st === 'idle' || login), login,
    // ORCH-2201: only a ticket's helper that really looks stuck (Stuck: at its prompt 20 min with nothing to wait on, or no
    // update) or whose login changed gets the slim line; a quiet session shows its pill and nothing else
    stuck:on && !terminal && (login || (!kind && s.word === 'Stuck')),
    stopOp:['run.interrupt', {ticket:s.id}],
    endOp:kind ? ['session.end', {kind}] : ['run.stop', {ticket:s.id}],
    startOp:kind ? ['session.new', {kind}] : ['run.start', {ticket:s.id}]};
}
// The words of the one question before End, and what a person reads after it.
function liveEndWords(name, kind) {
  const who = String(name || '').trim() || (kind === 'terminal' ? 'the plain terminal' : 'this session');
  return kind === 'terminal'
    ? {ask:'End ' + who + '?', why:'The terminal closes. Its output is not kept.', done:'Plain terminal closed.'}
    : {ask:'End ' + who + '?', why:'It stops now. Its conversation is kept: continue it later, or reopen it from History.',
      done:who.charAt(0).toUpperCase() + who.slice(1) + ' ended. Its conversation is in History.'};
}
// ORCH-1362 (UX checklist D5): Stop is never greyed. Pressed while nothing runs, it says so and what to do instead.
const LIVE_END_IDLE_STOP = 'Nothing is running right now, so there is nothing to stop. Type a message below to give it work.';
// ORCH-1362 (UX checklist E3, L4): an error says what went wrong, and its toast carries the one button that does it
// again; the button names what to do, so the words do not say it twice. text: orch's own reason ('' = fallback).
function liveFailText(text, fallback) {
  const said = String(text || '').trim() || String(fallback || 'That did not work.');
  return /[.!?]$/.test(said) ? said : said + '.';
}
// ORCH-2201 (owner, ORCH-2188 L a): no notice for a quiet session, only the pill ("Quiet 2 d", liveQuietWord). A helper
// that looks stuck gets one slim line with Restart; a changed login says so in the same line.
function liveEndIdleText(m) {
  return m.login ? {head:'Its login changed', tail:'Restart to use the new login'} : {head:'Looks stuck', tail:''};
}
// The status pill's word for a session at its prompt: "Quiet 2 d", "Quiet 20 min", "Quiet" without a time.
function liveQuietWord(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 60) return 'Quiet';
  return 'Quiet ' + (s < 3600 ? Math.floor(s / 60) + ' min' : s < 86400 ? Math.floor(s / 3600) + ' h' : Math.floor(s / 86400) + ' d');
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_END_KINDS, LIVE_END_IDLE_STOP, liveEndLogin, liveEndModel, liveEndWords, liveEndIdleText, liveQuietWord, liveFailText};
} else {
  // --- the page ---
  // One menu at a time, wherever it is: 'pane:<id>', 'tile:<id>' or 'bar:<id>'; ask = the End question shows.
  const liveEnd = {open:'', ask:false, busy:''};
  const liveEndSession = id => (Array.isArray(window.LiveSessions?.list) ? window.LiveSessions.list : []).find(x => x && x.id === id) || null;
  // A session of the API, else what the layer knows (a ticket's pane before the first answer of the sessions API).
  const liveEndOf = id => liveEndSession(id) || (typeof liveLayerSession === 'function' ? (x => x && x.running ? {id:x.id, kind:x.kind || '', status:'working', lines:[]} : null)(liveLayerSession(id)) : null);
  const liveEndName = id => { const s = liveEndSession(id); return s ? (typeof liveName === 'function' ? liveName(s) : s.title) || s.key || '' : ''; };
  window.liveEndKey = () => [liveEnd.open, liveEnd.ask, liveEnd.busy];
  function liveEndRepaint(focus) {
    if (typeof liveLayerPaint === 'function') liveLayerPaint();
    if (typeof liveWallRepaint === 'function') liveWallRepaint();
    window.dispatchEvent(new CustomEvent('orch:live-end'));  // the bar paints itself again
    if (focus) document.querySelector(focus)?.focus({preventScroll:true});
  }
  const ic = name => { const s = h('span', {className:'ic-wrap', 'aria-hidden':'true'}); s.innerHTML = icon(name, 18); return s; };
  // The pane header's two buttons: Stop (one click, greyed when nothing runs) and End session (opens the question).
  window.liveEndButtons = function liveEndButtons(id, label) {
    const m = liveEndModel(liveEndOf(id));
    if (!m.on) return [];
    const where = 'pane:' + id;
    return [
      m.stop ? h('button', {type:'button', className:'btn sm ghost live-pbtn', 'data-live-end':'stop', 'data-id':id, 'data-key':'live-stop',
        disabled:liveEnd.busy === id, 'aria-busy':liveEnd.busy === id ? 'true' : null, 'aria-label':'Stop the current step of ' + label,
        title:m.busy ? 'Stop: ends the current step, the session stays' : 'Nothing is running right now'}, ic('stop'), h('span', {className:'live-word'}, 'Stop')) : null,
      h('button', {type:'button', className:'btn sm ghost live-pbtn', 'data-live-end':'ask', 'data-where':where, 'data-id':id, 'data-key':'live-end',
        'aria-expanded':String(liveEnd.open === where), 'aria-label':'End session of ' + label, title:'End session'}, ic('power'), h('span', {className:'live-word'}, 'End session')),
      liveEnd.open === where ? liveEndMenu(id, where) : null];
  };
  // The More button of a tile or a bar row, and the menu it opens.
  window.liveEndMore = function liveEndMore(id, where, label) {
    if (!liveEndModel(liveEndOf(id)).on) return null;
    const w = where + ':' + id;
    return h('button', {type:'button', className:'btn icon sm ghost', 'data-live-end':'menu', 'data-where':w, 'data-id':id, 'data-key':where + '-end-' + id,
      'aria-expanded':String(liveEnd.open === w), 'aria-haspopup':'true', 'aria-label':'Stop or end ' + label, title:'Stop or end this session'}, ic('more'));
  };
  // Opens the Stop and End menu of a session that has one ('bar:<id>' from a chip's right-click); false when it has none.
  window.liveEndShow = where => {
    const id = where.slice(where.indexOf(':') + 1);
    if (!liveEndModel(liveEndOf(id)).on) return false;
    liveEnd.open = where; liveEnd.ask = false;
    liveEndRepaint('[data-key="live-end-menu"] button:not([disabled])');
    return true;
  };
  window.liveEndOpenAt = where => liveEnd.open.startsWith(where + ':') ? liveEnd.open.slice(where.length + 1) : '';
  // The menu: Stop and End session, or, once End was chosen, the one question (also the pane's End button).
  function liveEndMenu(id, where) {
    const s = liveEndOf(id), m = liveEndModel(s), name = liveEndName(id), words = liveEndWords(name, m.kind);
    const ask = liveEnd.ask || where.startsWith('pane:');
    if (!m.on) return null;
    const busy = liveEnd.busy === id;
    if (ask) return h('div', {className:'live-pop live-end-ask', role:'group', 'aria-label':words.ask, 'data-key':'live-end-ask'},
      h('p', {className:'live-pop-h'}, words.ask),
      h('p', {className:'meta'}, words.why),
      h('div', {className:'row live-end-row'},
        h('button', {type:'button', className:'btn danger sm', 'data-live-end':'yes', 'data-id':id, 'data-key':'live-end-yes', disabled:busy, 'aria-busy':busy ? 'true' : null}, 'End session'),
        h('button', {type:'button', className:'btn ghost sm', 'data-live-end':'no', 'data-id':id, 'data-key':'live-end-no'}, 'Keep it')));
    const item = (act, glyph, words2, sub, extra = {}) => h('button', {type:'button', className:'live-opt live-end-opt', 'data-live-end':act, 'data-id':id, 'data-where':where, ...extra},
      ic(glyph), h('span', {className:'live-opt-t'}, h('span', {}, words2), h('span', {className:'meta'}, sub)));
    return h('div', {className:'live-pop live-end-menu', role:'group', 'aria-label':'Stop or end ' + (name || 'this session'), 'data-key':'live-end-menu'},
      name ? h('p', {className:'live-pop-h'}, name) : null,
      m.stop ? item('stop', 'stop', 'Stop', m.busy ? 'Ends the current step. The session stays.' : 'Nothing is running right now.', {disabled:busy, 'aria-busy':busy ? 'true' : null, 'data-key':'live-end-stop'}) : null,
      item('ask', 'power', 'End session', m.kind === 'terminal' ? 'Closes the terminal.' : 'Ends the helper. It moves to History.', {'data-key':'live-end-end'}));
  }
  window.liveEndMenu = liveEndMenu;
  // The slim line of a helper that looks stuck (ORCH-2201): "Looks stuck · Restart". Quiet sessions have none.
  window.liveEndIdleFill = function liveEndIdleFill(box, id) {
    const m = liveEndModel(liveEndSession(id));
    box.hidden = !m.stuck;
    if (!m.stuck) { delete box.dataset.sig; return; }
    const t = liveEndIdleText(m), sig = t.head + '\u0001' + t.tail;
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig; box.textContent = '';
    box.append(h('span', {className:'live-stuck-t'}, h('strong', {}, t.head), t.tail ? ' · ' + t.tail : ''),
      h('button', {type:'button', className:'btn ghost sm', 'data-live-end':'restart', 'data-id':id, 'data-key':'live-restart'}, 'Restart'));
  };
  async function liveEndRun(id, op) {
    liveEnd.busy = id; liveEndRepaint();
    const r = await act(op[0], op[1], {quiet:true});
    liveEnd.busy = '';
    if (r.ok) await window.LiveSessions?.refresh?.();  // the pane, the wall and the bar show the new state at once
    return r;
  }
  const toast = (text, kind) => window.orch?.toast?.(text, kind);
  // An error toast with its one button (Try again by default) that does the failed thing once more (ORCH-1362).
  window.liveFail = function liveFail(text, fallback, again, label = 'Try again') {
    if (typeof again !== 'function') return window.orch?.toast?.(String(text || '').trim() || fallback, 'error');
    const go = () => { again(); };
    go.label = label;
    return window.orch?.toast?.(liveFailText(text, fallback), 'error', go);
  };
  document.addEventListener('click', async e => {
    const b = e.target.closest?.('[data-live-end]');
    if (!b) {
      if (liveEnd.open && !e.target.closest?.('.live-end-menu, .live-end-ask')) { liveEnd.open = ''; liveEnd.ask = false; liveEndRepaint(); }
      return;
    }
    if (b.disabled) return;
    e.preventDefault(); e.stopPropagation();
    // from a narrow pane's More: More closes, the question opens under the header in its place
    if (b.closest('#live-dock') && typeof liveLayerModel === 'function' && typeof liveLayerDo === 'function') {
      const menu = liveLayerModel().menu;
      if (menu) liveLayerDo({type:'menu', menu});
    }
    const id = b.dataset.id, s = liveEndOf(id), m = liveEndModel(s), what = b.dataset.liveEnd;
    if (what === 'menu' || what === 'ask') {
      const where = b.dataset.where || 'pane:' + id;
      const again = liveEnd.open === where && (what === 'menu' ? !liveEnd.ask : liveEnd.ask || where.startsWith('pane:'));
      liveEnd.open = again ? '' : where; liveEnd.ask = !again && what === 'ask';
      liveEndRepaint(liveEnd.open ? (liveEnd.ask || where.startsWith('pane:') ? '[data-key="live-end-yes"]' : '[data-key="live-end-menu"] button:not([disabled])') : null);
      return;
    }
    if (what === 'no') { liveEnd.open = ''; liveEnd.ask = false; liveEndRepaint(); toast('The session stays.', 'ok'); return; }
    liveEnd.open = ''; liveEnd.ask = false;
    if (what === 'stop' && !m.busy) toast(LIVE_END_IDLE_STOP, 'ok');
    else await liveEndDo(id, what, m);
    liveEndRepaint();
  }, true);
  // Stop, End session and Start again; a failure says what to do and offers Try again, which runs the same once more.
  async function liveEndDo(id, what, m) {
    // the ops come from the id and the kind, so the same m does it again even when the session list has changed
    const again = (next = what) => () => liveEndDo(id, next, m).then(() => liveEndRepaint());
    if (what === 'stop') {
      const r = await liveEndRun(id, m.stopOp);
      if (r.ok) toast('Stopped the current step. The session stays; type to go on.', 'ok'); else window.liveFail(r.text, 'Could not stop the step.', again());
    } else if (what === 'yes') {
      const r = await liveEndRun(id, m.endOp), words = liveEndWords(liveEndName(id), m.kind);
      if (r.ok) toast(words.done, 'ok'); else window.liveFail(r.text, 'Could not end the session.', again());
      if (r.ok && m.kind === 'terminal' && typeof liveLayerDo === 'function') liveLayerDo({type:'close', key:id});
    } else if (what === 'restart' || what === 'start') {
      // Start again ends first; when the end worked and only the start failed, Try again only starts
      const r = what === 'start' ? {ok:true} : await liveEndRun(id, m.endOp), r2 = r.ok ? await liveEndRun(id, m.startOp) : r;
      if (r2.ok) toast('Started again. It goes on with the same conversation.', 'ok');
      else window.liveFail(r2.text, r.ok ? 'Could not start it again.' : 'Could not end it to start it again.', again(r.ok ? 'start' : 'restart'));
    }
  }
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !liveEnd.open) return;
    const where = liveEnd.open.replace(/["\\]/g, '');
    e.stopPropagation(); liveEnd.open = ''; liveEnd.ask = false;
    liveEndRepaint('[data-live-end="' + (where.startsWith('pane:') ? 'ask' : 'menu') + '"][data-where="' + where + '"]');
  }, true);
}
