// Updates, with this checkout as the update source (run.cjs sets ORCH_REPO to it, so nothing is downloaded):
// - Home shows the note after an automatic update ("orch updated itself to ..."); the person presses Got it, reloads,
//   and the note is gone.
// - Settings > About & updates says a newer orch is ready (the demo home says it came from another commit); the
//   person presses "Update to ...". The update starts and then stops with a plain reason, because this demo runs
//   orch from its source folder: there is no installed tool folder to rebuild. Nothing is changed.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Updates: dismiss the note after an update, start an update',
  covers: ['update.note.dismiss', 'update.start', 'page:settings/about'],
  async run({ page, open, reload, act, must, text, home, until, forgetUpdateInfo }) {
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

    // another commit is "installed" (made up: a CI checkout holds only one commit), so this checkout is newer
    fs.writeFileSync(path.join(orchHome, 'installed.json'), JSON.stringify({ sha: 'c0ffee' + '1'.repeat(34) }));
    await forgetUpdateInfo();   // an earlier page may have asked already: the server keeps the answer 10 minutes
    await open('#settings/about');
    const start = page.locator('[data-key="update-start"]');
    await start.waitFor({ timeout: 60000 }).catch(async () => { throw new Error('no Update button:\n' + (await text()).slice(0, 600)); });
    await act('update.start', () => start.click());
    const failed = page.locator('[data-key="update-failed"]');
    await failed.waitFor({ timeout: 90000 }).catch(async () => { throw new Error('the update never said how it ended:\n' + (await text()).slice(0, 600)); });
    must(/orch is still the old version/.test(await failed.innerText()), 'the end of the update is not said in plain words: ' + await failed.innerText());
    fs.rmSync(path.join(orchHome, 'installed.json'), { force: true });
  },
};
