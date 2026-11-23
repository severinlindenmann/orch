// A portrait picture on a Focus wall tile must load, survive refreshes and open big.
const fs = require('node:fs');
const path = require('node:path');
module.exports = {
  name: 'Focus: picture result loads on the wall and opens big',
  covers: ['page:ticket'],
  async run({page, ids, workspace, open, reload, must, orch}) {
    const tid = /\[(t_[a-z0-9]+)\]/.exec(orch('ticket', 'new', 'Picture result'))[1];
    const folder = path.join(workspace, '.orch', 'tickets', tid, 'artifacts');
    fs.mkdirSync(folder, {recursive:true});
    const png = await page.evaluate(() => {
      const c = document.createElement('canvas'); c.width = 390; c.height = 1710;
      const x = c.getContext('2d');
      x.fillStyle = '#236a80'; x.fillRect(0, 0, c.width, c.height);
      x.fillStyle = '#ffffff'; x.font = '28px sans-serif'; x.fillText('Picture result', 24, 60);
      for (let y = 120; y < c.height; y += 120) x.fillRect(24, y, 342, 30);
      return c.toDataURL('image/png').split(',')[1];
    });
    fs.writeFileSync(path.join(folder, 'portrait.png'), Buffer.from(png, 'base64'));
    const live = {name:'focus', label:'Focus', icon:'target', active:true, removable:true,
      page:{path:'/', label:'Open Focus', live_session /* drawn by the dashboard */:true}, dashboard:{label:'Focus', icon:'target', order:20}};
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const response = await route.fetch(), st = await response.json();
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into && (!st.delta || 'addons' in into)) into.addons = [...(into.addons || []).filter(a => a.name !== 'focus'), live];
      await route.fulfill({response, json:st});
    });
    await page.route('**/addon/focus/**', route => route.fulfill({contentType:'text/html', body:'<!doctype html><title>Focus</title>'}));
    let polls = 0;
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({json:{sessions /* crowded wall fixture */:[{id:ids.table, title:'Pinned helper', status:'idle', word:'Idle', pinned:true}, {id:ids.lunch, title:'Other helper', status:'working', word:'Working'}, {
      id:tid, title:'Picture result', status:'working', word:'Working', detail:'Reading the picture ' + (++polls),
      waiting_on:[], question:null, lines:[], tool:'Helper', mode:'live', pinned:false,
    }, ...Array.from({length:12}, (_, i) => ({id:'t_pic' + String(i).padStart(3, '0'), title:'Helper ' + i, status:'working', word:'Working'}))], lines:8, age_ms:0}}));
    let releasePicture;
    const pictureReady = new Promise(resolve => {releasePicture = resolve;});
    await page.route(/\/api\/file\?.*portrait\.png/, async route => {
      const response = await route.fetch();
      await pictureReady;
      await route.fulfill({response});
    });
    const responses = [];
    page.on('response', response => {
      if (response.url().includes('/api/file?') && response.url().includes('portrait.png')) responses.push(response.status());
    });
    await page.addInitScript(() => { for (const k of Object.keys(localStorage)) if (k.startsWith('orch.live.')) localStorage.removeItem(k); });
    const tile = `.wall [data-tile="${tid}"]`;
    const picture = `${tile} .result-pic img`;
    try {
      const requested = page.waitForRequest(r => r.url().includes('/api/file?') && r.url().includes('portrait.png'), {timeout:15000});
      await open('#addon/focus');
      await requested;
      await page.locator(picture).waitFor({state:'visible', timeout:15000});
      const image = await page.locator(picture).elementHandle();
      // Redraw while the real endpoint's response is held: a lazy image must remain connected.
      const filter = page.getByPlaceholder('Filter by name, ticket or status');
      await filter.fill('Picture');
      await page.waitForFunction(s => !document.querySelector(s), `.wall [data-tile="${ids.lunch}"]`);
      must(await image.evaluate(im => im.isConnected), 'wall redraw replaced the pending picture');
      releasePicture();
      await page.waitForFunction(s => { const im = document.querySelector(s); return im?.complete && im.naturalWidth === 390; }, picture, {timeout:15000});
      must(responses.includes(200), 'the real picture endpoint did not answer 200');
      await filter.fill('');
      await page.locator(`.wall [data-tile="${ids.lunch}"]`).waitFor({state:'visible'});
      must(await image.evaluate(im => im.isConnected && im.complete && im.naturalWidth === 390), 'wall redraw replaced the loaded picture');
      await page.locator(`${tile} .result-open`).click();
      await page.waitForFunction(() => {const im = document.querySelector('dialog.result-overlay[open] .result-pic img'); return im?.complete && im.naturalWidth === 390;});
      await page.keyboard.press('Escape');
      await reload();
      await page.waitForFunction(s => {const im = document.querySelector(s); return im?.complete && im.naturalWidth === 390;}, picture);
      await page.locator(tile).scrollIntoViewIfNeeded();
      await open('#ticket/' + tid);
      await page.waitForFunction(() => [...document.querySelectorAll('.result-pic img')].some(im => im.complete && im.naturalWidth === 390));
      await open('#addon/focus');
      await page.locator(tile).scrollIntoViewIfNeeded();
      await page.waitForFunction(s => {const im = document.querySelector(s); return im?.complete && im.naturalWidth === 390;}, picture);
    } finally {
      releasePicture();
      // the picture was written straight into the ticket for this check: take it away again, or Sync (f-sync-page,
      // later on the same lane) pauses on it - 'portrait.png: cannot-check' on Linux (23 Nov probe, issue NNNN)
      fs.rmSync(path.join(folder, 'portrait.png'), {force:true});
    }
  },
};
