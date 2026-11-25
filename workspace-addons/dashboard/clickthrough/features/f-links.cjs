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
    // the page draws its list again once the links are loaded, and a click that lands during that redraw is lost
    // (no window) or a window opens late and twice: press Share a file until a window takes the file (#1756), and
    // use the newest window (the top one)
    const dlg = page.locator('dialog.share-dialog[open]').last();
    const file = path.join(home, 'lunch-menu.txt');
    fs.writeFileSync(file, 'Soup, bread, apple cake\n');
    let picked = false;
    for (let i = 0; i < 4 && !picked; i++) {
      if (!(await page.locator('dialog.share-dialog[open]').count())) {
        await page.getByRole('button', { name: 'Share a file' }).click();
        await dlg.waitFor({ timeout: 5000 }).catch(() => {});
      }
      picked = await dlg.locator('input[type=file]').setInputFiles(file, { timeout: 5000 }).then(() => true, () => false);
    }
    must(picked, 'Share a file opens no window that takes a file:\n' + (await text()).slice(0, 400));
    await act('link.share', () => dlg.getByRole('button', { name: 'Create link' }).click());
    // the window shows the new link once the list has it; when the list is slower than that the window closes and
    // says "Link created. Copy it from the list." Both are the page's answer; the reload below checks the list
    await dlg.getByText('Your link is ready').or(page.getByText('Link created. Copy it from the list.')).first()
      .waitFor({ timeout: 45000 });
    if (await page.locator('dialog.share-dialog[open]').count()) await page.keyboard.press('Escape');
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
