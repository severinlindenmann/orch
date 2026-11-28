'use strict';
// Review (#review): everything that waits for a decision, one card at a time (the kit's UI.reviewPage), with the
// waiting list beside it on a wide screen and after it on a narrow one. The cards and the decisions come with the
// state (state.review, from `orch review list`); an answer is a plain click (op review.answer).
// Owner's walk of 28 Nov: the card comes first and the list shows five rows at a time (W-036, O-04, O-05), there is no
// Compare (O-06), what the Reviewer did is on Answered (W-036), a card shows its evidence and what a paid click costs
// (W-040, CX-02), and the heading says the menu badge's number (W-003).
const REVIEW_ID = /^core:(?:q:(t_[a-z0-9]{6,16}):(q[0-9]{1,4})|review:(t_[a-z0-9]{6,16}))$/;
// ORCH-524: a Test results card's file as the ticket lists it (its time and size, when known here), so its link names
// its version and the browser keeps the picture; unknown: a plain link that asks again by content hash.
function reviewFileStamp(tid, kind, name) {
  const t = array(state?.tickets).find(x => x?.id === tid);
  if (!t || !window.FileViewer?.stampOf || typeof evidenceFile !== 'function' || typeof allArtifactFiles !== 'function') return '';
  const files = kind === 'evidence' ? array(t.checklist).flatMap(task => array(task.evidence).map(ev => evidenceFile(t, ev)).filter(Boolean)) : allArtifactFiles(t);
  const stamp = window.FileViewer.stampOf(files.find(file => file.name === name));
  return stamp ? '&v=' + encodeURIComponent(stamp) : '';
}
function reviewCards() { return [...reviewStuckCards(), ...array(state?.review?.cards).map(reviewPlainCard), ...reviewDraftCards()]; }
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
// W-040, CX-02: what a click that starts paid helper work costs, in the card's own words: the ticket's estimate when
// the helper gave one, else the plain truth. Never an invented number.
function reviewCostWords(t) {
  const est = t && typeof t.estimate === 'object' && t.estimate ? t.estimate : {}, D = window.DashHelpers || {}, parts = [];
  if (Number.isInteger(est.minutes) && est.minutes > 0 && D.durationWords) parts.push(D.durationWords(est.minutes * 60));
  if (typeof est.cost === 'number' && est.cost >= 0.005 && D.moneyWords) parts.push(D.moneyWords(est.cost));
  return parts.length ? "this ticket's estimate: about " + parts.join(' · ') : 'cost not known';
}
const REVIEW_SEND_BACK = 'Sends your changes for a helper to work on';
function reviewSendBackWords(t) { return REVIEW_SEND_BACK + ' · ' + reviewCostWords(t) + '.'; }
// W-040: one evidence line on a pull request card: which pull request, its check and merge state, how fresh that is.
function reviewPullNumber(url) { const m = /\/pull\/([0-9]{1,9})(?:[/?#]|$)/.exec(String(url || '')); return m ? ' #' + m[1] : ''; }
function reviewStuckEvidence(row) {
  if (row.kind !== 'helper:unmerged') return '';
  const pull = row.pull || {}, at = typeof pull.checked_at === 'string' && pull.checked_at ? pull.checked_at : '';
  return ['Pull request' + reviewPullNumber(pull.url), 'checks passed, not merged', row.since ? 'passed ' + time(row.since) : '', at ? 'looked at ' + time(at) : ''].filter(Boolean).join(' · ');
}
function reviewStuckLinks(row) {
  const url = String(row.pull?.url || '');
  return row.kind === 'helper:unmerged' && /^https:\/\//.test(url) ? [{label:'Open pull request' + reviewPullNumber(url), url}] : [];
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
    // the card reads: what happened (text), the evidence (why), what the buttons do and cost (hint), the buttons (W-042)
    const why = [reviewStuckEvidence(row), done ? done.word + ' ' + time(new Date(done.at).toISOString()) + '.' : '', step].filter(Boolean).join(' · ');
    const links = reviewStuckLinks(row);
    return {id, ticket:row.ticket, ticket_key:typeof t?.key === 'string' && t.key ? t.key : row.ticket, ticket_title:title,
      key:'stuck', cause:String(row.kind || ''), since:row.since, digest:reviewStuckDigest(row), href:'#ticket/' + encodeURIComponent(row.ticket),
      text:clean(row.text), ...(about ? {about} : {}), ...(links.length ? {links} : {}),
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
  if (row.kind === 'reviewer:unsure') return 'Open the ticket to review the result yourself.';
  // W-040: a button that starts paid helper work says what it costs (the estimate, or that it is not known)
  const cost = reviewCostWords(typeof ticketOf === 'function' ? ticketOf(row.ticket) : null), running = state.runs?.[row.ticket]?.running === true;
  if (row.kind === 'helper:unmerged') return 'Merge puts the pull request in. ' + (running ? 'Nudge asks the helper' : 'Start helper starts paid helper work (' + cost + ') that asks it') + ' to merge or say why it stays open.';
  return 'Nudge asks the helper to go on with the next step. Start fresh stops it and starts a new helper on this ticket (' + cost + ').';
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
const REVIEW_DRAFT_ID = /^factory:draft:(t_[a-z0-9]{6,16}):v[0-9]{1,6}$/;
// A Factory draft ready for Plan the run (ORCH-479) is a card too, with the Factory page's verbs: Read draft (the link),
// Plan the run (the approve button) and Ask for changes (the "no" button: the Comment sheet, your words go to the agent).
function reviewDraftCards() {
  const rows = typeof needsList === 'function' ? window.DashHelpers.factoryDrafts(needsList()) : [];
  return rows.filter(r => REVIEW_DRAFT_ID.test(r.id)).map(r => {
    const t = ticketOf(r.ticket), link = location.origin + location.pathname + (typeof factoryOrderHref === 'function' ? factoryOrderHref(r.ticket, 'draft') : '#ticket/' + r.ticket);
    return {id:r.id, ticket:r.ticket, key:'review', ticket_key:t && typeof t.key === 'string' ? t.key : r.ticket, ticket_title:t ? clean(t.title) : clean(r.title),
      since:r.since, digest:'', group:'Factory', text:'Read the draft, then plan the run or ask for changes.',
      links:[{label:'Read draft', url:link}],
      card:{kind:'draft', title:clean(r.title), ok_label:'Plan the run', no_label:'Ask for changes', no_words:true,
        then:'Your helper plans the whole run; the proposal comes here for your Start.'}};
  });
}
// A Factory proposal reads like Home's card (ORCH-183): its title as the question, the goal and the time in two short
// lines, not the whole frozen proposal (that stays on the ticket). Any other card is left as it is.
// W-040 / CX-02: a result to review shows its pull request (state and Open) and says that Send back is paid helper work.
function reviewCheckCard(c) {
  if (c?.card?.kind !== 'check' || typeof c.ticket !== 'string') return c;
  const t = typeof ticketOf === 'function' ? ticketOf(c.ticket) : null, have = new Set(array(c.links).map(l => l && l.url));
  const pulls = array(t?.refs).filter(r => r && typeof r.url === 'string' && /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/[0-9]+/.test(r.url) && !have.has(r.url))
    .map(r => ({label:('Pull request' + reviewPullNumber(r.url) + (r.status ? ' · ' + clean(r.status) : '')).slice(0, 60), url:r.url}));
  const links = [...array(c.links), ...pulls].slice(0, 5);
  const card = c.card.hint || c.card.blocked ? c.card : {...c.card, hint:'Send back: ' + reviewSendBackWords(t).replace(/^S/, 's')};
  return {...c, card, ...(links.length ? {links} : {})};
}
function reviewPlainCard(c) {
  const p = c && typeof c.text === 'string' ? window.DashHelpers?.factoryStart?.(c.text) : null;
  if (!p) return reviewCheckCard(c);
  // Home's own buttons (owner 17 Nov, choice B): Not now, Change it, Start, none filled; each answers with Factory's word.
  const answers = (window.DashHelpers.factoryStartOptions?.(c.options) || []).map(o => ({label:o.label, picked:o.answer}));
  const card = {...(c.card || {}), title:"Start '" + p.title + "'?"};
  if (answers.length) delete card.preview;  // the buttons are the answers: no second list of them on the card
  // Read proposal: the same verb and place as on the Factory page and Home (ORCH-479)
  const links = typeof c.ticket === 'string' && typeof factoryOrderHref === 'function' && /^t_[a-z0-9]{6,16}$/.test(c.ticket)
    ? [{label:'Read proposal', url:location.origin + location.pathname + factoryOrderHref(c.ticket, 'proposal')}, ...array(c.links)].slice(0, 5) : c.links;
  return {...c, text:p.goal + (p.meta ? '\n' + p.meta : ''), card, ...(links ? {links} : {}), ...(answers.length ? {answers} : {})};
}
function reviewAnswered() { return array(state?.review?.answered); }
// The cards of the stack: work that stopped, every open question (an add-on's own too, e.g. Factory's Start?) and every result to check.
function reviewCount() { return reviewCards().length; }
// W-003 (owner, 28 Nov: menu badge 31, subtitle 27 in one picture): the subtitle reads THE needs-you number
// (needsYouTotal: open questions, results to review and work that stopped), the very number of the Review menu badge,
// the top bar, Home and the live bar (ORCH-63, ORCH-705). It no longer follows the deck's own count.
let reviewWaiting = null;  // the cards waiting in the deck now (null before it is drawn): the list's "N waiting"
function reviewShown() { return (reviewWaiting != null ? reviewWaiting : reviewCount()) + reviewExtraRows().length; }
function reviewSubtitle() {
  const n = typeof needsYouTotal === 'function' ? needsYouTotal() || 0 : reviewShown(), shown = reviewShown();
  if (!n && !shown) return 'Nothing waits for you.';
  // A card put off on Home ("Later today") is not in the one number, but it is still a card here: the page names
  // that part instead of saying "Nothing waits" above cards (ORCH-420), and never another number than the badge
  if (!n) return 'Nothing new needs you. ' + shown + (shown === 1 ? ' card you put off is still here.' : ' cards you put off are still here.');
  // ORCH-2316 (R2 A, draft r2-a): "10 things need you. 2 hold up work now." (the second sentence only when any does)
  const laneOf = window.UI?.review?.laneOf || (c => c?.card_kind?.lane), held = reviewCards().filter(c => laneOf(c) === 'holds_up').length;
  return n + (n === 1 ? ' thing needs you.' : ' things need you.') + (held ? ' ' + held + (held === 1 ? ' holds up work now.' : ' hold up work now.') : '');
}
// The words the "All cards" list shows for an answered card (the same as the deck's own summary).
function reviewWord(answer) {
  const it = answer.item || {}, note = answer.note || {};
  const own = Array.isArray(it.answers) && it.answers.find(x => x.picked === note.picked);
  if (answer.verdict === 'ok' && own) return own.label;
  if (answer.verdict === 'ok' && note.ideas && window.UI?.ideasWord) return window.UI.ideasWord(note.ideas, (it.ideas || []).length);  // ORCH-2186
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
// W-003 (owner, 28 Nov: "one count everywhere, updated together"): a card answered here leaves the deck at once, but
// its answer is saved a few seconds later (the Undo time), so the menu badge and the heading still counted it. The
// answered card's item is taken out of the state's one count (counts.needs_you.items, what needsToday() adds up) while
// its answer waits or is being saved; Undo or a refusal puts it back. Work that stopped and a Factory draft are not
// answers: they stay counted.
const reviewHeld = new Set();  // review card ids answered here whose answer is not in the server's state yet
function reviewHeldItem(i) {
  if (!i || typeof i.ticket !== 'string') return false;
  if (i.question) return reviewHeld.has('core:q:' + i.ticket + ':' + i.question);
  return !i.stopped && !i.start && reviewHeld.has('core:review:' + i.ticket);
}
function reviewHeldOverlay(next) {
  const items = next?.counts?.needs_you?.items;
  if (!reviewHeld.size || !Array.isArray(items) || !items.some(reviewHeldItem)) return next;
  return {...next, counts:{...next.counts, needs_you:{...next.counts.needs_you, items:items.filter(i => !reviewHeldItem(i))}}};
}
function reviewHold(it) {
  const id = String(it?.id || '');
  if (snapshot || !REVIEW_ID.test(id) || reviewHeld.has(id)) return;
  reviewHeld.add(id);
  if (state) { state = reviewHeldOverlay(state); render(); }
}
// back: Undo or a refusal (the server's state says how it is); saved: the answer's own state already left it out
function reviewUnhold(it, back) {
  if (!reviewHeld.delete(String(it?.id || '')) || !back) return;
  if (state) state = {...state, rev:''};  // the count comes back with the server's whole state, taken even when nothing changed there
  wantFull = true;
  refresh();
}
// Called by accept() in app.js on every new state: a ticket whose Looks good is still being saved stays Done.
function acceptOverlay(next) {
  next = reviewHeldOverlay(next);
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
    if (res.ok && res.in_terminal) {  // a sign-in (ORCH-865): it started in the plain terminal; the card answers itself later
      runCardTerminal(res.terminal, ticket);  // the card itself says what to do: no toast
      return res;
    }
    if (res.ok && window.orch?.toast) window.orch.toast('Ran it. The card is answered.', 'ok');  // Home drops the card at once
    return res;
  }
  if (r.status === 403) return {ok:false, error:String(r.text || 'Sign in to do this.').slice(0, 300)};
  return {ok:false, error:String(r.text || 'Could not run it. Try again.').slice(0, 300)};
}
// Opens the plain terminal's session in the live layer (a sign-in card's terminal, ORCH-865); the sessions list is read
// again first, so a terminal that was just started is there.
async function runCardTerminal(id, ticket = '') {
  if (typeof id !== 'string' || !/^t_[a-z0-9]{6,16}$/.test(id)) return;
  // ORCH-2185: on Review with the side panel, Run it shows the terminal in the panel's helper tab beside the card
  if (reviewPanelRun(id, ticket)) return runCardWantTypingIn(id);
  try { await window.LiveSessions?.refresh?.(); } catch (e) { /* the layer still opens it */ }
  if (typeof window.LiveLayer?.open !== 'function') return;
  window.LiveLayer.open(id);
  // a phone: the sign-in takes the whole screen; Leave full screen (and Esc) goes back to the ticket
  if (typeof liveLayerPhone === 'function' && liveLayerPhone()) window.LiveLayer.place('full');
  return runCardWantTypingIn(id);
}
// the person turned typing on with the card's switch before the terminal was there: typing in its pane once it shows
async function runCardWantTypingIn(id) {
  if (!runCardWantTyping || !window.LiveTerm) return;
  runCardWantTyping = false;
  for (let i = 0; i < 25 && !window.LiveTerm.has(id); i++) await new Promise(r => setTimeout(r, 200));
  window.LiveTerm.want(id);
}
let runCardWantTyping = false;  // the card's typing switch was clicked while no terminal was open yet
// The plain terminal's session id (a sign-in card's terminal), from the page's sessions.
const runCardTermId = q => (q?.run_login?.terminal) || array(state?.sessions).find(x => x?.kind === 'terminal')?.id || '';
// "Turn on typing to sign in here" on a sign-in card (ORCH-865): the person's own click turns on typing in the plain
// terminal (the setting first when it is off, then typing in its pane); nothing turns it on by itself.
function runCardTyping(q, card) {
  const settingOn = () => state?.settings?.terminal_typing_on === true;
  return {
    on: () => {
      const id = runCardTermId(q);
      return settingOn() && (!id || !window.LiveTerm?.has(id) || window.LiveTerm.typing(id));
    },
    set: async () => {
      if (!settingOn()) {
        const r = await act('terminal-typing.set', {on:true});
        if (!r.ok) return {ok:false, error:String(r.text || 'Typing did not turn on.').slice(0, 300)};
        if (state?.settings) state.settings.terminal_typing_on = true;
      }
      const id = runCardTermId(q);
      if (id && window.LiveTerm?.has(id)) window.LiveTerm.want(id);
      else runCardWantTyping = true;  // the next sign-in this page opens takes typing at once
      return {ok:true};
    },
    watch: (fn, el) => {  // a card no longer on the page stops listening at the next change
      const node = () => el || card.node;
      const h = () => { const n = node(); if (n && !n.isConnected) window.removeEventListener('orch:term-typing', h); else fn(); };
      window.addEventListener('orch:term-typing', h);
    },
  };
}
// The Run it now card of a question on Home and the ticket page (outlined button; Review has the filled one). The other
// answer goes through the same answer as Review's (op review.answer, verdict no).
function runCardNode(ticketId, q) {
  if (!window.UI?.runCard || !q?.card || q.card.kind !== 'run' || !q.card.run) return null;
  const card = q.card, key = String(q.id || ''), held = {node:null};
  held.node = window.UI.runCard(card, {
    typing: q.run_terminal === true ? runCardTyping(q, held) : undefined,
    primary: false, last: q.run_last && typeof q.run_last === 'object' ? q.run_last : undefined,
    terminal: q.run_terminal === true, underway: q.run_login && typeof q.run_login === 'object' ? q.run_login : undefined,
    show: runCardTerminal,
    run: ({confirmed}) => runCardClick({ticket:ticketId, key, digest:q.digest, confirmed}),
    no: async () => {
      const r = await act('review.answer', {ticket:ticketId, key, verdict:'no', digest:q.digest});
      if (r.ok) return {ok:true};
      return {ok:false, error:String(r.text || 'Could not save your answer.').slice(0, 300)};
    }
  });
  return held.node;
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
      // a Test results card's own files (ORCH-183): a picture or PDF through /api/file, a web page in its sandboxed /view frame
      const f = /^(evidence|artifacts)\/((?:[^/\\]+\/){0,3}[^/\\]+)$/.exec(String(ref || ''));
      if (!f || f[2].split('/').some(p => p === '..' || p === '.' || p.startsWith('.'))) return '';
      return /\.html?$/i.test(f[2])
        ? '/view/' + encodeURIComponent(c.ticket) + '/' + f[1] + '/' + f[2].split('/').map(encodeURIComponent).join('/')
        : '/api/file?t=' + encodeURIComponent(c.ticket) + '&k=' + f[1] + '&n=' + encodeURIComponent(f[2]) + reviewFileStamp(c.ticket, f[1], f[2]);
    },
    // The Comment sheet's box (ORCH-422): screenshots, files and voice notes land on the ticket before the answer or note.
    get box() { return snapshot || typeof FEEDBACK_BOX === 'undefined' ? null : FEEDBACK_BOX; },
    attach: async ({ticket, files}) => {
      if (snapshot || typeof ticket !== 'string') return {ok:false, error:{code:'refused', message:'Files cannot be added here. Add them on the ticket page.'}};
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
    showTerminal: id => runCardTerminal(id),
    typing: row => runCardTyping(row, {node:null}),
    hold: (it, verdict) => { reviewHold(it); acceptHold(it, verdict); },
    release: it => { reviewUnhold(it, true); acceptRelease(it, false); },
    answer: async ({id, digest, verdict, picked, note}) => {
      if (STUCK_CARD.test(String(id || ''))) return snapshot ? {ok:false, error:{code:'refused', message:'Nothing can be changed here.'}} : reviewStuckAnswer(id, digest, picked);
      const draft = REVIEW_DRAFT_ID.exec(String(id || ''));
      if (draft) {  // Plan the run, or Ask for changes with your words: sent to the agent on the order, as on the Factory page
        const words = window.DashHelpers.FACTORY_DRAFT_WORDS, text = String(note?.text || '').trim();
        if (verdict !== 'ok' && !text) return {ok:false, error:{code:'refused', message:'Write what should change first.'}};
        const r = await sendAndStart(draft[1], verdict === 'ok' ? words.plan : words.change(text));
        return r.ok ? {ok:true} : {ok:false, error:{code:'error', message:r.error || "That didn't work. Nothing was sent."}};
      }
      const m = REVIEW_ID.exec(String(id || ''));
      if (!m) return {ok:false, error:{code:'not_found', message:'That card is not here any more.'}};
      const args = {ticket:m[1] || m[3], key:m[2] || 'review', verdict, digest};
      if (picked) args.picked = picked;
      if (note) args.note = note;
      const r = await act('review.answer', args);
      if (r.ok) { reviewUnhold({id}, false); acceptRelease({id}, true); return {ok:true}; }
      if (r.status === 403) return {ok:false, error:{code:'needs_person', message:r.text}};
      try {
        const body = JSON.parse(r.text);
        if (body?.error?.code) return {ok:false, error:body.error};
      } catch (_) { /* a plain refusal below */ }
      return {ok:false, error:{code:r.status === 400 ? 'refused' : 'error', message:String(r.text || 'Could not save your answer.').slice(0, 300)}};
    }
  };
}
// ---- The waiting list (owner's walk of 28 Nov) ----
// O-05 D: five compact rows and the count, with "Next five" and "All"; cards that wait for the same cause fold into
// one row with Open (it shows its cards), never a button that answers several at once: every decision stays its own.
// O-06 D: no Compare button and no ticks; a card that holds a before and an after still shows both on the card.
// O-04 D / W-036: the page draws the list (not the kit's deck.drawList): beside the card on a wide screen, after the
// card in the same page scroll on a narrow one, and under it one line that leads to what the Reviewer did.
const REVIEW_PAGE = 5;
let reviewListFrom = 0;              // the first row the list shows (a multiple of five): "Next five" moves on, never grows the list
let reviewListAll = false;           // "All": every row
let reviewListCur = '';              // the card that was on screen at the last draw (the list follows a new one)
const reviewListOpen = new Set();    // the causes whose cards are listed
let reviewDeck = null;               // the deck on screen (the list is drawn from it)
const STUCK_CAUSE = {'helper:unmerged':'Pull request not merged', 'helper:idle':'Helper stopped working', 'helper:failing':'Checks keep failing',
  'helper:permission':'Helper waits for your OK', 'reviewer:unsure':'Reviewer was not sure'};
// what a card waits for, when other cards can wait for the same: a kind of stopped work, else the card's own words
function reviewCauseOf(it) {
  const cause = it?.raw?.cause;
  if (typeof cause === 'string' && STUCK_CAUSE[cause]) return {key:'cause:' + cause, label:STUCK_CAUSE[cause]};
  // the same words on cards of one kind (a release recorded three times); a card without words of its own is never folded
  const title = clean(it?.title || '').replace(/\s+/g, ' ').trim();
  return title && title !== 'Review' ? {key:'title:' + String(it.kind || '') + ':' + title.toLowerCase(), label:title} : null;
}
// {total, rows, all, from, more, back}: the waiting cards in the deck's order, five rows at a time; two or more cards
// with one cause are one group row. The five shown are the ones that hold the card on screen when it changes.
function reviewListModel(deck, follow = false) {
  const items = array(deck?.items), answers = deck?.answers || {}, cur = deck?.index;
  const waiting = items.map((it, i) => ({it, i, now:i === cur, cause:reviewCauseOf(it)})).filter(x => x.it && !answers[x.it.id]);
  const count = new Map();
  waiting.forEach(x => { if (x.cause) count.set(x.cause.key, (count.get(x.cause.key) || 0) + 1); });
  const rows = [], groups = new Map();
  for (const x of waiting) {
    if (!x.cause || count.get(x.cause.key) < 2) { rows.push(x); continue; }
    let g = groups.get(x.cause.key);
    if (!g) { g = {group:x.cause.key, label:x.cause.label, rows:[], now:false, open:reviewListOpen.has(x.cause.key)}; groups.set(x.cause.key, g); rows.push(g); }
    g.rows.push(x); g.now = g.now || x.now;
  }
  const at = rows.findIndex(r => r.now), id = at >= 0 ? String((rows[at].group ? rows[at].rows.find(x => x.now) : rows[at]).it.id) : '';
  if (follow) {  // a new card on screen: the five rows that hold it
    if (id && id !== reviewListCur && !reviewListAll) reviewListFrom = Math.floor(at / REVIEW_PAGE) * REVIEW_PAGE;
    reviewListCur = id;
  }
  if (reviewListFrom >= rows.length) reviewListFrom = Math.max(0, Math.floor((rows.length - 1) / REVIEW_PAGE) * REVIEW_PAGE);
  if (rows.length <= REVIEW_PAGE) reviewListAll = false;
  const from = reviewListAll ? 0 : reviewListFrom, page = reviewListAll ? rows : rows.slice(from, from + REVIEW_PAGE);
  return {total:waiting.length, rows:page, all:rows.length, from, more:!reviewListAll && from + REVIEW_PAGE < rows.length, back:reviewListAll ? rows.length > REVIEW_PAGE : from > 0};
}
function reviewListJump(id) {
  const i = array(reviewDeck?.items).findIndex(it => it.id === id);
  if (i < 0 || typeof reviewDeck.jump !== 'function') return;
  if (reviewViewNow() === 'answered') reviewShow('deck');  // a row always shows its card, also from Answered
  reviewDeck.jump(i);
}
function reviewListRow(x, sub) {
  const b = h('button', {type:'button', className:'btn ghost review-queue-row' + (x.now ? ' is-now' : ''), title:clean(x.it.title), 'aria-current':x.now ? 'true' : null, 'data-review-row':x.it.id},
    h('span', {className:'review-queue-title'}, clean(x.it.title)), x.it.ticket ? h('span', {className:'meta'}, clean(x.it.ticket)) : null);
  b.onclick = () => reviewListJump(x.it.id);
  return h('div', {className:'review-queue-item' + (sub ? ' sub' : ''), role:'listitem'}, b);
}
function reviewListGroup(g) {
  const b = h('button', {type:'button', className:'btn ghost review-queue-row' + (g.now && !g.open ? ' is-now' : ''), 'aria-expanded':g.open ? 'true' : 'false', title:g.label, 'data-review-group':g.group},
    h('span', {className:'review-queue-title'}, g.rows.length + ' · ' + g.label), h('span', {className:'meta'}, g.open ? 'Close' : 'Open'));
  b.onclick = () => { if (reviewListOpen.has(g.group)) reviewListOpen.delete(g.group); else reviewListOpen.add(g.group); reviewDrawList(); };
  return [h('div', {className:'review-queue-item', role:'listitem'}, b), ...(g.open ? g.rows.map(x => reviewListRow(x, true)) : [])];
}
// The Reviewer's line under the list (W-036): what it did today in one line; Look opens Answered, where each entry
// has its reason and Undo.
function reviewReviewerLine() {
  const rows = reviewAccepted().filter(a => !a.earlier && a.undone !== true && !reviewUndone.has(reviewRowKey(a)));
  if (!rows.length) return null;
  const acc = rows.filter(a => !a.answer && !a.back).length, back = rows.filter(a => a.back).length, ans = rows.filter(a => a.answer).length;
  const parts = [acc ? 'accepted ' + acc : '', back ? 'sent back ' + back : '', ans ? 'answered ' + ans : ''].filter(Boolean);
  const look = h('button', {type:'button', className:'btn ghost sm', 'data-review-look':''}, 'Look');
  look.onclick = () => reviewShow('answered');
  return h('div', {className:'card-row', 'data-review-reviewer':''}, h('p', {className:'meta grow'}, 'The Reviewer ' + parts.join(', ') + ' for you today.'), look);
}
function reviewListNodes(deck, follow = false) {
  const m = reviewListModel(deck, follow), queue = reviewQueueLine(), reviewer = reviewReviewerLine();
  // one card alone needs no list; the lines under it still show
  if (m.total < 2 && !queue && !reviewer) return [];
  const step = (word, key, go) => { const b = h('button', {type:'button', className:'btn ' + (key === 'next' ? 'outline' : 'ghost') + ' sm', 'data-review-more':key}, word); b.onclick = () => { go(); reviewDrawList(); }; return b; };
  // under the rows, as plain card rows: the steps through the list, the merge line, the Reviewer's line
  const steps = [m.more ? step('Next five', 'next', () => { reviewListFrom = m.from + REVIEW_PAGE; }) : null,
    m.back ? step('First five', 'five', () => { reviewListFrom = 0; reviewListAll = false; }) : null,
    !reviewListAll && m.all > REVIEW_PAGE ? step('All ' + m.total, 'all', () => { reviewListAll = true; }) : null].filter(Boolean);
  const where = !reviewListAll && m.all > REVIEW_PAGE ? h('span', {className:'meta', 'data-review-where':''}, 'Rows ' + (m.from + 1) + ' to ' + (m.from + m.rows.length) + ' of ' + m.all) : null;
  return [
    h('div', {className:'review-list-head'}, h('h2', {className:'review-list-title'}, 'Needs you'), m.total ? h('span', {className:'review-group-count'}, m.total + ' waiting') : null),
    m.total > 1 ? h('div', {className:'review-list-groups'}, h('div', {className:'review-group', role:'list', 'aria-label':'Waiting'}, m.rows.flatMap(r => r.group ? reviewListGroup(r) : [reviewListRow(r)]))) : null,
    steps.length ? h('div', {className:'card-row'}, steps, where) : null, queue ? h('div', {className:'card-row'}, queue) : null, reviewer].filter(Boolean);
}
// draws the list into its place on the page (the aside beside the card, or the card after it); an empty list hides it
function reviewDrawSide(queue, deck, follow = true) {
  if (!queue) return;
  reviewDeck = deck || null;
  const kids = reviewListNodes(reviewDeck, follow), ae = typeof document === 'object' ? document.activeElement : null;
  if (queue.dataset) queue.dataset.reviewTotal = String(reviewListModel(reviewDeck).total);  // every waiting card, also those behind Next five or in a group
  const held = ae && queue.contains?.(ae) ? ae.dataset?.reviewRow || ae.dataset?.reviewGroup || ae.dataset?.reviewMore || '' : '';
  if (typeof queue.replaceChildren === 'function') queue.replaceChildren(...kids); else queue.children = kids;
  const box = queue.closest?.('[data-review-next]');
  if (box) box.hidden = !kids.length;
  // the keyboard stays on the row or button it was on (a redraw makes new ones)
  if (held && queue.querySelectorAll) [...queue.querySelectorAll('button')].find(b => [b.dataset.reviewRow, b.dataset.reviewGroup, b.dataset.reviewMore].includes(held))?.focus({preventScroll:true});
}
function reviewDrawList() {
  const queue = typeof document === 'object' && document.querySelector ? document.querySelector('[data-review-queue]') : null;
  reviewDrawSide(queue, reviewDeck, false);  // a click in the list itself: the rows stay where the person put them
}
// O-04 D: under 721 px, or beside the Focus panel when the page area is tight, the list comes after the card in the
// page's own scroll (the shell marks those with data-live-narrow / data-live-stack); wider, it stands beside the card.
function reviewNarrow() {
  if (typeof document !== 'object' || !document.body) return false;
  const d = document.body.dataset || {};
  return d.liveNarrow != null || d.liveStack != null || (typeof matchMedia === 'function' && matchMedia('(max-width:720px)').matches);
}
// Waiting or Answered (the kit's two views): what the page draws around them follows the view on screen
let reviewView = 'deck';
function reviewViewNow() {
  const a = typeof document === 'object' && document.getElementById ? document.getElementById('answered') : null;
  return a && a.hidden === false ? 'answered' : 'deck';
}
function reviewShow(view) {
  const page = typeof mounts === 'undefined' || typeof document !== 'object' ? null : mounts.get(document.querySelector('[data-review-host]'))?.page;
  page?.show?.(view);
  reviewView = view;
  render();
}
// "What the Reviewer did" (ORCH-77, renamed ORCH-1835): what the Reviewer, the Auto Reviewer and Away mode did today; each
// row says Accepted, Sent back or Answered, and one tap sends an accepted ticket back with a short note.
// A phone width keeps this card (the "All cards" aside hides there), so it sits under the deck.
const reviewSentBack = new Set();
function reviewAccepted() { return array(state?.review?.accepted).filter(a => a && typeof a.ticket === 'string'); }
async function reviewSendBack(a, note) {
  const text = String(note || '').trim();
  if (snapshot || !text) return false;
  const r = await act('ticket.changes', {ticket:a.ticket, text});
  window.orch.toast(r.ok ? 'Changes sent' : String(r.text || 'Could not send it back. Try again.').slice(0, 200), r.ok ? 'ok' : 'error');
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
  window.orch.toast(r.ok ? 'Undone: it waits for you again' : String(r.text || 'Could not undo it. Try again.').slice(0, 200), r.ok ? 'ok' : 'error');
  if (r.ok) { reviewUndone.add(reviewRowKey(a)); render(); }
  return r.ok;
}
function reviewAcceptedRow(a) {
  const key = reviewRowKey(a);
  const host = h('div', {'data-key':key});
  const undone = a.undone === true || reviewUndone.has(key);
  const sent = !undone && (a.sent_back === true || reviewSentBack.has(a.ticket));
  const accept = !a.answer && !a.back, earlier = a.earlier === true;
  const open = !accept || sent || earlier || undone || snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':key + '-send'}, 'Send back');
  const undo = !a.undo || undone || snapshot ? null : h('button', {type:'button', className:'btn ghost sm', 'data-key':key + '-undo'}, 'Undo');
  // The reason takes the full card width under the title; Send back and Undo sit on their own line below it
  // (the side column is narrow at 1280).
  const head = h('div', {className:'card-row'},
    h('div', {className:'grow'},
      h('a', {href:'#ticket/' + encodeURIComponent(a.ticket)}, clean([a.key, a.title].filter(Boolean).join(' · '))),
      h('p', {className:'meta'}, reviewRowWord(a)),
      a.why ? h('p', {className:'meta'}, clean(a.why)) : null,
      earlier ? h('p', {className:'meta'}, 'Earlier verdict: a newer one counts') : undone ? h('p', {className:'meta'}, 'Undone') : sent ? h('p', {className:'meta'}, 'Sent back') : open || undo ? h('div', {className:'row'}, open, undo) : null));
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
    // CX-02: Send back asks for paid helper work; the box says so, with the estimate when one is known
    host.replaceChildren(head, h('p', {className:'meta', 'data-key':key + '-cost'}, reviewSendBackWords(typeof ticketOf === 'function' ? ticketOf(a.ticket) : null)), box, h('div', {className:'row'}, cancel));
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
// W-036 / O-04: the first block of the Answered view (no longer a column under the list): every entry with its reason,
// Send back and Undo. What the Reviewer may accept is unchanged.
function reviewAcceptedCard() {
  const rows = reviewAccepted();
  if (!rows.length) return null;
  return card('review-accepted', 'What the Reviewer did', '', rows.map(reviewAcceptedRow));
}
// W-043: questions that closed by themselves today because their cause is gone (a helper or the automation took its
// own question back, with the reason): Answered says so in one line each.
function reviewClosedRows() {
  const day = v => { const d = new Date(v); return Number.isNaN(d.getTime()) ? '' : d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); };
  const today = day(typeof now === 'function' ? now() : new Date());
  return array(state?.tickets).flatMap(t => array(t?.questions).filter(q => q && q.taken_back && typeof q.taken_back === 'object' && day(q.taken_back.at) === today).map(q => ({t, q})))
    .sort((a, b) => String(b.q.taken_back.at).localeCompare(String(a.q.taken_back.at)));
}
function reviewClosedCard() {
  const rows = reviewClosedRows();
  if (!rows.length) return null;
  return card('review-closed', 'Closed without you', '', rows.map(({t, q}) => h('div', {className:'card-row', 'data-key':'review-closed-' + t.id + '-' + q.id},
    h('div', {className:'grow'}, h('a', {href:'#ticket/' + encodeURIComponent(t.id)}, clean([t.key, t.title].filter(Boolean).join(' · '))),
      h('p', {className:'meta'}, clean(q.text || '')),
      h('p', {className:'meta'}, 'Closed by itself · ' + clean(q.taken_back.reason || 'its cause is gone'))))));
}
// W-043: a paused automation is one line on top (never a card per ticket), with the click that turns it on again.
let reviewResuming = false;
async function reviewResume() {
  if (snapshot || reviewResuming) return null;
  reviewResuming = true; render();
  const r = await act('automation.resume', {});
  reviewResuming = false;
  window.orch.toast(r.ok ? 'Automation is on again' : String(r.text || 'Could not turn it on. Try again.').slice(0, 200), r.ok ? 'ok' : 'error');
  if (r.ok && state) state.paused = null;
  render();
  return r;
}
function reviewPausedLine() {
  const p = state?.paused;
  if (!p || typeof p !== 'object' || snapshot) return null;
  const n = array(state.tickets).filter(t => t && t.status === 'ready').length, why = clean(p.reason || '').replace(/[.\s]+$/, '');
  const on = h('button', {type:'button', className:'btn outline sm', 'data-key':'review-paused-on', disabled:reviewResuming}, 'Turn on');
  on.onclick = reviewResume;
  return h('div', {className:'banner attn', role:'status', 'data-key':'review-paused'},
    h('p', {className:'grow'}, h('strong', {}, 'Automation is paused' + (why ? ': ' + why : '') + '.'),
      ' Nothing starts by itself.' + (n ? ' ' + n + (n === 1 ? ' ticket waits' : ' tickets wait') + ' for a helper.' : '')), on);
}
// The Auto Reviewer and Away (ORCH-425): two switches, each saves at once (only a person turns them on;
// `orch config set workflow.auto_reviewer` / `workflow.away`). Tickets with Human review needed are left alone.
// ORCH-1798 (owner, 24 Nov): both are off by default and turned on in Settings; the Review page shows the card only
// while one is on (so it can be turned off there too). Plain words that fit any workspace; the fixed list of what
// always waits (autoreview.AWAY_STAYS) stays fixed (R4.4).
const reviewSwitchBusy = new Set();
const REVIEW_SWITCHES = {
  auto:{op:'auto_reviewer.set', field:'auto_reviewer_on', action:'auto-reviewer-set', title:'Check finished work',
    meta:'When a ticket is finished, a helper checks the work against its Done when and accepts it or sends it back with the reason. Tickets with “I review the result” on wait for you.'},
  away:{op:'away.set', field:'away_on', action:'away-set', title:'Away for the night',
    meta:'Also answers open questions with the suggested answer. Anything about money, wording, sending or sharing with others, deleting, or logins and keys always waits for you.'},
  // Reviewer mode (owner, 25 Nov 2026): off = the Reviewer accepts complete work and sends open work back (each with Undo)
  propose:{op:'reviewer_mode.set', field:'reviewer_propose_on', action:'reviewer-mode-set', title:'Nothing closes by itself',
    meta:'The Reviewer only proposes: finished work it checked waits under Checked by the Reviewer, and you accept or send it back with one click.'}
};
const REVIEW_AUTO_NOTE = 'Each verdict shows in the ticket\u2019s history, and you can undo it on Review under Answered.';
function reviewSwitchRow(key, where = 'review') {
  const sw = REVIEW_SWITCHES[key], on = state?.settings?.[sw.field] === true;
  return h('div', {className:'card-row', 'data-key':where + '-auto-' + key},
    h('div', {className:'grow'}, h('h3', {}, sw.title), h('p', {className:'meta'}, sw.meta)),
    h('span', {className:'switch-text', 'aria-hidden':'true'}, on ? 'On' : 'Off'),
    h('button', {type:'button', className:'switch', role:'switch', 'aria-label':sw.title, 'aria-checked':on, 'data-key':where + '-switch-' + key, 'data-action':sw.action, disabled:snapshot || reviewSwitchBusy.has(key)}));
}
// One set of rows for both places (R4.3): the Review card and Settings > General.
function reviewAutoRows(where = 'review') {
  return [reviewSwitchRow('auto', where), reviewSwitchRow('away', where), reviewSwitchRow('propose', where),
    h('div', {className:'card-row', 'data-key':where + '-auto-note'}, h('p', {className:'meta'}, REVIEW_AUTO_NOTE))];
}
function reviewAutoOn() {
  const s = state?.settings;
  return !!s && (s.auto_reviewer_on === true || s.away_on === true || s.reviewer_propose_on === true);
}
function reviewAutoCard() {
  if (!reviewAutoOn()) return null;
  return card('review-auto', 'Auto Reviewer', '', reviewAutoRows('review'));
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
  // ORCH-1687: a helper that could not start is in the number (Home's Try again row), so it is listed here too
  array(n.failed).forEach(([t, sf]) => add(t, 'failed', clean(sf?.text || '')));
  // orch's own count lists questions (with their id) and results (without one); an older core: Home's rows and results
  for (const it of array(n.askedItems)) {
    const t = ticketOf(it.ticket), q = it.question ? array(t?.questions).find(x => x && x.id === it.question && x.answer == null) : null;
    if (!it.question && it.start) continue;  // listed above as a helper that could not start (n.failed)
    // work that stopped is Home's row (#2385), never "A result to check"; its stuck card is the card (carded above). The core
    // can count a stop Home has no row for (ORCH-2339): that one is listed here, so the badge and the heading still add up
    if (!it.question && it.stopped) { add(t, 'stopped', 'Work stopped. Open the ticket to see where.'); continue; }
    if (!it.question && n.fromCore) add(t, 'result', 'A result to review.');
    else add(t, 'question', q ? clean(q.text) : 'Waits for your answer.');
  }
  if (!n.fromCore) array(n.review).filter(t => !n.unsure?.has?.(t.id)).forEach(t => add(t, 'result', 'A result to review.'));
  return out;
}
// ORCH-1643: a question with two or three choices (a helper's on its screen too, when its ticket carries it) is answered in its row with one click: the same question card as the
// live pane (liveAskFill, pages/live-layer.js), mounted after the paint (mountReview). Anything else keeps one line.
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
    : h('a', {className:'btn outline sm', href:'#ticket/' + encodeURIComponent(r.t.id), 'data-key':'review-extra-open-' + r.t.id}, r.what === 'result' ? 'Review' : r.what === 'failed' ? 'Open' : 'Answer');
  return card('review-extra', 'Also waiting for you', '',
    rows.map(r => reviewOneClick(r)
      ? h('div', {className:'card-row', 'data-key':'review-extra-' + r.t.id, 'data-what':r.what},
        h('div', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(r.t, h), clean(r.t.title)),
          h('div', {className:'live-ask', 'data-review-ask':r.t.id, 'data-key':'review-ask-' + r.t.id})))
      : h('div', {className:'card-row', 'data-key':'review-extra-' + r.t.id, 'data-what':r.what},
        h('div', {className:'grow'}, h('strong', {}, window.DashHelpers.keyTag(r.t, h), clean(r.t.title)),
          h('p', {className:'meta'}, r.text)), act(r))));
}
// ORCH-1804 (draft for the owner's pick): "Open ticket" on a card shows its ticket beside the deck (#review?ticket=<id>),
// so Review stays where it is. The panel is the ticket page itself (detail(), pages/ticket.js), on the left in place of
// All cards; Close or Back hides it, "Open full page" goes to #ticket/<id>. While it is open it follows the card on screen.
const REVIEW_TICKET = /^t_[a-z0-9]{6,16}$/;
// the parts of the Review address after '?', as written (card=..., ticket=...)
function reviewQuery() {
  const full = typeof location === 'undefined' ? '' : String(location.hash || ''), at = full.indexOf('?');
  return at < 0 ? [] : full.slice(at + 1).split('&').filter(Boolean);
}
function reviewTicketId() {
  const part = reviewQuery().find(p => p.startsWith('ticket=')), id = part ? part.slice(7) : '';
  return REVIEW_TICKET.test(id) ? id : '';
}
// the Review address with this ticket beside the deck ('' = closed); the card the page opened on (?card=) stays.
// ORCH-2185: tab (chat | helper, the Ticket tab is the plain address) and term (a plain terminal Run it started)
function reviewTicketHref(id, tab = '', term = '') {
  const rest = reviewQuery().filter(p => !/^(ticket|tab|term)=/.test(p));
  if (REVIEW_TICKET.test(String(id || ''))) {
    rest.push('ticket=' + id);
    if (REVIEW_TABS.includes(tab) && tab !== 'ticket') rest.push('tab=' + tab);
    if (tab === 'helper' && REVIEW_TICKET.test(String(term || ''))) rest.push('term=' + term);
  }
  return '#review' + (rest.length ? '?' + rest.join('&') : '');
}
// ORCH-2431: "Not now" on a question card parks its ticket (pick a day, or until the person brings it back); the card
// leaves Review with it. Only a ticket's own question: a result to check or a stuck ticket is not put off this way.
function reviewNotNow(it) {
  const id = String(it?.id || ''), t = it?.ticketId ? ticketOf(it.ticketId) : null;
  if (!t || !id.startsWith('core:q:') || typeof askNotNow !== 'function') return null;
  return () => askNotNow(ticketOf(t.id));
}
// ---- ORCH-2185 (Focused review D, behind workflow.decision_first): the panel beside the card has three tabs ----
// Ticket (the ticket page, as before), Chat (the ticket's chat with its message box; "Ask about this" in the card's
// More opens it with "About: <the decision>" in the box) and "What the helper does" (the helper's live screen,
// watching until "Let me type"; "Terminal" when the plain terminal's typing setting is on). It follows the card on
// screen and keeps its tab. Run it on a sign-in card shows the plain terminal there. A phone keeps the live layer.
const REVIEW_TABS = ['ticket', 'chat', 'helper'];
const reviewPanelTabsOn = () => !snapshot && state?.settings?.decision_first_on === true;
const reviewQueryPart = k => { const p = reviewQuery().find(x => x.startsWith(k + '=')); return p ? p.slice(k.length + 1) : ''; };
function reviewPanelTab() {
  const tab = reviewQueryPart('tab');
  return reviewPanelTabsOn() && REVIEW_TABS.includes(tab) ? tab : 'ticket';
}
const reviewPanelTerm = () => { const id = reviewQueryPart('term'); return REVIEW_TICKET.test(id) ? id : ''; };
const reviewHelperWord = () => state?.settings?.terminal_typing_on === true ? 'Terminal' : 'What the helper does';
// a helper with a live screen works on this ticket now (a one-step helper has none)
const reviewHelperLive = t => { const run = t ? state?.runs?.[t.id] : null; return !!(run?.running && run.claim?.mode !== 'oneshot'); };
const reviewChatDrafts = new Map();  // ticket id -> the words in the panel's message box
let reviewChatFocus = '';            // the panel's box gets the cursor once it shows (Ask about this)
let reviewCurrentTicket = '';        // the ticket of the card on screen (Run it opens its panel)
function reviewTabsNav(id, tab) {
  return h('nav', {className:'segmented review-ticket-tabs', 'aria-label':'Show', 'data-key':'review-ticket-tabs'},
    [['ticket', 'Ticket'], ['chat', 'Chat'], ['helper', reviewHelperWord()]].map(([k, word]) =>
      h('a', {className:'btn sm', href:reviewTicketHref(id, k, k === 'helper' && tab === 'helper' ? reviewPanelTerm() : ''), 'aria-current':k === tab ? 'true' : null, 'data-key':'review-tab-' + k}, word)));
}
// Chat: the ticket's chat lines (pages/ticketchat.js draws each), its questions as plain lines (the card beside
// answers them), and the one message box; sending is the Chats page's own send (tcSay).
function reviewPanelChat(t) {
  if (typeof tcItems !== 'function') return h('p', {className:'meta'}, 'The chat is not here.');
  const items = tcItems(t), g = typeof tcGroupOf === 'function' ? tcGroupOf(t) : null;
  const row = (item, prev) => item.kind === 'line' ? tcLine(item, prev, g) : item.kind === 'answer' ? tcAnswer(item, prev, g)
    : item.kind === 'event' ? h('div', {className:'chat-system', 'data-key':'review-chat-' + item.key}, item.text)
    : tcLineShell(item, prev, g, h('div', {className:'thread-line-text'}, clean(item.q.text)));
  const closed = ['done', 'dropped'].includes(t.status);
  return h('div', {className:'review-panel-chat', 'data-key':'review-chat-' + t.id},
    h('div', {className:'review-panel-log', role:'log', 'aria-live':'polite', 'aria-label':'Ticket chat', 'data-key':'review-chat-log-' + t.id},
      items.length ? items.map((item, i) => row(item, items[i - 1])) : h('p', {className:'meta', 'data-key':'review-chat-empty'}, 'No messages yet. Write to your helper below.')),
    closed ? h('p', {className:'meta', 'data-key':'review-chat-closed'}, 'This ticket is closed · you can read, not reply')
      : h('div', {className:'review-panel-box', 'data-review-chat-box':t.id, 'data-key':'review-chat-box-' + t.id}));
}
// What the helper does: the helper's live screen (or the plain terminal Run it started), mounted after the paint.
function reviewPanelHelper(t) {
  const term = reviewPanelTerm();
  if (term) return h('div', {className:'review-panel-term', 'data-review-term':term, 'data-review-plain':'yes', 'data-key':'review-term-' + term});
  if (reviewHelperLive(t)) return h('div', {className:'review-panel-term', 'data-review-term':t.id, 'data-key':'review-term-' + t.id});
  return h('div', {className:'empty-state', 'data-key':'review-helper-none'},
    h('strong', {}, 'No helper works on this now'),
    h('p', {}, 'What it did is on the Ticket tab. Write in Chat and a helper starts and reads it.'),
    h('a', {className:'btn outline sm', href:reviewTicketHref(t.id, 'chat'), 'data-key':'review-helper-chat'}, 'Open Chat'));
}
// "Ask about this" and "Watch the helper" in a decision-first card's More menu (UI.swipeDeck o.moreItems)
function reviewMoreItems(it) {
  const id = String(it?.ticketId || '');
  if (!reviewPanelTabsOn() || !REVIEW_TICKET.test(id)) return [];
  const out = [{label:'Ask about this', icon:'comment', key:'review-ask-' + id, href:reviewTicketHref(id, 'chat'), onClick:() => reviewAsk(it)}];
  if (reviewHelperLive(ticketOf(id))) out.push({label:'Watch the helper', icon:'code', key:'review-watch-' + id, href:reviewTicketHref(id, 'helper')});
  return out;
}
// Ask about this: the panel's message box starts with "About: <the decision>" (never over words already typed)
function reviewAsk(it) {
  const id = it.ticketId, q = clean(it.text || it.title || '').replace(/\s+/g, ' ').trim();
  const words = 'About: ' + (q.length > 160 ? q.slice(0, 159) + '…' : q) + '\n';
  if (!String(reviewChatDrafts.get(id) || '').trim()) reviewChatDrafts.set(id, words);
  reviewChatFocus = id;
  const field = typeof document === 'object' && document.querySelector ? document.querySelector('[data-review-chat-box="' + id + '"] textarea') : null;
  if (field) { if (!field.value.trim()) { field.value = reviewChatDrafts.get(id); field.dispatchEvent(new Event('input', {bubbles:true})); } field.focus(); reviewChatFocus = ''; }
}
// Run it on Review with the panel: the terminal shows in the panel's helper tab beside the card (true), not on a phone
function reviewPanelRun(term, ticket) {
  const id = REVIEW_TICKET.test(String(ticket || '')) ? ticket : reviewCurrentTicket;
  if (!reviewPanelTabsOn() || !REVIEW_TICKET.test(String(id || '')) || typeof route !== 'function' || route().kind !== 'review') return false;
  if (typeof liveLayerPhone === 'function' && liveLayerPhone()) return false;
  location.hash = reviewTicketHref(id, 'helper', term);
  return true;
}
// After the paint: the panel's message box and terminal (each once per host; the paint leaves a mounted host alone)
function mountReviewPanel(main) {
  main.querySelectorAll('[data-review-chat-box]').forEach(host => {
    if (mounts.has(host) || !window.UI?.composer) return;
    const id = host.dataset.reviewChatBox, t = ticketOf(id), shared = typeof tcShared === 'function' && typeof tcGroupOf === 'function' && tcShared(tcGroupOf(t));
    const label = shared ? 'Message everyone in this chat' : 'Message your helper about this ticket';
    host.id = 'review-chat-box-' + id;
    const composer = window.UI.composer(host, {voice:false, layout:'box', attach:false, interrupt:false, enterSends:true, sendLabel:'Send', hint:'Enter to send',
      label, placeholder:label, maxLength:2000, emptyError:'Write something first.', sendingText:'', sendAttrs:{'data-key':'review-chat-send'},
      draft:reviewChatDrafts.get(id) || '', onDraft:v => { reviewChatDrafts.set(id, v); },
      onSend:async m => {
        const now = ticketOf(id), text = String(m?.text || '').trim();
        if (!now || typeof tcSay !== 'function') return {ok:false, text:'Not sent. Open the ticket and try again.'};
        const r = await tcSay(now, text, []);
        if (r.ok) reviewChatDrafts.delete(id);
        return r;
      }});
    mounts.set(host, {destroy() { composer?.destroy?.(); }});
    if (reviewChatFocus === id) { reviewChatFocus = ''; const f = host.querySelector('textarea'); if (f) { f.focus(); f.setSelectionRange?.(f.value.length, f.value.length); } }
  });
  main.querySelectorAll('[data-review-term]').forEach(host => {
    if (mounts.has(host)) return;
    const id = host.dataset.reviewTerm, plain = host.dataset.reviewPlain === 'yes';
    mounts.set(host, {destroy() {}});
    const shown = window.LiveTerm?.mount ? window.LiveTerm.mount(host, id, plain ? 'Plain terminal' : 'the helper', plain) : false;
    if (!shown) host.append(h('p', {className:'meta', 'data-key':'review-term-elsewhere'}, window.LiveTerm?.mount ? 'This screen is open in the live view. Close it there to watch it here.' : 'The live screen is not here.'));
  });
}
function reviewTicketPanel(id) {
  if (!id || snapshot || typeof detail !== 'function') return null;
  const t = ticketOf(id), body = t ? detail(t) : typeof missingTicket === 'function' ? missingTicket(id) : null;
  // one h1 on the page (Review's): the ticket's own title reads as a heading inside the panel
  body?.querySelectorAll?.('h1').forEach(n => n.setAttribute('aria-level', '2'));
  const tabs = reviewPanelTabsOn() && t, tab = tabs ? reviewPanelTab() : 'ticket';
  const shown = tab === 'chat' ? reviewPanelChat(t) : tab === 'helper' ? reviewPanelHelper(t) : body;
  return h('aside', {className:'card review-ticket', 'data-key':'review-ticket', 'aria-label':'Ticket', 'data-tab':tabs ? tab : null},
    h('div', {className:'review-ticket-h'}, tabs ? reviewTabsNav(id, tab) : h('h2', {}, 'Ticket'),
      // with the tabs a small icon (the row is full); on Chat it opens the whole chat
      tabs ? h('a', {className:'btn ghost icon sm', href:(tab === 'chat' ? '#chat/' : '#ticket/') + encodeURIComponent(id), 'aria-label':'Open full page', title:'Open full page', 'data-key':'review-ticket-full'}, iconEl('external'))
        : h('a', {className:'btn ghost sm', href:'#ticket/' + encodeURIComponent(id), 'data-key':'review-ticket-full'}, 'Open full page'),
      h('a', {className:'btn ghost icon sm', href:reviewTicketHref(''), 'aria-label':'Close ticket', title:'Close', 'data-key':'review-ticket-close'}, iconEl('x'))),
    h('div', {className:'review-ticket-b', 'data-key':'review-ticket-' + id + (tab === 'ticket' ? '' : '-' + tab)}, shown));
}
// the panel follows the card on screen: a new card (answered, Later, a click in All cards) shows its own ticket
function reviewTicketFollow(deck) {
  const open = reviewTicketId(), it = deck && !deck.picking ? array(deck.items)[deck.index] : null;
  if (it && !deck.answers?.[it.id] && REVIEW_TICKET.test(String(it.ticketId || ''))) reviewCurrentTicket = it.ticketId;
  if (!open || !it || deck.answers?.[it.id] || !REVIEW_TICKET.test(String(it.ticketId || '')) || it.ticketId === open) return false;
  history.replaceState(history.state, '', reviewTicketHref(it.ticketId, reviewPanelTab()));  // the same tab (ORCH-2185)
  setTimeout(render, 0);
  return true;
}
let reviewDrawnNarrow = null;  // how the page was last drawn (the layout watcher below draws again only on a change)
function reviewPage() {
  const open = snapshot ? '' : reviewTicketId(), narrow = reviewDrawnNarrow = reviewNarrow(), answered = (reviewView = reviewViewNow()) === 'answered';
  // the page's own list: an aside beside the card (wide), or a card after it in the same scroll (narrow). The kit's
  // deck.drawList with its Compare button is not used any more (O-06).
  const queue = () => h('div', {className:'review-queue', 'data-review-queue':''});
  const side = narrow ? null : h('aside', {className:'card review-side', 'data-key':'review-side', 'data-review-side':'', 'aria-label':'Needs you'}, queue());
  const next = narrow ? h('section', {className:'card', 'data-key':'review-next', 'data-review-next':'', 'data-review-side':'', 'aria-label':'Needs you', hidden:true}, queue()) : null;
  // Same order in every layout (W-036): the card with its buttons, the list, the Reviewer's line. What has no card of
  // its own is listed after the card (W-039: never pushed in above the decision); the Reviewer's history and what
  // closed by itself are the first blocks of Answered (O-04).
  const main = h('div', {className:'review-main stack', 'data-key':'review-main'},
    h('div', {'data-review-nav':'', 'data-key':'review-nav'}),
    answered ? reviewAcceptedCard() : null, answered ? reviewClosedCard() : null,
    h('div', {'data-review-host':'', 'data-key':'review-host'}),
    answered ? null : reviewExtraCard(), answered ? null : next);
  const rail = h('div', {className:'stack review-rail', 'data-key':'review-rail'}, side, reviewAutoCard());
  return fragment(
    heading('Review', reviewSubtitle()),
    reviewPausedLine(),
    // The card comes before the list in the page in every layout, so Tab reaches the decision first (W-036). Wide: the
    // master still stands the list on the left; an open ticket takes the list's place (ORCH-1804). Narrow: one column.
    h('div', {className:'review-layout' + (open ? ' with-ticket' : ''), 'data-key':'review-layout', 'data-narrow':narrow ? 'yes' : null},
      open ? reviewTicketPanel(open) : null, main, rail));
}
// FX-04: results whose pull request is on its way in (in the merge queue, or its checks only just passed) have no card
// here: one quiet line under the list.
function reviewQueueLine() {
  const n = array(state?.counts?.needs_you?.queue).length;
  return n ? h('p', {className:'meta grow', 'data-key':'review-queue-line'}, n + (n === 1 ? ' waits' : ' wait') + ' to be merged, nothing to do') : null;
}
function reviewSetWaiting(main, deck) {
  reviewWaiting = deck ? Math.max(0, array(deck.items).length - Object.keys(deck.answers || {}).length) : null;
  const sub = main.querySelector('[data-key="heading"] p.muted');
  if (sub && sub.textContent !== reviewSubtitle()) sub.textContent = reviewSubtitle();
}
// Mount the kit page once per host (render() calls this after every reconcile; the mounted host is left alone).
function mountReview(main) {
  // the list's place and the place of the Waiting / Answered switch are filled once and left alone by the paint
  main.querySelectorAll('[data-review-side],[data-review-nav]').forEach(s => { if (!mounts.has(s)) mounts.set(s, {destroy() {}}); });
  // a list place the paint just made (the window crossed a width, the Focus panel opened) is drawn from the deck on screen
  main.querySelectorAll('[data-review-queue]').forEach(q => { if (!q.childNodes?.length && reviewDeck) reviewDrawSide(q, reviewDeck); });
  reviewKeepPlace(main);
  // the one-click question rows: the paint leaves a mounted host alone; its card redraws only when the question changes
  main.querySelectorAll('[data-review-ask]').forEach(box => {
    if (!mounts.has(box)) mounts.set(box, {destroy() {}});
    if (typeof liveAskFill === 'function') liveAskFill(box, box.dataset.reviewAsk);
  });
  main.querySelectorAll('[data-review-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.reviewPage) return;
    const queue = () => main.querySelector('[data-review-queue]');  // looked up at each change: a narrow page has another place
    const nav = main.querySelector('[data-review-nav]') || undefined;
    const want = /[?&]card=([^&]+)/.exec(typeof location === 'undefined' ? '' : location.hash || '');  // the ticket page's "Look and answer" opens this card
    // with helpers waiting on their screen (listed above the deck) the empty deck does not say "Nothing waits for you"
    // ORCH-1643: never "No cards to check" beside things that wait: the list above says it all
    const empty = () => reviewExtraRows().length ? {title:'No other cards', text:'What waits for you is listed above.'} : null;
    // nav: the switch stands above the Reviewer's blocks of Answered; compare:false: no Compare in the kit's own lists (O-06)
    const page = window.UI.reviewPage(host, reviewApi(), {poll:3000, nav, compare:false, empty, extra:() => reviewExtraRows().length, startId:want ? decodeURIComponent(want[1]) : null, onChange:deck => { reviewDrawSide(queue(), deck); reviewSetWaiting(main, deck); reviewTicketFollow(deck); }, ticketHref:id => '#ticket/' + encodeURIComponent(id), ticketPanel:snapshot ? undefined : id => reviewTicketHref(id), notNow:snapshot ? undefined : reviewNotNow, decisionFirst:() => state?.settings?.decision_first_on === true, moreItems:snapshot ? undefined : reviewMoreItems});
    mounts.set(host, {destroy() { reviewWaiting = null; reviewDeck = null; reviewListFrom = 0; reviewListAll = false; reviewListCur = ''; reviewListOpen.clear(); reviewPanelWas = null; page.destroy(); }, page});
  });
  mountReviewPanel(main);
}
// W-039: opening or closing the ticket beside the card keeps the page where it is (the shell scrolls a changed address
// to the top), the keyboard goes to the panel's Close and back to the card, and Esc closes the panel.
let reviewKeepY = null, reviewPanelWas = null;  // null: the page was just opened (a link straight to a ticket moves no keyboard place)
function reviewKeepPlace(main) {
  const open = snapshot ? '' : reviewTicketId();
  if (reviewKeepY != null && typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
    const keep = reviewKeepY; reviewKeepY = null;
    // only the paint that follows the click at once (a click that changed nothing must not pull a later paint back)
    if (Date.now() - keep.at < 1500) setTimeout(() => window.scrollTo(0, keep.y), 0);  // after the shell's own scroll at the end of this paint
  }
  if (open !== reviewPanelWas) {
    // the keyboard moves only when the panel opens or closes; a panel that follows the next card leaves it on the deck
    const to = reviewPanelWas == null ? '' : open && !reviewPanelWas ? '[data-key="review-ticket-close"]' : !open && reviewPanelWas ? '[data-review-host] .swipe-more summary' : '';
    reviewPanelWas = open;
    if (to) setTimeout(() => (main.querySelector(to) || main.querySelector('#deck'))?.focus?.({preventScroll:true}), 0);
  }
}
function reviewCloseTicket() {
  if (typeof location === 'undefined' || !reviewTicketId()) return false;
  reviewKeepY = {y:typeof window !== 'undefined' ? window.scrollY || 0 : 0, at:Date.now()};
  location.hash = reviewTicketHref('');
  return true;
}
if (typeof document !== 'undefined' && document.addEventListener) {
  // a click that opens, closes or changes the ticket beside the card: remember where the page stands
  document.addEventListener('click', e => {
    const a = e.target.closest?.('a[href^="#review"]');
    if (a && typeof route === 'function' && route().kind === 'review' && (/[?&]ticket=/.test(a.getAttribute('href')) || reviewTicketId())) reviewKeepY = {y:window.scrollY || 0, at:Date.now()};
    // Waiting / Answered (also the empty page's "See answers"): the page's own blocks follow the view on screen
    if (e.target.closest?.('[data-review-nav],[data-review-host]')) setTimeout(() => { if (reviewViewNow() !== reviewView && typeof route === 'function' && route().kind === 'review') render(); }, 0);
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.defaultPrevented || typeof route !== 'function' || route().kind !== 'review' || !reviewTicketId()) return;
    // Esc first closes what is open on top (a dialog, a menu, a sheet of the card) and leaves a text field alone
    if (document.querySelector('dialog[open]') || e.target.closest?.('textarea,input,select,[contenteditable],details[open],[role="menu"],[role="listbox"],.swipe-viewer,.swipe-sheet')) return;
    if (reviewCloseTicket()) e.preventDefault();
  });
}
// The list changes its place when the page area crosses a width or the Focus panel opens beside it. The shell writes
// its marks again at every paint (pages/live-layer.js liveLayerPad), and a watcher sees every write: the page is drawn
// again only when the layout really differs from the one on screen, so a paint can never start the next paint.
function reviewLayoutChanged() {
  if (typeof route !== 'function' || typeof render !== 'function' || route().kind !== 'review' || reviewDrawnNarrow == null) return false;
  if (reviewNarrow() === reviewDrawnNarrow) return false;
  render();
  return true;
}
if (typeof window !== 'undefined' && typeof document !== 'undefined' && document.body) {
  if (typeof matchMedia === 'function') matchMedia('(max-width:720px)').addEventListener?.('change', reviewLayoutChanged);
  if (typeof MutationObserver === 'function') new MutationObserver(reviewLayoutChanged).observe(document.body, {attributes:true, attributeFilter:['data-live-narrow', 'data-live-stack']});
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
