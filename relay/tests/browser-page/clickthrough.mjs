// The relay browser page's click-through (ORCH-1197, #2495): run it with run.sh next to it, which starts a relay.
import { createRequire } from 'module';
const require = createRequire(process.env.PW_DIR + '/');
const { chromium } = require('playwright');
import headless from '../../../e2e/headless.cjs'; // the keychain options (ORCH-615)
const PUB = process.env.PUB, ADM = process.env.ADM, TOK = process.env.ADMIN_TOKEN, OUT = process.env.OUT;
const log = (...a) => console.log(...a);
const must = (c, m) => { if (!c) { console.error('FAIL: ' + m); process.exit(1); } else log('ok  ' + m); };
async function admin(method, path, body) {
  const r = await fetch(ADM + path, { method, headers: { 'X-Orch-Admin': TOK, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return { s: r.status, j: r.status === 204 ? null : await r.json() };
}
const rid = (p) => p + Array.from({ length: 16 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(Math.random() * 36)]).join('');
async function wsSend(ws, msg) {
  const m = { schema: 'orch.msg/1', id: rid('m_'), from: ws.id, created_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'), ...msg };
  const r = await fetch(PUB + '/v1/messages', { method: 'POST', headers: { 'X-Orch-Workspace': ws.id, Authorization: 'Bearer ' + ws.token, 'Content-Type': 'application/json' }, body: JSON.stringify(m) });
  if (r.status >= 300) throw new Error('send ' + r.status + ' ' + (await r.text()));
  return m.id;
}
async function wsCall(ws, method, path) {
  const r = await fetch(PUB + path, { method, headers: { 'X-Orch-Workspace': ws.id, Authorization: 'Bearer ' + ws.token } });
  return r.json();
}
const view = (title, status, done, total) => ({ title, status, running: status === 'active', checklist: Array.from({ length: total }, (_, i) => ({ text: 'Step ' + (i + 1), done: i < done })), done, total, history_tail: [], attachments: [] });

(async () => {
  const a = await admin('POST', '/admin/api/workspaces', { name: "Severin's workspace", description: 'd', tags: ['x'] });
  must(a.s === 201, 'workspace made');
  const ws = { id: a.j.id || a.j.workspace?.id, token: a.j.token };
  await wsCall(ws, 'GET', '/v1/whoami'); // marks it online
  const d = await admin('POST', '/admin/api/phones', { name: 'Max laptop', kind: 'browser', workspaces: [ws.id] });
  must(d.s === 201 && d.j.link.includes('/app#code=pc_'), 'browser invitation made on the admin side: ' + d.j.link.replace(/code=.*/, 'code=…'));

  const browser = await headless.launch(chromium, {});
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  globalThis.PG = page;
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  const reqs = [];
  page.on('request', (r) => reqs.push(r.url()));
  await page.goto(d.j.link);
  await page.getByRole('heading', { name: 'You were invited' }).waitFor();
  must(!(await page.content()).includes("Severin's workspace"), 'sign-in screen names no workspace');
  must(!page.url().includes('code='), 'code left the address bar');
  must(!reqs.some((u) => u.includes('pc_')), 'no request carried the code before the press');
  await page.screenshot({ path: OUT + '/signin-1280.png' });
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('button', { name: 'New message' }).waitFor();
  must(true, 'signed in');
  await page.screenshot({ path: OUT + '/empty-1280.png' });
  await wsSend(ws, { to: 'phones', type: 'text', ticket: 't_aaaaaa', key: 'ORCH-41', body: { text: 'I read your notes and wrote a first draft with three parts.', update: { kind: 'note', title: 'Spring newsletter' }, ticket_view: view('Spring newsletter', 'active', 2, 4) } });
  await wsSend(ws, { to: 'phones', type: 'text', ticket: 't_bbbbbb', key: 'ORCH-38', body: { text: 'Applying the new prices to 42 lines.', update: { kind: 'working', title: 'Price list 2027' }, ticket_view: view('Price list 2027', 'active', 1, 3) } });
  await wsSend(ws, { to: 'phones', type: 'question', ticket: 't_aaaaaa', key: 'ORCH-41', body: { question_id: 'q1', text: 'Which subject line?', options: ['Spring is here: three new things to try', 'Your April update'], recommended: 'Spring is here: three new things to try' } });

  await page.getByText('Spring newsletter').first().waitFor({ timeout: 20000 });
  must(true, 'tickets listed (shown by the 10 s refresh)');
  await page.getByText('Spring newsletter').first().click();
  await page.getByRole('button', { name: /Spring is here/ }).waitFor();
  await page.screenshot({ path: OUT + '/app-1280.png' });
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({ path: OUT + '/app-1920.png' });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole('button', { name: /Spring is here/ }).click();
  await page.getByText('Answered from this browser').waitFor();
  must(true, 'question answered from the browser');
  await page.getByPlaceholder(/Message your helper/).fill('Please keep it short.');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByText('Please keep it short.').waitFor();
  must(true, 'text sent on the ticket');
  // The workspace receives both, from the browser's own id, named by the admin label.
  const inbox = await wsCall(ws, 'GET', '/v1/inbox');
  const items = (inbox.items || inbox).map((x) => x.message || x);
  const ans = items.find((m) => m.type === 'answer');
  const txt = items.find((m) => m.type === 'text' && m.body.text === 'Please keep it short.');
  must(ans && ans.from === d.j.phone_id && ans.body.answered_by === 'human:Max laptop', 'workspace got the answer from the browser id, answered_by human:Max laptop');
  must(txt && txt.from === d.j.phone_id && txt.ticket === 't_aaaaaa', 'workspace got the text from the browser id on the ticket');
  const ref = await wsCall(ws, 'GET', '/v1/refresh');
  const me = ((ref.workspaces && ref.workspaces.phones) || []).find((p) => p.id === d.j.phone_id);
  must(me && me.kind === 'browser' && me.name === 'Max laptop', 'refresh lists it as kind browser ' + JSON.stringify(ref).slice(0, 300));
  // Hostile text from a workspace stays text: title, key-like text, question and options.
  const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
  await wsSend(ws, { to: 'phones', type: 'text', ticket: 't_cccccc', key: 'ORCH-50', body: { text: 'Body ' + evil, update: { kind: 'note', title: 'Evil title' }, ticket_view: view('T ' + evil, 'active', 0, 1) } });
  await wsSend(ws, { to: 'phones', type: 'question', ticket: 't_cccccc', key: 'ORCH-50', body: { question_id: 'q1', text: 'Q ' + evil, options: ['A ' + evil, 'B'], recommended: 'B' } });
  // A question with no ticket in the list (proposal-like) must still be answerable from the workspace conversation.
  await wsSend(ws, { to: 'phones', type: 'question', ticket: 't_zzzzzz', key: 'ORCH-9', body: { question_id: 'q1', text: 'Old ticket question?', options: ['Yes', 'No'], recommended: 'Yes' } });
  await page.reload();
  await page.getByText('T <img').first().waitFor({ timeout: 20000 });
  await page.getByText('T <img').first().click();
  await page.locator('.msg p', { hasText: 'Body <img' }).waitFor();
  await page.getByRole('button', { name: /A <img/ }).waitFor();
  must(!(await page.evaluate(() => window.__pwned)) && (await page.locator('.b-thread img, .b-list img').count()) === 0, 'hostile workspace text shown as text, nothing ran');
  // Draft stays with its conversation.
  await page.getByPlaceholder(/Message your helper/).fill('secret draft for ORCH-50');
  await page.getByRole('button', { name: /New message/ }).first().click();
  await page.getByRole('button', { name: 'Old ticket question?' }).count(); // render
  must((await page.locator('[data-composer] [name=text]').inputValue()) === '', 'draft did not follow into another conversation');
  await page.getByText('Old ticket question?').waitFor();
  must(true, 'question without a listed ticket shown in the workspace conversation');
  // A second invitation while signed in adds its workspace.
  const b2 = await admin('POST', '/admin/api/workspaces', { name: 'Marketing', description: 'd', tags: ['x'] });
  const ws2 = { id: b2.j.id || b2.j.workspace?.id, token: b2.j.token };
  await wsCall(ws2, 'GET', '/v1/whoami');
  const d2 = await admin('POST', '/admin/api/phones', { name: 'Max laptop 2', kind: 'browser', workspaces: [ws2.id] });
  await page.goto(d2.j.link);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByText('You can now reach Marketing.').waitFor();
  await page.locator('.b-group-h', { hasText: 'Marketing' }).waitFor();
  must(true, 'second invitation added Marketing to the signed-in browser');
  // A late thread answer never shows under another title (outside review 2).
  await page.locator('.b-group-h', { hasText: "Severin's workspace" }).waitFor();
  await page.route(/\/v1\/phone\/updates\?workspace=.*ticket=t_aaaaaa/, async (r) => { await new Promise((ok) => setTimeout(ok, 1500)); await r.continue().catch(() => {}); });
  await page.getByText('Spring newsletter').first().click();
  await page.getByText('Price list 2027').first().click();
  await page.waitForTimeout(2500);
  must((await page.locator('.b-thread-h h1').innerText()) === 'Price list 2027' && (await page.locator('.b-thread .msg p', { hasText: 'I read your notes' }).count()) === 0, 'a late answer for another ticket is dropped, not shown under Price list 2027');
  await page.unroute(/\/v1\/phone\/updates\?workspace=.*ticket=t_aaaaaa/);
  // A send whose answer is lost is sent again with the same id: the workspace gets it once (outside review 7).
  let lost = true;
  await page.route('**/v1/phone/send', async (r) => { if (!lost) return r.continue(); lost = false; await r.fetch(); await r.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"The relay is busy. Try again."}' }); });
  await page.getByPlaceholder(/Message your helper/).fill('Only once please');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.waitForTimeout(800);
  must((await page.locator('[data-composer] [name=text]').inputValue()) === 'Only once please', 'a send that failed keeps the text');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.locator('.msg.me p', { hasText: 'Only once please' }).first().waitFor();
  await page.unroute('**/v1/phone/send');
  const inbox2 = await wsCall(ws, 'GET', '/v1/inbox');
  const once = (inbox2.items || inbox2).map((x) => x.message || x).filter((m) => m.type === 'text' && m.body.text === 'Only once please');
  must(once.length === 1, 'the retried send reached the workspace once (' + once.length + ')');
  // Sign-out that fails stays signed in and says so (outside review 3).
  await page.route('**/v1/phone/signout', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"x"}' }));
  await page.locator('.b-me > summary').click();
  await page.locator('[data-signout]').click();
  await page.locator('[data-signout-yes]').click();
  await page.getByText('Sign-out did not work').waitFor();
  must(await page.locator('#b-list').isVisible(), 'a failed sign-out keeps the browser signed in');
  await page.unroute('**/v1/phone/signout');
  // A reload before Sign in keeps the invitation (outside review 5).
  const d3 = await admin('POST', '/admin/api/phones', { name: 'Lea laptop', kind: 'browser', workspaces: [ws.id] });
  const p4 = await (await browser.newContext()).newPage();
  await p4.goto(d3.j.link);
  await p4.getByRole('heading', { name: 'You were invited' }).waitFor();
  await p4.reload();
  await p4.getByRole('button', { name: 'Sign in' }).click();
  await p4.getByRole('button', { name: /New message/ }).first().waitFor();
  must(!p4.url().includes('code='), 'a reload before Sign in kept the invitation, and it signed in');
  // While a message sends, its text box is locked: nothing typed meanwhile is lost or sent under the old id.
  await page.route('**/v1/phone/send', async (r) => { await new Promise((ok) => setTimeout(ok, 1500)); await r.continue().catch(() => {}); });
  await page.getByPlaceholder(/Message your helper/).fill('Locked while sending');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.waitForTimeout(300);
  must(await page.locator('[data-composer] [name=text]').evaluate((e) => e.readOnly), 'the text box is locked while it sends');
  await page.locator('.msg.me p', { hasText: 'Locked while sending' }).first().waitFor();
  await page.waitForTimeout(300);
  must(!(await page.locator('[data-composer] [name=text]').evaluate((e) => e.readOnly)), 'the text box is open again after sending');
  await page.unroute('**/v1/phone/send');
  // A second link opened while Sign in is still running is kept and shown next (second outside review, 3).
  const d4 = await admin('POST', '/admin/api/phones', { name: 'Ana laptop', kind: 'browser', workspaces: [ws.id] });
  const d5 = await admin('POST', '/admin/api/phones', { name: 'Ana laptop 2', kind: 'browser', workspaces: [ws2.id] });
  const p5 = await (await browser.newContext()).newPage();
  p5.on('pageerror', (e) => errors.push(String(e)));
  await p5.route('**/v1/phone/pair', async (r) => { await new Promise((ok) => setTimeout(ok, 1500)); await r.continue().catch(() => {}); });
  await p5.goto(d4.j.link);
  await p5.getByRole('button', { name: 'Sign in' }).click();
  await p5.evaluate((h) => { location.hash = h; }, '#' + d5.j.link.split('#')[1]);
  await p5.waitForTimeout(2500);
  must(await p5.getByRole('heading', { name: 'You were invited' }).isVisible(), 'the newer link is shown after the first sign-in finished');
  await p5.getByRole('button', { name: 'Sign in' }).click();
  await p5.getByText('You can now reach Marketing.').waitFor();
  must(true, 'the newer link added Marketing');
  // phone width
  const p2 = await (await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: await ctx.storageState() })).newPage();
  await p2.goto(PUB + '/app');
  await p2.getByText('Spring newsletter').first().waitFor();
  await p2.screenshot({ path: OUT + '/list-390.png' });
  await p2.getByText('Spring newsletter').first().click();
  await p2.locator('.msg p', { hasText: 'I read your notes' }).waitFor();
  await p2.screenshot({ path: OUT + '/thread-390.png' });
  // Cut by the admin: the next request shows the signed-out page.
  must((await admin('DELETE', '/admin/api/phones/' + d.j.phone_id)).s === 204, 'admin cut the browser');
  await page.reload();
  await page.getByRole('heading', { name: 'This browser was signed out' }).waitFor();
  must(true, 'cut browser shows signed out');
  await page.screenshot({ path: OUT + '/cut-1280.png' });
  // The used link again
  const p3 = await (await browser.newContext()).newPage();
  await p3.goto(d.j.link);
  await p3.getByRole('button', { name: 'Sign in' }).click();
  await p3.getByRole('heading', { name: 'This invitation no longer works' }).waitFor();
  must(true, 'used link shows no longer works');
  await p3.screenshot({ path: OUT + '/used-1280.png' });
  const real = errors.filter((e) => !/Failed to load resource: the server responded with a status of (401|410|500|503)/.test(e)); must(real.length === 0, 'no script or content-rule errors (expected 401/410 of the cut and used steps and the faked 500/503 aside): ' + real.join(' | '));
  await browser.close();
})().catch(async (e) => { console.error('FAIL', e); if (globalThis.PG) { await globalThis.PG.screenshot({ path: OUT + '/fail.png' }); console.error('TEXT', (await globalThis.PG.locator('.toasts').innerText().catch(() => ''))); } process.exit(1); });
