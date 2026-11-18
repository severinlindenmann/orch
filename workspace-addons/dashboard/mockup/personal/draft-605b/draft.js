/* Draft B (ORCH-605): "My day in one line". Mock data and views for the Personal add-on concept. Draft only.
   Every text goes through textContent; the only innerHTML is the fixed icon paths below. */
(() => {
'use strict';
const UI = window.UI;
const NOW = '2026-11-18T10:52:00', TODAY = 18, NOW_MIN = 10 * 60 + 52, DAY_START = 7 * 60, DAY_END = 20 * 60;
const NS = 'http://www.w3.org/2000/svg';
const pad = n => String(n).padStart(2, '0');
const mins = hm => { const p = hm.split(':'); return p[0] * 60 + +p[1]; };
const iso = (d, hm) => '2026-11-' + pad(d) + 'T' + hm + ':00';
const stamp = (d, hm) => UI.stamp(iso(d, hm), { now: NOW });
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const dow = d => DOW[(d + 5) % 7];
const dayName = d => d === TODAY ? 'today' : UI.stamp('2026-11-' + pad(d), { now: NOW });

function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  if (typeof props === 'string') n.className = props;
  else if (props) for (const k in props) {
    const v = props[k];
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'on') for (const e in v) n.addEventListener(e, v[e]);
    else if (k === 'vars') for (const c in v) n.style.setProperty(c, v[c]);
    else n.setAttribute(k, v === true ? '' : v);
  }
  kids.flat(3).forEach(c => { if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c))); });
  return n;
}
const IC = {
  meetings: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4m8-4v4"/>',
  messages: '<path d="M4 4h16v12H9l-5 4z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  notes: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6m-6 4h4"/>',
  files: '<path d="M3 6h7l2 3h9v10H3z"/>',
  tasks: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 3 3 5-6"/>',
  people: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  helper: '<path d="m12 3 2 6 7 3-7 2-2 7-2-7-7-2 7-3z"/>',
  left: '<path d="m15 5-7 7 7 7"/>', right: '<path d="m9 5 7 7-7 7"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>',
  pin: '<path d="M5 12h14m-5-5 5 5-5 5"/>'
};
function ic(name) {
  const s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('class', 'ic');
  s.innerHTML = IC[name] || IC.calendar;
  return s;
}
const KIND_IC = { mail: 'mail', teams: 'messages', wa: 'messages', note: 'notes' };
const KIND_WORD = { mail: 'Mail', teams: 'Teams', wa: 'WhatsApp', note: 'Note' };
const KIND_SRC = { mail: 'mail', teams: 'messages', wa: 'messages', note: 'notes' };

/* ---------- data ---------- */
const CALS = { work: { name: 'Work', src: 'Outlook' }, private: { name: 'Private', src: 'iCloud' }, family: { name: 'Family', src: 'shared' } };
const E = [];
const ev = (d, s, e, t, cal, o) => E.push(Object.assign({ id: 'e' + d + '-' + s.replace(':', ''), type: 'event', d, s, e, t, cal }, o));
for (let d = 2; d <= 30; d++) if ((d + 5) % 7 < 5) ev(d, '08:30', '09:00', 'Daily', 'work', { where: 'Teams', rec: d <= TODAY ? 'done' : null, people: ['Lea Brunner', 'Marco Keller', 'Jonas Frei'] });
ev(2, '13:00', '15:00', 'Quartalsplanung Q1', 'work', { where: 'Sitzungszimmer Limmat' });
ev(4, '10:00', '11:00', 'Helvetia: Vorgespräch', 'work', { where: 'Teams', rec: 'done', people: ['Anna Meier', 'Marco Keller'] });
ev(5, '17:00', '17:45', 'Coiffeur', 'private');
ev(7, '17:30', '19:00', 'Laternenumzug Kita', 'family');
ev(10, '10:00', '11:30', 'Sprint Planning', 'work', { where: 'Teams', rec: 'done' });
ev(11, '16:00', '17:00', 'Steuerberater', 'private');
ev(13, '15:00', '16:00', 'Sprint Review', 'work', { where: 'Teams', rec: 'done' });
ev(14, '10:00', '11:00', 'Skiferien planen', 'family');
ev(16, '10:00', '11:30', 'Sprint Planning', 'work', { id: 'm-sprint', where: 'Teams', rec: 'done', people: ['Lea Brunner', 'Marco Keller', 'Jonas Frei'] });
ev(16, '13:30', '14:15', '1:1 Lea Brunner', 'work', { where: 'Büro Zürich', people: ['Lea Brunner'] });
ev(16, '18:30', '19:30', 'Fitness', 'private');
ev(17, '11:00', '12:00', 'Architektur-Review Mandantenportal', 'work', { id: 'm-arch', where: 'Teams', rec: 'done', people: ['Marco Keller', 'Jonas Frei'] });
ev(17, '14:00', '15:00', 'Offerte Helvetia durchgehen', 'work', { where: 'Büro Zürich', people: ['Marco Keller'] });
ev(17, '17:30', '18:30', 'Elternabend Schule', 'family');
ev(18, '09:00', '09:45', 'Release 3.2: Go/No-go', 'work', { id: 'm-gonogo', where: 'Teams', rec: 'done', people: ['Lea Brunner', 'Marco Keller', 'Jonas Frei'] });
ev(18, '10:30', '11:30', 'Kickoff Helvetia: Mandantenportal', 'work', { id: 'm-kickoff', where: 'Teams', rec: 'live', people: ['Anna Meier', 'Lea Brunner', 'Marco Keller'] });
ev(18, '12:15', '13:00', 'Zmittag mit Jonas', 'private', { id: 'e-lunch', where: 'Markthalle' });
ev(18, '14:00', '15:00', 'Release-Planung 3.3', 'work', { where: 'Teams', people: ['Lea Brunner', 'Jonas Frei'] });
ev(18, '16:30', '17:00', 'Kinder abholen, Kita', 'family', { id: 'e-kita' });
ev(18, '19:00', '20:00', 'Tennis', 'private');
ev(19, '10:00', '11:00', 'Bewerbungsgespräch Backend', 'work', { where: 'Büro Zürich', people: ['Lea Brunner'] });
ev(19, '13:00', '14:30', 'Workshop Datenmigration', 'work', { where: 'Teams', people: ['Marco Keller', 'Anna Meier'] });
ev(19, '18:00', '20:00', 'Geburtstag Mama, Znacht', 'family');
ev(20, '11:00', '11:45', 'Zahnarzt', 'private');
ev(20, '15:00', '16:00', 'Sprint Review', 'work', { where: 'Teams', people: ['Lea Brunner', 'Marco Keller', 'Jonas Frei'] });
ev(21, '10:00', '12:00', 'Junioren-Match', 'family');
ev(22, '11:00', '13:00', 'Brunch bei Meiers', 'family');
ev(24, '10:00', '11:30', 'Sprint Planning', 'work', { where: 'Teams' });
ev(25, '14:00', '15:00', 'Helvetia: Review Sprint 1', 'work', { where: 'Teams' });
ev(26, '18:30', '20:00', 'Team-Znacht', 'work', { where: 'Restaurant Volkshaus' });
ev(27, '15:00', '16:00', 'Sprint Review', 'work', { where: 'Teams' });
ev(28, '17:00', '19:00', 'Adventsmarkt', 'family');
ev(29, '09:00', '12:00', 'Tennis-Turnier', 'private');
ev(30, '13:00', '14:00', 'Monatsabschluss', 'work', { where: 'Büro Zürich' });
E.sort((a, b) => a.d - b.d || mins(a.s) - mins(b.s));

const MEET = {
  'm-gonogo': {
    length: '45 min',
    summary: 'Release 3.2 goes out on Thursday at 18:00. Two open bugs are accepted as known issues. Helvetia gets the test report before the release.',
    steps: [
      { who: 'Lea Brunner', text: 'Testbericht 3.2 an Helvetia schicken', due: 'by Thursday noon' },
      { who: 'Marco Keller', text: 'Rollback-Plan für die Datenmigration prüfen', due: 'by Thursday noon' },
      { who: 'Jonas Frei', text: 'Alarm für den Login-Dienst einrichten', due: 'before the release' },
      { who: 'Severin', text: 'Release-Notes freigeben', due: 'today' }
    ],
    lines: [
      ['09:01', 'Severin', 'Gut, starten wir. Lea, wie sieht der Testbericht aus?'],
      ['09:03', 'Lea Brunner', 'Alle 214 Tests grün. Zwei bekannte Fehler im Export, beide mit Umgehung dokumentiert.'],
      ['09:09', 'Marco Keller', 'Die Datenmigration lief auf Staging in 14 Minuten durch. Den Rollback will ich noch einmal prüfen.'],
      ['09:17', 'Jonas Frei', 'Monitoring steht, es fehlt nur der Alarm für den Login-Dienst. Das mache ich vor dem Release.'],
      ['09:26', 'Lea Brunner', 'Helvetia will den Testbericht sehen, bevor wir live gehen. Ich schicke ihn bis Donnerstagmittag.'],
      ['09:38', 'Severin', 'Dann ist es ein Go für Donnerstag 18 Uhr. Ich gebe die Release-Notes heute frei.']
    ],
    helper: [['Read the transcript and wrote the summary', '09:47'], ['Proposed 4 next steps', '09:48']]
  },
  'm-kickoff': {
    summary: 'So far: Helvetia wants the first pilot with 40 advisers in February. Sign-in must use their own company login.',
    steps: [
      { who: 'Marco Keller', text: 'Offerte v3 mit Pilot-Umfang ergänzen', due: 'said at 10:41' },
      { who: 'Severin', text: 'Termin für den Technik-Workshop vorschlagen', due: 'said at 10:48' }
    ],
    lines: [
      ['10:31', 'Anna Meier', 'Danke, dass ihr alle da seid. Ich stelle kurz unser Projektteam vor.'],
      ['10:36', 'Severin', 'Unser Vorschlag: zuerst ein Pilot mit einer Agentur, danach der Ausbau.'],
      ['10:41', 'Anna Meier', 'Für den Pilot denken wir an 40 Beraterinnen und Berater ab Februar. Passt das in die Offerte?'],
      ['10:43', 'Marco Keller', 'Das ergänze ich in der Offerte v3, ihr habt sie bis Freitag.'],
      ['10:48', 'Lea Brunner', 'Die Anmeldung müsste über euer Firmen-Login laufen. Dafür brauchen wir einen Technik-Workshop.'],
      ['10:51', 'Anna Meier', 'Einverstanden. Schickt mir zwei Terminvorschläge, dann lade ich unsere IT dazu ein …']
    ],
    helper: []
  }
};
const IN = [
  { id: 'i-sprint', type: 'in', kind: 'teams', d: 16, at: '11:40', who: 'Marco Keller', subject: 'Sprint-Ziele bestätigt', pin: 'm-sprint',
    msgs: [['Marco Keller', '11:40', 'Sprint-Ziele sind im Board, alle drei bestätigt.'], ['Severin', '11:44', 'Super, danke dir.', true]] },
  { id: 'i-list', type: 'in', kind: 'mail', d: 17, at: '16:05', who: 'Anna Meier', subject: 'Teilnehmerliste Kickoff', pin: 'm-kickoff', box: 'Outlook (work)',
    msgs: [['Anna Meier', '16:05', 'Guten Tag Severin, von uns nehmen drei Personen am Kickoff teil. Die Liste ist im Anhang. Freundliche Grüsse, Anna Meier']] },
  { id: 'i-anna', type: 'in', kind: 'mail', d: 18, at: '08:12', who: 'Anna Meier', subject: 'Agenda Kickoff und offene Punkte', pin: 'm-kickoff', box: 'Outlook (work)', addr: 'anna.meier@example.ch',
    msgs: [
      ['Anna Meier', '08:12', 'Guten Morgen Severin, anbei die Agenda für heute 10:30. Zwei Punkte möchten wir sicher klären: den Umfang des Pilots und die Anmeldung über unser Firmen-Login. Könnt ihr dazu etwas vorbereiten? Freundliche Grüsse, Anna Meier'],
      ['Severin', '08:31', 'Guten Morgen Anna, danke für die Agenda. Beide Punkte nehmen wir auf, Lea bringt einen Vorschlag zur Anmeldung mit. Bis gleich, Severin', true]
    ],
    draft: 'Guten Tag Anna, vielen Dank für das Gespräch. Wie besprochen schicken wir die Offerte v3 bis Freitag und zwei Terminvorschläge für den Technik-Workshop. Freundliche Grüsse, Severin' },
  { id: 'i-kita', type: 'in', kind: 'wa', d: 18, at: '08:40', who: 'Familie', subject: 'Wer holt heute ab?', pin: 'e-kita', group: true,
    msgs: [['Mama', '08:40', 'Wer holt heute die Kinder in der Kita ab?'], ['Severin', '08:43', 'Ich, 16:30. Steht im Kalender.', true], ['Mama', '08:44', 'Perfekt, danke!']] },
  { id: 'i-lea', type: 'in', kind: 'teams', d: 18, at: '09:20', who: 'Lea Brunner', subject: 'Testbericht 3.2 ist im Kanal', pin: 'm-gonogo',
    msgs: [
      ['Lea Brunner', '09:20', 'Der Testbericht 3.2 liegt im Kanal «Release». Die zwei Export-Fehler stehen ganz oben.'],
      ['Severin', '09:47', 'Danke. Kannst du ihn bis morgen Mittag an Helvetia schicken?', true],
      ['Lea Brunner', '09:49', 'Ja, mache ich. Soll Anna Meier direkt im Verteiler sein?'],
      ['Severin', '09:52', 'Ja bitte, und Marco in Kopie.', true]
    ] },
  { id: 'i-marco', type: 'in', kind: 'mail', d: 18, at: '09:58', who: 'Marco Keller', subject: 'Offerte Helvetia v3', person: 'Marco Keller', box: 'Outlook (work)',
    msgs: [['Marco Keller', '09:58', 'Hoi Severin, die Offerte v3 ist im Anhang. Der Pilot fehlt noch, den ergänze ich nach dem Kickoff. Gruss, Marco']] },
  { id: 'i-jonas', type: 'in', kind: 'wa', d: 18, at: '10:31', who: 'Jonas Frei', subject: 'Zmittag 12:15 in der Markthalle?', pin: 'e-lunch',
    msgs: [['Jonas Frei', '10:31', 'Zmittag 12:15 in der Markthalle? Ich reserviere einen Tisch.'], ['Severin', '10:33', 'Gern, bin im Kickoff bis 11:30 und komme danach direkt.', true], ['Jonas Frei', '10:34', 'Tisch ist reserviert, bis später.']] }
];
const NOTES = [
  { id: 'n-helvetia', type: 'note', kind: 'note', title: 'Helvetia: Ansprechpersonen und Verlauf', pin: 'm-kickoff', changed: [17, '17:20'],
    body: [
      ['Anna Meier leitet das Projekt bei Helvetia. Entscheide über das Budget fällt ihr Vorgesetzter, er ist im Kickoff nicht dabei.'],
      ['Seit dem Vorgespräch am 4. November ist klar: zuerst ein Pilot, dann der Ausbau. Die Technik steht in ', ['n-portal'], '.'],
      ['Offen: Anmeldung über das Firmen-Login, siehe auch ', ['n-release'], ' für den Zeitplan.']
    ], links: ['n-portal', 'n-release'], back: ['n-portal'] },
  { id: 'n-portal', type: 'note', kind: 'note', title: 'Mandantenportal Architektur', pin: 'm-arch', changed: [17, '12:10'],
    body: [
      ['Das Portal läuft pro Kunde getrennt. Die Anmeldung wird über das Login des Kunden angebunden.'],
      ['Entschieden im Architektur-Review: eine Datenbank pro Kunde. Kundenwissen steht in ', ['n-helvetia'], '.']
    ], links: ['n-helvetia'], back: ['n-helvetia'] },
  { id: 'n-release', type: 'note', kind: 'note', title: 'Release 3.2 Checkliste', pin: 'm-gonogo', changed: [18, '09:50'],
    body: [
      ['Testbericht an den Kunden, Rollback geprüft, Alarm für den Login-Dienst, Release-Notes freigegeben.'],
      ['Release am Donnerstag 18:00. Betroffen ist auch der Pilot aus ', ['n-helvetia'], '.']
    ], links: ['n-helvetia'], back: ['n-helvetia'] }
];
const find = id => E.find(x => x.id === id) || IN.find(x => x.id === id) || NOTES.find(x => x.id === id);
const itemDay = it => !it ? TODAY : it.type === 'note' ? (find(it.pin) || {}).d || TODAY : it.d;

/* Helper access is set per account, not per source. Level 0 is always "Nothing". */
const SOURCES = [
  { id: 'meetings', name: 'Meetings', what: 'Records your calls on this computer. No bot joins the meeting.', accounts: [
    { id: 'rec', name: 'Recorder on Severin’s MacBook Pro', short: 'MacBook recorder', state: 'Connected · last sent today 09:46', opts: ['Nothing', 'Read transcripts', 'Read and make tickets'], level: 2,
      scope: 'Transcripts, summaries and next steps of calls you recorded. Never the sound: recordings stay on your computer.' }] },
  { id: 'calendar', name: 'Calendar', what: 'All your calendars in one view.', accounts: [
    { id: 'work', cal: 'work', name: 'Work · Outlook', short: 'Work', state: 'Connected', opts: ['Nothing', 'Read', 'Read and propose times'], level: 1, scope: 'Titles, times, places and who is invited, in your work calendar.' },
    { id: 'private', cal: 'private', name: 'Private · iCloud', short: 'Private', state: 'Connected', opts: ['Nothing', 'Busy times only', 'Read'], level: 0, scope: 'With "Busy times only": when you are busy, no titles. With "Read": titles, times and places of your private entries.' },
    { id: 'family', cal: 'family', name: 'Family · shared', short: 'Family', state: 'Connected', opts: ['Nothing', 'Busy times only', 'Read'], level: 0, scope: 'With "Busy times only": when you are busy, no titles. With "Read": titles, times and places the whole family entered.' }] },
  { id: 'messages', name: 'Messages', what: 'Your chats, shown at the time they arrived.', accounts: [
    { id: 'teams', name: 'Teams · work', short: 'Teams', state: 'Connected', opts: ['Nothing', 'Read', 'Read and draft, you send'], level: 1, scope: 'Your work chats and channels in Teams.' },
    { id: 'wa', name: 'WhatsApp · 4 chats you picked', short: 'WhatsApp', state: 'Connected', opts: ['Nothing', 'Read the picked chats'], level: 0, scope: 'The text of the 4 chats you picked: Familie, Jonas Frei, Tennisclub, Kita Eltern. No other chat, no photos. Helpers never write on WhatsApp.' }] },
  { id: 'mail', name: 'Mail', what: 'Mail threads, pinned to the meeting or person they belong to.', accounts: [
    { id: 'outlook', name: 'Outlook · work', short: 'Work mail', state: 'Connected', opts: ['Nothing', 'Read', 'Read and draft, you send'], level: 2, scope: 'Your work mail. A helper writes a draft; only you send it.' },
    { id: 'pmail', name: 'Private mail · iCloud', short: 'Private mail', state: 'Connected', opts: ['Nothing', 'Read', 'Read and draft, you send'], level: 0, scope: 'Every mail in your private inbox, also from banks, doctors and family.' }] },
  { id: 'notes', name: 'Notes', what: 'Your notes folder with links between notes.', accounts: [
    { id: 'vault', name: 'Folder "Severin" on this computer · 412 notes', short: 'Notes folder', state: 'Connected', opts: ['Nothing', 'Read', 'Read and edit'], level: 2, scope: 'Every note in the folder "Severin". With "Read and edit" a helper can also change and add notes.' }] }
];
const acc = id => { for (const s of SOURCES) { const a = s.accounts.find(x => x.id === id); if (a) return a; } };
const accState = a => a.id === 'pmail' && !S.mailOk ? 'Sign-in ended Mon 21:14' : a.state;
const can = a => a.level === 0 ? 'Helpers can use nothing' : 'Helpers can ' + a.opts[a.level].toLowerCase();
function canLine(s) {
  if (s.accounts.length === 1) return can(s.accounts[0]);
  const open = s.accounts.filter(a => a.level > 0);
  return 'Helpers can use: ' + (open.length ? open.map(a => a.short).join(', ') + (open.length < s.accounts.length ? ' only' : '') : 'nothing');
}
const KIND_ACC = { teams: 'teams', wa: 'wa' };
const itemAcc = i => i.kind === 'mail' ? acc(i.box && i.box.startsWith('Private') ? 'pmail' : 'outlook') : acc(KIND_ACC[i.kind]);
const LATER = [['files', 'Files', 'Documents shown on the meeting they were shared in.'], ['tasks', 'Tasks', 'To-dos with a date, on their day.'], ['people', 'People', 'Everything about one person in one place.']];
const LATELY = [
  ['mail', 'Drafted a reply to Anna Meier. It waits for you to send.', [18, '10:02'], 'i-anna'],
  ['meetings', 'Wrote the summary and proposed 4 tickets for Release 3.2: Go/No-go.', [18, '09:48'], 'm-gonogo'],
  ['calendar', 'Read today’s work calendar to plan the ticket "Offerte Helvetia nachfassen".', [18, '08:05'], null],
  ['notes', 'Added the review decision to the note Mandantenportal Architektur.', [17, '12:10'], 'n-portal'],
  ['messages', 'Asked for a WhatsApp chat. It may use nothing there, so it asked you instead.', [17, '09:30'], null],
  ['meetings', 'Made 3 tickets from the next steps of Sprint Planning.', [16, '11:42'], 'm-sprint']
];

/* ---------- state ---------- */
const S = { earlier: false, off: new Set(), hideCal: new Set(), tickets: new Set(), unchecked: new Set(), mailOk: false, autoTickets: true };
const on = id => !S.off.has(id);
const say = (m, undo) => { document.getElementById('announcement').textContent = m; if (UI.toast) UI.toast(m, undo); };

/* ---------- routing ---------- */
const VIEWS = ['week', 'day', 'month', 'sources', 'empty', 'error'];
function route() {
  const p = location.hash.replace(/^#\/?/, '').split('/');
  let view = p[0] || 'week', day = null;
  const m = /^day-(\d+)$/.exec(view);
  if (m) { view = 'day'; day = Math.min(30, Math.max(1, +m[1])); }
  if (!VIEWS.includes(view)) view = 'week';
  const item = p[1] ? find(p[1]) : null;
  if (day == null) day = view === 'day' && item ? itemDay(item) : TODAY;
  return { view, day, item, tab: p[2] || 'summary', variant: view === 'empty' || view === 'error' ? view : null };
}
function link(r, id, tab) {
  const base = r.view === 'day' ? (r.day === TODAY ? 'day' : 'day-' + r.day) : r.view;
  return '#' + base + (id ? '/' + id : '') + (tab && tab !== 'summary' ? '/' + tab : '');
}

/* ---------- small parts ---------- */
const swatch = cal => h('span', { class: 'p5-sw', 'data-cal': cal, 'aria-hidden': 'true' });
const calChip = cal => h('span', 'chip outline', swatch(cal), CALS[cal].name);
function visibleEvents(r, d) {
  if (!on('calendar') || r.variant === 'empty') return [];
  return E.filter(e => e.d === d && !S.hideCal.has(e.cal));
}
function incoming(d) { return IN.filter(i => i.d === d && on(KIND_SRC[i.kind])); }
function attached(e) {
  return { inc: IN.filter(i => i.pin === e.id && on(KIND_SRC[i.kind])), notes: on('notes') ? NOTES.filter(n => n.pin === e.id) : [] };
}
function recState(e, r) {
  if (!e.rec || !on('meetings')) return null;
  if (e.rec === 'live') return r.variant === 'error' ? 'missed' : 'live';
  return 'done';
}
const pinLabel = i => i.pin ? find(i.pin).t : i.person;
function evLabel(e, r) {
  const a = attached(e), rs = recState(e, r), bits = [e.t, stamp(e.d, e.s) + ' to ' + e.e, CALS[e.cal].name + ' calendar'];
  if (rs === 'live') bits.push('recording now'); if (rs === 'done') bits.push('recorded'); if (rs === 'missed') bits.push('not recorded');
  if (a.inc.length) bits.push(a.inc.length + (a.inc.length === 1 ? ' message or mail' : ' messages and mails')); if (a.notes.length) bits.push(a.notes.length === 1 ? '1 note' : a.notes.length + ' notes');
  return bits.join(', ');
}
function marks(e, r, big) {
  const a = attached(e), rs = recState(e, r), out = [];
  if (rs === 'live') out.push(h('span', 'p5-mark', h('span', 'dot-work'), 'Recording'));
  if (rs === 'done') out.push(h('span', 'p5-mark', ic('meetings'), big ? 'Recorded' : null));
  if (rs === 'missed') out.push(h('span', 'p5-mark', h('span', 'dot-err'), 'Not recorded'));
  const mail = a.inc.filter(i => i.kind === 'mail').length, chat = a.inc.length - mail;
  if (mail) out.push(h('span', 'p5-mark', ic('mail'), String(mail)));
  if (chat) out.push(h('span', 'p5-mark', ic('messages'), String(chat)));
  if (a.notes.length) out.push(h('span', 'p5-mark', ic('notes'), String(a.notes.length)));
  return out.length ? h('span', 'p5-marks', out) : null;
}
function evBlock(e, r, big) {
  const len = mins(e.e) - mins(e.s), sel = r.item && (r.item.id === e.id || r.item.pin === e.id);
  return h('a', { class: 'p5-ev' + (sel ? ' cur' : '') + (recState(e, r) === 'live' ? ' live' : ''), href: link(r, e.id), 'data-cal': e.cal, 'data-short': len < 45 || null, 'data-tall': len >= 60 || null,
    'aria-label': evLabel(e, r), title: e.t, vars: { '--at': mins(e.s), '--len': len } },
    h('span', 'p5-ev-t', e.t),
    big ? h('span', 'p5-ev-row', h('span', 'p5-ev-m', e.s + ' – ' + e.e + ' · ' + CALS[e.cal].name + (e.where ? ' · ' + e.where : '')), marks(e, r, true)) : len >= 45 ? marks(e, r, false) : null);
}
function hoursCol() {
  const c = h('div', { class: 'p5-hours', 'aria-hidden': 'true' });
  for (let m = DAY_START; m < DAY_END; m += 60) c.append(h('span', null, pad(m / 60) + ':00'));
  return c;
}
const nowLine = () => h('div', { class: 'p5-now', vars: { '--at': NOW_MIN } }, h('span', 'sr-only', 'Now, 10:52'));
/* lane items never overlap: each one sits at its own time or right under the one before */
function laneSlots(items, gap) {
  let last = -999;
  return items.map(i => { const at = Math.max(mins(i.at), last + gap); last = at; return { i, at }; });
}

/* ---------- top parts ---------- */
function strip(r, cls) {
  const grid = h('div', 'p5-srcgrid');
  SOURCES.forEach(s => {
    const off = r.variant === 'empty' ? s.id !== 'calendar' : !on(s.id);
    let dot = h('span', 'dot-ok'), state = 'Connected';
    if (off) { dot = null; state = 'Off'; }
    else if (r.variant === 'empty') state = 'On since 10:51';
    else if (s.id === 'meetings' && r.variant === 'error') { dot = h('span', 'dot-err'); state = 'Recorder not reachable'; }
    else if (s.id === 'mail' && !S.mailOk) { dot = h('span', 'dot-warn'); state = 'Private mail: sign in again'; }
    grid.append(h('a', { class: 'p5-srcrow' + (off ? ' off' : ''), href: '#sources', 'aria-label': s.name + ', ' + state + '. ' + (off ? '' : canLine(s) + '. ') + 'Change' },
      h('span', 'p5-srchead', ic(s.id), h('b', null, s.name), h('span', 'p5-srcstate', dot, state)),
      h('span', 'p5-srcacc', s.accounts.map(a => a.short).join(' · ')),
      off ? h('span', 'p5-srccan', 'Helpers can use nothing') : h('span', 'p5-srccan', canLine(s))));
  });
  return h('section', { class: 'p5-strip ' + cls, 'aria-label': 'Sources' }, grid);
}
function statusLines(r) {
  if (r.variant === 'empty') return null;
  const rows = [], k = find('m-kickoff');
  if (on('mail') && !S.mailOk) rows.push(h('div', { class: 'p5-status', role: 'alert' }, h('span', 'dot-warn'),
    h('span', 'grow', h('b', null, 'Private mail needs you to sign in again.'), ' Newer private mail is missing.'),
    h('button', { class: 'btn outline sm', type: 'button', on: { click: () => { S.mailOk = true; render(); say('Signed in. Private mail is up to date.'); } } }, 'Sign in again')));
  if (on('meetings') && on('calendar')) {
    if (r.variant === 'error') rows.push(h('div', { class: 'p5-status err', role: 'alert' }, h('span', 'dot-err'),
      h('span', 'grow', h('b', null, 'The recorder on your Mac is not reachable.'), ' ' + k.t + ' started at 10:30 and is not being recorded. Open the recorder on your Mac, then try again. Everything sent before stays here; last sent ' + stamp(18, '09:46') + '.'),
      h('button', { class: 'btn primary sm', type: 'button', on: { click: () => { location.hash = '#week'; say('Recorder connected. Recording ' + k.t + ' from 10:53.'); } } }, 'Try again')));
    else rows.push(h('div', { class: 'p5-status', role: 'status' }, h('span', 'dot-work'),
      h('span', 'grow', h('b', null, 'Recording now: ' + k.t), h('span', 'wide-only', ' · 22 min · stops by itself when the call ends'), h('span', 'phone-only', ' · 22 min')),
      h('a', { class: 'btn sm ' + (r.item ? 'outline' : 'primary'), href: link(r, 'm-kickoff') }, h('span', 'wide-only', 'Open live transcript'), h('span', 'phone-only', 'Open'))));
  }
  return rows.length ? h('section', { class: 'card p5-statuses', 'aria-label': 'Needs a look' }, rows) : null;
}
function calBar(r) {
  const label = r.view === 'day' ? dow(r.day) + ' ' + r.day + ' Nov 2026' : r.view === 'month' ? 'November 2026' : '16 – 22 Nov 2026';
  const step = n => () => {
    if (r.view === 'day') location.hash = link({ view: 'day', day: Math.min(30, Math.max(1, r.day + n)) });
    else say('This draft holds only this ' + r.view + '.');
  };
  const nav = h('div', 'row',
    h('button', { class: 'btn ghost icon sm', type: 'button', 'aria-label': 'Earlier', on: { click: step(-1) } }, ic('left')),
    h('a', { class: 'btn outline sm', href: '#' + (r.view === 'day' ? 'day' : r.view) }, 'Today'),
    h('button', { class: 'btn ghost icon sm', type: 'button', 'aria-label': 'Later', on: { click: step(1) } }, ic('right')),
    h('h2', 'p5-range', label));
  const legend = h('div', { class: 'row', role: 'group', 'aria-label': 'Calendars shown' }, Object.keys(CALS).map(c => {
    const shown = !S.hideCal.has(c);
    return h('button', { class: 'chip p5-calbtn' + (shown ? '' : ' outline'), type: 'button', 'aria-pressed': String(shown), title: CALS[c].name + ' calendar (' + CALS[c].src + ')',
      on: { click: () => { shown ? S.hideCal.add(c) : S.hideCal.delete(c); render(); } } }, swatch(c), CALS[c].name, h('span', 'p5-calsrc', CALS[c].src));
  }));
  const seg = h('div', { class: 'segmented', role: 'group', 'aria-label': 'View' }, ['day', 'week', 'month'].map(v =>
    h('button', { class: 'btn', type: 'button', 'aria-pressed': String(r.view === v || (v === 'week' && r.variant === 'error')), on: { click: () => { location.hash = '#' + v; } } }, v[0].toUpperCase() + v.slice(1))));
  return h('div', 'row between p5-calbar', nav, legend, seg);
}

/* ---------- week ---------- */
function weekGrid(r) {
  const g = h('div', { class: 'p5-cal p5-week wide-only', role: 'group', 'aria-label': 'Week 16 to 22 November' });
  g.append(h('div', 'p5-corner'));
  for (let d = 16; d <= 22; d++) g.append(h('a', { class: 'p5-dayhead' + (d === TODAY ? ' today' : ''), href: '#day' + (d === TODAY ? '' : '-' + d), 'aria-label': 'Open ' + dow(d) + ' ' + d + ' November' },
    dow(d) + ' ', h('b', null, String(d)), d === TODAY ? h('span', 'chip active', 'Today') : null));
  g.append(hoursCol());
  for (let d = 16; d <= 22; d++) {
    const col = h('div', 'p5-col' + (d === TODAY ? ' today' : ''));
    visibleEvents(r, d).forEach(e => col.append(evBlock(e, r, false)));
    if (d === TODAY) {
      col.append(nowLine());
      const lane = h('div', { class: 'p5-minilane', role: 'group', 'aria-label': 'Messages and mail today' });
      laneSlots(incoming(d), 36).forEach(s => lane.append(h('a', { class: 'p5-dot' + (r.item && r.item.id === s.i.id ? ' cur' : ''), href: link(r, s.i.id), vars: { '--at': s.at },
        'aria-label': KIND_WORD[s.i.kind] + ' from ' + s.i.who + ', ' + s.i.at + ', for ' + pinLabel(s.i), title: s.i.at + ' ' + s.i.who + ': ' + s.i.subject }, ic(KIND_IC[s.i.kind]))));
      col.append(lane);
    }
    g.append(col);
  }
  return g;
}
/* ---------- phone agenda ---------- */
function agendaDay(r, d, open) {
  const evs = visibleEvents(r, d), loose = incoming(d).filter(i => !i.pin || find(i.pin).d !== d || !evs.includes(find(i.pin)));
  const rows = [];
  const list = evs.map(e => ({ at: mins(e.s), e })).concat(loose.map(i => ({ at: mins(i.at), i }))).sort((a, b) => a.at - b.at);
  list.forEach(x => {
    if (x.i) { const i = x.i; rows.push(h('a', { class: 'short-row', href: link(r, i.id) }, ic(KIND_IC[i.kind]),
      h('span', 'grow', h('span', 'short-title', i.who + ': ' + i.subject), h('span', 'short-fact', KIND_WORD[i.kind] + ' · ' + i.at + ' · for ' + pinLabel(i))))); return; }
    const e = x.e, rs = recState(e, r), a = attached(e), n = a.inc.length + a.notes.length;
    const now = d === TODAY && mins(e.s) <= NOW_MIN && NOW_MIN < mins(e.e);
    rows.push(h('a', { class: 'short-row' + (now ? ' p5-nowrow' : ''), href: link(r, e.id), 'aria-label': evLabel(e, r) }, swatch(e.cal),
      h('span', 'grow', h('span', 'short-title', e.t), h('span', 'short-fact', e.s + ' – ' + e.e + ' · ' + CALS[e.cal].name + (rs === 'done' ? ' · recorded' : rs === 'missed' ? ' · not recorded' : rs === 'live' ? ' · recording' : ''))),
      n ? h('span', 'short-side', h('span', 'chip', n + ' related')) : null));
  });
  if (!rows.length) rows.push(h('p', 'short-row meta', 'Nothing on this day.'));
  return h('section', { class: 'card', id: 'p5-day-' + d }, h('header', 'card-h', h('h2', null, dow(d) + ' ' + d + ' Nov'), d === TODAY ? h('span', 'chip active', 'Today') : null,
    open ? null : h('a', { class: 'meta', href: '#day' + (d === TODAY ? '' : '-' + d) }, 'Open day')), rows);
}
/* phone week: dates in order, opening on today; the days before today sit behind one row on top */
function agenda(r, days) {
  if (days.length === 1) return h('div', 'stack phone-only', agendaDay(r, days[0], true));
  const before = days.filter(d => d < TODAY), rest = days.filter(d => d >= TODAY);
  const count = before.reduce((n, d) => n + visibleEvents(r, d).length, 0);
  const top = S.earlier ? before.map(d => agendaDay(r, d, false)) : h('button', { class: 'btn outline', type: 'button', on: { click: () => { S.earlier = true; render(); } } },
    'Show Mon 16 and Tue 17 (' + count + ' entries)');
  return h('div', 'stack phone-only', top, rest.map(d => agendaDay(r, d, false)));
}

/* ---------- day ---------- */
function dayGrid(r) {
  const d = r.day, g = h('div', { class: 'p5-cal p5-dayg wide-only', role: 'group', 'aria-label': dow(d) + ' ' + d + ' November' });
  g.append(h('div', 'p5-corner'), h('div', 'p5-dayhead' + (d === TODAY ? ' today' : ''), dow(d) + ' ', h('b', null, String(d)), d === TODAY ? h('span', 'chip active', 'Today') : null),
    h('div', 'p5-dayhead', 'Messages and mail'));
  g.append(hoursCol());
  const col = h('div', 'p5-col' + (d === TODAY ? ' today' : ''));
  visibleEvents(r, d).forEach(e => col.append(evBlock(e, r, true)));
  if (d === TODAY) col.append(nowLine());
  const lane = h('div', 'p5-col p5-lane');
  const inc = incoming(d);
  laneSlots(inc, 32).forEach(s => lane.append(h('a', { class: 'p5-in' + (r.item && r.item.id === s.i.id ? ' cur' : ''), href: link(r, s.i.id), vars: { '--at': s.at },
    'aria-label': KIND_WORD[s.i.kind] + ' from ' + s.i.who + ', ' + s.i.at + ': ' + s.i.subject + '. Pinned to ' + pinLabel(s.i), title: s.i.subject },
    ic(KIND_IC[s.i.kind]), h('span', 'p5-in-at', s.i.at), h('b', 'truncate', s.i.who), h('span', 'p5-in-pin truncate', ic('pin'), pinLabel(s.i)))));
  if (!inc.length) lane.append(h('p', 'meta p5-lane-none', 'No messages or mail.'));
  g.append(col, lane);
  return g;
}

/* ---------- month ---------- */
function monthGrid(r) {
  const g = h('div', { class: 'p5-month wide-only', role: 'group', 'aria-label': 'November 2026' });
  DOW.forEach(n => g.append(h('div', 'p5-mhead', n)));
  for (let d = -5; d <= 36; d++) {
    const inMonth = d >= 1 && d <= 30;
    const cell = h('div', 'p5-mcell' + (inMonth ? '' : ' dim') + (d === TODAY ? ' today' : ''));
    if (!inMonth) { cell.append(h('span', 'p5-mnum', String(d < 1 ? 31 + d : d - 30))); g.append(cell); continue; }
    cell.append(h('a', { class: 'p5-mnum', href: '#day' + (d === TODAY ? '' : '-' + d), 'aria-label': 'Open ' + dow(d) + ' ' + d + ' November' }, String(d), d === TODAY ? h('span', 'chip active', 'Today') : null));
    const all = visibleEvents(r, d), main = all.filter(e => e.t !== 'Daily'), show = main.slice(0, 3);
    show.forEach(e => cell.append(h('a', { class: 'p5-mev truncate', href: link(r, e.id), 'data-cal': e.cal, 'aria-label': evLabel(e, r), title: e.t },
      recState(e, r) === 'live' ? h('span', 'dot-work') : null, e.s + ' ' + e.t)));
    if (main.length > show.length) cell.append(h('a', { class: 'meta', href: '#day' + (d === TODAY ? '' : '-' + d) }, '+' + (main.length - show.length) + ' more'));
    g.append(cell);
  }
  return g;
}
function monthMini(r) {
  const g = h('div', { class: 'p5-mini phone-only card pad', role: 'group', 'aria-label': 'November 2026' });
  DOW.forEach(n => g.append(h('div', 'p5-mhead', n[0])));
  for (let d = -5; d <= 36; d++) {
    if (d < 1 || d > 30) { g.append(h('span', 'p5-minicell dim', String(d < 1 ? 31 + d : d - 30))); continue; }
    const cals = [...new Set(visibleEvents(r, d).map(e => e.cal))], n = visibleEvents(r, d).length;
    g.append(h('a', { class: 'p5-minicell' + (d === TODAY ? ' today' : ''), href: '#day' + (d === TODAY ? '' : '-' + d), 'aria-label': dow(d) + ' ' + d + ' November, ' + n + (n === 1 ? ' entry' : ' entries') },
      String(d), h('span', 'p5-dots', cals.map(swatch))));
  }
  return g;
}

/* ---------- helper parts ---------- */
function lately(n, title) {
  const ul = h('ul', 'hist');
  LATELY.filter(l => on(l[0])).slice(0, n).forEach(l => ul.append(h('li', null, ic(l[0]),
    l[3] ? h('a', { href: '#day/' + l[3] }, l[1]) : h('span', null, l[1]), h('span', 'meta', stamp(l[2][0], l[2][1])))));
  return h('section', 'card', h('header', 'card-h', ic('helper'), h('h2', null, title || 'What helpers did with it lately')), ul,
    h('p', 'p5-use meta', 'Helpers use: ', h('code', null, 'orch personal calendar today')));
}
function hand(title) {
  return () => say('Ticket made: "' + title + '". A helper starts when you press Start on the ticket.', () => say('Ticket removed.'));
}
const mayLine = id => can(acc(id)) + '.';

/* ---------- panels ---------- */
function stepList(e, m, live) {
  const made = S.tickets.has(e.id);
  return h('div', 'p5-list', m.steps.map((s, n) => {
    const key = e.id + ':' + n, picked = !S.unchecked.has(key), who = s.who === 'Severin' ? 'you' : s.who;
    return h('label', 'list-row p5-step', made || live ? ic('tasks') : h('input', { type: 'checkbox', checked: picked, 'aria-label': 'Make this ticket', on: { change: ev2 => { ev2.target.checked ? S.unchecked.delete(key) : S.unchecked.add(key); render(); } } }),
      h('span', 'grow', h('b', null, s.text), h('span', 'meta p5-due', 'For ' + who + ' · ' + s.due)),
      made && picked ? h('span', 'chip success', 'Ticket made') : null);
  }));
}
function meetingPanel(e, r) {
  const m = MEET[e.id], rs = recState(e, r), a = attached(e), out = [];
  const people = (e.people || []).concat('you').join(', ');
  out.push(h('div', 'row', calChip(e.cal), rs === 'live' ? h('span', 'pill working', h('span', 'dot-work'), 'Recording · 22 min') : rs === 'done' ? h('span', 'pill done', UI.statusIcon('done'), 'Recorded' + (m && m.length ? ' · ' + m.length : '')) : rs === 'missed' ? h('span', 'pill failed', h('span', 'dot-err'), 'Not recorded') : null));
  out.push(h('p', 'muted', stamp(e.d, e.s) + ' – ' + e.e + (e.where ? ' · ' + e.where : '') + (e.cal === 'work' ? ' · with ' + people : '')));
  const related = () => {
    const box = h('div', 'stack');
    if (a.inc.length) box.append(h('h3', 'sec-title', 'Messages and mail for this meeting'), h('div', 'p5-list', a.inc.map(i => h('a', { class: 'list-row', href: link(r, i.id) }, ic(KIND_IC[i.kind]), h('span', 'grow truncate', i.who + ': ' + i.subject), h('span', 'meta', stamp(i.d, i.at))))));
    if (a.notes.length) box.append(h('h3', 'sec-title', 'Notes linked to it'), h('div', 'p5-list', a.notes.map(n => h('a', { class: 'list-row', href: link(r, n.id) }, ic('notes'), h('span', 'grow truncate', n.title), h('span', 'meta', stamp(n.changed[0], n.changed[1]))))));
    if (m && m.helper.length) box.append(h('h3', 'sec-title', 'What helpers did with it'), h('div', 'p5-list', m.helper.map(x => h('div', 'list-row', ic('helper'), h('span', 'grow', x[0]), h('span', 'meta', stamp(e.d, x[1]))))));
    if (!box.children.length) box.append(h('p', 'muted', 'No mail, message or note belongs to this meeting yet.'));
    return box;
  };
  if (e.cal !== 'work') {
    out.push(h('p', 'quiet-note', 'From your ' + CALS[e.cal].name.toLowerCase() + ' calendar. ' + (acc(e.cal).level === 0 ? 'Helpers cannot see it.' : can(acc(e.cal)) + ' here.') + ' ', h('a', { href: '#sources' }, 'Change')), related());
    return out;
  }
  if (!m || !rs || rs === 'missed') {
    const past = e.d < TODAY || (e.d === TODAY && mins(e.e) < NOW_MIN);
    out.push(h('div', 'row', h('button', { class: 'btn primary sm', type: 'button', on: { click: hand((past ? 'Follow up: ' : 'Prepare: ') + e.t) } }, past ? 'Give the follow-up to a helper' : 'Give the preparation to a helper')));
    if (rs === 'missed') out.push(h('p', 'quiet-note', 'The recorder was not reachable when this call started, so there is no transcript.'));
    else if (rs === 'done') out.push(h('p', 'quiet-note', 'Recorded. The transcript and summary are on this meeting; this draft shows them in full for Release 3.2: Go/No-go.'));
    else if (!past && e.where === 'Teams' && on('meetings')) out.push(h('label', 'row between quiet-note', h('span', null, 'The recorder offers to record when this call starts.'), h('input', { class: 'switch', type: 'checkbox', checked: true, 'aria-label': 'Offer to record this meeting', on: { change: x => say(x.target.checked ? 'The recorder will offer to record ' + e.t + '.' : 'The recorder will not offer to record ' + e.t + '.') } })));
    out.push(related());
    return out;
  }
  const live = rs === 'live', made = S.tickets.has(e.id);
  const count = m.steps.filter((s, n) => !S.unchecked.has(e.id + ':' + n)).length;
  const tabs = [['summary', live ? 'So far' : 'Summary'], ['transcript', live ? 'Live transcript' : 'Transcript'], ['related', 'Related']];
  const tab = tabs.some(t => t[0] === r.tab) ? r.tab : 'summary';
  out.push(h('nav', { class: 'tabs', 'aria-label': 'Parts of this meeting' }, tabs.map(t => h('a', { href: link(r, e.id, t[0]), 'aria-current': t[0] === tab ? 'page' : null }, t[1]))));
  if (tab === 'summary') {
    out.push(h('p', 'p5-prose', m.summary), h('h3', 'sec-title', live ? 'Next steps heard so far' : made ? 'Tickets made from the next steps' : 'Proposed tickets, one per next step'), stepList(e, m, live));
    if (live) out.push(h('label', 'row between p5-auto', h('span', null, 'When the call ends, propose a ticket for each next step'),
      h('input', { class: 'switch', type: 'checkbox', checked: S.autoTickets, 'aria-label': 'Propose tickets when the call ends', on: { change: x => { S.autoTickets = x.target.checked; say(S.autoTickets ? 'Tickets will be proposed when the call ends.' : 'No tickets will be proposed.'); } } })));
    else if (made) out.push(h('p', 'meta', count + (count === 1 ? ' ticket is' : ' tickets are') + ' in Tickets, under To do, in the workspace Demo. No helper has started.'),
      h('div', 'row', h('a', { class: 'btn outline sm', href: '../../board/board.html' }, 'Open them in Tickets'),
        h('button', { class: 'btn ghost sm', type: 'button', on: { click: () => { S.tickets.delete(e.id); render(); say('The ' + count + ' tickets were removed.'); } } }, 'Undo')));
    else out.push(h('p', 'meta', 'They go to Tickets, under To do, in the workspace Demo, each linked to this meeting. No helper starts until you press Start on a ticket.'),
      h('div', 'row', h('button', { class: 'btn primary sm', type: 'button', disabled: count === 0, on: { click: () => { S.tickets.add(e.id); render(); say(count + (count === 1 ? ' ticket' : ' tickets') + ' made from ' + e.t + '.', () => { S.tickets.delete(e.id); render(); }); } } },
        'Make ' + (count === m.steps.length ? 'these ' : '') + count + (count === 1 ? ' ticket' : ' tickets')),
        count === 0 ? h('span', 'meta', 'Tick at least one.') : null));
  } else if (tab === 'transcript') {
    out.push(h('div', { class: 'p5-tx', role: 'log', 'aria-label': 'Transcript' }, m.lines.map(l => h('div', 'p5-line', h('span', 'meta', l[0]), h('p', null, h('b', null, l[1] === 'Severin' ? 'You' : l[1]), ' ', l[2])))));
    out.push(h('p', 'quiet-note', live ? 'Anna Meier is speaking. New lines appear here as they are said.' : 'Speaker names come from Teams. The recording itself stays on your Mac; only the words were sent here, privately.'));
  } else out.push(related());
  if (live) out.push(h('div', 'row', h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('Recording stopped. The transcript up to 10:52 is kept.', () => say('Recording again.')) } }, 'Stop recording now')));
  out.push(h('p', 'meta', mayLine('rec')));
  return out;
}
function bubbles(i) {
  return h('div', 'msgs', i.msgs.map(m => h('div', 'msg' + (m[3] ? ' me' : ''), h('span', 'meta', (m[3] ? 'You' : m[0]) + ' · ' + m[1]), h('p', null, m[2]))));
}
function pinnedRow(i, r) {
  if (i.pin) { const e = find(i.pin); return h('p', 'p5-pinned', ic('pin'), 'Pinned to ', h('a', { href: link({ view: r.view, day: r.view === 'day' ? e.d : r.day }, e.id) }, e.t), h('span', 'meta', stamp(e.d, e.s))); }
  return h('p', 'p5-pinned', ic('pin'), 'Pinned to ' + i.person + ', who is in your 10:30 meeting');
}
function mailPanel(i, r) {
  const out = [h('p', 'muted', 'Mail · ' + i.box + ' · ' + stamp(i.d, i.at)), h('p', 'meta', 'From ' + i.who + (i.addr ? ' (' + i.addr + ')' : '')), pinnedRow(i, r)];
  out.push(h('div', 'row', h('button', { class: 'btn primary sm', type: 'button', on: { click: hand('Mail from ' + i.who + ': ' + i.subject) } }, 'Give this mail to a helper'),
    i.draft ? null : h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('A helper is drafting a reply to ' + i.who + '. You send it.') } }, 'Draft a reply')));
  out.push(h('div', 'stack', i.msgs.map(m => h('article', 'p5-mailmsg', h('span', 'meta', (m[3] ? 'You' : m[0]) + ' · ' + stamp(i.d, m[1])), h('p', 'p5-prose', m[2])))));
  if (i.draft) out.push(h('section', 'banner info', h('div', 'grow', h('h3', null, 'A helper drafted a reply. You send it.'), h('p', 'p5-prose', i.draft),
    h('div', 'row space-top', h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('The draft is open in Outlook.') } }, 'Open the draft in Outlook'),
      h('button', { class: 'btn ghost sm', type: 'button', on: { click: () => say('Draft thrown away.', () => say('Draft is back.')) } }, 'Throw away')))));
  out.push(h('p', 'meta', can(itemAcc(i)) + ' in ' + i.box + '.'));
  return out;
}
function chatPanel(i, r) {
  const out = [h('p', 'muted', KIND_WORD[i.kind] + ' · ' + (i.group ? 'group ' : 'chat with ') + i.who + ' · ' + stamp(i.d, i.at)), pinnedRow(i, r)];
  out.push(h('div', 'row', h('button', { class: 'btn primary sm', type: 'button', on: { click: hand(KIND_WORD[i.kind] + ' chat with ' + i.who + ': ' + i.subject) } }, 'Make a ticket from this chat'),
    i.kind === 'teams' && acc('teams').level === 2 ? h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('A helper is drafting a reply to ' + i.who + '. You send it.') } }, 'Draft a reply') : null));
  out.push(bubbles(i));
  out.push(h('p', 'meta', i.kind === 'wa' ? (acc('wa').level === 0 ? 'Helpers can use nothing on WhatsApp. A ticket made here hands over this one chat only.' : can(acc('wa')) + '. They never write on WhatsApp.') : can(acc('teams')) + ' in Teams.'));
  return out;
}
function notePanel(n, r) {
  const out = [h('p', 'muted', 'Note · folder "Severin" · changed ' + stamp(n.changed[0], n.changed[1]))];
  const e = find(n.pin);
  out.push(h('p', 'p5-pinned', ic('pin'), 'Shown on ', h('a', { href: link({ view: r.view, day: r.view === 'day' ? e.d : r.day }, e.id) }, e.t), h('span', 'meta', stamp(e.d, e.s))));
  out.push(h('div', 'row', h('button', { class: 'btn primary sm', type: 'button', on: { click: hand('Note: ' + n.title) } }, 'Give this note to a helper'),
    h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('The note is open in your notes app.') } }, 'Open in your notes app')));
  out.push(h('article', 'stack', n.body.map(p => h('p', 'p5-prose', p.map(x => Array.isArray(x) ? h('a', { class: 'p5-wikilink', href: link(r, x[0]) }, find(x[0]).title) : x)))));
  const rel = [...new Set(n.links.concat(n.back))];
  out.push(h('h3', 'sec-title', 'Linked notes'), h('div', 'p5-list', rel.map(id => h('a', { class: 'list-row', href: link(r, id) }, ic('notes'), h('span', 'grow truncate', find(id).title),
    h('span', 'meta', n.links.includes(id) && n.back.includes(id) ? 'links both ways' : n.links.includes(id) ? 'this note links to it' : 'links to this note')))));
  out.push(h('p', 'meta', mayLine('vault')));
  return out;
}
function panel(r) {
  const it = r.item;
  if (it.type === 'event') return { title: it.t, kids: meetingPanel(it, r) };
  if (it.type === 'note') return { title: it.title, kids: notePanel(it, r) };
  return { title: it.subject, kids: it.kind === 'mail' ? mailPanel(it, r) : chatPanel(it, r) };
}

/* ---------- sources ---------- */
function sourcesView() {
  const out = [];
  out.push(h('p', 'muted p5-prose', 'A source that is on shows in My time. Helpers get nothing from an account until you choose it here, account by account. Under each choice you see what a helper could then see.'));
  SOURCES.forEach(s => {
    const isOn = on(s.id), card = h('section', { class: 'card', id: 'src-' + s.id });
    card.append(h('header', 'card-h', ic(s.id), h('h2', null, s.name), h('span', 'muted grow', s.what),
      h('span', 'switch-text', isOn ? 'On' : 'Off'),
      h('input', { class: 'switch', type: 'checkbox', checked: isOn, 'aria-label': s.name + ' on', on: { change: () => { isOn ? S.off.add(s.id) : S.off.delete(s.id); render(); say(s.name + (isOn ? ' is off. Nothing was deleted.' : ' is on.'), () => { isOn ? S.off.delete(s.id) : S.off.add(s.id); render(); }); } } })));
    if (!isOn) { card.append(h('p', 'pad muted', 'Off. It shows nowhere and helpers cannot use it.')); out.push(card); return; }
    s.accounts.forEach(a => {
      const bad = a.id === 'pmail' && !S.mailOk;
      card.append(h('div', 'setting-row p5-acc', h('span', 'row-label', a.cal ? swatch(a.cal) : null, ' ' + a.name),
        h('div', 'row-value stack',
          h('span', 'p5-accstate', h('span', bad ? 'dot-warn' : 'dot-ok'), accState(a), a.id === 'rec' ? ' · Windows PC: recorder not installed' : null),
          bad ? h('p', { class: 'meta', role: 'alert' }, 'Mail from before is still shown; newer private mail is missing.') : null,
          h('div', 'row', h('span', 'meta', 'Helpers can use'),
            h('div', { class: 'segmented', role: 'group', 'aria-label': 'What helpers can use of ' + a.name }, a.opts.map((label, n) =>
              h('button', { class: 'btn', type: 'button', 'aria-pressed': String(a.level === n), on: { click: () => { const was = a.level; if (was === n) return; a.level = n; render(); say(a.short + ': ' + can(a).toLowerCase() + '.', () => { a.level = was; render(); }); } } }, label)))),
          h('p', 'meta p5-scope', (a.level === 0 ? 'Now: nothing. If you turn it on, helpers can see: ' : 'Helpers can see: ') + a.scope)),
        h('div', 'row-action', bad ? h('button', { class: 'btn primary sm', type: 'button', on: { click: () => { S.mailOk = true; render(); say('Signed in. Private mail is up to date.'); } } }, 'Sign in again') : null)));
    });
    if (s.id === 'meetings') card.append(h('p', 'p5-use meta', 'The words reach this workspace privately. That needs Contacts, which you turn on yourself.'));
    if (s.id === 'calendar') card.append(h('div', 'p5-use', h('button', { class: 'btn outline sm', type: 'button', on: { click: () => say('Pick the calendar to add. This draft stops here.') } }, 'Add a calendar')));
    out.push(card);
  });
  out.push(h('h2', 'p5-h', 'More to add'));
  out.push(h('div', 'grid-3', LATER.map(l => h('section', 'card pad stack', h('div', 'row', ic(l[0]), h('h3', 'grow', l[1]), h('span', 'badge', 'Later')), h('p', 'muted', l[2]),
    h('div', 'row', h('button', { class: 'btn outline sm', type: 'button', disabled: true }, 'Add ' + l[1]), h('span', 'meta', 'Not built yet.'))))));
  out.push(lately(6));
  return out;
}

/* ---------- render ---------- */
let sheet = null, sheetFor = null, closing = false;
const mqWide = window.matchMedia('(min-width: 1100px)');
function closeSheet() { if (sheet) { closing = true; sheet.close(); closing = false; sheet = null; sheetFor = null; } }
function render() {
  const r = route(), view = document.getElementById('view'), out = [];
  document.querySelectorAll('.p5-bar a').forEach(a => a.toggleAttribute('aria-current', a.getAttribute('href') === (location.hash || '#week')));
  document.querySelectorAll('.tabs [data-tab]').forEach(a => a.dataset.tab === (r.view === 'sources' ? 'sources' : 'time') ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  document.title = (r.item ? (r.item.t || r.item.title || r.item.subject) + ' · ' : r.view === 'sources' ? 'Sources · ' : '') + 'Personal · orch';
  const inline = r.item && r.view === 'day' && mqWide.matches;
  if (r.view === 'sources') out.push(sourcesView());
  else {
    out.push(strip(r, r.variant === 'empty' ? '' : 'wide-only'));
    if (r.variant === 'empty' || !on('calendar')) {
      out.push(UI.state({ kind: 'empty', title: r.variant === 'empty' ? 'Calendar is on. Nothing here yet' : 'Calendar is off',
        text: r.variant === 'empty' ? 'Your week shows here as soon as the first calendar is read. That takes about a minute.' : 'Turn Calendar on and your week shows here again.',
        action: { label: r.variant === 'empty' ? 'Choose calendars' : 'Open sources', onClick: () => { location.hash = '#sources'; } } }));
    } else {
      out.push(statusLines(r), calBar(r));
      if (r.view === 'day') {
        const p = inline ? panel(r) : null;
        out.push(h('div', 'p5-day' + (inline ? ' open' : ''), h('div', 'p5-daymain', dayGrid(r), agenda(r, [r.day])),
          inline ? h('aside', { class: 'card p5-panel', 'aria-label': p.title }, h('header', 'row between', h('h2', 'p5-ptitle', p.title),
            h('a', { class: 'btn ghost icon sm', href: link(r), 'aria-label': 'Close' }, ic('x'))), p.kids) : null));
      } else if (r.view === 'month') out.push(monthGrid(r), monthMini(r));
      else out.push(weekGrid(r), agenda(r, [16, 17, 18, 19, 20, 21, 22]));
      out.push(strip(r, 'phone-only'), lately(3));
    }
  }
  view.replaceChildren(...out.flat(3).filter(Boolean));
  if (r.item && !inline && r.view !== 'sources' && !r.variant) {
    const p = panel(r), body = h('div', 'stack p5-sheetbody', p.kids);
    if (sheet && sheet.isConnected) { sheet.querySelector('.sheet-h h2').textContent = p.title; sheet.setAttribute('aria-label', p.title); sheet.querySelector('.p5-sheetbody').replaceWith(body); }
    else {
      sheet = UI.sheet(p.title, body); sheet.classList.add('p5-sheet');
      if (sheet.querySelector('.ui-overlay-close')) { const x = sheet.querySelector('.sheet-h button'); if (x) x.remove(); }
      const me = sheet;
      me.addEventListener('close', () => { if (sheet === me) { sheet = null; sheetFor = null; if (!closing) location.hash = link(route()); } });
    }
    sheetFor = r.item.id;
  } else closeSheet();
}
window.addEventListener('hashchange', render);
mqWide.addEventListener('change', render);
document.getElementById('p5-more').addEventListener('click', e => {
  const s = document.querySelector('.sidebar'), o = s.dataset.open !== 'true';
  s.dataset.open = String(o); e.currentTarget.setAttribute('aria-expanded', String(o));
});
render();
})();
