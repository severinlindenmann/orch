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
  /* The one "Needs you" rule (picker line and the Needs you group): each waiting ticket counts once. */
  const needsYou = t => t.status === 'waiting';
  function attentionText(rows) {
    const q = rows.filter(needsYou).length, r = rows.filter(t => t.status === 'review').length;
    if (!q && !r) return 'Nothing needs you right now.';
    const number = n => ['zero', 'one', 'two', 'three', 'four', 'five'][n] || String(n);
    const parts = [];
    if (q) parts.push(number(q) + ' question' + (q === 1 ? '' : 's'));
    if (r) parts.push(number(r) + ' result' + (r === 1 ? '' : 's'));
    const text = parts.join(' and ') + (q + r === 1 ? ' needs' : ' need') + (r ? ' your look.' : ' you.');
    return text[0].toUpperCase() + text.slice(1);
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
  /* The one source for the session's words: pill, feed headline, and whether work is shown as happening now
     ("Now:" marks and the "Waiting for the first step…" row). pill null: not started, the ticket's own status word. */
  function sessionState(v) {
    const t = v.ticket || {}, run = v.run || {};
    if (v.state === 'done') return {key: 'finished', pill: 'Done', headline: 'Work completed', active: false};
    if ((t.questions || []).some(q => q.answer == null)) return {key: 'waiting-for-you', pill: 'Needs you', headline: 'Before the question', active: false};
    if (v.state === 'needs') return {key: 'waiting-for-you', pill: 'Needs you', headline: run.running === true ? 'The work is taking shape' : 'Work so far', active: run.running === true};
    if (v.state === 'working') return {key: 'running', pill: 'Working', headline: 'The work is taking shape', active: true};
    if (v.state === 'waiting') return {key: 'paused', pill: 'Paused', headline: 'Paused', active: false};
    if (t.status === 'review') return {key: 'stopped', pill: 'Ready for review', headline: 'Work so far', active: false};
    if (t.started || run.run) return {key: 'paused', pill: 'Paused', headline: 'Paused', active: false};
    return {key: 'stopped', pill: null, headline: 'Work so far', active: false};
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
  root.FocusHelpers = {reviewBarShown, plainFileName, cleanOutcome, outcome, phase, completedAt, needsYou, attentionText, pickerLine, fileIcon, ago, agentColor, holdText, sessionState, nextStepText, limitGroup, resultCount};
  if (typeof module !== 'undefined') module.exports = root.FocusHelpers;
})(typeof window !== 'undefined' ? window : globalThis);
