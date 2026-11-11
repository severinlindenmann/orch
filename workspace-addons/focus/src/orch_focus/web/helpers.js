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
    const text = parts.join(' and ') + (q + r === 1 ? ' needs' : ' need') + (r ? ' your look.' : ' you.');
    return text[0].toUpperCase() + text.slice(1);
  }
  /* "2 agents are working. One question needs you." The agent part is left out while no agent works. */
  function pickerLine(agents, attention) {
    const n = Number(agents) || 0;
    const working = n ? (n === 1 ? '1 agent is working.' : n + ' agents are working.') : '';
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
  root.FocusHelpers = {plainFileName, cleanOutcome, outcome, phase, completedAt, attentionText, pickerLine, fileIcon, ago, agentColor, holdText};
  if (typeof module !== 'undefined') module.exports = root.FocusHelpers;
})(typeof window !== 'undefined' ? window : globalThis);
