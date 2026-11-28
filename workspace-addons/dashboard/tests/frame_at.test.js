// ORCH-241: a shipped add-on page that moves inside itself (Factory's #/order/<id>) tells the dashboard with
// frame-at; the dashboard address follows it (reload and Back keep the place) and the frame is never loaded again.
// Inside the ORCH-186 fence: only the shown frame, only with its per-frame code, only a place on the page shown.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8');
const C1 = 'ab'.repeat(16), P1 = 'p'.repeat(43), F1 = 'f'.repeat(43);

// kit/frame.js in a fake sandboxed frame (the same shape as frame_signin.test.js), with window events.
function frameEnv(hash, pathname = '/addon/factory/') {
  const posts = [], asks = [], winListeners = {};
  const loc = {protocol:'http:', host:'127.0.0.1:8420', pathname, search:'', hash, href:'http://127.0.0.1:8420' + pathname + hash};
  const win = {
    top:{}, origin:'null', location:loc,
    // the one ask every framed page sends first (W-006, is the window wide?) carries no pass and no code; it has its own test in frame_at.test.js
    parent:{postMessage:(m, o) => { if (m?.orch !== 'frame-window') posts.push([m, o]); else asks.push([m, o]); }},
    history:{state:null, replaceState:(s, _t, url) => { win.history.state = s; loc.hash = url.includes('#') ? url.slice(url.indexOf('#')) : ''; }},
    fetch:() => Promise.resolve({status:200}),
    addEventListener:(n, f) => { winListeners[n] = f; },
    document:{addEventListener:() => {}},
    URL, Headers, Date, Request:undefined, EventSource:undefined,
  };
  win.self = win; win.window = win;
  new Function('window', 'self', 'location', 'history', 'document', 'URL', 'Headers', 'Request', read('../../../workspace/src/orch_ui/static/frame.js'))
    (win, win, loc, win.history, win.document, URL, Headers, undefined);
  const go = h => { loc.hash = h; (winListeners.hashchange || (() => {}))(); };
  return {posts, asks, go, loc, winListeners, win};
}

test('frame.js tells the dashboard about a move inside its own page, with its code', () => {
  const {posts, go} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1);
  go('#/order/t_abcdef/proposal');
  assert.deepEqual(posts.at(-1), [{orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef/proposal', chan:C1}, 'http://127.0.0.1:8420']);
  const n = posts.length;
  go('#/order/t_abcdef/proposal');  // the same place again: nothing new
  assert.equal(posts.length, n);
  go('#/');
  assert.deepEqual(posts.at(-1)[0], {orch:'frame-at', path:'/addon/factory/', hash:'/', chan:C1});
});

test('frame.js says nothing for a place the dashboard would refuse, and nothing without its code', () => {
  const {posts, go} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1);
  const n = posts.length;
  go('#a b<script>');
  go('#' + 'x'.repeat(201));
  assert.equal(posts.length, n);
  const none = frameEnv('');  // no pass, no code: only the renew ask
  none.go('#/order/t_abcdef');
  assert.deepEqual(none.posts.map(p => p[0].orch), ['frame-go']);
});

test('frame.js also follows Back inside the frame (popstate)', () => {
  const {posts, loc, winListeners} = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1 + '&/order/t_abcdef');
  loc.hash = ''; winListeners.popstate();
  assert.deepEqual(posts.at(-1)[0], {orch:'frame-at', path:'/addon/factory/', hash:'', chan:C1});
});

// The dashboard side: pageFrame and the frame message listener from pages/settings.js, run with fakes.
function dashEnv(start) {
  const src = read('../src/orch_dashboard/web/pages/settings.js');
  const chunk = /let frameKeep = null;[\s\S]*?\n}\);\n/.exec(src)[0];
  const frameEntryLine = /const frameEntry = .*;/.exec(src)[0];
  const routeOf = hash => {
    const m = /^#addon\/([a-z][a-z0-9-]{1,31})(?:\/([A-Za-z0-9_./-]*))?(?:#([A-Za-z0-9_/-]*))?$/.exec(hash);
    return m ? {kind:'page', id:m[1], path:m[2] || '', ...(m[3] ? {inner:m[3]} : {}), hash} : {kind:'home', hash};
  };
  const loc = {hash:start};
  const env = {loc, followed:[], renders:0, listener:null, iframe:null, hashSets:[]};
  const location = {get hash() { return loc.hash; }, set hash(v) { env.hashSets.push(v); loc.hash = v; }};
  const framePasses = new Map([['factory', {pass:P1, file:F1, chan:C1}]]);
  const h = (tag, attrs) => ({tag, attrs, getAttribute:n => attrs[n], addEventListener() {}, classList:{add() {}, remove() {}}, dataset:{}});
  const fakeGlobal = {addEventListener:(n, f) => { if (n === 'message') env.listener = f; }, orchFrameChan:() => C1};
  const document = {querySelector:() => env.iframe, querySelectorAll:() => []};
  const body = frameEntryLine + '\n' + chunk + '\nreturn {pageFrame};';
  const api = new Function('globalThis', 'location', 'document', 'route', 'snapshot', 'addons', 'framePass', 'framePasses', 'frameFresh',
    'pageStopped', 'skeletonFor', 'h', 'fragment', 'shellAddons', 'addonLabel', 'SHIPPED_SANDBOX', 'framesLoaded', 'followAddress', 'render', body)(
    fakeGlobal, location, document, () => routeOf(loc.hash), false, () => [{name:'factory', shipped:true, page:true}],
    name => framePasses.get(name) || null, framePasses, new Map(), () => null, () => ({dataset:{}}), h,
    (...kids) => kids.filter(Boolean), new Set(), () => 'Factory', 'allow-scripts', new Set([]),
    hash => { env.followed.push(hash); loc.hash = hash; }, () => { env.renders++; });
  env.draw = () => { const out = api.pageFrame(routeOf(loc.hash)); env.iframe = out.find(n => n.tag === 'iframe'); env.iframe.contentWindow = env.win; return env.iframe; };
  env.win = {};
  env.send = (data, opts = {}) => env.listener({origin:opts.origin || 'null', source:opts.source || env.win, data});
  framePasses.set('factory', {pass:P1, file:F1, chan:C1});
  env.framePasses = framePasses;
  return env;
}

test('the dashboard address follows a move inside the frame and the frame keeps its address', () => {
  const env = dashEnv('#addon/factory');
  const first = env.draw().attrs.src;
  assert.match(first, /^\/addon\/factory\/#orch-frame=/);
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef/proposal', chan:C1});
  assert.deepEqual(env.followed, ['#addon/factory#/order/t_abcdef/proposal']);
  assert.deepEqual(env.hashSets, []);  // no hash change: no new history entry, no page change
  assert.equal(env.draw().attrs.src, first);  // drawn again (the 3 s refresh): the frame is not reloaded
  // Back inside the frame: the address follows back, the frame is still the same one
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'', chan:C1});
  assert.equal(env.loc.hash, '#addon/factory');
  assert.equal(env.draw().attrs.src, first);
});

test('a reload opens the frame at the place the address names', () => {
  const env = dashEnv('#addon/factory#/order/t_abcdef/proposal');
  assert.match(env.draw().attrs.src, /&orch-chan=[0-9a-f]{32}&\/order\/t_abcdef\/proposal$/);
});

test('another address (a link, the menu, a typed address) opens the frame anew', () => {
  const env = dashEnv('#addon/factory');
  env.draw();
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:C1});
  env.loc.hash = '#addon/factory#/autopilot';
  assert.match(env.draw().attrs.src, /&\/autopilot$/);
  // a new pass (renew) never keeps the old address either
  env.loc.hash = '#addon/factory';
  env.draw();
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:C1});
  env.framePasses.set('factory', {pass:'q'.repeat(43), file:F1, chan:C1});
  assert.match(env.draw().attrs.src, /#orch-frame=q{43}&.*&\/order\/t_abcdef$/);
});

test('back from another page, a new frame opens at the place the address names, not the kept one', () => {
  const env = dashEnv('#addon/factory');
  env.draw();
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:C1});
  env.iframe = null;  // Settings was shown: the frame is gone; Back brings the same address again
  assert.match(env.draw().attrs.src, /&\/order\/t_abcdef$/);
});

test('frame-at is refused without the code, from another window, for another page or a bad place', () => {
  const env = dashEnv('#addon/factory');
  env.draw();
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef'});  // no code (a page navigated into the frame)
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:'cd'.repeat(16)});  // wrong code
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:C1}, {source:{}});  // another window
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'/order/t_abcdef', chan:C1}, {origin:'http://evil.example'});
  env.send({orch:'frame-at', path:'/addon/factory/x', hash:'', chan:C1});  // another page of the add-on: only frame-go opens it
  env.send({orch:'frame-at', path:'/addon/focus/', hash:'', chan:C1});  // another add-on
  env.send({orch:'frame-at', path:'/addon/factory/api/x', hash:'', chan:C1});
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'a b', chan:C1});  // not a place
  env.send({orch:'frame-at', path:'/addon/factory/', hash:'x'.repeat(201), chan:C1});
  assert.deepEqual(env.followed, []);
  assert.equal(env.loc.hash, '#addon/factory');
});

// W-001, W-006 (owner, 28 Nov): touch sizes follow the window, never the frame. A framed add-on page beside the Focus
// panel is narrower than a phone in a wide window; the dashboard says the window is wide and the kit's 44 px rules stand down.
test('a framed page asks whether the window is wide and takes only its parent\'s word for it', () => {
  const env = frameEnv('#orch-frame=' + P1 + '&orch-file=' + F1 + '&orch-chan=' + C1);
  assert.deepEqual(env.asks, [[{orch:'frame-window'}, 'http://127.0.0.1:8420']], 'asked once at the start, no pass and no code in it');
  const marks = {};
  env.win.document.documentElement = {setAttribute:(k, v) => { marks[k] = v; }, removeAttribute:k => { delete marks[k]; }};
  const hear = env.winListeners.message;
  hear({source:{}, data:{type:'orch.window', wide:true}});
  assert.deepEqual(marks, {}, 'another window is not believed');
  hear({source:env.win.parent, data:{type:'orch.window', wide:true}});
  assert.deepEqual(marks, {'data-window':'wide'});
  hear({source:env.win.parent, data:{type:'orch.window', wide:false}});
  assert.deepEqual(marks, {}, 'a window at phone width: the touch sizes are back');
  // the dashboard answers only its own add-on frames, with a yes or no
  const app = read('../src/orch_dashboard/web/app.js');
  assert.match(app, /if \(e\.data\?\.orch !== 'frame-window' \|\| !e\.source\) return;\n  if \(embedFrames\(\)\.some\(f => f\.contentWindow === e\.source\)\) postWindowWide\(e\.source\);/);
  assert.match(app, /win\?\.postMessage\(\{type:'orch\.window', wide:windowWide\(\)\}, '\*'\)/);
  // the kit's touch rules stand down for that mark, with no added weight
  const kit = read('../../../workspace/src/orch_ui/static/components.css');
  assert.match(kit, /:where\(html:not\(\[data-window=wide\]\)\) \.btn,:where\(html:not\(\[data-window=wide\]\)\) \.btn\.sm,[^{]*\{min-height:44px\}/);
  assert.match(kit, /:where\(html:not\(\[data-window=wide\]\)\) \.input\{font-size:16px;min-height:44px\}/);
});
