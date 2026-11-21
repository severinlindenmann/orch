// Owns the picker’s running jobs and stop controls.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, toast} = S;

  function mount(box) {
    /* ---- Running now: every run Focus started, each with Stop; Stop all asks once (a plain click) ---- */
    const procBox = h('section', {class: 'fx-procs', hidden: true});
    box.append(procBox);
    const minutes = at => { const m = Math.max(0, Math.floor((Date.now() - Date.parse(at)) / 60000)); return isNaN(m) ? '' : m < 1 ? 'just now' : m + ' min'; };
    const CHIP = {working: ['Working', 'good'], paused: ['Paused', ''], needs: ['Waiting for you', 'needs-you']};
    let stopping = false;
    const loadProcs = async () => {
      if (stopping || document.hidden) return;
      try { const r = await fetch(P + '/api/procs'); if (r.ok) paintProcs((await r.json()).procs || []); } catch (e) { /* next round */ }
    };
    const stopCall = async (op, args) => {
      stopping = true;
      let r;
      try { r = await fetch(P + '/api/act', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, args})}); } catch (e) { r = null; }
      stopping = false;
      if (!r || !r.ok) { toast(r ? (await r.text()).slice(0, 200) : 'Could not reach Focus.', 'error'); loadProcs(); return; }
      const d = await r.json(); paintProcs(d.procs || []);
      toast(d.failed ? 'Some did not stop.' : 'Stopped.', d.failed ? 'error' : 'ok');
    };
    const confirmAll = n => {
      const d = h('dialog', {class: 'dialog fx-confirm', 'aria-labelledby': 'fx-stopall-t'}, h('h2', {id: 'fx-stopall-t', text: 'Stop all ' + n + '?'}),
        h('div', {class: 'actions'}, h('button', {class: 'btn ghost', text: 'Keep running', onclick: () => d.close()}),
          h('button', {class: 'btn primary', text: 'Stop all', onclick: () => { d.close(); stopCall('proc.stop_all', {}); }})));
      d.addEventListener('close', () => d.remove());
      document.body.append(d); d.showModal();
    };
    function paintProcs(rows) {
      procBox.hidden = !rows.length;
      const waiting = rows.filter(x => x.state === 'needs').length;
      procBox.replaceChildren(...(rows.length ? [
        h('div', {class: 'row fx-procs-h'}, h('h2', {class: 'grow'}, 'Running now ', h('span', {class: 'meta', text: '(' + rows.length + (waiting ? ', ' + waiting + ' waiting for you' : '') + ')'})),
          h('button', {class: 'btn outline sm', 'data-act': 'stop-all', text: 'Stop all', onclick: () => confirmAll(rows.length)})),
        h('div', {class: 'card'}, rows.map(x => {
          const [word, tone] = CHIP[x.state] || CHIP.working;
          return h('div', {class: 'fx-proc'},
            h('div', {class: 'row'}, h('span', {class: 'grow'}, h('strong', {text: x.label}), ' on ', h('span', {class: 'mono key', text: x.key || x.ticket}), ' ', x.title),
              h('span', {class: 'chip ' + tone, text: word}), h('span', {class: 'meta', text: minutes(x.started_at)}),
              h('button', {class: 'btn ghost sm', 'data-act': 'stop-one', 'aria-label': 'Stop ' + x.label + ' on ' + (x.key || x.title), text: 'Stop', onclick: () => stopCall('proc.stop', {ticket: x.ticket, run: x.run})})),
            h('div', {},
              h('p', {class: 'meta'}, x.started_at ? 'Started ' + new Date(x.started_at).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false}) + ' · ' : '', h('a', {href: P + '/t/' + x.ticket, text: x.key || 'Open ticket'}), x.pid ? ' · process ' + x.pid : '')));
        }))] : []));
    }
    loadProcs(); setInterval(loadProcs, 5000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadProcs(); });
  }

  S.register('jobs', {mount});
})();
