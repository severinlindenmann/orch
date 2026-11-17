'use strict';
// Pure helpers of the dashboard page (no DOM), so node can test them.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DashHelpers = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const arr = v => Array.isArray(v) ? v : [];
  const STATUS_WORD = {open: 'To do', ready: 'To do', active: 'Working', waiting: 'Needs you', review: 'Check', done: 'Done', dropped: 'Dropped'};
  /* The ONE source of status words and order (board columns, Home, ticket page, Move to, history, lists).
     Lifecycle order. "ready" is the same place as "open" (no separate word); "waiting" shows as "Needs you". */
  const STATUS_ORDER = ['open', 'active', 'waiting', 'review', 'done'];
  const statusWord = (status, started) => (status === 'open' || status === 'ready') && started === true ? 'Paused' : STATUS_WORD[status] || 'To do';
  const columnOf = status => status === 'ready' ? 'open' : status;
  const STATUS_CHOICES = STATUS_ORDER.map(s => [s, STATUS_WORD[s]]);
  // "Move to" offers four places; Waiting is decided by the agent.
  const MOVE_CHOICES = STATUS_CHOICES.filter(([s]) => s !== 'waiting');
  const FIELD_WORD = {title: 'the title', owner: 'the owner', due: 'the due day', note: 'the note', summary: 'the summary',
    status: 'the status', done_when: 'the Done when line'};

  /* Due dates (G1). `due` is "YYYY-MM-DD" (a day) or "YYYY-MM-DDTHH:MM" (local wall time, no zone). Only a due with a
     time gets words here: "Due 18:30" (today), "Due Mon 18:30" (within a week), "Due 14 Nov 2026, 18:30" (further),
     and "Late since ..." once it has passed on an active ticket. A day-only due returns '' (callers keep their day
     wording). The same words as orch.tickets.due_label (the CLI). */
  const DUE_DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const DUE_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const dueTime = due => { const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(due || '')); return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null; };
  const dueKey = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const dueClock = d => String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  /* A local time in plain words: "18:30" (today), "Mon 18:30" (within a week), "14 Nov 2026, 18:30" (further).
     The same words as orch.tickets._when_words. */
  function whenWords(at, now) {
    const gap = Math.round((new Date(at.getFullYear(), at.getMonth(), at.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
    return gap === 0 ? dueClock(at) : Math.abs(gap) < 7 ? DUE_DAYS[at.getDay()] + ' ' + dueClock(at) : at.getDate() + ' ' + DUE_MONTHS[at.getMonth()] + ' ' + at.getFullYear() + ', ' + dueClock(at);
  }
  function dueWords(due, status, now) {
    const at = dueTime(due);
    if (!at) return '';
    now = now || new Date();
    return (at < now && status !== 'done' && status !== 'dropped' ? 'Late since ' : 'Due ') + whenWords(at, now);
  }
  /* G2: "No news since 09:20" for a Working ticket quiet for 6 h. `since` is `quiet_since` (UTC ISO, computed once by
     orch.tickets.quiet_since); shown in local time. '' when the ticket is not quiet. The same words as
     orch.tickets.quiet_label (the CLI). */
  function quietWords(since, now) {
    const at = since ? new Date(since) : null;
    return at && !isNaN(at) ? 'No news since ' + whenWords(at, now || new Date()) : '';
  }
  /* Past its day (day-only) or its time (with a time), on a ticket that is not closed. */
  function dueLate(due, status, now) {
    if (!due || status === 'done' || status === 'dropped') return false;
    now = now || new Date();
    const at = dueTime(due);
    return at ? at < now : String(due) < dueKey(now);
  }

  /* One plain line for a history entry. The common words the CLI writes become sentences; anything else is shown as
     written (the caller still strips ids). */
  /* The one place a raw actor id inside a line ("agent:<name>", "human:<name>") becomes the name a person reads. */
  function plainNames(text) {
    return String(text ?? '').replace(/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g, (_, n) => n.charAt(0).toUpperCase() + n.slice(1));
  }

  /* A task finished by the agent is written twice (orch's own "Check c1 done" and the agent's own note): both read
     "Finished a task: ...". Within two minutes the longer of two equal-or-prefix lines stays, once. Original order kept. */
  function dedupeHistory(entries, checklist) {
    const list = Array.isArray(entries) ? entries : [], drop = new Set(), last = [];
    const order = list.map((e, i) => [e, i]).sort((a, b) => (Date.parse(a[0] && a[0].at) || 0) - (Date.parse(b[0] && b[0].at) || 0) || a[1] - b[1]);
    for (const [e] of order) {
      const line = historyLine(e, checklist), at = Date.parse(e && e.at) || 0;
      const dup = last.find(p => Math.abs(at - p.at) <= 120000 && (p.line === line || line.startsWith(p.line + ':') || p.line.startsWith(line + ':')));
      if (!dup) { last.push({e, line, at}); continue; }
      if (line.length > dup.line.length) { drop.add(dup.e); Object.assign(dup, {e, line, at}); } else drop.add(e);
    }
    return list.filter(e => !drop.has(e));
  }

  /* The sidebar footer: empty unless something is wrong, i.e. the relay add-on's saved connection is lost
     (the same fact Settings shows as "Connected"). A shared copy says so. */
  function footerState(state, snapshot) {
    if (snapshot) return 'Shared copy';
    const relay = ((state && state.settings && state.settings.addons) || []).find(a => a && a.name === 'relay' && a.active && a.detail);
    return relay && !relay.detail.connected ? 'Not connected' : '';
  }

  function historyLine(entry, checklist) {
    const text = String((entry && entry.text) ?? '').trim();
    let m;
    // the lines orch writes itself (same words as the CLI): a task line names the task, add-on settings their add-on
    const task = id => { const c = (Array.isArray(checklist) ? checklist : []).find(x => x && x.id === id); return c && c.text ? ': ' + c.text : ''; };
    const addon = key => key.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase());
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a step' + task(m[1]);
    if ((m = /^Marked (c\d+) as won't do$/.exec(text))) return "Marked as won't do" + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a step' + task(m[1]);
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    if ((m = /^Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?$/.exec(text))) return 'Removed ' + addon(m[1]) + ' settings';
    if (/^Created under t_\w+$/.test(text)) return 'Created as a sub-ticket';
    if ((m = /^Recorded a check run for (c\d+)(?: \(exit (\d+)\))?$/.exec(text))) return 'Ran a check' + task(m[1]) + (m[2] == null ? '' : m[2] === '0' ? ' (passed)' : ' (failed)');
    if ((m = /^Moved (c\d+) after c\d+$/.exec(text))) return 'Moved a task' + task(m[1]);
    if ((m = /^Created under (.+)$/.exec(text))) return 'Created under ' + m[1];
    if (/^Created/.test(text)) return /under /.test(text) ? 'Created as a sub-ticket' : 'Ticket created';
    if ((m = /^Edited (.+)$/.exec(text))) {
      const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
      return 'Changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]);
    }
    if (/^Asked\b/.test(text)) return 'Asked a question';
    if (/^Answered q\d+/.test(text)) return 'Answered a question';
    if ((m = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if (/^Summary/.test(text)) return 'Updated the summary';
    if ((m = /^Added (?:task|check)[:\s]+(.+)$/i.exec(text))) return 'Added a step: ' + m[1];
    if ((m = /^Finished a (?:task|step)[:\s]+(.+)$/i.exec(text))) return 'Finished a step: ' + m[1];
    if (/^(Updated|Removed) .+ settings$/.test(text)) return text;
    if (/^Check c\d+ done/i.test(text) || /^(Checked|Done)\b.*\bc\d+/.test(text) || /^Task .* done/i.test(text)) return 'Finished a step';
    if (/^Added task|^Added check/i.test(text)) return 'Added a step';
    if (/^Linked|^Link added/i.test(text)) return 'Added a reference';
    return plainNames(text).replace(/ moved it to Review$/, ' sent it to Check');
  }

  /* Plain words for a failure or notice: never a raw ticket id, an internal actor name (agent:/human:) or a UTC time.
     A conflict ("was changed by agent:<name> at 12:08") becomes "<Name> just changed this ticket - updated." */
  function titleCase(n) { return String(n || '').replace(/[_.-]+/g, ' ').trim().replace(/^./, c => c.toUpperCase()); }
  function scrubText(text) {
    const raw = String(text ?? '');
    const m = /\bchanged by (?:(agent|human):)?([A-Za-z0-9_.@ -]*?)(?: at \d{1,2}:\d{2})?\s*\.?(?:\s|$)/.exec(raw);
    if (/\bwas changed by\b/.test(raw) && m) return (m[2] && m[1] !== 'human' ? titleCase(m[2]) : 'Someone') + ' just changed this ticket — updated.';
    return plainNames(raw)
      .replace(/\s+(?:at|since|on)\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:UTC|Z))?/g, '')
      .replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?/g, '')
      .replace(/\bt_[A-Za-z0-9]+\b/g, 'this ticket')
      .replace(/\s*Reload the page and try again\./g, '')
      .replace(/\s{2,}/g, ' ').trim();
  }

  /* Who a history line is about: "You" for the current person, the display name otherwise. */
  function historyWho(by, me) {
    const b = String(by || '');
    if (me && b === me) return 'You';
    return titleCase(b.replace(/^(?:agent|human):/, '')) || 'Someone';
  }
  /* The history of a ticket as plain rows {entry, who, line, sentence}. Person actions on the status or fields become one
     sentence ("You asked for changes: <note>"); the "Change: <note>" task that went with it is folded into that sentence. */
  function historyView(entries, checklist, me) {
    const list = dedupeHistory(entries, checklist), out = [];
    const noteFor = (entry) => {
      const at = Date.parse(entry && entry.at) || 0;
      for (const e of list) {
        const m = /^Added check (c\d+)$/.exec(String((e && e.text) || '').trim());
        const c = m && (Array.isArray(checklist) ? checklist : []).find(x => x && x.id === m[1]);
        if (c && /^Change: /.test(c.text || '') && Math.abs((Date.parse(e.at) || 0) - at) <= 120000) return {entry: e, note: c.text.slice(8)};
      }
      return null;
    };
    const hidden = new Set();
    for (const e of list) {
      const text = String((e && e.text) || '').trim(), by = String((e && e.by) || '');
      const who = historyWho(by, me);
      let sentence = null, m;
      if (by.startsWith('human:')) {
        if ((m = /^Asked for changes(?:: ([\s\S]*))?$/.exec(text))) {
          const n = noteFor(e);
          if (n) hidden.add(n.entry);
          const note = m[1] || (n && n.note) || '';
          sentence = who + ' asked for changes' + (note ? ': ' + note : '');
        } else
        if ((m = /^(?:Patched status \(status|Status) (\w+) -> (\w+)\)?$/.exec(text))) {
          if (m[1] === 'review' && m[2] === 'active') {
            const n = noteFor(e);
            if (n) hidden.add(n.entry);
            sentence = who + ' asked for changes' + (n && n.note ? ': ' + n.note : '');
          } else if (m[2] === 'done') sentence = who + ' marked it Done';
          else sentence = who + ' moved it to ' + (STATUS_WORD[m[2]] || m[2]);
        } else if ((m = /^Patched ([a-z_, ]+?)(?: \(status \w+ -> (\w+)\))?$/.exec(text))) {
          const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
          sentence = who + ' changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]) + (m[2] ? ' and moved it to ' + (STATUS_WORD[m[2]] || m[2]) : '');
        }
      }
      out.push({entry: e, who, line: historyLine(e, checklist), sentence});
    }
    return out.filter(r => !hidden.has(r.entry));
  }

  /* The answer that is already there for a question (someone else was first). Null when it is still open. */
  function winningAnswer(tickets, ticketId, questionId) {
    const t = arr(tickets).find(x => x && x.id === ticketId);
    const q = arr(t && t.questions).find(x => x && x.id === questionId);
    if (!q || q.answer == null) return null;
    return {text: String(q.answer), who: q.answered_by || '', via: q.via || ''};
  }

  /* The rows of "Needs you", each thing that needs the person exactly once: the same row id, or the same question of
     the same ticket (a core row and an add-on row for it), counts once. The Home badge and the list use this one list. */
  function uniqueNeeds(rows) {
    const seen = new Set(), out = [];
    for (const r of arr(rows)) {
      if (!r) continue;
      const q = r.answer && r.answer.question;
      const key = r.ticket && q ? 'q:' + r.ticket + ':' + q : 'id:' + r.id;
      if (seen.has(key)) continue;
      seen.add(key); out.push(r);
    }
    return out;
  }

  /* A row that only tells the person something and needs no answer (an add-on's note that offers just an OK, or a
     warning with no button): it stays reachable on Home as one quiet line and is never counted. */
  function isNotice(row) {
    const r = row || {}, acts = arr(r.actions);
    if (r.answer && r.answer.question && !acts.some(a => a && String(a.label).toLowerCase() === 'ok')) return false;
    if (!r.source || r.source === 'core' || r.kind === 'overdue-wait' || r.kind === 'addon:not-running') return false;
    if (acts.some(a => a && String(a.label).toLowerCase() === 'ok')) return true;
    return !r.answer && !acts.length && r.tone === 'warn';
  }
  /* A helper's changes waiting to be added: shown as "Changes to add" from the ticket, not as a second row. */
  const isBringBack = row => !!row && row.kind === 'copies:bring-back';
  /* The one "Needs you" number (Review menu entry, top bar, Home heading, Review page, Tickets pill, Focus): the open
     questions plus the results to check, the same things the Review page shows as cards (owner, 16 Nov, ORCH-63).
     One per question (a ticket with two open questions counts two); a ticket that only waits for another ticket, a
     failed start, a helper idle at its prompt and other rows without a question are shown on Home but not counted.
     results is a number or a list. */
  function needsYouCount(rows, results = 0) {
    const asked = new Set(arr(rows).filter(r => r && r.ticket && r.answer && r.answer.question && !isNotice(r) && !isBringBack(r))
      .map(r => r.ticket + ':' + r.answer.question)).size;
    return asked + (Array.isArray(results) ? results.length : Number(results) || 0);
  }

  /* True when "Needs you" already lists a question of this ticket (the question text is shown there only). */
  function inNeeds(rows, ticketId) {
    return arr(rows).some(r => r && r.ticket === ticketId && r.answer && r.answer.question);
  }

  /* The one button of a "Needs you" row. kind: answer (opens the question card), review (an add-on's own question),
     run (start the work again) or open (the ticket). */
  function needAction(row) {
    const r = row || {};
    const answerable = !!r.answer && r.kind !== 'overdue-wait';
    if (answerable && /^[a-z][a-z0-9-]*:/.test(String(r.kind || ''))) return {label: 'Review', kind: 'review'};
    if (answerable) return {label: 'Answer', kind: 'answer'};
    if (r.kind === 'addon:not-running' && !r.ticket) return {label: 'Start', kind: 'start'};  // a background add-on that stopped
    if (r.tone === 'bad' && r.ticket) return {label: 'Run again', kind: 'run'};
    return {label: 'Open', kind: 'open'};
  }

  /* Agents card: who works, who waits for the person, who is idle. Working comes from `runs`, idle from the
     tickets' sessions (newest session per agent that is not working now). */
  function agentRows(tickets, runs, nowMs) {
    const out = [], busy = new Set();
    for (const [tid, run] of Object.entries(runs || {})) {
      if (!run || (run.running !== true && run.state !== 'maybe-stale')) continue;
      const t = arr(tickets).find(x => x.id === tid);
      const agent = (run.claim && (run.claim.agent || run.claim.by)) || 'agent';
      const asks = arr(t && t.questions).some(q => q && q.answer == null);
      busy.add(String(agent).replace(/^(agent|human):/, ''));
      const idle = !asks && run.state !== 'maybe-stale' && run.claim && run.claim.live && run.claim.live.state === 'idle';  // a live session waiting for a message
      out.push({agent: String(agent).replace(/^(agent|human):/, ''), state: run.state === 'maybe-stale' ? 'stuck' : asks ? 'needs' : idle ? 'idle' : run.claim && run.claim.live && run.claim.live.state === 'starting' ? 'starting' : 'working',
        ticket: tid, since: idle ? run.claim.live.since : run.claim && run.claim.started_at});
    }
    const last = new Map();
    for (const t of arr(tickets)) for (const s of arr(t.sessions)) {
      const at = Date.parse(s && s.last_used);
      if (!s || !s.agent || Number.isNaN(at) || busy.has(s.agent)) continue;
      if (!last.has(s.agent) || at > last.get(s.agent).at) last.set(s.agent, {at, ticket: t.id});
    }
    for (const [agent, v] of last) if (nowMs - v.at >= 0) out.push({agent, state: 'idle', ticket: v.ticket, since: new Date(v.at).toISOString()});
    const rank = {needs: 0, stuck: 1, working: 2, starting: 2, idle: 3};
    return out.sort((a, b) => rank[a.state] - rank[b.state]);
  }

  /* ORCH-61: the ONE state of a running helper, as the core words it (orch run status "helper"):
     {state: working|starting|you|waiting|idle|stuck, word, detail}; null when no helper runs. An older core without
     the field: the same words from the claim, so the page never shows a second set. */
  const HELPER_WORDS = {working: 'Working', starting: 'Starting', you: 'Waits for you', waiting: 'On hold', idle: 'Idle', stuck: 'Stuck'};
  function helperState(run, ticket) {
    const r = run || null;
    if (!r || (r.running !== true && r.state !== 'maybe-stale')) return null;
    const h = r.helper;
    if (h && typeof h === 'object' && HELPER_WORDS[h.state]) return {state: h.state, word: HELPER_WORDS[h.state], detail: typeof h.detail === 'string' ? h.detail : ''};
    if (r.state === 'maybe-stale') return {state: 'stuck', word: 'Stuck', detail: 'No update for a while'};
    const live = (r.claim && r.claim.live) || {}, asks = arr(ticket && ticket.questions).some(q => q && q.answer == null);
    const key = live.state === 'attention' || (asks && live.state !== 'working') ? 'you' : live.state === 'starting' ? 'starting' : live.state === 'idle' ? 'idle' : 'working';
    return {state: key, word: HELPER_WORDS[key], detail: key === 'you' ? (asks ? 'Your answer' : 'Your OK on the screen') : ''};
  }
  /* Rows of the Helpers list (Home side panel; the live add-on page draws the same widget): one per running helper, in the order
     working, starting, waits for you, waiting, idle, stuck. Each: {ticket, state, word, detail, step, minutes, idle, finished}. */
  const HELPER_ORDER = ['working', 'starting', 'you', 'waiting', 'idle', 'stuck'];
  function helperRows(tickets, runs) {
    const out = [];
    for (const t of arr(tickets)) {
      const run = runs && runs[t.id], st = helperState(run, t);
      if (!st) continue;
      const tasks = arr(t.checklist).filter(c => c && !c.wont_do), at = tasks.findIndex(c => c.state === 'doing');
      const n = at >= 0 ? at : tasks.findIndex(c => !c.done);
      out.push({ticket: t, ...st, step: tasks.length && n >= 0 ? {n: n + 1, of: tasks.length} : null,
        minutes: Number.isFinite(run.age_seconds) ? Math.floor(run.age_seconds / 60) : null,
        idle: Number.isFinite(run.idle_seconds) ? Math.floor(run.idle_seconds / 60) : null,
        finished: ['review', 'done', 'dropped'].includes(t.status)});
    }
    return out.sort((a, b) => HELPER_ORDER.indexOf(a.state) - HELPER_ORDER.indexOf(b.state));
  }
  /* Links to other running pages of this workspace (label and address come from the services data). */
  function serviceLinks(services, ownOrigin) {
    return arr(services).filter(s => s && s.running === true && typeof s.url === 'string' && /^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/.test(s.url)
      && !s.url.startsWith(ownOrigin) && /^[a-z][a-z0-9-]{1,31}$/.test(String(s.addon || s.name)))
      .map(s => ({label: String(s.addon || s.name), url: s.url}));
  }

  const noPrefix = v => String(v || '').replace(/^(agent|human):/, '');
  const capital = v => String(v || '').charAt(0).toUpperCase() + String(v || '').slice(1);
  const minutes = ms => Math.max(0, Math.round(ms / 60000));
  const span = ms => { const m = minutes(ms); return m < 1 ? 'just now' : m < 60 ? m + ' min' : m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' days'; };

  function agentLabel(settings, claim = {}) {
    claim = claim || {};
    const agents = arr(settings && settings.agents).filter(Boolean);
    const match = agents.find(a => a.name === claim.agent);
    const chosen = agents.find(a => a.chosen);
    return capital(noPrefix(claim.label || match?.label || claim.agent || chosen?.label || chosen?.name || agents[0]?.label || agents[0]?.name || 'Helper'));
  }
  const matchesTicket = (ref, t) => !!ref && (ref === t.id || (!!t.key && String(ref).toLowerCase() === String(t.key).toLowerCase()));
  // Creation order (the plan order): the key number counts up with every new ticket; created_at only breaks ties.
  const keyNumber = c => Number(String(c && c.key || '').split('-').pop()) || 0;
  const creationOrder = (x, y) => keyNumber(x) - keyNumber(y) || (Date.parse(x.created_at) || 0) - (Date.parse(y.created_at) || 0) || String(x.id).localeCompare(String(y.id));
  function childrenOf(all, t) {
    const seen = new Set();
    return arr(all).filter(c => c && c.id !== t.id && (matchesTicket(c.parent, t) || arr(t.children).includes(c.id)) && !seen.has(c.id) && seen.add(c.id)).sort(creationOrder);
  }
  function parentOf(all, t) {
    return arr(all).find(p => p && p.id !== t.id && matchesTicket(t.parent, p)) ||
      arr(all).find(p => p && p.id !== t.id && arr(p.children).includes(t.id)) || null;
  }
  const plainFileName = value => String(value || '').split(/[\\/]/).pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase());
  const cleanOutcome = value => String(value || '').replace(/\b\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|bytes?)\b/gi, '').replace(/(?:[\w-]+\/)*[\w-]+\.(?:md|txt|html?|csv|json|pdf|png|jpe?g|webp)\b/gi, name => plainFileName(name)).replace(/^[\s✓✔·—,:;-]+|[\s·—,:;-]+$/g, '').replace(/\s+/g, ' ').trim();
  const resolved = task => !!(task.done || task.wont_do);
  function outcome(task) {
    if (task.wont_do) return "";
    const said = arr(task.evidence).slice().reverse().map(ev => cleanOutcome(ev.summary) || cleanOutcome(ev.text) || (ev.type === 'note' ? cleanOutcome(ev.ref) : '')).find(Boolean);
    return said || (task.done ? 'Completed.' : task.state === 'doing' ? 'Working on this task.' : 'Not started yet.');
  }

  /* The cause of a failed agent start in plain words ("the agent program was not found"), from waiting_on.ref. */
  function plainStartReason(ref) {
    const s = String(ref || '');
    const missing = /No such file or directory:?\s*'([^']+)'/i.exec(s) || /\[Errno 2\][^']*'([^']+)'/.exec(s);
    const program = missing && missing[1].split(/[\\/]/).pop();
    if (program && /^[A-Za-z0-9._-]{1,40}$/.test(program)) return 'the ' + program + ' program was not found';
    if (/Errno 13|Permission denied/i.test(s)) return 'it is not allowed to run';
    return 'it did not start';  // anything else (paths, commands, tokens) is never shown
  }

  /* {agent, reason, text} when the ticket waits because the agent could not be started (waiting_on.start), else null. */
  function startFailure(ticket, run, settings) {
    const t = ticket || {}, w = t.waiting_on;
    if (t.status !== 'waiting' || !w || w.start !== true || (run && run.running === true)) return null;
    const agent = agentLabel(settings, (run && run.claim) || {}), reason = plainStartReason(w.ref);
    return {agent, reason, text: agent + ' could not start: ' + reason};
  }

  /* The ONE agent line under the ticket title. state: working | starting | background | stuck | needs | failed | resume | new.
     primary = the main action {label, op, args} (op is a dashboard op, or "open" with a url); items = the rest, under "...". */
  function agentLine(ticket, run, nowMs, liveLink, settings) {
    const t = ticket || {}, r = run || null, id = t.id;
    const sessions = arr(t.sessions).slice().sort((a, b) => Date.parse(b.last_used || 0) - Date.parse(a.last_used || 0));
    const claim = (r && r.claim) || {};
    const agent = agentLabel(settings, claim);
    const asks = arr(t.questions).some(q => q && q.answer == null);
    const start = (label, extra) => ({label, op: 'run.start', args: {ticket: id, ...(extra || {})}});
    const stop = {label: 'Stop', op: 'run.stop', args: {ticket: id}};
    const fresh = {label: 'Start fresh', op: 'run.start', args: {ticket: id, fresh: true}};
    const since = claim.started_at ? ' · ' + span(nowMs - Date.parse(claim.started_at)) : '';
    // core: running is state == "alive"; a claim nobody renewed for a while is state "maybe-stale" with running false
    if (r && r.state === 'maybe-stale') return {state: 'stuck', agent, status: 'may be stuck · quiet for a while' + since,
      primary: start('Start anyway', {take_over: true}), items: [stop]};
    if (r && r.running === true) {
      const by = claim.by ? ' · started by ' + noPrefix(claim.by) : '';
      if (asks) return {state: 'needs', agent, status: 'needs your answer' + since, primary: {label: 'Answer', op: 'answer'}, items: [stop, fresh]};
      const waits = claim.live && claim.live.state === 'attention' ? (plainWhy(claim.live.why, agent) || 'waiting for your OK in the live session') : '';
      if (waits) return {state: 'needs', agent, status: waits, primary: liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : stop,
        items: liveLink ? [stop] : []};
      const live = liveLink ? {label: 'Open ' + liveLink.label, op: 'open', url: liveLink.url} : null;
      const hold = typeof r.hold === 'string' ? r.hold.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
      if (hold) return {state: 'working', agent, status: hold, hold, primary: live || stop, items: live ? [stop] : []};  /* the core's words, as is */
      if (claim.live && claim.live.state === 'starting') return {state: 'starting', agent, status: 'Starting…', primary: live || stop, items: live ? [stop] : []};
      if (claim.mode === 'oneshot') return {state: 'background', agent, status: 'works in the background (no live view)' + since,
        primary: live ? {...live, label: 'Watch in ' + liveLink.label} : stop, items: live ? [stop] : []};
      if (claim.live && claim.live.state === 'idle') return {state: 'idle', agent, status: 'live session open, waiting for a message' + by, primary: live || stop, items: live ? [stop] : []};
      return {state: 'working', agent, status: 'working' + by + since, primary: live || stop, items: live ? [stop] : []};
    }
    const sf = startFailure(t, r, settings);
    if (sf) return {state: 'failed', agent, status: sf.text, startFailed: true, primary: start('Retry'), items: []};
    if (r && r.state === 'dead') return {state: 'failed', agent, status: 'the last run ended without finishing',
      primary: start('Try again'), items: [fresh]};
    if (asks) return {state: 'needs', agent, status: 'needs your answer', primary: {label: 'Answer', op: 'answer'}, items: [fresh]};
    if (sessions[0]) {
      const when = Date.parse(sessions[0].last_used);
      return {state: 'resume', agent, status: 'last worked ' + (Number.isNaN(when) ? 'earlier' : span(nowMs - when) === 'just now' ? 'just now' : span(nowMs - when) + ' ago'),
        primary: start('Continue'), items: [fresh]};
    }
    // a ticket already waiting for the person's check has no run to start: no Start button
    if (t.status === 'review') return {state: 'new', agent, status: 'ready for you to check', primary: null, items: []};
    return {state: 'new', agent, status: 'not started yet', primary: start('Start'), items: []};
  }

  /* A Factory start question (kind factory:start) in a few lines for Home (ORCH-60). The question's text is the frozen
     proposal Factory wrote ("Start '<title>'? ~10 h · target $5 · you're needed for ~15 min. Goal: … . Done means: …
     Cap: 13 h active. …"); Home shows its title, goal and time only and links to the whole proposal. Null when the
     text is not in that shape (the card then shows the question as it always did). */
  function factoryStart(text) {
    const m = /^Start '(.+?)'\? ~([^.]+?)\. Goal: (.+?)\. Done means: /s.exec(String(text || ''));
    if (!m) return null;
    const head = m[2].split(' · '), cap = /\. Cap: (.+?) active\. /.exec(String(text))?.[1];
    const usd = head.map(x => /^target \$([0-9.]+)$/.exec(x)?.[1]).find(Boolean);
    const owner = head.map(x => /^you're needed for ~(.+)$/.exec(x)?.[1]).find(Boolean);
    const meta = ['Runs about ' + head[0], owner ? 'needs you for about ' + owner : '', usd ? 'about $' + usd : '', cap ? 'up to ' + cap + ' of helper time' : ''];
    return {title: m[1], goal: /[.!?…]$/.test(m[3]) ? m[3] : m[3] + '.', meta: meta.filter(Boolean).join(' · ')};
  }
  /* Its buttons as drawn (owner, 16 Nov): Not now, Change it, Start, Start last; each sends Factory's own option word. */
  const FACTORY_START_ORDER = ['Not now', 'Edit', 'Start'], FACTORY_START_LABEL = {Edit: 'Change it'};
  function factoryStartOptions(options) {
    const opts = arr(options);
    return opts.slice().sort((a, b) => (FACTORY_START_ORDER.indexOf(a) + 1 || 99) - (FACTORY_START_ORDER.indexOf(b) + 1 || 99))
      .map(o => ({answer: o, label: FACTORY_START_LABEL[o] || o}));
  }

  /* The line under an agent's "waiting" chip, in plain words: no command text, a login named as signing in. */
  function plainWhy(why, label) {
    const w = String(why || '');
    if (/wants a login|log in to|login method/i.test(w)) return (label || 'The helper') + ' needs you to sign in';
    return plainNames(w).replace(/\s*(Open the live session[^:]*:\s*)?orch run attach\s+\S+/gi, '').replace(/\s+/g, ' ').trim().replace(/[.:]$/, '');
  }

  /* One line of the question a ticket waits on (the first open one), for under its title; '' when none. */
  function questionPreview(ticket) {
    const q = arr(ticket && ticket.questions).find(x => x && x.answer == null && x.text);
    const text = q ? String(q.text).replace(/\s+/g, ' ').trim() : '';
    return text.length > 90 ? text.slice(0, 89) + '…' : text;
  }

  /* One state per ticket: a ticket the agent cannot go on with (live state attention) is Waiting, never Working. */
  function shownStatus(ticket, run) {
    const t = ticket || {}, live = run && run.claim && run.claim.live;
    return t.status === 'active' && live && live.state === 'attention' ? 'waiting' : t.status;
  }

  /* True while the yellow "Needs you" chip shows (an open question, or the agent needs you): the plain
     Waiting status chip is then left out, so the ticket shows one chip. */
  function showsAnswerChip(ticket, run) {
    const t = ticket || {}, live = run && run.claim && run.claim.live;
    return arr(t.questions).some(q => q && q.answer == null) || !!(live && live.state === 'attention');
  }

  /* Tickets tab tree: parents with their children (N of M done), children beyond 3 collapsed, a child whose parent is
     missing is shown as a top-level ticket. Input order is kept. */
  function treeRows(tickets) {
    const all = arr(tickets), byId = new Map(all.map(t => [t.id, t]));
    const byKey = new Map(all.filter(t => t.key).map(t => [String(t.key).toLowerCase(), t.id]));
    // `parent` is a ticket id, but real data may carry the key ("PIL-2"): both name the same parent
    const pid = t => t.parent && (byId.has(t.parent) ? t.parent : byKey.get(String(t.parent).toLowerCase())) || null;
    const kids = new Map();
    for (const t of all) if (pid(t) && pid(t) !== t.id) {
      if (!kids.has(pid(t))) kids.set(pid(t), []);
      kids.get(pid(t)).push(t);
    }
    // Children in the order they were made (the order of the work), not the order the page lists tickets.
    const made = t => Date.parse(t.created_at) || 0;
    for (const list of kids.values()) list.sort((a, b) => made(a) - made(b) || String(a.id).localeCompare(String(b.id)));
    const seen = new Set(), out = [];
    const walk = (t, depth, idx) => {
      if (seen.has(t.id)) return;
      seen.add(t.id);
      const ch = kids.get(t.id) || [];
      const done = ch.filter(c => c.status === 'done').length;
      out.push({ticket: t, depth, children: ch.length, done, parentMissing: !!t.parent && !pid(t), late: depth > 0 && idx >= 3});
      ch.forEach((c, i) => walk(c, depth + 1, i));
    };
    for (const t of all) if (!pid(t) || pid(t) === t.id) walk(t, 0, 0);
    for (const t of all) walk(t, 0, 0);  // a parent cycle still shows its tickets
    return out;
  }

  /* What helpers need (ORCH-45; look and words chosen by the owner on ORCH-43): the last check of every tool login,
     connection and key (state.logins = orch.health.last). States: works | soon | renew | unreachable. */
  const NEED_KINDS = ['login', 'connection', 'key'];
  const needKind = item => NEED_KINDS.includes(item && item.kind) ? item.kind : 'login';
  /* "GitHub login", "Company wiki connection", "Payments key" (a label that already ends in its kind keeps it). */
  function needName(item) {
    const label = String((item && (item.label || item.name)) || '').trim(), kind = needKind(item);
    return label.toLowerCase() === kind || label.toLowerCase().endsWith(' ' + kind) ? label : (label + ' ' + kind).trim();
  }
  /* The name in the list: a login says so ("GitHub login"); a connection or key shows its own name, the kind is below. */
  const needListName = item => needKind(item) === 'login' ? needName(item) : String((item && (item.label || item.name)) || '').trim();
  const needKindWord = item => ({login:'Login', connection:'Connection', key:'Key'})[needKind(item)];
  const LONG_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const endOf = item => { const d = item && item.ends_at ? new Date(item.ends_at) : null; return d && !isNaN(d) ? d : null; };
  /* "Monday 16 November at 22:24" (local time), '' without an end time. */
  function needEnds(item) {
    const d = endOf(item);
    return d ? LONG_DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + LONG_MONTHS[d.getMonth()] + ' at ' + dueClock(d) : '';
  }
  /* The state chip: {word, tone} with the kit badge tone. */
  function needState(item) {
    const d = endOf(item), short = d ? ' · ' + DUE_DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + DUE_MONTHS[d.getMonth()] : '';
    const s = item && item.state;
    return s === 'works' ? {word:'✓ Works', tone:'done'} : s === 'soon' ? {word:'Runs out soon' + short, tone:'needs'}
      : s === 'renew' ? {word:'Needs renewing', tone:'error'} : {word:'Cannot be reached', tone:'error'};
  }
  const needStopsWord = n => n ? 'Stops ' + n + (n === 1 ? ' ticket' : ' tickets') : '';
  /* The rows of the last check, cleaned: [{name, label, kind, state, ends_at, chosen, stops:[{id, key, title}]}]. */
  function needItems(logins) {
    return arr(logins && logins.items).filter(i => i && ['works', 'soon', 'renew', 'unreachable'].includes(i.state))
      .map(i => ({...i, kind:needKind(i), stops:arr(i.stops).filter(t => t && t.id)}));
  }
  /* Home: what runs out soon (a row in Needs you) and what stopped working (the red banner). */
  function needWarnings(logins) {
    const items = needItems(logins);
    return {soon:items.filter(i => i.state === 'soon'), stopped:items.filter(i => i.state === 'renew' || i.state === 'unreachable')};
  }
  /* The tickets a set of items stops, each once. */
  function needTickets(items) {
    const seen = new Map();
    for (const i of arr(items)) for (const t of arr(i.stops)) if (!seen.has(t.id)) seen.set(t.id, t);
    return [...seen.values()];
  }

  /* "just now" under a minute, else "5 min ago" / "2 h ago" / "3 days ago"; "" for no date. */
  function ago(iso, nowMs) {
    const when = Date.parse(iso);
    if (Number.isNaN(when)) return '';
    const s = span(nowMs - when);
    return s === 'just now' ? s : s + ' ago';
  }
  /* When something was added, in the person's own time: "today 16:05", "yesterday 09:12", "Mon 08:00", "5 Nov 2026, 09:12". */
  function stamp(iso, nowMs) {
    const d = new Date(iso), now = new Date(nowMs);
    if (!iso || Number.isNaN(d.getTime()) || Number.isNaN(now.getTime())) return '';
    const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    const two = n => String(n).padStart(2, '0'), time = two(d.getHours()) + ':' + two(d.getMinutes());
    if (diff === 0) return 'today ' + time;
    if (diff === 1) return 'yesterday ' + time;
    if (diff > -7 && diff < 7) return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()] + ' ' + time;  // same format as the kit's UI.stamp
    const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
    return d.getDate() + ' ' + month + ' ' + d.getFullYear() + ', ' + time;
  }
  /* A file proof: its title or file name, the size core saved in `text`, and when it was added ("hello.txt · 1 KB · today 16:05"). */
  function fileProofLabel(ev, nowMs) {
    const e = ev || {}, base = String(e.ref || '').split(/[\\/]/).pop();
    return [e.title || base || 'File', e.text, e.at && nowMs != null ? stamp(e.at, nowMs) : ''].filter(Boolean).join(' · ');
  }
  /* FO-14: who stands behind a proof. */
  function proofMark(ev) {
    return String((ev && ev.by) || '').startsWith('human:') ? {mark: '●', label: 'You'} : {mark: '○', label: 'Helper says'};
  }
  /* Leaving the page: every answer still in its Undo window is sent now. entries: [{state, send}]. Returns how many. */
  function flushPending(entries) {
    let n = 0;
    for (const e of arr(entries)) {
      const st = e && e.state && e.state.getState ? e.state.getState() : null;
      if (!st || st.phase !== 'pending' || typeof e.send !== 'function') continue;
      const answer = st.answer;
      e.state.reset();
      e.send(answer);
      n++;
    }
    return n;
  }

  /* A cron line in plain words for the common shapes (else the line itself): "30 7 * * *" -> "Every day at 07:30". */
  function cronHuman(value) {
    const raw = String(value == null ? '' : value).trim(), f = raw.split(/\s+/);
    if (f.length !== 5) return raw;
    const [mi, hr, dom, mon, dow] = f, num = x => /^\d{1,2}$/.test(x);
    const at = () => String(hr).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const every = /^\*\/(\d{1,2})$/.exec(mi);
    if (every && hr === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every ' + every[1] + ' minutes';
    if (num(mi) && hr === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every hour at :' + String(mi).padStart(2, '0');
    if (!num(mi) || !num(hr) || mon !== '*') return raw;
    if (dom === '*' && dow === '*') return 'Every day at ' + at();
    if (dom === '*' && dow === '1-5') return 'Weekdays at ' + at();
    if (dom === '*' && /^[0-7]$/.test(dow)) return 'Every ' + days[+dow] + ' at ' + at();
    if (num(dom) && dow === '*') return 'Every month on day ' + dom + ' at ' + at();
    return raw;
  }

  /* A text from the phone, as the workspace wrote it into the history (relay `_describe`), split into parts the page can
     show: {head, text, parts:[{type:'voice'|'photo'|'sound'|'file'|'location'|'feedback'|'pin'|'note', ...}]}.
     Files are only trusted when they sit in this ticket's files folder. */
  function phoneParts(text, tid) {
    const lines = String(text ?? '').split('\n');
    const first = /^From ([^:]{1,100}): (.*)$/.exec(lines[0] || '');
    if (!first) return null;
    const folder = '.orch/tickets/' + tid + '/files/';
    const out = {who: first[1], text: '', parts: []};
    const fileOf = rel => rel.startsWith(folder) && !rel.slice(folder.length).includes('..') && rel.length < 300 ? rel.slice(folder.length) : null;
    let m;
    for (const [i, raw] of [first[2], ...lines.slice(1)].entries()) {
      const line = raw.trimEnd();
      if (!line.trim()) continue;
      if ((m = /^Voice message \(([^)]*)\): "([\s\S]*)"$/.exec(line))) out.parts.push({type:'voice', lang:m[1], transcript:m[2]});
      else if (/^Voice message \(nothing could be understood\)$/.test(line)) out.parts.push({type:'voice', lang:'', transcript:''});
      else if ((m = /^(Photo|Voice recording|File): (\.orch\/\S.*)$/.exec(line)) && fileOf(m[2])) {
        const name = fileOf(m[2]);
        out.parts.push({type:m[1] === 'Photo' ? 'photo' : m[1] === 'Voice recording' ? 'sound' : 'file', name});
      } else if ((m = /^(Photo|Voice recording|File)(?: .*)?: could not be downloaded\.$/.exec(line)) || line === 'A file could not be saved.') out.parts.push({type:'note', text:'A file could not be loaded.'});
      else if ((m = /^Location: (-?[\d.]+), (-?[\d.]+)(?: \((.*)\))? - (https:\/\/maps\.apple\.com\/\?\S+)$/.exec(line))) out.parts.push({type:'location', lat:m[1], lon:m[2], label:m[3] || '', url:m[4]});
      else if ((m = /^Feedback on (.*?)(?: \(([A-Za-z0-9._:-]{1,12})\))?: (?:(\u{1F44D}) Looks good|changes wanted)$/u.exec(line))) out.parts.push({type:'feedback', title:m[1], rev:m[2] || '', approve:!!m[3]});
      else if ((m = /^ {2}(\d+|-)\. (.*)$/.exec(line))) {
        const w = /^(".*?"(?=: |$)|the page|page \d+|a page|the picture[^:]*)(?:: (.*))?$/.exec(m[2]);
        out.parts.push({type:'pin', n:m[1], where:w ? w[1] : '', said:w ? w[2] || '' : m[2]});
      } else if (/^ {2}\(\+\d+ more .* not shown\)$/.test(line) || /^\(Phone message /.test(line) || /^ {2}\(the rest is not shown\)$/.test(line)) continue;
      else if (i === 0) out.text = line === '(empty)' ? '' : line;  // the words the person typed
      else out.parts.push({type:'note', text:line.trim()});
    }
    return out;
  }

  // Narrow board: which column opens first, and the quiet label of a column chip.
  function firstColumnWithTickets(counts) {
    const keys = Object.keys(counts || {});
    return keys.find(k => counts[k] > 0) || keys[0] || '';
  }
  /* Watch live and Stop exist only while a helper is at work: a ticket waiting for the person's check (or finished)
     has nothing to watch or stop, even when its live session is still open. */
  const helperAlive = (ticket, run) => !!run && run.running === true && !['review', 'done'].includes(ticket && ticket.status);
  const needsYou = n => n + (n === 1 ? ' needs you' : ' need you');  // same words as the phone
  const columnChipLabel = (label, n) => n > 0 ? label + ' ' + n : label;
  // ORCH-58: the short ticket number people talk in (ORCH-58) goes before the title wherever a ticket shows.
  // `make` is the page's element maker h(); the result is [<span class="key">ORCH-58</span>, ' '] or null.
  const ticketKey = t => t && typeof t.key === 'string' ? t.key.trim() : '';
  const keyTag = (t, make) => { const k = ticketKey(t); return k ? [make('span', {className:'key'}, k), ' '] : null; };
  // "x of y steps": one pattern for every step counter (always "steps").
  const stepsText = (done, total) => (Number(done) || 0) + ' of ' + (Number(total) || 0) + (Number(total) === 1 ? ' step' : ' steps');
  // Topbar freshness: when /api/state last answered. Under a minute is "just now".
  function updatedText(at, nowMs) {
    const t = typeof at === 'number' ? at : Date.parse(at);
    if (!Number.isFinite(t)) return '';
    const min = Math.floor(Math.max(0, (Number(nowMs) || Date.now()) - t) / 60000);
    if (min < 1) return 'Updated just now';
    if (min < 60) return 'Updated ' + min + ' min ago';
    const hours = Math.floor(min / 60);
    return hours < 24 ? 'Updated ' + hours + (hours === 1 ? ' hour ago' : ' hours ago') : 'Updated ' + Math.floor(hours / 24) + (hours < 48 ? ' day ago' : ' days ago');
  }

  // ORCH-189 manager view. Helper time and money at list price: "1 h 40 min · $3.10"; "" without any.
  function durationWords(seconds) {
    const n = Number(seconds) || 0, m = Math.round(n / 60);
    if (n <= 0) return '';
    if (m < 1) return 'under 1 min';
    return m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min';
  }
  const moneyWords = cost => '$' + (Number(cost) || 0).toFixed(2);
  function spendWords(spend) {
    if (!spend || typeof spend !== 'object') return '';
    const time = durationWords(spend.seconds), cost = Number(spend.cost) || 0;
    return [time, cost > 0 ? moneyWords(cost) : ''].filter(Boolean).join(' · ');
  }
  function spendTotal(items) {
    return (items || []).reduce((sum, t) => ({cost:sum.cost + (Number(t?.spend?.cost) || 0), seconds:sum.seconds + (Number(t?.spend?.seconds) || 0)}), {cost:0, seconds:0});
  }
  // The one line under a stuck ticket (the core's reason; a stuck helper says its own words).
  function stuckWords(t, nowMs = Date.now()) {
    const why = t && t.stuck;
    if (why === 'question') {
      const open = (t.questions || []).filter(q => q && q.answer == null && !q.taken_back).map(q => Date.parse(q.sent_at || q.at)).filter(Number.isFinite);
      const days = open.length ? Math.floor((nowMs - Math.min(...open)) / 86400000) : 1;
      return 'Question waits ' + (days <= 1 ? '1 day' : days + ' days');
    }
    if (why === 'quiet') {
      const at = Date.parse(t.quiet_since || '');
      return Number.isFinite(at) ? 'No news for ' + Math.floor((nowMs - at) / 3600000) + ' h' : 'No news for a day';
    }
    if (why === 'overdue') return 'Past its due date';
    return '';
  }
  // This week = Monday 00:00 to Sunday 23:59 local. A ticket is "this week" when it is due by Sunday and not
  // finished, works now, or finished since Monday.
  function weekStart(nowMs = Date.now()) {
    const d = new Date(nowMs); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.getTime();
  }
  function inThisWeek(t, status, nowMs = Date.now()) {
    const start = weekStart(nowMs), end = start + 7 * 86400000;
    if (status === 'active') return true;
    if (status === 'done') { const at = Date.parse(t.done_at || t.updated_at); return Number.isFinite(at) && at >= start; }
    if (status === 'dropped' || !t.due) return false;
    const due = /T/.test(t.due) ? new Date(t.due).getTime() : new Date(t.due + 'T00:00').getTime();
    return Number.isFinite(due) && due < end;
  }
  return {durationWords, moneyWords, spendWords, spendTotal, stuckWords, weekStart, inThisWeek, ticketKey, keyTag, helperState, helperRows, HELPER_WORDS, dueWords, quietWords, dueLate, stepsText, updatedText, resolved, agentLabel, childrenOf, creationOrder, parentOf, plainFileName, cleanOutcome, outcome, plainNames, scrubText, historyWho, historyView, dedupeHistory, footerState, STATUS_WORD, STATUS_ORDER, STATUS_CHOICES, MOVE_CHOICES, statusWord, columnOf, helperAlive, needsYou, needsYouCount, isNotice, isBringBack, uniqueNeeds, inNeeds, firstColumnWithTickets, columnChipLabel, phoneParts, cronHuman, flushPending, historyLine, winningAnswer, needAction, agentRows, serviceLinks, agentLine, startFailure, plainStartReason, plainWhy, factoryStart, factoryStartOptions, questionPreview, shownStatus, showsAnswerChip, treeRows, proofMark, fileProofLabel, stamp, ago, needName, needListName, needKindWord, needEnds, needState, needStopsWord, needItems, needWarnings, needTickets};
});
