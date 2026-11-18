// Earlier sessions (the History tab of a session pane in the new live layer, behind Focus's Preview switch): a ticket
// remembers two helper conversations, the older one still on this computer (a stand-in conversation file in the
// throw-away home). The person opens the ticket's pane, opens History, presses Reopen on the earlier conversation,
// and the ticket now continues that one (the stand-in agent program of server.py is what starts).
const fs = require('node:fs');
const path = require('node:path');

const OLD = 'standin-session-old1', NEW = 'standin-session-new2';

module.exports = {
  name: 'Session history: reopen an earlier conversation of a ticket',
  covers: ['session.reopen'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, addonOn, python, workspace, home, until }) {
    addonOn('focus');
    orchAsPerson('config', 'set', 'focus.preview', 'on');
    const tid = JSON.parse(orch('ticket', 'new', 'Write the party invite', '--json')).id;
    // two conversations of the stand-in "claude" on this computer; recording the second keeps the first as earlier
    python('import sys; from pathlib import Path; from orch import tickets, runs\n' +
      'for sid in sys.argv[3:]: tickets.record_session(Path(sys.argv[1]), sys.argv[2], "claude", sid, runs.host())',
    workspace, tid, OLD, NEW);
    const conv = path.join(home, '.claude', 'projects', 'standin');
    fs.mkdirSync(conv, { recursive: true });
    fs.writeFileSync(path.join(conv, OLD + '.jsonl'), JSON.stringify({ type: 'user', timestamp: new Date().toISOString(),
      message: { role: 'user', content: 'Draft the invite for the summer party' } }) + '\n');

    await open('#home');
    await until(s => s.settings?.focus_preview_on === true && (s.tickets || []).some(t => t.id === tid), 'the Preview on and the ticket there');
    // the layer remembers its open panes per browser: open the ticket's pane as a person who had it open
    await page.evaluate(id => localStorage.setItem('orch.live.layer', JSON.stringify({ mode: 'bottom', last: 'bottom', back: 'bottom', panes: [id], cur: id })), tid);
    await reload();
    const hist = page.locator('#live-dock [data-key="live-history"]').first();
    await hist.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no History button on the ticket pane:\n' + (await page.locator('#live-dock').innerText().catch(() => '(no live dock)')).slice(0, 400)); });
    // with the keyboard: a mouse press on a pane button replays the panel's slide-in, so the release misses the
    // button (orch issue 1431); Enter on the focused button is what a keyboard user does
    await hist.focus();
    await page.keyboard.press('Enter');
    const reopen = page.locator('#live-dock [data-live-hist="reopen"]').first();
    await reopen.waitFor({ timeout: 30000 }).catch(async () => {
      const api = await page.evaluate(async id => (await fetch('/api/sessions/' + id)).text(), tid);
      throw new Error('no Reopen for the earlier conversation: ' + (await page.locator('#live-dock .live-pane').first().innerText()).slice(0, 300).replace(/\n/g, ' | ') + ' / sessions: ' + api.slice(0, 400));
    });
    must((await page.locator('#live-dock').innerText()).includes('Draft the invite for the summer party'), 'the earlier conversation does not show what it was about');
    await act('session.reopen', async () => { await reopen.focus(); await page.keyboard.press('Enter'); });
    await reload();
    const sessions = JSON.parse(orch('ticket', 'show', tid, '--json')).sessions || [];
    must(sessions.some(s => s.agent === 'claude' && s.id === OLD), 'the ticket does not continue the earlier conversation: ' + JSON.stringify(sessions.map(s => s.id)));
    try { orchAsPerson('run', 'stop', tid); } catch (e) { /* the stand-in already ended */ }
    orchAsPerson('config', 'set', 'focus.preview', 'off');
    orchAsPerson('addon', 'remove', 'focus');
    await page.evaluate(() => localStorage.removeItem('orch.live.layer'));
  },
};
