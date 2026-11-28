'use strict';
// Page controls use direct listeners; h() only sets attributes.
function changeUnavailable() {
  const banner = document.getElementById('connection');
  if (banner?.hidden !== false || banner.dataset?.kind === 'slow') return false;  // a slow answer is no failure: changes go on
  window.orch.toast(banner.dataset?.kind === 'error' ? 'orch had a problem. Your change was not sent; try again in a moment.' : "Can't reach orch. Your change was not sent; try again in a moment.", 'error');
  return true;
}
function changeError(result) {
  if (result.status === 0) return "Can't reach orch. Your change was not sent; try again in a moment.";
  const text = window.DashHelpers.scrubText(result.text);
  // the page was older than the ticket (a new round started, the work changed): nothing was approved
  if (/changed while you worked|Read it again/i.test(text)) return 'This ticket changed since you opened it. Look at it again, then accept.';
  // an answer to a question that is settled or changed meanwhile (ORCH-1047): plain words, no question id
  if (/^q[0-9]+ is already answered/.test(text)) return 'This question was already answered.';
  if (/^q[0-9]+ changed after it was shown/.test(text)) return 'This question changed since you saw it. Look at it again, then answer.';
  return text;
}
const finishedAt = t => parse(window.DashHelpers.doneAt(t));

// What a finished row says under its title (ORCH-1849): the outcome or completion note the helper or a person wrote,
// one short line. With none written it says the ticket's summary (the ticket page's "In short"), else names the
// result file of a finished task (ORCH-2297: the two pages said different things); "No result written yet" only when
// the ticket has none of them, never a made-up line.
const FINISHED_CHARS = 110;
function finishedSaid(t) {
  const words = changedWords(t), said = words ? plainChanged(changedText(words), FINISHED_CHARS) : '';
  if (said) return said;
  const short = plainChanged(clean(t.summary || ''), FINISHED_CHARS);
  if (short) return short;
  const files = [...new Set(array(t.checklist).filter(c => c.done && !c.wont_do).flatMap(c => array(c.evidence))
    .filter(ev => (ev.type || ev.kind) === 'file').map(ev => clean(ev.title || String(ev.ref || '').split(/[\\/]/).pop())).filter(Boolean))];
  return files.length ? 'Result: ' + files[0] + (files.length > 1 ? ' and ' + (files.length - 1) + ' more' : '') : '';
}
// A row of the quiet list at the foot of Home (O-01 D): something to know that is neither blocked work nor a card of
// the Review page: an add-on's own row with its buttons, a notice, a wait that is late.
function noteRow(row) {
  const key = 'need-' + row.id;
  if (needActs(row).length) return needActionsRow(row, key);
  if (!row.ticket && array(row.answer?.options).length) return needNoticeRow(row, key);
  const t = ticketOf(row.ticket), source = !t && row.source ? addonName(row.source) : '', when = typeof age === 'function' ? age(row.since) : '';
  const meta = [t ? [window.DashHelpers.ticketKey(t), clean(t.title)].filter(Boolean).join(' ') : source, when].filter(Boolean).join(' · ');
  const said = shortQuestion(needQuestion(row)), title = source && String(said).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(said, 'The helper');
  return listRow(key, clean(title), meta, t ? h('a', {className:'btn outline sm', href:href(t.id), 'data-key':key + '-open'}, 'Open') : null, {'data-need-row':row.id});
}
// The Factory page's address of an order's draft or proposal (the Review card links there); the ticket without that page.
function factoryOrderHref(id, part) {
  const page = typeof addons === 'function' && addons().some(a => a.name === 'factory' && a.page);
  return page && /^t_[a-z0-9]{6,16}$/.test(id) ? '#addon/factory/#/order/' + id + '/' + part : href(id);
}
const isFactoryDraftRow = row => !!window.DashHelpers.isFactoryDraft?.(row);
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
// The display name of an add-on from its id ("sync" -> "Sync"): its dashboard label, else the id with a capital.
function addonName(id) {
  const a = typeof addons === 'function' ? addons().find(x => x.name === id) : null;
  return typeof addonLabel === 'function' && a ? addonLabel(a) : String(id).replace(/^./, c => c.toUpperCase());
}
// A command the helper wrote in backticks in its question ("Sign in again with `az login`") shows with a Copy button (ORCH-218).
function questionCommandRows(text, key) {
  if (!window.UI?.commandCopy || !window.DashHelpers.questionCommands) return null;
  return window.DashHelpers.questionCommands(text).map((c, i) => window.UI.commandCopy(c, {dataKey:key + '-cmd-' + i}));
}
function needQuestionOf(row) { return array(ticketOf(row.ticket)?.questions).find(q => q.id === row.answer?.question); }
function needQuestion(row) { return needQuestionOf(row)?.text || row.title || row.text; }
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
    h('div', {className:'acts'}, signed ? h('span', {className:'sig', 'data-key':key + '-sig'}, iconEl('shield'), 'Needs your OK') : null, controls));
}
// O-01 D (owner, 28 Nov): Home answers one question first: is anything broken or blocked? "Blocked now" lists only what
// stops work, each as one line with one action: a sign-in or tool that stopped, a helper that could not start, a
// merge that waits, a helper that waits for an OK on its screen or keeps failing, an idle helper, a service work
// depends on. Questions and results are never rows here: they are one line that opens Review.
function blockedRow(key, kind, what, why, action, attrs = {}) {
  // data-counts: how much of THE number (the Review badge) the row carries; the browser check adds them up (ORCH-476)
  return h('div', {className:'card-row home-need need-acts', 'data-key':key, 'data-blocked':kind, 'data-counts':'0', ...attrs},
    h('div', {className:'grow'}, h('p', {}, what), why ? h('p', {className:'meta'}, why) : null),
    action ? h('div', {className:'acts'}, action) : null);
}
const ticketLink = t => h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title));
// Work that stopped short (core rows): a pull request left open after its checks passed (Merge), a helper idle at its
// prompt (Remind), a helper waiting on the person's OK on its screen or a step whose checks keep failing (Open: the
// answer is on the ticket). A ticket the Reviewer was not sure about is a card of the Review page, not a row here.
const STUCK_ROWS = ['helper:permission', 'helper:failing', 'reviewer:unsure'];
const HELPER_ROWS = ['helper:unmerged', 'helper:idle', ...STUCK_ROWS];
const isHelperRow = row => !!row && row.source === 'core' && HELPER_ROWS.includes(row.kind) && !!row.ticket;
const isStuckRow = row => isHelperRow(row) && STUCK_ROWS.includes(row.kind);
// The words sent to the helper are fixed here; the Review page's stuck card sends the same ones.
const MERGE_ASK = 'The pull request of this ticket passed its checks but is still open. If the ticket or the workspace rules say to merge it, merge it now and record it on the ticket; if not, say on the ticket why it stays open.';
const NUDGE = 'You have been idle for a while with open tasks on this ticket. Carry on with the next open task, or ask if something blocks you.';
async function nudgeHelper(tid, text) {
  const sent = await act('run.send', {ticket:tid, text});
  if (!sent.ok) return sent;
  return state.runs?.[tid]?.running === true ? sent : act('run.start', {ticket:tid});
}
async function restartFresh(tid) {
  if (state.runs?.[tid]?.running === true) {
    const stopped = await act('run.stop', {ticket:tid});
    if (!stopped.ok) return stopped;
  }
  return act('run.start', {ticket:tid, fresh:true});
}
function stoppedRow(row) {
  const key = 'need-' + row.id, t = ticketOf(row.ticket), pull = row.pull || {};
  const click = (label, done, run) => {
    const control = button(label, 'outline sm', async () => {
      if (changeUnavailable() || locks.has(key)) return;
      locks.add(key);
      try {
        const result = await run();
        window.orch.toast(result.ok ? done : changeError(result), result.ok ? 'ok' : 'error');
      } finally { locks.delete(key); render(); }
    });
    control.dataset.key = key + '-act-' + label;
    return control;
  };
  const action = row.kind === 'helper:unmerged' ? (snapshot ? null : click('Merge', 'Merged', () => act('pull.merge', {ticket:row.ticket, url:pull.url, head:pull.head})))
    : row.kind === 'helper:idle' ? (snapshot ? null : click('Remind', 'Message sent', () => nudgeHelper(row.ticket, NUDGE)))
    : t ? h('a', {className:'btn outline sm', href:href(t.id), 'data-key':key + '-open'}, 'Open') : null;
  const link = row.kind === 'helper:unmerged' && /^https:\/\/github\.com\//.test(String(pull.url || '')) ? h('a', {href:pull.url, target:'_blank', rel:'noopener noreferrer'}, 'Pull request') : null;
  return blockedRow(key, 'stopped', clean(row.text), [t ? ticketLink(t) : clean(row.title), link ? [' · ', link] : null], action,
    {'data-need-row':row.id, 'data-stopped':row.kind, 'data-counts':'1'});
}
function startFailedRow(t, sf) {
  const key = 'start-failed-' + t.id;
  const again = snapshot ? null : startHost(t, key + '-retry', {label:'Try again', continueLabel:'Try again'}) || button('Try again', 'outline sm', async () => {
    if (changeUnavailable()) return;
    const result = await act('run.start', {ticket:t.id});
    window.orch.toast(result.ok ? 'Starting again' : changeError(result), result.ok ? 'ok' : 'error');
  });
  return blockedRow(key, 'start', clean(sf.text), ticketLink(t), again, {'data-counts':'1'});
}
// Helpers (ORCH-61, owner pick A on ORCH-64): one row per running helper with ORCH-n, step, minutes and the core's
// state word (Working, Needs you, Waiting, Idle, Stuck); Remind on an idle or stuck row. The same kit widget
// (UI.helperList) draws the live list of the other add-on page.
// CX-01 (28 Nov: "1 helper working" above a Stuck row with Stop for work that was finished): a row on a finished
// ticket is read once (DashHelpers.helperShown): nothing running is "Finished" with Open ticket, a process that still
// runs says so and keeps Stop, and a run orch cannot read says that. The number beside it counts the same rows.
function helpersCard(rows) {
  const key = 'helpers';
  const action = (r, label, run, done) => ({label, key:key + '-' + r.ticket.id + '-' + label.toLowerCase().replace(/\s+/g, '-'), run:async () => {
    const lock = key + '-' + r.ticket.id;
    if (changeUnavailable() || locks.has(lock)) return;
    locks.add(lock);
    try {
      const result = await run();
      window.orch.toast(result.ok ? done : changeError(result), result.ok ? 'ok' : 'error');
    } finally { locks.delete(lock); render(); }
  }});
  const acts = {
    stop:r => action(r, 'Stop', () => act('run.stop', {ticket:r.ticket.id}), 'Helper stopped'),
    remind:r => action(r, 'Remind', () => nudgeHelper(r.ticket.id, NUDGE), 'Message sent'),
    open:r => ({label:'Open ticket', key:key + '-' + r.ticket.id + '-open', run:() => { location.hash = href(r.ticket.id); }}),
  };
  return window.UI.helperList(rows.map(r => {
    const shown = window.DashHelpers.helperShown(r);
    return {key:typeof r.ticket.key === 'string' ? r.ticket.key : '', title:clean(r.ticket.title), href:href(r.ticket.id),
      state:shown.state, word:shown.word, meta:shown.meta != null ? shown.meta : window.UI.helperMeta(r), dataKey:key + '-' + r.ticket.id,
      // Open ticket is a plain way to the ticket: it shows in a read-only copy too
      actions:!shown.act || (snapshot && shown.act !== 'open') ? [] : [acts[shown.act](r)]};
  }), {dataKey:'helpers'});
}
// ORCH-2140: the ids of the open tickets that wait for nobody are the core's (orch counts), so Home and `orch counts`
// say the same. O-01 D: the numbers are one quiet row under the Review line, never tiles.
function openLists(all, waits) {
  const c = state.counts || {};
  if (Array.isArray(c.in_progress) && Array.isArray(c.not_started)) {
    const pick = ids => ids.map(ticketOf).filter(Boolean);
    return {inProgress:pick(c.in_progress), notStarted:pick(c.not_started)};
  }
  // a snapshot without the core's count: the same rule from the tickets themselves
  const open = all.filter(t => ['open', 'ready', 'active', 'waiting', 'blocked'].includes(shown(t).status) && !waits.has(t.id));
  const begun = t => !['open', 'ready'].includes(shown(t).status) || array(t.checklist).some(x => window.DashHelpers.resolved(x));
  return {inProgress:open.filter(begun), notStarted:open.filter(t => !begun(t))};
}
function homeNumbers(inProgress, notStarted, finishedToday, working) {
  const part = (key, n, words, to) => h(to ? 'a' : 'span', {className:'home-number', 'data-key':'tile-' + key, ...(to ? {href:to} : {})}, h('strong', {}, String(n)), ' ' + words);
  return h('div', {className:'row home-numbers', 'data-key':'tiles'},
    part('in-progress', inProgress, 'in progress', '#tickets'),
    part('helpers', working, working === 1 ? 'helper working' : 'helpers working'),
    part('not-started', notStarted, 'not started', '#tickets'),
    part('finished-today', finishedToday, 'finished today', '#tickets?view=done-today'));
}
// O-01 D: what waits in Review is one line with the way there. The parts are the ones the Review badge counts.
function reviewLine(n, questions, results, filled) {
  if (!n) return h('section', {className:'card home-card', 'data-key':'review-line', 'data-counts':'0'}, h('div', {className:'card-row muted'}, 'Nothing waits in Review.'));
  const part = (k, one, many) => k > 0 ? k + ' ' + (k === 1 ? one : many) : '', more = n - questions - results;
  const parts = more < 0 || more === n ? [n + (n === 1 ? ' thing' : ' things')] : [part(questions, 'question', 'questions'), part(results, 'result', 'results'), more ? more + ' more' : ''].filter(Boolean);
  const words = (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts.at(-1) : parts[0]) + (n === 1 ? ' waits' : ' wait') + ' in Review';
  return h('section', {className:'card home-card', 'data-key':'review-line', 'data-counts':String(n)},
    h('div', {className:'card-row'}, h('span', {className:'grow'}, h('strong', {}, words)),
      h('a', {className:'btn ' + (filled ? 'primary' : 'outline') + ' sm', href:'#review', 'data-key':'review-all'}, 'Open Review')));
}
// One row of a quiet list: the title, one line saying where it comes from, and ONE button.
function listRow(key, title, meta, action, attrs = {}) {
  return h('div', {className:'card-row', 'data-key':key, ...attrs}, h('div', {className:'grow'}, h('h3', {}, title), meta ? h('p', {className:'meta'}, meta) : null), action);
}
// A long add-on question (a whole proposal) shows as its first sentence; the full text is in the question card.
function shortQuestion(text) {
  const first = String(text || '').split(/(?<=[?.])\s/)[0].trim();
  return first.length > 110 ? first.slice(0, 107) + '…' : first;
}
// Changes a helper made in its own copy, waiting to be added to the person's files (the signed copies.approve path).
function changeRow(t) {
  let action = h('a', {className:'btn outline sm', href:href(t.id)}, 'See what changed');
  if (!snapshot && t.bring_back?.tip && typeof ticketBringBackDialog === 'function') {
    action = h('button', {type:'button', className:'btn outline sm', 'data-key':'add-files-' + t.id}, 'Apply changes');
    action.onclick = () => ticketBringBackDialog(t);
  }
  return listRow('change-' + t.id, [window.DashHelpers.keyTag(t, h), clean(t.title)], t.bring_back?.empty ? 'No changes to apply' : 'Apply the changes?', action);
}
// One group per ticket; a single question asked the same way (same words, same choices) on several tickets is one group.
function homeNeeds(rows) {
  const groups = new Map(), out = [], byQuestion = new Map();
  for (const row of rows) {
    const key = isHelperRow(row) ? row.id : isFactoryDraftRow(row) ? 'draft:' + row.ticket : row.ticket || row.id;  // work that stopped never hides behind a question of its ticket
    if (!groups.has(key)) groups.set(key, {row, count:0, same:[], asked:0});
    const g = groups.get(key);
    if (g.row !== row && !g.row.answer?.question && row.answer?.question && !isHelperRow(g.row)) g.row = row;  // a question leads its ticket's row
    g.count++;
    if (row.ticket && row.answer?.question) g.asked++; else if (isFactoryDraftRow(row)) g.asked = 1;  // a ready Factory draft is one of THE number
  }
  for (const g of groups.values()) {
    const options = array(g.row.answer?.options);
    const sig = g.count === 1 && g.row.ticket && options.length && !needActs(g.row).length ? clean(needQuestion(g.row)).toLowerCase() + '\n' + options.join('\n') : null;
    const first = sig && byQuestion.get(sig);
    if (first) { first.same.push(g.row); first.asked += g.asked; continue; }
    if (sig) byQuestion.set(sig, g);
    out.push(g);
  }
  return out;
}
// ORCH-1741: results whose pull request waits in the merge queue need nobody: one quiet line, no card, not counted.
// They come back as a result to check if the queue gives up on the pull request.
function queueLine(queued) {
  const n = array(queued).length;
  return n ? h('div', {className:'card-row', 'data-key':'needs-queue'}, h('span', {className:'meta'}, n + ' in the merge queue, nothing to do')) : null;
}
let notesOpen = false;
// The notes that need no answer ("11 sync notes, nothing to do") are one quiet line; Show lists them.
function notesLine(notices) {
  const sources = [...new Set(notices.map(n => addonName(n.source || 'orch').toLowerCase()))];
  const label = notices.length + ' ' + (sources.length === 1 ? sources[0] + ' ' : '') + (notices.length === 1 ? 'note' : 'notes') + ', nothing to do';
  return h('div', {className:'card-row', 'data-key':'needs-notes'}, h('span', {className:'meta'}, label),
    button(notesOpen ? 'Hide' : 'Show', 'ghost xs', () => { notesOpen = !notesOpen; render(); }));
}
// ORCH-2431: what is parked (state.parked, the core's list): one quiet line; Show lists each with its reason and Bring back.
let parkedOpen = false;
function parkedList() { return array(state?.parked).filter(r => r && ticketOf(r.ticket)); }
function parkedIds() { return new Set(array(state?.parked).map(r => r && r.ticket)); }
// a parked ticket gives no row on Home (the core leaves it out of needs and the number; this covers Home's own rows)
function isParked(t, ids = parkedIds()) { return !!t && (t.status === 'open' || ids.has(t.id)); }
function parkedLine(list) {
  const label = list.length + ' parked, ' + (list.length === 1 ? 'it asks' : 'they ask') + ' nothing until ' + (list.length === 1 ? 'it comes' : 'they come') + ' back';
  return h('div', {className:'card-row', 'data-key':'needs-parked'}, h('span', {className:'meta'}, label),
    button(parkedOpen ? 'Hide' : 'Show', 'ghost xs', () => { parkedOpen = !parkedOpen; render(); }));
}
function parkedRow(r) {
  const t = ticketOf(r.ticket), n = Number(r.questions) || 0;
  const meta = [clean(r.reason), n ? n + (n === 1 ? ' question' : ' questions') + ' kept' : ''].filter(Boolean).join(' · ');
  const back = snapshot || typeof bringBack !== 'function' ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':'parked-back-' + t.id}, 'Bring back');
  if (back) back.onclick = () => bringBack(ticketOf(r.ticket));
  return listRow('parked-' + t.id, [window.DashHelpers.keyTag(t, h), h('a', {href:href(t.id)}, clean(t.title))], meta, back, {'data-counts':'0'});
}
// What needs the person today (Home, the Home badge and the Menu count all use this): the parts of the Home subtitle, summed.
function needsToday() {
  const hidden = needsList().filter(laterToday);
  const live = needsList().filter(r => !laterToday(r));
  const notices = live.filter(window.DashHelpers.isNotice);
  const needs = live.filter(r => !window.DashHelpers.isNotice(r) && !window.DashHelpers.isBringBack(r));
  const failed = tickets().map(t => [t, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings)]).filter(([t, sf]) => sf && !needs.some(n => n.ticket === t.id));
  const groups = homeNeeds(needs), all = tickets();
  // ORCH-1741: with the core's count, only the tickets whose Check card shows are results to check: one the merge queue
  // holds waits on nobody (one line, queueLine), one with another card (a question, a pull request to merge) is that card
  const checks = Array.isArray(state.counts?.needs_you?.items) ? new Set(state.counts.needs_you.items.filter(i => i && !i.question && !i.stopped && !i.start).map(i => i.ticket)) : null;
  const review = all.filter(t => t.status === 'review' && (!checks || checks.has(t.id)));  // each result to check is one row and one count, like the Review page cards
  const queued = array(state.counts?.needs_you?.queue);
  const resting = parkedIds();
  const changes = all.filter(t => t.bring_back?.state === 'waiting' && !isParked(t, resting));
  const asked = groups.length + failed.length, results = review;
  const drafts = groups.filter(g => isFactoryDraftRow(g.row)).length;  // a ready Factory draft waits like a question (ORCH-479)
  // what helpers need: a login that runs out soon is a row of Home's list; the stopped ones are the banner
  const logins = loginWarnings();
  // Work that stopped (stuck tickets, a pull request left open, an idle helper) is part of THE number, so Home, the
  // top bar, Menu, the live bar and the wall say the same (ORCH-705). A ticket the Reviewer was not sure about is that
  // row, not also a result to check.
  // One order is one item: a ticket whose ready Factory draft is a card of its own (a helper moved it to Review) is that
  // draft, not also a result to check, so the draft counts and its result row does not (owner-visible double count)
  const stuck = groups.filter(g => isHelperRow(g.row)), unsure = new Set([...stuck.filter(g => g.row.kind === 'reviewer:unsure').map(g => g.row.ticket),
    ...groups.filter(g => isFactoryDraftRow(g.row)).map(g => g.row.ticket)]);
  const hiddenResults = review.filter(t => unsure.has(t.id)).length;
  // ORCH-476: questions and results are the core's (state.counts); an older core without it: counted here as before
  const core = window.DashHelpers.needsYouFrom(state.counts, hidden);
  const questions = core ? core.questions : window.DashHelpers.needsYouCount(needs), resultCount = core ? core.results : review.length;
  // #2385: the core counts the work that stopped (and leaves out the result a "Reviewer not sure" row stands for); an
  // older core: the rows are added here
  const stoppedCount = core && core.stopped != null ? core.stopped : stuck.length;
  // ORCH-1358: a helper that needs you on its screen (an OK in the terminal, no written question) is in Home's Helpers
  // list as Needs you and an orange chip in the live bar, so it counts here too; a ticket already counted is not again
  // (never a finished ticket, nor one already in the needs list or the core's count: a Home row, or one snoozed for
  // later or just answered)
  const counted = new Set([...needsList().map(r => r.ticket), ...review.map(t => t.id), ...(core ? core.items.map(i => i.ticket) : [])]);
  const screenRows = window.DashHelpers.helperRows(all, state.runs, state.counts).filter(r => r.state === 'you' && !r.finished && !counted.has(r.ticket.id) && !isParked(r.ticket, resting)), screen = screenRows.length;
  // the open questions the number counts, by ticket (the Review page lists those that have no card of their own)
  const askedItems = core ? core.items : needs.map(r => ({ticket:r.ticket, question:r.answer?.question || r.id}));
  return {needs, notices, failed, groups, review, changes, asked, logins, stuck, unsure, hiddenResults, questions, results:Math.max(0, resultCount - hiddenResults), screen, screenRows, askedItems, queued, fromCore:!!core,
    // ORCH-1687: a ticket whose helper could not start is a row of Home's Needs you with its own Try again, so it is
    // part of THE number too (the Review badge said 2 above a Needs you list of 5); the Review page and the Tickets
    // Needs you view list it the same way
    count:questions + resultCount + stoppedCount - hiddenResults + screen + failed.length + drafts};
}
// The one needs-you number (questions, results to check and work that stopped): the Review badge shows it (ORCH-1616:
// only there), the Review page's line, the live bar's need-you end on a phone and the wall read the same one.
function needsYouTotal() { return state ? needsToday().count : 0; }
// ORCH-1687: the tickets the number counts beyond their own questions and results (a helper that could not start, work
// that stopped, a helper waiting on its screen), for the Tickets Needs you view; read once per paint (every ticket
// row asks).
let needIds = null;
function needsYouTicketIds() {
  if (!state) return new Set();
  if (needIds) return needIds;
  const n = needsToday();
  needIds = new Set([...n.failed.map(([t]) => t.id), ...n.stuck.map(g => g.row.ticket), ...n.screenRows.map(r => r.ticket.id)].filter(Boolean));
  Promise.resolve().then(() => { needIds = null; });
  return needIds;
}
// Services that should run but do not (one that is off on purpose, like Sync before it is turned on, is not one).
function stoppedServices() { return array(state.services).filter(s => s.running === false && !s.idle); }
function stoppedServicesRow() {
  const names = stoppedServices().map(s => { const a = addons().find(x => x.name === s.addon); const n = a?.dashboard?.label || s.addon; return n.charAt(0).toUpperCase() + n.slice(1); });
  if (!names.length) return null;
  const list = names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names.at(-1) : names[0];
  const start = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, names.length > 1 ? 'Start them' : 'Start ' + names[0]);
  return blockedRow('background', 'service', h('strong', {}, list + (names.length > 1 ? ' have stopped.' : ' has stopped.')),
    (names.length > 1 ? 'Their' : 'Its') + ' work waits. Your tickets and everything else still work.', start);
}
// After an automatic update (Settings > About & updates): the new version and what changed, or a plain note that it
// failed and orch stays on the old version. "Got it" clears it.
function autoUpdateNote() {
  const n = state.auto_update_note;
  if (!n || (n.state !== 'updated' && n.state !== 'failed')) return null;
  // "orch 17" is a release ("17", as drawn); a development build ("orch develop 5d59166f") is a test version: never a
  // branch name or commit id on Home (report r-1118-0907)
  const rel = v => (/^orch (\d+)$/.exec(String(v || '')) || [])[1];
  const to = rel(n.to) || 'the newest test version';
  const got = snapshot ? null : h('button', {type:'button', className:'btn ghost sm', 'data-action':'auto-update-note-ok', 'data-key':'auto-update-note-ok'}, 'Got it');
  if (n.state === 'failed') {
    return h('div', {className:'banner attn', 'data-key':'auto-update-note', role:'status'}, h('p', {className:'grow'},
      'orch could not update itself to ' + to + (n.reason ? ': ' + clean(n.reason).replace(/[.\s]+$/, '') : '') + '. ' +
      (rel(n.from) ? 'It is still ' + rel(n.from) : 'It keeps the version it has') + ' and tries again later.'), got);
  }
  const changes = array(n.changes);
  return h('section', {className:'card home-card', 'data-key':'auto-update-note'},
    h('div', {className:'card-h row between'}, h('h2', {}, 'orch updated itself to ' + to), got),
    h('div', {className:'pad'}, changes.length ? h('ul', {className:'upd-changes', 'data-key':'auto-update-changes'}, changes.map(c => h('li', {}, clean(c)))) : h('p', {className:'muted'}, rel(n.from) ? 'Updated from ' + rel(n.from) + '.' : 'The update is done.')));
}
// After an update whose short self-check failed (ORCH-551): what does not work, and one button to go back to the
// release the update came from. "Not now" clears it.
function updateCheckCard() {
  const c = state.update_check;
  if (!c || !array(c.failed).length) return null;
  // A page server that could not sign in ("x sign-in failed (answer 403)"; the code stays in the stored check for
  // the problem log): on screen its name and what to do, never a code a person cannot use. A restart is not known
  // to fix a refused sign-in, so the card offers Report a problem (report r-1122-0539).
  let signIn = false;
  const whys = array(c.failed).map(f => clean(f.why || f.name).replace(/[.\s]+$/, '').replace(/^(\S+) sign-in failed(?: \(answer [^)]*\))?$/, (m, who) => {
    signIn = true;
    return who.charAt(0).toUpperCase() + who.slice(1) + ' could not sign in';
  })).filter(Boolean);
  const what = (c.release ? 'After the update to version ' + c.release + ', ' : 'After the update, ') + (whys.length > 1 ? 'these do not work: ' + whys.join('; ') + '.' : whys[0] + '.');
  const actions = snapshot ? [] : [
    c.back_to ? h('button', {type:'button', className:'btn outline sm', 'data-action':'update-check-back', 'data-to':String(c.back_to), 'data-key':'update-check-back'}, 'Go back to ' + c.back_to) : null,
    signIn ? h('button', {type:'button', className:'btn outline sm', 'data-action':'update-check-report', 'data-key':'update-check-report'}, 'Report a problem') : null,
    h('button', {type:'button', className:'btn ghost sm', 'data-action':'update-check-ok', 'data-key':'update-check-ok'}, c.back_to ? 'Not now' : 'Got it'),
  ];
  return h('div', {className:'banner attn', 'data-key':'update-check', role:'status'},
    h('p', {className:'grow'}, what + (c.back_to ? ' Go back to release ' + c.back_to + '?' : '')), ...actions);
}
// What the helper wrote when work finished: the outcome, else the completion note.
function changedWords(t) {
  const o = typeof outcomeOf === 'function' ? outcomeOf(t) : {}, first = String(o.changed || o.why || '').split('\n')[0].trim();
  if (first) return {head:first.length > 110 ? first.slice(0, 107) + '…' : first, detail:o.changed ? o.why || '' : ''};
  const n = typeof completionNotes === 'function' ? completionNotes(t)[0] : null;
  return n ? {head:n.head, detail:n.body} : null;
}
// Plain words only (ORCH-407, report r-1118-0544: whole helper summaries with commit ids, file
// and test names, 8+ lines each): the sentences without technical names, in order, up to CHANGED_CHARS; when no
// sentence is plain, the first one, cut short.
const CHANGED_CHARS = 200;
const TECHNICAL = [
  /\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/,  // a commit id
  /[\w/-]\.(py|js|cjs|mjs|ts|json|jsonl|md|css|html|sh|rs|toml|ya?ml|swift|txt|lock)\b/i,  // a file name
  /\w_\w/, /\b[a-z_]+\.[a-z_]+\.[a-z_]+/, /\b[a-z]+[A-Z]\w*\(/,  // code names
  /(^|\s)--?[a-z][\w-]*/, /[`<>{}]/, /\/\w+\//,  // flags, code marks, paths
];
function plainChanged(text, max = CHANGED_CHARS) {
  const all = String(text || '').replace(/\s+/g, ' ').trim();
  if (!all) return '';
  const sentences = all.split(/(?<=[.!?])\s+/), cut = s => s.length <= max ? s : s.slice(0, s.lastIndexOf(' ', max - 1) > 40 ? s.lastIndexOf(' ', max - 1) : max - 1).replace(/[\s,;:]+$/, '') + '…';
  const plain = sentences.filter(s => !TECHNICAL.some(r => r.test(s)));
  if (!plain.length) return cut(sentences[0]);
  let out = '';
  for (const s of plain) {
    if (out && out.length + 1 + s.length > max) break;
    out = out ? out + ' ' + s : s;
  }
  return cut(out);
}
// the head and its detail as sentences: a head the detail repeats is said once, a head without an end gets a full stop
function changedText(words) {
  const head = clean(words.head || '').trim(), detail = clean(words.detail || '').trim();
  if (!detail) return head;
  if (!head || detail.startsWith(head.replace(/…$/, ''))) return detail;
  return head + (/[.!?…]$/.test(head) ? ' ' : '. ') + detail;
}
// "Finished" on Home (O-01 D): the five newest finished tickets, each one title and one short line of its result
// (finishedSaid), then one link to all of them in the Tickets list.
const FINISHED_SHOWN = 5;
function finishedRow(t) {
  const at = finishedAt(t), said = finishedSaid(t);
  return h('div', {className:'card-row home-finished', 'data-key':'ticket-' + t.id},
    h('div', {className:'grow'}, h('h3', {className:'truncate'}, h('a', {href:href(t.id), title:clean(t.title)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t)),
      h('p', {className:'meta truncate', 'data-key':'finished-result-' + t.id, title:said || null}, said || 'No result written yet')),
    at ? h('span', {className:'meta nowrap'}, time(at)) : null);
}
function finishedCard(all) {
  const done = all.filter(t => t.status === 'done' && finishedAt(t)).sort((a, b) => finishedAt(b) - finishedAt(a));
  const more = done.length > FINISHED_SHOWN ? h('div', {className:'card-row', 'data-key':'finished-done'}, h('a', {className:'btn ghost sm', href:'#tickets?view=done-week'}, 'Done tickets →')) : null;
  return card('finished-today', 'Finished', '', done.length ? [...done.slice(0, FINISHED_SHOWN).map(finishedRow), more] : [emptyRow('Nothing finished yet.')]);
}
// What helpers need (ORCH-45, drawn and chosen on ORCH-43): a login, connection or key that runs out within three days
// is a row in Needs you; one that stopped working or cannot be reached is the red banner at the top, naming the tickets
// it stops. The Renew button comes from the renew step (a page function renewButton) when it is there; until then
// Check again runs every check once more (orch logins), and Try again for one that cannot be reached.
const loginWarnings = () => window.DashHelpers.needWarnings(snapshot ? null : state?.logins);
function loginTicketLinks(list) {
  return list.flatMap((t, i) => [i ? ' · ' : null, h('a', {href:href(t.id), 'data-key':'login-ticket-' + t.id}, (typeof t.key === 'string' && t.key && t.key !== t.id && !/^t_[a-z0-9]+$/i.test(t.key) ? t.key + ' ' : '') + clean(t.title || ''))]);
}
async function checkLogins(item, key) {
  if (changeUnavailable() || locks.has(key)) return;
  locks.add(key);
  try {
    const result = await act('logins.check', {});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); return; }
    const after = window.DashHelpers.needItems(state?.logins).find(i => i.name === item.name);
    window.orch.toast(clean(window.DashHelpers.needName(item)) + ': ' + (after ? window.DashHelpers.needState(after).word.replace(/^✓ /, '') : 'checked'), after?.state === 'works' ? 'ok' : 'error');
  } finally { locks.delete(key); render(); }
}
function loginAction(item, key, quiet = false) {
  if (snapshot) return null;
  const own = typeof renewButton === 'function' ? renewButton(item, {key, quiet}) : null;
  if (own || quiet) return own || null;
  const reach = item.state === 'unreachable';
  const control = button(reach ? 'Try again' : 'Check again', 'outline sm', () => checkLogins(item, key));  // one filled button per view
  control.dataset.key = key + '-check';
  return control;
}
// A tool orch cannot renew itself says the one step the person takes (ORCH-48); with its sign-in command the command
// itself and one Copy button (ORCH-218).
function loginHow(item, key = 'login-how-' + item.name) {
  const how = window.DashHelpers.needHow(item), cmd = window.DashHelpers.needSignIn(item);
  if (cmd && window.UI?.commandCopy) return window.UI.commandCopy(cmd, {lead:how, dataKey:key});
  return how ? h('p', {className:'meta', 'data-key':key}, how + (cmd ? ' ' + cmd : '')) : null;
}
function loginSoonRow(item) {
  const key = 'login-soon-' + item.name, n = item.stops.length;
  return h('div', {className:'card-row', 'data-key':key, 'data-login':'soon'},
    h('div', {className:'grow'}, h('p', {}, h('strong', {}, 'The ' + clean(window.DashHelpers.needName(item)) + ' ends on ' + window.DashHelpers.needEnds(item) + '.')),
      n ? h('p', {className:'meta'}, 'After that helpers stop on ' + n + (n === 1 ? ' ticket: ' : ' tickets: '), loginTicketLinks(item.stops)) : null,
      loginHow(item)),
    loginAction(item, key));
}
// W-017 (28 Nov): a sign-in or tool that stopped is one line with one button in Blocked now. A helper tool's own
// sign-in shows only for the tool chosen in Settings (a workspace that runs Claude never hears about Codex); the line
// never names a terminal: orch renews it where it can (Renew), else Sign in opens the tool's step in Settings.
const blockedLogins = stopped => stopped.filter(i => !i.helper || i.chosen);
function loginStoppedRow(item) {
  const key = 'login-stopped-' + item.name, n = item.stops.length, name = clean(window.DashHelpers.needName(item));
  const noNew = item.chosen && item.state === 'renew';
  const why = n ? 'Helpers stopped on ' + n + (n === 1 ? ' ticket' : ' tickets') + (noNew ? ' and start no new work.' : '.') : noNew ? 'Helpers start no new work.' : '';
  const own = snapshot || typeof renewButton !== 'function' ? null : renewButton(item, {key});
  const action = snapshot ? null : own || (item.state === 'renew' ? h('a', {className:'btn outline sm', href:'#settings/agent', 'data-key':key + '-sign-in'}, 'Sign in') : loginAction(item, key));
  return blockedRow(key, 'login', h('strong', {}, 'The ' + name + window.DashHelpers.needStoppedWord(item) + '.'), why, action, {'data-login':'stopped'});
}
// Tickets waiting in line for a helper, and why none starts now (ORCH-266: the computer looked busy and nothing said so).
// One short line, never the list of waiting tickets (ORCH-1100: 112 links filled the screen; owner picked design B).
// No reason (only the short pause between two starts): no banner, it passes within seconds.
function lineWords(line) {
  if (line.limit) return 'Helper limit reached.';
  const why = clean(line.why);
  if (/^the usage limit/i.test(why)) return 'Usage limit reached.';
  if (/^the disk is almost full/i.test(why)) return 'Disk almost full.';
  if (/busy/i.test(why)) return 'Computer too busy to start more work.';
  return why.charAt(0).toUpperCase() + why.slice(1).replace(/\.?$/, '.');
}
function lineBanner() {
  const line = snapshot ? null : state.start_line;
  if (!line || !line.why || !array(line.waiting).length) return null;
  const known = new Set(tickets().map(t => t.id));
  if (!array(line.waiting).some(id => known.has(id))) return null;
  return h('div', {className:'banner attn', role:'status', 'data-key':'start-line'},
    h('p', {className:'grow'}, h('strong', {}, lineWords(line))),
    line.limit ? h('a', {className:'btn outline sm', href:'#settings/helper', 'data-key':'start-line-limit'}, 'Allow more helpers') : null);
}
// Home (O-01 D, owner 28 Nov): blocked work first, then ONE line for what waits in Review, the numbers in one row,
// Helpers and the five newest finished tickets. No question or result card is drawn here: Review has them all.
function home() {
  const {notices, failed, groups, changes, logins, stuck, questions, results, queued, count:needCount} = needsToday(), all = tickets();
  // a ticket waiting for review is the person's result, never an idle helper (ORCH-407); its left-over session is
  // closed by orch run tend (the core's count leaves it out the same way, ORCH-476)
  const helpers = window.DashHelpers.helperRows(all, state.runs, state.counts).filter(r => !(r.ticket.status === 'review' && ['idle', 'stuck'].includes(r.state)));
  const stopped = stuck.filter(g => g.row.kind !== 'reviewer:unsure');
  // an add-on's own row that says something is broken and offers the fix (a service work depends on, W-054 A)
  const broken = groups.filter(g => !isHelperRow(g.row) && g.row.tone === 'bad' && needActs(g.row).length);
  const signIns = blockedLogins(logins.stopped);
  const holdsFilled = el => !!el && (/\bprimary\b/.test(String(el.className || el.attrs?.className || '')) || [...(el.children || [])].some(holdsFilled));
  const mark = (el, kind) => { el.setAttribute?.('data-blocked', kind); el.setAttribute?.('data-counts', '0'); return el; };
  const blocked = [...signIns.map(loginStoppedRow), stoppedServicesRow(), ...broken.map(g => mark(needActionsRow(g.row, 'need-' + g.row.id), 'addon')),
    ...failed.map(([t, sf]) => startFailedRow(t, sf)), ...stopped.map(g => stoppedRow(g.row))].filter(Boolean);
  // THE number (the Review badge) minus the blocked rows that are part of it: what the Review line says
  const waiting = Math.max(0, needCount - stopped.length - failed.length);
  // what is neither blocked nor a card of Review, quiet at the foot: a login that runs out soon, an add-on's own
  // row, changes to put live, the notes, the merge queue and what is parked
  const other = groups.filter(g => !broken.includes(g) && !isHelperRow(g.row) && !isFactoryDraftRow(g.row) && (needActs(g.row).length || !g.row.ticket || !g.row.answer?.question));
  const parked = parkedList();
  const also = [...logins.soon.map(loginSoonRow), ...other.map(g => noteRow(g.row)), ...changes.map(changeRow),
    ...(notices.length ? [notesLine(notices), ...(notesOpen ? notices.map(noteRow) : [])] : []), queueLine(queued),
    ...(parked.length ? [parkedLine(parked), ...(parkedOpen ? parked.map(parkedRow) : [])] : [])].filter(Boolean);
  const banner = [lineBanner(), typeof reviewPausedLine === 'function' ? reviewPausedLine() : null, typeof browseAskBanner === 'function' ? browseAskBanner() : null, updateCheckCard(), autoUpdateNote()];
  const title = blocked.length || waiting || logins.soon.length || other.length || changes.length ? 'Things to look at' : 'Nothing needs you';
  const today = now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'});
  // ORCH-1698: the top bar (and its New ticket) is hidden under the phone tabs, so Home offers it itself on a phone
  // ORCH-1699: a workspace with no ticket yet never links to "All 0 tickets"; its empty page names the first step
  const head = heading(title, today, {
    actions:fragment(snapshot || !all.length ? null : h('button', {type:'button', className:'btn outline sm phone-only', 'data-action':'new', 'data-key':'new-ticket-phone'}, 'New ticket'),
      all.length ? h('a', {className:'btn ghost sm', href:'#tickets', 'data-key':'all-tickets'}, 'All ' + all.length + (all.length === 1 ? ' ticket →' : ' tickets →')) : null)});
  const blockedCard = blocked.length ? h('section', {className:'card home-card', 'data-key':'blocked', id:'needs-you'},
    h('header', {className:'card-h'}, h('h2', {}, 'Blocked now'), h('span', {className:'grow'}), h('span', {className:'meta'}, String(blocked.length))), blocked) : null;
  const alsoCard = also.length ? h('section', {className:'card home-card', 'data-key':'needs-notes-card'}, also) : null;
  if (!all.length) {
    // W-017 (28 Nov): day one is the first step and nothing else: one sentence, one filled New ticket
    const step = typeof newButton === 'function' ? newButton() : null, first = 'Write your first ticket';
    const text = 'Say in one sentence what needs doing. A helper works on it and asks you only for real decisions.';
    return fragment(head, banner, blockedCard, window.UI?.pageEmpty ? window.UI.pageEmpty({title:first, text, step, dataKey:'empty'})
      : h('section', {className:'card page-empty', 'data-key':'empty'}, h('h2', {}, first), h('p', {}, text), step), alsoCard);
  }
  const {inProgress, notStarted} = openLists(all, new Set([...groups.map(g => g.row.ticket), ...all.filter(t => t.status === 'review').map(t => t.id)].filter(Boolean)));
  const finishedToday = all.filter(t => t.status === 'done' && finishedAt(t)?.toDateString() === now().toDateString()).length;
  // a read-only copy has no run data: no Helpers card
  const helpersEl = helpers.length && window.UI?.helperList ? helpersCard(helpers) : null, finished = finishedCard(all);
  return fragment(head, banner,
    blockedCard || h('section', {className:'card home-card', 'data-key':'blocked', 'data-empty':''}, h('div', {className:'card-row muted'}, 'Nothing is blocked.')),
    // one filled button on the page: a blocked row's own filled one (Renew a sign-in) is the main thing while it shows
    snapshot && !waiting ? null : reviewLine(waiting, questions, results, !snapshot && !blocked.some(holdsFilled)),
    homeNumbers(inProgress.length, notStarted.length, finishedToday, window.DashHelpers.helpersWorking(helpers)),
    helpersEl ? h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'}, finished), h('aside', {className:'stack', 'data-key':'right'}, helpersEl)) : finished,
    alsoCard);
}
// Three different states, three sets of words: nothing arrived (offline), the server answered with a failure
// (error), the answer is only late (slow: no failure, nothing is held back).
const HELD_WORDS = /^(Start|Start helper|Try again|Check again)$/;
function connectionNotice(connectionEl, hadState, kind = 'offline') {
  const saved = hadState ? 'Showing the last saved view. You can’t change anything until ' : '';
  const words = kind === 'slow' ? ['Still loading', 'orch is taking longer than usual to answer. Nothing is lost.']
    : kind === 'error' ? ['orch had a problem', hadState ? saved + 'it works again.' : 'orch answered with an error. Your data has not been changed.']
    : ['Can’t reach the workspace', hadState ? saved + 'you’re back online.' : 'Reconnect to load your workspace. Your data has not been changed.'];
  connectionEl.dataset.kind = kind;
  // No null child: replaceChildren writes null as the text "null" (seen in the corner of Still loading at phone width)
  connectionEl.replaceChildren(...[h('div', {className:'grow'}, h('h3', {}, words[0]), h('p', {}, words[1])),
    kind === 'slow' ? null : button('Try again', 'outline sm', () => refresh())].filter(Boolean));
  connectionEl.hidden = false;
  holdChanges();
  if (typeof paintUpdated === 'function') paintUpdated();
}
// While the workspace is unreachable or failing, the buttons that start or change something stay off; they come
// back with the connection. A page drawn again meanwhile is held again (see the observer in app.js).
function holdChanges() {
  const banner = document.getElementById('connection'), main = document.getElementById('content');
  if (!main?.querySelectorAll) return;
  const hold = banner?.hidden === false && banner.dataset?.kind !== 'slow';
  for (const b of main.querySelectorAll('button')) {
    if (hold && (b.matches('.btn.primary, [data-action="start"]') || HELD_WORDS.test((b.textContent || '').trim())) && !b.disabled) {
      b.disabled = true; b.dataset.held = '1'; b.title = 'Not available while the workspace is offline.';
    } else if (!hold && b.dataset.held) { b.disabled = false; delete b.dataset.held; b.removeAttribute('title'); }
  }
}
// Chat (former General) lives in pages/chat.js.