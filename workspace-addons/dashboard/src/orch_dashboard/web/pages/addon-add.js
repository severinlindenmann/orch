'use strict';
// ORCH-1739, owner pick A: add several add-ons at once. Settings › Add-ons › "Add add-ons" opens a pick list with real
// checkboxes (add-ons that ship with orch and are not here yet, and installed ones that are off), a confirm step with
// each pick's consent lines, then ONE run (`addon.add`: `orch addon add <names> --yes --job`, one tool reinstall,
// one restart). The dialog then shows the run's steps from GET /api/addon-job; Hide leaves a slim banner on the
// Add-ons page. The job lives in a file of the machine, so a reload, another tab or the restart keeps it.
// Rules: the page never sends the add again by itself (Try again is a click, once); while orch restarts nothing else
// asks the server (window.orchQuiet), only the job is read until it answers; at most 31 minutes of waiting (the core fails a run after 30).

// --- the model (plain data, tested in tests/addon_add.test.js) ---
const AJ_LIVE = ['running', 'restarting'];
const AJ_OTHER = 'orch is adding add-ons from another workspace. This page comes back by itself.';
const AJ_BUSY = 'You can add more when this is done.';
const AJ_SLOW = 'orch is still restarting. Wait a moment, then try again.';
const AJ_GIVE_UP_MS = 31 * 60 * 1000;  // past the core's 30-minute stop, so the core's own failed answer comes first
const ajLive = job => !!job && AJ_LIVE.includes(job.state);
const ajJoin = names => names.length < 2 ? (names[0] || '') : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
const ajCount = n => n + (n === 1 ? ' add-on' : ' add-ons');
const ajAreOn = n => ajCount(n) + (n === 1 ? ' is on' : ' are on');
const ajClock = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const ajCap = s => String(s || '').replace(/^./, c => c.toUpperCase());
const ajLabel = (name, labels) => (labels && labels[name]) || ajCap(name);
// What the pick list sends: the picks in catalogue order, an add-on another pick needs (manifest `requires`, when the
// catalogue knows it) put in front of it. why[name] = the label of the pick that needs it (not picked by the person).
function ajPlan(picked, rows) {
  const byName = new Map(rows.map(r => [r.name, r])), list = [], why = {}, chosen = new Set(picked), seen = new Set();
  const put = (row, by) => {
    if (!row) return;
    if (!list.includes(row.name) && !seen.has(row.name)) {  // seen: two add-ons that need each other end the walk
      seen.add(row.name);
      for (const need of Array.isArray(row.requires) ? row.requires : []) put(byName.get(need), row);
      if (!list.includes(row.name)) list.push(row.name);
    }
    if (by && !chosen.has(row.name) && !why[row.name]) why[row.name] = by.label || ajCap(by.name);
  };
  rows.forEach(r => { if (chosen.has(r.name)) put(r); });
  return {list, why};
}
const AJ_STATE = {waiting:'todo', running:'now', done:'done', failed:'bad', skipped:'skip'};
// The view of one job dict (contract ORCH-1739): phase, title, the steps with their look, the line under the title.
// labels: name -> the name the person knows (the catalogue's); now: seconds on the server's clock.
function ajView(job, labels, now) {
  if (!job || typeof job !== 'object') return null;
  const names = Array.isArray(job.names) ? job.names.filter(n => typeof n === 'string') : [];
  const n = names.length, live = ajLive(job), final = job.state === 'failed', done = job.state === 'finished';
  const shown = names.map(x => ajLabel(x, labels));
  const raw = Array.isArray(job.steps) ? job.steps.filter(s => s && typeof s.key === 'string') : [];
  let bad = false;
  const steps = raw.map(s => {
    let look = AJ_STATE[s.state] || 'todo';
    if (done && s.key !== 'rollback') look = 'done';
    if (final && look === 'now') look = bad ? 'skip' : 'bad';
    if (final && look === 'todo') look = 'skip';
    const key = s.key, on = key.startsWith('on:') ? key.slice(3) : null;
    const label = key === 'ready' ? 'Getting ' + ajJoin(shown) + ' ready' : on ? 'Turning on ' + ajLabel(on, labels)
      : key === 'restart' ? 'Restarting orch (about 10 seconds)' : key === 'rollback' ? 'Putting things back as they were'
      : String(s.label || '');
    const step = {key, look, label, sub:'', bar:false, reason:''};
    if (look === 'bad' && !bad) { bad = true; step.reason = typeof job.reason === 'string' ? job.reason : ''; }
    if (key === 'ready' && look === 'now') { step.bar = true; step.sub = 'elapsed'; }
    if (key === 'restart' && look === 'now') step.sub = 'This page comes back by itself. Your tickets and helpers keep going.';
    if (key === 'restart' && look === 'todo') step.sub = 'Your tickets and helpers keep going.';
    return step;
  });
  const failedName = typeof job.failed === 'string' && job.failed ? job.failed : null;
  const failing = bad || !!failedName;
  const phase = job.here === false && live ? 'other' : live ? (failing ? 'failing' : 'going') : done ? 'done' : final ? 'failed' : 'idle';
  const rollback = steps.find(s => s.key === 'rollback');
  const nothing = final && ((rollback && rollback.look === 'done') || /Nothing was changed/.test(String(job.reason || '')));
  const lost = (failedName ? ajLabel(failedName, labels) : ajJoin(shown)) + ' could not be added';
  const title = phase === 'going' || phase === 'other' ? 'Adding ' + ajCount(n) : phase === 'failing' ? lost
    : phase === 'failed' ? (nothing ? 'Nothing was changed' : lost) : phase === 'done' ? ajAreOn(n) : '';
  const others = failedName ? names.filter(x => x !== failedName).map(x => ajLabel(x, labels)) : [];
  const note = phase !== 'failed' ? '' : !bad && job.reason ? String(job.reason)
    : others.length ? ajJoin(others) + (others.length === 1 ? ' was' : ' were') + ' not added either.' : '';
  const nowStep = steps.find(s => s.look === 'now') || null;
  const started = Number(job.started) || 0, ended = Number(job.ended) || 0;
  const elapsed = started ? Math.max(0, Math.floor((live || !ended ? now : ended) - started)) : 0;
  const readyNow = !!(nowStep && nowStep.key === 'ready');
  return {phase, live, title, note, steps, names, shown, n, nowStep, readyNow, elapsed, nothing,
    reason:typeof job.reason === 'string' ? job.reason : '', id:job.id || '',
    clock:(phase === 'going' || phase === 'failing') && !readyNow};
}
// The one line a screen reader hears for the state (role=status).
function ajSay(v) {
  if (!v) return '';
  return v.phase === 'going' ? (v.nowStep ? v.nowStep.label : v.title) : v.phase === 'failing' ? v.title + '. ' + v.reason
    : v.phase === 'done' ? v.title : v.phase === 'failed' ? v.title + '. ' + (v.reason || v.note) : v.phase === 'other' ? AJ_OTHER : '';
}

// --- the page ---
// phase: idle | pick | confirm | job. picked: the names ticked. job: the last job read. open: the dialog is shown.
const aj = {phase:'idle', picked:new Set(), job:null, d:null, title:null, live:null, sending:false, err:'', skew:0,
  polling:false, timer:0, tick:0, since:0, down:false, gaveUp:false, said:''};
const AJ_SEEN = 'orch-addon-job-seen';
const ajSeen = () => { try { return localStorage.getItem(AJ_SEEN) || ''; } catch (_) { return ''; } };
const ajMarkSeen = id => { if (id) try { localStorage.setItem(AJ_SEEN, id); } catch (_) { /* private window */ } };
const ajNow = () => Date.now() / 1000 + aj.skew;
// The add-ons the pick list offers: shipped and not here yet, and installed but off (never the dashboard).
function ajRows() {
  const st = state?.settings || {};
  const off = array(st.addons).filter(r => r && typeof r.name === 'string' && r.name !== 'dashboard' && !r.active && r.installed !== false);
  const avail = array(st.available).filter(r => r && typeof r.name === 'string' && r.name !== 'dashboard');
  return avail.concat(off.filter(r => !avail.some(a => a.name === r.name))).map(r => ({...r, label:rowLabel(r)}));
}
function ajLabels() {
  const out = {};
  for (const r of array(state?.settings?.available).concat(array(state?.settings?.addons))) if (r && typeof r.name === 'string') out[r.name] = rowLabel(r);
  return out;
}
const ajViewNow = () => ajView(aj.job, ajLabels(), ajNow());
// A job the page should show: a live one, or a finished or failed one of this workspace not closed yet.
const ajShowable = job => !!job && (ajLive(job) || (job.here !== false && (job.state === 'finished' || job.state === 'failed') && job.id !== ajSeen()));
const ajWin = typeof window === 'object' ? window : {};
ajWin.addonJobLive = () => ajLive(aj.job);
// Nothing else asks the server while orch restarts at the end of the run (the job is still read until it answers).
ajWin.addonJobQuiet = () => {
  if (aj.gaveUp || !ajLive(aj.job)) return false;
  const restart = array(aj.job.steps).find(s => s && s.key === 'restart');
  return aj.down || aj.job.state === 'restarting' || restart?.state === 'running';
};

async function ajRead() {
  try {
    const res = await fetch('/api/addon-job', {cache:'no-store'});
    if (!res.ok) return {ok:false};
    if (typeof noteBoot === 'function') noteBoot(res);
    const date = Date.parse(res.headers?.get?.('Date') || '');
    if (!Number.isNaN(date)) aj.skew = date / 1000 - Date.now() / 1000;
    const body = await res.json();
    return {ok:true, job:body && typeof body.job === 'object' ? body.job : null};
  } catch (_) { return {ok:false}; }
}
// Read the job every 1.5 s while it is live (or the server is away while it was); stop after 10 minutes.
function ajFollow(job) {
  if (job) aj.job = job;
  aj.gaveUp = false; aj.since = Date.now();
  if (!aj.polling) { aj.polling = true; ajSchedule(0); }
  ajTicker();
  ajPaint();
}
function ajSchedule(ms) { clearTimeout(aj.timer); aj.timer = setTimeout(ajPoll, ms); }
async function ajPoll() {
  const was = aj.job, r = await ajRead();
  if (!r.ok) aj.down = true;
  else {
    aj.down = false;
    aj.job = r.job;
  }
  const ended = ajLive(was) && r.ok && !ajLive(aj.job);
  if (ended) await ajFreshState();
  const keep = ajLive(aj.job) || (!r.ok && ajLive(was));
  if (keep && Date.now() - aj.since > AJ_GIVE_UP_MS) { aj.gaveUp = true; aj.polling = false; }
  else if (keep) ajSchedule(1500);
  else aj.polling = false;
  ajTicker();
  ajPaint();
}
// After the run: the state as it is now (the new add-ons, their pages in the menu).
async function ajFreshState() {
  try {
    const res = await fetch('/api/state?fresh=1', {cache:'no-store'});
    if (!res.ok) return;
    if (typeof noteBoot === 'function') noteBoot(res);
    const next = await res.json();
    if (next && !next.delta) accept(next);
  } catch (_) { /* the next poll of the page reads it */ }
}
// The time so far, every second, without drawing the page again.
function ajTicker() {
  const on = ajLive(aj.job);
  if (on && !aj.tick) aj.tick = setInterval(() => {
    const v = ajViewNow();
    if (!v) return;
    document.querySelectorAll('[data-elapsed]').forEach(e => { e.textContent = ajClock(v.elapsed); });
  }, 1000);
  if (!on && aj.tick) { clearInterval(aj.tick); aj.tick = 0; }
}
// The page's first look (and after a reload): a live job, or one not closed yet, shows its banner.
async function ajBoot() {
  if (snapshot) return;
  const r = await ajRead();
  if (!r.ok || !r.job) return;
  aj.job = r.job;
  if (ajLive(r.job)) ajFollow(r.job); else ajPaint();
}

// The one send. A refusal shows its words next to the buttons; a lost answer is never sent again: a job that
// started anyway is followed.
async function ajStart(names) {
  if (aj.sending || snapshot || !names.length) return;
  aj.sending = true; aj.err = ''; ajPaint();
  let res = null, body = null, text = '';
  try {
    res = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json', 'X-Orch-Op':'addon.add', 'X-Orch-Act-Id':newActId()},
      body:JSON.stringify({op:'addon.add', args:{names}})});
    if (typeof noteBoot === 'function') noteBoot(res);
    if (res.status === 202) body = await res.json(); else text = await res.text();
  } catch (_) { res = null; }
  aj.sending = false;
  if (res && res.status === 202 && body?.job) { aj.phase = 'job'; aj.picked.clear(); ajFollow(body.job); return; }
  if (!res) {
    const r = await ajRead();
    if (r.ok && ajLive(r.job)) { aj.phase = 'job'; aj.picked.clear(); ajFollow(r.job); return; }
    aj.err = 'Could not reach orch.';
  } else aj.err = String(text || 'That did not work.').slice(0, 300);
  ajPaint();
}

// --- drawing ---
const ajIc = look => look === 'now' ? h('span', {className:'run-ic', 'aria-hidden':'true'}, h('span', {className:'spinner'}))
  : h('span', {className:'run-ic is-' + look, 'aria-hidden':'true'}, look === 'done' ? '✓' : look === 'bad' ? '×' : look === 'skip' ? '–' : '');
const AJ_SR = {now:'Now: ', done:'Done: ', todo:'Next: ', bad:'Failed: ', skip:'Not done: '};
const ajElapsed = v => h('span', {className:'elapsed', 'data-elapsed':'1', 'aria-label':'Time so far'}, ajClock(v.elapsed));
function ajSteps(v) {
  return h('ol', {className:'run-steps', 'data-key':'addon-job-steps'}, v.steps.map(s => h('li', {className:'run-step is-' + s.look, 'data-key':'addon-job-step-' + s.key, ...(s.look === 'now' ? {'aria-current':'step'} : {})},
    ajIc(s.look), h('span', {}, h('span', {className:'sr-only'}, AJ_SR[s.look] || ''), s.label,
      s.bar ? h('span', {className:'progress indeterminate', 'aria-hidden':'true'}, h('span')) : null,
      s.sub === 'elapsed' ? h('span', {className:'meta run-sub'}, ajElapsed(v), ' · about a minute') : s.sub ? h('span', {className:'meta run-sub'}, s.sub) : null,
      s.reason ? h('span', {className:'run-sub run-reason'}, s.reason) : null))));
}
const ajBtn = (cls, label, key, click, off) => { const b = h('button', {type:'button', className:'btn ' + cls, 'data-key':key, disabled:!!off}, label); b.addEventListener('click', click); return b; };
const ajReport = () => { const a = h('button', {type:'button', className:'link-quiet actions-link', 'data-key':'addon-job-report'}, 'See the problem report'); a.addEventListener('click', async () => { if (aj.d) await window.orch.close(aj.d); if (typeof reportOpen === 'function') reportOpen(); }); return a; };
const ajClose = () => { if (aj.d) window.orch.close(aj.d); };
function ajRetry() {
  // the ones that did get turned on (a restart that failed, a rollback that failed) are left out: the server
  // refuses an add-on that is already on
  const on = new Set(addons().map(a => a.name));
  const names = aj.job && Array.isArray(aj.job.names) ? aj.job.names.filter(n => !on.has(n)) : [];
  if (names.length) ajStart(names);
  else ajClose();
}
function ajPickBody(rows, plan, busy) {
  if (!rows.length) return [settingsText('p', {className:'meta', 'data-key':'catalog-empty'}, 'Every add-on that comes with orch is already here and turned on.')];
  const list = h('div', {className:'pick-list', role:'group', 'aria-label':'Add-ons you can add', 'data-key':'catalog-list'}, rows.map(r => {
    const need = plan.why[r.name], on = plan.list.includes(r.name), id = 'pick-' + r.name;
    const box = h('input', {type:'checkbox', id, 'data-key':'catalog-pick-' + r.name, disabled:busy || !!need});
    box.checked = on;
    box.addEventListener('change', () => { if (box.checked) aj.picked.add(r.name); else aj.picked.delete(r.name); aj.err = ''; ajPaint(); });
    return h('label', {className:'pick-row' + (on ? ' is-on' : ''), for:id, 'data-key':'catalog-card-' + r.name}, box,
      h('span', {className:'grow'}, settingsText('span', {className:'pick-name'}, r.label), settingsText('span', {className:'meta pick-text'}, r.description || ''),
        need ? settingsText('span', {className:'meta pick-why'}, need + ' needs ' + r.label + ', so it is added too.') : null));
  }));
  return [settingsText('p', {className:'muted'}, 'Pick everything you want. They are added together.'), list,
    busy ? settingsText('p', {className:'meta', 'data-key':'catalog-busy'}, AJ_BUSY) : null];
}
// What turning it on does, in plain lines: the consent text without its description (shown in the pick list),
// its name-and-version line and the terminal command line (both technical for this dialog).
const ajConsent = r => {
  const lines = String(r.consent || '').split('\n').map(l => l.trim()).filter(Boolean);
  const name = String(r.name || ''), desc = String(r.description || '').trim();
  const plain = lines.filter(l => l !== desc && l !== name && !l.startsWith(name + ' ') && !/the terminal:/.test(l));
  return plain.join('\n');
};
function ajErr() { return aj.err ? settingsText('p', {className:'run-reason', role:'alert', 'data-key':'addon-job-error'}, aj.err) : null; }
// Draw the dialog for the phase and the job; the keyboard stays on the control it was on (or the title).
function ajPaintDialog() {
  const d = aj.d;
  if (!d) return;
  const had = document.activeElement, key = d.contains(had) ? had?.dataset?.key : '';
  const head = (title, extra) => { aj.title.textContent = title; return h('div', {className:'dialog-head'}, aj.title, extra || null); };
  const acts = (...kids) => h('div', {className:'actions'}, ...kids);
  const rows = ajRows(), labels = ajLabels(), busy = ajLive(aj.job);
  let parts;
  if (aj.phase === 'pick') {
    const plan = ajPlan([...aj.picked], rows), n = plan.list.length;
    parts = [head('Add add-ons'), ...ajPickBody(rows, plan, busy), ajErr(),
      acts(ajBtn('ghost', 'Cancel', 'addon-job-cancel', ajClose), ajBtn('primary', n ? 'Add ' + ajCount(n) : 'Add add-ons', 'addon-job-go', () => { if (n && !busy) { aj.phase = 'confirm'; aj.err = ''; ajPaint(); } }, !n || busy))];
  } else if (aj.phase === 'confirm') {
    const plan = ajPlan([...aj.picked], rows), n = plan.list.length, by = new Map(rows.map(r => [r.name, r]));
    parts = [head(n === 1 ? 'Add ' + ajLabel(plan.list[0], labels) + '?' : 'Add these ' + n + ' add-ons?'),
      h('ul', {className:'consent-list', 'data-key':'addon-job-consent'}, plan.list.map(name => { const r = by.get(name) || {name}; return h('li', {}, settingsText('strong', {}, ajLabel(name, labels)), settingsText('span', {}, ajConsent(r)),
        plan.why[name] ? settingsText('span', {}, 'Added because ' + plan.why[name] + ' needs it.') : null); })),
      settingsText('p', {className:'meta'}, 'This takes about a minute. orch restarts once at the end.'), ajErr(),
      acts(ajBtn('ghost', 'Back', 'addon-job-back', () => { aj.phase = 'pick'; aj.err = ''; ajPaint(); }, aj.sending),
        ajBtn('primary', n === 1 ? 'Yes, add it' : 'Yes, add them', 'addon-job-go', () => ajStart(plan.list), aj.sending || busy || !n))];
  } else {
    const v = ajViewNow();
    if (!v) { parts = [head('Add add-ons'), acts(ajBtn('outline', 'Close', 'addon-job-close', ajClose))]; }
    else if (v.phase === 'other') parts = [head('Add add-ons'), h('p', {className:'row muted'}, h('span', {className:'spinner', 'aria-hidden':'true'}), settingsText('span', {className:'grow'}, AJ_OTHER)),
      acts(ajBtn('outline', 'Close', 'addon-job-close', ajClose))];
    else if (v.phase === 'done') parts = [head(v.title), h('ul', {className:'done-list', 'data-key':'addon-job-done'}, v.names.map(name => h('li', {}, ajIc('done'), settingsText('span', {className:'grow'}, ajLabel(name, labels)),
      h('a', {className:'btn outline sm', href:addons().some(a => a.name === name) ? '#addon/' + encodeURIComponent(name) : '#settings/addons/' + encodeURIComponent(name), 'data-key':'addon-job-open-' + name, 'aria-label':'Open ' + ajLabel(name, labels)}, 'Open')))),
      acts(ajBtn('primary', 'Close', 'addon-job-close', ajClose))];
    else {
      const failed = v.phase === 'failed';
      parts = [head(v.title, v.clock ? ajElapsed(v) : null), v.note ? settingsText('p', {className:'muted'}, v.note) : null, ajSteps(v),
        aj.gaveUp ? settingsText('p', {className:'run-reason', role:'alert', 'data-key':'addon-job-slow'}, AJ_SLOW) : null, ajErr(),
        failed ? acts(ajReport(), ajBtn('outline', 'Close', 'addon-job-close', ajClose), ajBtn('primary', 'Try again', 'addon-job-retry', ajRetry, aj.sending))
          : aj.gaveUp ? acts(ajBtn('outline', 'Hide', 'addon-job-hide', ajClose), ajBtn('primary', 'Check again', 'addon-job-again', () => ajFollow(null)))
          : acts(settingsText('span', {className:'meta actions-note'}, v.phase === 'going' ? 'You can hide this. It keeps going by itself.' : ''), ajBtn('outline', 'Hide', 'addon-job-hide', ajClose))];
    }
  }
  d.replaceChildren(...parts.filter(Boolean), aj.live);
  const back = key && d.querySelector('[data-key="' + key + '"]:not([disabled])');
  if (back) back.focus({preventScroll:true});
  else if (d.contains(had) || had === document.body || !had) aj.title.focus({preventScroll:true});
}
function ajPaint() {
  const v = aj.phase === 'job' || !aj.d ? ajViewNow() : null, said = aj.d ? ajSay(v) : '';
  if (aj.d) ajPaintDialog();
  if (aj.live && aj.live.textContent !== said) aj.live.textContent = said;
  render();
}
// Open the dialog: on the job when one should be shown, else on the pick list (it reads the add-ons again first).
function addonCatalog(show) {
  if (snapshot) return;
  if (aj.d) return;
  const showJob = show === 'job' || ajLive(aj.job);
  aj.phase = showJob ? 'job' : 'pick';
  if (!showJob) { aj.picked.clear(); aj.err = ''; if (aj.job) ajMarkSeen(aj.job.id); }  // a new pick closes the last run
  const {d} = dialog('Add add-ons', 'dialog sheet-phone ui-bottom-close', 'settings-other');
  aj.d = d; aj.title = d.querySelector('h2'); aj.title.tabIndex = -1;
  aj.live = h('p', {className:'sr-only', role:'status', 'aria-live':'polite', 'data-key':'addon-job-say'});
  d.setAttribute('data-key', 'addon-job-dialog');
  d.addEventListener('close', () => {
    const v = aj.phase === 'job' ? ajViewNow() : null;
    if (v && (v.phase === 'done' || v.phase === 'failed')) ajMarkSeen(v.id);
    if (aj.phase !== 'job') aj.phase = 'idle';
    aj.d = null; aj.title = null; aj.live = null;
    render();  // the banner comes back under the closed dialog
  });
  window.orch.open(d);
  ajPaintDialog();  // after open: the kit's first open drops a plain Close button it finds in the dialog
  const first = aj.phase === 'pick' ? d.querySelector('input:not([disabled])') : null;
  (first || aj.title).focus({preventScroll:true});
  if (aj.phase === 'pick') fetch('/api/state?fresh=1', {cache:'no-store'}).then(res => res.ok ? res.json() : null).then(next => { if (next && !next.delta && aj.d === d) { accept(next); ajPaintDialog(); } }).catch(() => {});
}
// The banner on top of the Add-ons page while the dialog is closed (always for a run from another workspace).
function addonJobBanner() {
  const v = ajViewNow();
  if (!v || snapshot) return null;
  const spin = () => h('span', {className:'spinner', 'aria-hidden':'true'});
  const show = () => ajBtn('outline sm', 'Show', 'addon-job-show', () => addonCatalog('job'));
  const dismiss = () => ajBtn('ghost sm', 'Dismiss', 'addon-job-dismiss', () => { ajMarkSeen(v.id); aj.phase = 'idle'; render(); });
  if (v.phase === 'other') return h('div', {className:'banner info slim', 'data-key':'addon-job-banner-other'}, spin(), settingsText('p', {className:'grow'}, AJ_OTHER));
  if (aj.d) return null;
  if (v.phase === 'going') return h('div', {className:'banner info slim', 'data-key':'addon-job-banner-run'}, spin(),
    h('p', {className:'grow'}, settingsText('strong', {}, v.title), settingsText('span', {className:'banner-now'}, v.nowStep ? v.nowStep.label : ''),
      v.readyNow ? h('span', {className:'progress indeterminate', 'aria-hidden':'true'}, h('span')) : null),
    h('span', {className:'elapsed'}, ajElapsed(v), v.readyNow ? ' · about a minute' : ''), aj.gaveUp ? null : show(), aj.gaveUp ? settingsText('span', {className:'run-reason'}, AJ_SLOW) : null);
  if (v.phase === 'failing') return h('div', {className:'banner error slim', 'data-key':'addon-job-banner-bad'}, v.nowStep?.key === 'rollback' ? spin() : ajIc('bad'),
    h('p', {className:'grow'}, settingsText('span', {className:'run-reason'}, v.reason || v.title), settingsText('span', {className:'banner-now'}, v.nowStep?.key === 'rollback' ? v.nowStep.label : '')), ajElapsed(v), show());
  if (v.id === ajSeen() || v.phase === 'idle') return null;
  if (v.phase === 'failed') {
    const retry = ajBtn('primary sm', 'Try again', 'addon-job-retry', () => { addonCatalog('job'); ajRetry(); }, aj.sending);
    return h('div', {className:'banner error', 'data-key':'addon-job-banner-failed'}, h('div', {className:'grow'}, settingsText('strong', {}, v.title),
      v.reason ? settingsText('p', {className:'run-reason'}, v.reason) : null, v.note && v.note !== v.reason ? settingsText('p', {}, v.note) : null),
    h('div', {className:'actions'}, ajReport(), retry, dismiss()));
  }
  if (v.phase === 'done') return h('div', {className:'banner success slim', 'data-key':'addon-job-banner-done'}, ajIc('done'),
    h('p', {className:'grow'}, settingsText('strong', {}, v.title), settingsText('span', {className:'banner-now'}, ajJoin(v.names.map(n => ajLabel(n, ajLabels()))))), show(), dismiss());
  return null;
}

if (typeof module === 'object' && module.exports) {
  module.exports = {ajPlan, ajView, ajSay, ajJoin, ajCount, ajAreOn, ajClock, ajLive, AJ_OTHER, AJ_BUSY};
} else if (typeof document === 'object') {
  document.addEventListener('DOMContentLoaded', () => ajBoot());  // after app.js: the state, the sign-in and snapshot exist
}
