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
  return h('div', {className:'row ticket-title'}, h('h3', {className:'grow'}, h('a', {href:href(t.id)}, clean(t.title))), tail);
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
// `same`: rows on other tickets asking the identical question with the same choices; one answer goes to all of them.
function needRow(row, newest, questionCount = 1, same = []) {
  const key = 'need-' + row.id;
  if (needActs(row).length) return needActionsRow(row, key);
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row);
  const options = array(row.answer?.options);
  let actions = null;
  if (!snapshot && options.length) {
    actions = h('div', {className:'row answer-options'}, options.map(option => {
      const control = button(option + (option === row.answer.recommended ? ' · Suggested' : ''), 'outline sm', async event => {
        if (changeUnavailable() || locks.has(key)) return;
        const host = event.currentTarget.closest('[data-need-row]');
        locks.add(key);
        host.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
          let answered = 0, failed = null;
          for (const r of [row, ...same]) {
            const result = await act('answer', {ticket:r.ticket, question:r.answer.question, digest:r.answer.digest, answer:option});
            if (result.ok) answered++; else failed = failed || result;
          }
          const total = same.length + 1;
          window.orch.toast(failed ? (answered ? 'Answered on ' + answered + ' of ' + total + ' tickets. ' : '') + changeError(failed) : same.length ? 'Answered on ' + answered + ' tickets' : 'Answered', failed ? 'error' : 'ok');
        } finally {
          locks.delete(key);
          host.querySelectorAll('button').forEach(b => { b.disabled = false; });
          render();
        }
      });
      control.dataset.key = key + '-option-' + option;
      return control;
    }));
  } else if (!snapshot) {
    actions = h('button', {type:'button', className:'btn outline sm', 'data-action':'need', 'data-need':row.id}, choice.label);
  }
  const question = needQuestion(row);
  return h('div', {className:'card-row home-need', 'data-key':key, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null},
    t ? ticketTitle(t) : h('h3', {}, clean(row.title)),
    same.length ? h('p', {className:'meta', 'data-key':key + '-same'}, 'Asked on ' + (same.length + 1) + ' tickets – answer once') : null,
    questionCount > 1 ? h('p', {className:'meta'}, questionCount + ' questions') : null, h('p', {}, clean(window.DashHelpers.plainWhy(question, 'The helper'))),
    actions, t ? parentLine(t) : null);
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
const laterToday = row => array(row.actions).some(a => a && a.later) && needsLater()[row.id] === today();
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
function workingRow(t) {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const claim = state.runs?.[t.id]?.claim, task = tasks.find(task => !window.DashHelpers.resolved(task));
  return h('div', {className:'card-row home-work', 'data-key':'ticket-' + t.id}, ticketTitle(t),
    task ? h('p', {}, clean(task.text || task.title)) : null,
    h('p', {className:'meta'}, [window.DashHelpers.agentLabel ? window.DashHelpers.agentLabel(state.settings, claim) : capitalise(name(claim?.label || claim?.agent || t.owner)), age(claim?.started_at)].filter(Boolean).join(' · ')),
    tasks.length ? h('div', {className:'segments', role:'progressbar', 'aria-label':'Tasks done', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done}, tasks.map(task => h('span', {className:window.DashHelpers.resolved(task) ? 'complete' : ''}))) : null,
    h('div', {className:'row'}, h('span', {className:'meta grow'}, done + ' of ' + tasks.length + ' tasks done'), h('a', {className:'btn ghost sm', href:href(t.id)}, 'Watch →')));
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
function resultRow(group) {
  const t = group[group.length - 1], older = group.slice(0, -1);
  return h('div', {className:'card-row home-result', 'data-key':'ticket-' + t.id},
    h('a', {className:'result-link', href:href(t.id)}, h('span', {className:'grow'}, clean(t.title)), older.length ? h('span', {className:'meta'}, group.length + ' versions') : null, h('span', {className:'chevron', 'aria-hidden':'true'}, '›')),
    older.length && !snapshot ? h('div', {className:'row'}, button('Mark older as done', 'ghost sm', async event => {
      const lock = 'older-' + t.id, control = event?.currentTarget;
      if (locks.has(lock)) return;
      locks.add(lock);
      if (control) control.disabled = true;
      // one at a time, so the moves (and their Undo) do not race each other
      try { for (const o of older) await moveTicket(o.id, 'done'); }
      finally { locks.delete(lock); if (control) control.disabled = false; }
    })) : null);
}
function homeSection(key, title, body) {
  return h('section', {className:'home-section', 'data-key':key, id:key === 'needs-you' ? key : null}, h('h2', {}, title), h('div', {className:'card'}, body));
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
let needsOpen = false;
// Three or more items fold: the oldest question shows as a full card with its answers, then "N more questions".
function needsFold(groups, failed, newest) {
  const oldest = groups.slice().sort((a, b) => (Date.parse(a.row.since) || Infinity) - (Date.parse(b.row.since) || Infinity))[0];
  const first = oldest ? needRow(oldest.row, newest, oldest.count, oldest.same) : failed.length ? startFailedRow(...failed[0]) : null;
  const more = groups.length + failed.length - 1; // stacked identical questions count once
  return [first, h('div', {className:'card-row needs-fold', 'data-key':'needs-fold'}, button(more + (more === 1 ? ' more question' : ' more questions'), 'outline sm', () => { needsOpen = true; render(); }))];
}
// What needs the person today (Home, the Home badge and the Menu count all use this).
function needsToday() {
  const needs = needsList().filter(r => !laterToday(r));
  const failed = tickets().map(t => [t, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings)]).filter(([t, sf]) => sf && !needs.some(n => n.ticket === t.id));
  return {needs, failed, count:window.DashHelpers.needsYouCount(needs, failed)};
}
function home() {
  const {needs, failed, count:needCount} = needsToday(), groupedNeeds = homeNeeds(needs), all = tickets();
  const rowsShown = groupedNeeds.length + failed.length; // stacked identical questions are one row
  if (rowsShown < 3) needsOpen = false;
  const working = sorted(all.filter(t => shown(t).status === 'active' && !needs.some(n => n.ticket === t.id)));
  const review = all.filter(t => t.status === 'review' && !needs.some(n => n.ticket === t.id)), results = resultGroups(review);
  const finished = all.filter(t => t.status === 'done' && finishedAt(t)?.toDateString() === now().toDateString());
  const newest = needs.slice().sort((a,b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const hour = now().getHours();
  const stopped = array(state.services).some(s => s.running === false);
  const banner = stopped ? h('div', {className:'banner attn', 'data-key':'background'}, h('p', {className:'grow'}, 'Background work is not running. Start it so repeating work and checks can run.'), snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start')) : null;
  return fragment(heading('Good ' + (hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'), now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'})), banner,
    h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
      homeSection('needs-you', 'Needs you (' + needCount + ')', rowsShown >= 3 && !needsOpen ? needsFold(groupedNeeds, failed, newest) : needCount ? [...groupedNeeds.map(({row, count, same}) => needRow(row, newest, count, same)), ...failed.map(([t, sf]) => startFailedRow(t, sf)), rowsShown >= 3 ? h('div', {className:'card-row', 'data-key':'needs-hide'}, button('Hide', 'ghost sm', () => { needsOpen = false; render(); })) : null] : emptyRow('Nothing needs you right now.')),
      working.length ? homeSection('working-now', 'Working now', working.map(workingRow)) : null,
      homeSection('check-result', 'Check result (' + review.length + ')', results.length ? [...results.slice(0, 3).map(resultRow),
        results.length > 3 ? h('div', {className:'card-row', 'data-key':'results-all'}, h('a', {className:'btn ghost sm', href:'#tickets'}, 'Show all (' + review.length + ')')) : null] : emptyRow('No results to check.')),
      h('a', {className:'see-all', href:'#tickets', 'data-key':'everything-else'}, 'See all tickets (' + all.length + ')')),
    h('aside', {className:'stack', 'data-key':'right'},
      card('finished-today', 'Finished today', '', finished.length ? finished.map(ticketRow) : emptyRow('Nothing finished today yet.')))));
}
function loadingView() {
  const shape = kind => h('div', {className:'card skeleton-card ' + kind, 'aria-hidden':'true'}, h('div', {className:'skeleton-line'}), h('div', {className:'skeleton-line short'}), h('div', {className:'skeleton-line'}));
  return h('div', {className:'loading-home', 'data-key':'loading', 'aria-busy':'true'}, h('p', {role:'status'}, 'Loading your workspace…'),
    h('div', {className:'skeleton-heading', 'aria-hidden':'true'}), h('div', {className:'columns'}, h('div', {className:'stack'}, shape('question'), shape('work'), shape('result')), h('aside', {className:'stack'}, shape('message'), shape('finished'))));
}
function connectionNotice(connectionEl, hadState) {
  connectionEl.replaceChildren(h('p', {className:'grow'}, hadState ? "Can't reach orch. Showing the last update, trying again every few seconds." : "Can't reach orch yet. Trying again shortly."),
    button('Try now', 'outline sm', () => refresh()), h('details', {}, h('summary', {}, 'Details'), h('p', {}, 'Is the computer asleep? orch runs on the computer that owns this workspace. Wake it up and check that it is connected. This page will try again shortly.')));
  connectionEl.hidden = false;
}
// Chat (former General) lives in pages/chat.js.
