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
// `same`: rows on other tickets asking the identical question with the same choices; one answer goes to all of them.
function needRow(row, newest, questionCount = 1, same = []) {
  const key = 'need-' + row.id;
  if (needActs(row).length) return needActionsRow(row, key);
  if (!row.ticket && array(row.answer?.options).length) return needNoticeRow(row, key);
  const t = ticketOf(row.ticket), choice = window.DashHelpers.needAction(row);
  const options = array(row.answer?.options);
  let actions = null, other = null;
  if (!snapshot && options.length) {
    const answer = async (option, event) => {
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
  return h('div', {className:'card-row home-need', 'data-key':key, 'data-need-row':row.id, 'data-newest':row.id === newest ? '' : null},
    h('h2', {className:'question-title'}, clean(source && String(question).trim().toLowerCase() === String(row.source).toLowerCase() ? source : window.DashHelpers.plainWhy(question, 'The helper'))),
    h('p', {className:'meta question-context'}, asked + ' asked' + (when ? ' ' + when : ''),
      t ? [' on ‘' + clean(t.title) + '’ · ', h('a', {href:href(t.id)}, 'Open ticket')] : null, typeof titleTag === 'function' && t ? titleTag(t) : null),
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
function workingRow(t) {
  const tasks = array(t.checklist), done = tasks.filter(window.DashHelpers.resolved).length;
  const claim = state.runs?.[t.id]?.claim, task = tasks.find(task => !window.DashHelpers.resolved(task));
  const who = window.DashHelpers.agentLabel ? window.DashHelpers.agentLabel(state.settings, claim) : capitalise(name(claim?.label || claim?.agent || t.owner));
  return h('a', {className:'working-row', href:href(t.id), 'data-key':'ticket-' + t.id},
    h('span', {className:'avatar', 'aria-hidden':'true'}, String(who || 'H').slice(0, 1).toUpperCase()),
    h('span', {className:'grow'}, h('strong', {}, clean(t.title)), task ? h('span', {className:'meta'}, clean(task.text || task.title)) : null),
    h('span', {className:'working-progress'},
      tasks.length ? h('span', {className:'segments', role:'progressbar', 'aria-label':'Steps done', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done}, tasks.map(task => h('span', {className:window.DashHelpers.resolved(task) ? 'complete' : ''}))) : null,
      tasks.length ? h('span', {className:'meta'}, done + ' of ' + tasks.length + ' steps') : null,
      h('span', {className:'meta'}, [who, typeof age === 'function' ? age(claim?.started_at) : ''].filter(Boolean).join(' · '))));
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
// A small preview of the newest result file (what the product knows: its name and size); "Preview →" opens the viewer.
// No file known for the ticket: no thumbnail.
function resultPreview(t) {
  if (snapshot || typeof artifactFiles !== 'function' || typeof previewFile !== 'function') return null;
  if (typeof loadArtifacts === 'function') loadArtifacts(t, false);
  const file = artifactFiles(t)[0];
  if (!file?.name) return null;
  const base = file.name.split('/').pop(), label = clean(window.DashHelpers.plainFileName?.(file.name) || base);
  const image = typeof PREVIEW_EXT === 'object' && PREVIEW_EXT.image.test(file.name);
  const src = '/api/file?t=' + encodeURIComponent(t.id) + '&k=artifacts&n=' + encodeURIComponent(file.name);
  const thumb = h('span', {className:'preview-thumbnail', 'aria-hidden':'true'},
    image ? h('img', {src, alt:'', loading:'lazy'}) : [h('span', {}, (base.split('.').pop() || 'file').slice(0, 4).toUpperCase()), h('i', {}), h('i', {}), h('i', {})]);
  const open = h('button', {type:'button', className:'inline-preview', 'data-key':'preview-' + t.id, 'aria-label':'Preview ' + label},
    '▤ ' + label + (Number(file.size) >= 0 && typeof sizeText === 'function' ? ' · ' + sizeText(Number(file.size)) : ''), h('span', {}, 'Preview →'));
  open.onclick = () => previewFile(t.id, 'artifacts', file.name);
  return {thumb, open};
}
function resultRow(group) {
  const t = group[group.length - 1], older = group.slice(0, -1), preview = resultPreview(t);
  return h('div', {className:'card-row home-result', 'data-key':'ticket-' + t.id}, preview ? preview.thumb : null,
    h('div', {className:'grow'},
      h('h3', {className:'result-link'}, h('span', {className:'grow'}, clean(t.title)), older.length ? h('span', {className:'meta'}, group.length + ' versions') : null),
      preview ? preview.open : null),
    h('a', {className:'btn outline sm', href:href(t.id), 'data-key':'check-' + t.id}, 'Check result'),
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
// Changes a helper made in its own copy, waiting to be added to the person's files (the signed copies.approve path).
function changeRow(t) {
  const add = !snapshot && t.bring_back?.tip && typeof ticketBringBackDialog === 'function'
    ? h('button', {type:'button', className:'btn outline sm', 'data-key':'add-files-' + t.id}, 'Add to my files') : null;
  if (add) add.onclick = () => ticketBringBackDialog(t);
  return h('div', {className:'card-row home-change', 'data-key':'change-' + t.id}, h('span', {className:'badge needs'}, '↗ Changes to add'),
    h('div', {className:'grow'}, h('h3', {}, 'Add the changes from ‘' + clean(t.title) + '’ to your files?'), h('a', {className:'meta', href:href(t.id)}, 'See what changed')), add);
}
function attentionCard(key, badge, cls, body, meta = '') {
  return h('section', {className:'card home-card', 'data-key':key, id:key}, h('header', {className:'card-h'}, h('span', {className:'badge ' + cls}, badge), h('span', {className:'grow'}), meta ? h('span', {className:'meta'}, meta) : null), body);
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
let needsOpen = false;
// Three or more items fold: the oldest question shows as a full card with its answers, then "N more questions".
function needsFold(groups, failed, newest) {
  const oldest = groups.slice().sort((a, b) => (Date.parse(a.row.since) || Infinity) - (Date.parse(b.row.since) || Infinity))[0];
  const first = oldest ? needRow(oldest.row, newest, oldest.count, oldest.same) : failed.length ? startFailedRow(...failed[0]) : null;
  const more = groups.length + failed.length - 1; // stacked identical questions count once
  return [first, h('div', {className:'card-row needs-fold', 'data-key':'needs-fold'}, button(more + (more === 1 ? ' more question' : ' more questions'), 'outline sm', () => { needsOpen = true; render(); }))];
}
// What needs the person today (Home, the Home badge and the Menu count all use this): the parts of the Home subtitle, summed.
function needsToday() {
  const needs = needsList().filter(r => !laterToday(r));
  const failed = tickets().map(t => [t, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings)]).filter(([t, sf]) => sf && !needs.some(n => n.ticket === t.id));
  const groups = homeNeeds(needs), all = tickets();
  const review = all.filter(t => t.status === 'review' && !needs.some(n => n.ticket === t.id));
  const changes = all.filter(t => t.bring_back?.state === 'waiting');
  const asked = groups.length + failed.length;
  return {needs, failed, groups, review, changes, asked, count:asked + review.length + changes.length};
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
// Home: what needs the person first, in order: questions, results to check, changes to add, then what is working.
function home() {
  const {needs, failed, groups:groupedNeeds, review, changes, asked, count:needCount} = needsToday(), all = tickets();
  const rowsShown = groupedNeeds.length + failed.length; // stacked identical questions are one row
  if (rowsShown < 3) needsOpen = false;
  const working = sorted(all.filter(t => shown(t).status === 'active' && !needs.some(n => n.ticket === t.id)));
  const results = resultGroups(review);
  const finished = all.filter(t => t.status === 'done' && finishedAt(t)?.toDateString() === now().toDateString());
  const newest = needs.slice().sort((a,b) => (Date.parse(b.since) || 0) - (Date.parse(a.since) || 0))[0]?.id;
  const banner = backgroundBanner();
  const title = needCount ? needCount + (needCount === 1 ? ' thing needs you' : ' things need you') : 'Nothing needs you';
  const head = heading(title, attentionSummary(groupedNeeds, failed, review.length, changes.length), {
    eyebrow:now().toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}),
    actions:h('a', {className:'btn ghost sm', href:'#tickets', 'data-key':'all-tickets'}, 'All ' + all.length + (all.length === 1 ? ' ticket →' : ' tickets →'))});
  const finishedCard = card('finished-today', 'Finished today', finished.length ? String(finished.length) : '', finished.length ? finished.map(ticketRow) : emptyRow('Nothing finished today yet.'));
  if (!needCount && !results.length && !changes.length && !working.length) {
    return fragment(head, banner, h('section', {className:'empty-workspace', 'data-key':'empty'}, h('h2', {}, 'All clear'),
      h('p', {}, 'Questions and results to check will appear here.'), typeof newButton === 'function' ? newButton() : null), finishedCard);
  }
  const allQuestions = !failed.length && groupedNeeds.every(g => g.row.answer?.question && !needActs(g.row).length);
  const needsBody = rowsShown >= 3 && !needsOpen ? needsFold(groupedNeeds, failed, newest) : [...groupedNeeds.map(({row, count, same}) => needRow(row, newest, count, same)), ...failed.map(([t, sf]) => startFailedRow(t, sf)), rowsShown >= 3 ? h('div', {className:'card-row', 'data-key':'needs-hide'}, button('Hide', 'ghost sm', () => { needsOpen = false; render(); })) : null];
  return fragment(head, banner,
    h('div', {className:'columns home-columns', 'data-key':'columns'}, h('div', {className:'stack', 'data-key':'left'},
      asked ? attentionCard('needs-you', (allQuestions ? '! Question · ' : '! Needs you · ') + asked, 'needs', needsBody, groupedNeeds.length ? whoAsked(ticketOf(groupedNeeds[0].row.ticket)) : '') : null,
      results.length ? attentionCard('check-result', '◇ Check · ' + review.length, 'review', [...results.slice(0, 3).map(resultRow),
        results.length > 3 ? h('div', {className:'card-row', 'data-key':'results-all'}, h('a', {className:'btn ghost sm', href:'#tickets'}, 'Show all (' + review.length + ')')) : null], (() => {
        const newestResult = results[0][results[0].length - 1], at = finishedAt(newestResult) || parse(newestResult.updated_at);
        return [whoAsked(newestResult), at ? time(at) : ''].filter(Boolean).join(' · ');
      })()) : null,
      changes.length ? h('section', {className:'card home-card home-changes', 'data-key':'changes', id:'changes'}, changes.map(changeRow)) : null,
      working.length ? homeSection('working-now', 'Working now', working.map(workingRow), working.length, h('a', {className:'btn ghost xs', href:'#tickets?view=working', 'data-key':'working-all'}, 'View all →')) : null),
    h('aside', {className:'stack', 'data-key':'right'}, finishedCard,
      h('p', {className:'quiet-note', 'data-key':'finished-note'}, 'Finished work stays in Tickets. ', h('a', {href:'#tickets'}, 'See finished tickets →')))));
}
function connectionNotice(connectionEl, hadState) {
  connectionEl.replaceChildren(h('div', {className:'grow'}, h('h3', {}, "Can’t reach the workspace"),
    h('p', {}, hadState ? 'Showing the last saved view. Changes are unavailable until you reconnect.' : 'Reconnect to load your workspace. Your data has not been changed.')),
    button('Try again', 'outline sm', () => refresh()));
  connectionEl.hidden = false;
}
// Chat (former General) lives in pages/chat.js.
