// Home: the questions of a Factory order answered one after the other with the suggested option, each click while
// the answer before it still waits in its Undo window, while the order also waits for its Start (ORCH-1047: the third
// answer went out for the first question and was refused "q1 is already answered."). Every answer must reach its
// own question.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Home: answer the questions of a Factory order in a row',
  covers: ['page:home', 'answer'],
  async run({ page, open, reload, must, orch, orchAsPerson, addonOn, addonOff, until, workspace }) {
    // the seeded lunch question is answered first, so the order's question is Home's first card
    for (const t of JSON.parse(orch('ticket', 'list', '--json'))) {
      for (const q of t.questions || []) if (q.answer == null && q.recommended) orchAsPerson('answer', t.id, q.id, q.recommended);
    }
    addonOn('factory');
    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'factory'), 'Factory on');
    const tid = JSON.parse(orchAsPerson('factory', 'idea', 'Weekly coffee shop newsletter template', '--json')).order;
    const asked = [
      ['What should the news story be?', 'Survey results', 'Spring menu'],
      ['Which colour for the header?', 'Brown', 'Green'],
      ['Which language should the newsletter be in?', 'English', 'German'],
    ];
    for (const [text, rec, other] of asked) orch('ask', tid, text, '--option', rec, '--option', other, '--recommend', rec);
    const repo = path.resolve(__dirname, '..', '..', '..', '..');
    const proposal = JSON.parse(fs.readFileSync(path.join(repo, 'contracts/examples/factory-proposal/valid-run.json'), 'utf8'));
    proposal.title = 'Newsletter template';
    const file = path.join(workspace, 'proposal-s.json');
    fs.writeFileSync(file, JSON.stringify(proposal));
    orch('factory', 'propose', tid, '--file', file, '--json');
    fs.unlinkSync(file);

    const refused = [], back = [];
    page.on('response', r => {
      if (!r.url().endsWith('/api/act')) return;
      if (r.status() !== 200) { r.text().then(t => refused.push(r.status() + ' ' + t)).catch(() => {}); return; }
      // the answer is saved: its card must not come back on Home (the click's answer held the old needs list)
      let q = null;
      try { const b = JSON.parse(r.request().postData() || '{}'); if (b.op === 'answer') q = b.args.question; } catch (_) { /* not an answer */ }
      if (!q) return;
      page.waitForTimeout(150).then(() => page.locator('[data-need-row="core:q:' + tid + ':' + q + '"]').count())
        .then(n => { if (n) back.push(q); }).catch(() => {});
    });
    for (const [text, rec] of asked) {
      await open('#home');
      const row = page.locator('[data-need-row^="core:q:' + tid + ':"]').filter({ hasText: text });
      await row.waitFor({ timeout: 10000 }).catch(async () => { throw new Error('no card "' + text + '" on Home:\n' + (await page.locator('main').innerText()).slice(0, 800)); });
      await row.getByRole('button', { name: new RegExp('^' + rec) }).click();
      await page.waitForTimeout(1500);  // a person goes on before the Undo window of this answer ends
    }
    await page.waitForTimeout(7000);  // every Undo window has ended and its answer was sent
    const t = JSON.parse(orch('ticket', 'show', tid, '--json'));
    const answers = (t.questions || []).slice(0, 3).map(q => q.id + '=' + q.answer);
    must(!refused.length, 'an answer from Home was refused: ' + refused.join(' | '));
    must(!back.length, 'answered questions came back on Home right after their answer was saved: ' + back.join(', '));
    must(answers.join(',') === 'q1=Survey results,q2=Brown,q3=English', 'not every question got its own answer: ' + answers.join(', '));
    await reload();
    await addonOff('factory');
  },
};
