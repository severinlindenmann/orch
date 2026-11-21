// Factory stage review (ORCH-419): an order whose build stage has two built tasks waiting for the person's Looks good.
// - Factory home lists ONE review card for the stage under "Waits for you", with a picture of each built task
//   (the pictures load through the dashboard: no "No picture") and the true merge state ("Merged", although one
//   task also has a closed pull request that never merged).
// - `orch factory needs` lists the same review for the command line.
// - Looks good moves both tasks to Done; after a reload the card is gone and the tickets stay Done.
const fs = require('node:fs');
const path = require('node:path');

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNk+M9AEmAiTfmohlENQ00DAIHrAR/0Pq4mAAAAAElFTkSuQmCC', 'base64');

module.exports = {
  name: 'Factory: the stage review shows pictures and merge state, Looks good answers it',
  covers: ['addon.start', 'ticket.patch'],
  async run({ page, open, reload, must, text, act, orch, orchAsPerson, addonOn, addonOff, until, workspace, shot, slowOk }) {
    addonOn('factory');
    const repo = path.resolve(__dirname, '..', '..', '..', '..');
    const proposal = JSON.parse(fs.readFileSync(path.join(repo, 'contracts/examples/factory-proposal/valid-run.json'), 'utf8'));
    proposal.line = [
      { stage: 'build', stop: false, why: 'Layout already approved in the chat.' },
      { stage: 'ship', stop: true, why: 'You decide whether it goes live.' },
    ];
    proposal.tasks = [
      { slug: 'booking-form', title: 'Booking form', role: 'builder', stage: 'build', proves: [0] },
      { slug: 'free-times', title: 'Free times', role: 'builder', stage: 'build', proves: [1] },
      { slug: 'release', title: 'Prepare the release', role: 'builder', stage: 'ship' },
    ];
    const file = path.join(workspace, 'proposal-o.json');
    fs.writeFileSync(file, JSON.stringify(proposal));
    const order = JSON.parse(orch('factory', 'idea', 'Booking page', '--json')).order;
    const q = JSON.parse(orch('factory', 'propose', order, '--file', file, '--json')).question;
    fs.unlinkSync(file);
    orchAsPerson('answer', order, q, 'Start');
    orch('factory', 'next', order, '--json');

    // two built tasks: a picture each (as evidence), a recorded test, pull requests, then sent to Review
    const built = [];
    for (const [slug, pulls] of [['booking-form', [['merged', 11], ['closed', 12]]], ['free-times', [['merged', 13]]]]) {
      const tid = JSON.parse(orch('factory', 'crew', 'add', order, slug, '--json')).ticket;
      built.push(tid);
      orch('ticket', 'status', tid, 'active');
      orch('check', 'add', tid, 'Build it');
      const pic = path.join(workspace, `shot-${slug}.png`);
      fs.writeFileSync(pic, PNG);
      orch('check', 'done', tid, 'c1', '--file', pic, '--title', `${slug} at 1280`, '--summary', 'Built and shown.');
      fs.unlinkSync(pic);
      orch('check', 'record', tid, 'c1', '--cmd', 'pytest -q', '--exit', '0');
      // the pull requests' states as core keeps them on the ticket's links (the GitHub stand-in knows no such repo)
      for (const [state, n] of pulls) {
        const url = `https://github.com/standin/lunch/pull/${n}`;
        orch('ref', 'add', tid, url);
        orch('ref', 'set', tid, url, '--status', state);
      }
      orch('ticket', 'status', tid, 'done');   // a helper's done = Review
    }

    // the command line lists the same review
    const needs = JSON.parse(orchAsPerson('factory', 'needs', '--json'));
    const review = (Array.isArray(needs) ? needs : []).find(n => n.kind === 'factory:review' && n.order === order);
    must(review && built.every(t => review.tickets.includes(t)), '`orch factory needs` does not list the stage review: ' + JSON.stringify(needs));

    // its first answer can take longer than the page server's budget: then it answers 503 and shows Try again
    slowOk('/addon/factory/api/home');
    await open('#addon/factory');
    // the Factory page's own server, started from the page as a person does (from the dashboard, so it runs this
    // checkout's orch for as long as the run lasts)
    const start = page.locator('[data-key="page-start"]');
    await start.waitFor({ timeout: 30000 });
    await act('addon.start', () => start.click());
    await until(s => (s.services || []).some(x => x.addon === 'factory' && x.running === true), 'Factory running');
    await reload();
    const frame = page.frameLocator('iframe.embed');
    const card = frame.locator('.card', { hasText: 'what your crew built' }).first();
    for (let i = 0; i < 6 && !(await card.isVisible()); i++) {   // the first build of the page's answer can be slow here
      await page.waitForTimeout(5000);
      const again = frame.getByRole('button', { name: 'Try again' });
      if (await again.count()) await again.click();
    }
    await card.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no stage review card on Factory:\n' + (await text()).slice(0, 500)); });
    const pics = card.locator('img.thumbnail');
    await page.waitForTimeout(1500);
    must(await card.getByText('No picture').count() === 0, 'the stage review says "No picture" although each task has one');
    must(await pics.count() === 2, `the stage review shows ${await pics.count()} pictures, not 2`);
    for (let i = 0; i < 2; i++) must(await pics.nth(i).evaluate(img => img.complete && img.naturalWidth > 0), `picture ${i + 1} did not load`);
    must(await card.getByText('Not merged yet').count() === 0, 'a task whose pull request is merged says "Not merged yet"');
    must(await card.getByText('Merged').count() >= 2, 'the merged pull requests do not say "Merged"');
    await shot('factory-stage-review', card);

    await act('ticket.patch', () => card.getByRole('button', { name: 'Looks good' }).click());
    await until(s => built.every(id => (s.tickets || []).some(t => t.id === id && t.status === 'done')), 'both built tasks Done after Looks good');
    await reload();
    await page.waitForTimeout(2000);
    must(await page.frameLocator('iframe.embed').locator('.card', { hasText: 'what your crew built' }).count() === 0,
      'the stage review card is still there after Looks good and a reload');
    orchAsPerson('stop');
    await open('#home');   // leave the Factory tab first, as r-factory-idea-to-start does
    await addonOff('factory');   // off again for the next click-through, and wait until the page knows (ORCH-1402)
  },
};
