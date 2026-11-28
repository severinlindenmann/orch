// "Not now" on a question parks its ticket (ORCH-2431). Since O-01 D (28 Nov) the question card and its Not now are on
// Review only; the question leaves Review and the Needs you number; Home lists the ticket under Parked with the
// reason; Bring back returns the question. All of it survives a reload.
module.exports = {
  name: 'Not now on Review parks a question, Home lists it, Bring back returns it',
  covers: ['page:home', 'page:review', 'ticket.patch'],
  async run({ page, open, reload, act, must, orch, orchAsPerson, until }) {
    // every other open question is answered or taken back first, so ours is Home's first card with its buttons
    for (const t of JSON.parse(orch('ticket', 'list', '--json'))) {
      for (const q of t.questions || []) {
        if (q.answer != null) continue;
        try { orchAsPerson('answer', t.id, q.id, q.recommended || (q.options || [])[0] || 'OK'); }
        catch (_) { try { orch('ask', t.id, 'Not needed for this click-through.', '--take-back', q.id); } catch (_e) { /* a card stays */ } }
      }
    }
    const tid = JSON.parse(orch('ticket', 'new', 'Not now walk: try the notebook kit', '--json')).id;
    orch('ask', tid, 'Did the notebook kit work on your notebook?', '--option', 'It worked', '--option', 'Something did not work');
    const asks = s => (s.needs || []).some(n => n.ticket === tid);
    const parked = s => (s.parked || []).some(r => r.ticket === tid);
    await open('#home');
    await until(asks, 'the question in the page state');
    const saysOne = () => page.waitForFunction(() => /\b1 question\b.* waits? in Review/.test(document.querySelector('[data-key="review-line"]')?.innerText || ''), null, { timeout: 15000 }).then(() => true, () => false);
    must(await saysOne(), 'Home does not say one question waits in Review: ' + await page.locator('[data-key="review-line"]').innerText());
    await open('#review?card=' + encodeURIComponent('core:q:' + tid + ':q1'));
    const card = page.locator('[data-key="review-host"] article.swipe-card:not(.under):not(.under2)').first();
    await card.getByText('Did the notebook kit work on your notebook?').waitFor({ timeout: 15000 });
    await page.locator('[data-key="review-host"]').getByRole('button', { name: 'Not now' }).first().click();
    const dlg = page.locator('dialog[open]');
    await dlg.getByText('Bring it back when?').waitFor();
    await act('ticket.patch', () => dlg.getByRole('button', { name: 'When I bring it back' }).click());
    await until(s => !asks(s) && parked(s), 'the question off the needs list and the ticket in the parked list');
    await open('#home');
    await reload();
    must(!/question/.test(await page.locator('[data-key="review-line"]').innerText()), 'the parked question still counts in Home\'s Review line');
    const line = page.locator('[data-key="needs-parked"]');
    must(/parked/.test(await line.innerText()), 'Home has no parked line');
    await line.getByRole('button', { name: 'Show' }).click();
    const item = page.locator('[data-key="parked-' + tid + '"]');
    must(/Until you bring it back/.test(await item.innerText()), 'the parked row does not say why it is parked');
    must(/1 question kept/.test(await item.innerText()), 'the parked row does not say its question is kept');
    await open('#review');
    must(!(await page.getByText('Did the notebook kit work on your notebook?').count()), 'the parked question is a card on Review');

    await open('#home');  // the parked list is still open (Show was pressed above)
    await page.locator('[data-key="parked-back-' + tid + '"]').waitFor();
    await act('ticket.patch', () => page.locator('[data-key="parked-back-' + tid + '"]').click());
    await until(s => asks(s) && !parked(s), 'the question back in the needs list');
    await reload();
    must(await saysOne(), 'the question is not back in Home\'s Review line after Bring back and a reload');
    orchAsPerson('answer', tid, 'q1', 'It worked');  // leave nothing open for the click-throughs after this one
  },
};
