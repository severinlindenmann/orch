// Local only: file previews of orch publish in a real browser (docs/publish.md "Previews").
// Builds and starts orch-publish on 127.0.0.1, shares an html page, a folder page (html+css+js+json, packed by the
// orch CLI's bundle()), a png, a pdf, a md, a .py and a csv, checks each preview and screenshots it.
// Usage: node publish-previews.mjs [out dir]   (default ~/orch-dev/state/fresh-start-2026-11-04/ux5/publish)
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import { webcrypto as crypto } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUT = path.resolve(process.argv[2] || path.join(os.homedir(), 'orch-dev/state/fresh-start-2026-11-04/ux5/publish'));
const BASE = path.join(os.homedir(), 'orch-dev');
fs.mkdirSync(BASE, { recursive: true });
const TMP = fs.mkdtempSync(path.join(BASE, '.tf-pubprev-'));
const ADMIN = 'preview-admin-' + Math.random().toString(36).slice(2);
const port = 18000 + Math.floor(Math.random() * 900);
const aport = port + 50;
const pub = `http://127.0.0.1:${port}`;
const fails = [];
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) fails.push(what); };

const b64u = (b) => Buffer.from(b).toString('base64url');
async function encrypt(content, name, type) {
  const key = crypto.getRandomValues(new Uint8Array(32));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const header = Buffer.from(JSON.stringify({ name, type, size: content.length }));
  const n = Buffer.alloc(4); n.writeUInt32BE(header.length);
  const k = await crypto.subtle.importKey('raw', key, 'AES-GCM', false, ['encrypt']);
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: Buffer.from('OPF1'), tagLength: 128 },
    k, Buffer.concat([n, header, Buffer.from(content)]));
  return { blob: Buffer.concat([Buffer.from('OPF1'), iv, Buffer.from(ct)]), key: b64u(key) };
}
function pdf(text) { // one page, Helvetica, offsets computed
  const objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R]/Count 1>>',
    '<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>', null,
    '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>'];
  const stream = `BT /F1 28 Tf 72 760 Td (${text}) Tj ET BT /F1 14 Tf 72 720 Td (A PDF shared with orch publish.) Tj ET`;
  objs[3] = `<</Length ${stream.length}>>\nstream\n${stream}\nendstream`;
  let s = '%PDF-1.4\n'; const off = [];
  objs.forEach((o, i) => { off.push(s.length); s += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = s.length;
  s += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + off.map((o) => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return Buffer.from(s + `trailer\n<</Size ${objs.length + 1}/Root 1 0 R>>\nstartxref\n${x}\n%%EOF\n`);
}

let srv, browser;
try {
  const env = { ...process.env, PATH: `/opt/homebrew/opt/rustup/bin:${process.env.PATH}` };
  const b = spawnSync('cargo', ['build', '-j', '4', '-q'], { cwd: path.join(REPO, 'publish'), env, stdio: 'inherit' });
  if (b.status) throw new Error('cargo build failed');
  srv = spawn(path.join(REPO, 'publish/target/debug/orch-publish'), [], {
    stdio: 'ignore',
    env: { PATH: process.env.PATH, ORCH_PUBLISH_DATA_DIR: path.join(TMP, 'data'), ORCH_PUBLISH_ADMIN_TOKEN: ADMIN,
      ORCH_PUBLISH_LISTEN: `127.0.0.1:${port}`, ORCH_PUBLISH_ADMIN_LISTEN: `127.0.0.1:${aport}`, ORCH_PUBLISH_PUBLIC_URL: pub },
  });
  for (let i = 0; i < 80; i++) { try { if ((await fetch(pub + '/health')).ok) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }
  const ws = await (await fetch(`http://127.0.0.1:${aport}/admin/api/workspaces`, {
    method: 'POST', headers: { 'x-orch-admin': ADMIN, 'content-type': 'application/json' },
    body: JSON.stringify({ name: 'Previews', description: 'browser check', tags: ['e2e'], rights: { files: true, apps: false, permanent: false, public: false } }),
  })).json();
  async function share(content, name, type) {
    const e = await encrypt(content, name, type);
    const r = await (await fetch(pub + '/v1/files', { method: 'POST', body: e.blob,
      headers: { 'x-orch-workspace': ws.id, authorization: 'Bearer ' + ws.token } })).json();
    return `${pub}/f/${r.id}#k=${e.key}`;
  }

  // fixtures
  browser = await chromium.launch({ channel: 'chromium' }); // full Chromium (new headless) has the PDF viewer
  const shot = await browser.newPage({ viewport: { width: 900, height: 520 } });
  await shot.setContent('<body style="margin:0;background:linear-gradient(135deg,#1e3a8a,#60a5fa);font:600 48px system-ui;color:#fff;display:grid;place-items:center;height:100vh">Quarterly chart<br><span style="font-size:22px">a PNG preview</span></body>');
  const png = await shot.screenshot();
  await shot.close();
  const site = path.join(TMP, 'site');
  fs.mkdirSync(path.join(site, 'data'), { recursive: true });
  fs.writeFileSync(path.join(site, 'index.html'), '<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><h1 id="t">Team board</h1><p id="n">loading…</p><img src="data/dot.svg" width="40" alt="dot"><p><a href="about.html">About this page</a></p><script src="app.js"></script></body></html>');
  fs.writeFileSync(path.join(site, 'about.html'), '<!doctype html><link rel="stylesheet" href="style.css"><h1 id="about">About</h1>');
  fs.writeFileSync(path.join(site, 'style.css'), 'body{font:16px system-ui;background:#f4f7fb;margin:32px}h1{color:rgb(37, 99, 235)}');
  fs.writeFileSync(path.join(site, 'app.js'), 'fetch("data/items.json").then(r=>r.json()).then(d=>{document.getElementById("n").textContent=d.items.length+" items: "+d.items.join(", ")});');
  fs.writeFileSync(path.join(site, 'data/items.json'), '{"items":["plan","build","ship"]}');
  fs.writeFileSync(path.join(site, 'data/dot.svg'), '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#60a5fa"/></svg>');
  fs.writeFileSync(path.join(site, '.env'), 'SECRET=never');
  const py = spawnSync('uv', ['run', '--project', path.join(REPO, 'workspace'), 'python', '-c',
    'import sys,pathlib;from orch.publish import bundle;sys.stdout.buffer.write(bundle(pathlib.Path(sys.argv[1])))', site], { maxBuffer: 1 << 26 });
  if (py.status) throw new Error('bundle: ' + py.stderr);
  const html = '<!doctype html><html><head><style>body{font:16px system-ui;margin:40px;background:#fff8e7}h1{color:#b45309}</style></head><body><h1>Single page report</h1><p id="js">script did not run</p><p id="parent"></p><p id="store"></p><script>document.getElementById("js").textContent="inline script ran";try{parent.location.href;document.getElementById("parent").textContent="parent readable"}catch(e){document.getElementById("parent").textContent="parent blocked"}try{localStorage.length;document.getElementById("store").textContent="storage open"}catch(e){document.getElementById("store").textContent="storage blocked"}</script></body></html>';
  const md = '# Release notes\n\nThis week we shipped **file previews** for `orch publish`.\n\n## What changed\n\n- Images, PDFs, video and audio open in the page\n- [x] Markdown is rendered\n- [ ] Office files still download\n\n> Raw HTML like <script>alert(1)</script> is shown as text.\n\n| Format | Preview |\n|---|---|\n| png | image |\n| md | rendered |\n\n```py\ndef hello(name):\n    return f"hi {name}"\n```\n';
  const code = '"""Small example."""\nimport json\n\n\ndef total(items: list[dict]) -> float:\n    # add up the prices\n    return sum(i["price"] * i.get("qty", 1) for i in items)\n\n\nif __name__ == "__main__":\n    print(json.dumps({"total": total([{"price": 9.5, "qty": 2}])}))\n';
  const csv = 'name,team,score\n"Ada, L.",core,98\nGrace,relay,95\nLinus,publish,91\n';
  const links = {
    html: await share(Buffer.from(html), 'report.html', 'text/html'),
    folder: await share(py.stdout, 'site', 'application/vnd.orch.bundle'),
    png: await share(png, 'chart.png', 'image/png'),
    pdf: await share(pdf('Invoice 2026-11'), 'invoice.pdf', 'application/pdf'),
    md: await share(Buffer.from(md), 'NOTES.md', 'text/markdown'),
    py: await share(Buffer.from(code), 'total.py', 'text/x-python'),
    csv: await share(Buffer.from(csv), 'scores.csv', 'text/csv'),
    docx: await share(Buffer.from('PK fake office file'), 'plan.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
  };

  fs.mkdirSync(OUT, { recursive: true });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 }, colorScheme: 'dark' })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const open = async (k) => { await page.goto(links[k]); await page.waitForSelector('.file-page'); };
  const save = (k) => page.screenshot({ path: path.join(OUT, `${k}.png`) });

  await open('html');
  const frame = page.frameLocator('#preview iframe');
  await frame.locator('#js').filter({ hasText: 'inline script ran' }).waitFor({ timeout: 10000 });
  check(await page.getAttribute('#preview iframe', 'sandbox') === 'allow-scripts', 'html: iframe sandbox is exactly allow-scripts');
  check((await frame.locator('#parent').textContent()) === 'parent blocked', 'html: page cannot read the parent (key stays safe)');
  check((await frame.locator('#store').textContent()) === 'storage blocked', 'html: no storage/cookies in the frame');
  check(await page.isVisible('#fullscreen'), 'html: Full screen button');
  check((await page.textContent('#preview .viewer-bar')).includes('Runs in a safe frame'), 'html: safe frame label');
  check(/Shared with you · .* · 7 days left/.test(await page.textContent('.file-heading p')), 'header: shared · size · days left');
  await save('html');
  await page.click('#fullscreen');
  check(await page.$eval('#preview', (e) => e.classList.contains('full')), 'html: full screen on');
  await save('html-fullscreen');
  await page.keyboard.press('Escape');

  await open('folder');
  const ff = page.frameLocator('#preview iframe');
  await ff.locator('#n').filter({ hasText: '3 items' }).waitFor({ timeout: 10000 });
  check((await ff.locator('#n').textContent()) === '3 items: plan, build, ship', 'folder: fetch() of relative json works');
  check((await ff.locator('h1').evaluate((e) => getComputedStyle(e).color)) === 'rgb(37, 99, 235)', 'folder: css file applied');
  check(await ff.locator('img').evaluate((e) => e.complete && e.naturalWidth > 0), 'folder: image from the folder loads');
  check((await page.textContent('#preview .chip')) === 'Website · 6 files', 'folder: .env left out by the packer (Website · 6 files)');
  await save('folder');
  await ff.locator('a').click();
  await ff.locator('#about').waitFor({ timeout: 5000 });
  check(true, 'folder: link to another page of the folder opens it');

  await open('png');
  await page.waitForSelector('#preview .viewer-bar >> text=900 × 520');
  check(await page.$eval('#preview img', (e) => e.complete && e.naturalWidth === 900), 'png: image shown with its size');
  await save('png');

  await open('pdf');
  check((await page.getAttribute('#preview iframe', 'src')).startsWith('blob:'), 'pdf: viewer frame with a blob url');
  check((await page.textContent('#preview .viewer-bar')).includes('1 page'), 'pdf: page count');
  await page.waitForTimeout(3500);
  await save('pdf');

  await open('md');
  check(await page.isVisible('#preview .md h1'), 'md: rendered');
  check((await page.textContent('#preview .md blockquote')).includes('<script>'), 'md: raw html shown as text');
  check(await page.$('#preview .md script') === null, 'md: no script element');
  await save('md');

  await open('py');
  check(await page.isVisible('#preview pre.code .tk-k'), 'py: highlighted code');
  check((await page.textContent('#preview .viewer-bar.foot')).includes('11 lines'), 'py: line count');
  await save('py');

  await open('csv');
  check((await page.$$('#preview table.sheet tr')).length === 4, 'csv: table with 4 rows');
  check((await page.textContent('#preview .chip')) === '3 columns', 'csv: column chip');
  await save('csv');

  await open('docx');
  check(await page.$('#preview') === null && (await page.textContent('.other-card')).includes('No preview for Word files yet'), 'docx: card + download only');
  await save('docx');

  await page.setViewportSize({ width: 390, height: 800 });
  for (const k of ['md', 'png', 'folder', 'docx']) { await open(k); await page.waitForTimeout(400); await save(k + '-phone'); }

  check(errors.length === 0, 'no page errors ' + errors.join(' | '));
  console.log(fails.length ? `${fails.length} FAILED` : 'ALL OK', '- screenshots in', OUT);
  process.exitCode = fails.length ? 1 : 0;
} finally {
  if (browser) await browser.close();
  if (srv) srv.kill();
  fs.rmSync(TMP, { recursive: true, force: true });
}
