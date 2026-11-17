(function (root) {
  'use strict';
  const plainFileName = name => String(name || '').split('/').pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase());
  const cleanOutcome = value => String(value || '').replace(/\b\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|bytes?)\b/gi, '').replace(/^[\s✓✔·—,:;-]+|[\s·—,:;-]+$/g, '').replace(/\s+/g, ' ').trim();
  function outcome(c) {
    if (c.wont_do) return "Won't do";
    const ev = (c.evidence || []).slice(-1)[0];
    const text = ev && (cleanOutcome(ev.summary) || cleanOutcome(ev.text) || (ev.type === 'note' ? cleanOutcome(ev.ref) : ''));
    return text || (c.done ? 'Completed.' : c.state === 'doing' ? 'Working on this task.' : 'Not started yet.');
  }
  function phase(v) {
    const t = v.ticket, run = v.run || {};
    if (v.state === 'done' || t.status === 'done') return 3;
    if (t.status === 'review') return 2;
    return run.running || t.started || run.run || ((t.questions || []).some(q => q.answer == null) && ((t.checklist || []).length || (v.board?.tasks || []).length)) ? 1 : 0;
  }
  function completedAt(t) {
    const at = t.closed_at || [...(t.history || [])].reverse().find(e => /(?:status.*(?:->|→)\s*done|marked done|ticket completed)/i.test(e.text || ''))?.at;
    return at && !isNaN(Date.parse(at)) ? at : null;
  }
  /* The one "Needs you" rule (picker line and the Needs you group): each ticket with an open question counts once.
     Not the status: a ticket stays "waiting" after its question was answered until its helper runs again (ORCH-63). */
  const needsYou = t => Number(t.question_count) > 0 && t.status !== 'done' && t.status !== 'dropped';
  /* Inside the dashboard the line says the dashboard's own number (the top bar's), in Home's words. */
  const dashCountText = n => !n ? 'Nothing needs you right now.' : n + (n === 1 ? ' thing needs you.' : ' things need you.');
  function attentionText(rows) {
    /* the dashboard's one number: each open question plus each result to check (owner, 16 Nov, ORCH-63) */
    const q = rows.filter(needsYou).reduce((n, t) => n + Number(t.question_count), 0), r = rows.filter(t => t.status === 'review').length;
    if (!q && !r) return 'Nothing needs you right now.';
    const number = n => ['zero', 'one', 'two', 'three', 'four', 'five'][n] || String(n);
    const parts = [];
    if (q) parts.push(number(q) + ' question' + (q === 1 ? '' : 's'));
    if (r) parts.push(number(r) + ' result' + (r === 1 ? '' : 's'));
    const text = parts.join(' and ') + (q + r === 1 ? ' needs' : ' need') + (r ? ' your look.' : ' you.');
    return text[0].toUpperCase() + text.slice(1);
  }
  /* The ticket Focus opens on: the oldest question first, then the oldest result to check. Null when nothing waits. */
  function nextNeeding(rows) {
    const at = t => Date.parse(t.updated_at) || Infinity;
    const oldest = list => list.map((t, i) => [t, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(x => x[0])[0];
    const list = rows || [], q = oldest(list.filter(needsYou)), r = oldest(list.filter(t => t.status === 'review' && !needsYou(t)));
    return q ? {ticket: q, hash: ''} : r ? {ticket: r, hash: '#results'} : null;
  }
  /* "Tickets in focus": tickets a helper is working on first, then the most recently updated. */
  function listOrder(rows) {
    const at = t => Date.parse(t.updated_at) || 0, run = t => t.status === 'active' ? 1 : 0;
    return (rows || []).map((t, i) => [t, i]).sort((a, b) => run(b[0]) - run(a[0]) || at(b[0]) - at(a[0]) || a[1] - b[1]).map(x => x[0]);
  }
  /* "2 agents are working. One question needs you." The agent part is left out while no agent works. */
  function pickerLine(agents, attention) {
    const n = Number(agents) || 0;
    const working = n ? (n === 1 ? '1 helper is working.' : n + ' helpers are working.') : '';
    return [working, attention || ''].filter(Boolean).join(' ');
  }
  /* A small picture for a file by its kind: 📊 sheets, 📝 writing, 📄 PDF, 🖼 pictures, 📁 the rest. */
  function fileIcon(path) {
    const ext = (String(path || '').split('/').pop().match(/\.([a-z0-9]+)$/i) || [])[1];
    const kind = String(ext || '').toLowerCase();
    if (['xlsx', 'xls', 'csv'].includes(kind)) return '📊';
    if (['docx', 'doc', 'md', 'txt'].includes(kind)) return '📝';
    if (kind === 'pdf') return '📄';
    if (['png', 'jpg', 'jpeg'].includes(kind)) return '🖼';
    return '📁';
  }
  /* "just now", "2 min ago", "3 h ago"; empty when the time is unknown. */
  function ago(at, now = Date.now()) {
    const t = Date.parse(at);
    if (!at || isNaN(t)) return '';
    const min = Math.floor(Math.max(0, now - t) / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return min + ' min ago';
    return Math.floor(min / 60) + ' h ago';
  }
  /* One stable colour per agent, from its name (no agent tool is named here: the names live in the adapter data). */
  const PALETTE = ['#d97745', '#3b82f6', '#8b5cf6', '#14a37f', '#d6478a', '#b88a1a'];
  function agentColor(name) {
    let hash = 0;
    for (const ch of String(name || '').toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return PALETTE[hash % PALETTE.length];
  }
  /* Why a live run waits before orch types into its window: the core's own words, only while the run runs. */
  function holdText(v) {
    return v && v.run && v.run.running === true && typeof v.hold === 'string' ? v.hold.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
  }
  /* The helper's state while one runs: the core's word (ORCH-61), or from the view when an older core sends none. */
  const HELPER_STATES = ['working', 'starting', 'you', 'waiting', 'idle', 'stuck'];
  function helperOf(v) {
    const run = (v && v.run) || {};
    if (run.running !== true) return null;
    if (run.helper && HELPER_STATES.includes(run.helper.state)) return {state: run.helper.state, detail: String(run.helper.detail || '')};
    return {state: v.attention || v.state === 'needs' ? 'you' : v.state === 'waiting' ? 'idle' : 'working', detail: ''};
  }
  /* The ticket's one state, the same pill and word as the ticket page (kit rule UI.ticketState, ORCH-71). */
  function ticketState(v, rule) {
    rule = rule || (root.UI && root.UI.ticketState);
    const t = (v && v.ticket) || {};
    return rule ? rule({...t, status: v && v.state === 'done' ? 'done' : t.status}, helperOf(v)) : null;
  }
  /* The session's words: pill (the ticket page's word), feed headline, and whether work is shown as happening now
     ("Now:" marks and the "Waiting for the first step…" row). */
  function sessionState(v, rule) {
    const t = v.ticket || {}, run = v.run || {}, s = ticketState(v, rule), hs = helperOf(v);
    const pill = s ? s.word : null, detail = hs ? hs.detail : '';
    if (v.state === 'done') return {key: 'finished', pill, headline: 'Work completed', active: false};
    if (hs && ['working', 'starting'].includes(hs.state) && !(t.questions || []).some(q => q.answer == null)) return {key: 'running', pill, headline: 'The work is taking shape', active: true, detail};
    if (hs && hs.state !== 'you' && !(t.questions || []).some(q => q.answer == null)) return {key: 'paused', pill, headline: detail || pill || 'Work so far', active: false, detail};
    if ((t.questions || []).some(q => q.answer == null)) return {key: 'waiting-for-you', pill, headline: '', active: false, detail};
    if (v.state === 'needs' || (hs && hs.state === 'you')) return {key: 'waiting-for-you', pill, headline: run.running === true ? 'The work is taking shape' : 'Work so far', active: run.running === true, detail};
    if (t.status === 'review') return {key: 'stopped', pill, headline: 'Work so far', active: false};
    if (t.started || run.run) return {key: 'paused', pill, headline: 'Work so far', active: false};
    return {key: 'stopped', pill, headline: 'Work so far', active: false};
  }
  /* The header line under nothing but the title, as on the ticket page: ORCH-n, the state pill, "Step 3 of 4 · 52 min".
     key is empty when the ticket has no number yet (never the internal id). */
  function headerLine(v, rule) {
    const t = (v && v.ticket) || {}, run = (v && v.run) || {};
    const key = typeof t.key === 'string' && t.key && !/^t_/.test(t.key) ? t.key : '';
    const tasks = (t.checklist || []).filter(c => c && !c.wont_do), doing = tasks.findIndex(c => !c.done && c.state === 'doing');
    const n = doing >= 0 ? doing : tasks.findIndex(c => !c.done);
    const hs = helperOf(v), state = ticketState(v, rule);
    const row = {state: hs ? hs.state : 'working', detail: hs ? hs.detail : '',
      step: tasks.length && n >= 0 && v.state !== 'done' ? {n: n + 1, of: tasks.length} : null,
      minutes: hs && Number.isFinite(run.age_seconds) ? Math.floor(run.age_seconds / 60) : null,
      idle: hs && Number.isFinite(run.idle_seconds) ? Math.floor(run.idle_seconds / 60) : null};
    return {key, state, row};
  }
  /* One result as a plain line: what it is, what came out, and Open (no kinds, no commands, no file names). */
  const FALLBACK = {command: 'Check ran', commit: 'Change saved', pr: 'Pull request', url: 'Link'};
  function resultLine(item) {
    const c = (item && item.c) || {}, ev = (item && item.ev) || {};
    const short = text => text.length > 160 ? text.slice(0, 157).trimEnd() + '…' : text;
    const what = cleanOutcome(ev.title) || cleanOutcome(c.text) || 'Result';
    const out = cleanOutcome(ev.summary) || (ev.type === 'note' ? cleanOutcome(ev.text || ev.ref) : '') ||
      (ev.type === 'file' ? plainFileName(ev.ref) : FALLBACK[ev.type] || '');
    return {what: short(what), outcome: short(out.replace(/\s+/g, ' '))};
  }
  /* The ticket list row's small line: the actual next step only when it says more than the action chip. */
  function nextStepText(t, action) {
    const next = String((t && t.next_step) || '').trim();
    return next && next.toLowerCase() !== String(action || '').toLowerCase() ? next : '';
  }
  /* A list group shows the first n rows; the rest wait behind "Show all". */
  function limitGroup(rows, n = 5) {
    return {shown: rows.slice(0, n), more: Math.max(0, rows.length - n)};
  }
  /* Results counts tasks, the same unit as "1 of 1 tasks": the finished tasks that have a result. */
  function resultCount(checklist) {
    return (checklist || []).filter(c => c.done && !c.wont_do && (c.evidence || []).length).length;
  }
  /* The review bar (Accept / Ask for changes) shows whenever the ticket waits for review and nothing else needs
     the person first: in compact, terminal and full-screen views alike, never only on the Results tab. */
  function reviewBarShown(v) {
    const t = (v && v.ticket) || {};
    const asking = (t.questions || []).some(q => q.answer == null) || (v && v.state === 'needs');
    return t.status === 'review' && !asking && !(v && v.run && v.run.running);
  }
  root.FocusHelpers = {helperOf, ticketState, headerLine, resultLine, reviewBarShown, plainFileName, cleanOutcome, outcome, phase, completedAt, needsYou, dashCountText, attentionText, nextNeeding, listOrder, pickerLine, fileIcon, ago, agentColor, holdText, sessionState, nextStepText, limitGroup, resultCount};
  if (typeof module !== 'undefined') module.exports = root.FocusHelpers;
})(typeof window !== 'undefined' ? window : globalThis);
