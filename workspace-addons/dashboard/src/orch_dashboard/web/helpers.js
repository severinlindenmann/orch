'use strict';
// Pure helpers of the dashboard page (no DOM), so node can test them.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DashHelpers = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const arr = v => Array.isArray(v) ? v : [];
  const STATUS_WORD = {open: 'Open', active: 'Doing', waiting: 'Waiting', done: 'Done', dropped: 'Dropped'};
  const FIELD_WORD = {title: 'the title', owner: 'the owner', due: 'the due day', note: 'the note', summary: 'the summary',
    status: 'the status'};

  /* One plain line for a history entry. The common words the CLI writes become sentences; anything else is shown as
     written (the caller still strips ids). */
  function historyLine(entry) {
    const text = String((entry && entry.text) ?? '').trim();
    let m;
    if (/^Created/.test(text)) return /under /.test(text) ? 'Created as a sub-ticket' : 'Ticket created';
    if ((m = /^Edited (.+)$/.exec(text))) {
      const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
      return 'Changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]);
    }
    if (/^Asked\b/.test(text)) return 'Asked a question';
    if (/^Answered\b/.test(text)) return 'Answered a question';
    if ((m = /^Status \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if (/^Summary/.test(text)) return 'Updated the summary';
    if (/^(Checked|Done)\b.*\bc\d+/.test(text) || /^Task .* done/i.test(text)) return 'Finished a task';
    if (/^Added task|^Added check/i.test(text)) return 'Added a task';
    if (/^Linked|^Link added/i.test(text)) return 'Added a link';
    return text;
  }

  /* The answer that is already there for a question (someone else was first). Null when it is still open. */
  function winningAnswer(tickets, ticketId, questionId) {
    const t = arr(tickets).find(x => x && x.id === ticketId);
    const q = arr(t && t.questions).find(x => x && x.id === questionId);
    if (!q || q.answer == null) return null;
    return {text: String(q.answer), who: q.answered_by || '', via: q.via || ''};
  }

  /* The one button of a "Needs you" row. kind: answer (opens the question card), review (an add-on's own question),
     run (start the work again) or open (the ticket). */
  function needAction(row) {
    const r = row || {};
    const answerable = !!r.answer && r.kind !== 'overdue-wait';
    if (answerable && /^[a-z][a-z0-9-]*:/.test(String(r.kind || ''))) return {label: 'Review', kind: 'review'};
    if (answerable) return {label: 'Answer', kind: 'answer'};
    if (r.tone === 'bad' && r.ticket) return {label: 'Run again', kind: 'run'};
    return {label: 'Open', kind: 'open'};
  }

  /* Agents card: who works, who waits for the person, who is idle. Working comes from `runs`, idle from the
     tickets' sessions (newest session per agent that is not working now). */
  function agentRows(tickets, runs, nowMs) {
    const out = [], busy = new Set();
    for (const [tid, run] of Object.entries(runs || {})) {
      if (!run || run.running !== true) continue;
      const t = arr(tickets).find(x => x.id === tid);
      const agent = (run.claim && (run.claim.agent || run.claim.by)) || 'agent';
      const asks = arr(t && t.questions).some(q => q && q.answer == null);
      busy.add(String(agent).replace(/^(agent|human):/, ''));
      out.push({agent: String(agent).replace(/^(agent|human):/, ''), state: run.state === 'maybe-stale' ? 'stuck' : asks ? 'needs' : 'working',
        ticket: tid, since: run.claim && run.claim.started_at});
    }
    const last = new Map();
    for (const t of arr(tickets)) for (const s of arr(t.sessions)) {
      const at = Date.parse(s && s.last_used);
      if (!s || !s.agent || Number.isNaN(at) || busy.has(s.agent)) continue;
      if (!last.has(s.agent) || at > last.get(s.agent).at) last.set(s.agent, {at, ticket: t.id});
    }
    for (const [agent, v] of last) if (nowMs - v.at >= 0) out.push({agent, state: 'idle', ticket: v.ticket, since: new Date(v.at).toISOString()});
    const rank = {needs: 0, stuck: 1, working: 2, idle: 3};
    return out.sort((a, b) => rank[a.state] - rank[b.state]);
  }

  /* Links to other running pages of this workspace (label and address come from the services data). */
  function serviceLinks(services, ownOrigin) {
    return arr(services).filter(s => s && s.running === true && typeof s.url === 'string' && /^http:\/\/(127\.0\.0\.1|localhost):\d+/.test(s.url)
      && !s.url.startsWith(ownOrigin) && /^[a-z][a-z0-9-]{1,31}$/.test(String(s.addon || s.name)))
      .map(s => ({label: String(s.addon || s.name), url: s.url}));
  }
  return {historyLine, winningAnswer, needAction, agentRows, serviceLinks};
});
