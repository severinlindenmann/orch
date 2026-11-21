// Updates, with this checkout as the update source (run.cjs sets ORCH_REPO to it, so nothing is downloaded):
// - Home shows the note after an automatic update ("orch updated itself to ..."); the person presses Got it, reloads,
//   and the note is gone.
// - Home shows the card after an update whose self-check failed ("Go back to release 32?"); the person presses Not now,
//   reloads, and the card is gone.
// - Settings > About & updates says a newer orch is ready (the demo home says it came from another commit); the
//   person presses "Update to ...". The update starts and then stops with a plain reason, because this demo runs
//   orch from its source folder: there is no installed tool folder to rebuild. Nothing is changed.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Updates: dismiss the note after an update, start an update',
  covers: ['update.note.dismiss', 'update.check.dismiss', 'update.start', 'page:settings/about'],
  async run({ page, open, reload, act, must, text, home, until, forgetUpdateInfo, python }) {
    const orchHome = path.join(home, 'orch');
    fs.writeFileSync(path.join(orchHome, 'auto-update-note.json'), JSON.stringify({
      state: 'updated', at: Math.floor(Date.now() / 1000) - 60, from: 'orch 40', to: 'orch 41', changes: ['The board loads faster'] }));
    await open('#home');
    await until(s => s.auto_update_note?.state === 'updated', 'the note after an automatic update');
    await reload();
    const ok = page.locator('[data-action="auto-update-note-ok"]');
    await ok.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no note after the update on Home:\n' + (await text()).slice(0, 500)); });
    must((await text()).includes('The board loads faster'), 'the note does not say what changed');
    await act('update.note.dismiss', () => ok.click());
    await reload();
    must(await ok.count() === 0, 'the note is still on Home after Got it and a reload');

    fs.writeFileSync(path.join(orchHome, 'update-check.json'), JSON.stringify({
      at: Math.floor(Date.now() / 1000) - 60, release: 33, back_to: 32, failed: [{ name: 'Factory list', why: 'the Factory list does not open' }] }));
    await until(s => s.update_check?.back_to === 32, 'the card after a failed self-check');
    await reload();
    const notNow = page.locator('[data-action="update-check-ok"]');
    await notNow.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no self-check card on Home:\n' + (await text()).slice(0, 500)); });
    must((await text()).includes('Go back to release 32?'), 'the card does not offer going back to 32');
    must(await page.locator('[data-action="update-check-back"]').count() === 1, 'no Go back button on the card');
    await act('update.check.dismiss', () => notNow.click());
    await reload();
    must(await notNow.count() === 0, 'the self-check card is still on Home after Not now and a reload');

    // another commit is "installed" (made up: a CI checkout holds only one commit), so this checkout is newer
    fs.writeFileSync(path.join(orchHome, 'installed.json'), JSON.stringify({ sha: 'c0ffee' + '1'.repeat(34) }));
    await forgetUpdateInfo();   // an earlier page may have asked already: the server keeps the answer 10 minutes
    await open('#settings/about');
    const start = page.locator('[data-key="update-start"]');
    await start.waitFor({ timeout: 60000 }).catch(async () => {
      const info = await page.evaluate(async () => (await fetch('/api/update-info', { cache: 'no-store' })).text());
      const git = python('from pathlib import Path; from orch import addons, safegit\n' +
        'print(safegit.run(["rev-parse", "HEAD"], Path(addons.repo()), 5, read_only=True, filters=False, root=Path(addons.repo())))');
      throw new Error('no Update button; update-info says ' + info.slice(0, 300) + '; orch git rev-parse: ' + git.trim().slice(0, 300));
    });
    await act('update.start', () => start.click());
    const failed = page.locator('[data-key="update-failed"]');
    await failed.waitFor({ timeout: 90000 }).catch(async () => { throw new Error('the update never said how it ended:\n' + (await text()).slice(0, 600)); });
    must(/orch is still the old version/.test(await failed.innerText()), 'the end of the update is not said in plain words: ' + await failed.innerText());
    fs.rmSync(path.join(orchHome, 'installed.json'), { force: true });
  },
};
