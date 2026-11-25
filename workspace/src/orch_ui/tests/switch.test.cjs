// Targeted browser regression: shared tracks must survive dashboard button rules.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');
const headless = require('../../../../e2e/headless.cjs');
const root = path.resolve(__dirname, '../../../..');
let playwright;
try { playwright = require('playwright'); } catch {
  playwright = require(path.join(execFileSync('npm', ['root', '-g'], {encoding:'utf8'}).trim(), 'playwright'));
}

test('switch dots occupy opposite ends with equal padding at every width', async () => {
  const browser = await headless.launch(playwright.chromium);
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(path.join(root, 'workspace/src/orch_ui/static/gallery.html')).href);
    for (const name of ['settings', 'desktop']) {
      await page.addStyleTag({path:path.join(root, `workspace-addons/dashboard/src/orch_dashboard/web/pages/${name}.css`)});
    }
    await page.locator('#switch-states').evaluate(el => el.classList.add('settings'));
    for (const reducedMotion of ['no-preference', 'reduce']) {
      await page.emulateMedia({reducedMotion});
      for (const width of [320, 390, 1280, 1440, 1920]) {
        await page.setViewportSize({width, height:844});
        const facts = await page.locator('#switch-states .switch').evaluateAll(nodes => nodes.map(el => {
          const box = el.getBoundingClientRect(), s = getComputedStyle(el), dot = getComputedStyle(el, '::after');
          const on = el.checked || el.getAttribute('aria-checked') === 'true';
          const x = parseFloat(s.borderLeftWidth) + parseFloat(dot.left) + new DOMMatrix(dot.transform).m41;
          const y = parseFloat(s.borderTopWidth) + parseFloat(dot.top);
          const label = el.closest('label').getBoundingClientRect();
          return {on, background:s.backgroundColor, width:box.width, height:box.height, x, y, dotWidth:parseFloat(dot.width),
            dotHeight:parseFloat(dot.height), labelHeight:label.height};
        }));
        assert.equal(facts[0].background, facts[4].background, 'button and checkbox Off colours match');
        assert.equal(facts[1].background, facts[5].background, 'button and checkbox On colours match');
        assert.notEqual(facts[0].background, facts[1].background);
        for (const f of facts) {
          assert.equal(f.width, 36, JSON.stringify({width, reducedMotion, f}));
          assert.equal(f.height, 24);
          assert.equal(f.on ? f.width - f.x - f.dotWidth : f.x, 4);
          assert.equal(f.y, (f.height - f.dotHeight) / 2);
          assert.equal(f.labelHeight, 24, 'words must stay beside the track');
        }
      }
    }
    const checkbox = page.getByRole('switch', {name:'Checkbox off example', exact:true});
    await checkbox.focus();
    await checkbox.press('Space');
    assert.equal(await checkbox.isChecked(), true);
    assert.notEqual(await checkbox.evaluate(el => getComputedStyle(el).outlineStyle), 'none');
    assert.equal(await page.getByRole('switch', {name:'Unavailable off example', exact:true}).isDisabled(), true);
    // The native checkbox must also retain the track size without interaction.css.
    await page.locator('link[href="interaction.css"]').evaluate(el => el.remove());
    assert.equal(await checkbox.evaluate(el => el.offsetWidth), 36);
  } finally { await browser.close(); }
});
