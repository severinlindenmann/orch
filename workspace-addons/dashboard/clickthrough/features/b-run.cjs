// The stand-in helper: Start helper on a seeded ticket, Stop it again, and write a message to the helper on another.
// The seed makes sure only stand-ins can run here (server.py): the workspace helper is a script, and programs named
// claude and codex are stand-ins too, first on PATH. A Start never runs a real agent.
module.exports = {
  name: 'Helper: start, stop and send a message',
  covers: ['run.start', 'run.stop', 'run.send'],
  async run({ page, ids, open, reload, act, must, workspace }) {
    const activity = async () => {
      await page.getByRole('tab', { name: /^Activity/ }).click();
      return page.locator('main').innerText();
    };

    // start, then stop
    await open('#ticket/' + ids.budget);
    await act('run.start', () => page.getByRole('button', { name: 'Start helper', exact: true }).click());
    const stop = page.getByRole('button', { name: 'Stop', exact: true });
    await stop.waitFor({ timeout: 15000 });
    await act('run.stop', () => stop.click());
    await reload();
    const log = await activity();
    must(/helper/i.test(log), 'the ticket shows no sign that a helper ran after a reload');
    must(!(await stop.count()), 'the helper still shows Stop after Stop and a reload');

    // write to the helper (nothing runs on this ticket: the message is saved and a helper starts)
    await open('#ticket/' + ids.table);
    await page.getByPlaceholder(/Write what is new/).fill('Please use the blue folder');
    await act('run.send', () => page.getByRole('button', { name: /^Send/ }).click());
    await reload();
    // The helper got the person's words: the stand-in writes what it was started with into its log.
    const standinLog = require('node:path').join(workspace, '..', 'fake-agent.log');
    let got = '';
    for (let i = 0; i < 50 && !got.includes('blue folder'); i++) {
      try { got = require('node:fs').readFileSync(standinLog, 'utf8'); } catch (e) { /* not yet */ }
      await page.waitForTimeout(200);
    }
    must(got.includes('blue folder'), 'the helper never got the message');
  },
};
