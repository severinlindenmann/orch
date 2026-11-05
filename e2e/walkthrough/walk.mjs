// Visual click-through of the live orch publish + relay and a workspace, one screenshot per step.
// Usage: see run.sh. Env: E2E_PUBLISH_ADMIN_TOKEN, E2E_RELAY_ADMIN_TOKEN (never printed), WALK_TMP, WALK_OUT.
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../..');
const TMP = process.env.WALK_TMP;
const OUT = process.env.WALK_OUT || path.join(process.env.HOME, 'orch-dev/state/fresh-start-2026-11-04/walkthrough');
const PT = process.env.E2E_PUBLISH_ADMIN_TOKEN, RT = process.env.E2E_RELAY_ADMIN_TOKEN;
const PUB_ADMIN = process.env.PUB_ADMIN || 'http://100.71.130.135:8411';
const REL_ADMIN = process.env.REL_ADMIN || 'http://100.71.130.135:8412';
if (!TMP || !PT || !RT) { console.error('need WALK_TMP, E2E_PUBLISH_ADMIN_TOKEN, E2E_RELAY_ADMIN_TOKEN'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });
for (const f of fs.readdirSync(OUT)) if (/^\d\d-.*\.png$/.test(f)) fs.rmSync(path.join(OUT, f)); // only this script's own screenshots

const secrets = [PT, RT];
const scrub = s => secrets.reduce((t, x) => t.split(x).join('<token>'), String(s));
const toolBin = path.join(TMP, '.local/bin');
const env = {
  HOME: TMP, PATH: `${toolBin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin`,
  UV_CACHE_DIR: path.join(process.env.HOME, '.cache/uv'), ORCH_REPO: REPO, LANG: 'en_US.UTF-8',
  ORCH_HOME: process.env.WALK_ORCH_HOME || '', // only trusted under the real home (see run.sh)
};
function sh(cmd, cwd = TMP, input) {
  const r = spawnSync('sh', ['-c', cmd], { cwd, env, encoding: 'utf8', timeout: 180000, input });
  return { code: r.status, out: (r.stdout || '') + (r.stderr || ''), stdout: r.stdout || '' };
}
const sleep = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
function must(cmd, cwd) {
  let r;
  for (let i = 0; i < 6; i++) { // the network of this machine flaps: retry connection errors only
    r = sh(cmd, cwd);
    if (r.code === 0 || !/Cannot reach|Connection refused|timed out|Could not resolve/i.test(r.out)) break;
    sleep(5000);
  }
  if (r.code !== 0) throw new Error(`${cmd.split(' ').slice(0, 4).join(' ')} -> exit ${r.code}: ${scrub(r.out).slice(0, 300)}`);
  return r.out.trim();
}

const results = [];
let n = 0, page;
async function shot(name) {
  const file = `${String(n).padStart(2, '0')}-${name}.png`;
  try { await page.screenshot({ path: path.join(OUT, file), fullPage: true }); } catch { return ''; }
  return file;
}
async function step(name, text, fn) {
  n++;
  let status = 'pass', note = '', file = '';
  try { note = (await fn()) || ''; } catch (e) { status = 'fail'; note = scrub(e.message).split('\n')[0].slice(0, 300); }
  file = await shot(name);
  results.push({ n, name, text, status, note, file });
  console.log(`${status.toUpperCase()} ${n} ${text}${note ? ' - ' + note : ''}`);
}
// A step that only runs shell commands: the screenshot shows the last page.
const cliStep = step;

const ws = {}; // name -> {relay:{id,cmd}, pub:{id,cmd}}
const parse = (prompt, kind) => {
  const m = new RegExp(`orch ${kind} connect (\\S+) --workspace (\\S+) --token (\\S+)`).exec(prompt);
  if (!m) throw new Error(`no connect command in the ${kind} prompt`);
  return { url: m[1], id: m[2], cmd: m[0] };
};
const dirs = { Pilatus: path.join(TMP, 'pilatus'), Reports: path.join(TMP, 'reports') };

async function relayLogin() {
  await page.goto(REL_ADMIN + '/admin#overview');
  await page.fill('input[name=token]', RT);
  await page.click('button[type=submit]');
  await page.waitForSelector('.workspace-card, .empty, .summary-line');
}
async function relayAdd(name, description, tags) {
  await page.goto('about:blank');
  await page.goto(REL_ADMIN + '/admin#add');
  await page.fill('input[name=name]', name);
  await page.click('details summary:has-text("More options")');
  await page.fill('input[name=description]', description);
  await page.fill('input[name=tags]', tags);
  await page.click('button[type=submit]');
  await page.waitForSelector('#install-prompt');
  return parse(await page.inputValue('#install-prompt'), 'relay');
}

async function adminApi(base, token, method, p) {
  const r = await fetch(base + '/admin/api' + p, { method, headers: { 'X-Orch-Admin': token } });
  return r.ok ? (r.status === 204 ? null : r.json().catch(() => null)) : null;
}

let dash;
const cleanup = [];
try {
  // ---------- setup (not screenshotted) ----------
  must(`uv tool install ${REPO}/workspace`);
  for (const [k, d] of Object.entries(dirs)) { fs.mkdirSync(d, { recursive: true }); must('orch init', d); }
  must('orch addon add dashboard --yes', dirs.Pilatus);

  const browser = await chromium.launch();
  page = await (await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: process.env.WALK_SCHEME || 'dark', acceptDownloads: true })).newPage();

  // ---------- 1. relay admin ----------
  page.setDefaultTimeout(10000);
  await step('relay-login', 'Relay admin: open the portal and sign in with the admin token', relayLogin);
  await step('relay-add-pilatus', 'Relay admin: add workspace "Walk Pilatus" (description + tags), see its connect prompt', async () => {
    ws.Pilatus = { relay: await relayAdd('Walk Pilatus', 'Walkthrough workspace that sends', 'walk, sender') };
  });
  await step('relay-add-reports', 'Relay admin: add workspace "Walk Reports", see its connect prompt', async () => {
    ws.Reports = { relay: await relayAdd('Walk Reports', 'Walkthrough workspace that receives', 'walk, receiver') };
  });
  await step('relay-overview', 'Relay admin: overview lists both new workspaces', async () => {
    await page.goto(REL_ADMIN + '/admin#overview');
    await page.waitForSelector('text=Walk Pilatus'); await page.waitForSelector('text=Walk Reports');
  });
  await step('relay-rules', 'Relay admin: set a pair rule Pilatus -> Reports (text, files) and save', async () => {
    await page.goto(REL_ADMIN + '/admin#rules');
    await page.waitForSelector('.pair-group, .pair');
    // pairs that allow nothing are folded away: open every fold first
    await page.evaluate(() => document.querySelectorAll('details.pair-group').forEach(d => { d.open = true; }));
    const pair = page.locator('.pair', { has: page.locator('h3', { hasText: 'Walk Pilatus → Walk Reports' }) });
    for (const k of ['Messages', 'Files'])
      await pair.locator('label.pair-toggle', { hasText: k }).locator('input').check();
    await page.click('button:has-text("Save")');
    await page.waitForSelector('#toast:not([hidden])');
  });

  // ---------- 2. publish admin ----------
  await step('publish-login', 'Publish admin: open the portal and sign in with the admin token', async () => {
    await page.goto(PUB_ADMIN + '/admin#workspaces');
    await page.fill('#admin-token', PT);
    await page.click('#login-form button[type=submit]');
    await page.waitForSelector('.summary-line, .empty-card');
  });
  await step('publish-add', 'Publish admin: add "Walk Pilatus" with description, tags and rights; see the prompt', async () => {
    await page.goto(PUB_ADMIN + '/admin#add');
    await page.fill('#name', 'Walk Pilatus');
    await page.click('details.more summary:has-text("More options")');
    await page.fill('#description', 'Walkthrough workspace that publishes');
    await page.fill('#tags', 'walk, publish');
    await page.click('form button[type=submit]');
    await page.waitForSelector('button.copy-prompt');
    await page.click('details.more summary:has-text("Show what will be copied")');
    ws.Pilatus.pub = parse(await page.textContent('details.more pre'), 'publish');
  });

  // ---------- 3. workspace side ----------
  await cliStep('connect', 'Workspace: connect Pilatus to publish and relay, Reports to relay, with the prompts\' commands', async () => {
    must(ws.Pilatus.pub.cmd, dirs.Pilatus);
    must(ws.Pilatus.relay.cmd, dirs.Pilatus);
    must(ws.Reports.relay.cmd, dirs.Reports);
    return must('orch relay whoami', dirs.Pilatus).split('\n')[0];
  });
  let tid;
  await cliStep('ticket', 'Workspace: ticket with checklist, evidence, a question and links', async () => {
    const d = dirs.Pilatus;
    tid = JSON.parse(must('orch ticket new "Walk: export the invoices" --json', d)).id;
    must(`orch check add ${tid} "Write the export"`, d);
    must(`orch check add ${tid} "Check the totals"`, d);
    must(`orch check done ${tid} c1 --evidence '{"type":"command","ref":"pytest -q"}'`, d);
    must(`orch ask ${tid} "Which format?" --option CSV --option XLSX --recommend CSV`, d);
    must(`orch link add ${tid} --type jira --url https://example.com/browse/WALK-1 --title "WALK-1"`, d);
    must(`orch link add ${tid} --type file --url file:///tmp/walk.txt --title "notes"`, d);
    must(`orch log ${tid} "Started the walkthrough"`, d);
    return tid;
  });
  const port = 18000 + Math.floor(Math.random() * 900);
  await step('dashboard-list', 'Dashboard: start it and open the ticket list', async () => {
    dash = spawn('orch', ['dashboard', 'serve', '--port', String(port)], { cwd: dirs.Pilatus, env, stdio: 'ignore' });
    for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/`)).ok) break; } catch {} await new Promise(r => setTimeout(r, 250)); }
    await page.goto(`http://127.0.0.1:${port}/#tickets`);
    await page.waitForSelector('a.card');
  });
  await step('dashboard-detail', 'Dashboard: click the ticket, see checklist, evidence, question, links, history', async () => {
    await page.click('a.card');
    await page.waitForSelector('text=Which format?');
  });
  await step('dashboard-no-tab', 'Dashboard: no Schedule tab while the scheduler add-on is off', async () => {
    if (await page.locator('a[href="#addon/scheduler"]').count()) throw new Error('scheduler tab without the add-on');
  });
  await step('dashboard-scheduler', 'Dashboard: turn the scheduler on (orch addon add scheduler), repeat the ticket, open the Schedule tab', async () => {
    must('orch addon add scheduler --yes', dirs.Pilatus);
    must(`orch scheduler repeat ${tid} "0 7 * * 1"`, dirs.Pilatus);
    await page.reload(); await page.waitForSelector('a[href="#addon/scheduler"]');
    await page.click('a[href="#addon/scheduler"]');
    await page.waitForSelector('text=Repeating');
  });
  await step('dashboard-inbox', 'Dashboard: inbox view', async () => {
    await page.click('a[href="#inbox"]'); await page.waitForTimeout(500);
  });

  let fileLink;
  await step('file-open', 'Publish: share a file, open the /f/ link (decrypts in the browser) and download it', async () => {
    const content = 'walkthrough file ' + Date.now() + '\n';
    fs.writeFileSync(path.join(dirs.Pilatus, 'report.txt'), content);
    const out = must('orch publish file report.txt --days 1', dirs.Pilatus);
    fileLink = out.split('\n').pop().trim();
    await page.goto(fileLink);
    await page.waitForSelector('text=Download file');
    const [dl] = await Promise.all([page.waitForEvent('download'), page.click('text=Download file')]);
    const got = fs.readFileSync(await dl.path(), 'utf8');
    if (got !== content) throw new Error('downloaded bytes differ');
    return 'downloaded bytes identical';
  });
  await step('file-wrong-key', 'Publish: the same link with a wrong key shows an error page', async () => {
    await page.goto('about:blank');
    await page.goto(fileLink.replace(/#k=.*/, '#k=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'));
    await page.waitForSelector("text=This link doesn");
  });
  await step('file-no-key', 'Publish: the link without a key shows an error page', async () => {
    await page.goto('about:blank');
    await page.goto(fileLink.replace(/#k=.*/, ''));
    await page.waitForTimeout(1500);
  });

  let appLink, appName;
  await cliStep('app-deploy-python', 'Publish: create a python app with sqlite (orch publish new python --store sqlite) and deploy it', async () => {
    must('orch publish new python walk-api --store sqlite', dirs.Pilatus);
    return must('orch publish app walk-api --days 1', dirs.Pilatus).split('\n')[0];
  });
  await cliStep('app-deploy-static', 'Publish: create a static app and deploy it (used for the next steps)', async () => {
    must('orch publish new static walk-site', dirs.Pilatus);
    const out = must('orch publish app walk-site --days 1', dirs.Pilatus);
    appLink = out.split('\n').pop().trim();
    appName = /Deployed (\S+)/.exec(out)?.[1];
    return out.split('\n')[0];
  });
  await step('app-private', 'Publish: open /a/<name>/ without a token (private page)', async () => {
    const base = appLink.split('?')[0];
    await page.goto(base);
    await page.waitForTimeout(1000);
  });
  await step('app-token', 'Publish: open the app with ?token=', async () => {
    await page.goto(appLink);
    await page.waitForTimeout(1500);
  });

  let msgId;
  await cliStep('relay-send', 'Relay: Pilatus sends a text message to Reports; Reports reads it in its inbox', async () => {
    const o = must(`orch relay send "Walk Reports" "Hello from the walkthrough" --json`, dirs.Pilatus);
    msgId = JSON.parse(o).id;
    const inbox = must('orch relay inbox', dirs.Reports);
    if (!inbox.includes('Hello from the walkthrough')) throw new Error('message not in Reports inbox');
    return inbox.split('\n')[0];
  });
  await step('relay-messages', 'Relay admin: messages page shows the message', async () => {
    await page.goto(REL_ADMIN + '/admin#messages');
    const m = page.locator('details.msg', { hasText: 'Walk Reports' }).first();
    await m.waitFor();
    await m.locator('summary').first().click();   // rows are one line; open it to read the full text
    await page.waitForSelector('text=Hello from the walkthrough');
  });
  await step('relay-phones', 'Relay admin: phones page, create a pairing link/QR for Walk Pilatus', async () => {
    await page.goto(REL_ADMIN + '/admin#phones');
    await page.waitForSelector('form');
    await page.fill('form input[name=name]', 'Walk phone');
    await page.check('input[name=workspace]:near(:text("Walk Pilatus"))').catch(() => {});
    await page.click('form button[type=submit]');
    await page.waitForSelector('.qr, #toast:not([hidden])');
  });
  await step('relay-config', 'Relay admin: shared config page', async () => {
    await page.goto(REL_ADMIN + '/admin#config'); await page.waitForSelector('text=Shared tools');
  });
  await cliStep('webhook-new', 'Relay: Pilatus creates a one-time webhook', async () => {
    return must('orch relay webhook new --once', dirs.Pilatus).split('\n')[0];
  });
  await step('relay-webhooks', 'Relay admin: webhooks page shows it', async () => {
    await page.goto(REL_ADMIN + '/admin#webhooks'); await page.waitForSelector('text=Incoming events');
    await page.waitForTimeout(500);
  });

  await step('snapshot', 'Dashboard: publish a snapshot (orch dashboard snapshot --publish) and open it with its token', async () => {
    const out = must('orch dashboard snapshot --publish', dirs.Pilatus);
    const link = /(https?:\/\/\S+\?token=\S+)/.exec(out)?.[1];
    if (!link) throw new Error('no snapshot link in: ' + out.slice(0, 200));
    await page.goto(link);
    await page.waitForSelector('.snapshot-banner');
  });

  await step('publish-files', 'Publish admin: files page lists the file with no name', async () => {
    await page.goto(PUB_ADMIN + '/admin#files'); await page.waitForSelector('article.item');
    const text = await page.textContent('section.card');
    if (text.includes('report.txt')) throw new Error('file name visible in admin');
  });
  await step('publish-apps', 'Publish admin: apps page shows the apps with status', async () => {
    await page.goto(PUB_ADMIN + '/admin#apps'); await page.waitForSelector('.app-card');
  });
  await step('publish-restart', 'Publish admin: click restart on the app', async () => {
    await page.click('.app-card:has-text("Walk Pilatus") details.menu summary'); await page.click('.app-card:has-text("Walk Pilatus") [data-action="restart"]'); await page.waitForSelector('#toast:not([hidden])');
    return await page.textContent('#toast');
  });
  await step('publish-stop', 'Publish admin: click stop on the app', async () => {
    await page.goto(PUB_ADMIN + '/admin#apps'); await page.waitForSelector('.app-card');
    await page.click('.app-card:has-text("Walk Pilatus") details.menu summary'); await page.click('.app-card:has-text("Walk Pilatus") [data-action="stop"]'); await page.waitForFunction(() => /stop/i.test(document.querySelector('#toast')?.textContent || ''));
    return await page.textContent('#toast');
  });

  await browser.close();
} catch (e) {
  console.error('fatal:', scrub(e.message));
  results.push({ n: ++n, name: 'fatal', text: 'Setup or run aborted', status: 'fail', note: scrub(e.message).slice(0, 300), file: '' });
} finally {
  if (dash) dash.kill();
  // ---------- cleanup: delete every "Walk ..." workspace on both servers (removes its files and apps) ----------
  for (const [base, tok] of [[PUB_ADMIN, PT], [REL_ADMIN, RT]]) {
    const r = await adminApi(base, tok, 'GET', '/workspaces?limit=100');
    for (const w of r?.items || []) if (/^Walk /.test(w.name)) await adminApi(base, tok, 'DELETE', '/workspaces/' + encodeURIComponent(w.id));
    const left = await adminApi(base, tok, 'GET', '/workspaces?limit=100');
    console.log(`cleanup ${base}: ${(left?.items || []).filter(w => /^Walk /.test(w.name)).length} Walk workspaces left`);
  }
  // the phone created in the relay is removed with its workspace; remove it explicitly too
  const ph = await adminApi(REL_ADMIN, RT, 'GET', '/phones');
  for (const p of ph?.items || []) if (/^Walk /.test(p.name)) await adminApi(REL_ADMIN, RT, 'DELETE', '/phones/' + encodeURIComponent(p.id));
  writeIndex();
}

function writeIndex() {
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  const tokens = fs.readFileSync(path.join(REPO, 'brand/tokens.css'), 'utf8');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const pass = results.filter(r => r.status === 'pass').length;
  const rows = results.map(r => `<tr class="${r.status}"><td>${r.n}</td><td>${esc(r.text)}</td><td>${r.file ? `<a href="${r.file}"><img src="${r.file}" alt="${esc(r.name)}" loading="lazy"></a>` : ''}</td><td><span class="b ${r.status}">${r.status}</span></td><td>${esc(r.note)}</td></tr>`).join('\n');
  fs.writeFileSync(path.join(OUT, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>orch walkthrough</title><style>${tokens}
body{margin:0;padding:24px;background:var(--bg,#0f1115);color:var(--text,#e8eaed);font:14px/1.5 system-ui,sans-serif}
h1{margin:0 0 4px}p.s{color:var(--text-muted,#9aa0a6);margin:0 0 20px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--border,#2a2f38);padding:10px;vertical-align:top;text-align:left}
img{width:360px;max-width:100%;border:1px solid var(--border,#2a2f38);border-radius:8px}
.b{padding:2px 8px;border-radius:99px;font-size:12px}.b.pass{background:rgba(47,191,113,.2);color:#2fbf71}.b.fail{background:rgba(240,80,80,.2);color:#f05050}
</style></head><body><h1>orch walkthrough</h1><p class="s">${pass} of ${results.length} steps passed - ${new Date().toISOString()}</p>
<table><thead><tr><th>#</th><th>Step</th><th>Screenshot</th><th>Result</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table></body></html>`);
  console.log(`done: ${pass}/${results.length} passed -> ${OUT}/index.html`);
}
