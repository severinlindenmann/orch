// Home: "Not now" on a question parks its ticket (ORCH-2431). The question leaves Home and Review and the Needs you
// number; Home lists the ticket under Parked with the reason; Bring back returns the question. All of it survives a
// reload.
module.exports = {
  name: 'Home: Not now parks a question, Bring back returns it',
  covers: ['page:home', 'ticket.patch'],
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
    await until(asks, 'the question on Home');
    const row = page.locator('[data-need-row="core:q:' + tid + ':q1"]');
    await row.getByRole('button', { name: 'Not now' }).click();
    const dlg = page.locator('dialog[open]');
    await dlg.getByText('Bring it back when?').waitFor();
    await act('ticket.patch', () => dlg.getByRole('button', { name: 'When I bring it back' }).click());
    await until(s => !asks(s) && parked(s), 'the question off Home and the ticket in the parked list');
    must(!(await page.locator('[data-need-row="core:q:' + tid + ':q1"]').count()), 'the parked question is still a row on Home');
    await reload();
    must(!(await page.locator('[data-need-row="core:q:' + tid + ':q1"]').count()), 'the parked question is back on Home after a reload');
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
    await until(s => asks(s) && !parked(s), 'the question back on Home');
    await reload();
    must(await page.locator('[data-need-row="core:q:' + tid + ':q1"]').count(), 'the question is not back on Home after Bring back and a reload');
    orchAsPerson('answer', tid, 'q1', 'It worked');  // leave nothing open for the click-throughs after this one
  },
};
