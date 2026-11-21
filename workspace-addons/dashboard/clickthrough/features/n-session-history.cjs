// Earlier sessions (the History tab of a session pane in the live layer of Focus): a ticket
// remembers two helper conversations, the older one still on this computer (a stand-in conversation file in the
// throw-away home). The person opens the ticket's pane, opens History, presses Reopen on the earlier conversation,
// and the ticket now continues that one (the stand-in agent program of server.py is what starts).
const OLD = 'standin-session-old1', NEW = 'standin-session-new2';

module.exports = {
  name: 'Session history: reopen an earlier conversation of a ticket',
  covers: ['session.reopen'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, addonOn, python, workspace, home, until, addonOff }) {
    addonOn('focus');
    const tid = JSON.parse(orch('ticket', 'new', 'Write the party invite', '--json')).id;
    // two conversations of a built-in helper tool whose conversations orch can read (from orch's adapter list; this
    // file names no tool), the older one saved where that tool keeps it in the throw-away home; recording the
    // second keeps the first as earlier
    python('import json, sys, time; from pathlib import Path; from orch import adapters, tickets, runs\n' +
      'root, tid, old, new, home = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])\n' +
      'name, h = next((n, a["session"]["chat_files"]) for n in sorted(adapters.builtin_names()) for a in [adapters.load(n)]\n' +
      '               if (a.get("session") or {}).get("chat_files", {}).get("lines") == "chat")\n' +
      'f = home / h["home"] / h["glob"].replace("*", "standin").replace("{session}", old)\n' +
      'f.parent.mkdir(parents=True, exist_ok=True)\n' +
      'f.write_text(json.dumps({"type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),\n' +
      '  "message": {"role": "user", "content": "Draft the invite for the summer party"}}) + "\\n")\n' +
      'for sid in (old, new): tickets.record_session(root, tid, name, sid, runs.host())', workspace, tid, OLD, NEW, home);

    await open('#home');
    await until(s => (s.addons || []).some(a => a.page?.live_session === true) && (s.tickets || []).some(t => t.id === tid), 'Focus on and the ticket there');
    // the layer remembers its open panes per workspace in this browser (orch.live.layer.<workspace>, issue 1351): open
    // the ticket's pane as a person who had it open, and drop what earlier click-throughs left
    await page.evaluate(id => {
      Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k));
      const ws = String((typeof state === 'object' && state && state.workspace) || '');
      localStorage.setItem(ws ? 'orch.live.layer.' + ws : 'orch.live.layer', JSON.stringify({ mode: 'bottom', last: 'bottom', back: 'bottom', panes: [id], cur: id }));
    }, tid);
    await reload();
    // a roomy pane shows History in its header; a compact one (smaller than 1200 px, ORCH-463) keeps it in More
    const tab = page.locator('#live-dock .live-pane :is([data-key="live-history"], [data-key="live-pane-more"])').first();
    await tab.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no History button on the ticket pane:\n' + (await page.locator('#live-dock').innerText().catch(() => '(no live dock)')).slice(0, 400)); });
    if (await tab.getAttribute('data-key') === 'live-pane-more') {
      await tab.focus();
      await page.keyboard.press('Enter');
      await page.locator('[data-key="live-more-menu"] [data-key="live-history-item"]').waitFor({ timeout: 5000 });
    }
    const hist = page.locator('#live-dock :is([data-key="live-history"], [data-key="live-more-menu"] [data-key="live-history-item"])').first();
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
    must(sessions.some(s => s.id === OLD), 'the ticket does not continue the earlier conversation: ' + JSON.stringify(sessions.map(s => s.id)));
    try { orchAsPerson('run', 'stop', tid); } catch (e) { /* the stand-in already ended */ }
    await addonOff('focus');
    await page.evaluate(() => Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)));
  },
};
