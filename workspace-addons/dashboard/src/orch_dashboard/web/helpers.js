'use strict';
// Pure helpers of the dashboard page (no DOM), so node can test them.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DashHelpers = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const arr = v => Array.isArray(v) ? v : [];
  const STATUS_WORD = {open: 'Backlog', ready: 'To do', active: 'Working', waiting: 'Needs you', review: 'Check', done: 'Done', dropped: "Won't do"};
  /* The ONE source of status words and order (board columns, Home, ticket page, Move to, history, lists).
     Lifecycle order. New tickets land in Backlog ("open"); To do ("ready") is what comes next, and paused or sent-back
     work; "waiting" shows as "Needs you". ORCH-152 (owner, 17 Nov): Backlog, To do, Waiting, Won't do, Superseded. */
  const STATUS_ORDER = ['open', 'ready', 'active', 'waiting', 'review', 'done'];
  const statusWord = (status, started) => (status === 'open' || status === 'ready') && started === true ? 'Paused' : STATUS_WORD[status] || 'Backlog';
  // A person's Send back that is not yet worked: Ready + a task made from their words (origin change_request) still open.
  // Derived, like the core's changes_asked: Undo and finishing the task clear it. Same rule, same word.
  const changesAsked = t => !!t && t.status === 'ready' && arr(t.checklist).some(c => c && c.origin === 'change_request' && !c.done && !c.wont_do);
  const columnOf = status => status;
  const STATUS_CHOICES = STATUS_ORDER.map(s => [s, STATUS_WORD[s]]);
  /* The board's lanes, left to right. "blocked" = Waiting: waits for a date, another ticket or the outside, with no
     open question. "superseded" = Won't do because another ticket replaces it (superseded_by). */
  const LANES = [['open', 'Backlog'], ['ready', 'To do'], ['active', 'Working'], ['waiting', 'Needs you'], ['blocked', 'Waiting'],
    ['review', 'Check'], ['done', 'Done'], ['dropped', "Won't do"], ['superseded', 'Superseded']];
  /* "Move to" (ticket page, list, board card) offers every lane but Needs you, which only a helper's question makes.
     Waiting asks for its date and reason, Superseded for the ticket that replaces it (ORCH-235: the same places
     everywhere). */
  const MOVE_CHOICES = LANES.filter(([lane]) => lane !== 'waiting');
  /* The lane of a ticket. `status` is the status as shown (a live helper that needs the person shows as waiting);
     `asks` is true while the ticket has an open question. */
  function laneOf(t, status, asks) {
    const s = status || (t && t.status) || 'open';
    if (s === 'dropped') return t && t.superseded_by ? 'superseded' : 'dropped';
    if (s === 'done') return 'done';
    if (asks) return 'waiting';
    if (s === 'waiting') return ((t && t.waiting_on) || {}).kind === 'question' ? 'waiting' : 'blocked';
    return STATUS_WORD[s] ? s : 'open';
  }
  /* What a move to a lane writes: {status[, waiting_on | superseded_by]}, or null when the lane needs more first
     (Waiting asks for a date, Superseded for the ticket that replaces it). */
  function laneMove(lane, extra) {
    const x = extra || {};
    if (lane === 'blocked') return x.until ? {status: 'waiting', waiting_on: {kind: 'time', until: x.until}} : null;
    if (lane === 'superseded') return x.by ? {status: 'dropped', superseded_by: x.by} : null;
    if (lane === 'dropped') return {status: 'dropped', superseded_by: null};
    return STATUS_WORD[lane] ? {status: lane} : null;
  }
  /* ORCH-235: what a Waiting ticket waits for, in one line: "Waits until Mon 09:00 · The price list",
     "Waits for ORCH-12", "Waits: the supplier". `all` finds the other ticket, `stamp(at)` says a time. '' = nothing known. */
  function waitWords(t, all, stamp) {
    const w = (t && t.waiting_on) || {}, ref = typeof w.ref === 'string' ? w.ref.trim() : '';
    if (w.kind === 'ticket' && ref) {
      const other = arr(all).find(o => o && (o.id === ref || (o.key && String(o.key).toLowerCase() === ref.toLowerCase())));
      return 'Waits for ' + (other ? other.key || other.title : 'another ticket');
    }
    if (w.kind === 'time' && w.until) return 'Waits until ' + (stamp ? stamp(w.until) : w.until) + (ref ? ' · ' + ref : '');
    if (w.kind === 'external' && ref) return 'Waits: ' + ref;
    return '';
  }
  const FIELD_WORD = {title: 'the title', owner: 'the owner', due: 'the due day', note: 'the note', summary: 'the summary',
    status: 'the status', done_when: 'the Done when line'};

  /* Due dates (G1). `due` is "YYYY-MM-DD" (a day) or "YYYY-MM-DDTHH:MM" (local wall time, no zone). Only a due with a
     time gets words here: "Due 18:30" (today), "Due Mon 16 Nov, 18:30" (within a week), "Due 14 Nov 2026, 18:30" (further),
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
    const gap = Math.round((new Date(at.getFullYear(), at.getMonth(), at.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
    // ORCH-240: within a week the day of the month too ("Due Mon 16 Nov, 18:30"), never a bare weekday
    const words = gap !== 0 && Math.abs(gap) < 7 ? DUE_DAYS[at.getDay()] + ' ' + at.getDate() + ' ' + DUE_MONTHS[at.getMonth()] + ', ' + dueClock(at) : whenWords(at, now);
    return (at < now && status !== 'done' && status !== 'dropped' ? 'Late since ' : 'Due ') + words;
  }
  /* G2: "Quiet since 09:20" for a Working ticket quiet for 6 h. `since` is `quiet_since` (UTC ISO, computed once by
     orch.tickets.quiet_since); shown in local time. '' when the ticket is not quiet. The same words as
     orch.tickets.quiet_label (the CLI). */
  function quietWords(since, now) {
    const at = since ? new Date(since) : null;
    return at && !isNaN(at) ? 'Quiet since ' + whenWords(at, now || new Date()) : '';
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
    return String(text ?? '').replace(/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g, (_, n) => NAMES[n] || n.charAt(0).toUpperCase() + n.slice(1));
  }
  /* ORCH-1161: people of the workspace's person list act as human:pr_<id>; the page shows their name (a rename shows
     everywhere at once, a removed person reads "Lea (removed)"). Old lines keep their old names. */
  let NAMES = {};
  function setPersonNames(map) {
    NAMES = {};
    for (const [id, name] of Object.entries(map && typeof map === 'object' ? map : {})) {
      if (/^pr_[a-z0-9]{10}$/.test(id) && typeof name === 'string' && name) NAMES[id] = name;
    }
  }
  const listedName = by => NAMES[String(by || '').replace(/^human:/, '')] || null;

  /* A task finished by the agent is written twice (orch's own "Check c1 done" and the agent's own note): both read
     "Finished a task: ...". Within two minutes the longer of two equal-or-prefix lines stays, once. Original order kept. */
  /* ORCH-185: the old and new text of a note edit, when the line carries them ("Edited note (was: ... | now: ...)"). */
  /* ORCH-240: also the title, owner, due day and a renamed task. */
  function historyChange(entry) {
    const text = String((entry && entry.text) || '').trim();
    const m = /^(?:Edited (note|done_when|owner|due)|(Title) changed|Renamed (c\d+)) \(was: ([\s\S]*) \| now: ([\s\S]*)\)$/.exec(text);
    return m ? {field: m[1] || (m[2] ? 'title' : 'task'), was: m[4], now: m[5]} : null;
  }
  function dedupeHistory(entries, checklist) {
    const list = Array.isArray(entries) ? entries : [], drop = new Set(), last = [];
    const order = list.map((e, i) => [e, i]).sort((a, b) => (Date.parse(a[0] && a[0].at) || 0) - (Date.parse(b[0] && b[0].at) || 0) || a[1] - b[1]);
    for (const [e] of order) {
      const line = historyLine(e, checklist), at = Date.parse(e && e.at) || 0;
      const dup = last.find(p => !(historyChange(e) && historyChange(p.e)) && Math.abs(at - p.at) <= 120000 && (p.line === line || line.startsWith(p.line + ':') || p.line.startsWith(line + ':')));
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
    if ((m = /^Added check (c\d+)$/.exec(text))) return 'Added a task' + task(m[1]);
    if ((m = /^Marked (c\d+) as won't do$/.exec(text))) return "Marked as won't do" + task(m[1]);
    if ((m = /^Check (c\d+) done$/.exec(text))) return 'Finished a task' + task(m[1]);
    // ORCH-240: never a raw task id ("Reopened c1"); the old and new text show below the line (historyChange)
    if ((m = /^Reopened (c\d+)(?: \(old evidence: [\s\S]*\))?$/.exec(text))) return 'Opened a task again' + task(m[1]);
    if ((m = /^Renamed (c\d+)( \(was: [\s\S]* \| now: [\s\S]*\))?$/.exec(text))) return 'Renamed a task' + (m[2] ? '' : task(m[1]));
    if ((m = /^Linked (c\d+) to Done when$/.exec(text))) return 'Linked a task to Done when' + task(m[1]);
    if ((m = /^Removed step c\d+ '([\s\S]*)' \((?:was done|was open)(?:; evidence: [\s\S]*)?\)$/.exec(text))) return 'Removed a task: ' + m[1];
    if (/^Title changed(?: \(was: [\s\S]* \| now: [\s\S]*\))?$/.test(text)) return 'Changed the title';
    if ((m = /^Set ext\.([a-z][a-z0-9-]*)$/.exec(text))) return 'Updated ' + addon(m[1]) + ' settings';
    if ((m = /^Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?$/.exec(text))) return 'Removed ' + addon(m[1]) + ' settings';
    if (/^Created under t_\w+$/.test(text)) return 'Created as a sub-ticket';
    if ((m = /^Recorded a check run for (c\d+)(?: \(exit (\d+)\))?$/.exec(text))) return 'Ran a check' + task(m[1]) + (m[2] == null ? '' : m[2] === '0' ? ' (passed)' : ' (failed)');
    if ((m = /^Moved (c\d+) after c\d+$/.exec(text))) return 'Moved a task' + task(m[1]);
    if ((m = /^Created under (.+)$/.exec(text))) return 'Created under ' + m[1];
    if (/^Created/.test(text)) return /under /.test(text) ? 'Created as a sub-ticket' : 'Ticket created';
    if ((m = /^Edited ([a-z_, ]+?)(?: \(was: [\s\S]* \| now: [\s\S]*\))?$/.exec(text)) || (m = /^Edited (.+)$/.exec(text))) {
      const parts = m[1].split(/,\s*/).map(f => FIELD_WORD[f.trim()] || f.trim());
      return 'Changed ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]);
    }
    if (/^Asked\b/.test(text)) return 'Asked a question';
    if (/^Answered q\d+/.test(text)) return 'Answered a question';
    if ((m = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text))) return 'Moved to ' + (STATUS_WORD[m[1]] || m[1]);
    if (/^Summary/.test(text)) return 'Updated the summary';
    if ((m = /^Added (?:task|check)[:\s]+(.+)$/i.exec(text))) return 'Added a task: ' + m[1];
    if ((m = /^Finished a (?:task|step)[:\s]+(.+)$/i.exec(text))) return 'Finished a task: ' + m[1];
    if (/^(Updated|Removed) .+ settings$/.test(text)) return text;
    if (/^Check c\d+ done/i.test(text) || /^(Checked|Done)\b.*\bc\d+/.test(text) || /^Task .* done/i.test(text)) return 'Finished a task';
    if (/^Added task|^Added check/i.test(text)) return 'Added a task';
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
  /* A person's name for a "by": a line recorded under the computer's login ("human:lume") is the person who picked
     their name in "You: ..." (people.me), never the login (ORCH-184). Agents and other people keep their own name. */
  function personName(by, st) {
    if (listedName(by)) return listedName(by);
    const b = String(by || '').replace(/^(?:agent|human):/, ''), s = st || {};
    const me = s.people && s.people.me;
    return /^human:/.test(String(by || '')) && me && s.login && b === s.login ? me : b;
  }

  function historyWho(by, me) {
    const b = String(by || '');
    if (me && b === me) return 'You';
    if (listedName(b)) return listedName(b);
    if (/^human:pr_[a-z0-9]{10}$/.test(b)) return 'Someone';  // a person id without the list (a shared copy)
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
      // a line stamped with a person (people list on) reads as that person's name; "You" stays "You"
      const who = (me && by === me) ? 'You' : (listedName(e && e.person) || historyWho(by, me));
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
  /* The open questions plus the results to check, the same things the Review page shows as cards (owner, 16 Nov,
     ORCH-63). The dashboard's one "Needs you" number (needsYouTotal) adds the rows of work that stopped (ORCH-705).
     One per question (a ticket with two open questions counts two); a ticket that only waits for another ticket, a
     helper idle at its prompt and other rows without a question are shown on Home but not counted here (a failed start
     is added by needsToday, ORCH-1687).
     results is a number or a list. */
  function needsYouCount(rows, results = 0) {
    const asked = new Set(arr(rows).filter(r => r && r.ticket && r.answer && r.answer.question && !isNotice(r) && !isBringBack(r))
      .map(r => r.ticket + ':' + r.answer.question)).size;
    return asked + (Array.isArray(results) ? results.length : Number(results) || 0);
  }
  /* A Factory draft that is ready for Plan the run (Factory's own row, kind factory:draft, ORCH-479): it waits for the
     person like a question, so it is listed and counted on Home and Review the same as on the Factory page. */
  function isFactoryDraft(row) {
    return !!row && row.source === 'factory' && row.kind === 'factory:draft' && typeof row.ticket === 'string' && /^t_[a-z0-9]{6,16}$/.test(row.ticket);
  }
  /* One per order (the newest version's row). */
  function factoryDrafts(rows) {
    const seen = new Set();
    return arr(rows).filter(r => isFactoryDraft(r) && !seen.has(r.ticket) && seen.add(r.ticket));
  }
  /* The words Plan the run and Ask for changes send to the agent on the order, as the person's message: the same as the
     Factory page sends (workspace-addons/factory/src/orch_factory/web/factory.js, PLAN_TEXT), so the agent gets one wording. */
  const FACTORY_DRAFT_WORDS = {
    plan: 'Now plan the run: propose the whole run for this order (orch factory propose).',
    change: words => 'Change the draft: ' + String(words || '').trim(),
  };

  /* ORCH-476: the core's one count (state.counts, made by orch/counts.py from the same tickets and runs the page draws).
     needsYouFrom: the needs-you items minus the ones this page hides for a moment (an answer being sent, a "Not now"
     for today), so the number always equals the rows shown. null with an older core: the page counts as before. */
  function needsYouFrom(counts, hiddenRows) {
    const n = counts && counts.needs_you;
    if (!n || !Array.isArray(n.items)) return null;
    const hidden = new Set(arr(hiddenRows).filter(r => r && r.ticket && r.answer && r.answer.question).map(r => r.ticket + ':' + r.answer.question));
    const items = n.items.filter(i => i && !(i.question && hidden.has(i.ticket + ':' + i.question)));
    // ORCH-1687: a failed start is its own part (the page lists it from the ticket, with Try again), never a result
    const questions = items.filter(i => i.question).length, failed = items.filter(i => !i.question && i.start).length;
    return {count: items.length, questions, results: items.length - questions - failed, failed, items};
  }
  const countsOf = (counts, t) => (counts && counts.tickets && t && counts.tickets[t.id]) || null;
  /* "Step n of total" of a ticket: the core's step (every task counts, a won't-do one too; the task being done, else
     the first open one). The same rule here for an older core. */
  function stepOf(counts, t) {
    const c = countsOf(counts, t);
    if (c) return c.step || null;
    if (!t || ['done', 'dropped'].includes(t.status)) return null;
    const tasks = arr(t.checklist).filter(Boolean), open = tasks.map((c, i) => [c, i]).filter(([c]) => !c.done && !c.wont_do);
    const at = (open.find(([c]) => c.state === 'doing') || open[0] || [])[1];
    return at == null ? null : {n: at + 1, of: tasks.length};
  }
  /* {done, wont_do, doing, todo, finished, total} of a ticket's tasks: the core's progress, the same rule for an older core. */
  function progressOf(counts, t) {
    const c = countsOf(counts, t);
    if (c && c.progress) return c.progress;
    const tasks = arr(t && t.checklist).filter(Boolean);
    const done = tasks.filter(c => c.done && !c.wont_do).length, wont = tasks.filter(c => c.wont_do).length;
    const doing = tasks.filter(c => !c.done && !c.wont_do && c.state === 'doing').length;
    return {done, wont_do: wont, doing, todo: tasks.length - done - wont - doing, finished: done + wont, total: tasks.length};
  }
  const WONT_DO = "Won't do";  // the one word for a task that will not be done (never "skipped")

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
    if (r.kind === 'overdue-wait' && r.ticket) return {label: 'Continue', kind: 'run'};  // ORCH-255: a passed wake time with no helper
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
     {state: working|starting|you|waiting|idle|stuck|limit, word, detail}; null when no helper runs. An older core without
     the field: the same words from the claim, so the page never shows a second set. */
  const HELPER_WORDS = {working: 'Working', starting: 'Starting', you: 'Needs you', waiting: 'On hold', idle: 'Idle', stuck: 'Stuck', limit: 'Stopped: usage limit'};
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
     working, starting, needs you, waiting, idle, stuck, stopped on the usage limit. Each: {ticket, state, word, detail, step, minutes, idle, finished}. */
  const HELPER_ORDER = ['working', 'starting', 'you', 'waiting', 'idle', 'stuck', 'limit'];
  function helperRows(tickets, runs, counts) {
    const out = [];
    for (const t of arr(tickets)) {
      const run = runs && runs[t.id], st = helperState(run, t);
      if (!st) continue;
      // the core's step (stepOf): every task counts, a won't-do one too, so "Step 4 of 4" sits beside "3 of 4 tasks"
      out.push({ticket: t, ...st, step: stepOf(counts, t),
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
  const span = ms => { const m = minutes(ms); return m < 1 ? 'just now' : m < 60 ? m + ' min' : m < 1440 ? Math.round(m / 60) + ' h' : (d => d + (d === 1 ? ' day' : ' days'))(Math.round(m / 1440)); };

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
  /* ORCH-156: the tickets a ticket can be put under ("Part of" in Edit ticket): not itself, not one of its own
     sub-tickets (a loop), not closed (its current parent stays listed). Releases, epics, then tickets that already
     hold others, then the rest; newest first inside each group. */
  /* parentOf for every ticket of one list in one pass (ORCH-522): parentOf per ticket read the whole list each time,
     2.5 million comparisons for the Part of choices at 1,600 open tickets (most of a second per ticket page).
     Same answer as parentOf(list, x): the first match in list order, by parent reference, else by a children list. */
  function parentIndex(list) {
    const put = (map, k, i) => { const a = map.get(k); if (!a) map.set(k, [i]); else if (a[a.length - 1] !== i) a.push(i); };
    const byId = new Map(), byKey = new Map(), byChild = new Map();
    list.forEach((p, i) => {
      put(byId, p.id, i);
      if (p.key) put(byKey, String(p.key).toLowerCase(), i);
      for (const c of arr(p.children)) put(byChild, c, i);
    });
    const first = (x, ...lists) => {
      let best = -1;
      for (const a of lists) for (const i of a || []) if (list[i].id !== x.id && (best < 0 || i < best)) { best = i; break; }
      return best;
    };
    // every ticket a reference names (by id, or by key in any case), in list order
    const named = ref => !ref ? [] : [...new Set([...(byId.get(ref) || []), ...(byKey.get(String(ref).toLowerCase()) || [])])];
    return {
      named,
      of(x) {
        let i = x.parent ? first(x, byId.get(x.parent), byKey.get(String(x.parent).toLowerCase())) : -1;
        if (i < 0) i = first(x, byChild.get(x.id));
        return i < 0 ? null : list[i];
      },
    };
  }
  function parentChoices(all, t) {
    const list = arr(all).filter(x => x && x.id), inside = new Set([t.id]), index = parentIndex(list);
    // its own sub-tickets at any depth: a ticket whose parent reference names one already inside
    const kids = new Map();
    for (const x of list) for (const i of index.named(x.parent)) { const id = list[i].id; if (!kids.has(id)) kids.set(id, []); kids.get(id).push(x); }
    for (const queue = [t.id]; queue.length;) for (const x of kids.get(queue.pop()) || []) if (!inside.has(x.id)) { inside.add(x.id); queue.push(x.id); }
    const current = parentOf(list, t), holds = new Set(list.map(x => (index.of(x) || {}).id).filter(Boolean));
    const rank = x => x.release ? 0 : x.epic ? 1 : holds.has(x.id) ? 2 : 3;  // ORCH-37: releases first
    return list.filter(x => !inside.has(x.id) && (!['done', 'dropped'].includes(x.status) || (current && x.id === current.id)))
      .sort((x, y) => rank(x) - rank(y) || creationOrder(y, x));
  }
  /* ORCH-156: the order inside one board lane. A ticket the person placed in this lane (lane_order) keeps its
     place; tickets that came in since (no place in this lane) stay on top in the order given, newest news first. */
  const lanePlace = (t, lane) => t && t.lane_order && t.lane_order.lane === lane && Number.isFinite(t.lane_order.n) ? t.lane_order.n : null;
  function laneSorted(list, lane) {
    const all = arr(list), fresh = all.filter(t => lanePlace(t, lane) == null);
    const placed = all.filter(t => lanePlace(t, lane) != null).map((t, i) => [t, i]).sort((x, y) => lanePlace(x[0], lane) - lanePlace(y[0], lane) || x[1] - y[1]).map(x => x[0]);
    return [...fresh, ...placed];
  }
  /* The lane's ids after `moved` goes right before `before` (null: to the end of the lane). */
  function laneReorder(ids, moved, before) {
    if (moved === before) return arr(ids).slice();  // dropped onto itself: nothing moves
    const rest = arr(ids).filter(id => id !== moved), at = before == null ? -1 : rest.indexOf(before);
    rest.splice(at < 0 ? rest.length : at, 0, moved);
    return rest;
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
      // "no live view" only when there is nothing to watch: never next to a Watch button (report r-1118-0907)
      if (claim.mode === 'oneshot') return {state: 'background', agent, status: 'works in the background' + (live ? '' : ', nothing to watch live') + since,
        primary: live ? {...live, label: 'Watch in ' + liveLink.label} : stop, items: live ? [stop] : []};
      if (claim.live && claim.live.state === 'idle') return {state: 'idle', agent, status: 'live session open, waiting for a message' + by, primary: live || stop, items: live ? [stop] : []};
      return {state: 'working', agent, status: 'working' + by + since, primary: live || stop, items: live ? [stop] : []};
    }
    const sf = startFailure(t, r, settings);
    if (sf) return {state: 'failed', agent, status: sf.text, startFailed: true, primary: start('Try again'), items: []};
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
     proposal Factory wrote ("Start '<title>'? ~10 h · AI cost about $5 · you're needed for ~15 min. Goal: … . Done means: …
     Time limit: 13 h active. …"); Home shows its title, goal and time only and links to the whole proposal. Null when the
     text is not in that shape (the card then shows the question as it always did). */
  function factoryStart(text) {
    const m = /^Start '(.+?)'\? ~([^.]+?)\. Goal: (.+?)\. Done means: /s.exec(String(text || ''));
    if (!m) return null;
    const head = m[2].split(' · '), cap = /\. Time limit: (.+?) active\. /.exec(String(text))?.[1];
    const usd = head.map(x => /^(?:target|AI cost about) \$([0-9.]+)$/.exec(x)?.[1]).find(Boolean);
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

  /* When a ticket was finished: the history entry that marked it done, else done_at, else the last change. Every page
     (Home, Tickets, the board, the ticket) takes the day and time from here, so one ticket never has two dates (ORCH-184). */
  function doneAt(ticket) {
    const t = ticket || {}, event = arr(t.history).slice().reverse().find(e => e && (e.kind === 'done' || /(?:->|to) done\b|^Done\b/i.test(e.text || '')));
    return (event && event.at) || t.done_at || t.completed_at || t.updated_at || '';
  }

  /* When a ticket's question was asked: the time Home shows for it (the oldest open row of that ticket), else the last
     change. Home, Tickets and the ticket page say the same wait (ORCH-184). */
  function askedAt(ticket, rows) {
    const id = ticket && ticket.id, times = arr(rows).filter(r => r && r.ticket === id && Number.isFinite(Date.parse(r.since))).map(r => Date.parse(r.since));
    return times.length ? new Date(Math.min(...times)).toISOString() : (ticket && ticket.updated_at) || '';
  }

  /* Is phone mode on right now? A mode whose end time has passed is over, whatever the last state said (ORCH-184). */
  function mobileOn(mm, nowMs) {
    if (!mm || !mm.on) return false;
    const end = mm.ends_at ? Date.parse(mm.ends_at) : NaN;
    return !(Number.isFinite(end) && end <= (Number(nowMs) || Date.now()));
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
  /* Terminal commands a helper wrote in backticks in a question (ORCH-218: "Sign in again with `az login`"): at most two,
     each a tool name and at least one more word in plain characters, so a quoted name or `c1` is never one. */
  const questionCommands = text => [...new Set([...String(text || '').matchAll(/`([^`\n]{3,120})`/g)].map(m => m[1].trim())
    .filter(c => /^[a-z][a-z0-9._-]{0,31}( [A-Za-z0-9._:=\/@,'"+-]+)+$/.test(c)))].slice(0, 2);
  /* The question as shown: the backticks around those commands dropped (the command itself stays in the words). */
  const questionWords = text => { const cmds = questionCommands(text); return cmds.reduce((t, c) => t.split('`' + c + '`').join(c), String(text ?? '')); };
  const needOwnStep = item => item && item.state !== 'works' && !item.renew && !item.key;
  /* The terminal command that signs in again (ORCH-218: 'az login'), shown with a Copy button under the words. */
  const needSignIn = item => needOwnStep(item) && typeof item.sign_in === 'string' && /^[A-Za-z0-9][A-Za-z0-9 ._:=\/@,'"+-]{0,119}$/.test(item.sign_in) ? item.sign_in : '';
  /* What the person does to renew when orch cannot start it (ORCH-48): the check's own plain step, else the lead line of
     its sign-in command; none when a Renew or Replace button is there or it works. */
  const needHow = item => !needOwnStep(item) ? '' : typeof item.how === 'string' && item.how ? item.how : needSignIn(item) ? 'Open a terminal on this computer and run:' : '';
  /* The rows of the last check, cleaned: [{name, label, kind, state, ends_at, chosen, stops:[{id, key, title}]}]. */
  function needItems(logins) {
    return arr(logins && logins.items).filter(i => i && ['works', 'soon', 'renew', 'unreachable'].includes(i.state))
      .map(i => ({...i, kind:needKind(i), stops:arr(i.stops).filter(t => t && t.id)}));
  }
  // Only a helper's own failed login blocks a start; unrelated connections do not.
  function helperStartReason(logins, helper = '') {
    const item = needItems(logins).find(i => i.helper && (helper ? i.helper === helper : i.chosen)
      && ['renew', 'unreachable'].includes(i.state));
    return item ? 'The ' + needName(item) + (item.state === 'unreachable' ? ' cannot be reached.' : ' stopped working.') : '';
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
  // ORCH-906 (owner picked it, 20 Nov): an epic or a release says so wherever the ticket shows, not only on its board
  // card. `make` is the page's h(); the result is [' ', <span class="chip kind">Epic</span>] or null for a plain ticket.
  const kindWord = t => t && t.release ? 'Release' : t && t.epic ? 'Epic' : '';
  const kindTag = (t, make) => { const w = kindWord(t); return w ? [' ', make('span', {className:'chip kind', 'data-key':'kind-' + w.toLowerCase()}, w)] : null; };
  // "x of y tasks": one pattern for every task counter (owner, 17 Nov: the to-do lines are "tasks" everywhere).
  const stepsText = (done, total) => (Number(done) || 0) + ' of ' + (Number(total) || 0) + (Number(total) === 1 ? ' task' : ' tasks');
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
    return m >= 60 ? Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '') : m + ' min';
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
  // The ticket page's Time · cost: the helper's first-run estimate beside what it took so far (ORCH-189).
  function costLine(t) {
    const est = t && t.estimate, parts = [];
    if (est && typeof est === 'object') {
      // ORCH-740/742: a range keeps the high end in minutes / cost and the low end in minutes_low / cost_low
      const okM = v => Number.isInteger(v) && v > 0, okC = v => typeof v === 'number' && v >= 0;
      const m = okM(est.minutes) ? (okM(est.minutes_low) && est.minutes_low < est.minutes ? durationWords(est.minutes_low * 60) + '–' : '') + durationWords(est.minutes * 60) : '';
      const c = okC(est.cost) ? (okC(est.cost_low) && est.cost_low < est.cost ? moneyWords(est.cost_low) + '–' : '') + moneyWords(est.cost) : '';
      if (m || c) parts.push('Estimate: about ' + [m, c].filter(Boolean).join(' · '));
    }
    if (!parts.length && t && !t.spend && typeof t.range === 'string' && t.range) parts.push('Before Start: ' + t.range);  // ORCH-297
    const so = spendWords(t && t.spend);
    if (so) parts.push('So far: ' + so);
    return parts.join(' — ');
  }
  // The one line above a start (UX D2, ORCH-415): the model, the ticket's estimate and what it used so far; a start is never free.
  function startCostWords(t, model) {
    const est = t && t.estimate, spent = Number(t && t.spend && t.spend.cost) || 0;
    const parts = [];
    if (est && typeof est.cost === 'number' && est.cost >= 0.005) parts.push('estimate about ' + moneyWords(est.cost));
    else if (!spent && t && typeof t.range === 'string' && t.range) parts.push(t.range);  // before the first start (ORCH-297)
    if (spent >= 0.005) parts.push(moneyWords(spent) + ' used so far');
    const money = parts.length ? parts.join(', ') : 'a start uses paid helper time';
    return model ? 'On ' + model + ' · ' + money : money.charAt(0).toUpperCase() + money.slice(1);
  }
  // The one line under a stuck ticket (the core's reason; a stuck helper says its own words).
  function stuckWords(t, nowMs = Date.now()) {
    const why = t && t.stuck;
    if (why === 'question') {
      const open = (t.questions || []).filter(q => q && q.answer == null && !q.taken_back).map(q => Date.parse(q.asked_at || q.sent_at || q.at)).filter(Number.isFinite);
      const days = open.length ? Math.floor((nowMs - Math.min(...open)) / 86400000) : 1;
      return 'Question waits ' + (days <= 1 ? '1 day' : days + ' days');
    }
    if (why === 'quiet') {
      const at = Date.parse(t.quiet_since || '');
      return Number.isFinite(at) ? 'Quiet for ' + Math.floor((nowMs - at) / 3600000) + ' h' : 'Quiet for a day';
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
  /* ORCH-1081 (owner picked draft C): the Tickets calendar. Weeks as rows (Mon-Fri plus one Weekend cell), late
     tickets leave their day for one Late list, a day with 5 or more tickets shows 3 and "+N more". Days are local
     "YYYY-MM-DD" strings: a due "2026-11-20T18:30" is local wall time and lands on the 20th. Only `due` counts. */
  const CAL_DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const CAL_DOW_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const CAL_MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const calDate = s => { const [y, m, d] = String(s).split('-').map(Number); return new Date(y, m - 1, d, 12); };
  const calAdd = (s, n) => { const d = calDate(s); d.setDate(d.getDate() + n); return dueKey(d); };
  const calDow = s => (calDate(s).getDay() + 6) % 7;
  const calMonday = s => calAdd(s, -calDow(s));
  const calOkDay = v => /^\d{4}-\d{2}-\d{2}$/.test(String(v || '')) && dueKey(calDate(v)) === v ? v : '';
  const calDayOf = due => { const m = /^(\d{4}-\d{2}-\d{2})(?:T([01]\d|2[0-3]):[0-5]\d)?$/.exec(String(due || '')); return m && calOkDay(m[1]) ? m[1] : ''; };  // a broken time (T99:99) is not on the calendar
  const calTime = due => { const m = /T((?:[01]\d|2[0-3]):[0-5]\d)$/.exec(String(due || '')); return m ? m[1] : ''; };
  const calNum = s => calDate(s).getDate();
  const calDayShort = s => CAL_DOW[calDow(s)] + ' ' + calNum(s) + ' ' + DUE_MONTHS[calDate(s).getMonth()];
  const calDayLong = s => CAL_DOW_LONG[calDow(s)] + ' ' + calNum(s) + ' ' + CAL_MONTHS_LONG[calDate(s).getMonth()];
  // "16 – 22 Nov", "26 Oct – 1 Nov"
  const calRange = mon => { const a = calDate(mon), b = calDate(calAdd(mon, 6)); return a.getDate() + (a.getMonth() === b.getMonth() ? '' : ' ' + DUE_MONTHS[a.getMonth()]) + ' – ' + b.getDate() + ' ' + DUE_MONTHS[b.getMonth()]; };
  // The weeks (their Mondays) that hold a day of the month of `day`.
  const calMonthWeeks = day => { const first = day.slice(0, 8) + '01', out = []; for (let m = calMonday(first); m.slice(0, 7) <= first.slice(0, 7); m = calAdd(m, 7)) out.push(m); return out; };
  // One rule for a full day everywhere: from five tickets on, three show and the rest sit behind "+N more".
  const calCut = list => list.length > 4 ? list.slice(0, 3) : list;
  const calTitle = (mode, day) => { if (mode === 'week') { const mon = calMonday(day); return calRange(mon) + ' ' + calDate(calAdd(mon, 6)).getFullYear(); } return CAL_MONTHS_LONG[calDate(day).getMonth()] + ' ' + calDate(day).getFullYear(); };
  // Previous / next: a week or a month; a month that holds today opens on today.
  function calStep(mode, day, dir, today) {
    if (mode === 'week') return calAdd(day, 7 * dir);
    const d = calDate(day.slice(0, 8) + '01'); d.setMonth(d.getMonth() + dir);
    const next = dueKey(d);
    return today && next.slice(0, 7) === today.slice(0, 7) ? today : next;
  }
  /* What the calendar shows. `items`: the tickets after the page's filters. o.now (Date), o.mode 'month'|'week',
     o.day (a day of the shown month or week, '' = today), o.statusOf(t) the status as shown. */
  function calendarPlan(items, o = {}) {
    const now = o.now || new Date(), today = dueKey(now), thisMon = calMonday(today), mode = o.mode === 'week' ? 'week' : 'month';
    const day = calOkDay(o.day) || today, statusOf = o.statusOf || (t => t.status);
    const late = t => dueLate(t.due, statusOf(t), now), done = t => statusOf(t) === 'done';
    const order = (a, b) => done(a) - done(b) || (calTime(a.due) || '99').localeCompare(calTime(b.due) || '99') ||
      String(a.key || a.id || '').localeCompare(String(b.key || b.id || ''), 'en', {numeric:true});
    const dated = arr(items).filter(t => calDayOf(t.due)), byDay = new Map();
    for (const t of dated) { const d = calDayOf(t.due); if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(t); }
    const name = mon => mon === thisMon ? 'This week' : mon === calAdd(thisMon, 7) ? 'Next week' : mon === calAdd(thisMon, -7) ? 'Last week' : calRange(mon);
    const when = mon => mon < thisMon ? 'past' : mon === thisMon ? 'now' : mon === calAdd(thisMon, 7) ? 'next' : 'later';
    const weeks = (mode === 'week' ? [calMonday(day)] : calMonthWeeks(day)).map(mon => {
      const days = Array.from({length:7}, (_, i) => calAdd(mon, i)), all = days.flatMap(d => byDay.get(d) || []);
      const nLate = all.filter(late).length, nDone = all.filter(done).length, nOpen = all.length - nLate - nDone;
      return {mon, when:when(mon), name:name(mon), range:calRange(mon),
        counts:[nLate && nLate + ' late', nOpen && nOpen + ' open', nDone && nDone + ' done'].filter(Boolean).join(', ') || 'Nothing due',
        days:days.map(d => ({day:d, today:d === today, all:(byDay.get(d) || []).length, items:(byDay.get(d) || []).filter(t => !late(t)).sort(order)}))};
    });
    const lateList = dated.filter(late).sort((a, b) => String(a.due).localeCompare(String(b.due)) || order(a, b));
    return {mode, day, today, title:calTitle(mode, day), weeks, late:lateList, noDue:arr(items).length - dated.length};
  }
  const calendar = {plan:calendarPlan, cut:calCut, step:calStep, title:calTitle, dayOf:calDayOf, time:calTime, okDay:calOkDay, monday:calMonday, add:calAdd,
    dow:calDow, num:calNum, dayShort:calDayShort, dayLong:calDayLong, range:calRange, DOW:CAL_DOW};
  // ORCH-517: a poll that held a recent revision gets only what changed (state_delta.py). Returns the new state,
  // or null when the delta does not fit the state held (the caller then fetches the whole state). Unchanged
  // tickets stay the same objects.
  function applyStateDelta(state, d) {
    if (!state || !d || d.delta !== true || !state.rev || d.base !== state.rev || !Array.isArray(d.keys)) return null;
    const next = {};
    for (const k of d.keys) next[k] = Object.prototype.hasOwnProperty.call(d.set || {}, k) ? d.set[k] : state[k];
    // ORCH-524: a top-level object (runs, settings) as only its changed entries and fields
    for (const [k, p] of Object.entries(d.patch && typeof d.patch === 'object' ? d.patch : {})) {
      const old = state[k];
      if (!d.keys.includes(k) || !old || typeof old !== 'object' || Array.isArray(old) || !p || typeof p !== 'object') return null;
      const v = {...old};
      for (const sk of arr(p.drop)) delete v[sk];
      Object.assign(v, p.set && typeof p.set === 'object' ? p.set : {});
      for (const [sk, f] of Object.entries(p.fields && typeof p.fields === 'object' ? p.fields : {})) {
        const o = v[sk];
        if (!o || typeof o !== 'object' || Array.isArray(o) || !f || typeof f !== 'object') return null;
        v[sk] = {...o, ...f};
      }
      next[k] = v;
    }
    const byId = new Map(arr(state.tickets).map(t => [t && t.id, t]));
    for (const id of arr(d.remove)) byId.delete(id);
    for (const row of arr(d.upsert)) {
      if (!row || typeof row.id !== 'string') return null;
      const old = byId.get(row.id);
      const t = old ? {...old, ...row} : {...row};
      const append = row['~append'] && typeof row['~append'] === 'object' ? row['~append'] : {};
      for (const k of Object.keys(append)) {
        if (!old || !Array.isArray(old[k])) return null;
        t[k] = [...old[k], ...arr(append[k])];
      }
      for (const k of arr(row['~drop'])) delete t[k];
      delete t['~drop']; delete t['~append'];
      byId.set(row.id, t);
    }
    const held = arr(state.tickets).map(t => t && t.id);
    let order = held.filter(id => byId.has(id));
    if (Array.isArray(d.order)) {  // ORCH-524: pieces of the held order ([start, count]) and single ids
      order = [];
      for (const part of d.order) {
        if (typeof part === 'string') { order.push(part); continue; }
        if (!Array.isArray(part) || part.length !== 2 || !Number.isInteger(part[0]) || !Number.isInteger(part[1]) || part[0] < 0 || part[1] < 1 || part[0] + part[1] > held.length) return null;
        for (let i = part[0]; i < part[0] + part[1]; i++) order.push(held[i]);
      }
    }
    if (order.length !== byId.size || order.some(id => !byId.has(id))) return null;
    next.tickets = order.map(id => byId.get(id));
    return next;
  }
  return {calendar, historyChange, applyStateDelta, waitWords, durationWords, moneyWords, spendWords, costLine, startCostWords, spendTotal, stuckWords, weekStart, inThisWeek, ticketKey, keyTag, kindWord, kindTag, helperState, helperRows, HELPER_WORDS, dueWords, quietWords, dueLate, stepsText, updatedText, resolved, agentLabel, childrenOf, creationOrder, parentOf, parentChoices, laneSorted, laneReorder, plainFileName, cleanOutcome, outcome, plainNames, scrubText, historyWho, historyView, dedupeHistory, footerState, STATUS_WORD, STATUS_ORDER, STATUS_CHOICES, MOVE_CHOICES, LANES, laneOf, laneMove, statusWord, changesAsked, columnOf, helperAlive, needsYou, needsYouCount, isNotice, isBringBack, isFactoryDraft, factoryDrafts, FACTORY_DRAFT_WORDS, uniqueNeeds, inNeeds, firstColumnWithTickets, columnChipLabel, phoneParts, cronHuman, flushPending, historyLine, winningAnswer, needAction, agentRows, serviceLinks, agentLine, startFailure, plainStartReason, plainWhy, factoryStart, factoryStartOptions, questionPreview, shownStatus, mobileOn, personName, listedName, setPersonNames, doneAt, askedAt, showsAnswerChip, treeRows, proofMark, fileProofLabel, stamp, ago, needName, needListName, needKindWord, needEnds, needState, needStopsWord, needHow, needSignIn, questionCommands, questionWords, needItems, helperStartReason, needWarnings, needTickets, needsYouFrom, countsOf, stepOf, progressOf, WONT_DO};
});
