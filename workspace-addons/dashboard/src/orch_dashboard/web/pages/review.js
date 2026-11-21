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
function reviewCards() { return array(state?.review?.cards).map(reviewPlainCard); }
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
// The cards of the stack: every open question (an add-on's own too, e.g. Factory's Start?) and every result to check.
function reviewCount() { return reviewCards().length; }
// The subtitle shows THE needs-you number (needsYouTotal: open questions, results to check and work that stopped; the
// Review menu entry, the top bar, Home and the live bar show the same one, ORCH-63, ORCH-705).
function reviewSubtitle() {
  // A card put off on Home ("Later today") is not in the one number, but it is still a card here: the subtitle never
  // says "Nothing waits" above a Waiting tab with cards in it (ORCH-420, owner's picture 18 Nov).
  const n = (typeof needsYouTotal === 'function' ? needsYouTotal() : 0) || reviewCount();
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
    hold: (it, verdict) => acceptHold(it, verdict),
    release: it => acceptRelease(it, false),
    // ORCH-547: take back an answer someone gave for the person (the Answered list's "Answered for me"); the card waits again.
    undo: async ({id}) => {
      const m = REVIEW_ID.exec(String(id || ''));
      if (snapshot || !m || !m[2]) return {ok:false, error:{code:'not_found', message:'That answer is not here any more.'}};
      const r = await act('review.undo', {ticket:m[1], key:m[2]});
      return r.ok ? {ok:true} : {ok:false, error:{code:r.status === 403 ? 'needs_person' : 'error', message:String(r.text || 'Could not undo it.').slice(0, 300)}};
    },
    answer: async ({id, digest, verdict, picked, note}) => {
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
function reviewAcceptedRow(a) {
  const key = 'review-accepted-' + a.ticket;
  const host = h('div', {'data-key':key});
  const sent = a.sent_back === true || reviewSentBack.has(a.ticket);
  const open = sent || snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':key + '-send'}, 'Send back');
  // The reason takes the full card width under the title; Send back sits on its own line below it (the side
  // column is narrow at 1280).
  const head = h('div', {className:'card-row'},
    h('div', {className:'grow'},
      h('a', {href:'#ticket/' + encodeURIComponent(a.ticket)}, clean([a.key, a.title].filter(Boolean).join(' · '))),
      a.why ? h('p', {className:'meta'}, clean(a.why)) : null,
      sent ? h('p', {className:'meta'}, 'Sent back') : open ? h('div', {}, open) : null));
  host.append(head);
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
function reviewPage() {
  // the kit draws the list's header ("All cards", Compare / Cancel) and its rows into the queue (ORCH-477 round 2)
  const side = h('aside', {className:'card review-side', 'data-key':'review-side', 'data-review-side':'', 'aria-label':'All cards'},
    h('div', {className:'review-queue', 'data-review-queue':''}));
  return fragment(
    heading('Review', reviewSubtitle()),
    // the list on the left, the card (or the two ticked side by side) on the right (ORCH-477)
    h('div', {className:'review-layout', 'data-key':'review-layout'},
      h('div', {className:'stack review-rail', 'data-key':'review-rail'}, side, reviewAcceptedCard()),
      h('div', {className:'review-main', 'data-key':'review-main'}, h('div', {'data-review-host':'', 'data-key':'review-host'}))));
}
// Mount the kit page once per host (render() calls this after every reconcile; the mounted host is left alone).
function mountReview(main) {
  main.querySelectorAll('[data-review-side]').forEach(s => { if (!mounts.has(s)) mounts.set(s, {destroy() {}}); });
  main.querySelectorAll('[data-review-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.reviewPage) return;
    const queue = main.querySelector('[data-review-queue]');
    const want = /[?&]card=([^&]+)/.exec(typeof location === 'undefined' ? '' : location.hash || '');  // the ticket page's "Look and answer" opens this card
    const page = window.UI.reviewPage(host, reviewApi(), {poll:3000, startId:want ? decodeURIComponent(want[1]) : null, onChange:deck => reviewDrawSide(queue, deck), ticketHref:id => '#ticket/' + encodeURIComponent(id)});
    mounts.set(host, {destroy() { page.destroy(); }, page});
  });
}
// A new state (a card arrived, one was answered elsewhere): the open page reads it at once, not at its next tick.
if (typeof window !== 'undefined' && window.addEventListener) {
  window.addEventListener('orch:state', () => {
    if (typeof mounts === 'undefined') return;
    for (const m of mounts.values()) m.page?.tick?.();
  });
}
