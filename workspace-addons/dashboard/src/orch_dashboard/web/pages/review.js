'use strict';
// Review (#review): everything that waits for a decision, one card at a time (the kit's UI.reviewPage), with the
// "All cards" list beside it on a wide screen. The cards and the decisions come with the state (state.review, from
// `orch review list`); an answer is a plain click (op review.answer).
const REVIEW_ID = /^core:(?:q:(t_[a-z0-9]{6,16}):(q[0-9]{1,4})|review:(t_[a-z0-9]{6,16}))$/;
function reviewCards() { return array(state?.review?.cards).map(reviewPlainCard); }
// A Factory proposal reads like Home's card (ORCH-183): its title as the question, the goal and the time in two short
// lines, not the whole frozen proposal (that stays on the ticket). Any other card is left as it is.
function reviewPlainCard(c) {
  const p = c && typeof c.text === 'string' ? window.DashHelpers?.factoryStart?.(c.text) : null;
  if (!p) return c;
  return {...c, text:p.goal + (p.meta ? '\n' + p.meta : ''), card:{...(c.card || {}), title:"Start '" + p.title + "'?"}};
}
function reviewAnswered() { return array(state?.review?.answered); }
// The cards of the stack: every open question (an add-on's own too, e.g. Factory's Start?) and every result to check.
function reviewCount() { return reviewCards().length; }
// The subtitle shows THE needs-you number (needsYouTotal: open questions plus results to check, exactly what this page
// shows as cards; the Review menu entry and the top bar show the same one, ORCH-63).
function reviewSubtitle() {
  const n = typeof needsYouTotal === 'function' ? needsYouTotal() : reviewCount();
  return n ? n + (n === 1 ? ' thing waits' : ' things wait') + ' on you, most urgent first.' : 'Nothing waits for you.';
}
// The words the "All cards" list shows for an answered card (the same as the deck's own summary).
function reviewWord(answer) {
  const it = answer.item || {}, note = answer.note || {};
  if (answer.verdict === 'ok') return note.picked ? 'Use ' + note.picked : it.okLabel || 'Looks good';
  if (answer.verdict === 'no') return it.preview?.type === 'options' ? 'None' : it.kind === 'check' ? 'Sent back' : "Don't do";
  return 'Sent back';
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
        : '/api/file?t=' + encodeURIComponent(c.ticket) + '&k=' + f[1] + '&n=' + encodeURIComponent(f[2]);
    },
    answer: async ({id, digest, verdict, picked, note}) => {
      const m = REVIEW_ID.exec(String(id || ''));
      if (!m) return {ok:false, error:{code:'not_found', message:'That card is not here any more.'}};
      const args = {ticket:m[1] || m[3], key:m[2] || 'review', verdict, digest};
      if (picked) args.picked = picked;
      if (note) args.note = note;
      const r = await act('review.answer', args);
      if (r.ok) return {ok:true};
      if (r.status === 403) return {ok:false, error:{code:'needs_person', message:r.text}};
      try {
        const body = JSON.parse(r.text);
        if (body?.error?.code) return {ok:false, error:body.error};
      } catch (_) { /* a plain refusal below */ }
      return {ok:false, error:{code:r.status === 400 ? 'refused' : 'error', message:String(r.text || 'Could not save your answer.').slice(0, 300)}};
    }
  };
}
// The deck list: one section per set of cards (the helper's group, else the ticket) with its own count, one line
// per card, the one on screen in bold, answered ones quiet with their word.
function reviewGroupOf(it) { return it.group || it.ticketTitle || it.ticket || ''; }
function reviewDrawSide(queue, deck) {
  if (!queue || !deck) return;
  const groups = new Map();
  deck.items.forEach((it, i) => {
    const key = reviewGroupOf(it);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(i);
  });
  const row = i => {
    const it = deck.items[i], a = deck.answers[it.id], r = el('button', 'btn ghost sm review-queue-row' + (i === deck.index && !a ? ' is-now' : '') + (a ? ' is-done' : ''));
    r.type = 'button'; r.setAttribute('role', 'listitem');
    const title = el('span', 'review-queue-title', it.title); title.title = it.title;  // two lines, and the whole title on hover (F4: cut titles looked repeated)
    r.append(iconEl(it.icon), title);
    const word = a ? reviewWord(a) : i === deck.index ? 'Now' : '';
    if (word) r.append(el('span', 'swipe-ov-state ' + (a ? a.verdict : 'wait'), word));
    r.onclick = () => deck.jump(i);
    return r;
  };
  const one = groups.size < 2;
  queue.replaceChildren(...[...groups].map(([name, rows]) => {
    const sec = el('div', 'review-group');
    sec.setAttribute('role', 'list');
    sec.setAttribute('aria-label', name || 'Cards');
    if (!one || name) {
      const left = rows.filter(i => !deck.answers[deck.items[i].id]).length;
      const head = el('h3', 'review-group-head');
      head.append(el('span', '', name || 'Cards'), el('span', 'meta', left ? left + ' of ' + rows.length + ' waiting' : 'All ' + rows.length + ' answered'));
      sec.append(head);
    }
    sec.append(...rows.map(row));
    return sec;
  }));
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
    let busy = false;
    const input = h('input', {type:'text', className:'input', placeholder:'What should change?', 'aria-label':'What should change?'});
    const close = () => { if (busy) return; locks.delete(key); host.replaceChildren(head); open.focus(); };
    const send = h('button', {type:'button', className:'btn primary sm', disabled:true}, 'Send back');
    const cancel = h('button', {type:'button', className:'btn ghost icon', 'aria-label':'Cancel'}, iconEl('x'));
    send.onclick = async () => {
      if (!input.value.trim() || busy) return;
      busy = true; send.disabled = input.disabled = cancel.disabled = true;
      let ok = false;
      try { ok = await reviewSendBack(a, input.value); } finally { busy = false; input.disabled = cancel.disabled = false; send.disabled = !input.value.trim(); }
      if (ok) { locks.delete(key); render(); }
    };
    cancel.onclick = close;
    input.oninput = () => { send.disabled = busy || !input.value.trim(); };
    input.onkeydown = e => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send.click(); }
    };
    host.replaceChildren(head, h('div', {className:'ticket-ask-line'}, input, send, cancel));
    input.focus();
  };
  return host;
}
function reviewAcceptedCard() {
  const rows = reviewAccepted();
  if (!rows.length) return null;
  return card('review-accepted', 'Accepted for you', '', rows.map(reviewAcceptedRow));
}
function reviewPage() {
  const side = h('aside', {className:'card review-side', 'data-key':'review-side', 'data-review-side':''},
    h('h2', {}, 'All cards'),
    h('p', {className:'meta'}, 'Click one to jump there.'),
    h('div', {className:'review-queue', 'aria-label':'All cards', 'data-review-queue':''}));
  return fragment(
    heading('Review', reviewSubtitle()),
    h('div', {className:'review-layout', 'data-key':'review-layout'},
      h('div', {className:'review-main', 'data-key':'review-main'}, h('div', {'data-review-host':'', 'data-key':'review-host'})),
      h('div', {className:'stack', 'data-key':'review-rail'}, side, reviewAcceptedCard())));
}
// Mount the kit page once per host (render() calls this after every reconcile; the mounted host is left alone).
function mountReview(main) {
  main.querySelectorAll('[data-review-side]').forEach(s => { if (!mounts.has(s)) mounts.set(s, {destroy() {}}); });
  main.querySelectorAll('[data-review-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.reviewPage) return;
    const queue = main.querySelector('[data-review-queue]');
    const want = /[?&]card=([^&]+)/.exec(typeof location === 'undefined' ? '' : location.hash || '');  // the ticket page's "Look and answer" opens this card
    const page = window.UI.reviewPage(host, reviewApi(), {poll:3000, startId:want ? decodeURIComponent(want[1]) : null, onChange:deck => reviewDrawSide(queue, deck)});
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
