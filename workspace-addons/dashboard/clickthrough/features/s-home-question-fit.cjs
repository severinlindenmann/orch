// Home at 390: a question with a long web address in it (a download link, as on ORCH-1497) wraps inside its card;
// nothing of the card (the question, its ticket line, the answer buttons, "Sub-ticket of ...") runs past the right
// edge of the phone (daily look report r-1123-0533-ws, ORCH-1713).
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Home: a question with a long web address fits the phone width',
  covers: ['page:home'],
  async run({ page, open, must, orch, orchAsPerson, shot }) {
    // every other open question is answered or taken back first, so this one is Home's full question card
    for (const t of JSON.parse(orch('ticket', 'list', '--json'))) {
      for (const q of t.questions || []) {
        if (q.answer != null) continue;
        try { orchAsPerson('answer', t.id, q.id, q.recommended || (q.options || [])[0] || 'OK'); }
        catch (_) { try { orch('ask', t.id, 'Not needed for this click-through.', '--take-back', q.id); } catch (_e) { /* a card stays */ } }
      }
    }
    const epic = idOf(orch('ticket', 'new', 'Meeting notes for the kitchen team'));
    const tid = idOf(orch('ticket', 'new', 'Try the new recorder on the office Mac', '--parent', epic));
    const link = 'https://downloads.example.com/releases/download/recorder-v0.1.0/Kitchen-Recorder-0.1.0-universal-build.zip';
    orch('ask', tid, 'Please try the recorder on your Mac (about 5 minutes). Download: ' + link + ' Then open it and say if it worked.',
      '--option', 'It worked', '--option', 'Something did not work', '--recommend', 'It worked');

    await page.setViewportSize({ width: 390, height: 844 });
    await open('#home');
    const row = page.locator('[data-need-row^="core:q:' + tid + ':"]');
    await row.waitFor({ timeout: 15000 });
    await row.getByRole('button', { name: /^It worked/ }).waitFor({ timeout: 10000 });
    const fit = await row.evaluate(card => {
      const vw = window.innerWidth;
      const over = [...card.querySelectorAll('h2, p, a, button')]
        .filter(e => e.getBoundingClientRect().width && e.getBoundingClientRect().right > vw + 1)
        .map(e => e.tagName + ' "' + (e.innerText || '').trim().slice(0, 40) + '"');
      return { over, page: document.documentElement.scrollWidth - vw };
    });
    await shot('question-390', row);
    await page.setViewportSize({ width: 1280, height: 900 });
    must(!fit.over.length, 'at 390 the question card runs past the right edge: ' + fit.over.join(', '));
    must(fit.page <= 1, `at 390 Home is ${fit.page} px wider than the phone`);
  },
};
