'use strict';
// ORCH-818: the permission mode of a session without a ticket (Manager, Empty helper, Chat helper). The New menu of
// the bar (pages/livebar.js) has a Permissions row for the next start; a running session's pane (pages/live-layer.js)
// shows its mode in words on the line at its top, and its menu goes on in another mode (ends the session and
// continues the same conversation). The modes, what the workspace allows and whether the Bypass permissions warning
// was seen come from state.session_modes (core sessionmode.py). Everything goes through `session.new` (= `orch session
// new <kind> --permission-mode <mode>`); the core refuses a mode the workspace does not allow, and a raise without
// the signed-in person.

// --- the model (plain data, tested in tests/live_perm.test.js) ---
const LIVE_PERM_KINDS = ['manager', 'empty', 'chat'];
const LIVE_PERM_WARN = 'Bypass permissions: the helper runs every command without asking, also risky ones. Use it only in a workspace you trust.';
const LIVE_PERM_OFF = 'Not allowed in this workspace. A person can allow it in Settings.';
// The Permissions row for a kind: {choices: [{mode, label, allowed, on}], cur, label, running, runningLabel, warn}, or
// null when there is nothing to choose (no tool, the plain terminal, an older orch). pick: the person's choice in the
// menu ('' = the kind's remembered one); a mode the workspace does not allow is never picked.
function livePermRow(modes, kind, pick) {
  const m = modes && typeof modes === 'object' && LIVE_PERM_KINDS.includes(kind) ? modes[kind] : null;
  const list = Array.isArray(m?.choices) ? m.choices.filter(c => c && typeof c.mode === 'string') : [];
  if (!list.length) return null;
  const ok = v => list.some(c => c.mode === v && c.allowed === true);
  const cur = pick && ok(pick) ? pick : m.current;
  const word = v => String((list.find(c => c.mode === v) || {}).label || '');
  return {
    choices: list.map(c => ({mode: c.mode, label: String(c.label || c.mode), allowed: c.allowed === true, on: c.mode === cur})),
    cur, label: word(cur) || String(m.label || ''),
    running: typeof m.running === 'string' ? m.running : null, runningLabel: String(m.running_label || ''),
    warn: cur === 'full' && m.full_warned !== true ? LIVE_PERM_WARN : '',
  };
}
// What a start sends: the mode only when the person picked one; else the kind starts in its remembered mode.
function livePermArgs(kind, pick) {
  return pick && LIVE_PERM_KINDS.includes(kind) ? {kind, permissions: pick} : {kind};
}
// The words on the pane's line: "Permissions: Auto" ('' when the session shows no mode).
function livePermPaneText(row) {
  return row && row.runningLabel ? 'Permissions: ' + row.runningLabel : '';
}

if (typeof module === 'object' && module.exports) {
  module.exports = {LIVE_PERM_KINDS, LIVE_PERM_WARN, LIVE_PERM_OFF, livePermRow, livePermArgs, livePermPaneText};
} else {
  const rowOf = kind => livePermRow(state?.session_modes, kind, '');
  // for the dock's repaint key: what each pane's mode line shows
  window.livePermKey = () => LIVE_PERM_KINDS.map(k => { const r = rowOf(k); return r ? [k, r.runningLabel, r.warn, r.choices.map(c => c.allowed)] : null; });
  // The line at the top of a running session's pane: its mode in words, and the menu to go on in another mode.
  window.livePermPaneRow = function livePermPaneRow(sess, s) {
    const r = rowOf(sess.kind), text = livePermPaneText(r);
    if (!text) return null;
    const menu = 'perm:' + sess.id, open = s.menu === menu;
    return h('div', {className:'live-prow meta', 'data-key':'live-perm-row'},
      h('span', {className:'live-mdl-wrap'},
        h('button', {type:'button', className:'btn ghost sm live-mdl', 'data-live':'menu', 'data-menu':menu, 'aria-expanded':String(open),
          'data-key':'live-perm', title:'See or change what the ' + sess.title + ' may do without asking'}, text),
        open ? h('div', {className:'live-pop', 'data-down':'', role:'group', 'aria-label':sess.title + ': permissions', 'data-key':'live-perm-menu'},
          h('p', {className:'live-pop-h'}, sess.title + ': permissions'),
          r.choices.map(c => h('button', {type:'button', className:'live-opt', 'data-live-perm':c.mode, 'data-kind':sess.kind, 'data-session':sess.id,
            'aria-pressed':String(c.mode === r.running), disabled:!c.allowed, title:c.allowed ? null : LIVE_PERM_OFF},
          h('span', {className:'live-opt-t'}, h('strong', {}, c.label + (c.mode === r.running ? ' (now)' : '')),
            c.allowed ? null : h('span', {className:'meta'}, LIVE_PERM_OFF)))),
          r.choices.some(c => c.mode === 'full' && c.allowed) && state?.session_modes?.[sess.kind]?.full_warned !== true
            ? h('p', {className:'meta'}, LIVE_PERM_WARN) : null,
          h('p', {className:'meta'}, 'A new mode ends the session and goes on with the same conversation.')) : null));
  };
  document.addEventListener('click', async e => {
    const b = e.target.closest?.('#live-dock [data-live-perm]');
    if (!b || b.disabled) return;
    const id = b.dataset.session, kind = b.dataset.kind, mode = b.dataset.livePerm, r = rowOf(kind);
    if (typeof liveLayerDo === 'function') liveLayerDo({type:'menu', menu:'perm:' + id}, `.live-pane[data-session="${id.replace(/["\\]/g, '')}"] [data-key="live-perm"]`);
    if (!r || r.running === mode) return;
    const word = (r.choices.find(c => c.mode === mode) || {}).label || mode;
    const go = async () => {
      const res = await act('session.new', livePermArgs(kind, mode));
      if (res.ok) window.orch?.toast?.('Goes on in ' + word + '.', 'ok');
      else (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(res.text, 'Could not change the permissions.', go);
    };
    await go();
  });
}
