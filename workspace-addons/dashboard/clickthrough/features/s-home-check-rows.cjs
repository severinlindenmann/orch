// Home at 1920 (ORCH-1717): a ticket the Reviewer left for the person shows on Home with the calm Check mark and one
// short plain reason (never a red Stuck and never the Reviewer's file counts), and a Finished row keeps its title
// next to its ticket number, left-aligned like the Helpers rows.
module.exports = {
  name: 'Home: Reviewer left it for you, Finished rows at 1920',
  covers: ['page:home'],
  async run({ page, open, reload, must, orchAsPerson, python, workspace }) {
    await page.setViewportSize({ width: 1920, height: 1080 });
    const made = JSON.parse(orchAsPerson('ticket', 'new', 'Paint the meeting room', '--json'));
    orchAsPerson('ticket', 'status', made.id, 'review');
    // what the Reviewer's pass keeps when it leaves a ticket for the person (orch/reviewer.py remember_left)
    python('import json, sys; from pathlib import Path; from orch import runs\n' +
      'p = runs.run_dir(Path(sys.argv[1])) / "reviewer.json"; p.parent.mkdir(parents=True, exist_ok=True)\n' +
      'd = json.loads(p.read_text()) if p.exists() else {}\n' +
      'd[sys.argv[2]] = {"left": "changes code the Reviewer cannot read (not Python) (11 files); too big for a small fix (25 files, 4070 lines; small is 10 and 300)."}\n' +
      'p.write_text(json.dumps(d))', workspace, made.id);
    const done = JSON.parse(orchAsPerson('ticket', 'new', 'Order new chairs for the meeting room after the paint has dried', '--json'));
    orchAsPerson('ticket', 'status', done.id, 'done');

    await open('#home');
    await reload();
    const row = page.locator(`[data-key="need-core:unsure:${made.id}"]`);
    await row.waitFor();
    const said = await row.innerText();
    must(!/\bStuck\b/.test(said), 'a ticket the Reviewer left for you is marked Stuck: ' + said);
    must(/\bCheck\b/.test(said), 'a ticket the Reviewer left for you has no Check mark: ' + said);
    must(!/Reviewer|\d+ files|small is/.test(said), 'the row repeats the Reviewer\'s words or file counts: ' + said);
    must(/changes more than|look at it yourself|big change/i.test(said), 'the row gives no plain reason: ' + said);

    const fin = page.locator(`[data-key="ticket-${done.id}"]`);
    await fin.waitFor();
    const box = await fin.evaluate(el => {
      const a = el.querySelector('h3 a'), key = a.querySelector('.key'), r = el.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(a);
      const rects = [...range.getClientRects()];
      return { row: r.left, key: key.getBoundingClientRect().left, text: Math.min(...rects.map(x => x.left)), align: getComputedStyle(a).textAlign,
        display: getComputedStyle(a).display, h3: getComputedStyle(a.parentElement).display };
    });
    must(box.text - box.row < 40, 'the Finished title does not start at the left of its row: ' + JSON.stringify(box));
  },
};
