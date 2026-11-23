// Settings > General > Copies on this computer, with real copies made here in the throw-away home:
// - A stuck copy: a ticket's copy where git was interrupted (an old index.lock, as a crash leaves it) is kept when
//   its ticket is done. Settings says a copy could not be cleaned up; the person presses Try again, reloads, and the
//   line no longer says so.
// - A moved project: a second workspace made a copy, then its folder was deleted (the project's git folder stays).
//   Settings says a copy is from a moved or deleted project; the person presses "Remove the moved ones", reloads,
//   and the line no longer says so.
const fs = require('node:fs');
const path = require('node:path');

const MAKE_COPY = 'import sys; from pathlib import Path; from orch import worktrees\n' +
  'e = worktrees.create(Path(sys.argv[1]), sys.argv[2])\n' +
  'print(worktrees.work_dir(e) if e else "")';
/** orch's own line on why it made no copy for a ticket (its copy-setup log), so a failure names the reason */
const whyNoCopy = (ws, tid) => {
  try { return fs.readFileSync(path.join(ws, '.orch', 'run', 'logs', `${tid}-copy-setup.log`), 'utf8').trim().split('\n').pop(); } catch (_) { return '(no reason written)'; }
};

module.exports = {
  name: 'Copies: try again on a stuck copy, remove copies of a moved project',
  covers: ['copies.retry', 'copies.remove_orphaned', 'page:settings/general'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, orchIn, git, python, workspace, home, until }) {
    // the workspace is a git project with at least one commit (an earlier click-through may have made it one, or
    // left a git folder with no commit yet: ORCH-1652)
    if (!fs.existsSync(path.join(workspace, '.git'))) git(workspace, 'init', '-q');
    let hasCommit = true;
    try { git(workspace, 'rev-parse', '--verify', '-q', 'HEAD'); } catch (_) { hasCommit = false; }
    if (!hasCommit) {
      fs.writeFileSync(path.join(workspace, 'menu.txt'), 'Soup\n');
      git(workspace, 'add', 'menu.txt');
      git(workspace, 'commit', '-q', '-m', 'Start');
    }
    orchAsPerson('config', 'set', 'workflow.copies', 'together');

    // a stuck copy
    const tid = JSON.parse(orch('ticket', 'new', 'Rewrite the lunch invite', '--json')).id;
    const copy = python(MAKE_COPY, workspace, tid).trim();
    must(copy && fs.existsSync(copy), 'no copy was made for the ticket: ' + (copy || whyNoCopy(workspace, tid)));
    fs.writeFileSync(path.join(copy, 'invite.txt'), 'Friday, 12:00, Seehaus\n');
    const lock = path.join(git(copy, 'rev-parse', '--absolute-git-dir').trim(), 'index.lock');
    fs.writeFileSync(lock, '');
    const old = new Date(Date.now() - 20 * 60 * 1000);
    fs.utimesSync(lock, old, old);   // git was interrupted 20 minutes ago
    orch('ticket', 'summary', tid, 'Invite rewritten.');
    orchAsPerson('ticket', 'status', tid, 'dropped');
    orchAsPerson('copy', 'clean');
    await open('#settings/general');
    await until(s => (s.settings?.copies_disk?.stuck || []).length > 0, 'a copy that could not be cleaned up');
    await reload();
    must((await text()).includes('a copy could not be cleaned up'), 'Settings does not say a copy could not be cleaned up');
    await act('copies.retry', () => page.locator('[data-key="settings-copies-retry"]').click());
    await until(s => !(s.settings?.copies_disk?.stuck || []).length, 'the stuck copy cleaned up');
    await reload();
    must(!(await text()).includes('a copy could not be cleaned up'), 'Settings still says a copy could not be cleaned up after Try again and a reload');
    must(!fs.existsSync(copy), 'the stuck copy is still there');

    // copies of a moved project
    const project = path.join(home, 'Garden');
    const moved = path.join(project, 'Planning');
    fs.mkdirSync(moved, { recursive: true });
    git(project, 'init', '-q');
    fs.writeFileSync(path.join(project, 'plants.txt'), 'Basil\n');
    git(project, 'add', 'plants.txt');
    git(project, 'commit', '-q', '-m', 'Start');
    orchIn(moved, 'init');
    orchIn(moved, 'config', 'set', 'workflow.copies', 'together');
    const tid2 = JSON.parse(orchIn(moved, 'ticket', 'new', 'Water the basil', '--json')).id;
    const copy2 = python(MAKE_COPY, moved, tid2).trim();
    must(copy2 && fs.existsSync(copy2), 'no copy was made in the second workspace');
    fs.rmSync(moved, { recursive: true, force: true });   // the workspace folder is gone; the project's git stays
    await until(s => (s.settings?.copies_disk?.orphaned || []).length > 0, 'copies of a moved project');
    await reload();
    must((await text()).includes('from a moved or deleted project'), 'Settings does not say a copy is from a moved project');
    await act('copies.remove_orphaned', () => page.locator('[data-key="settings-copies-orphaned"]').click());
    await until(s => !(s.settings?.copies_disk?.orphaned || []).length, 'the copies of the moved project removed');
    await reload();
    must(!(await text()).includes('from a moved or deleted project'), 'Settings still names a moved project after Remove and a reload');
    must(!fs.existsSync(copy2), 'the copy of the moved project is still there');
    orchAsPerson('config', 'set', 'workflow.copies', 'off');
  },
};
