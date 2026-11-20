// Shared links with a stand-in sharing server (server.py, on 127.0.0.1): the person turns Shared links on and
// connects it here, shares a small file from the Shared links page, reloads and sees it in the list, extends it by a
// week, then stops sharing it (confirms) and sees it gone after a reload. Nothing leaves this computer.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Shared links: share a file, extend it, stop sharing',
  covers: ['link.share', 'link.extend', 'link.stop'],
  async run({ page, open, reload, act, must, text, orch, standins, home, until, addonOff }) {
    const p = standins.publish;
    orch('addon', 'add', 'publish', '--yes');
    orch('publish', 'connect', p.url, '--workspace', p.workspace, '--token', p.token);
    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'publish'), 'Shared links turned on and connected');
    await open('#addon/publish');
    await page.getByRole('button', { name: 'Share a file' }).waitFor({ timeout: 30000 })
      .catch(async () => { throw new Error('no Share a file button:\n' + (await text()).slice(0, 400)); });
    // the page draws its list again once the links are loaded, and a click that lands during that redraw is lost:
    // press Share a file again until its window is open
    const dlg = page.locator('dialog.share-dialog[open]');
    for (let i = 0; i < 4 && !(await dlg.count()); i++) {
      await page.getByRole('button', { name: 'Share a file' }).click();
      await dlg.waitFor({ timeout: 5000 }).catch(() => {});
    }
    await dlg.waitFor({ timeout: 5000 }).catch(async () => { throw new Error('Share a file opens no window:\n' + (await text()).slice(0, 400)); });
    const file = path.join(home, 'lunch-menu.txt');
    fs.writeFileSync(file, 'Soup, bread, apple cake\n');
    await dlg.locator('input[type=file]').setInputFiles(file);
    await act('link.share', () => dlg.getByRole('button', { name: 'Create link' }).click());
    await dlg.getByText('Your link is ready').waitFor({ timeout: 15000 });
    await page.keyboard.press('Escape');
    await reload();
    await page.getByText('lunch-menu.txt').first().waitFor({ timeout: 30000 }).catch(() => {});
    must((await text()).includes('lunch-menu.txt'), 'the shared file is not in the list after a reload:\n' + (await text()).slice(0, 600));

    await act('link.extend', () => page.getByRole('button', { name: 'Extend' }).first().click());
    await page.getByText('Link extended.').first().waitFor({ timeout: 10000 });

    await page.getByRole('button', { name: 'Stop sharing' }).first().click();
    await act('link.stop', () => page.locator('dialog[open]').getByRole('button', { name: 'Stop sharing' }).click());
    await reload();
    await page.getByRole('button', { name: 'Share a file' }).waitFor({ timeout: 30000 });
    must(!(await text()).includes('lunch-menu.txt'), 'the file is still shared after Stop sharing and a reload');
    await addonOff('publish');   // off again, as the next click-through expects
  },
};
