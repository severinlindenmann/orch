'use strict';
// Review (#review): everything that waits for a decision, one card at a time (the kit's UI.reviewPage), with the
// "All cards" list beside it on a wide screen. The cards and the decisions come with the state (state.review, from
// `orch review list`); an answer is a plain click (op review.answer).
const REVIEW_ID = /^core:(?:q:(t_[a-z0-9]{6,16}):(q[0-9]{1,4})|review:(t_[a-z0-9]{6,16}))$/;
// ORCH-524: a Check result's file as the ticket lists it (its time and size, when known here), so its link names
// its version and the browser keeps the picture; unknown: a plain link that asks again by content hash.
function reviewFileStamp(tid, kind, name) {
  const t = array(state?.tickets).find(x => x?.id === tid);
  if (!t || !window.FileViewer?.stampOf || typeof evidenceFile !== 'function' || typeof allArtifactFiles !== 'function') return '';
  const files = kind === 'evidence' ? array(t.checklist).flatMap(task => array(task.evidence).map(ev => evidenceFile(t, ev)).filter(Boolean)) : allArtifactFiles(t);
  const stamp = window.FileViewer.stampOf(files.find(file => file.name === name));
  return stamp ? '&v=' + encodeURIComponent(stamp) : '';
}
function reviewCards() { return [...reviewStuckCards(), ...array(state?.review?.cards).map(reviewPlainCard)]; }
// ORCH-1108 (owner's pick on ORCH-1102): work that stopped (Home's rows: a pull request left open, an idle helper, checks
// that keep failing, a helper waiting for an OK on its screen, a ticket the Reviewer was not sure about) is a card here
// too, first in line as on Home, so THE number and the Waiting cards are the same count. The same rows as needsToday()
// stuck; a ticket the Reviewer was not sure about that waits in Check is its Check card (counted once, as on Home).
// Its buttons are Home's (helperRow): Merge and Nudge, or Nudge and Start fresh, or none; Open goes to the ticket.
const STUCK_CARD = /^stuck:(.{1,200})$/;
function reviewStuckRows() {
  if (!state || typeof needsToday !== 'function') return [];
  return needsToday().stuck.map(g => g.row).filter(row => !(row.kind === 'reviewer:unsure' && ticketOf(row.ticket)?.status === 'review'));
}
function reviewStuckAnswers(row) {
  if (row.kind === 'helper:permission' || row.kind === 'reviewer:unsure') return [];  // the answer is on the ticket page: Open
  if (row.kind === 'helper:unmerged') return [{label:'Merge', picked:'merge'}, {label:state.runs?.[row.ticket]?.running === true ? 'Nudge' : 'Start helper', picked:'nudge'}];
  return [{label:'Nudge', picked:'nudge'}, {label:'Start fresh', picked:'fresh'}];
}
// A button pressed on a stuck card does not end the stopped work (Home keeps its row too): the card comes back in
// Waiting with what was done and when, so the number and the cards stay the same count. Kept per page.
const reviewStuckDone = new Map();  // card id -> {word, at, stop}: stop = the stop it was pressed on (a later stop starts clean)
const reviewStuckBusy = new Set();  // card ids whose button is running now: a second press waits for nothing and does nothing
const STUCK_WORDS = {merge:'Merged', nudge:'Message sent', start:'Helper started', fresh:'Helper started fresh'};
const reviewStuckStop = row => [row.kind, row.since || '', row.pull?.head || ''].join('@');
function reviewStuckDoneOf(row) {
  const done = reviewStuckDone.get('stuck:' + row.id);
  return done && done.stop === reviewStuckStop(row) ? done : null;
}
function reviewStuckDigest(row) {
  const done = reviewStuckDoneOf(row);
  return reviewStuckStop(row) + '@' + (done ? done.at : '');
}
function reviewStuckCards() {
  if (snapshot) return [];
  return reviewStuckRows().map(row => {
    const t = ticketOf(row.ticket), id = 'stuck:' + row.id, done = reviewStuckDoneOf(row);
    const title = clean(t?.title || row.title || ''), about = reviewStuckAbout(t), step = reviewStuckStep(t);
    const why = [done ? done.word + ' ' + time(new Date(done.at).toISOString()) + '.' : '', step].filter(Boolean).join(' ');
    return {id, ticket:row.ticket, ticket_key:typeof t?.key === 'string' && t.key ? t.key : row.ticket, ticket_title:title,
      key:'stuck', since:row.since, digest:reviewStuckDigest(row), href:'#ticket/' + encodeURIComponent(row.ticket),
      text:clean(row.text), ...(about ? {about} : {}),
      card:{kind:'stuck', title:title || clean(row.text), hint:reviewStuckHint(row), ...(why ? {why} : {})}, answers:reviewStuckAnswers(row)};
  });
}
// The context the owner asked for (ORCH-1108 q1, "not enough context what it is about"): the ticket's name as the card's
// title, what was asked in one line (About), the step it stopped on, and what each button does.
function reviewStuckAbout(t) {
  const first = String(t?.description || '').split(/\n/).map(s => s.trim()).find(Boolean) || '';
  const line = clean(first);
  return line.length > 160 ? line.slice(0, 157).replace(/\s+\S*$/, '') + '…' : line;
}
function reviewStuckStep(t) {
  const tasks = array(t?.checklist).filter(task => !task.wont_do);
  if (!tasks.length) return '';
  const done = tasks.filter(task => task.done).length, open = tasks.find(task => !task.done);
  return (open ? 'Stopped at: ' + clean(open.text || open.title || '') + ' · ' : '') + done + ' of ' + tasks.length + ' steps done.';
}
function reviewStuckHint(row) {
  if (row.kind === 'helper:permission') return 'Open the ticket to see what the helper asks and answer it there.';
  if (row.kind === 'reviewer:unsure') return 'Open the ticket to check the result yourself.';
  if (row.kind === 'helper:unmerged') return 'Merge puts the pull request in. ' + (state.runs?.[row.ticket]?.running === true ? 'Nudge asks' : 'Start helper starts a helper that asks') + ' it to merge or say why it stays open.';
  return 'Nudge asks the helper to go on with the next step. Start fresh stops it and starts a new helper on this ticket.';
}
async function reviewStuckAnswer(id, digest, picked) {
  const m = STUCK_CARD.exec(String(id || '')), row = m && reviewStuckRows().find(r => r.id === m[1]);
  if (!row) return {ok:false, error:{code:'decided', message:'This is not stuck any more.'}};
  // the card as it was shown: a newer commit or a newer stop is a new card, never merged or nudged unseen
  if (digest !== reviewStuckDigest(row)) return {ok:false, error:{code:'changed', message:'This card changed.'}};
  if (reviewStuckBusy.has(id)) return {ok:false, error:{code:'busy', message:'That button is already running.'}};
  reviewStuckBusy.add(id);
  try { return await reviewStuckRun(id, row, picked); } finally { reviewStuckBusy.delete(id); }
}
async function reviewStuckRun(id, row, picked) {
  const pull = row.pull || {}, running = state.runs?.[row.ticket]?.running === true;
  const r = picked === 'merge' && row.kind === 'helper:unmerged' ? await act('pull.merge', {ticket:row.ticket, url:pull.url, head:pull.head})
    : picked === 'nudge' && reviewStuckAnswers(row).length ? await nudgeHelper(row.ticket, row.kind === 'helper:unmerged' ? MERGE_ASK : NUDGE)
    : picked === 'fresh' && row.kind !== 'helper:unmerged' && reviewStuckAnswers(row).length ? await restartFresh(row.ticket)
    : null;
  if (!r) return {ok:false, error:{code:'refused', message:'That button is not on this card.'}};
  if (!r.ok) return {ok:false, error:{code:'error', message:String(r.text || 'It did not work. Try again.').slice(0, 300)}};
  reviewStuckDone.set(id, {word:STUCK_WORDS[picked === 'nudge' && !running ? 'start' : picked], at:Date.now(), stop:reviewStuckStop(row)});
  return {ok:true};
}
// A Factory proposal reads like Home's card (ORCH-183): its title as the question, the goal and the time in two short
// lines, not the whole frozen proposal (that stays on the ticket). Any other card is left as it is.
function reviewPlainCard(c) {
  const p = c && typeof c.text === 'string' ? window.DashHelpers?.factoryStart?.(c.text) : null;
  if (!p) return c;
  // Home's own buttons (owner 17 Nov, choice B): Not now, Change it, Start, none filled; each answers with Factory's word.
  const answers = (window.DashHelpers.factoryStartOptions?.(c.options) || []).map(o => ({label:o.label, picked:o.answer}));
  const card = {...(c.card || {}), title:"Start '" + p.title + "'?"};
  if (answers.length) delete card.preview;  // the buttons are the answers: no second list of them on the card
  return {...c, text:p.goal + (p.meta ? '\n' + p.meta : ''), card, ...(answers.length ? {answers} : {})};
}
function reviewAnswered() { return array(state?.review?.answered); }
// The cards of the stack: work that stopped, every open question (an add-on's own too, e.g. Factory's Start?) and every result to check.
function reviewCount() { return reviewCards().length; }
// The subtitle shows THE needs-you number (needsYouTotal: open questions, results to check and work that stopped; the
// Review menu entry, the top bar, Home and the live bar show the same one, ORCH-63, ORCH-705).
// While the deck is open, the heading says what its Waiting tab says (cards answered here leave both at once, ORCH-476).
let reviewWaiting = null;
function reviewSubtitle() {
  // A card put off on Home ("Later today") is not in the one number, but it is still a card here: the subtitle never
  // says "Nothing waits" above a Waiting tab with cards in it (ORCH-420, owner's picture 18 Nov).
  // ORCH-1616: the cards waiting plus what is listed above them (no card of its own): what the page shows
  const n = reviewWaiting != null ? reviewWaiting + reviewExtraRows().length : (typeof needsYouTotal === 'function' ? needsYouTotal() : 0) || reviewCount();
  return n ? n + (n === 1 ? ' thing waits' : ' things wait') + ' on you, most urgent first.' : 'Nothing waits for you.';
}
// The words the "All cards" list shows for an answered card (the same as the deck's own summary).
function reviewWord(answer) {
  const it = answer.item || {}, note = answer.note || {};
  const own = Array.isArray(it.answers) && it.answers.find(x => x.picked === note.picked);
  if (answer.verdict === 'ok' && own) return own.label;
  if (answer.verdict === 'ok') return note.picked ? 'Use ' + note.picked : it.okLabel || 'Looks good';
  if (answer.verdict === 'no') return it.preview?.type === 'options' ? 'None' : it.kind === 'check' ? 'Sent back' : "Don't do";
  return 'Sent back';
}
// ORCH-548: Looks good on a Check card waits 6 s for Undo, then its save takes seconds more (3 s in the middle,
// 18 s at worst on a busy workspace). Meanwhile the ticket shows Done on every page, with one line that it is being
// saved (ticket.js); Undo or a refusal reads the whole state again, so the page shows what really is.
const acceptSaving = new Map();  // ticket id -> when Looks good was given
function acceptTicketOf(it) {
  const m = REVIEW_ID.exec(String(it?.id || ''));
  return m && m[3] ? m[3] : null;  // only a Check card (core:review:<ticket>) moves a ticket to Done
}
// Called by accept() in app.js on every new state: a ticket whose Looks good is still being saved stays Done.
function acceptOverlay(next) {
  if (!Array.isArray(next?.tickets) || !next.tickets.some(t => t && (acceptSaving.has(t.id) || t.accept_saving))) return next;
  return {...next, tickets:next.tickets.map(t => {
    if (!t) return t;
    if (acceptSaving.has(t.id)) return t.status === 'review' ? {...t, status:'done', accept_saving:true, accept_was:'review'} : t;
    if (!t.accept_saving) return t;
    const {accept_saving, ...rest} = t;  // accept_was stays until the server's state replaces the ticket
    return rest;
  })};
}
function acceptHold(it, verdict) {
  const tid = acceptTicketOf(it);
  if (!tid || verdict !== 'ok' || snapshot) return;
  acceptSaving.set(tid, Date.now());
  if (state) state = acceptOverlay(state);
  render();
}
function acceptRelease(it, saved) {
  const tid = acceptTicketOf(it);
  if (!tid || !acceptSaving.delete(tid)) return;
  if (saved) { if (state) state = acceptOverlay(state); render(); return; }  // the answer's own state already says Done
  // Undo or a refusal: back to Check at once, then the server's whole state (its revision is cleared, so the page
  // takes it even when nothing changed on the server: the Done was only the page's own)
  if (state) state = {...acceptOverlay(state), rev:''};
  if (state) state.tickets = state.tickets.map(t => t && t.id === tid && t.status === 'done' && !t.accept_saving && t.accept_was ? {...t, status:t.accept_was} : t);
  render();
  wantFull = true;
  refresh();
}

// One Run it now click (op card.run) for any page: {ok, exit, output, error?} to show on the card. 403 = not signed in.
async function runCardClick({ticket, key, digest, confirmed}) {
  const args = {ticket, key, digest};
  if (confirmed) args.confirmed = true;
  const r = await act('card.run', args);
  if (r.ok) {
    const res = r.state?.run_result || {ok:false, error:'orch did not say how it went. Look at the ticket before you try again.'};
    if (res.ok && window.orch?.toast) window.orch.toast('Ran it. The card is answered.', 'ok');  // Home drops the card at once
    return res;
  }
  if (r.status === 403) return {ok:false, error:String(r.text || 'Sign in to do this.').slice(0, 300)};
  return {ok:false, error:String(r.text || 'Could not run it.').slice(0, 300)};
}
// The Run it now card of a question on Home and the ticket page (outlined button; Review has the filled one). The other
// answer goes through the same answer as Review's (op review.answer, verdict no).
function runCardNode(ticketId, q) {
  if (!window.UI?.runCard || !q?.card || q.card.kind !== 'run' || !q.card.run) return null;
  const card = q.card, key = String(q.id || '');
  return window.UI.runCard(card, {
    primary: false, last: q.run_last && typeof q.run_last === 'object' ? q.run_last : undefined,
    run: ({confirmed}) => runCardClick({ticket:ticketId, key, digest:q.digest, confirmed}),
    no: async () => {
      const r = await act('review.answer', {ticket:ticketId, key, verdict:'no', digest:q.digest});
      if (r.ok) return {ok:true};
      return {ok:false, error:String(r.text || 'Could not save your answer.').slice(0, 300)};
    }
  });
}
// What the page's api needs, from the dashboard: state in, one signed click out, files through /api/file.
function reviewApi() {
  return {
    get workspace() { return clean(state?.workspace || ''); },
    stack: async () => reviewCards(),
    answered: async () => reviewAnswered(),
    fileUrl: (c, ref) => {
      if (typeof c?.ticket !== 'string') return '';
      const m = /^reviewed\/([0-9a-f]{12})\/([^/]+)$/.exec(String(ref || ''));
      if (m) return '/api/file?t=' + encodeURIComponent(c.ticket) + '&k=reviewed&n=' + encodeURIComponent(m[1] + '/' + m[2]);
      // a Check result's own files (ORCH-183): a picture or PDF through /api/file, a web page in its sandboxed /view frame
      const f = /^(evidence|artifacts)\/((?:[^/\\]+\/){0,3}[^/\\]+)$/.exec(String(ref || ''));
      if (!f || f[2].split('/').some(p => p === '..' || p === '.' || p.startsWith('.'))) return '';
      return /\.html?$/i.test(f[2])
        ? '/view/' + encodeURIComponent(c.ticket) + '/' + f[1] + '/' + f[2].split('/').map(encodeURIComponent).join('/')
        : '/api/file?t=' + encodeURIComponent(c.ticket) + '&k=' + f[1] + '&n=' + encodeURIComponent(f[2]) + reviewFileStamp(c.ticket, f[1], f[2]);
    },
    // The Comment sheet's box (ORCH-422): screenshots, files and voice notes land on the ticket before the answer or note.
    get box() { return snapshot || typeof FEEDBACK_BOX === 'undefined' ? null : FEEDBACK_BOX; },
    attach: async ({ticket, files}) => {
      if (snapshot || typeof ticket !== 'string') return {ok:false, error:{code:'refused', message:'Files cannot be added here.'}};
      const r = await ticketAttachFiles(ticket, files, true);  // the feedback folder: the card being answered stays the same
      return r.ok ? r : {ok:false, error:{code:'error', message:String(r.text || 'The files could not be added.').slice(0, 300)}};
    },
    // "Add note" on the Comment sheet: the words (and files) go to the ticket's helper (queued if none is running); no verdict, the card stays.
    note: async ({ticket, text, files}) => {
      const list = array(files);
      if (snapshot || typeof ticket !== 'string' || (!String(text || '').trim() && !list.length)) return {ok:false, error:{code:'refused', message:'Write your note first.'}};
      const kept = await ticketAttachFiles(ticket, list);
      if (!kept.ok) return {ok:false, error:{code:'error', message:String(kept.text || 'The files could not be added.').slice(0, 300)}};
      const r = await act('run.send', {ticket, text:ticketTalkText(text, kept.names)});
      return r.ok ? {ok:true} : {ok:false, error:{code:'error', message:String(r.text || 'Could not save the note.').slice(0, 300)}};
    },
    // Run it now (ORCH-848): the click runs the card's command; the answer carries what it printed (run_result).
    run: async ({id, digest, confirmed}) => {
      const m = REVIEW_ID.exec(String(id || ''));
      if (!m || !m[1]) return {ok:false, error:'That card is not here any more.'};
      return runCardClick({ticket:m[1], key:m[2], digest, confirmed});
    },
    hold: (it, verdict) => acceptHold(it, verdict),
    release: it => acceptRelease(it, false),
    answer: async ({id, digest, verdict, picked, note}) => {
      if (STUCK_CARD.test(String(id || ''))) return snapshot ? {ok:false, error:{code:'refused', message:'Nothing can be changed here.'}} : reviewStuckAnswer(id, digest, picked);
      const m = REVIEW_ID.exec(String(id || ''));
      if (!m) return {ok:false, error:{code:'not_found', message:'That card is not here any more.'}};
      const args = {ticket:m[1] || m[3], key:m[2] || 'review', verdict, digest};
      if (picked) args.picked = picked;
      if (note) args.note = note;
      const r = await act('review.answer', args);
      if (r.ok) { acceptRelease({id}, true); return {ok:true}; }
      if (r.status === 403) return {ok:false, error:{code:'needs_person', message:r.text}};
      try {
        const body = JSON.parse(r.text);
        if (body?.error?.code) return {ok:false, error:body.error};
      } catch (_) { /* a plain refusal below */ }
      return {ok:false, error:{code:r.status === 400 ? 'refused' : 'error', message:String(r.text || 'Could not save your answer.').slice(0, 300)}};
    }
  };
}
// The "All cards" list beside the deck is the kit's own (deck.drawList, ORCH-477 round 2): a row opens its card; the
// "Compare" button in its header turns on the ticks (at most two), then Compare opens them side by side and Cancel ends
// it. One section per set (the helper's group, else the ticket); the phone's full list draws the same rows.
function reviewDrawSide(queue, deck) {
  if (!queue || !deck || typeof deck.drawList !== 'function') return;
  deck.drawList(queue);
}
// "Accepted for you" (ORCH-77): what the Reviewer marked Done today; one tap sends a ticket back with a short note.
// A phone width keeps this card (the "All cards" aside hides there), so it sits under the deck.
const reviewSentBack = new Set();
function reviewAccepted() { return array(state?.review?.accepted).filter(a => a && typeof a.ticket === 'string'); }
async function reviewSendBack(a, note) {
  const text = String(note || '').trim();
  if (snapshot || !text) return false;
  const r = await act('ticket.changes', {ticket:a.ticket, text});
  window.orch.toast(r.ok ? 'Changes sent' : String(r.text || 'Could not send it back.').slice(0, 200), r.ok ? 'ok' : 'error');
  if (r.ok) reviewSentBack.add(a.ticket);
  return r.ok;
}
// Undo (ORCH-425): each thing the Reviewer, the Auto Reviewer or Away mode did comes back to you in one click.
const reviewUndone = new Set();
// one row per history event: the ticket plus the event's time (an accept, a send-back and a second accept differ)
function reviewRowKey(a) { return 'review-accepted-' + a.ticket + (a.question ? '-' + a.question : a.back ? '-back' : '') + (a.at ? '-' + String(a.at).replace(/[^0-9]/g, '') : ''); }
function reviewRowWord(a) {
  const who = a.auto ? (a.answer ? 'Away mode' : 'Auto Reviewer') : 'Reviewer';
  return who + ' · ' + (a.answer ? 'Answered' : a.back ? 'Sent back to the helper' : 'Accepted');
}
async function reviewUndo(a) {
  if (snapshot || !a.undo) return false;
  const args = {ticket:a.ticket};
  if (a.undo === 'answer' && a.question) args.question = a.question;
  const r = await act('review.undo', args);
  window.orch.toast(r.ok ? 'Undone: it waits for you again' : String(r.text || 'Could not undo it.').slice(0, 200), r.ok ? 'ok' : 'error');
  if (r.ok) { reviewUndone.add(reviewRowKey(a)); render(); }
  return r.ok;
}
function reviewAcceptedRow(a) {
  const key = reviewRowKey(a);
  const host = h('div', {'data-key':key});
  const undone = a.undone === true || reviewUndone.has(key);
  const sent = !undone && (a.sent_back === true || reviewSentBack.has(a.ticket));
  const accept = !a.answer && !a.back;
  const open = !accept || sent || undone || snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':key + '-send'}, 'Send back');
  const undo = !a.undo || undone || snapshot ? null : h('button', {type:'button', className:'btn ghost sm', 'data-key':key + '-undo'}, 'Undo');
  // The reason takes the full card width under the title; Send back and Undo sit on their own line below it
  // (the side column is narrow at 1280).
  const head = h('div', {className:'card-row'},
    h('div', {className:'grow'},
      h('a', {href:'#ticket/' + encodeURIComponent(a.ticket)}, clean([a.key, a.title].filter(Boolean).join(' · '))),
      h('p', {className:'meta'}, reviewRowWord(a)),
      a.why ? h('p', {className:'meta'}, clean(a.why)) : null,
      undone ? h('p', {className:'meta'}, 'Undone') : sent ? h('p', {className:'meta'}, 'Sent back') : open || undo ? h('div', {className:'row'}, open, undo) : null));
  host.append(head);
  if (undo) undo.onclick = () => reviewUndo(a);
  if (open) open.onclick = () => {
    locks.add(key);
    // The feedback box (ORCH-422): words, a pasted screenshot, a file or a voice note.
    const box = h('div', {id:key + '-box'});
    let comp = null, busy = false;
    const close = () => { if (busy) return; comp?.destroy?.(); locks.delete(key); host.replaceChildren(head); open.focus(); };
    const cancel = h('button', {type:'button', className:'btn ghost sm'}, 'Cancel');
    cancel.onclick = close;
    host.replaceChildren(head, box, h('div', {className:'row'}, cancel));
    if (!window.UI?.composer || typeof FEEDBACK_BOX === 'undefined') return;
    comp = window.UI.composer(box, {...FEEDBACK_BOX, label:'What should change?', placeholder:'What should change?', sendLabel:'Send back', interrupt:false, hint:'',
      emptyError:'Write what should change, or add a file or a voice note.', dropTarget:host, dropLabel:'Drop to send back with this', sendingText:'Sending…',
      onSend:async message => {
        busy = true;
        try {
          const kept = await ticketAttachFiles(a.ticket, message.files);
          if (!kept.ok) return kept;
          const ok = await reviewSendBack(a, ticketTalkText(message.text, kept.names));
          if (ok) { busy = false; locks.delete(key); render(); return {ok:true, text:''}; }
          return {ok:false, dropFiles:kept.names.length > 0, text:'It was not sent back. Try again.'};
        } finally { busy = false; }
      }});
    box.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); close(); } });
    comp.field.focus();
  };
  return host;
}
function reviewAcceptedCard() {
  const rows = reviewAccepted();
  if (!rows.length) return null;
  return card('review-accepted', 'Accepted for you', '', rows.map(reviewAcceptedRow));
}
// The Auto Reviewer and Away (ORCH-425): two switches on the rail, each saves at once (only a person turns them
// on; `orch config set workflow.auto_reviewer` / `workflow.away`). Tickets with Human review needed are left alone.
const reviewSwitchBusy = new Set();
const REVIEW_SWITCHES = {
  auto:{op:'auto_reviewer.set', field:'auto_reviewer_on', action:'auto-reviewer-set', title:'Check finished work',
    meta:'Tickets without Human review needed get a written verdict and are accepted or sent back by themselves.'},
  away:{op:'away.set', field:'away_on', action:'away-set', title:'Away for the night',
    meta:"Also answers cards with the helper's recommendation at once. Words, names, money, deploy, delete and keys wait for you."}
};
function reviewSwitchRow(key) {
  const sw = REVIEW_SWITCHES[key], on = state?.settings?.[sw.field] === true;
  return h('div', {className:'card-row', 'data-key':'review-auto-' + key},
    h('div', {className:'grow'}, h('h3', {}, sw.title), h('p', {className:'meta'}, sw.meta)),
    h('button', {type:'button', className:'switch', role:'switch', 'aria-label':sw.title, 'aria-checked':on, 'data-key':'review-switch-' + key, 'data-action':sw.action, disabled:snapshot || reviewSwitchBusy.has(key)}));
}
function reviewAutoCard() {
  if (!state?.settings) return null;
  return card('review-auto', 'Auto Reviewer', '', [reviewSwitchRow('auto'), reviewSwitchRow('away')]);
}
async function reviewSwitch(key) {
  const sw = REVIEW_SWITCHES[key];
  if (!sw || snapshot || reviewSwitchBusy.has(key)) return null;
  reviewSwitchBusy.add(key); render();
  const r = await act(sw.op, {on:state?.settings?.[sw.field] !== true});
  reviewSwitchBusy.delete(key);
  if (!r.ok) window.orch.toast(String(r.text || 'Could not save it.').slice(0, 200), 'error');
  render();
  return r;
}
// ORCH-1616 (owner's look stop: the badge said 4 above a page that listed 3): the Review page lists everything the
// needs-you number counts. The cards show most of it; what has no card of its own (a helper that waits for an OK on
// its screen, ORCH-1358; a question or a result orch has no card for yet) is listed above the cards, so the badge,
// the heading and what the page shows are the same count.
function reviewExtraRows() {
  if (!state || typeof needsToday !== 'function') return [];
  let n;
  try { n = needsToday(); } catch (e) { return []; }
  const carded = new Set(reviewCards().map(c => c && (c.ticket || c.ticketId)).filter(Boolean));
  const out = [], seen = new Set(), add = (t, what, text) => {
    if (!t || carded.has(t.id) || seen.has(what + ':' + t.id)) return;
    seen.add(what + ':' + t.id); out.push({t, what, text});
  };
  // ORCH-1643: plain words (the helper asks in its session, there is nothing more to say about where)
  array(n.screenRows).forEach(r => add(r.ticket, 'screen', 'Waits for your answer.'));
  // orch's own count lists questions (with their id) and results (without one); an older core: Home's rows and results
  for (const it of array(n.askedItems)) {
    const t = ticketOf(it.ticket), q = it.question ? array(t?.questions).find(x => x && x.id === it.question && x.answer == null) : null;
    if (!it.question && n.fromCore) add(t, 'result', 'A result to check.');
    else add(t, 'question', q ? clean(q.text) : 'Waits for your answer.');
  }
  if (!n.fromCore) array(n.review).filter(t => !n.unsure?.has?.(t.id)).forEach(t => add(t, 'result', 'A result to check.'));
  return out;
}
// ORCH-1643: a question with two or three choices (a helper's on its screen too, when its ticket carries it) is answered in its row with one click: the same question card as the
// Focus pane (liveAskFill, pages/live-layer.js), mounted after the paint (mountReview). Anything else keeps one line.
function reviewOneClick(r) {
  // a helper that waits on its screen whose ticket carries the open question with its choices: the same card
  if (!['question', 'screen'].includes(r.what) || typeof liveAskFill !== 'function' || typeof liveAskModel !== 'function' || snapshot) return false;
  const q = liveAskModel(r.t);
  return !!q && q.plain && q.options.length >= 2 && q.options.length <= 3;
}
function reviewExtraCard() {
  const rows = reviewExtraRows();
  if (!rows.length) return null;
  const live = typeof window.LiveLayer?.open === 'function' && typeof liveFocusOn === 'function' && liveFocusOn();
  const act = r => r.what === 'screen' && live
    ? h('button', {type:'button', className:'btn outline sm', 'data-review-screen':r.t.id, 'data-key':'review-extra-open-' + r.t.id}, 'Answer')
    : h('a', {className:'btn outline sm', href:'#ticket/' + encodeURIComponent(r.t.id), 'data-key':'review-extra-open-' + r.t.id}, r.what === 'result' ? 'Check' : 'Answer');
  return card('review-extra', 'Also waiting for you', '',
    rows.map(r => reviewOneClick(r)
      ? h('div', {className:'card-row', 'data-key':'review-extra-' + r.t.id, 'data-what':r.what},
        h('div', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(r.t, h), clean(r.t.title)),
          h('div', {className:'live-ask', 'data-review-ask':r.t.id, 'data-key':'review-ask-' + r.t.id})))
      : h('div', {className:'card-row', 'data-key':'review-extra-' + r.t.id, 'data-what':r.what},
        h('div', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(r.t, h), clean(r.t.title)),
          h('p', {className:'meta'}, r.text)), act(r))));
}
function reviewPage() {
  // the kit draws the list's header ("All cards", Compare / Cancel) and its rows into the queue (ORCH-477 round 2)
  const side = h('aside', {className:'card review-side', 'data-key':'review-side', 'data-review-side':'', 'aria-label':'All cards'},
    h('div', {className:'review-queue', 'data-review-queue':''}));
  return fragment(
    heading('Review', reviewSubtitle()),
    // the list on the left, the card (or the two ticked side by side) on the right (ORCH-477)
    h('div', {className:'review-layout', 'data-key':'review-layout'},
      h('div', {className:'stack review-rail', 'data-key':'review-rail'}, reviewAutoCard(), side, reviewAcceptedCard()),
      h('div', {className:'review-main stack', 'data-key':'review-main'}, reviewExtraCard(), h('div', {'data-review-host':'', 'data-key':'review-host'}))));
}
function reviewSetWaiting(main, deck) {
  reviewWaiting = deck ? Math.max(0, array(deck.items).length - Object.keys(deck.answers || {}).length) : null;
  const sub = main.querySelector('[data-key="heading"] p.muted');
  if (sub && sub.textContent !== reviewSubtitle()) sub.textContent = reviewSubtitle();
}
// Mount the kit page once per host (render() calls this after every reconcile; the mounted host is left alone).
function mountReview(main) {
  main.querySelectorAll('[data-review-side]').forEach(s => { if (!mounts.has(s)) mounts.set(s, {destroy() {}}); });
  // the one-click question rows: the paint leaves a mounted host alone; its card redraws only when the question changes
  main.querySelectorAll('[data-review-ask]').forEach(box => {
    if (!mounts.has(box)) mounts.set(box, {destroy() {}});
    if (typeof liveAskFill === 'function') liveAskFill(box, box.dataset.reviewAsk);
  });
  main.querySelectorAll('[data-review-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.reviewPage) return;
    const queue = main.querySelector('[data-review-queue]');
    const want = /[?&]card=([^&]+)/.exec(typeof location === 'undefined' ? '' : location.hash || '');  // the ticket page's "Look and answer" opens this card
    // with helpers waiting on their screen (listed above the deck) the empty deck does not say "Nothing waits for you"
    // ORCH-1643: never "No cards to check" beside things that wait: the list above says it all
    const empty = () => reviewExtraRows().length ? {title:'No other cards', text:'What waits for you is listed above.'} : null;
    const page = window.UI.reviewPage(host, reviewApi(), {poll:3000, empty, startId:want ? decodeURIComponent(want[1]) : null, onChange:deck => { reviewDrawSide(queue, deck); reviewSetWaiting(main, deck); }, ticketHref:id => '#ticket/' + encodeURIComponent(id)});
    mounts.set(host, {destroy() { reviewWaiting = null; page.destroy(); }, page});
  });
}
// Answer on a helper that asks on its screen: its session opens in the live layer over the Review page
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('click', e => {
    const b = e.target.closest?.('[data-review-screen]');
    if (b && typeof window.LiveLayer?.open === 'function') window.LiveLayer.open(b.dataset.reviewScreen);
  });
}
// A new state (a card arrived, one was answered elsewhere): the open page reads it at once, not at its next tick.
if (typeof window !== 'undefined' && window.addEventListener) {
  window.addEventListener('orch:state', () => {
    if (typeof mounts === 'undefined') return;
    for (const m of mounts.values()) m.page?.tick?.();
  });
}
