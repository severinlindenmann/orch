// ORCH-892 (clean e2e of Home and Review): every question card kind answered like a person on the Review page, and
// the draft guard. A helper asks five cards on one ticket each: a draft (a letter), a choice with pictures (three
// posters), a merge card for a pull request, a link card and a plan. Then:
//  1. the terminal cannot pick the draft or the poster choice (only a person, signed in on the page or a phone)
//  2. Looks good on the draft from the signed-in page goes through
//  3. picking poster B and pressing Pick one answers "Use B"
//  4. Merge merges exactly the shown commit (the stand-in gh writes the merge it was asked for)
//  5. Don't do on the link card
//  6. Comment > Add note on the plan keeps the card and sends the words to the helper; then Comment > Send back
//  7. the Answered tab names each answer, also after a reload
const fs = require('node:fs');
const path = require('node:path');

const CARD = (tid, q = 'q1') => '#review?card=' + encodeURIComponent(`core:q:${tid}:${q}`);
const HAS_CARD = (tid, q = 'q1') => s => (s.review?.cards || []).some(c => c.id === `core:q:${tid}:${q}`);
const POSTER = (name, colour) => `<!doctype html><html><body style="background:${colour};font:24px sans-serif"><h1>${name}</h1></body></html>`;

module.exports = {
  name: 'Review page: every card kind and the draft guard',
  covers: ['page:review', 'review.answer', 'run.send'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, python, until, workspace, home, standins }) {
    await open('#home');  // the state polls below run in the page
    fs.writeFileSync(path.join(workspace, 'kinds-letter.txt'), 'Dear customer,\nthank you for a great year.\n');
    fs.writeFileSync(path.join(workspace, 'kinds-plan.txt'), 'Summer party: 20 people, Friday 18:00.\n');
    for (const [f, n, c] of [['kinds-a.html', 'Poster A', '#dde'], ['kinds-b.html', 'Poster B', '#edd'], ['kinds-c.html', 'Poster C', '#ded']]) {
      fs.writeFileSync(path.join(workspace, f), POSTER(n, c));
    }
    const ticket = title => python('import sys; from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), sys.argv[1], "agent:standin")["id"])', title).trim();
    const answer = (tid, q = 'q1') => python('import sys, json; from pathlib import Path; from orch import tickets\n'
      + 't = tickets.load(Path.cwd(), sys.argv[1]); print(json.dumps([x.get("answer") for x in t.get("questions") or [] if x["id"] == sys.argv[2]]))', tid, q).trim();
    const host = () => page.locator('[data-key="review-host"]');
    const button = re => host().locator('button').filter({ hasText: re }).first();
    const show = async tid => { await until(HAS_CARD(tid), 'the card of ' + tid); await open('#home'); await open(CARD(tid)); await host().locator('article.swipe-card:not(.under):not(.under2)').first().waitFor(); };

    const draft = ticket('Kinds walk: thank-you letter');
    orch('ask', draft, 'Is this letter good to send?', '--draft', 'Thank-you letter', '--file', 'kinds-letter.txt', '--then', 'I send it to the top customers');
    const choice = ticket('Kinds walk: shop window poster');
    orch('ask', choice, 'Which poster goes in the window?', '--choose', 'Shop window poster', '--option', 'A=Calm blue:kinds-a.html',
      '--option', 'B=Loud red:kinds-b.html', '--option', 'C=Green:kinds-c.html', '--suggest', 'A', '--then', 'I print the one you pick');
    const merge = ticket('Kinds walk: lunch menu change');
    orch('ask', merge, 'Merge the lunch menu change?', '--link', 'Lunch menu change', '--open', 'https://github.com/standin/lunch/pull/7', '--merge', '--then', 'It goes live');
    const link = ticket('Kinds walk: price list link');
    orch('ask', link, 'Share this link with the shop staff?', '--link', 'Price list link', '--open', 'https://example.com/prices', '--then', 'I send it to the staff');
    const plan = ticket('Kinds walk: summer party plan');
    orch('ask', plan, 'Is this plan ok?', '--plan', 'Summer party plan', '--file', 'kinds-plan.txt', '--then', 'I book the room');

    // 1. the draft guard: the terminal cannot pick a draft, nor a choice whose options show files
    for (const [tid, word] of [[draft, 'Looks good'], [choice, 'A']]) {
      let refused = '';
      try { orchAsPerson('answer', tid, 'q1', word); } catch (e) { refused = String(e.stderr || e.stdout || e.message); }
      must(/Only a person picks a draft/.test(refused), `the terminal answered ${tid} or said something else: ${refused.slice(0, 200)}`);
      must(answer(tid) === '[null]', `${tid} has an answer after the terminal was refused`);
    }

    // 2. the draft, picked by the signed-in person on the page
    await show(draft);
    must((await host().innerText()).includes('Dear customer'), 'the draft card does not show the letter');
    await act('review.answer', () => button(/^\s*Looks good/).click());
    must(answer(draft) !== '[null]', 'the draft has no answer after Looks good on the page');

    // 3. the poster choice: B, then Pick one
    await show(choice);
    await host().locator('button').filter({ hasText: /^\s*B\s*Loud red/ }).first().click();
    await act('review.answer', () => button(/^\s*(Pick one|Use B)/).click());
    must(/B/.test(answer(choice)), `the poster choice was answered ${answer(choice)}, not B`);

    // 4. Merge: the stand-in gh merged exactly the shown commit
    await show(merge);
    must(/Exact version/.test(await host().innerText()), 'the merge card does not name the exact version it merges');
    const log = path.join(home, 'standin-merged');  // shared by every click-through of the run: only what this click adds counts
    const before = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').length : 0;
    await act('review.answer', () => button(/^\s*Merge/).click());
    const added = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').slice(before) : '';
    must(added.includes('https://github.com/standin/lunch/pull/7') && added.includes('--match-head-commit ' + standins.head),
      'Merge did not merge pull request 7 at the shown commit: ' + added.slice(-200));

    // 5. Don't do on the link card
    await show(link);
    await act('review.answer', () => button(/^\s*Don't do/).click());
    must(answer(link) !== '[null]', 'the link card has no answer after Don\'t do');

    // 6. the plan: Add note keeps the card, Send back answers it with the words
    await show(plan);
    // the Comment sheet (widgets.js): its words box is named "What should change"
    const words = () => page.getByRole('textbox', { name: 'What should change' }).last();
    await button(/^\s*Comment/).click();
    await words().fill('Ask the bakery for the cake too.');
    await act('run.send', () => page.getByRole('button', { name: 'Add note' }).last().click());
    must(answer(plan) === '[null]', 'Add note answered the plan card; it should stay open');
    const queued = path.join(workspace, '.orch', 'run', 'pending', plan + '.jsonl');  // the words wait for the plan's helper
    must(fs.existsSync(queued) && fs.readFileSync(queued, 'utf8').includes('Ask the bakery for the cake too.'), 'the note did not reach the plan ticket\'s helper');
    await show(plan);
    await button(/^\s*Comment/).click();
    await words().fill('Book a room for 40 people, not 20.');
    await act('review.answer', () => page.getByRole('button', { name: 'Send back for changes' }).last().click());
    must(answer(plan) !== '[null]', 'the plan has no answer after Send back');

    // the answers as saved in the ticket files
    const saved = {draft: answer(draft), choice: answer(choice), merge: answer(merge), link: answer(link), plan: answer(plan)};
    must(/Approved|Looks good/.test(saved.draft), 'draft saved as ' + saved.draft);
    must(/Merge/.test(saved.merge), 'merge card saved as ' + saved.merge);
    must(/Don't do|Do not|No/i.test(saved.link), 'link card saved as ' + saved.link);
    must(/Book a room for 40 people/.test(saved.plan), 'plan saved without the words: ' + saved.plan);

    // 7. the Answered tab names the answers, also after a reload
    await open('#review');
    await reload();
    await page.getByRole('tab', { name: /Answered/ }).first().click().catch(() => page.getByText('Answered', { exact: true }).first().click());
    await page.getByText('Use B').first().waitFor({ timeout: 20000 });
    const all = await text();
    for (const word of ['Kinds walk: thank-you letter', 'Kinds walk: shop window poster', 'Kinds walk: lunch menu change',
      'Kinds walk: price list link', 'Kinds walk: summer party plan', 'Use B', "Don't do", 'Book a room for 40 people']) {
      must(all.includes(word), `the Answered tab does not show "${word}"`);
    }
  },
};
