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
  function attentionText(rows) {
    const q = rows.filter(t => t.status !== 'done').reduce((n, t) => n + (t.question_count || 0), 0), r = rows.filter(t => t.status === 'review').length;
    if (!q && !r) return 'Nothing needs you right now.';
    const number = n => ['zero', 'one', 'two', 'three', 'four', 'five'][n] || String(n);
    const parts = [];
    if (q) parts.push(number(q) + ' question' + (q === 1 ? '' : 's'));
    if (r) parts.push(number(r) + ' result' + (r === 1 ? '' : 's'));
    const text = parts.join(' and ') + (q + r === 1 ? ' needs' : ' need') + ' your look.';
    return text[0].toUpperCase() + text.slice(1);
  }
  /* Why a live run waits before orch types into its window: the core's own words, only while the run runs. */
  function holdText(v) {
    return v && v.run && v.run.running === true && typeof v.hold === 'string' ? v.hold.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
  }
  root.FocusHelpers = {plainFileName, cleanOutcome, outcome, phase, completedAt, attentionText, holdText};
  if (typeof module !== 'undefined') module.exports = root.FocusHelpers;
})(typeof window !== 'undefined' ? window : globalThis);
