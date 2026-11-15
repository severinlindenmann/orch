'use strict';
// Page controls use direct listeners; h() only sets attributes.
function changeUnavailable() {
  if (document.getElementById('connection')?.hidden !== false) return false;
  window.orch.toast("Can't reach orch. Your change was not sent.", 'error');
  return true;
}
function changeError(result) {
  if (result.status === 0) return "Can't reach orch. Your change was not sent.";
  const text = window.DashHelpers.scrubText(result.text);
  // the page was older than the ticket (a new round started, the work changed): nothing was approved
  return /changed while you worked|Read it again/i.test(text) ? 'This ticket changed since you opened it. Look at it again, then accept.' : text;
}
// Home rows sit under a heading that already says their status, so a row shows no status chip, and no ticket key
// (that is under the ticket's Technical details). `tail` is what a row adds instead, e.g. when it finished.
function ticketTitle(t, tail = null) {
  return h('div', {className:'row ticket-title'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, clean(t.title)), titleTag(t)), tail);
}
function parentLine(t) {
  const parent = ticketOf(t.parent || tickets().find(p => array(p.children).includes(t.id))?.id);
  return parent ? h('p', {className:'meta'}, 'Step of ', h('a', {href:href(parent.id)}, clean(parent.title))) : null;
}
const finishedAt = t => parse(t.done_at || t.completed_at || t.updated_at);

function ticketRow(t) {
  const at = finishedAt(t);
  return h('div', {className:'card-row home-ticket', 'data-key':'ticket-' + t.id}, ticketTitle(t, at ? h('span', {className:'meta'}, 'Finished ' + time(at)) : null));
}
// Answered on Home but not sent yet (the Undo window): the question is hidden and not counted.
const pendingAnswers = new Map();
let ANSWER_UNDO_MS = 5200, enterRowId = '';
// `same`: rows on other tickets asking the identical question with the same choices; one answer goes to all of them.
function needRow(row, newest, questionCount = 1, same = []) {
  const key = 'need-' + row.id;
  if (needActs(row).length) return needActionsRow(row, key);
  if (!row.ticket && array(row.answer?.options).length) return needNoticeRow(row, key);
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row);
  const options = array(row.answer?.options);
  let actions = null, other = null;
  if (!snapshot && options.length) {
    // The card leaves at once (master row-out), the badge counts down, the toast offers Undo; the answer is sent
    // when the Undo window ends. Reloading inside the window sends nothing and the question is back.
    const answer = async (option, event) => {
      if (changeUnavailable() || locks.has(key) || pendingAnswers.has(row.id)) return;
      const host = event.currentTarget.closest('[data-need-row]');
      const rows = [row, ...same], total = rows.length;
      host.querySelectorAll('button').forEach(b => { b.disabled = true; });
      host.classList.add('row-out');
      const next = typeof needsToday !== 'function' ? '' : needsToday().groups.find(g => g.row !== row && !same.includes(g.row))?.row.id;
      rows.forEach(r => pendingAnswers.set(r.id, true));
      let undone = false;
      const timer = setTimeout(async () => {
        if (undone) return;
        locks.add(key);
        let answered = 0, failed = null;
        try {
          for (const r of rows) {
            const result = await act('answer', {ticket:r.ticket, question:r.answer.question, digest:r.answer.digest, answer:option});
            if (result.ok) answered++; else failed = failed || result;
          }
          if (failed) window.orch.toast((answered ? 'Answered on ' + answered + ' of ' + total + ' tickets. ' : '') + changeError(failed), 'error');
        } finally {
          rows.forEach(r => pendingAnswers.delete(r.id));
          locks.delete(key);
          render();
        }
      }, ANSWER_UNDO_MS);
      setTimeout(() => { enterRowId = next || ''; render(); setTimeout(() => { enterRowId = ''; }, 400); }, 160);
      window.orch.toast('Answered · ' + (same.length ? total + ' tickets' : t ? clean(t.title) : 'question'), 'ok', () => {
        undone = true; clearTimeout(timer); rows.forEach(r => pendingAnswers.delete(r.id)); render();
      });
    };
    actions = h('div', {className:'answer-options'}, options.map(option => {
      const suggested = option === row.answer.recommended;
      const control = h('button', {type:'button', className:'answer-option' + (suggested ? ' suggested' : ''), 'data-key':key + '-option-' + option},
        h('span', {}, h('strong', {}, option), suggested ? h('span', {className:'badge'}, 'Suggested') : null));
      control.onclick = event => answer(option, event);
      return control;
    }));
    // a written answer goes through the full question card (checked answer, Undo)
    other = h('button', {type:'button', className:'btn ghost sm', 'data-action':'need', 'data-need':row.id, 'data-write':'own'}, 'Write your own…');
  } else if (!snapshot) {
    actions = h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id}, choice.label);
  }
  // An add-on's own row (no ticket) is named by the add-on's display name, never its id ("sync").
  const source = !t && row.source ? addonName(row.source) : '', asked = source || whoAsked(t);
  const question = needQuestion(row), when = typeof age === 'function' ? age(row.since) : '';
  return h('div', {className:'card-row home-need' + (row.id === enterRowId ? ' row-new' : ''), 'data-key':key, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null},
    h('h2', {className:'question-title'}, clean(source && String(question).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(question, 'The helper'))),
    h('p', {className:'meta question-context'}, asked + ' asked' + (when ? ' ' + when : ''),
      t ? [(clean(t.title).toLowerCase() === String(window.DashHelpers.plainWhy(question, 'The helper')).trim().toLowerCase() ? ' · ' : ' on ‘' + clean(t.title) + '’ · '), h('a', {href:href(t.id)}, 'Open ticket')] : null, typeof titleTag === 'function' && t ? titleTag(t) : null),
    actions && options.length ? h('p', {className:'meta choose-line'}, 'Needs you · Choose an answer') : null,
    same.length ? h('p', {className:'meta', 'data-key':key + '-same'}, 'Asked on ' + (same.length + 1) + ' tickets – answer once') : null,
    questionCount > 1 ? h('p', {className:'meta'}, questionCount + ' questions') : null,
    actions, other, t ? parentLine(t) : null);
}
// A row that offers choices but belongs to no ticket cannot be answered as a ticket question (the answer needs a
// ticket). It shows as a plain notice and can always be put off for the day.
function needNoticeRow(row, key) {
  const later = snapshot ? null : button('Not now', 'quiet sm', () => {
    try { localStorage.setItem(NEED_LATER, JSON.stringify({...needsLater(), [row.id]:today()})); } catch (_) { /* fine without storage */ }
    window.orch.toast('Asking again tomorrow.', 'ok'); render();
  });
  if (later) later.dataset.key = key + '-later';
  return h('div', {className:'card-row home-need need-acts need-notice', 'data-key':key, 'data-need-row':row.id},
    h('div', {className:'grow'}, h('p', {}, clean(row.text || row.title)), h('p', {className:'meta'}, typeof capitalise === 'function' ? capitalise(row.source || 'orch') : 'orch')),
    h('div', {className:'acts'}, later));
}
// Who asked: the helper working on the ticket (the product's name for it), else "Helper".
function whoAsked(t) {
  return window.DashHelpers.agentLabel ? window.DashHelpers.agentLabel(state?.settings, state?.runs?.[t?.id]?.claim) : 'Helper';
}
// The display name of an add-on from its id ("sync" -> "Sync"): its dashboard label, else the id with a capital.
function addonName(id) {
  const a = typeof addons === 'function' ? addons().find(x => x.name === id) : null;
  return typeof addonLabel === 'function' && a ? addonLabel(a) : String(id).replace(/^./, c => c.toUpperCase());
}
function needQuestion(row) { return array(ticketOf(row.ticket)?.questions).find(q => q.id === row.answer?.question)?.text || row.title || row.text; }
// An add-on row that names its own buttons (needs.schema.json `actions`, e.g. sync): each runs that add-on's verb on
// the one generic op, a signed one after the person's sign step; "Not now" waits a day, "View file" opens the file.
// The only core op a row may name is the existing, signed private.move, and only in a row of the sync add-on. Its button
// and sign step always use the core's own words below: a row's label and review are never shown for a core op.
const NEED_OPS = {'private.move':{label:'Move', title:'Move your orch files out of the team repository?',
  body:'Why: your team’s repository holds orch files that are not shared with the team, so everyone on the team sees each change. Where: they stay in this folder on this computer; the team repository no longer keeps them. Your team’s files are not touched.',
  done:'Moved your orch files.'}};
const needOp = (row, a) => row.source === 'sync' && typeof a.op === 'string' && Object.prototype.hasOwnProperty.call(NEED_OPS, a.op) ? NEED_OPS[a.op] : null;
const needLabel = a => a.core ? a.core.label : a.label;
const NEED_LATER = 'orch.needs.later';
function needsLater() {
  try { const v = JSON.parse(localStorage.getItem(NEED_LATER) || '{}'); return v && typeof v === 'object' ? v : {}; } catch (_) { return {}; }
}
const laterToday = row => { const day = needsLater()[row.id]; return !!day && day === today(); }; // only a "Not now" button sets it
// a core op: only {op, core wording}, always signed; an add-on verb, "Not now" or "View file" as the row names it
const needAct = (row, a) => {
  if (!a || typeof a !== 'object') return null;
  if ('op' in a) { const core = needOp(row, a); return core ? {op:a.op, core, sign:true} : null; }
  return typeof a.label === 'string' && (a.later || a.view || /^[a-z][a-z-]{0,20}$/.test(String(a.verb || ''))) ? a : null;
};
const needActs = row => !snapshot && /^[a-z][a-z0-9-]{1,31}$/.test(String(row.source || '')) && row.source !== 'core' ? array(row.actions).map(a => needAct(row, a)).filter(Boolean).slice(0, 4) : [];
async function needActRun(row, a) {
  const result = a.op ? await act(a.op, {}) : await act('addon.act', {addon:row.source, verb:a.verb, target:a.target});
  if (!a.sign) window.orch.toast(result.ok ? 'Done.' : changeError(result), result.ok ? 'ok' : 'error');
  return result;
}
function needActionsRow(row, key) {
  const acts = needActs(row), signed = acts.some(a => a.sign && !a.later && !a.view);
  const source = typeof addonLabel === 'function' && typeof addons === 'function' ? addonLabel(addons().find(a => a.name === row.source) || {name:capitalise(row.source)}) : capitalise(row.source);
  const controls = acts.map(a => {
    const quiet = a.later || a.view;
    const control = button(needLabel(a), quiet ? 'quiet sm' : 'outline sm', async () => {
      if (changeUnavailable() || locks.has(key)) return;
      if (a.later) {
        try { localStorage.setItem(NEED_LATER, JSON.stringify({...needsLater(), [row.id]:today()})); } catch (_) { /* fine without storage */ }
        window.orch.toast('Asking again tomorrow.', 'ok'); render(); return;
      }
      if (a.view) { if (typeof previewFile === 'function' && a.view.ticket && a.view.name) previewFile(a.view.ticket, 'artifacts', a.view.name); return; }
      if (a.core) { signStep({title:a.core.title, body:a.core.body, done:a.core.done, run:() => needActRun(row, a)}); return; }
      // the sign step shows the add-on's review of exactly what it will sign (signedAct), not the row's text
      if (a.sign) { signedAct({addon:row.source, verb:a.verb, target:a.target}, String(a.review?.done || '').slice(0, 120)); return; }
      locks.add(key);
      try { await needActRun(row, a); } finally { locks.delete(key); render(); }
    });
    control.dataset.key = key + '-act-' + needLabel(a);
    return control;
  });
  return h('div', {className:'card-row home-need need-acts', 'data-key':key, 'data-need-row':row.id},
    h('div', {className:'grow'}, h('p', {}, clean(row.text)), h('p', {className:'meta'}, source)),
    h('div', {className:'acts'}, signed ? h('span', {className:'sig', 'data-key':key + '-sig'}, iconEl('shield'), 'Needs your signature') : null, controls));
}
function startFailedRow(t, sf) {
  return h('div', {className:'card-row home-need', 'data-key':'start-failed-' + t.id}, ticketTitle(t),
    h('p', {}, clean(sf.text)),
    snapshot ? null : h('div', {className:'row'}, button('Retry', 'outline sm', async () => {
      if (changeUnavailable()) return;
      const result = await act('run.start', {ticket:t.id});
      window.orch.toast(result.ok ? 'Starting again' : changeError(result), result.ok ? 'ok' : 'error');
    })), parentLine(t));
}
// Working now: title and the task being done, nothing else (the ticket page shows the steps).
function workingRow(t) {
  const tasks = array(t.checklist), claim = state.runs?.[t.id]?.claim, task = tasks.find(task => !window.DashHelpers.resolved(task));
  const who = window.DashHelpers.agentLabel ? window.DashHelpers.agentLabel(state.settings, claim) : capitalise(name(claim?.label || claim?.agent || t.owner));
  return h('a', {className:'card-row working-row', href:href(t.id), 'data-key':'ticket-' + t.id},
    h('span', {className:'avatar', 'aria-hidden':'true'}, String(who || 'H').slice(0, 1).toUpperCase()),
    h('span', {className:'grow'}, h('strong', {}, clean(t.title)), task ? h('span', {className:'meta'}, clean(task.text || task.title)) : null));
}
// Results with the same name are one row ("9 versions"): the row opens the newest; "Mark older as done" closes the rest
// (each move shows its Undo). Signing off a single result happens in the result view, not here.
const resultWhen = t => Date.parse(t.updated_at || t.created_at) || 0;
function resultGroups(review) {
  const groups = new Map();
  for (const t of review.slice().sort((a, b) => resultWhen(a) - resultWhen(b))) {
    const key = clean(t.title).toLowerCase() || 'id:' + t.id; // untitled results never stack
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  // newest first, by each group's newest member
  return [...groups.values()].sort((a, b) => resultWhen(b[b.length - 1]) - resultWhen(a[a.length - 1]));
}
// One row of the "Needs you" list: the title, one line saying where it comes from, and ONE button.
function listRow(key, title, meta, action, attrs = {}) {
  return h('div', {className:'card-row', 'data-key':key, ...attrs}, h('div', {className:'grow'}, h('h3', {}, title), meta ? h('p', {className:'meta'}, meta) : null), action);
}
// A long add-on question (a whole proposal) shows as its first sentence; the full text is in the question card.
function shortQuestion(text) {
  const first = String(text || '').split(/(?<=[?.])\s/)[0].trim();
  return first.length > 110 ? first.slice(0, 107) + '…' : first;
}
// A further question, startable failure or add-on row: the same one button the full card would open.
function needListRow(row, count, same) {
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row), key = 'need-' + row.id;
  const source = !t && row.source ? addonName(row.source) : '', when = typeof age === 'function' ? age(row.since) : '';
  const meta = [t ? clean(t.title) : source, count > 1 ? count + ' questions' : '', same.length ? 'Asked on ' + (same.length + 1) + ' tickets' : '', when].filter(Boolean).join(' · ');
  const action = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id, 'data-key':key + '-answer'}, choice.label);
  const question = shortQuestion(needQuestion(row)), title = source && String(question).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(question, 'The helper');
  return listRow(key, clean(title), meta, action, {'data-need-row':row.id});
}
// A result to check: same-name results are one row ("3 versions"); the row opens the newest.
function resultRow(group) {
  const t = group[group.length - 1];
  return listRow('check-' + t.id, 'Check the result', clean(t.title) + (group.length > 1 ? ' · ' + group.length + ' versions' : ''),
    h('a', {className:'btn outline sm', href:href(t.id), 'data-key':'result-' + t.id}, 'Check result'));
}
// Changes a helper made in its own copy, waiting to be added to the person's files (the signed copies.approve path).
function changeRow(t) {
  let action = h('a', {className:'btn outline sm', href:href(t.id)}, 'See what changed');
  if (!snapshot && t.bring_back?.tip && typeof ticketBringBackDialog === 'function') {
    action = h('button', {type:'button', className:'btn outline sm', 'data-key':'add-files-' + t.id}, 'Apply changes');
    action.onclick = () => ticketBringBackDialog(t);
  }
  return listRow('change-' + t.id, 'Apply the changes?', clean(t.title), action);
}
function attentionCard(key, badge, cls, body, meta = '', action = null) {
  return h('section', {className:'card home-card', 'data-key':key, id:key}, h('header', {className:'card-h'}, h('span', {className:'badge ' + cls}, badge), h('span', {className:'grow'}), meta ? h('span', {className:'meta'}, meta) : null, action), body);
}
// "Review all": the cards of the Review page (state.review) in one go. The number is the same set of questions and
// results Home already counts, so it is never added to Home's own total.
function reviewAllButton() {
  const n = typeof reviewCount === 'function' ? reviewCount() : 0;
  return n && !snapshot ? h('a', {className:'btn primary sm', href:'#review', 'data-key':'review-all'}, 'Review all', h('span', {className:'count'}, String(n))) : null;
}
function attentionSummary(groups, failed, results, changes) {
  const questionsAsked = groups.filter(g => g.row.answer?.question).length, other = groups.length - questionsAsked + failed.length;
  const part = (n, one, many) => n ? n + ' ' + (n === 1 ? one : many) : null;
  return [part(questionsAsked, 'question', 'questions'), part(other, 'thing to look at', 'things to look at'),
    part(results, 'result to check', 'results to check'), part(changes, 'change to add', 'changes to add')].filter(Boolean).join(' · ');
}
function homeSection(key, title, body, count = '', more = null) {
  return h('section', {className:'home-section', 'data-key':key, id:key === 'needs-you' ? key : null},
    h('div', {className:'row between home-section-head'}, h('h2', {}, title, count ? [' ', h('span', {className:'meta'}, String(count))] : null), more), h('div', {className:'card'}, body));
}
// One group per ticket; a single question asked the same way (same words, same choices) on several tickets is one group.
function homeNeeds(rows) {
  const groups = new Map(), out = [], byQuestion = new Map();
  for (const row of rows) {
    const key = row.ticket || row.id;
    if (!groups.has(key)) groups.set(key, {row, count:0, same:[]});
    groups.get(key).count++;
  }
  for (const g of groups.values()) {
    const options = array(g.row.answer?.options);
    const sig = g.count === 1 && g.row.ticket && options.length && !needActs(g.row).length ? clean(needQuestion(g.row)).toLowerCase() + '\n' + options.join('\n') : null;
    const first = sig && byQuestion.get(sig);
    if (first) { first.same.push(g.row); continue; }
    if (sig) byQuestion.set(sig, g);
    out.push(g);
  }
  return out;
}
let notesOpen = false;
// The notes that need no answer ("11 sync notes, nothing to do") are one quiet line; Show lists them.
function notesLine(notices) {
  const sources = [...new Set(notices.map(n => addonName(n.source || 'orch').toLowerCase()))];
  const label = notices.length + ' ' + (sources.length === 1 ? sources[0] + ' ' : '') + (notices.length === 1 ? 'note' : 'notes') + ', nothing to do';
  return h('div', {className:'card-row', 'data-key':'needs-notes'}, h('span', {className:'meta'}, label),
    button(notesOpen ? 'Hide' : 'Show', 'ghost xs', () => { notesOpen = !notesOpen; render(); }));
}
// What needs the person today (Home, the Home badge and the Menu count all use this): the parts of the Home subtitle, summed.
function needsToday() {
  const live = needsList().filter(r => !laterToday(r) && !pendingAnswers.has(r.id));
  const notices = live.filter(window.DashHelpers.isNotice);
  const needs = live.filter(r => !window.DashHelpers.isNotice(r) && !window.DashHelpers.isBringBack(r));
  const failed = tickets().map(t => [t, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings)]).filter(([t, sf]) => sf && !needs.some(n => n.ticket === t.id));
  const groups = homeNeeds(needs), all = tickets();
  const review = all.filter(t => t.status === 'review' && !needs.some(n => n.ticket === t.id));
  const changes = all.filter(t => t.bring_back?.state === 'waiting');
  const asked = groups.length + failed.length;
  return {needs, notices, failed, groups, review, changes, asked, count:window.DashHelpers.needsYouCount(groups.map(g => g.row), failed, review, changes)};
}
// The one needs-you number: sidebar badge, Menu, Home and Tickets headers all read it.
function needsYouTotal() { return state ? needsToday().count : 0; }
// Services that should run but do not (one that is off on purpose, like Sync before it is turned on, is not one).
function stoppedServices() { return array(state.services).filter(s => s.running === false && !s.idle); }
function backgroundBanner() {
  const names = stoppedServices().map(s => { const a = addons().find(x => x.name === s.addon); const n = a?.dashboard?.label || s.addon; return n.charAt(0).toUpperCase() + n.slice(1); });
  if (!names.length) return null;
  const list = names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names.at(-1) : names[0];
  return h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, list + (names.length > 1 ? ' are' : ' is') + ' not running. Press Start so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start'));
}
// "What changed": what the helper wrote when work finished (the outcome, else the completion note), newest first.
function doneAt(t) {
  if (typeof t.done_at === 'string' && t.done_at) return t.done_at;
  return (typeof ticketDoneEvent === 'function' ? ticketDoneEvent(t)?.at : '') || t.updated_at || t.created_at || '';
}
function changedWords(t) {
  const o = typeof outcomeOf === 'function' ? outcomeOf(t) : {}, first = String(o.changed || o.why || '').split('\n')[0].trim();
  if (first) return {head:first.length > 110 ? first.slice(0, 107) + '…' : first, detail:o.changed ? o.why || '' : ''};
  const n = typeof completionNotes === 'function' ? completionNotes(t)[0] : null;
  return n ? {head:n.head, detail:n.body} : null;
}
function changedList(items, limit = 5) {
  return items.filter(t => t.status === 'done').map(t => ({t, words:changedWords(t)})).filter(x => x.words)
    .sort((a, b) => (Date.parse(doneAt(b.t)) || 0) - (Date.parse(doneAt(a.t)) || 0)).slice(0, limit);
}
function whatChangedCard(list) {
  if (!list.length) return null;
  return h('section', {className:'card home-card what-changed', 'data-key':'what-changed'},
    h('div', {className:'card-h row between'}, h('h2', {}, 'What changed'), h('a', {className:'btn ghost sm', href:'#tickets?view=done-week'}, 'Done tickets →')),
    list.map(({t, words}) => h('a', {className:'home-note', href:href(t.id), 'data-key':'changed-' + t.id},
      h('div', {className:'grow'}, h('strong', {}, clean(t.title)), h('p', {className:'muted preserve-lines'}, clean(words.head) + (words.detail ? ' ' + clean(words.detail) : ''))),
      h('span', {className:'meta'}, [typeof ticketDoneEvent === 'function' && typeof ticketActor === 'function' ? ticketActor(ticketDoneEvent(t)?.by) : '', time(doneAt(t))].filter(Boolean).join(' · ')))));
}
// The day the last finished ticket was closed, for the empty "Finished" card ("Last: “…”, Fri.").
function lastFinished(all) {
  const t = all.filter(x => x.status === 'done' && finishedAt(x)).sort((a, b) => finishedAt(b) - finishedAt(a))[0];
  return t ? 'Last: “' + clean(t.title) + '”, ' + finishedAt(t).toLocaleDateString('en-GB', {weekday:'short'}) + '.' : '';
}
// Home: what needs the person first, as ONE list: the oldest question with its answers, then one row per further
// question, result to check and change to add (one button each); the notes that need no answer are one quiet line.
function home() {
  const {needs, notices, failed, groups:groupedNeeds, review, changes, count:needCount} = needsToday(), all = tickets();
  const working = sorted(all.filter(t => shown(t).status === 'active' && !needs.some(n => n.ticket === t.id)));
  const results = resultGroups(review);
  const finished = all.filter(t => t.status === 'done' && finishedAt(t)?.toDateString() === now().toDateString());
  const newest = needs.slice().sort((a,b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const banner = backgroundBanner(), changedCard = whatChangedCard(changedList(all));
  const title = needCount ? needCount + (needCount === 1 ? ' thing needs you' : ' things need you') : 'Nothing needs you';
  const today = now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}), summary = attentionSummary(groupedNeeds, failed, review.length, changes.length);
  const head = heading(title, summary ? today + ' · ' + summary : today, {
    actions:h('a', {className:'btn ghost sm', href:'#tickets', 'data-key':'all-tickets'}, 'All ' + all.length + (all.length === 1 ? ' ticket →' : ' tickets →'))});
  const notes = notices.length ? [notesLine(notices), ...(notesOpen ? notices.map(row => needRow(row, newest)) : [])] : [];
  if (!needCount && !working.length) {
    return fragment(head, banner, h('section', {className:'empty-workspace', 'data-key':'empty'}, h('h2', {}, 'All clear'),
      h('p', {}, 'Questions and results to check will appear here.'), typeof newButton === 'function' ? newButton() : null),
      notes.length ? h('section', {className:'card home-card', 'data-key':'needs-notes-card'}, notes) : null,
      card('finished-today', 'Finished', '', finished.length ? finished.map(ticketRow) : emptyRow(lastFinished(all) ? 'Nothing finished today. ' + lastFinished(all) : 'Nothing finished yet.')), changedCard);
  }
  const first = groupedNeeds.slice().sort((a, b) => (Date.parse(a.row.since) || Infinity) - (Date.parse(b.row.since) || Infinity))
    .find(g => g.row.answer?.question && array(g.row.answer.options).length && !needActs(g.row).length);
  const further = groupedNeeds.filter(g => g !== first).map(({row, count, same}) => needActs(row).length || (!row.ticket && array(row.answer?.options).length) ? needRow(row, newest, count, same) : needListRow(row, count, same));
  const list = [first ? needRow(first.row, newest, first.count, first.same) : null, ...further, ...failed.map(([t, sf]) => startFailedRow(t, sf)),
    ...results.map(resultRow), ...changes.map(changeRow), ...notes];
  const finishedBody = finished.length ? finished.map(ticketRow) : emptyRow(lastFinished(all) ? 'Nothing finished today. ' + lastFinished(all) : 'Nothing finished yet.');
  return fragment(head, banner,
    h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
      needCount ? attentionCard('needs-you', 'Needs you · ' + needCount, 'needs', list, first ? whoAsked(ticketOf(first.row.ticket)) : '', reviewAllButton()) : null),
    h('aside', {className:'stack', 'data-key':'right'},
      working.length ? card('working-now', 'Working now', String(working.length), working.slice(0, 5).map(workingRow)) : null,
      card('finished-today', 'Finished', '', finishedBody))),
    changedCard);
}
function connectionNotice(connectionEl, hadState) {
  connectionEl.replaceChildren(h('div', {className:'grow'}, h('h3', {}, "Can’t reach the workspace"),
    h('p', {}, hadState ? 'Showing the last saved view. Changes are unavailable until you reconnect.' : 'Reconnect to load your workspace. Your data has not been changed.')),
    button('Try again', 'outline sm', () => refresh()));
  connectionEl.hidden = false;
}
// Chat (former General) lives in pages/chat.js.
