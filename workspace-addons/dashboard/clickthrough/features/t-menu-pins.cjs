// The menu's add-ons and its open/close button (ORCH-1184, tidied by owner D2 A, ORCH-2283), like a person: the rows
// carry no pin; "Change this list" shows one switch per add-on, turning one off and pressing Done moves it under
// "More (n)"; More unfolds it in place, the switch brings it back; after a reload the choice is still there. The
// button beside the orch name closes the menu to its icons, a reload keeps it closed, the button opens it again.
module.exports = {
  name: 'Menu: change the add-on list, More and Fewer, close and open the menu',
  covers: ['page:home'],
  async run({ page, open, reload, must, addonOn, addonOff, until }) {
    await open('#home');
    addonOn('factory');   // the demo starts with no add-on in the menu
    await until(st => (st.addons || []).some(a => a.name === 'factory'), 'factory on');
    await reload();
    const inList = () => page.locator('#side-addons nav[aria-label="Add-ons"] a[href="#addon/factory"]');
    const underMore = () => page.locator('#side-addons nav[aria-label="More add-ons"] a[href="#addon/factory"]');
    const change = () => page.locator('#side-addons .nav-change');
    const more = () => page.locator('#side-addons .nav-more');
    const sw = () => page.locator('#side-addons [data-pin="factory"]');
    await inList().waitFor({ timeout: 20000 }).catch(() => { throw new Error('Factory is not in the menu list'); });
    must(await page.locator('#side-addons [data-pin]').count() === 0, 'the menu rows still carry a pin');

    // Change this list: Factory's switch is on; off and Done moves it under More
    await change().click();
    must(await change().innerText() === 'Done', 'Change this list did not turn into Done');
    must(await sw().getAttribute('aria-checked') === 'true', 'Factory is in the list but its switch is off');
    await sw().click();
    must(await sw().getAttribute('aria-checked') === 'false', 'the switch did not move Factory out of the list');
    await change().click();
    must(await page.locator('#side-addons [data-pin]').count() === 0, 'the switches stay after Done');
    must(await inList().count() === 0, 'Factory is still in the list after Done');
    must(/^More \(\d+\)$/.test(await more().getAttribute('aria-label')), 'no More (n) once an add-on waits under it');
    await reload();
    must(await inList().count() === 0 && await underMore().count() === 0, 'Factory came back into the menu after a reload');

    // More unfolds the rest in place, with Change this list at its end; the switch brings Factory back
    await more().click();
    must(await more().getAttribute('aria-expanded') === 'true', 'More did not unfold');
    must(await more().innerText() === 'Fewer', 'the unfolded More does not say Fewer');
    must(await underMore().count() === 1, 'Factory is not under More');
    await change().click();
    await sw().click();
    must(await sw().getAttribute('aria-checked') === 'true', 'the switch did not put Factory back in the list');
    await change().click();
    await reload();
    must(await inList().count() === 1, 'Factory is not in the list after a reload');

    const toggle = page.locator('#side-toggle');
    await toggle.click();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'Close menu did not close the menu');
    must(await toggle.getAttribute('aria-label') === 'Open menu', 'the closed menu button does not say Open menu');
    must(!(await page.locator('#side-nav .nav-label').first().isVisible()), 'the closed menu still shows its words');
    await reload();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'the menu opened again after a reload');
    await page.locator('#side-toggle').click();
    must(await page.locator('.shell').getAttribute('data-side') === null, 'Open menu did not open the menu');
    must(await page.locator('#side-nav .nav-label').first().isVisible(), 'the opened menu shows no words');
    await addonOff('factory');   // off again for the next click-through
  },
};
