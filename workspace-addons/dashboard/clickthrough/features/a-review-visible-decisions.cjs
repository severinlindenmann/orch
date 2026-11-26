// ORCH-1686: decisions must be hit-testable before any scrolling, above the Live bar; a file tile shows its
// type (a PDF the browser cannot draw small); the summary and the step are said once; the expand button keeps clear of the progress bar.
// The Live bar shows with the Focus add-on; the demo has none, so the page's state says it is on (as f-session-new).
const fs = require('node:fs');
const path = require('node:path');
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
// a 2 x 2 picture (PNG), so the first tile is a picture
// the smallest PDF a browser opens (one empty page)
const PDF = '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGNk+M/AwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==', 'base64');
module.exports = {
  name: 'Review decisions stay visible and evidence stays readable',
  covers: ['page:review', 'review.answer'],
  async run({page, open, orch, python, until, must, shot, act, workspace}) {
    const tid = python('from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), "Summarise the customer survey", "agent:standin")["id"])').trim();
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into && (!st.delta || 'addons' in into)) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
      route.fulfill({ response: res, json: st });
    });
    fs.writeFileSync(path.join(workspace, 'survey.png'), PNG);
    fs.writeFileSync(path.join(workspace, 'survey.pdf'), PDF);
    orch('check', 'add', tid, 'Write the one-page summary');
    orch('check', 'done', tid, 'c1', '--summary', 'A one-page summary.', '--file', 'survey.png', '--file', 'survey.pdf');
    orch('ticket', 'summary', tid, 'Most customers like our staff. Many ask for Sunday morning opening.');
    orch('ticket', 'status', tid, 'done');
    await open('#home');
    await until(s => (s.review?.cards || []).some(c => c.id === 'core:review:' + tid), 'survey ready for review');
    await open('#review?card=' + encodeURIComponent('core:review:' + tid));
    const card = page.locator('.swipe-card:not(.under):not(.under2)').first();
    await card.waitFor();
    // R6 A (ORCH-2173): a result card is titled with the helper's first summary sentence, the ticket's name is not repeated
    if (!(await card.innerText()).includes('Most customers like our staff.')) {  // the first load may still show the first card
      await page.locator('.review-side').getByText('Most customers like our staff.').first().click();
      await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Most customers like our staff.'}).first().waitFor();
    }
    await page.locator('#live-bar').waitFor();
    await shot('loaded');
    for (const [width, height] of [[1280,800], [1440,900], [1024,768], [1920,1080], [390,844], [320,844]]) {
      await page.setViewportSize({width,height});
      await page.evaluate(() => window.scrollTo(0,0));
      await page.waitForTimeout(300);
      for (const label of ['Looks good','Send back']) {
        const hit = await page.getByRole('button', {name:new RegExp('^'+label)}).first().evaluate(b => {
          const r=b.getBoundingClientRect(), e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
          return {visible:r.top>=0&&r.bottom<=innerHeight&&b.contains(e),top:r.top,bottom:r.bottom};
        });
        must(hit.visible, `${label} hidden at ${width}x${height}: ${JSON.stringify(hit)}`);
      }
      const overlap = await card.evaluate(c => {
        // ORCH-2173: Make bigger is for pictures only, so a words-only result has none (then nothing can overlap)
        const ex=c.querySelector('.swipe-expand'), pg=c.querySelector('.doc-progress');
        if (!ex || !pg) return false;
        const a=ex.getBoundingClientRect(), b=pg.getBoundingClientRect();
        return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
      });
      must(!overlap, `expand overlaps progress at ${width}`);
    }
    // ORCH-2316: on a phone the pinned answer bar never covers the card's Open ticket (under the title; above it at 360 and less)
    for (const [width, height] of [[390,844], [320,844]]) {
      await page.setViewportSize({width,height});
      await page.evaluate(() => window.scrollTo(0,0));
      await page.waitForTimeout(300);
      const tl = card.locator('a.swipe-ticket').first();
      if (await tl.count()) {
        const hit = await tl.evaluate(b => { const r=b.getBoundingClientRect(), e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
          const bar=document.querySelector('.swipe-actions:not([hidden])');
          return {visible:r.top>=0&&r.bottom<=innerHeight&&b.contains(e),top:r.top,bottom:r.bottom,on:e&&(e.closest('[class]')||e).className,
            barTop:bar&&Math.round(bar.getBoundingClientRect().top)}; });
        // a margin, not a 1 px touch: fonts on Linux wrap wider than on a Mac
        must(hit.visible && (hit.barTop == null || hit.bottom <= hit.barTop - 24), `Open ticket covered at ${width}x${height}: ${JSON.stringify(hit)}`);
      }
    }
    await page.setViewportSize({width:1280,height:800});
    // R6 A (ORCH-2316): the helper's steps fold under "What the helper did"; open it, then each step shows once
    const fold=card.locator('details.doc-steps summary');
    if (await fold.count()) await fold.first().click();
    const words=await card.innerText();
    must(words.split('Write the one-page summary').length===2, 'step repeated');
    must(words.split('Most customers like our staff.').length===2, 'summary repeated');
    const pdf=card.locator('.swipe-file').filter({hasText:'survey.pdf'});
    // the test browser has no PDF view, so the small picture cannot be drawn: the tile still says what it is
    must((await pdf.locator('.swipe-file-thumb').innerText()).trim() === 'PDF', 'the PDF tile is blank');
    await page.setViewportSize({width:1280,height:800});
    await page.getByRole('button',{name:/^Looks good/}).first().focus();
    await shot('keyboard');
    await act('review.answer', () => page.getByRole('button',{name:/^Looks good/}).first().click());
    await shot('accepted');
  }
};
