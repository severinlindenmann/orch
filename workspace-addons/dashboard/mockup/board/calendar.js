/* Mockup of the Tickets calendar (ORCH-1081, owner picked draft C on 20 Nov). Draws the month (weeks as rows, Late on
   the left) or the week from the sample tickets with the master looks (widgets.css .cal-*). Today is fixed at
   Fri 20 Nov 2026 so the pictures stay the same. Only the due day is shown. View, day and filters live in the address
   (?view=week&day=2026-11-23). The product: dashboard pages/tickets.js calendarView(). */
(() => {
'use strict';
const TODAY = '2026-11-20';
const PAGE = {todo:'ticket-copy.html', working:'ticket-working.html', needs:'ticket-question.html', check:'ticket-review.html', done:'ticket-done.html'};
const WORD = {todo:'To do', working:'Working', needs:'Needs you', check:'Check', done:'Done'};
// number, title, status, person, due day ('' = no due date), due time
const RAW = [
 [8, 'Print flyers for the street fair', 'todo', 'Ben', '', ''],
 [9, 'Which supplier for the gift boxes?', 'needs', 'Ben', '2026-11-20', '18:30'],
 [10, 'Weekly sales numbers by email', 'todo', 'Anna', '', ''],
 [11, 'Summarise the customer survey', 'check', 'Anna', '2026-11-19', ''],
 [12, 'Plan the autumn newsletter', 'working', 'Anna', '2026-11-24', ''],
 [14, 'Update the price list', 'working', 'Anna', '2026-11-23', '12:00'],
 [15, 'Book the spring workshop room', 'working', 'Ben', '2026-11-18', ''],
 [16, 'Prepare the new opening hours poster', 'done', 'Anna', '2026-11-17', ''],
 [17, 'Fix the typo on the opening hours page', 'done', 'Anna', '2026-11-13', ''],
 [18, 'Set up the weekly sales report', 'todo', 'Anna', '2026-11-27', ''],
 [19, 'Redesign the logo', 'todo', 'Ben', '2026-11-16', ''],
 [20, 'Thank-you notes for our top customers', 'todo', 'Ben', '2026-12-03', ''],
 [21, 'Answer customer emails from last week', 'todo', 'Ben', '', ''],
 [22, 'Send the December invoices', 'todo', 'Anna', '2026-12-01', '09:00'],
 [23, 'Order the Christmas gift boxes', 'todo', 'Ben', '2026-11-26', ''],
 [24, 'Write the Black Friday email', 'working', 'Anna', '2026-11-26', '10:00'],
 [25, 'Update the shop window poster', 'todo', 'Ben', '2026-11-26', ''],
 [26, 'Check the stock list for December', 'todo', 'Anna', '2026-11-26', ''],
 [27, 'Post the Black Friday offer online', 'todo', 'Anna', '2026-11-26', '18:30'],
 [28, 'Call the printer about the calendars', 'needs', 'Ben', '2026-11-26', ''],
 [29, 'Pay the October supplier bills', 'done', 'Anna', '2026-11-05', ''],
 [30, 'Send the November newsletter', 'done', 'Anna', '2026-11-10', ''],
 [31, 'Renew the website address', 'done', 'Ben', '2026-11-04', ''],
 [32, 'Plan the staff Christmas dinner', 'todo', 'Ben', '2026-12-11', ''],
 [33, 'Prepare the year-end stock count', 'todo', 'Anna', '2026-12-15', ''],
 [34, 'Collect customer reviews for the website', 'todo', 'Ben', '2026-11-30', ''],
 [35, 'Translate the menu card into French', 'todo', 'Anna', '', ''],
 [36, 'Tidy the shared photo folder', 'todo', 'Ben', '', ''],
 [37, 'Send the quote to the bakery', 'todo', 'Ben', '2026-11-12', ''],
 [38, 'Wrap the gift boxes for the fair', 'done', 'Ben', '2026-11-20', ''],
 [39, 'Clean up the customer address list', 'todo', 'Anna', '2026-11-25', '16:00'],
];
const ALL = RAW.map(([n, title, status, person, due, time]) => ({key:'ORCH-' + n, title, status, person, due, time}));

/* dates */
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DOWL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const D = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d, 12); };
const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const add = (s, n) => { const d = D(s); d.setDate(d.getDate() + n); return iso(d); };
const dow = s => (D(s).getDay() + 6) % 7;
const monday = s => add(s, -dow(s));
const num = s => D(s).getDate();
const first = s => s.slice(0, 8) + '01';
const dayShort = s => DOW[dow(s)] + ' ' + num(s) + ' ' + MON[D(s).getMonth()];
const dayLong = s => DOWL[dow(s)] + ' ' + num(s) + ' ' + MONL[D(s).getMonth()];
const range = mon => { const a = D(mon), b = D(add(mon, 6)); return a.getDate() + (a.getMonth() === b.getMonth() ? '' : ' ' + MON[a.getMonth()]) + ' – ' + b.getDate() + ' ' + MON[b.getMonth()]; };
const week = mon => Array.from({length:7}, (_, i) => add(mon, i));
const monthWeeks = s => { const f = first(s), out = []; for (let m = monday(f); m.slice(0, 7) <= f.slice(0, 7); m = add(m, 7)) out.push(m); return out; };
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);

/* state, kept in the address */
const P = new URLSearchParams(location.search);
const okDay = v => /^\d{4}-\d\d-\d\d$/.test(v || '') ? v : '';
const S = {view:P.get('view') === 'week' ? 'week' : 'month', cur:okDay(P.get('day')) || TODAY, sel:okDay(P.get('sel')), person:P.get('person') || '', q:P.get('q') || '', early:false, all:false};
const sync = () => { const u = new URL(location.href), set = (k, v) => v ? u.searchParams.set(k, v) : u.searchParams.delete(k);
  set('view', S.view === 'week' ? 'week' : ''); set('day', S.cur === TODAY ? '' : S.cur); set('sel', S.sel); set('person', S.person); set('q', S.q); history.replaceState(null, '', u); };

/* tickets */
const shown = () => ALL.filter(t => (!S.person || t.person === S.person) && (!S.q || (t.key + ' ' + t.title).toLowerCase().includes(S.q.toLowerCase())));
const late = t => !!t.due && t.due < TODAY && t.status !== 'done';
const order = (a, b) => (a.status === 'done') - (b.status === 'done') || (a.time || '99').localeCompare(b.time || '99') || a.key.localeCompare(b.key, 'en', {numeric:true});
const dueOn = day => shown().filter(t => t.due === day).sort(order);
const byDue = (a, b) => a.due.localeCompare(b.due) || order(a, b);
const lateList = () => shown().filter(late).sort(byDue);
const notLate = day => dueOn(day).filter(t => !late(t));
// One rule for a full day everywhere: from five tickets on, three show and the rest sit behind "+N more".
const cut = ts => ts.length > 4 ? ts.slice(0, 3) : ts;
const tone = t => late(t) ? 'late' : t.status === 'done' ? 'done' : t.due === TODAY ? 'today' : '';
const href = t => '../../ticket/' + PAGE[t.status];

/* small builders: text always goes in as text */
const h = (tag, attrs, ...kids) => { const e = document.createElement(tag);
  for (const k in attrs || {}) { const v = attrs[k]; if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k.startsWith('on')) e[k] = v; else e.setAttribute(k, v === true ? '' : v); }
  for (const c of kids.flat(3)) if (c != null && c !== false) e.append(c); return e; };
const put = (e, ...kids) => { for (const c of kids.flat(3)) if (c != null && c !== false) e.append(c); return e; };
const icon = t => UI.statusIcon(t.status);
const keyOf = t => h('span', {class:'key', text:t.key});
const dueWords = t => late(t) ? 'Was due ' + dayShort(t.due) : t.due === TODAY ? (t.time ? 'Due ' + t.time : 'Due today') : 'Due ' + dayShort(t.due) + (t.time ? ', ' + t.time : '');
const dueTag = t => late(t) ? h('span', {class:'chip danger', text:'Late'})
  : t.status === 'done' ? null
  : t.due === TODAY ? h('span', {class:'chip warning', text:t.time ? 'Due ' + t.time : 'Today'})
  : t.time ? h('span', {class:'cal-time', text:t.time}) : null;
const label = t => t.key + ' ' + t.title + ', ' + WORD[t.status] + ', ' + dueWords(t);

// One line on a day: status icon, title, then time and person (and the status word on the phone).
const chip = (t, o = {}) => h('a', {class:'cal-chip', href:href(t), 'data-tone':tone(t), title:t.key + ' ' + t.title + ' · ' + t.person, 'aria-label':label(t)},
  icon(t), h('span', {class:'cal-chip-t'}, keyOf(t), ' ', t.title),
    o.meta !== false ? h('span', {class:'cal-chip-m', text:[o.word && WORD[t.status], t.time, t.person].filter(Boolean).join(' · ')}) : null);
// A row in a day's list (the master short row): title, one fact line, Late or Today on the right.
const row = (t, o = {}) => h('a', {class:'short-row', href:href(t)}, icon(t),
  h('span', {class:'grow'}, h('span', {class:'short-title'}, keyOf(t), ' ', t.title),
    h('span', {class:'short-fact', text:[t.person, WORD[t.status], o.date ? dueWords(t) : t.time && !late(t) ? 'Due ' + t.time : ''].filter(Boolean).join(' · ')})),
  h('span', {class:'short-side'}, late(t) ? h('span', {class:'chip danger', text:'Late'}) : t.due === TODAY && t.status !== 'done' ? h('span', {class:'chip warning', text:'Today'}) : null));
// A full-width ticket card for the agenda: status, title, person, due.
const pill = t => { const p = h('span', {class:'pill' + (['working', 'needs', 'done'].includes(t.status) ? ' ' + t.status : '')}); p.append(icon(t), WORD[t.status]); return p; };
const full = t => h('a', {class:'cal-card', href:href(t), 'data-tone':tone(t)},
  h('span', {class:'cal-card-s'}, pill(t)), h('span', {class:'cal-card-t'}, keyOf(t), ' ', t.title),
  h('span', {class:'cal-card-who'}, h('span', {class:'avatar sm', 'aria-hidden':'true', text:t.person[0]}), t.person),
  h('span', {class:'cal-card-due'}, dueTag(t)));
const dayHead = (day, ln) => h('header', {class:'cal-dhead'},
  h('span', {class:'cal-num', text:num(day) === 1 ? num(day) + ' ' + MON[D(day).getMonth()] : String(num(day))}),
  day === TODAY && h('span', {class:'cal-tag', text:'Today'}), ln ? h('span', {class:'cal-late', text:ln + ' late'}) : null);
const dateBlock = day => h('header', {class:'cal-date'}, h('span', {class:'cal-dow', text:DOW[dow(day)]}), h('span', {class:'cal-dnum', text:String(num(day))}),
  day === TODAY ? h('span', {class:'cal-rel', text:'Today'}) : day === add(TODAY, 1) ? h('span', {class:'cal-rel', text:'Tomorrow'}) : null);
const moreBtn = (n, go) => h('button', {class:'btn ghost xs cal-more', type:'button', onclick:go, text:'+' + n + ' more'});
const none = text => h('p', {class:'meta cal-none', text:text || 'Nothing due'});
const emptyState = text => h('div', {class:'empty'}, h('p', {text}));

/* A day's whole list: a small window (draft A) or a side sheet (draft C). */
const openDay = (day, kind, list) => { const ts = list || dueOn(day);
  const body = h('div', {class:'cal-daylist'}, h('p', {class:'meta', text:plural(ts.length, 'ticket', 'tickets') + ' due'}), h('div', {class:'card cal-list'}, ts.map(t => row(t))));
  const d = h('dialog', {class:'sheet', 'aria-label':dayLong(day)});   // the master adds Close
  d.append(h('h2', {text:dayLong(day)}), body);
  d.addEventListener('close', () => d.remove(), {once:true}); document.body.append(d); d.showModal(); };

// A folding group of rows for the phone (the master short group).
const group = (title, ts, o = {}) => { const body = h('div', {class:'cal-gbody', hidden:!!o.folded});
  const show = o.cap ? cut(ts) : ts;
  put(body, ...(ts.length ? show.map(t => row(t, {date:o.date})) : [h('p', {class:'meta cal-gnone', text:'Nothing due'})]));
  if (ts.length > show.length) put(body, h('div', {class:'short-more'}, moreBtn(ts.length - show.length, o.more)));
  const b = h('button', {type:'button', 'aria-expanded':String(!o.folded), onclick:() => { const open = b.getAttribute('aria-expanded') !== 'true'; b.setAttribute('aria-expanded', String(open)); body.hidden = !open; }},
    h('span', {text:title}), o.tag, h('span', {class:'count', text:String(ts.length)}), UI.chevron());
  return h('section', {class:'card short-group' + (o.cls ? ' ' + o.cls : '')}, h('header', {class:'card-h'}, b), body); };

const draw = () => { const solo = S.view === 'week', thisMon = monday(TODAY), mons = solo ? [monday(S.cur)] : monthWeeks(S.cur), lates = lateList();
  const when = mon => mon < thisMon ? 'past' : mon === thisMon ? 'now' : mon === add(thisMon, 7) ? 'next' : 'later';
  const name = mon => mon === thisMon ? 'This week' : mon === add(thisMon, 7) ? 'Next week' : mon === add(thisMon, -7) ? 'Last week' : range(mon);
  const onDay = notLate;                                           // late tickets sit in the Late list, not on their day
  const more = (day, ts, show) => ts.length > show.length && moreBtn(ts.length - show.length, () => openDay(day, 'sheet', ts));
  const dayBody = (c, day, w) => { const ts = onDay(day);
    if (w === 'past') { if (ts.length) { const b = h('button', {class:'btn ghost xs cal-done', type:'button', onclick:() => openDay(day, 'sheet', ts)}); b.append(UI.statusIcon('done'), ts.length + ' done'); put(c, b); } return; }
    const show = cut(ts); put(c, show.map(t => chip(t, {meta:w !== 'later'})), more(day, ts, show)); };
  const cell = (day, w) => { const c = h('div', {class:'cal-cell', 'data-today':day === TODAY, 'aria-label':dayLong(day)}, dayHead(day, 0)); dayBody(c, day, w); return c; };
  // Saturday and Sunday share one cell
  const weekend = (a, b, w) => { const c = h('div', {class:'cal-cell cal-we', 'data-today':a === TODAY || b === TODAY, 'aria-label':dayLong(a) + ' and ' + dayLong(b)},
      h('header', {class:'cal-dhead'}, h('span', {class:'cal-num', text:'Sat ' + num(a) + ' · Sun ' + num(b)}), (a === TODAY || b === TODAY) && h('span', {class:'cal-tag', text:'Today'})));
    dayBody(c, a, w); dayBody(c, b, w); return c; };
  const counts = mon => { const ts = week(mon).flatMap(dueOn), l = ts.filter(late).length, d = ts.filter(t => t.status === 'done').length, o = ts.length - l - d;
    return [l && l + ' late', o && o + ' open', d && d + ' done'].filter(Boolean).join(', ') || 'Nothing due'; };
  const lane = h('aside', {class:'card cal-lane wide-only', 'aria-label':'Late tickets'}, h('header', {class:'card-h'}, h('span', {class:'dot-err', 'aria-hidden':'true'}), h('h2', {text:'Late'}), h('span', {class:'cal-count', text:String(lates.length)})),
    lates.length ? lates.map(t => h('a', {class:'cal-late', href:href(t)}, h('span', {class:'cal-late-t'}, keyOf(t), ' ', t.title), h('span', {class:'cal-late-m'}, h('b', {text:'Was due ' + dayShort(t.due)}), ' · ' + t.person + ' · ' + WORD[t.status])))
      : h('p', {class:'meta cal-lane-none', text:'Nothing is late.'}));
  // week: one full-width row per day with readable cards; month: the weeks as rows
  const grid = solo ? h('div', {class:'card cal-drows wide-only'}, h('p', {class:'cal-drows-h'}, h('strong', {text:name(mons[0]) + ': '}), counts(mons[0])),
      week(mons[0]).map(day => { const ts = onDay(day), ln = dueOn(day).length - ts.length;
        return h('section', {class:'cal-drow', 'data-today':day === TODAY, 'data-none':!ts.length, 'aria-label':dayLong(day)}, dateBlock(day),
          h('div', {class:'cal-items'}, ts.length ? ts.map(full) : none(ln ? 'Nothing else due' : 'Nothing due'))); }))
    : h('div', {class:'card cal-grid wide-only'},
    h('div', {class:'cal-head', 'aria-hidden':'true'}, h('span'), DOW.slice(0, 5).map(d => h('span', {text:d})), h('span', {text:'Weekend'})),
    mons.map(mon => { const w = when(mon), days = week(mon);
      const head = [h('strong', {text:name(mon)}), name(mon) === range(mon) ? null : h('span', {class:'meta', text:range(mon)}), h('span', {class:'meta', text:counts(mon)})];
      return h('section', {class:'cal-row', 'data-when':w, 'aria-label':name(mon)},
        h('button', {class:'cal-wk', type:'button', title:'Show this week', onclick:() => { S.view = 'week'; S.cur = mon === thisMon ? TODAY : mon; render(); }}, head),
        days.slice(0, 5).map(d => cell(d, w)), weekend(days[5], days[6], w)); }));
  // phone: Late first, then a list per day under each week; weeks that are over fold into one line
  const phone = h('div', {class:'phone-only cal-phone'});
  if (lates.length) put(phone, group('Late', lates, {date:true, cls:'cal-plate'}));
  mons.forEach(mon => { const w = when(mon), days = week(mon).filter(d => onDay(d).length);
    if (w === 'past' && !solo) { const ts = week(mon).flatMap(onDay); if (ts.length) put(phone, group(name(mon) === range(mon) ? range(mon) : name(mon) + ', ' + range(mon), ts, {folded:true, date:true})); return; }
    put(phone, h('div', {class:'cal-pwk'}, h('h3', {text:name(mon)}), name(mon) === range(mon) ? null : h('span', {class:'meta', text:range(mon)})));
    if (!days.length) { put(phone, none('Nothing due')); return; }
    put(phone, h('div', {class:'card cal-pdays'}, days.map(day => { const ts = onDay(day), show = cut(ts);
      return h('section', {class:'cal-prow', 'data-today':day === TODAY, 'aria-label':dayLong(day)}, dateBlock(day),
        h('div', {class:'cal-plist'}, show.map(t => chip(t, {word:true})), more(day, ts, show))); }))); });
  return [lane, grid, phone]; };

/* ---------- the page ---------- */
const $ = s => document.querySelector(s);
function render() { sync();
  const unit = S.view === 'week' ? 'week' : 'month', mon = monday(S.cur), end = D(add(mon, 6));
  $('#cal-title').textContent = S.view === 'week' ? range(mon) + ' ' + end.getFullYear() : MONL[D(S.cur).getMonth()] + ' ' + D(S.cur).getFullYear();
  $('#prev').setAttribute('aria-label', 'Previous ' + unit); $('#next').setAttribute('aria-label', 'Next ' + unit);
  document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
  const y = scrollY; $('#cal').replaceChildren(...draw()); scrollTo(0, y);
  const n = shown().filter(t => !t.due).length; $('#nodate').hidden = !n;
  $('#nodate-text').textContent = (n === 1 ? '1 ticket has' : n + ' tickets have') + ' no due date, so ' + (n === 1 ? 'it is' : 'they are') + ' not on the calendar.';
  $('#total').textContent = String(ALL.length); }
const step = dir => { if (S.view === 'week') S.cur = add(S.cur, 7 * dir); else { const d = D(first(S.cur)); d.setMonth(d.getMonth() + dir); S.cur = iso(d).slice(0, 7) === TODAY.slice(0, 7) ? TODAY : iso(d); }
  S.sel = ''; S.all = false; render(); };
$('#prev').onclick = () => step(-1); $('#next').onclick = () => step(1);
$('#today').onclick = () => { S.cur = TODAY; S.sel = ''; S.all = false; render(); };
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { S.view = b.dataset.view; S.sel = ''; S.all = false; render(); });
$('#person').value = S.person; $('#q').value = S.q;
$('#person').onchange = e => { S.person = e.target.value; render(); };
$('#q').oninput = e => { S.q = e.target.value; render(); };
document.addEventListener('keydown', e => { if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { e.preventDefault(); $('#q').focus(); } });
$('#nav-count').textContent = '3';
render();
})();
