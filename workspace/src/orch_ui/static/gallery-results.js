/* gallery.html: the result widgets section (results.js). Demo content only, nothing here is product data.
   Size and state come from the switches, or from the address for screenshots: gallery.html?rw=lg,error#result-widgets */
(() => {
  'use strict';
  const q = s => document.querySelector(s);
  const LOG = ['15:04:01 node --test tests/insights.test.js', '15:04:02 ✔ counts skills per day (41 ms)', '15:04:02 ✔ counts keys that were never used (9 ms)',
    '15:04:03 ✔ empty workspace shows zero, not an error (6 ms)', '15:04:03 ✔ week view adds up to the day view (17 ms)', '15:04:03 ℹ tests 14 · pass 14 · fail 0'].join('\n');
  const CODE = ['def keep_name(old, new):', '    # the first name stays, links keep working', '    if old.name == new.name:', '        return old.name',
    '    return unique(new.name)', '', 'def unique(name):', '    stem, ext = split(name)', '    return f"{stem}-2{ext}"'].join('\n');
  const MD = ['# Release notes, week 46', 'Two changes are ready for review. Nothing needs a decision from you.', '',
    '- Phone pages no longer scroll sideways.', '- Files and notes can be added to a ticket.', '- The Steer button is on every working ticket.', '',
    '## Known gaps', 'The usage chart is still a draft. The newsletter waits for a date.'].join('\n');
  const DATA = JSON.stringify({theme: 'dark', widths: [1280, 1920, 390], limits: {file_mb: 25, live_helpers: 6}, phone: {questions: true, until: '10:50'}}, null, 2);
  const CSV = 'Plan,Per month,Per year\nStarter,19,190\nTeam,49,490\nCompany,129,1290\nExtra seat,9,90\nNonprofit,0,0\n';
  const S = 'samples/';
  const ITEMS = [
    {type: 'md', name: 'release-notes.md', meta: 'Document · 9 lines', text: MD, download: S + 'sample-notes.md'},
    {type: 'text', name: 'test-run.log', meta: 'Log · 6 lines', text: LOG, download: S + 'sample-message.txt'},
    {type: 'code', name: 'attach.py', meta: 'Code · 9 lines', text: CODE},
    {type: 'data', name: 'settings.json', meta: 'Data · 4 keys', text: DATA, download: S + 'sample-hours.json'},
    {type: 'table', name: 'price-list.csv', meta: 'Table · 3 columns · 6 rows', text: CSV, numeric: [1, 2], download: S + 'sample-responses.csv'},
    {type: 'page', name: 'phone-widths.html', meta: 'Web page', src: S + 'sample-page.html', href: S + 'sample-page.html'},
    {type: 'pdf', name: 'offer-acme.pdf', meta: 'PDF · 1 page', pages: 1, src: S + 'sample-summary.pdf', href: S + 'sample-summary.pdf', download: S + 'sample-summary.pdf'},
    {type: 'picture', name: 'invoices-october.svg', meta: 'Picture · 680 × 380', width: 680, height: 380, src: S + 'sample-poster.svg', alt: 'October invoices with the Export CSV button', href: S + 'sample-poster.svg', download: S + 'sample-poster.svg'},
    {type: 'video', name: 'walkthrough.webm', meta: 'Video · 0:02', duration: '0:02', src: S + 'sample-clip.webm', poster: S + 'sample-poster.svg', download: S + 'sample-clip.webm'},
    {type: 'audio', name: 'voice-note.wav', meta: 'Audio · 0:01', duration: '0:01', src: S + 'sample-tone.wav', transcript: 'Please keep the old file name, and add a note for the support team.', download: S + 'sample-tone.wav'},
    {type: 'chart', name: 'Uses by day', meta: 'Chart · 7 days', labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], values: [41, 56, 38, 72, 88, 12, 9], labelName: 'Day', unit: 'Uses'},
    {type: 'change', name: 'Phone width fix', meta: 'Change · 4 files', checks: '3 of 12 green',
      files: [['dashboard/static/home.css', 48, 12], ['dashboard/static/shell.css', 31, 9], ['dashboard/pages/home.js', 22, 14], ['tests/test_phone_width.py', 23, 3]],
      diff: '@@ home.css @@\n- .home { min-width: 480px; }\n+ .home { min-width: 0; }\n+ .home .card { overflow-wrap: anywhere; }'},
    {type: 'pr', name: 'Pull request 1318', meta: 'Pull request · draft', status: 'draft', title: 'Phone pages no longer scroll sideways', href: '#result-widgets',
      checks: [{name: 'Tests on Linux', state: 'pass'}, {name: 'Tests on Windows', state: 'pass'}, {name: 'Tests on macOS', state: 'pass'}, {name: 'Page check', state: 'run'}, {name: 'Word check', state: 'fail'}]},
    {type: 'pr', name: 'Pull request 1322', meta: 'Pull request · conflict', status: 'conflict', title: 'Home shows one question card', href: '#result-widgets'},
    {type: 'archive', name: 'export-november.zip', meta: 'Archive · 14 files', total: 14, download: S + 'sample-print.zip',
      files: [['tickets.csv', '48 KB'], ['files/home-390.png', '212 KB'], ['files/offer-acme.pdf', '1.1 MB'], ['files/release-notes.md', '3 KB']]},
    {type: 'link', name: 'Notes on phone widths', meta: 'wiki.example.com', href: 'https://wiki.example.com/phone-widths'},
    {type: 'file', name: 'layout-v3.sketch', meta: 'File · 4.2 MB', size: 4404019, download: S + 'sample-print.zip'}
  ];
  const STATES = ['ready', 'empty', 'loading', 'error', 'large'];
  // too big: the text kinds keep a first part to show; the rest shows the sentence only
  const bigItem = it => Object.assign({}, it, {shown: 3, state: 'large'});
  const emptyItem = it => Object.assign({}, it, {text: '', rows: undefined, values: [], files: [], checks: it.type === 'pr' ? [] : it.checks, href: it.type === 'link' ? '' : it.href, state: 'empty'});
  function shape(it, state) { return state === 'large' ? bigItem(it) : state === 'empty' ? emptyItem(it) : Object.assign({}, it, {state}); }

  function render(size, state) {
    const host = q('#rw-grid'); if (!host || !window.UI || !UI.result) return;
    host.className = 'result-grid' + (size === 'lg' ? ' big' : '');
    const list = ITEMS.map(it => shape(it, state));
    host.replaceChildren(...list.map((it, i) => UI.result(it, {size, list, index: i, onRetry: () => UI.toast?.('Trying again (demo).')})));
    const say = q('#rw-say'); if (say) say.textContent = '16 widgets · ' + (size === 'lg' ? 'big' : 'small') + ' · ' + {ready: 'loaded', empty: 'empty', loading: 'loading', error: 'error', large: 'too big'}[state];
  }
  function strip() {
    const host = q('#rw-states'); if (!host) return;
    ['table', 'picture', 'pr'].forEach(type => {
      const it = ITEMS.find(x => x.type === type), row = document.createElement('div'); row.className = 'result-grid';
      STATES.forEach(st => row.append(UI.result(shape(it, st), {size: 'sm'})));
      host.append(row);
    });
  }
  function start() {
    if (!q('#rw-grid')) return;
    const p = (new URLSearchParams(location.search).get('rw') || '').split(',');
    let size = p.includes('lg') ? 'lg' : 'sm', state = STATES.find(s => p.includes(s)) || 'ready';
    document.querySelectorAll('input[name=rw-size]').forEach(r => { r.checked = r.value === size; r.addEventListener('change', () => { size = r.value; render(size, state); }); });
    document.querySelectorAll('input[name=rw-state]').forEach(r => { r.checked = r.value === state; r.addEventListener('change', () => { state = r.value; render(size, state); }); });
    render(size, state); strip();
    q('#rw-open')?.addEventListener('click', () => UI.resultOverlay(ITEMS, 0));
    q('#rw-open-loading')?.addEventListener('click', () => UI.resultOverlay([Object.assign({}, ITEMS[4], {state: 'loading'})], 0));
    q('#rw-open-error')?.addEventListener('click', () => UI.resultOverlay([Object.assign({}, ITEMS[6], {state: 'error'})], 0, {onRetry: () => UI.toast?.('Trying again (demo).')}));
    q('#rw-open-large')?.addEventListener('click', () => UI.resultOverlay([bigItem(ITEMS[1]), bigItem(ITEMS[8])], 0));
    const ov = new URLSearchParams(location.search).get('rwov');
    if (ov !== null) UI.resultOverlay(ITEMS, Number(ov) || 0);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
