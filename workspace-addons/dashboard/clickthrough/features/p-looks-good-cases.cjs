// ORCH-548: Looks good on a Review card either makes the ticket Done or the page says in one line why not and what
// to press. Each case on its own ticket, made in Check by the stand-in helper:
//  1. plain: the ticket shows Done at once (the save waits 6 s for Undo, then takes seconds more), Done after a reload
//  2. Undo within those seconds: the ticket is back in Check and nothing was saved
//  3. a step not finished: Looks good is off, the card says why and that Send back is the way on
//  4. an open question: Looks good is off on the card and on the ticket page until it is answered
//  5. a pull request not merged yet and a second look by the Reviewer still to come: the card says so, Looks good works
//  6. the Reviewer sends it back while the page still shows the card: the answer says who, when and why
//  7. it was accepted elsewhere (another tab, the phone): the answer says Done already, not that it failed
const CARD = id => '#review?card=' + encodeURIComponent('core:review:' + id);
const HAS_CARD = id => s => (s.review?.cards || []).some(c => c.id === 'core:review:' + id);
const OK = /^\s*Looks good/;

module.exports = {
  name: 'Review page: Looks good finishes a ticket or says why not',
  covers: ['page:review', 'review.answer', 'page:ticket'],
  async run({ page, open, reload, act, must, text, python, until }) {
    // a ticket in Check as a helper leaves it (one step, done with evidence unless `open`)
    const inCheck = (title, { stepOpen = false } = {}) => python(`
import sys; from pathlib import Path; from orch import tickets
root = Path.cwd(); t = tickets.create(root, sys.argv[1], "agent:standin")
tickets.check_add(root, t["id"], "Write it", "agent:standin")
if sys.argv[2] != "open":
    tickets.check_done(root, t["id"], "c1", ['{"type":"note","ref":"wrote it"}'], "agent:standin")
tickets.set_status(root, t["id"], "review", "agent:standin")
print(t["id"])`, title, stepOpen ? 'open' : 'done').trim();
    const status = id => python('import sys; from pathlib import Path; from orch import tickets; print(tickets.load(Path.cwd(), sys.argv[1])["status"])', id).trim();
    const shown = id => page.evaluate(tid => { const t = (state.tickets || []).find(x => x.id === tid); return t ? {status:t.status, saving:!!t.accept_saving} : null; }, id);  // eslint-disable-line no-undef
    const top = () => page.locator('[data-key="review-host"] article.swipe-card:not(.under):not(.under2)').first();
    const okButton = () => page.locator('[data-key="review-host"] button.swipe-act').filter({ hasText: OK }).first();
    // the page keeps what it holds (its state polls answer "unchanged"): the card stays on screen while a change
    // made elsewhere lands, as on a busy workspace whose page has not caught up yet
    const freeze = () => page.route('**/api/state**', r => r.fulfill({ status:200, contentType:'application/json', body:'{"unchanged":true}' }));
    const thaw = () => page.unroute('**/api/state**');

    await open('#home');  // not #review: a deck already on screen keeps its card order
    // 1. the plain case
    const plain = inCheck('Looks good walk: plain');
    await until(HAS_CARD(plain), 'the Check card of ' + plain); await open('#home'); await open(CARD(plain)); await top().waitFor();
    await act('review.answer', async () => {
      await okButton().click();
      await page.waitForTimeout(400);  // the card leaves in a short fade first
      const now = await shown(plain);
      must(now && now.status === 'done' && now.saving, `right after Looks good the ticket shows ${JSON.stringify(now)}, not Done while it is saved`);
      await open('#ticket/' + plain);  // leaving the Review page saves it at once
      must(/Done/.test(await page.locator('main').innerText()), 'the ticket page does not say Done right after Looks good');
    });
    must(status(plain) === 'done', `the ticket is ${status(plain)} in its file after Looks good`);
    await reload();
    must(/Done/.test(await text()), 'the ticket is not Done after a reload');

    // 2. Undo within the wait: back in Check, nothing saved
    const undo = inCheck('Looks good walk: undo');
    await until(HAS_CARD(undo), 'the Check card of ' + undo); await open('#home'); await open(CARD(undo)); await top().waitFor();
    await okButton().click();
    await page.waitForTimeout(400);
    must((await shown(undo))?.status === 'done', 'the ticket does not show Done after Looks good');
    await page.locator('[data-key="review-host"] button').filter({ hasText: /^\s*Undo/ }).first().click();
    await page.waitForFunction(tid => (state.tickets || []).find(x => x.id === tid)?.status === 'review', undo, { timeout:15000 });  // eslint-disable-line no-undef
    await page.waitForTimeout(6500);  // longer than the wait: an answer would have gone by now
    must(status(undo) === 'review', `after Undo the ticket is ${status(undo)}, not in Check`);

    // 3. a step not finished: Looks good is off and says why
    const stepOpen = inCheck('Looks good walk: a step is open', { stepOpen:true });
    await until(HAS_CARD(stepOpen), 'the Check card of ' + stepOpen); await open('#home'); await open(CARD(stepOpen)); await top().waitFor();
    await top().getByText('1 step is not finished. Send it back to get it done.').waitFor({ timeout:20000 });
    must((await top().innerText()).includes('Looks good is off'), 'the card does not say Looks good is off');
    must((await okButton().getAttribute('aria-disabled')) === 'true', 'Looks good is not marked off with a step open');
    await okButton().click({ force:true });  // a person can still press it: it says why instead of acting
    await page.getByText('1 step is not finished. Send it back to get it done.').last().waitFor();
    await page.waitForTimeout(6500);
    must(status(stepOpen) === 'review', 'Looks good went through with a step open');

    // 4. an open question: off on the card and on the ticket page, on again once it is answered
    const asks = inCheck('Looks good walk: a question waits');
    python('import sys; from pathlib import Path; from orch import tickets; tickets.ask(Path.cwd(), sys.argv[1], "Start the run?", ["Start", "Not now"], None, "agent:standin", kind="factory:start"); tickets.set_status(Path.cwd(), sys.argv[1], "review", "agent:standin")', asks);
    await until(HAS_CARD(asks), 'the Check card of ' + asks); await open('#home'); await open(CARD(asks)); await top().waitFor();
    await top().getByText('A question on this ticket still waits for your answer. Answer it first, then press Looks good.').waitFor({ timeout:20000 });
    await open('#ticket/' + asks);
    must(await page.locator('[data-key="ticket-review-open-question"]').count() > 0, 'the ticket page does not say the open question stops Looks good');
    must(await page.getByRole('button', { name: 'Looks good', exact:true }).first().isDisabled(), 'Looks good is on with a question open');

    // 5. a pull request not merged yet and a second look still to come: said, not stopping. Its checks are not known
    //    green (the stand-in GitHub answers only for standin/lunch): a green one left open is the "passed its checks but
    //    was not merged" row with Merge instead of this card, one card per ticket (ORCH-1741)
    const pr = inCheck('Looks good walk: pull request open');
    python(`
import sys; from pathlib import Path; from orch import lookreview, tickets
root, tid = Path.cwd(), sys.argv[1]
def op(t):
    t["refs"].append({"kind": "github-pr", "url": "https://github.com/standin/dinner/pull/7", "status": "ready to merge", "at": tickets.now(), "by": "agent:standin"})
tickets.apply_op(root, tid, op, by="agent:standin")
lookreview.queue(root, tid, "the look of a page changed")`, pr);
    await until(HAS_CARD(pr), 'the Check card of ' + pr); await open('#home'); await open(CARD(pr)); await top().waitFor();
    // "If you approve" stands in the pinned answers bar under the card (ORCH-477)
    const bar = () => page.locator('[data-key="review-host"] .swipe-bar-then').first();
    await bar().getByText('although pull request #7 is not merged yet').waitFor({ timeout:20000 });  // the card is drawn anew once the state has the reference
    // the reference and the second look are two writes: the state may show the first one alone for a poll
    await bar().getByText("The Reviewer's second look is not needed then.").waitFor({ timeout:20000 })
      .catch(() => must(false, 'the card does not say the second look is still to come'));
    await act('review.answer', async () => { await okButton().click(); await open('#ticket/' + pr); });
    must(status(pr) === 'done', 'Looks good did not make the ticket with an open pull request Done');

    // 6. the Reviewer sends it back while the page still shows the card
    const race = inCheck('Looks good walk: the Reviewer was first');
    await until(HAS_CARD(race), 'the Check card of ' + race); await open('#home'); await open(CARD(race)); await top().waitFor();
    await freeze();
    python('import sys; from pathlib import Path; from orch import tickets; tickets.ask_for_changes(Path.cwd(), sys.argv[1], "Pull request #7 is not merged yet.", tickets.REVIEWER)', race);
    await act('review.answer', () => okButton().click(), { refused:true });
    await page.getByText(/The Reviewer sent it back today \d\d:\d\d: Pull request #7 is not merged yet\. It is To do now/).last().waitFor();
    await thaw();
    await open('#ticket/' + race);
    must(!/Done/.test(await page.locator('[data-key^="status"]').first().innerText().catch(() => '')) && status(race) === 'ready', 'the ticket the Reviewer sent back shows Done');

    // 7. accepted elsewhere a moment before: Done already, said as such
    const twice = inCheck('Looks good walk: accepted on the phone');
    await until(HAS_CARD(twice), 'the Check card of ' + twice); await open('#home'); await open(CARD(twice)); await top().waitFor();
    await freeze();
    python('import sys; from pathlib import Path; from orch import tickets; tickets.accept_review(Path.cwd(), sys.argv[1], "human:Severin", "phone")', twice);
    await act('review.answer', () => okButton().click(), { refused:true });
    await page.getByText(/Already Done: you accepted it today \d\d:\d\d\. Nothing more to press\./).last().waitFor();
    await thaw();
    await reload();
    must(status(twice) === 'done', 'the ticket accepted on the phone is not Done');
    await open('#review');
  },
};
