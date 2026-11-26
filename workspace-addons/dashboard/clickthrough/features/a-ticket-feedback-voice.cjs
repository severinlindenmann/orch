// ORCH-422: richer feedback. On a ticket in Check the person presses Send back, writes a line, pastes a screenshot and
// drops a picture, tries a file kind that is refused, records a voice note (a fake microphone), and sends: the files are on the ticket and the ticket is back with the
// helper after a reload. Then on Review, Send back on another ticket's card opens the Comment sheet, it takes a voice note and "Add note" keeps
// it on that ticket while the card stays.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
const SHOTS = process.env.CT_SHOTS || '';  // a folder: pictures of the open boxes at 1280, 1920 and 390 (for the pull request)
async function shoot(page, name) {
  if (!SHOTS) return;
  const size = page.viewportSize();
  for (const [w, h] of [[1280, 800], [1920, 1080], [390, 844]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${SHOTS}/${name}-${w}.png` });
  }
  await page.setViewportSize(size);
}
async function newCheckTicket(page, open, act, title) {
  await open('#home');
  await page.getByRole('button', { name: 'New ticket' }).first().click();
  const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
  await dlg.getByPlaceholder(/What should the helper do/).fill(title);
  await act('ticket.new', () => dlg.getByRole('button', { name: 'Save ticket' }).click());
  await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
  await open('#tickets');
  await page.getByText(title).first().click();
  await page.getByRole('button', { name: 'Change title' }).waitFor();
  await page.getByLabel('More ticket actions').click();
  await act('ticket.patch', () => page.getByRole('menuitem', { name: 'Check', exact: true }).click());
  return decodeURIComponent(/#ticket\/([^/?&]+)/.exec(page.url())[1]);
}
async function record(page, scope) {
  await scope.getByRole('button', { name: 'Record a voice note' }).click();
  await scope.getByRole('button', { name: 'Stop recording' }).waitFor();
  await page.waitForTimeout(1600);
  await scope.getByRole('button', { name: 'Stop recording' }).click();
  await scope.locator('.attachment-tile', { hasText: /voice-note-\d{4}\.webm/ }).waitFor();
}
module.exports = {
  name: 'Send back and Add note with a screenshot and a voice note',
  covers: ['ticket.attach', 'ticket.changes', 'run.send', 'page:ticket', 'page:review'],
  async run({ page, open, reload, act, must, text }) {
    await newCheckTicket(page, open, act, 'Redo the lunch flyer');
    await page.getByRole('button', { name: 'Send back', exact: true }).click();
    const box = page.locator('[id^=ticket-changes-box-]');
    await box.getByLabel('What should change?').fill('Bigger date line, see the picture and my voice note.');
    // paste a screenshot into the box, as Cmd/Ctrl+V does
    await box.locator('textarea').evaluate((ta, b64) => {
      const bin = atob(b64), bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const dt = new DataTransfer();
      dt.items.add(new File([bytes], 'flyer-shot.png', { type: 'image/png' }));
      ta.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }, PNG.toString('base64'));
    await box.locator('.attachment-tile', { hasText: 'flyer-shot.png' }).waitFor();
    await shoot(page, 'ticket-pasted-screenshot');
    // a file of a kind tickets do not take: refused in the box with plain words, nothing added
    await box.locator('input[type=file]').setInputFiles({ name: 'setup.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') });
    must(/only text files, pictures and voice recordings/i.test(await box.locator('.attachment-error').textContent()), 'a refused file does not say why');
    must(!(await box.locator('.attachment-tile', { hasText: 'setup.exe' }).count()), 'a refused file was added');
    await shoot(page, 'ticket-refused-file');
    // drag a picture over the ticket: the drop label shows; dropping adds it to the box
    const drag = await page.evaluateHandle(b64 => {
      const bin = atob(b64), bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const dt = new DataTransfer();
      dt.items.add(new File([bytes], 'menu-photo.png', { type: 'image/png' }));
      return dt;
    }, PNG.toString('base64'));
    const zone = page.locator('[data-key^=ticket-changes-]').first();
    await zone.dispatchEvent('dragenter', { dataTransfer: drag });
    await page.getByText('Drop to send back with this').waitFor();
    await shoot(page, 'ticket-drag-over');
    await zone.dispatchEvent('drop', { dataTransfer: drag });
    await box.locator('.attachment-tile', { hasText: 'menu-photo.png' }).waitFor();
    await record(page, box);
    await shoot(page, 'ticket-send-back-box');
    await act('ticket.attach', () => box.getByRole('button', { name: 'Send back', exact: true }).click());
    await page.waitForTimeout(1500);
    await reload();
    await page.getByText('flyer-shot.png').first().waitFor({ timeout: 10000 }).catch(() => {});
    await shoot(page, 'ticket-after-send-back');
    let t = await text();
    must(t.includes('flyer-shot.png'), 'the pasted screenshot is not on the ticket after a reload');
    must(t.includes('menu-photo.png'), 'the dropped picture is not on the ticket after a reload');
    must(/voice-note-\d{4}\.webm/.test(t), 'the voice note is not on the ticket after a reload');
    must(t.includes('Bigger date line'), 'the words that were sent back are not on the ticket after a reload');
    must(!(await page.getByRole('button', { name: 'Looks good' }).count()), 'the ticket is still in Check after it was sent back');

    // Review: Comment on the card, a voice note, Add note (the card stays)
    const tid = await newCheckTicket(page, open, act, 'Check the seating plan');
    await open('#review?card=' + encodeURIComponent('core:review:' + tid));
    await page.locator('.swipe-card', { hasText: 'Check the seating plan' }).first().waitFor();
    await page.getByRole('button', { name: /^Send back/ }).first().click();  // a Check card's Send back opens the Comment sheet
    const sheet = page.locator('.swipe-sheet');
    await sheet.waitFor();
    must(await sheet.getByRole('button', { name: 'Add file' }).count() === 1, 'the Comment sheet has no Add file button');
    await record(page, sheet);
    await shoot(page, 'review-comment-sheet');
    await act('run.send', () => sheet.getByRole('button', { name: 'Add note' }).click());
    await page.waitForTimeout(1000);
    await open('#tickets');
    await page.getByText('Check the seating plan').first().click();
    await page.getByRole('button', { name: 'Change title' }).waitFor();
    must(await page.getByRole('button', { name: 'Looks good' }).count() > 0, 'Add note moved the ticket out of Check');
    await reload();
    await page.getByText(/voice-note-\d{4}\.webm/).first().waitFor({ timeout: 10000 }).catch(() => {});
    t = await text();
    must(/voice-note-\d{4}\.webm/.test(t), 'the voice note from Add note is not on the ticket');
    // leave no extra card in Check: later click-throughs (b-answer) expect the seeded cards only
    await act('ticket.patch', () => page.getByRole('button', { name: 'Looks good' }).first().click());
  },
};
