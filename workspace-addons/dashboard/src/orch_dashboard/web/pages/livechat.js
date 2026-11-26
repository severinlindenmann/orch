'use strict';
// The chat view of a ticket's session in Focus (ORCH-687, draft D feature 5): the helper's messages and the ticket's
// events as one plain conversation, oldest first, with the waiting question answered right above the message box.
// The helper's own words come from its real conversation where the tool keeps one (ORCH-2204, GET /api/talk/<ticket>:
// the newest turns of the session in use); the ticket adds the steps, questions, events and your messages around them.
// Where no conversation can be read, everything comes from the ticket the page already polls, and the chat says it is
// a summary, with Open terminal for the real screen.
//   step events     a done step ("Step 2 done: <its words>") at the time of its newest evidence
//   helper messages the one-line summary of a done step, with its links (pull request, address); a question the
//                   helper asked; a Chat or group line an agent wrote (chat_message)
//   your messages   the answer to a question; a Chat line a person wrote; a message sent to the helper (orch keeps it:
//                   run status sent_input, so it stays after a reload, ORCH-695), with the files it carried
//   other events    the helper started, stopped or finished, and a person moved the ticket
// The open question is not a message: the pane shows it as its question card (live-layer.js liveAskFill).
// Each pane chooses Chat or Terminal (its last lines until the terminal comes); the choice is kept per browser.
const LIVE_CHAT_MAX = 60;       // rows kept, the newest
const LIVE_CHAT_TEXT = 600;     // characters of one message; a longer question reads in full on the ticket
const LIVE_VIEW_KEY = 'orch.live.view';

function liveChatTime(at) {
  const ms = Date.parse(at || '');
  return Number.isFinite(ms) ? ms : NaN;
}
function liveChatCut(text) {
  const s = String(text ?? '').replace(/\s+\n/g, '\n').trim();
  return s.length > LIVE_CHAT_TEXT ? s.slice(0, LIVE_CHAT_TEXT - 1).trimEnd() + '…' : s;
}
function liveChatWho(by) {
  const m = /^(?:human|agent):(.+)$/.exec(String(by || ''));
  return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1) : '';
}
// The other events worth a line in a conversation, in plain words; every other history line stays on the ticket.
const LIVE_CHAT_STATUS = {review:'Review', done:'Done', active:'Working', todo:'To do', ready:'To do', blocked:'Blocked'};
function liveChatEvent(e) {
  const text = String(e.text || '').trim(), by = String(e.by || '');
  if (/^(?:[A-Z][\w.-]*(?: [A-Z][\w.-]*){0,2}|The agent) started$/.test(text) || /^Automation started an agent run/i.test(text)) return 'The helper started';
  if (/finished the work and sent it to /i.test(text)) return 'The helper finished and sent it for review';
  if (/^The agent stopped before the work was finished/i.test(text)) return 'The helper stopped before the work was finished';
  if (/^Sent the helper on\b/i.test(text)) return 'The helper was sent on: it had stopped with open steps';
  const st = /^Status \S+ -> (\S+)$/.exec(text);
  if (st && /^human:/.test(by) && LIVE_CHAT_STATUS[st[1]]) return 'Moved to ' + LIVE_CHAT_STATUS[st[1]] + ' by ' + (liveChatWho(by) || 'a person');
  return '';
}
// The links of a step's evidence that open by themselves: a pull request or an address (files come with the results).
function liveChatLinks(evidence) {
  return evidence.filter(v => v && (v.type === 'pr' || v.type === 'url') && /^https?:\/\//.test(String(v.ref || '')))
    .map(v => {
      const ref = String(v.ref), pr = /\/pull\/(\d+)/.exec(ref);
      return {href:ref, label:clean0(v.title) || (v.type === 'pr' ? (pr ? 'Pull request ' + pr[1] : 'Pull request') : ref.replace(/^https?:\/\//, '').slice(0, 60))};
    });
}
function clean0(s) { return typeof s === 'string' ? s.trim() : ''; }
// A message with files (ticketTalkText on the ticket page, the message box of a pane) ends with one line naming them:
// the words and the names come apart again, so the chat shows the files as small previews, not as that line.
const LIVE_CHAT_FILES = /(?:^|\n\n)I added (?:a file|\d+ files) to (?:this ticket|\.orch\/tickets\/t_[a-z0-9]+\/artifacts)(?:: ([^\n]+?))?\.(?: The voice note came without written words\.)? Read (?:it|them) (?:first|and carry on)\.$/;
function liveChatSplit(text) {
  const s = String(text ?? ''), m = LIVE_CHAT_FILES.exec(s);
  if (!m || !m[1]) return {text:s, files:[]};  // no names (a long message): the line stays as words
  return {text:s.slice(0, m.index).trim(), files:m[1].split(', ').map(x => x.trim()).filter(Boolean).slice(0, 10)};
}
// What the person sent: orch's own list (read or not) and, until orch lists it, what this page just sent (same words).
function liveChatMine(run, local) {
  const kept = Array.isArray(run?.sent_input) ? run.sent_input.filter(m => m && clean0(m.text) && Number.isFinite(liveChatTime(m.at))) : [];
  const said = new Set(kept.map(m => clean0(m.text)));
  return [...kept, ...(Array.isArray(local) ? local : []).filter(m => m && !said.has(clean0(m.text)))];
}
// Commands in a helper's words (ORCH-2203, draft D a): a ``` block of one line, a line that is only `code`, and a line
// starting with "!" (the helper's own way to say "run this in a shell"). Each gets "Run in terminal" in the chat. A
// block of several lines stays plain text: typing it would press Enter in the middle.
const LIVE_CMD_MAX = 1000;
const liveCmdOk = c => c.length > 0 && c.length <= LIVE_CMD_MAX && !/[\x00-\x1f\x7f]/.test(c);
// [{t:'text', text} | {t:'cmd', text}] in order; a message with no command is one text part.
function liveChatParts(text) {
  const out = [], buf = [];
  const flush = () => { const t = buf.join('\n').trim(); buf.length = 0; if (t) out.push({t:'text', text:t}); };
  const lines = String(text ?? '').split('\n');
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i], line = ln.trim();
    const fence = /^```/.test(line);
    if (fence) {
      const end = lines.findIndex((x, j) => j > i && /^```\s*$/.test(x.trim()));
      if (end < 0) { buf.push(ln); continue; }
      const inner = lines.slice(i + 1, end).map(x => x.trim()).filter(Boolean);
      flush();
      if (inner.length === 1 && liveCmdOk(inner[0])) out.push({t:'cmd', text:inner[0]});
      else if (inner.length) out.push({t:'text', text:inner.join('\n')});
      i = end;
      continue;
    }
    const code = /^`([^`]+)`$/.exec(line), bang = /^!\S/.test(line);
    const cmd = code ? code[1].trim() : bang ? line : '';
    if (cmd && liveCmdOk(cmd)) { flush(); out.push({t:'cmd', text:cmd}); } else buf.push(ln);
  }
  flush();
  return out;
}
// What is typed: into a plain terminal a "!command" is just the command; the helper takes the "!" itself. Never Enter.
function liveCmdTyped(cmd, plain) { return plain ? String(cmd).replace(/^!\s*/, '') : String(cmd); }
const LIVE_TALK_TEXT = 2000;    // characters of one turn of the real conversation (the server cuts it too)
// rows: {w: 'e' | 'h' | 'y', text, at, who?, links?}; me: the person looking ("human:<name>"), whose lines say You.
// talk: the real conversation ({available, turns:[{w, text, at}]}): its turns are the helper's words, so a step's
// one-line summary is left out (its links and results stay).
function liveChatModel(t, me = '', sent = [], talk = null) {
  if (!t || typeof t !== 'object') return [];
  const rows = [], mine = by => !!by && by === me;
  const real = liveTalkReal(talk);
  const steps = Array.isArray(t.checklist) ? t.checklist.filter(c => c && typeof c === 'object') : [];
  steps.forEach((c, i) => {
    if (c.done !== true) return;
    const ev = Array.isArray(c.evidence) ? c.evidence.filter(v => v && typeof v === 'object') : [];
    const at = ev.map(v => v.at).filter(a => Number.isFinite(liveChatTime(a))).sort().pop() || c.done_at || '';
    if (!Number.isFinite(liveChatTime(at))) return;
    rows.push({w:'e', text:'Step ' + (i + 1) + ' done: ' + liveChatCut(c.text), at});
    const said = ev.find(v => clean0(v.summary));
    const links = liveChatLinks(ev);
    // a file the step proved or a check run is a result too: it shows as a widget inside the message (ORCH-687, ORCH-697)
    const made = ev.some(v => (v.type === 'file' && /^\.orch\/tickets\/[^/]+\/(evidence|artifacts)\//.test(String(v.ref || ''))) || (v.type === 'command' && (typeof v.exit === 'number' || v.output_tail)));
    const text = said && !real ? liveChatCut(said.summary) : '';
    if (text || links.length || made) rows.push({w:'h', text, at, links, step:typeof c.id === 'string' ? c.id : ''});
  });
  for (const q of Array.isArray(t.questions) ? t.questions : []) {
    if (!q || typeof q !== 'object' || q.answer == null) continue;  // the open one is the question card
    if (Number.isFinite(liveChatTime(q.asked_at))) rows.push({w:'h', text:liveChatCut(q.text), at:q.asked_at, question:true});
    const at = q.answered_at || q.at;
    if (!Number.isFinite(liveChatTime(at))) continue;
    const who = String(q.answered_by || '');
    rows.push(/^human:/.test(who)
      ? {w:'y', text:liveChatCut(q.answer), at, who:mine(who) ? '' : liveChatWho(who)}
      : {w:'e', text:'Answered for you: ' + liveChatCut(q.answer), at});
  }
  for (const e of Array.isArray(t.history) ? t.history : []) {
    if (!e || typeof e !== 'object' || !Number.isFinite(liveChatTime(e.at))) continue;
    const by = String(e.by || '');
    if (e.chat_message === true && clean0(e.text)) {
      rows.push(/^human:/.test(by) ? {w:'y', text:liveChatCut(e.text), at:e.at, who:mine(by) ? '' : liveChatWho(by)} : {w:'h', text:liveChatCut(e.text), at:e.at});
      continue;
    }
    const line = liveChatEvent(e);
    if (line) rows.push({w:'e', text:line, at:e.at});
  }
  // a Chat line a person wrote is also queued for the helper: it shows once, from the history
  const said = new Set((Array.isArray(t.history) ? t.history : []).filter(e => e && e.chat_message === true && /^human:/.test(String(e.by || ''))).map(e => clean0(e.text)));
  for (const m of Array.isArray(sent) ? sent : []) {
    if (!m || !clean0(m.text) || !Number.isFinite(liveChatTime(m.at)) || said.has(clean0(m.text))) continue;
    const part = liveChatSplit(m.text), who = m.by && !mine(m.by) ? liveChatWho(m.by) : '';
    rows.push({w:'y', text:liveChatCut(part.text), at:m.at, sent:true, ...(who ? {who} : {}), ...(part.files.length ? {files:part.files} : {})});
  }
  if (real) for (const x of talk.turns) {
    if (!x || (x.w !== 'h' && x.w !== 'y') || !clean0(x.text) || !Number.isFinite(liveChatTime(x.at))) continue;
    const s = String(x.text).trim();
    rows.push({w:x.w, text:s.length > LIVE_TALK_TEXT ? s.slice(0, LIVE_TALK_TEXT - 1).trimEnd() + '…' : s, at:x.at, talk:true});
  }
  // oldest first; at the same moment the step goes before what the helper said about it (the order pushed)
  return rows.map((r, n) => [r, n]).sort((a, b) => (liveChatTime(a[0].at) - liveChatTime(b[0].at)) || (a[1] - b[1]))
    .map(x => x[0]).slice(-LIVE_CHAT_MAX);
}
// The real conversation counts when orch could read it and it has turns; else the chat is the ticket's summary.
function liveTalkReal(talk) {
  return !!(talk && talk.available === true && Array.isArray(talk.turns) && talk.turns.length);
}
// Chat or Terminal per session, kept per browser: {<session id>: 'term'}; chat is the default and is not stored.
function liveViewRead(store) {
  try {
    const v = JSON.parse(store?.getItem(LIVE_VIEW_KEY) || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).filter(([k, x]) => k && x === 'term').slice(-50)) : {};
  } catch { return {}; }
}
function liveViewWrite(store, views) {
  try { store?.setItem(LIVE_VIEW_KEY, JSON.stringify(views)); } catch { /* private window: the choice lasts this page */ }
}
// --- the page ---
let liveViews = null;
const liveChatSent = new Map();  // messages sent from this page, per session, until the page reloads
const liveTalk = new Map();      // ticket id -> {at, data, busy}: the real conversation, read again every few seconds
const LIVE_TALK_EVERY = 4000;
function liveTalkLoad(id, box) {
  const hit = liveTalk.get(id);
  if (hit && (hit.busy || Date.now() - hit.at < LIVE_TALK_EVERY)) return;
  // only a ticket id has a conversation to read (the server answers 404 to anything else): the chat is the summary
  if (!/^t_[a-z0-9]{6,16}$/.test(String(id))) { liveTalk.set(id, {at:Date.now(), data:{available:false, turns:[]}, busy:false}); return; }
  liveTalk.set(id, {at:Date.now(), data:hit?.data || null, busy:true});
  fetch('/api/talk/' + encodeURIComponent(id)).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    // a failed read keeps what the chat shows; the first one shows the summary
    liveTalk.set(id, {at:Date.now(), data:data && typeof data === 'object' ? data : hit?.data || {available:false}, busy:false});
    if (box.isConnected && !box.hidden) liveChatFill(box);
  });
}
function liveViewsNow() {
  if (!liveViews) liveViews = liveViewRead(typeof liveLayerStore === 'function' ? liveLayerStore() : null);
  return liveViews;
}
function liveViewOf(id) { return liveViewsNow()[id] === 'term' ? 'term' : 'chat'; }
function liveViewSet(id, view) {
  const v = {...liveViewsNow()};
  if (view === 'term') v[id] = 'term'; else delete v[id];
  liveViews = v;
  liveViewWrite(typeof liveLayerStore === 'function' ? liveLayerStore() : null, v);
}
// "Run in terminal" (ORCH-2203): types the command into the helper of this pane, into an open plain terminal (a new one
// when none is open) or into a new plain terminal; the person presses Enter. Every refusal says what to do.
const liveTermsOpen = () => (Array.isArray(state?.sessions) ? state.sessions : []).filter(x => x && x.kind === 'terminal' && x.open === true && typeof x.id === 'string');
async function liveRunIn(to, tid, cmd) {
  const say = (t, kind) => window.orch?.toast?.(t, kind);
  if (!window.LiveTerm?.send) return say('The terminal is not ready. Reload the page and try again.', 'error');
  let id = tid, plain = false;
  if (to === 'helper') {
    const live = typeof liveLayerSession === 'function' ? liveLayerSession(tid) : null;
    if (live && live.running === false) return say('This helper is not running. Start it, then run the command.', 'error');
  } else {
    plain = true;
    const was = liveTermsOpen().map(x => x.id);
    if (to === 'new' || !was.length) {
      const r = await act('session.new', {kind:'terminal'}, {quiet:true});
      if (!r.ok) return say(r.text || 'The terminal did not start. Try again.', 'error');
      await window.LiveSessions?.refresh?.();
      id = liveTermsOpen().map(x => x.id).find(x => !was.includes(x)) || '';
    } else id = was[0];
    if (!id) return say('The new terminal is not listed yet. Open it from New and try again.', 'error');
  }
  const r = await window.LiveTerm.send(id, liveCmdTyped(cmd, plain), {plain});
  if (r.ok) say('Typed into ' + (plain ? 'the plain terminal' : 'the helper') + '. Press Enter to run it.', 'ok');
  else if (r.text && !r.status) say(r.text, 'error');
}
function liveChatNote(id, text) {  // shows at once; orch's own list takes over on the next poll
  const list = liveChatSent.get(id) || [];
  list.push({text, at:new Date().toISOString()});
  liveChatSent.set(id, list.slice(-20));
}
// Chat | Terminal in a ticket pane's header (draft D's segmented switch)
function liveViewSwitch(sess) {
  if (!sess || sess.kind) return null;
  const view = liveViewOf(sess.id), b = (v, word) => h('button', {type:'button', className:'btn sm', 'data-live-view':v, 'data-session':sess.id,
    'data-key':'live-view-' + v, 'aria-pressed':String(view === v)}, word);
  return h('span', {className:'segmented live-view', role:'group', 'aria-label':'View'}, b('chat', 'Chat'), b('term', 'Terminal'));
}
// The log the fill writes into; empty until the first fill
function liveChatBox(sess, label) {
  if (!sess || sess.kind) return null;
  return h('div', {className:'live-chat', 'data-live-chat':sess.id, role:'log', 'aria-label':'Messages and ticket events of ' + label, tabindex:'0',
    hidden:liveViewOf(sess.id) !== 'chat'});
}
const LIVE_CHAT_PIC = /\.(png|jpe?g|gif|webp)$/i;
// The files a sent message carried, as small previews: a picture's thumbnail or a file chip; a click opens the big preview.
function liveChatFiles(tid, names) {
  if (!names?.length || !tid) return null;
  return h('div', {className:'live-chat-files', role:'group', 'aria-label':names.length === 1 ? '1 file' : names.length + ' files'}, names.map(n => {
    const src = typeof fileUrl === 'function' ? fileUrl(tid, 'artifacts', n) : '';
    return h('button', {type:'button', className:'live-chat-file', 'data-live-file':n, 'data-ticket':tid, title:n, 'aria-label':'Open ' + n},
      LIVE_CHAT_PIC.test(n) && src ? h('img', {src, alt:'', loading:'lazy'}) : (k => { if (typeof window === 'object' && window.icon) k.innerHTML = window.icon('file', 16); return k; })(h('span', {className:'live-chat-kind', 'aria-hidden':'true'})),
      h('span', {className:'live-chat-fname'}, n));
  }));
}
// A suggested command with its "Run in terminal" menu: it types the command, the person presses Enter.
function liveCmdBlock(cmd, tid) {
  const item = (to, word) => h('button', {type:'button', className:'btn ghost sm', role:'menuitem', 'data-live-run':to, 'data-ticket':tid, 'data-cmd':cmd, 'data-key':'live-run-' + to}, word);
  return h('div', {className:'live-cmd'}, h('code', {}, cmd),
    h('details', {className:'menu live-run'}, h('summary', {className:'btn primary sm', 'data-key':'live-run'}, 'Run in terminal ▾'),
      h('div', {className:'menu-pop', role:'menu', 'aria-label':'Where to type it'}, item('helper', 'This helper'), item('plain', 'Plain terminal'), item('new', 'New plain terminal'))));
}
function liveChatRow(r, tid = '') {
  const stamp = typeof time === 'function' ? time(r.at) : '';
  if (r.w === 'e') return h('p', {className:'live-ev meta'}, h('span', {'aria-hidden':'true'}, '✓'), ' ' + r.text + (stamp ? ' · ' + stamp : ''));
  // the step's results as small widgets (pages/results-feed.js); plain links only where no widget can be drawn
  const widgets = !!(r.step && tid && typeof resultsHost === 'function' && typeof window === 'object' && window.UI?.result);
  const links = widgets ? [] : (r.links || []).map(l => h('a', {className:'live-link', href:l.href, target:'_blank', rel:'noopener'}, l.label));
  return h('div', {className:'live-chat-msg', 'data-w':r.w},
    h('span', {className:'meta'}, (r.w === 'y' ? r.who || 'You' : 'Helper') + (stamp ? ' · ' + stamp : '')),
    ...(r.w === 'h' && r.text ? liveChatParts(r.text) : r.text ? [{t:'text', text:r.text}] : []).map(p => p.t === 'cmd' ? liveCmdBlock(p.text, tid) : h('p', {}, p.text)),
    liveChatFiles(tid, r.files),
    links.length ? h('div', {className:'live-links'}, links) : null,
    widgets ? resultsHost(tid, {key:'chat-results-' + tid + '-' + r.step, step:r.step, cls:'live-results', label:'Results of this step'}) : null);
}
// The small label above a chat that is the ticket's summary, not the helper's conversation: Open terminal shows the
// real screen (the Chat | Terminal switch's own click, below).
function liveChatSrc(id) {
  return h('p', {className:'meta live-chat-src', 'data-key':'live-chat-src'}, h('span', {}, 'Summary from the ticket'),
    h('button', {type:'button', className:'btn ghost xs', 'data-live-view':'term', 'data-session':id, 'data-key':'live-chat-open-term'}, 'Open terminal'));
}
// Written only when the rows change, so the scroll and a selection stay; follows the end while it is at the end.
function liveChatFill(box) {
  const id = box.dataset.liveChat, t = typeof ticketOf === 'function' ? ticketOf(id) : null;
  const st = typeof state === 'object' && state ? state : {};
  if (typeof fetch === 'function') liveTalkLoad(id, box);
  const talk = liveTalk.get(id)?.data || null;
  const rows = liveChatModel(t, st.me || '', liveChatMine(st.runs?.[id], liveChatSent.get(id)), talk);
  // the label says the chat is a summary once orch knows it cannot read the real conversation (not while it asks)
  const src = talk && !liveTalkReal(talk) ? 'summary' : '';
  const sigs = [src, ...rows.map(r => [r.w, r.at, r.text, (r.links || []).map(l => l.href).join(' '), (r.files || []).join('/'), r.step || ''].join('\u0001'))];
  const was = box.liveChatSigs, sig = sigs.join('\u0002');
  if (was && was.join('\u0002') === sig && box.dataset.sig) return;
  const end = !box.dataset.sig || box.scrollHeight - box.scrollTop - box.clientHeight < 8;
  box.dataset.sig = '1';
  box.liveChatSigs = sigs;
  // new rows at the end only: they are added, so a focused link or a selection in the older rows stays
  if (was && was.length > 1 && sigs.length > was.length && was.every((x, i) => x === sigs[i])) for (const r of rows.slice(was.length - 1)) box.append(liveChatRow(r, id));
  else {
    box.textContent = '';
    if (src) box.append(liveChatSrc(id));
    if (!rows.length) box.append(h('p', {className:'meta live-chat-empty'}, 'No messages yet. Steps the helper finishes and its questions show here.'));
    else for (const r of rows) box.append(liveChatRow(r, id));
  }
  if (typeof resultsFillAll === 'function') resultsFillAll(box);
  if (end) box.scrollTop = box.scrollHeight;
  liveChatFollow(box);
}
// The newest message stays whole (ORCH-1361, draft D). While the chat is at its end it stays there when its size
// changes (the message box grows with files, the question card comes or goes, the layer is resized). When the pane is
// too short for the chat and the message box together, its body scrolls too: it follows its own end, so the message
// box that stays at the bottom never covers the last message. Scrolling up by hand stops the following.
const liveChatAtEnd = el => el.scrollHeight - el.scrollTop - el.clientHeight < 8;
function liveChatEnd(box) {
  const f = box.liveFollow, pb = box.closest('.live-pb');
  if (!f || box.hidden) return;
  if (f.chat) box.scrollTop = box.scrollHeight;
  if (!f.pane || !pb || pb.scrollHeight <= pb.clientHeight) return;
  // a waiting question is the newest thing in the pane: its orange card (or its line, when the card has no answers to
  // show) starts the pane, whole, and the chat sits under it
  const ask = pb.querySelector(':scope > :is([data-live-ask], [data-live-now][data-live-q]):not([hidden])');
  pb.scrollTop = ask ? pb.scrollTop + ask.getBoundingClientRect().top - pb.getBoundingClientRect().top - parseFloat(getComputedStyle(pb).paddingTop || 0) : pb.scrollHeight;
}
function liveChatFollow(box) {
  const pb = box.closest('.live-pb');
  if (!box.liveFollow) {
    box.liveFollow = {chat:liveChatAtEnd(box), pane:true};
    box.addEventListener('scroll', () => { box.liveFollow.chat = liveChatAtEnd(box); }, {passive:true});
    if (pb) {
      // only the person's own scrolling (wheel, touch, keys) stops it: a focus or a click that scrolls the body does not
      let byHand = 0;
      for (const type of ['wheel', 'touchmove', 'keydown']) pb.addEventListener(type, () => { byHand = Date.now(); }, {passive:true});
      pb.addEventListener('pointerdown', e => { if (e.target === pb) byHand = Date.now(); }, {passive:true});  // its scrollbar
      pb.addEventListener('scroll', () => { if (box.isConnected && Date.now() - byHand < 1000) box.liveFollow.pane = liveChatAtEnd(pb); }, {passive:true});
    }
    if (typeof ResizeObserver === 'function') {
      const ro = new ResizeObserver(() => { if (box.isConnected) liveChatEnd(box); else ro.disconnect(); });
      for (const el of [box, ...(pb ? [pb, ...pb.children] : [])]) ro.observe(el);
    }
  }
  liveChatEnd(box);
}
// Shows the chosen view in a pane's body: the chat, or the last lines (the terminal's place until it comes).
function liveViewApply(body) {
  const box = body.querySelector('[data-live-chat]');
  if (!box) return;
  const term = liveViewOf(box.dataset.liveChat) === 'term', pre = body.querySelector('[data-live-lines]');
  box.hidden = term;
  body.dataset.liveView = term ? 'term' : 'chat';
  if (pre && !term) pre.hidden = true;
  if (!term) liveChatFill(box);
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  document.addEventListener('click', e => {
    const f = e.target.closest?.('#live-dock [data-live-file]');
    if (f && typeof previewFile === 'function') { previewFile(f.dataset.ticket, 'artifacts', f.dataset.liveFile); return; }
    const run = e.target.closest?.('#live-dock [data-live-run]');
    if (run) { run.closest('details')?.removeAttribute('open'); if (typeof liveRunIn === 'function') liveRunIn(run.dataset.liveRun, run.dataset.ticket, run.dataset.cmd); return; }
    const b = e.target.closest?.('#live-dock button[data-live-view]');  // the pane body carries data-live-view too
    if (!b) return;
    const id = b.dataset.session, view = b.dataset.liveView === 'term' ? 'term' : 'chat';
    liveViewSet(id, view);
    const pane = b.closest('.live-pane');
    pane?.querySelectorAll('.live-view [data-live-view]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.liveView === view)));  // only the Chat / Terminal switch is pressed (ORCH-1360)
    if (typeof liveLayerFill === 'function') liveLayerFill();  // shows the view in place: no repaint, the keyboard stays
  });
}
