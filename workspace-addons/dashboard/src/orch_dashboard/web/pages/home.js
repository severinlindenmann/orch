'use strict';
// Page controls use direct listeners; h() only sets attributes.
function changeUnavailable() {
  const banner = document.getElementById('connection');
  if (banner?.hidden !== false || banner.dataset?.kind === 'slow') return false;  // a slow answer is no failure: changes go on
  window.orch.toast(banner.dataset?.kind === 'error' ? 'orch had a problem. Your change was not sent.' : "Can't reach orch. Your change was not sent.", 'error');
  return true;
}
function changeError(result) {
  if (result.status === 0) return "Can't reach orch. Your change was not sent.";
  const text = window.DashHelpers.scrubText(result.text);
  // the page was older than the ticket (a new round started, the work changed): nothing was approved
  if (/changed while you worked|Read it again/i.test(text)) return 'This ticket changed since you opened it. Look at it again, then accept.';
  // an answer to a question that is settled or changed meanwhile (ORCH-1047): plain words, no question id
  if (/^q[0-9]+ is already answered/.test(text)) return 'This question was already answered.';
  if (/^q[0-9]+ changed after it was shown/.test(text)) return 'This question changed since you saw it. Look at it again, then answer.';
  return text;
}
// Home rows sit under a heading that already says their status, so a row shows no status chip; the ticket number
// (ORCH-58) goes before the title. `tail` is what a row adds instead, e.g. when it finished.
function ticketTitle(t, tail = null) {
  return h('div', {className:'row ticket-title'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)), titleTag(t)), tail);
}
function parentLine(t) {
  const parent = ticketOf(t.parent || tickets().find(p => array(p.children).includes(t.id))?.id);
  return parent ? h('p', {className:'meta'}, parent.epic ? 'Part of the epic ' : 'Sub-ticket of ', h('a', {href:href(parent.id)}, clean(parent.title))) : null;
}
const finishedAt = t => parse(window.DashHelpers.doneAt(t));

// A finished row says its result right under the title (ORCH-1849): the outcome or completion note the helper or a
// person wrote, in at most about 3 lines of the narrow side card; with none written it says so, never a made-up line.
const FINISHED_CHARS = 110;
function ticketRow(t) {
  const at = finishedAt(t), words = changedWords(t), said = words ? plainChanged(changedText(words), FINISHED_CHARS) : '';
  // The time sits under the title (not beside it), so a title fits on one line in the narrow side card.
  const when = [at ? 'Finished ' + time(at) : '', said ? '' : 'No result written yet'].filter(Boolean).join(' · ');
  return h('div', {className:'card-row home-ticket', 'data-key':'ticket-' + t.id}, ticketTitle(t),
    said ? h('p', {className:'muted', 'data-key':'finished-result-' + t.id}, said) : null, h('p', {className:'meta'}, when));
}
// Answered on Home but not sent yet (the Undo window): the question is hidden and not counted.
const pendingAnswers = new Map();
let ANSWER_UNDO_MS = 5200, enterRowId = '';
// `same`: rows on other tickets asking the identical question with the same choices; one answer goes to all of them.
function needRow(row, newest, questionCount = 1, same = []) {
  const key = 'need-' + row.id;
  if (isFactoryDraftRow(row)) return factoryDraftRow(row, key);
  if (isHelperRow(row)) return helperRow(row, key);
  if (needActs(row).length) return needActionsRow(row, key);
  if (!row.ticket && array(row.answer?.options).length) return needNoticeRow(row, key);
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row);
  const options = array(row.answer?.options), factory = factoryStartOf(row);
  let actions = null, other = null;
  if (factory && (snapshot || !options.length)) return factoryStartRow(row, key, t, factory, []);
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
          if (failed) {
            window.orch.toast((answered ? 'Answered on ' + answered + ' of ' + total + ' tickets. ' : '') + changeError(failed), 'error');
            if (typeof refresh === 'function') refresh();  // a refused answer: Home reads what is open now
          }
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
    if (factory) return factoryStartRow(row, key, t, factory, window.DashHelpers.factoryStartOptions(options).map(o => {
      const control = h('button', {type:'button', className:'btn outline sm', 'data-key':key + '-option-' + o.answer}, o.label);
      control.onclick = event => answer(o.answer, event);
      return control;
    }));
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
  const question = (window.DashHelpers.questionWords || String)(needQuestion(row)), when = typeof age === 'function' ? age(row.since) : '';
  return h('div', {className:'card-row home-need' + (row.id === enterRowId ? ' row-new' : ''), 'data-key':key, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null},
    h('h2', {className:'question-title'}, clean(source && String(question).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(question, 'The helper'))),
    h('p', {className:'meta question-context'}, asked + ' asked' + (when ? ' ' + when : ''),
      t ? [(clean(t.title).toLowerCase() === String(window.DashHelpers.plainWhy(question, 'The helper')).trim().toLowerCase() ? ' · ' : ' on ' + (window.DashHelpers.ticketKey(t) ? window.DashHelpers.ticketKey(t) + ' ' : '') + '‘' + clean(t.title) + '’ · '), h('a', {href:href(t.id)}, 'Open ticket')] : null, typeof titleTag === 'function' && t ? titleTag(t) : null),
    questionCommandRows(needQuestion(row), key),
    actions && options.length ? h('p', {className:'meta choose-line'}, 'Needs you · Choose an answer') : null,
    same.length ? h('p', {className:'meta', 'data-key':key + '-same'}, 'Asked on ' + (same.length + 1) + ' tickets – answer once') : null,
    questionCount > 1 ? h('p', {className:'meta'}, questionCount + ' questions') : null,
    actions, other, t ? parentLine(t) : null);
}
// A Factory start question (ORCH-60, as drawn and accepted on 16 Nov): the whole proposal is hundreds of words, so
// Home shows its title, goal and time and links to the proposal on the Factory page; the buttons are equal, Start last.
function factoryStartOf(row) {
  const q = array(ticketOf(row.ticket)?.questions).find(x => x.id === row.answer?.question);
  return q && q.kind === 'factory:start' ? window.DashHelpers.factoryStart(q.text) : null;
}
function factoryProposalHref(t) { return factoryOrderHref(t.id, 'proposal'); }
function factoryStartRow(row, key, t, p, buttons) {
  const when = typeof age === 'function' ? age(row.since) : '';
  return h('div', {className:'card-row home-need' + (row.id === enterRowId ? ' row-new' : ''), 'data-key':key, 'data-need-row':row.id, 'data-factory-start':''},
    h('p', {className:'meta'}, 'Proposed project', typeof t.key === 'string' ? [' · ', h('span', {className:'key'}, t.key)] : null),
    h('h2', {className:'question-title'}, 'Start “' + clean(p.title) + '”?'),
    h('p', {className:'muted'}, clean(p.goal)),
    h('p', {className:'meta'}, p.meta),
    h('p', {className:'meta question-context'}, whoAsked(t) + ' asked' + (when ? ' ' + when : '') + ' · ',
      h('a', {href:factoryProposalHref(t), 'data-key':key + '-proposal'}, 'Read proposal')),
    buttons.length ? h('div', {className:'actions'}, buttons) : null);
}
// A Factory draft ready for Plan the run (ORCH-479): the card of the Factory page, with its verbs. Read draft opens it
// on the Factory page; Plan the run and Ask for changes send the person's words to the agent on the order, as there.
function factoryOrderHref(id, part) {
  const page = typeof addons === 'function' && addons().some(a => a.name === 'factory' && a.page);
  return page && /^t_[a-z0-9]{6,16}$/.test(id) ? '#addon/factory/#/order/' + id + '/' + part : href(id);
}
const isFactoryDraftRow = row => !!window.DashHelpers.isFactoryDraft?.(row);
const draftSent = new Map();  // row id -> what Home said after a click (the row goes once the agent works on it)
function factoryDraftRow(row, key) {
  const t = ticketOf(row.ticket), when = typeof age === 'function' ? age(row.since) : '';
  const tag = t && typeof t.key === 'string' ? [' · ', h('span', {className:'key'}, t.key)] : null;
  return h('div', {className:'card-row home-need' + (row.id === enterRowId ? ' row-new' : ''), 'data-key':key, 'data-need-row':row.id, 'data-factory-draft':''},
    h('p', {className:'meta'}, 'Factory draft', tag),
    h('h2', {className:'question-title'}, clean(row.title)),
    h('p', {className:'muted'}, 'Read the draft, then plan the run or ask for changes.'),
    h('p', {className:'meta question-context'}, (t ? whoAsked(t) : 'Helper') + ' wrote it' + (when ? ' ' + when : '') + ' · ',
      h('a', {href:factoryOrderHref(row.ticket, 'draft'), 'data-key':key + '-draft'}, 'Read draft')),
    snapshot ? null : factoryDraftActions(row, key));
}
function factoryDraftActions(row, key) {
  const said = draftSent.get(row.id);
  const status = h('p', {className:'meta', role:'status', 'data-key':key + '-status'}, said || '');
  status.hidden = !said;
  if (said) return status;
  const words = window.DashHelpers.FACTORY_DRAFT_WORDS;
  const plan = button('Plan the run', 'outline sm', () => go(words.plan, 'Sent. Your helper is planning the run; the proposal shows up here.'));
  const change = button('Ask for changes', 'outline sm', () => writing(true));
  const note = h('textarea', {className:'text-input', rows:'3', maxLength:'2000', 'aria-label':'What should change', placeholder:'For example: shorter, and add a map', 'data-key':key + '-note'});
  const send = button('Send', 'primary sm', () => { const w = note.value.trim(); if (w) go(words.change(w), 'Sent. Your helper is changing the draft.'); });
  const cancel = button('Cancel', 'ghost sm', () => writing(false));
  plan.dataset.key = key + '-plan'; change.dataset.key = key + '-change'; send.dataset.key = key + '-send'; cancel.dataset.key = key + '-cancel';
  const pick = h('div', {className:'actions'}, plan, change), write = h('div', {className:'actions'}, send, cancel);
  note.hidden = write.hidden = true; send.disabled = true;
  note.addEventListener('input', () => { send.disabled = !note.value.trim(); });
  function writing(on) { note.hidden = write.hidden = !on; pick.hidden = on; status.hidden = true; if (on) note.focus(); }
  async function go(text, sent) {
    if (changeUnavailable() || locks.has(key)) return;
    locks.add(key);
    for (const b of [plan, change, send, cancel]) b.disabled = true;
    try {
      const r = await sendAndStart(row.ticket, text);
      if (r.ok) { draftSent.set(row.id, r.delivered || r.started ? sent : 'Saved. Your helper gets it as soon as it is free.'); window.orch.toast(draftSent.get(row.id), 'ok'); return; }
      window.orch.toast((r.error ? r.error + ' ' : "That didn't work. ") + 'Nothing was sent.', 'error');
    } finally { locks.delete(key); render(); }
  }
  return h('div', {className:'stack'}, pick, note, write, status);
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
// A command the helper wrote in backticks in its question ("Sign in again with `az login`") shows with a Copy button (ORCH-218).
function questionCommandRows(text, key) {
  if (!window.UI?.commandCopy || !window.DashHelpers.questionCommands) return null;
  return window.DashHelpers.questionCommands(text).map((c, i) => window.UI.commandCopy(c, {dataKey:key + '-cmd-' + i}));
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
    h('div', {className:'acts'}, signed ? h('span', {className:'sig', 'data-key':key + '-sig'}, iconEl('shield'), 'Needs your OK') : null, controls));
}
// Work that stopped short (core rows): a pull request left open after its checks passed, or a helper idle at its
// prompt. Two buttons, each one click on an op the page already has; the words sent to the helper are fixed here.
// Stuck tickets (ORCH-426) come first in the list, whether or not the ticket needs a person's review: a helper waiting
// on the person's OK on its screen, a step whose checks keep failing, a ticket the Reviewer was not sure about.
const STUCK_ROWS = ['helper:permission', 'helper:failing', 'reviewer:unsure'];
const HELPER_ROWS = ['helper:unmerged', 'helper:idle', ...STUCK_ROWS];
const isHelperRow = row => !!row && row.source === 'core' && HELPER_ROWS.includes(row.kind) && !!row.ticket;
const isStuckRow = row => isHelperRow(row) && STUCK_ROWS.includes(row.kind);
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
function helperRow(row, key) {
  const t = ticketOf(row.ticket), alive = state.runs?.[row.ticket]?.running === true, pull = row.pull || {};
  const acts = row.kind === 'helper:unmerged'
    ? [['Merge', 'primary sm', () => act('pull.merge', {ticket:row.ticket, url:pull.url, head:pull.head}), 'Merged'],
      [alive ? 'Remind' : 'Start helper', 'outline sm', () => nudgeHelper(row.ticket, MERGE_ASK), alive ? 'Message sent' : 'Helper started']]
    : row.kind === 'helper:permission' || row.kind === 'reviewer:unsure' ? []  // the answer is on the ticket page: the Open link
    : [['Remind', 'outline sm', () => nudgeHelper(row.ticket, NUDGE), 'Message sent'],
      ['Start fresh', 'outline sm', () => restartFresh(row.ticket), 'Helper started fresh']];
  // ORCH-475: the starts are the one Start button (pages/start.js): Starting… until it runs, the caret opens the Start choice.
  // Start helper sends the merge ask first; Start fresh stops the idle helper first, then starts fresh on the usual tool.
  const startOf = label => !t || alive && label === 'Start helper' ? null
    : label === 'Start helper' ? startHost(t, key + '-start', {label, before:async () => [['run.send', {ticket:row.ticket, text:MERGE_ASK}]]})
    : label === 'Start fresh' ? startHost(t, key + '-fresh', {label, fresh:true, running:false, before:async () => state.runs?.[row.ticket]?.running === true ? [['run.stop', {ticket:row.ticket}]] : []})
    : null;
  const controls = snapshot ? [] : acts.map(([label, style, run, done]) => {
    const kit = startOf(label);
    if (kit) return kit;
    const control = button(label, style, async () => {
      if (changeUnavailable() || locks.has(key)) return;
      locks.add(key);
      try {
        const result = await run();
        window.orch.toast(result.ok ? done : changeError(result), result.ok ? 'ok' : 'error');
      } finally { locks.delete(key); render(); }
    });
    control.dataset.key = key + '-act-' + label;
    return control;
  });
  const link = row.kind === 'helper:unmerged' && /^https:\/\/github\.com\//.test(String(pull.url || '')) ? h('a', {href:pull.url, target:'_blank', rel:'noopener noreferrer'}, 'Pull request') : null;
  const open = isStuckRow(row) && t ? h('a', {className:'btn outline sm', href:href(t.id), 'data-key':key + '-open'}, 'Open') : null;
  // the mark: the master's helper pill, the same word as the Helpers list (Stuck; a helper idle under 20 min is Idle).
  // ORCH-1717: a ticket the Reviewer left for the person is not stuck, it waits for a look: the calm Check pill of a
  // ticket in Review and the one plain reason (`short`), never the Reviewer's file counts.
  const unsure = row.kind === 'reviewer:unsure';
  const mark = unsure ? (window.UI?.ticketPill ? window.UI.ticketPill({pill:'check', word:'Check'}) : null)
    : window.UI?.helperPill ? (row.kind === 'helper:idle' ? window.UI.helperPill('idle', 'Idle') : window.UI.helperPill('stuck', 'Stuck')) : null;
  const said = unsure && typeof row.short === 'string' && row.short ? row.short : row.text;
  return h('div', {className:'card-row home-need need-acts', 'data-key':key, 'data-need-row':row.id, 'data-stopped':row.kind},
    h('div', {className:'grow'}, h('p', {}, mark, mark ? ' ' : null, clean(said)),
      h('p', {className:'meta'}, t ? h('a', {href:href(t.id)}, window.DashHelpers.keyTag(t, h), clean(t.title)) : clean(row.title), link ? [' · ', link] : null)),
    h('div', {className:'acts'}, open, controls));
}
function startFailedRow(t, sf) {
  return h('div', {className:'card-row home-need', 'data-key':'start-failed-' + t.id}, ticketTitle(t),
    h('p', {}, clean(sf.text)),
    snapshot ? null : h('div', {className:'row'}, startHost(t, 'start-failed-' + t.id + '-retry', {label:'Try again', continueLabel:'Try again'}) || button('Try again', 'outline sm', async () => {
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
    h('span', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(t, h), clean(t.title)), task ? h('span', {className:'meta'}, clean(task.text || task.title)) : null));
}
// Helpers (ORCH-61, owner pick A on ORCH-64): one row per running helper with ORCH-n, step, minutes and the core's
// state word (Working, Needs you, Waiting, Idle, Stuck); Remind on an idle or stuck row, Stop on one whose ticket
// is finished. The same kit widget (UI.helperList) draws the live list of the other add-on page.
function helpersCard(rows) {
  const key = 'helpers';
  const action = (r, label, run, done) => ({label, key:key + '-' + r.ticket.id + '-' + label.toLowerCase(), run:async () => {
    const lock = key + '-' + r.ticket.id;
    if (changeUnavailable() || locks.has(lock)) return;
    locks.add(lock);
    try {
      const result = await run();
      window.orch.toast(result.ok ? done : changeError(result), result.ok ? 'ok' : 'error');
    } finally { locks.delete(lock); render(); }
  }});
  return window.UI.helperList(rows.map(r => ({
    key:typeof r.ticket.key === 'string' ? r.ticket.key : '', title:clean(r.ticket.title), href:href(r.ticket.id),
    state:r.state, word:r.word, meta:window.UI.helperMeta(r), dataKey:key + '-' + r.ticket.id,
    actions:snapshot || !['idle', 'stuck'].includes(r.state) ? [] : r.finished
      ? [action(r, 'Stop', () => act('run.stop', {ticket:r.ticket.id}), 'Helper stopped')]
      : [action(r, 'Remind', () => nudgeHelper(r.ticket.id, NUDGE), 'Message sent')],
  })), {dataKey:'helpers'});
}
// G2: a Working ticket with no news for 6 h is one quiet line ("Quiet since 09:20: title"), never a need.
function quietRow(t) {
  return h('a', {className:'card-row working-row quiet-row', href:href(t.id), 'data-key':'quiet-' + t.id},
    h('span', {className:'grow'}, h('span', {className:'meta'}, window.DashHelpers.quietWords(t.quiet_since, now()) + ': '), h('strong', {}, window.DashHelpers.keyTag(t, h), clean(t.title))));
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
// The card on a question (orch ask --draft/--choose/...), else null.
function needCardQuestion(row) {
  const q = array(ticketOf(row.ticket)?.questions).find(x => x.id === row.answer?.question);
  return q && q.card && typeof q.card === 'object' ? q : null;
}
// A Run it now question: its own row with the command box and the one button (ORCH-848), not a link to Review.
function runCardRow(row) {
  const t = ticketOf(row.ticket), q = needCardQuestion(row), key = 'need-run-' + (t?.id || row.id);
  const node = !snapshot && typeof runCardNode === 'function' ? runCardNode(t.id, q) : null;
  const meta = [t && clean(t.title) !== clean(q.card?.title) ? clean(t?.title) : '', typeof age === 'function' ? age(row.since) : ''].filter(Boolean).join(' · ');
  return h('div', {className:'card-row', 'data-key':key, 'data-need-row':row.id},
    h('div', {className:'grow stack'}, h('div', {}, h('h3', {}, window.DashHelpers.keyTag(t, h), clean(q.card?.title || shortQuestion(q.text))), h('p', {className:'meta'}, meta)), node));
}
// Cards that wait on one ticket (a design review is often a set of them): one row with the set's name, how many,
// the first pictures, and one button that opens Review at the first card.
function cardSetRow(row) {
  const t = ticketOf(row.ticket), open = array(t?.questions).filter(q => q.answer == null && !q.taken_back && q.card && typeof q.card === 'object');
  const names = [...new Set(open.map(q => q.group).filter(Boolean))], n = open.length || 1, key = 'need-set-' + (t?.id || row.id);
  // One card: the row says what it asks (its title, else its question); several: the set's name. Always with the ticket key.
  const one = open.length === 1 ? open[0] : null, ask = one ? clean(one.card?.title || shortQuestion(one.text)) : '';
  const title = ask || (names.length === 1 ? names[0] : clean(t?.title || 'Cards to look at'));
  const api = typeof reviewApi === 'function' ? reviewApi() : null, o = {fileUrl:api ? api.fileUrl : () => ''};
  const pics = window.UI?.cardShown ? open.slice(0, 3).map(q => {
    const g = window.UI.cardShown({card:q.card, ticket:t.id}, o), tiles = g ? [...g.children] : [];
    if (open.length === 1) return tiles;  // one card: every picture side by side (Before and After, A and B), each captioned
    const pick = tiles.find(x => x.dataset.on === 'after') || tiles.find(x => x.dataset.on !== 'before') || tiles[0];  // a set: the proposal of each card
    if (!pick) return null;
    const cap = pick.querySelector('b');
    if (cap) cap.textContent = clean(q.card.title || '');
    return pick;
  }).flat().filter(Boolean) : [];
  const meta = [n === 1 ? '1 card to look at' : n + ' cards to look at', (names[0] && names[0] !== title ? names[0] : '') || (t && clean(t.title) !== title ? clean(t.title) : ''), typeof age === 'function' ? age(row.since) : ''].filter(Boolean).join(' · ');
  const go = snapshot ? null : h('a', {className:'btn outline sm', href:'#review?card=' + encodeURIComponent('core:q:' + row.ticket + ':' + (open[0]?.id || row.answer?.question)), 'data-key':key + '-go'}, n === 1 ? 'Look at it' : 'Look at all ' + n);
  return h('div', {className:'card-row', 'data-key':key, 'data-need-row':row.id},
    h('div', {className:'grow stack'}, h('div', {}, h('h3', {}, window.DashHelpers.keyTag(t, h), title), h('p', {className:'meta'}, meta)), pics.length ? h('div', {className:'decision-shown'}, pics) : null), go);
}
// A further question, startable failure or add-on row: the same one button the full card would open.
function needListRow(row, count, same) {
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row), key = 'need-' + row.id;
  const source = !t && row.source ? addonName(row.source) : '', when = typeof age === 'function' ? age(row.since) : '';
  const meta = [t ? [window.DashHelpers.ticketKey(t), clean(t.title)].filter(Boolean).join(' ') : source, count > 1 ? count + ' questions' : '', same.length ? 'Asked on ' + (same.length + 1) + ' tickets' : '', when].filter(Boolean).join(' · ');
  // a Factory start question below the first one opens the proposal, never the whole text with Start in a dialog
  if (isFactoryDraftRow(row)) return listRow(key, clean(row.title), ['Factory draft', when].filter(Boolean).join(' · '),
    h('a', {className:'btn outline sm', href:factoryOrderHref(row.ticket, 'draft'), 'data-key':key + '-draft'}, 'Read draft'), {'data-need-row':row.id});
  const factory = t && factoryStartOf(row);
  if (factory) return listRow(key, 'Start “' + clean(factory.title) + '”?', [factory.meta, when].filter(Boolean).join(' · '),
    h('a', {className:'btn outline sm', href:factoryProposalHref(t), 'data-key':key + '-proposal'}, 'Read proposal'), {'data-need-row':row.id});
  const action = snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id, 'data-key':key + '-answer'}, choice.label);
  const question = shortQuestion(needQuestion(row)), title = source && String(question).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(question, 'The helper');
  return listRow(key, clean(title), meta, action, {'data-need-row':row.id});
}
// A result to check: same-name results are one row ("3 versions"); the row opens the newest.
function resultRow(group) {
  const t = group[group.length - 1];
  return listRow('check-' + t.id, [window.DashHelpers.keyTag(t, h), clean(t.title)], 'Check the result' + (group.length > 1 ? ' · ' + group.length + ' versions' : ''),
    h('a', {className:'btn outline sm', href:href(t.id), 'data-key':'result-' + t.id}, 'Check result'));
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
function attentionCard(key, badge, cls, body, meta = '', action = null) {
  return h('section', {className:'card home-card', 'data-key':key, id:key}, h('header', {className:'card-h'}, h('span', {className:'badge ' + cls}, badge), h('span', {className:'grow'}), meta ? h('span', {className:'meta'}, meta) : null, action), body);
}
// "Review all": the cards of the Review page (state.review) in one go. The number is the same set of questions and
// results Home already counts, so it is never added to Home's own total.
function reviewAllButton() {
  // the one number, not the length of the card list; the card count only when the page holds cards the number does not
  const cards = typeof reviewCount === 'function' ? reviewCount() : 0, n = cards ? (typeof needsYouTotal === 'function' && needsYouTotal()) || cards : 0;
  return n && !snapshot ? h('a', {className:'btn ' + (loginWarnings().stopped.length ? 'outline' : 'primary') + ' sm', href:'#review', 'data-key':'review-all'}, 'Review all') : null;
}
// "Hide old": the questions that have waited more than a week go in one click. Same path as a one-click answer:
// the rows leave at once, the toast offers Undo, and only when the Undo window ends is each one answered.
const OLD_QUESTION_MS = 7 * 24 * 3600 * 1000, OLD_QUESTION_ANSWER = 'Dismissed: older than a week';
function oldQuestions() {
  const cutoff = now().getTime() - OLD_QUESTION_MS;
  return needsToday().needs.filter(r => r.ticket && r.answer?.question && r.answer?.digest && !needActs(r).length && Date.parse(r.since) < cutoff);
}
function clearOldButton() {
  const old = snapshot ? [] : oldQuestions();
  if (!old.length) return null;
  const label = 'Dismiss the ' + old.length + (old.length === 1 ? ' question' : ' questions') + ' older than a week';
  const b = h('button', {type:'button', className:'btn quiet sm', title:label, 'aria-label':label, 'data-key':'clear-old'}, 'Hide old');
  b.onclick = () => {
    if (changeUnavailable()) return;
    const rows = oldQuestions();
    if (!rows.length) return;
    rows.forEach(r => pendingAnswers.set(r.id, true));
    let undone = false;
    const timer = setTimeout(async () => {
      if (undone) return;
      let answered = 0, failed = null;
      try {
        for (const r of rows) {
          const result = await act('answer', {ticket:r.ticket, question:r.answer.question, digest:r.answer.digest, answer:OLD_QUESTION_ANSWER});
          if (result.ok) answered++; else failed = failed || result;
        }
        if (failed) window.orch.toast('Cleared ' + answered + ' of ' + rows.length + ' old questions. ' + changeError(failed), 'error');
      } finally {
        rows.forEach(r => pendingAnswers.delete(r.id));
        render();
      }
    }, ANSWER_UNDO_MS);
    window.orch.toast('Cleared ' + rows.length + ' old ' + (rows.length === 1 ? 'question' : 'questions'), 'ok', () => {
      undone = true; clearTimeout(timer); rows.forEach(r => pendingAnswers.delete(r.id)); render();
    });
    render();
  };
  return b;
}
function attentionSummary(groups, failed, results, changes, stuck = [], hidden = 0, questions = null, soon = 0) {
  // the parts before "also" add up to the number in the title (questions + results); what is listed but not counted
  // (notes without a question, changes to put live, logins that run out soon) follows "also", so title,
  // subtitle and rows agree (ORCH-184)
  // questions = every open question (also a same-worded one on two tickets)
  // stuck = the rows of work that stopped (listed first, counted on Home, said with their mark: Stuck or Idle); hidden =
  // results shown as one of them instead
  // a Factory draft ready for Plan the run counts too, as its own part (ORCH-479)
  const drafts = groups.filter(g => isFactoryDraftRow(g.row)).length;
  const questionsAsked = questions ?? needsToday().questions, other = groups.filter(g => !g.row.answer?.question && !isHelperRow(g.row) && !isFactoryDraftRow(g.row)).length + soon;
  const part = (n, one, many) => n ? n + ' ' + (n === 1 ? one : many) : null;
  const idle = stuck.filter(r => r.kind === 'helper:idle').length;
  const counted = [part(stuck.length - idle, 'stuck ticket', 'stuck tickets'), part(idle, 'idle helper', 'idle helpers'), part(failed.length, 'helper that could not start', 'helpers that could not start'), part(questionsAsked, 'question', 'questions'), part(drafts, 'draft to read', 'drafts to read'), part(results - hidden, 'result to check', 'results to check')].filter(Boolean).join(' · ');
  const extra = [part(other, 'thing to look at', 'things to look at'), part(changes, 'change to put live', 'changes to put live')].filter(Boolean).join(' · ');
  return counted && extra ? counted + ' · also ' + extra : counted || extra;
}
function homeSection(key, title, body, count = '', more = null) {
  return h('section', {className:'home-section', 'data-key':key, id:key === 'needs-you' ? key : null},
    h('div', {className:'row between home-section-head'}, h('h2', {}, title, count ? [' ', h('span', {className:'meta'}, String(count))] : null), more), h('div', {className:'card'}, body));
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
// What needs the person today (Home, the Home badge and the Menu count all use this): the parts of the Home subtitle, summed.
function needsToday() {
  const hidden = needsList().filter(r => laterToday(r) || pendingAnswers.has(r.id));
  const live = needsList().filter(r => !laterToday(r) && !pendingAnswers.has(r.id));
  const notices = live.filter(window.DashHelpers.isNotice);
  const needs = live.filter(r => !window.DashHelpers.isNotice(r) && !window.DashHelpers.isBringBack(r));
  const failed = tickets().map(t => [t, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings)]).filter(([t, sf]) => sf && !needs.some(n => n.ticket === t.id));
  const groups = homeNeeds(needs), all = tickets();
  // ORCH-1741: with the core's count, only the tickets whose Check card shows are results to check: one the merge queue
  // holds waits on nobody (one line, queueLine), one with another card (a question, a pull request to merge) is that card
  const checks = Array.isArray(state.counts?.needs_you?.items) ? new Set(state.counts.needs_you.items.filter(i => i && !i.question && !i.stopped && !i.start).map(i => i.ticket)) : null;
  const review = all.filter(t => t.status === 'review' && (!checks || checks.has(t.id)));  // each result to check is one row and one count, like the Review page cards
  const queued = array(state.counts?.needs_you?.queue);
  const changes = all.filter(t => t.bring_back?.state === 'waiting');
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
  const screenRows = window.DashHelpers.helperRows(all, state.runs, state.counts).filter(r => r.state === 'you' && !r.finished && !counted.has(r.ticket.id)), screen = screenRows.length;
  // the open questions the number counts, by ticket (the Review page lists those that have no card of their own)
  const askedItems = core ? core.items : needs.map(r => ({ticket:r.ticket, question:r.answer?.question || r.id}));
  return {needs, notices, failed, groups, review, changes, asked, logins, stuck, unsure, hiddenResults, questions, screen, screenRows, askedItems, queued, fromCore:!!core,
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
function backgroundBanner() {
  const names = stoppedServices().map(s => { const a = addons().find(x => x.name === s.addon); const n = a?.dashboard?.label || s.addon; return n.charAt(0).toUpperCase() + n.slice(1); });
  if (!names.length) return null;
  const list = names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names.at(-1) : names[0];
  return h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, list + (names.length > 1 ? ' are' : ' is') + ' not running. Press Start so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start'));
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
// "What changed": what the helper wrote when work finished (the outcome, else the completion note), newest first; the
// tickets finished today are left out, Finished already shows them with the same words (ORCH-1849).
function doneAt(t) {
  return window.DashHelpers.doneAt(t) || t.created_at || '';
}
function changedWords(t) {
  const o = typeof outcomeOf === 'function' ? outcomeOf(t) : {}, first = String(o.changed || o.why || '').split('\n')[0].trim();
  if (first) return {head:first.length > 110 ? first.slice(0, 107) + '…' : first, detail:o.changed ? o.why || '' : ''};
  const n = typeof completionNotes === 'function' ? completionNotes(t)[0] : null;
  return n ? {head:n.head, detail:n.body} : null;
}
// At most about 3 plain lines per ticket (ORCH-407, report r-1118-0544: whole helper summaries with commit ids, file
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
function changedList(items, limit = 5) {
  return items.filter(t => t.status === 'done').map(t => ({t, words:changedWords(t)})).filter(x => x.words)
    .sort((a, b) => (Date.parse(doneAt(b.t)) || 0) - (Date.parse(doneAt(a.t)) || 0)).slice(0, limit);
}
function whatChangedCard(list) {
  if (!list.length) return null;
  return h('section', {className:'card home-card what-changed', 'data-key':'what-changed'},
    h('div', {className:'card-h row between'}, h('h2', {}, 'What changed'), h('a', {className:'btn ghost sm', href:'#tickets?view=done-week'}, 'Done tickets →')),
    list.map(({t, words}) => h('a', {className:'home-note', href:href(t.id), 'data-key':'changed-' + t.id},
      h('div', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(t, h), clean(t.title)), h('p', {className:'muted'}, plainChanged(changedText(words)))),
      h('span', {className:'meta'}, [typeof ticketDoneEvent === 'function' && typeof ticketActor === 'function' ? ticketActor(ticketDoneEvent(t)?.by) : '', time(doneAt(t))].filter(Boolean).join(' · ')))));
}
// "Finished" on Home: the 5 newest finished today, each with its result, then one link to all of them in the Tickets list
// (report r-1116-2215-ws: 60 rows made Home 8000 px tall). `doneLink`: no "What changed" card below (every result is
// from today), so this card keeps the way to the done tickets.
const FINISHED_SHOWN = 5;
function finishedBody(finished, all, doneLink = false) {
  const older = doneLink && all.some(t => t.status === 'done') ? h('div', {className:'card-row', 'data-key':'finished-done'},
    h('a', {className:'btn ghost sm', href:'#tickets?view=done-week'}, 'Done tickets →')) : null;
  if (!finished.length) return [emptyRow(lastFinished(all) ? 'Nothing finished today. ' + lastFinished(all) : 'Nothing finished yet.'), older];
  const newest = finished.slice().sort((a, b) => (finishedAt(b) || 0) - (finishedAt(a) || 0));
  const more = newest.length > FINISHED_SHOWN ? h('div', {className:'card-row', 'data-key':'finished-all'},
    h('a', {className:'btn ghost sm', href:'#tickets?view=done-today'}, 'All finished today (' + newest.length + ') →')) : older;
  return [...newest.slice(0, FINISHED_SHOWN).map(ticketRow), more];
}
// The day the last finished ticket was closed, for the empty "Finished" card ("Last: “…”, Fri.").
function lastFinished(all) {
  const t = all.filter(x => x.status === 'done' && finishedAt(x)).sort((a, b) => finishedAt(b) - finishedAt(a))[0];
  return t ? 'Last: “' + clean(t.title) + '”, ' + finishedAt(t).toLocaleDateString('en-GB', {weekday:'short'}) + '.' : '';
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
function loginBanner(stopped) {
  if (!stopped.length) return null;
  const list = window.DashHelpers.needTickets(stopped), n = list.length, noNew = stopped.some(i => i.chosen && i.state === 'renew');
  const lead = n ? 'Helpers stopped on ' + n + (n === 1 ? ' ticket' : ' tickets') + (noNew ? ' and start no new work' : '') : noNew ? 'Helpers start no new work' : '';
  if (stopped.length === 1) {
    const item = stopped[0], name = clean(window.DashHelpers.needName(item));
    return h('div', {className:'banner error', role:'alert', 'data-key':'login-stopped', 'data-login':'stopped'},
      h('div', {className:'grow'}, h('strong', {}, 'The ' + name + (item.state === 'unreachable' ? ' cannot be reached' : ' stopped working')),
        lead ? h('p', {}, lead + (n ? ': ' : '.'), n ? loginTicketLinks(list) : null) : null, loginHow(item)),
      loginAction(item, 'login-stopped-' + item.name));
  }
  const names = stopped.map(i => clean(window.DashHelpers.needName(i))).join(' · ');
  return h('div', {className:'banner error', role:'alert', 'data-key':'login-stopped', 'data-login':'several'},
    h('div', {className:'grow'}, h('strong', {}, stopped.length + ' things stopped working'), h('p', {}, (lead ? lead + '. ' : '') + names + '.')),
    snapshot ? null : h('a', {className:'btn primary sm', href:'#settings/agent', 'data-key':'login-see'}, 'See what to fix'));
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
// Home: what needs the person first, as ONE list: the oldest question with its answers, then one row per further
// question, result to check and change to put live (one button each); the notes that need no answer are one quiet line.
function home() {
  // Work that stopped (stuck tickets, a pull request left open, an idle helper) is listed first and is part of THE number
  const {needs, notices, failed, groups:groupedNeeds, review, changes, logins, stuck, unsure, hiddenResults, questions, queued, count:needCount} = needsToday(), all = tickets();
  const working = sorted(all.filter(t => shown(t).status === 'active' && !needs.some(n => n.ticket === t.id)));
  // a ticket waiting for review is the person's "Check result" row, never an idle helper with Stop (ORCH-407); its
  // left-over session is closed by orch run tend (the core's count leaves it out the same way, ORCH-476)
  const helpers = window.DashHelpers.helperRows(all, state.runs, state.counts).filter(r => !(r.ticket.status === 'review' && ['idle', 'stuck'].includes(r.state)));
  // a ticket is in one box only: one with a helper row stays in Helpers, never also in Quiet (report r-1124-0536)
  const helperIds = new Set(helpers.map(r => r.ticket.id));
  const quiet = working.filter(t => t.quiet_since && !helperIds.has(t.id));
  const results = resultGroups(review);
  const finished = all.filter(t => t.status === 'done' && finishedAt(t)?.toDateString() === now().toDateString());
  const newest = needs.slice().sort((a,b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const banner = [loginBanner(logins.stopped), lineBanner(), typeof browseAskBanner === 'function' ? browseAskBanner() : null, backgroundBanner(), updateCheckCard(), autoUpdateNote()];
  // each finished ticket once (ORCH-1849): today's with their result in Finished, the earlier results in What changed
  const changedCard = whatChangedCard(changedList(all.filter(t => !finished.includes(t)))), doneLink = !changedCard;
  // The number counts open questions, results to check, work that stopped and failed starts; the list below also holds
  // changes to put live and add-on rows, so it shows whenever it has anything, with or without a number.
  const anyNeeds = groupedNeeds.length + failed.length + review.length + changes.length + logins.soon.length > 0;
  // a login that stopped working needs the person too: it counts in the title (never "Nothing needs you" / "All clear")
  // ORCH-1616 (owner, less noise): the needs-you number shows in one place, the Review badge of the menu; the heading,
  // the card and Review all never repeat it (the line under the heading still says what kinds wait)
  const title = needCount || anyNeeds || logins.stopped.length ? 'Things to look at' : 'Nothing needs you';
  const today = now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'});
  // ORCH-1616 (owner): the number lives only on the Review badge, so the line under the heading is the date alone
  const head = heading(title, today, {
    // ORCH-1698: the top bar (and its New ticket) is hidden under the phone tabs, so Home offers it itself on a phone
    actions:fragment(snapshot ? null : h('button', {type:'button', className:'btn outline sm phone-only', 'data-action':'new', 'data-key':'new-ticket-phone'}, 'New ticket'),
      h('a', {className:'btn ghost sm', href:'#tickets', 'data-key':'all-tickets'}, 'All ' + all.length + (all.length === 1 ? ' ticket →' : ' tickets →')))});
  const notes = [...(notices.length ? [notesLine(notices), ...(notesOpen ? notices.map(row => needRow(row, newest)) : [])] : []), queueLine(queued)].filter(Boolean);
  if (!anyNeeds && !working.length && !helpers.length) {
    return fragment(head, banner, logins.stopped.length ? null : h('section', {className:'empty-workspace', 'data-key':'empty'}, h('h2', {}, 'All clear'),
      h('p', {}, 'Questions and results to check will appear here.'), typeof newButton === 'function' ? newButton() : null),
      notes.length ? h('section', {className:'card home-card', 'data-key':'needs-notes-card'}, notes) : null,
      card('finished-today', 'Finished', '', finishedBody(finished, all, doneLink)), changedCard);
  }
  const first = groupedNeeds.slice().sort((a, b) => (Date.parse(a.row.since) || Infinity) - (Date.parse(b.row.since) || Infinity))
    .find(g => g.row.answer?.question && array(g.row.answer.options).length && !needActs(g.row).length && !needCardQuestion(g.row));
  // data-counts on every row of the list: how much of THE number it carries (its questions, its results, 1 for work
  // that stopped; 0 for a row that is shown but not counted), so the rows always add up to the title (the browser
  // check sums them, ORCH-476)
  const weigh = (el, n) => { if (el && el.setAttribute) el.setAttribute('data-counts', String(n)); return el; };
  const further = groupedNeeds.filter(g => g !== first && !isHelperRow(g.row)).map(g => { const {row, count, same} = g; return weigh(needCardQuestion(row) ? (needCardQuestion(row).card.kind === 'run' && needCardQuestion(row).card.run ? runCardRow(row) : cardSetRow(row)) : needActs(row).length || isHelperRow(row) || isFactoryDraftRow(row) || (!row.ticket && array(row.answer?.options).length) ? needRow(row, newest, count, same) : needListRow(row, count, same), g.asked); });
  const list = [...stuck.map(g => weigh(needRow(g.row, newest, g.count, g.same), 1)), first ? weigh(needRow(first.row, newest, first.count, first.same), first.asked) : null, ...logins.soon.map(r => weigh(loginSoonRow(r), 0)), ...further, ...failed.map(([t, sf]) => weigh(startFailedRow(t, sf), 1)),
    ...results.map(g => g.filter(t => !unsure.has(t.id))).filter(g => g.length).map(g => weigh(resultRow(g), g.length)), ...changes.map(t => weigh(changeRow(t), 0)), ...notes];
  const helpersEl = helpers.length && window.UI?.helperList ? helpersCard(helpers) : snapshot && working.length ? card('working-now', 'Working now', String(working.length), working.slice(0, 5).map(workingRow)) : null;
  // ORCH-1643: with no Needs you card (only helpers that wait on their screen, shown in Helpers) the helpers take the
  // wide column, so the left half is never empty next to them
  const lead = anyNeeds ? attentionCard('needs-you', 'Needs you', 'needs', list, '', [clearOldButton(), reviewAllButton()]) : helpersEl;
  return fragment(head, banner,
    h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'}, lead),
    h('aside', {className:'stack', 'data-key':'right'},
      anyNeeds ? helpersEl : null,
      quiet.length ? card('quiet-now', 'Quiet', String(quiet.length), quiet.slice(0, 5).map(quietRow)) : null,
      card('finished-today', 'Finished', '', finishedBody(finished, all, doneLink)))),
    changedCard);
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
  connectionEl.replaceChildren(h('div', {className:'grow'}, h('h3', {}, words[0]), h('p', {}, words[1])),
    kind === 'slow' ? null : button('Try again', 'outline sm', () => refresh()));
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
