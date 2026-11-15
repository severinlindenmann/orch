'use strict';
// Review (#review): everything that waits for a decision, one card at a time (the kit's UI.reviewPage), with the
// "All cards" list beside it on a wide screen. The cards and the decisions come with the state (state.review, from
// `orch review list`); an answer is a plain click (op review.answer).
const REVIEW_ID = /^core:(?:q:(t_[a-z0-9]{6,16}):(q[0-9]{1,4})|review:(t_[a-z0-9]{6,16}))$/;
function reviewCards() { return array(state?.review?.cards); }
function reviewAnswered() { return array(state?.review?.answered); }
// The one number of "things that wait on you" this page shows: the cards of the stack (the same questions and
// results to check that Home counts; Home's own total is not changed by this page).
function reviewCount() { return reviewCards().length; }
function reviewSubtitle() {
  const n = reviewCount();
  return n ? n + (n === 1 ? ' thing waits on you, most urgent first.' : ' things wait on you, most urgent first.') : 'Nothing waits for you.';
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
      const m = /^reviewed\/([0-9a-f]{12})\/([^/]+)$/.exec(String(ref || ''));
      return m && typeof c?.ticket === 'string'
        ? '/api/file?t=' + encodeURIComponent(c.ticket) + '&k=reviewed&n=' + encodeURIComponent(m[1] + '/' + m[2]) : '';
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
// The deck list: one line per card, the one on screen in bold, answered ones quiet with their word.
function reviewDrawSide(queue, deck) {
  if (!queue || !deck) return;
  queue.replaceChildren(...deck.items.map((it, i) => {
    const a = deck.answers[it.id], row = el('button', 'btn ghost sm review-queue-row' + (i === deck.index && !a ? ' is-now' : '') + (a ? ' is-done' : ''));
    row.type = 'button'; row.setAttribute('role', 'listitem');
    const icon = iconEl(it.icon);
    row.append(icon, el('span', 'review-queue-title', it.title));
    const word = a ? reviewWord(a) : i === deck.index ? 'Now' : '';
    if (word) row.append(el('span', 'swipe-ov-state ' + (a ? a.verdict : 'wait'), word));
    row.onclick = () => deck.jump(i);
    return row;
  }));
}
function reviewPage() {
  const side = h('aside', {className:'card review-side', 'data-key':'review-side', 'data-review-side':''},
    h('h2', {}, 'All cards'),
    h('p', {className:'meta'}, 'Click one to jump there.'),
    h('div', {className:'review-queue', role:'list', 'aria-label':'All cards', 'data-review-queue':''}));
  return fragment(
    heading('Review', reviewSubtitle()),
    h('div', {className:'review-layout', 'data-key':'review-layout'},
      h('div', {className:'review-main', 'data-key':'review-main'}, h('div', {'data-review-host':'', 'data-key':'review-host'})), side));
}
// Mount the kit page once per host (render() calls this after every reconcile; the mounted host is left alone).
function mountReview(main) {
  main.querySelectorAll('[data-review-side]').forEach(s => { if (!mounts.has(s)) mounts.set(s, {destroy() {}}); });
  main.querySelectorAll('[data-review-host]').forEach(host => {
    if (mounts.has(host) || !window.UI?.reviewPage) return;
    const queue = main.querySelector('[data-review-queue]');
    const page = window.UI.reviewPage(host, reviewApi(), {poll:3000, onChange:deck => reviewDrawSide(queue, deck)});
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
