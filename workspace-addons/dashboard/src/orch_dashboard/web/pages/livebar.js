'use strict';
// The live bar (draft D, ORCH-337): one calm row under every page. ORCH-2198 (owner pick J b, "calmer, less
// distraction from the task I have open"): the row holds only the page's name, one "Helpers" menu and New. The menu
// lists every live session in three groups with their counts: Needs you, Working and Quiet (in line and idle). Each
// row opens its pane. The menu opens inside the window: above the bar at the bottom, below it when the bar sits at the
// top (full screen).
// The dashboard names no add-on: the live page is found by its live_session capability (pages/live.js).
//
// Data: the live sessions API (pages/livesessions.js, window.LiveSessions; ORCH-359). Pins and own names are kept by
// orch for the workspace (window.LiveSessions.pins, ORCH-361); a pinned session comes first in its group.
//
// Mount: the bar is one element (#live-bar). It goes into the dashboard's keep place ([data-keep], the mount point that
// outlives page changes) when there is one, else at the end of .shell-body; LiveBar.mount(host) moves it anywhere else
// and it stays the same element (its open menu included). With the layer (window.LiveLayer.open) a row opens its
// session there; the layer's orch:live-layer event marks the open ones; LiveBar.end(fn) fills the right end.
const LIVEBAR_SYM = {wait:'◆', run:'●', queue:'◷', idle:'◐'};
// The groups of the Helpers menu, in order: [id, heading]. Quiet holds the sessions in line and the idle ones.
const LIVEBAR_GROUPS = [['wait', 'Needs you'], ['run', 'Working'], ['quiet', 'Quiet']];
const LIVEBAR_SEARCH_FROM = 9;  // a menu this long gets a search box (draft D)

// The New menu (draft D): sessions without a ticket, in its order; the core starts them (`orch session new <kind>`).
const LIVEBAR_NEW = [
  {kind:'empty', title:'Empty helper', what:'A helper with no ticket and no task yet'},
  {kind:'chat', title:'Chat helper', what:'Ask anything, no ticket'},
  {kind:'terminal', title:'Plain terminal', what:'An empty terminal in this workspace'},
  {kind:'manager', title:'Manager', what:'Looks after all helpers'},
];

// Runs on (draft D features 4 and 12; ORCH-710, ORCH-1660, ORCH-1617): one row in the New menu and on the wall, the tool
// and the model a new helper without a ticket starts on, the usual ones preselected so it stays one click, like the Start
// choice of a ticket. The model comes from orch (state.sessions, the core's next pick); before the first Empty helper
// exists it is the one orch picks for it (core modelpick.EMPTY_HELPER; tests/test_sessions_data.py keeps the two the same).
const LIVEBAR_MODELS = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku'], ['fable', 'Fable']];
const LIVEBAR_EMPTY_MODEL = 'sonnet';
const liveBarModelOk = m => LIVEBAR_MODELS.some(x => x[0] === m);
// {tools, usual, tool, takesModel, model, usualModel} of the Runs on row, or null when no tool is set up here.
// pick: {tool, model} the person changed ('' = the usual one).
function liveBarRunsOn(sessions, agents, pick) {
  const tools = (Array.isArray(agents) ? agents : []).filter(a => a && typeof a.name === 'string' && a.found !== false)
    .map(a => ({name:a.name, label:String(a.label || a.name), models:a.models === true, chosen:a.chosen === true}));
  if (!tools.length) return null;
  const usual = (tools.find(t => t.chosen) || tools[0]).name;
  const tool = tools.find(t => t.name === pick?.tool) || tools.find(t => t.name === usual);
  const s = (Array.isArray(sessions) ? sessions : []).find(x => x && x.kind === 'empty');
  const usualModel = s && liveBarModelOk(s.model) ? s.model : LIVEBAR_EMPTY_MODEL;
  return {tools, usual, tool:tool.name, takesModel:tool.models, model:liveBarModelOk(pick?.model) ? pick.model : usualModel, usualModel};
}
// What New sends for a session without a ticket: the tool only when it is not the usual one, the model only when the
// person picked one other than the one this helper starts on anyway. A plain terminal runs no helper: neither.
function liveBarNewArgs(kind, pick, runsOn, sessions) {
  const out = {kind};
  if (kind === 'terminal' || !runsOn) return out;
  if (pick?.tool && pick.tool !== runsOn.usual && runsOn.tools.some(t => t.name === pick.tool)) out.agent = pick.tool;
  if (runsOn.takesModel && liveBarModelOk(pick?.model)) {
    const s = (Array.isArray(sessions) ? sessions : []).find(x => x && x.kind === kind);
    const own = s && liveBarModelOk(s.model) ? s.model : kind === 'empty' ? LIVEBAR_EMPTY_MODEL : '';
    if (pick.model !== own) out.model = pick.model;
  }
  return out;
}

// One row per live session: {id, key, title, s: wait|run|queue|idle, word, pin}, from the live sessions API
// (pages/livesessions.js, ORCH-359): the same list the panes and the wall read.
const liveBarModel = typeof liveBarRows === 'function' ? liveBarRows : require('./livesessions.js').liveBarRows;
// One ticket's session from the dashboard's own state (helpers.js), for the ticket's session button: it shows on its
// own, so it does not wait for the live sessions API. Same states as the bar: wait, run, queue, idle.
function liveTicketSession(t, run, helperState) {
  if (!t || !t.id || t.status === 'dropped' || !run) return null;
  const hs = helperState(run, t);
  if (hs) return {s:hs.state === 'you' ? 'wait' : hs.state === 'idle' ? 'idle' : hs.state === 'waiting' ? 'queue' : 'run'};
  return run.hold ? {s:'queue'} : null;
}
// The word on a ticket's session button (draft D feature 3, "the button on every ticket"): Answer when it needs you, Watch while its helper works, Open
// when the helper sits idle, In line while it waits for a free place, Start when no helper runs. A finished ticket with
// no helper gets no button (''). The same session states as the bar, so the button and the bar never disagree.
function liveFocusVerb(t, run, helperState) {
  if (!t || !t.id) return '';
  const o = liveTicketSession(t, run, helperState);
  const asks = Array.isArray(t.questions) && t.questions.some(q => q && q.answer == null);
  if (o?.s === 'wait' || (asks && !['done', 'dropped', 'superseded'].includes(t.status) && o?.s !== 'run')) return 'Answer';
  if (o) return {run:'Watch', idle:'Open', queue:'In line'}[o.s];
  return ['done', 'dropped', 'superseded'].includes(t.status) ? '' : 'Start';
}
// The group of the Helpers menu a session is in: Needs you, Working, or Quiet (in line or idle).
function liveBarGroup(o) {
  return o.s === 'wait' ? 'wait' : o.s === 'run' ? 'run' : 'quiet';
}
// The Helpers menu's groups that have something: [{g, head, rows, n}], in the order Needs you, Working, Quiet. The
// rows keep the order of the sessions API (pinned first within a state). The Needs you count is the workspace's one
// needs-you number (ORCH-1643: questions, results to check, helpers that wait; the Review badge shows it), so the group
// shows even when nothing that waits is a live session here.
function liveBarGroups(all, needTotal) {
  const list = Array.isArray(all) ? all : [];
  return LIVEBAR_GROUPS.map(([g, head]) => {
    const rows = list.filter(o => liveBarGroup(o) === g);
    return {g, head, rows, n:g === 'wait' ? liveBarNeedCount(needTotal, rows.length) : rows.length};
  }).filter(x => x.n > 0);
}
// A helper without a ticket that was made and is not on now (ended, or closed after an hour idle): New starts it
// again, and its History opens its pane (ORCH-817). A plain terminal keeps nothing, so it has none.
function liveBarNewEnded(sessions, kind) {
  return kind === 'terminal' ? null : (Array.isArray(sessions) ? sessions : []).find(x => x && x.kind === kind && x.open !== true && typeof x.id === 'string') || null;
}
// The open session without a ticket of a kind (state.sessions), or null: New goes to it instead of a second one.
function liveBarNewOpen(sessions, kind) {
  return (Array.isArray(sessions) ? sessions : []).find(x => x && x.kind === kind && x.open === true) || null;
}
// The one a New start made (#1531): in the state's sessions, else in the live sessions list (which lists open ones only,
// and may hold it before the state does).
function liveBarNewMade(sessions, live, kind) {
  return liveBarNewOpen(sessions, kind) || (Array.isArray(live) ? live : []).find(x => x && x.kind === kind) || null;
}
// ORCH-1643: the Needs you number is the workspace's one needs-you number (needsYouTotal: open questions, results to
// check, work that stopped and helpers that wait on their screen; the Review badge shows it). The sessions that wait
// are part of it, so it is never smaller than they are.
function liveBarNeedCount(total, sessions) {
  return Math.max(Number(total) || 0, Number(sessions) || 0);
}
// Where the Helpers menu (and a Stop and End menu) opens: on the side of the bar with more room, never past the window.
// above/below: the px between the bar and the window's top and bottom edge. {side:'above'|'below', max: px tall}.
function liveBarMenuAt(above, below) {
  const side = below > above ? 'below' : 'above', room = Math.max(above, below) - 16;
  return {side, max:Math.max(120, Math.min(480, Math.round(room)))};
}
// The accessible name and tooltip of the Helpers button: it says when something needs the person (the button shows
// only a ◆ then, no number: the number is on the Review badge, ORCH-1616).
function liveBarHelpersName(need) {
  return need > 0 ? 'Helpers: something needs you' : 'Helpers';
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveBarNeedCount, liveBarGroup, liveBarGroups, liveBarHelpersName, liveBarMenuAt, liveBarRunsOn, liveBarNewArgs, LIVEBAR_MODELS, LIVEBAR_EMPTY_MODEL, liveBarModel, liveFocusVerb, liveBarNewOpen, liveBarNewMade, LIVEBAR_GROUPS, LIVEBAR_NEW, liveBarNewEnded};
} else {
  (() => {
    const bar = {el:null, host:null, docked:false, end:null, panes:[], shown:null, list:'', q:'', sig:'', fold:0, menu:false, pick:{tool:'', model:''}, busy:'', perm:''};
    // ORCH-818: the Permissions row of the New menu (pages/live-perm.js): the tool's modes for the next start
    const permRow = kind => typeof livePermRow === 'function' ? livePermRow(state?.session_modes, kind, bar.perm) : null;
    const liveAddon = () => array(state?.addons).find(a => a.page?.live_session === true) || null;
    const sessions = () => window.LiveSessions?.list || [];
    const groups = () => window.LiveSessions?.groups || [];
    const pins = () => window.LiveSessions?.pins || [];  // kept by orch for the workspace (ORCH-361)
    const phone = () => window.matchMedia('(max-width: 720px)').matches;
    const link = (a, o) => '#addon/' + encodeURIComponent(a.name) + '/t/' + encodeURIComponent(o.id);
    const label = o => o.name || o.key || o.title;  // a chip shows the session's own name when it has one (draft D)
    const needTotal = () => { try { return typeof needsYouTotal === 'function' ? needsYouTotal() : 0; } catch (e) { return 0; } };
    const sym = (s, text) => h('span', {className:'lbar-sym', 'data-s':s, 'aria-hidden':'true'}, text);

    // ORCH-2198: one Helpers button instead of chips and counts. A ◆ (no number, ORCH-1616) says something needs you.
    function helpersButton(need) {
      const name = liveBarHelpersName(need);
      return h('button', {type:'button', className:'lbar-cnt lbar-helpers', 'data-lbar-list':'helpers', 'data-key':'lbar-helpers',
        'aria-expanded':String(bar.list === 'helpers'), 'aria-haspopup':'true', 'aria-label':name, title:name},
        need > 0 ? sym('wait', LIVEBAR_SYM.wait) : null, h('span', {}, 'Helpers'), iconEl('chevron-down'));
    }
    // One row of the menu: symbol, key, name (a Quiet row also says in line or idle), Open; More has Stop and End.
    function row(a, o, g) {
      const open = (o.members || [o.id]).some(id => (bar.shown || bar.panes).includes(id));
      const name = label(o) === o.key ? o.title : label(o);
      return h('div', {className:'lbar-rw'}, h('a', {className:'lbar-row', href:link(a, o), 'data-s':o.s, 'data-key':'lbar-row-' + o.id, 'data-lbar-open':o.id,
        'aria-current':open ? 'true' : null, title:o.title + ' · ' + (o.group ? o.line : o.word)},
        sym(o.s, LIVEBAR_SYM[o.s]), h('span', {className:'lbar-key'}, o.key),
        // a group (ORCH-345) is one row with its helper count, the same number as its tile
        h('span', {className:'lbar-rn'}, name, o.group ? h('span', {className:'lbar-n', 'aria-label':o.line, title:o.line}, String(o.n)) : null,
          g === 'quiet' && o.word && !o.group ? h('span', {className:'meta'}, ' · ' + o.word) : null),
        h('span', {className:'lbar-go', 'aria-hidden':'true'}, 'Open')),
        o.group || typeof window.liveEndMore !== 'function' ? null : window.liveEndMore(o.id, 'bar', label(o)));
    }
    function rows(a, all) {
      const q = bar.q.trim().toLowerCase();
      const hit = o => !q || (o.key + ' ' + o.title + ' ' + o.name).toLowerCase().includes(q);
      const out = [];
      for (const x of liveBarGroups(all, needTotal())) {
        const list = x.rows.filter(hit), rest = x.g === 'wait' && !q ? waitRest(x) : null;
        if (!list.length && !rest) continue;
        out.push(h('div', {className:'lbar-gh', role:'presentation', 'data-g':x.g, 'data-key':'lbar-group-' + x.g}, h('span', {}, x.head), h('b', {}, String(x.n))),
          ...list.map(o => row(a, o, x.g)), rest);
      }
      if (out.length) return out.filter(Boolean);
      return [h('p', {className:'meta', 'data-key':'lbar-empty'}, q ? 'No helper matches.' : 'No helper is open. New starts one.')];
    }
    // ORCH-1643: the Needs you number counts more than the sessions (questions, results to check): the rest is one link to Review
    function waitRest(x) {
      const rest = x.n - x.rows.length;
      return rest > 0 ? h('div', {className:'lbar-rw'}, h('a', {className:'lbar-row', href:'#review', 'data-key':'lbar-wait-rest'},
        sym('wait', LIVEBAR_SYM.wait), h('span', {className:'lbar-key'}), h('span', {className:'lbar-rn'}, rest + (rest === 1 ? ' more thing waits' : ' more things wait') + ' on the Review page'),
        h('span', {className:'lbar-go', 'aria-hidden':'true'}, 'Open'))) : null;
    }
    // Stop and End session of one session (ORCH-817, pages/live-end.js): from a row's More or a right-click on a row;
    // it opens where the menu opens.
    function endPop() {
      const id = typeof window.liveEndOpenAt === 'function' ? window.liveEndOpenAt('bar') : '';
      const menu = id ? window.liveEndMenu(id, 'bar:' + id) : null;
      return menu ? h('div', {className:'lbar-endwrap', 'data-key':'lbar-end'}, menu) : null;
    }
    function pop(a, all) {
      if (!bar.list) return endPop();
      return h('div', {className:'lbar-pop', role:'dialog', 'aria-label':'Helpers', 'data-key':'lbar-pop'},
        all.length >= LIVEBAR_SEARCH_FROM ? h('input', {className:'input', type:'search', placeholder:'Search helpers', 'aria-label':'Search helpers',
          autocomplete:'off', value:bar.q, 'data-lbar-q':'1'}) : null,
        h('div', {className:'lbar-list', 'data-lbar-rows':'1'}, rows(a, all)));
    }
    // New (draft D): a session without a ticket. One that is open already is offered as "go to it".
    // The Permissions row: one segment per mode of the tool; a mode the workspace does not allow is off and says why.
    // Nothing picked: each helper starts in its own remembered mode (its line says which).
    function permSegs() {
      const r = permRow('manager');
      if (!r) return null;
      return [h('div', {className:'live-prow', role:'group', 'aria-label':'Permissions', 'data-key':'lbar-perm'},
        h('span', {className:'meta'}, 'Permissions'),
        h('span', {className:'segmented', role:'group', 'aria-label':'Permissions'}, r.choices.map(c => h('button', {type:'button', className:'btn sm',
          'data-lbar-perm':c.mode, 'data-key':'lbar-perm-' + c.mode, 'aria-pressed':String(bar.perm === c.mode), disabled:!c.allowed || !!bar.busy,
          title:c.allowed ? null : LIVE_PERM_OFF}, c.label)))),
      // a greyed mode says why under the row, not only on hover (ORCH-1362, UX checklist D5)
      r.choices.some(c => !c.allowed) ? h('p', {className:'meta', 'data-key':'lbar-perm-off'}, r.choices.filter(c => !c.allowed).map(c => c.label).join(', ') + ': ' + LIVE_PERM_OFF.charAt(0).toLowerCase() + LIVE_PERM_OFF.slice(1)) : null,
      r.warn ? h('p', {className:'meta', 'data-key':'lbar-perm-warn'}, r.warn) : null];
    }
    // Runs on (ORCH-1660): the tool and the model of the next helper started here, the usual ones preselected; the same
    // row on the wall (window.LiveNew.runsOn). A tool picker only when there are two or more tools (kit .start-run).
    const runsOnNow = () => liveBarRunsOn(state.sessions, state?.settings?.agents, bar.pick);
    function runsOn(where) {
      const r = runsOnNow();
      if (!r) return null;
      const k = where === 'wall' ? 'wall-runs' : 'lbar-runs';
      const opt = (v, word, on, usual) => h('option', {value:v, selected:on ? '' : null}, word + (usual ? ' (usual)' : ''));
      const tool = r.tools.length > 1
        ? h('select', {'aria-label':'Tool', 'data-lnew-pick':'tool', 'data-key':k + '-tool', disabled:!!bar.busy},
          r.tools.map(t => opt(t.name, t.label, t.name === r.tool, t.name === r.usual)))
        : h('span', {className:'chip', 'data-key':k + '-tool'}, 'Tool: ' + r.tools[0].label);
      const model = r.takesModel
        ? h('select', {'aria-label':'Model', 'data-lnew-pick':'model', 'data-key':k + '-model', disabled:!!bar.busy},
          LIVEBAR_MODELS.map(([v, word]) => opt(v, word, v === r.model, v === r.usualModel)))
        : h('span', {className:'meta', 'data-key':k + '-model'}, 'This tool uses its own model.');
      return h('div', {className:where === 'wall' ? 'live-prow wall-runs' : 'live-prow', role:'group', 'aria-label':'Runs on', 'data-key':k},
        h('span', {className:'meta'}, 'Runs on'), h('span', {className:'start-run'}, tool, model));
    }
    // The helpers working (of how many may), under the choices (draft D): a new helper takes one, or waits in line when all are taken.
    function placesLine() {
      const p = typeof liveStartPlaces === 'function' ? liveStartPlaces(state?.runs, state?.settings, state?.start_line) : null;
      if (!p || typeof liveWallPlaces !== 'function') return null;
      return h('p', {className:'meta', 'data-key':'lbar-new-places'}, liveWallPlaces(p));
    }
    function newMenu() {
      return h('div', {className:'live-pop', role:'group', 'aria-label':'New session without a ticket', 'data-key':'lbar-new-menu'},
        h('p', {className:'live-pop-h'}, 'New session without a ticket'),
        runsOn('bar'),
        permSegs(),
        LIVEBAR_NEW.map(n => {
          const open = liveBarNewOpen(state.sessions, n.kind), r = permRow(n.kind), ended = open ? null : liveBarNewEnded(state.sessions, n.kind);
          const moved = open && r && bar.perm && r.running && r.cur !== r.running;  // goes on in the picked mode
          const what = moved ? 'Open: goes on in ' + r.label : open ? 'Already open: go to it' : ended ? 'Ended: start it again' : n.what + (r ? ' · ' + r.label : '');
          const start = h('button', {type:'button', className:'live-opt', 'data-lbar-kind':n.kind, 'data-key':'lbar-new-' + n.kind,
            'aria-busy':bar.busy === n.kind ? 'true' : null, disabled:!!bar.busy},
          h('span', {className:'live-opt-t'}, h('strong', {}, n.title), h('span', {className:'meta'}, what)));
          // an ended helper (ORCH-817): its earlier conversations are one click away
          return ended ? h('span', {className:'lbar-newrow'}, start, h('button', {type:'button', className:'btn sm ghost', 'data-lbar-hist':ended.id,
            'data-key':'lbar-new-history-' + n.kind, 'aria-label':'History of the ' + n.title}, 'History')) : start;
        }),
        placesLine());
    }
    function newButton(fold) {
      const tiny = fold >= 3;
      return h('span', {className:'live-end', 'data-key':'lbar-new-wrap'},
        h('button', {type:'button', className:'btn sm ghost', 'data-lbar-new':'1', 'data-key':'lbar-new', 'aria-expanded':String(bar.menu),
          'aria-haspopup':'true', 'aria-label':tiny ? 'New session without a ticket' : null, title:'New session without a ticket'},
        iconEl('plus'), tiny ? null : h('span', {className:'live-word'}, 'New')),
        bar.menu ? newMenu() : null);
    }
    function build(a, all, fold) {
      return h('div', {id:'live-bar', className:bar.docked ? 'lbar lbar-docked' : 'lbar', role:'group', 'aria-label':addonLabel(a) + ' bar', 'data-fold':String(fold), 'data-toast-clear':''},
        h('a', {className:'lbar-home', href:'#addon/' + encodeURIComponent(a.name), 'data-key':'lbar-home', title:addonLabel(a) + ' start page'}, addonLabel(a)),
        h('nav', {className:'lbar-sw', 'aria-label':'Sessions'}, helpersButton(liveBarNeedCount(needTotal(), all.filter(o => o.s === 'wait').length))),
        h('span', {className:'lbar-end'}, newButton(fold), typeof bar.end === 'function' ? bar.end() : null),
        pop(a, all));
    }
    // Opens the session in the layer when there is one, else its page (a chip's link).
    function openSession(a, id) {
      if (typeof window.LiveLayer?.open === 'function') window.LiveLayer.open(id);
      else location.hash = link(a, {id});
    }
    // The one start path (core `orch session new`), on the tool and model of the Runs on row; the new one is pinned
    // (pins stay in this browser until orch keeps them) and opens in the layer. One already open is only opened.
    async function startNew(kind) {
      const a = liveAddon();
      if (!a || bar.busy) return;
      const open = liveBarNewOpen(state.sessions, kind), pr = permRow(kind);
      const pick = pr && bar.perm && pr.cur === bar.perm ? bar.perm : '';  // a mode this kind can take, else its own
      if (open && !(pick && pr.running && pick !== pr.running)) { bar.menu = false; paint(true); openSession(a, open.id); return; }
      bar.busy = kind; paint(true); wallPaint();
      // a running one keeps its tool and model (ORCH-710): Runs on is only for a start
      const args = {...(open ? {kind} : liveBarNewArgs(kind, bar.pick, runsOnNow(), state.sessions)),
        ...(typeof livePermArgs === 'function' ? livePermArgs(kind, pick) : {})};
      const r = await act('session.new', args);
      bar.busy = '';
      if (r.ok) { bar.perm = ''; bar.pick = {tool:'', model:''}; }
      wallPaint();
      let made = r.ok ? liveBarNewOpen(state.sessions, kind) : null;
      if (r.ok && !made) {
        // #1531: orch started it but the answer's state does not list it yet: read the sessions once more, never
        // say "It did not start" for a start that worked
        await window.LiveSessions?.refresh?.();
        made = liveBarNewMade(state.sessions, window.LiveSessions?.list, kind);
        if (!made && typeof refresh === 'function') { await refresh(); made = liveBarNewMade(state.sessions, window.LiveSessions?.list, kind); }
      }
      bar.menu = !made && !r.ok;
      if (made) {
        // a session without a ticket is pinned by orch until it is unpinned (sessionprefs, ORCH-361)
        window.dispatchEvent(new CustomEvent('orch:live-pins', {detail:{key:made.id, pinned:true}}));
        await window.LiveSessions?.refresh?.();  // the bar and the panes read the sessions API: show it now
      }
      paint(true);
      if (made) openSession(a, made.id);
      else if (!r.ok) (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(r.text, 'It did not start.', () => startNew(kind));
    }
    // the wall shows the same Runs on row (pages/livewall.js): it is drawn again when the pick changes
    const wallPaint = () => { if (typeof liveWallRepaint === 'function') liveWallRepaint(); };
    window.LiveNew = {start: startNew, kinds: LIVEBAR_NEW, runsOn: () => runsOn('wall')};
    function place() {
      const el = bar.el; if (!el) return;
      const tab = document.getElementById('tabbar');
      el.style.setProperty('--lbar-bottom', tab && tab.offsetHeight ? tab.offsetHeight + 'px' : '0px');
      const p = el.querySelector('.lbar-pop'), b = bar.list && el.querySelector('[data-lbar-list="' + bar.list + '"]');
      if (p && b) {
        const x = b.getBoundingClientRect().left - el.getBoundingClientRect().left;
        p.style.left = Math.max(8, Math.min(x, el.clientWidth - p.offsetWidth - 8)) + 'px';
      }
      // ORCH-2198: the menu opens inside the window, on the side of the bar with more room (above it at the bottom,
      // below it at the top in full screen), and scrolls within the room there
      for (const m of el.querySelectorAll('.lbar-pop, .lbar-endwrap')) {
        const r = el.getBoundingClientRect(), at = liveBarMenuAt(r.top, window.innerHeight - r.bottom);
        m.dataset.at = at.side;
        if (m.classList.contains('lbar-pop')) m.style.maxHeight = at.max + 'px';
      }
    }
    function paint(force) {
      const a = liveAddon(), on = typeof liveFocusOn === 'function' && liveFocusOn() && !!a;
      // the place that outlives a page change when the dashboard has one ([data-keep]), else the end of .shell-body
      const host = bar.host?.isConnected ? bar.host : document.querySelector('.shell-body [data-keep]') || document.querySelector('.shell-body');
      if (!on || !host) {
        if (bar.el) { bar.el.remove(); bar.el = null; bar.sig = ''; }
        delete document.body.dataset.liveBar;
        return;
      }
      window.LiveSessions?.sync();
      if (!window.LiveSessions?.ready && !bar.el) return;  // no "All calm" flash before the first answer
      const all = liveBarModel(sessions(), pins(), groups());
      const sig = JSON.stringify([a.name, addonLabel(a), all, state.sessions, state.session_modes, state?.settings?.agents, bar.menu ? [state?.runs, state?.settings?.live_max, state?.start_line] : 0, bar.perm, bar.list, bar.menu, bar.pick, bar.busy, bar.panes, bar.shown, bar.docked, phone(), window.innerWidth, needTotal(), window.liveEndKey?.()]);
      if (!force && sig === bar.sig && bar.el?.parentNode === host) return;
      bar.sig = sig;
      const active = document.activeElement, focusKey = bar.el?.contains(active) ? (active.dataset.key || (active.dataset.lbarQ ? 'q' : '')) : '';
      const caret = focusKey === 'q' ? active.selectionStart : null;
      let fold = phone() ? 3 : 0, el = build(a, all, fold);
      if (bar.el) bar.el.replaceWith(el); else host.append(el);
      if (el.parentNode !== host) host.append(el);
      bar.el = el;
      for (let sw = el.querySelector('.lbar-sw'); fold < 4 && sw.scrollWidth > sw.clientWidth + 1; sw = el.querySelector('.lbar-sw')) {
        const next = build(a, all, ++fold); el.replaceWith(next); el = bar.el = next;
      }
      bar.fold = fold;
      document.body.dataset.liveBar = '1';
      place();
      window.UI?.toastPlace?.();  // an error toast that stays open moves up when the bar appears or changes height (ORCH-1594)
      if (focusKey) {
        const t = focusKey === 'q' ? el.querySelector('[data-lbar-q]') : el.querySelector('[data-key="' + focusKey + '"]');
        if (t) { t.focus(); if (caret != null) t.setSelectionRange(caret, caret); }
      }
    }
    function toggle(l) {
      bar.list = bar.list === l ? '' : l; bar.q = '';
      paint(true);
      const q = bar.el?.querySelector('[data-lbar-q]');
      if (q) q.focus(); else bar.el?.querySelector('.lbar-row')?.focus();
    }
    function close(back) {
      if (!bar.list) return;
      const l = bar.list; bar.list = ''; bar.q = ''; paint(true);
      if (back) bar.el?.querySelector('[data-lbar-list="' + l + '"]')?.focus();
    }
    // the Runs on row's tool and model (in the New menu or on the wall): kept for the next start
    document.addEventListener('change', e => {
      const sel = e.target.closest?.('[data-lnew-pick]');
      if (!sel) return;
      bar.pick = {...bar.pick, [sel.dataset.lnewPick]:sel.value};
      const key = sel.dataset.key, inBar = !!bar.el?.contains(sel);
      // after the kit's picker closed: the bar is drawn new, so the keyboard goes back to the same picker
      setTimeout(() => {
        paint(true); wallPaint();
        if (inBar) requestAnimationFrame(() => {
          const n = bar.el?.querySelector('[data-key="' + key + '"]');
          (n?.closest('.ui-select')?.querySelector('.ui-select-trigger') || n)?.focus();
        });
      });
    });
    document.addEventListener('click', e => {
      const nb = e.target.closest?.('[data-lbar-new]');
      if (nb && bar.el?.contains(nb)) {
        bar.menu = !bar.menu; bar.list = ''; bar.q = ''; paint(true);
        if (bar.menu) bar.el?.querySelector('[data-lbar-kind]')?.focus();
        return;
      }
      const hb = e.target.closest?.('[data-lbar-hist]');
      if (hb && bar.el?.contains(hb)) {
        bar.menu = false; paint(true);
        window.LiveLayer?.open?.(hb.dataset.lbarHist);  // its pane: Start again and the earlier conversations
        return;
      }
      const k = e.target.closest?.('[data-lbar-kind]');
      if (k && bar.el?.contains(k)) { startNew(k.dataset.lbarKind); return; }
      const pm = e.target.closest?.('[data-lbar-perm]');
      if (pm && bar.el?.contains(pm)) {  // pick (or unpick) the mode of the next start; nothing starts yet
        bar.perm = bar.perm === pm.dataset.lbarPerm ? '' : pm.dataset.lbarPerm;
        paint(true); bar.el?.querySelector('[data-lbar-perm="' + pm.dataset.lbarPerm + '"]')?.focus();
        return;
      }
      if (bar.menu && !bar.el?.querySelector('[data-key="lbar-new-wrap"]')?.contains(e.target)) { bar.menu = false; paint(true); }
      const b = e.target.closest?.('[data-lbar-list]');
      if (b && bar.el?.contains(b)) { toggle(b.dataset.lbarList); return; }
      // with the layer there, a chip or row opens its session in the layer instead of changing page
      const o = e.target.closest?.('[data-lbar-open]');
      if (o && bar.el?.contains(o) && typeof window.LiveLayer?.open === 'function' && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
        e.preventDefault(); close(false); window.LiveLayer.open(o.dataset.lbarOpen); return;
      }
      if (bar.list && (!bar.el?.contains(e.target) || e.target.closest('a'))) close(false);
    });
    document.addEventListener('input', e => {
      if (!e.target.matches?.('[data-lbar-q]') || !bar.el?.contains(e.target)) return;
      bar.q = e.target.value;
      const a = liveAddon(), box = bar.el.querySelector('[data-lbar-rows]');
      if (a && box) box.replaceChildren(...rows(a, liveBarModel(sessions(), pins(), groups())));
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || !bar.el?.contains(document.activeElement)) return;
      if (bar.menu) { e.stopPropagation(); bar.menu = false; paint(true); bar.el?.querySelector('[data-lbar-new]')?.focus(); }
      else if (bar.list) { e.stopPropagation(); close(true); }
    }, true);
    // the layer says which sessions are open ({mode, panes, shown: ticket ids}); the ones in sight are marked current
    window.addEventListener('orch:live-sessions', () => paint());
    // a Stop and End menu opened or closed (ORCH-817): the bar's own menu opens in place of a list
    window.addEventListener('orch:live-end', () => { if (window.liveEndOpenAt?.('bar')) { bar.list = ''; bar.q = ''; bar.menu = false; } paint(true); });
    // a right-click on a row of the Helpers menu opens its Stop and End menu, as its More button does
    document.addEventListener('contextmenu', e => {
      const c = e.target.closest?.('.lbar-row[data-lbar-open]');
      if (!c || !bar.el?.contains(c) || typeof window.liveEndShow !== 'function') return;
      if (window.liveEndShow('bar:' + c.dataset.lbarOpen)) e.preventDefault();
    });
    window.addEventListener('orch:live-layer', e => {
      const p = e.detail?.panes, v = e.detail?.shown;
      bar.panes = Array.isArray(p) ? p.map(String) : [];
      bar.shown = Array.isArray(v) ? v.map(String) : null;
      paint();
    });
    let frame = 0;
    window.addEventListener('resize', () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => paint(true)); });
    window.paintLiveBar = paint;
    window.LiveBar = {
      // Move the bar into another host (a mount point that survives page changes); it stays the same element.
      // docked: the host places it (the layer's dock), so it is not fixed to the bottom of the window.
      mount(host, opts = {}) { bar.host = host || null; bar.docked = !!(host && opts.docked); if (bar.el && host) host.append(bar.el); paint(true); },
      // The buttons at the right end (the layer's Open and Place): fn returns nodes, called on every repaint.
      end(fn) { bar.end = typeof fn === 'function' ? fn : null; paint(true); },
      repaint() { paint(true); },
      model: liveBarModel,
    };
  })();
}
