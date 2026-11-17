// ORCH-186: the add-on frame asks for fullscreen one way only (no console warning), and a read refused for a
// missing sign-in (401) shows the same sign-in notice as a refused click (403).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');

test('the add-on frame sets allow=fullscreen without the old allowfullscreen attribute', () => {
  const frame = /function pageFrame[\s\S]*?\n}\n/.exec(web('pages/settings.js'))[0];
  assert.match(frame, /allow:'fullscreen'/);
  assert.doesNotMatch(frame, /allowfullscreen/i);
});

test('a 401 answer shows the sign-in notice too', () => {
  assert.match(web('session.js'), /r\.status === 401 \|\| r\.status === 403\) signInNotice\(r\)/);
});

// ORCH-186 review: passes go only to the add-on's own page, never to its files, answers or ticket pages.
test('a pass goes only to the add-on page itself', () => {
  const line = /const frameEntry = .*;/.exec(web('pages/settings.js'))[0];
  const frameEntry = new Function(line + '; return frameEntry;')();
  for (const ok of ['', 't/t_abcdef', 'order/x']) assert.equal(frameEntry(ok), true, ok);
  for (const no of ['api/order/x/file/evil.svg', 'api', 'page/t_abcdef/0123456789abcdef/x.html', 'kit/frame.js', 'web/x', 'x.html', 'a//b', '../x'])
    assert.equal(frameEntry(no), false, no);
});

// kit/frame.js in a fake sandboxed frame: takes the passes out of the address, sends the pass only as a header to
// this server, the file pass only in this add-on's addresses, and its per-frame code with every message.
function frameEnv(hash, state = null) {
  const posts = [], fetched = [], replaced = [], listeners = {};
  const loc = {protocol:'http:', host:'127.0.0.1:8420', pathname:'/addon/focus/t/t_abcdef', search:'', hash, href:'http://127.0.0.1:8420/addon/focus/t/t_abcdef' + hash};
  const win = {
    top:{}, origin:'null', location:loc,
    parent:{postMessage:(m, o) => posts.push([m, o])},
    history:{state, replaceState:(s, _t, url) => { win.history.state = s; replaced.push(url); loc.hash = url.includes('#') ? url.slice(url.indexOf('#')) : ''; }},
    fetch:(input, init) => { fetched.push([String(input), init]); return Promise.resolve({status:200}); },
    document:{addEventListener:(n, f) => { listeners[n] = f; }},
    URL, Headers, Date, Request:undefined, EventSource:undefined,
  };
  win.self = win; win.window = win;
  new Function('window', 'self', 'location', 'history', 'document', 'URL', 'Headers', 'Request', fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/frame.js'), 'utf8'))
    (win, win, loc, win.history, win.document, URL, Headers, undefined);
  return {win, posts, fetched, replaced, listeners};
}
const P1 = 'p'.repeat(43), F1 = 'f'.repeat(43), C1 = 'ab'.repeat(16);

test('frame.js takes the passes out of the address and keeps only its code for a reload of the same page', () => {
  const {win, replaced} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1 + '&results');
  assert.deepEqual(replaced, ['/addon/focus/t/t_abcdef#results']);
  assert.equal(win.OrchFrame.on, true); assert.equal(win.OrchFrame.chan, C1);
  assert.deepEqual(win.history.state.orchFrame, {chan:C1});  // the passes stay in memory only
  const again = frameEnv('#results', win.history.state);
  assert.equal(again.win.OrchFrame.chan, C1);
  assert.deepEqual(again.posts, [[{orch:'frame-go', path:'/addon/focus/t/t_abcdef', hash:'results', fresh:true, chan:C1}, 'http://127.0.0.1:8420']]);
});

test('frame.js sends the pass only as a header to this server, the file pass only in its own addresses', async () => {
  const {win, fetched} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1);
  await win.fetch('/addon/focus/api/t/t_abcdef');
  await win.fetch('https://example.com/x');
  await win.fetch('/addon/viewer/api/x');
  await win.fetch('/api/act');
  assert.equal(fetched[0][1].headers.get('X-Orch-Frame'), P1);
  assert.equal(fetched[0][1].redirect, 'error');  // a call that carries the pass is never redirected
  assert.equal(fetched[1][1], undefined);  // another site: nothing added
  assert.equal(fetched[2][1], undefined);  // another add-on's address: nothing added
  assert.equal(fetched[3][1].headers.get('X-Orch-Frame'), P1);  // a dashboard call a page makes (the server decides)
  assert.equal(win.OrchFrame.url('/addon/focus/api/file?t=t_abcdef&m=view'), '/addon/focus/api/file?t=t_abcdef&m=view&orch-frame=' + F1);
  assert.equal(win.OrchFrame.url('/api/act'), '/api/act');  // not this add-on's address: no pass
  assert.equal(win.OrchFrame.url('https://example.com/x.png'), 'https://example.com/x.png');
});

test('frame.js asks for new passes when it has none, and its messages carry the per-frame code', () => {
  const none = frameEnv('');
  assert.deepEqual(none.posts, [[{orch:'frame-go', path:'/addon/focus/t/t_abcdef', hash:'', fresh:true}, 'http://127.0.0.1:8420']]);
  const {listeners, posts} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1);
  const click = href => { let stopped = false; const a = {getAttribute:n => (n === 'href' ? href : null), hasAttribute:() => false};
    listeners.click({defaultPrevented:false, button:0, target:{closest:() => a}, preventDefault:() => { stopped = true; }}); return stopped; };
  assert.equal(click('/addon/focus/t/t_other'), true);
  assert.deepEqual(posts.at(-1), [{orch:'frame-go', path:'/addon/focus/t/t_other', hash:'', chan:C1}, 'http://127.0.0.1:8420']);
  const before = posts.length;
  assert.equal(click('/addon/viewer/x?a=1'), true);  // another add-on's page: never opened in this frame
  assert.equal(posts.length, before);
  assert.equal(click('https://example.com/'), true);  // another site never opens inside this frame
});
