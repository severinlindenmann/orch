'use strict';
// These three icons are in the look catalog but not the shell's iconEl registry.
function ticketGlyph(kind) {
  if (!['robot', 'phone', 'flame'].includes(kind)) return iconEl(kind);
  const paths = {
    robot:'<path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2m16 0h2M9 13v2m6-2v2"/>',
    phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    flame:'<path d="M12 3c1 6 7 7 7 12a7 7 0 0 1-14 0c0-2 1-4 3-6 0 4 5 4 4-6Z"/>'
  };
  const node = h('span', {className:'ic-wrap', 'aria-hidden':'true'});
  node.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths[kind] + '</svg>'; // ic-wrap: static icon paths only
  return node;
}

// Ticket page: links, fields, agent bar, artifacts, tasks, phone texts, inline fields, questions.
// Tick a task on or off by hand (orch check done / reopen). A task with proof from an agent can be opened again.
async function toggleTask(id, cid) {
  const t = ticketOf(id), task = array(t?.checklist).find(c => c.id === cid), lock = 'task-' + id + '-' + cid;
  if (!task || locks.has(lock)) return;
  locks.add(lock);
  const result = task.wont_do ? await act('check.reopen', {ticket:t.id, check:cid}) : await act('check.set', {ticket:t.id, check:cid, done:!window.DashHelpers.resolved(task)});
  locks.delete(lock);
  render();
  if (!result.ok) window.orch.toast(result.text, 'error');
}
function localUrl(value) {
  if (typeof value !== 'string' || !/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/.test(value)) return null;
  try { return new URL(value).href; } catch (_) { return null; }
}
// An add-on that declares a [page] opens inside this app at #addon/<add-on>/<path> (old #open/ links forward); the server shows it under /addon/<add-on>/.
const pageHash = (addon, path) => '#addon/' + encodeURIComponent(addon) + (String(path).replace(/^\/+/, '') ? '/' + String(path).replace(/^\/+/, '') : '');
function addonUrl(addon) {
  return array(state.services).filter(s => s.addon === addon && s.running === true).map(s => localUrl(s.url)).find(Boolean) || null;
}
function addonLink(addon, path, label, startLabel = addon) {
  if (!/^[a-z][a-z0-9-]{1,31}$/.test(addon) || typeof path !== 'string' || !/^[A-Za-z0-9_./-]*$/.test(path) || path.includes('..')) return null;
  // the live-session add-on's page is drawn by this dashboard (the live page): it has no server of its own to wait for
  const base = addonUrl(addon) || addons().some(a => a.name === addon && a.page?.live_session === true);
  return base ? h('a', {className:'chip outline', href: pageHash(addon, path)}, label)
    : snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-action':'start'}, 'Start ' + startLabel);
}
function ticketLinks(t) {
  const links = array(t.refs).map(link => {
    const url = link.url;
    if (typeof url !== 'string') return null;
    const addon = /^addon:([a-z][a-z0-9-]{1,31})\/([A-Za-z0-9_./-]*)$/.exec(url);
    if (addon) return addonLink(addon[1], addon[2], clean(link.title) || addon[1]);
    if (/^t_[A-Za-z0-9]+$/.test(url)) {
      const target = ticketOf(url);
      return target ? h('a', {className:'chip outline', href:href(url)}, clean(target.title)) : null;
    }
    if (link.view) return null;  // web references are in the References card
    if (!/^https:\/\/[^\s<>"'`]+$/.test(url)) return null;
    try { const parsed = new URL(url); return h('a', {className:'chip outline', href:parsed.href, target:'_blank', rel:'noopener noreferrer'}, clean(link.title) || parsed.host); } catch (_) { return null; }
  }).filter(Boolean);
  return links.length ? h('div', {className:'chips', 'data-key':'ticket-links'}, links) : null;
}
function addonValue(row, value) {
  if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
  if (row.format === 'time') return time(value) || date(value);  // the stamp says the day already ("today 18:38")
  if (row.format === 'cron-human') return window.DashHelpers.cronHuman(value);
  if (row.format === 'yes-no') return value === true ? 'Yes' : value === false ? 'No' : '';
  if (row.format === 'chips') return h('div', {className:'chips'}, array(value).map(v => chip(clean(v))));
  return typeof value === 'object' ? '' : clean(value);
}
// Add-on rows of a ticket. Links ("open-page") stay under the story; plain values (Repeats) go into Properties.
function addonViewRows(ticket, links) {
  return addons().flatMap(a => array(a.ticket_view).map(r => [r, (ticket.ext || {})[a.name], a.name]))
    .filter(([r]) => (r.format === 'open-page') === links)
    .map(([r, ext, addon]) => [r, ext && typeof ext === 'object' ? (r.format === 'open-page' ? addonLink(addon, ext[r.field], r.label, r.label) : addonValue(r, ext[r.field])) : '', addon]).filter(([, v]) => v);
}
function addonRows(ticket) {
  const rows = addonViewRows(ticket, true);
  return rows.length ? h('dl', {className:'addon-rows'}, rows.map(([, v]) => h('dd', {className:'addon-page'}, v))) : null;
}
// A value in Properties from an add-on (Repeats): plain text, a small pencil when it can be changed.
function addonPropertyRows(t) {
  return addonViewRows(t, false).map(([r, v, addon]) => {
    const editable = !snapshot && addon === repeatsAddon();
    const value = editable ? ticketButton([v, iconEl('pencil')], 'ed ed-plain', () => repeatsDialog(t.id, addon), {title:'Click to change', 'data-key':'property-' + addon + '-' + r.field}) : v;
    return h('div', {}, h('dt', {}, r.label), h('dd', {}, value));
  });
}
// ---- Ticket links and add-on fields. Each web link carries `view` from the core's one link module (orch/refs.py):
// label, icon key, monogram, title, status (only while its add-on is on) and the Artifacts group. Fields come typed
// from `orch addon list` (ticket_fields) and are saved with `orch ticket set` (op ticket.field).
const KEY = /^[a-z0-9][a-z0-9-]{0,31}$/;
const safeHref = url => { try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? u.href : null; } catch (_) { return null; } };
const webLinks = t => array(t.refs).filter(l => l && typeof l.url === 'string' && /^https?:\/\/[^\s<>"'`]+$/i.test(l.url) && l.view && typeof l.view === 'object' && safeHref(l.url));
function linkTile(v, size = '') {
  const key = KEY.test(String(v.icon)) ? v.icon : 'link';
  const node = h('span', {className:'li h-' + key + (size ? ' ' + size : ''), 'aria-hidden':'true'});
  if (v.mono && key !== 'link') node.textContent = String(v.mono).slice(0, 3); else node.append(iconEl('link'));
  return node;
}
const linkStatus = status => typeof status === 'string' && KEY.test(status.replace(/ /g, '-')) ? h('span', {className:'st st-' + status.replace(/ /g, '-')}, status) : null;
// what a link row says it is comes from the server (data.shown_type / host_parts): an allowlisted type, the
// registrable domain (never cut, its own style) and the rest of the host before it (cut from the head)
const oneLine = (text, max) => String(text ?? '').replace(/\p{Cf}/gu, '').replace(/[\p{Cc}\u2028\u2029]/gu, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
const linkType = v => typeof v.shown_type === 'string' && v.shown_type ? v.shown_type : 'Link';
const linkHost = v => (typeof v.host_head === 'string' ? v.host_head : '') + (typeof v.domain === 'string' ? v.domain : '');
// the browser's own reading of the address must give the same host; if not, it is a plain Link with the browser's host
const browserHost = url => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch (_) { return ''; } };
const linkSub = (v, url) => {
  const bh = browserHost(url);
  if (bh !== linkHost(v)) return h('span', {className:'lk-sub'}, h('span', {className:'lk-type'}, 'Link ·\u00a0'), h('span', {className:'lk-dom'}, bh));
  return h('span', {className:'lk-sub'}, h('span', {className:'lk-type'}, linkType(v) + ' ·\u00a0'),
    v.host_head ? h('span', {className:'lk-head'}, '\u200E' + String(v.host_head) + '\u200E') : null, h('span', {className:'lk-dom'}, String(v.domain || '')));
};
const ART_WORD = {html:'Page', pr:'Pull request', commit:'Commit'};
// what the phone calls this link (Page, Pull request, Commit) with its id and revision on hover
const artMark = (t, url) => { const a = t.art?.[url]; return a && ART_WORD[a.kind] ? h('span', {className:'chip art-kind', title:clean(a.id + (a.rev ? ' · ' + a.rev : ''))}, ART_WORD[a.kind]) : null; };
function linkRow(t, link, removable) {
  if (['ticket', 'artifact', 'file'].includes(link.kind)) return referenceRow(t, link, removable);
  const v = link.view, url = safeHref(link.url);
  return h('div', {className:'lk-row', 'data-key':'link-' + link.url},
    h('a', {className:'lk', href:url, target:'_blank', rel:'noopener noreferrer', title:url}, linkTile(v), h('span', {className:'t'}, h('b', {}, oneLine(clean(v.title), 200)), linkSub(v, url)), linkStatus(v.status), artMark(t, link.url), h('span', {className:'ext'}, iconEl('external'))),
    removable && !snapshot ? h('button', {type:'button', className:'btn ghost icon xs lk-x', title:'Remove this reference', 'aria-label':'Remove reference ' + clean(v.title), 'data-action':'link-remove', 'data-ticket':t.id, 'data-n':link.n || array(t.refs).indexOf(link) + 1}, iconEl('x')) : null);
}
// add-ons that are on, have a refresh act and own a link on this ticket
const refreshers = t => addons().filter(a => array(a.acts).includes('refresh') && webLinks(t).some(l => l.view.addon === a.name));
// ---- References as the master dense list (.ref-list, one 32 px row per link): tool mark, key + title, state.
const REF_ICONS = ['github', 'gitlab', 'jira'];
const REF_DONE = ['done', 'closed', 'merged'], REF_ACTIVE = ['in progress', 'in review', 'review', 'active'];
const sentence = word => { const w = oneLine(word, 40); return w ? w.charAt(0).toUpperCase() + w.slice(1) : ''; };
// "#812" from an issue or pull request address, "BILL-207" from a Jira address, else nothing
function refKey(url) {
  try {
    const path = new URL(url).pathname;
    const n = /\/(?:issues|pull|pulls|merge_requests)\/(\d+)/.exec(path), j = /\/browse\/([A-Za-z][A-Za-z0-9]*-\d+)/.exec(path);
    return n ? '#' + n[1] : j ? j[1] : '';
  } catch (_) { return ''; }
}
// 0 issue, 1 pull request or Jira issue, 2 ticket, 3 anything else (plain links, files, results)
function refGroup(link) {
  if (link.kind === 'ticket') return 2;
  if (!link.view || typeof link.url !== 'string') return 3;
  const path = (() => { try { return new URL(link.url).pathname; } catch (_) { return ''; } })();
  if (/\/(?:pull|pulls|merge_requests)\/\d+/.test(path)) return 1;
  if (/\/browse\/[A-Za-z][A-Za-z0-9]*-\d+/.test(path)) return 1;  // a Jira issue sits with the pull requests, in the order added
  return refKey(link.url) ? 0 : 3;
}
const refTone = word => REF_DONE.includes(String(word).toLowerCase()) ? 'done' : REF_ACTIVE.includes(String(word).toLowerCase()) ? 'active' : String(word).toLowerCase() === 'not found' ? 'bad' : '';
function refMark(link, v) {
  const name = link.kind === 'ticket' ? 'ticket' : REF_ICONS.includes(v?.icon) ? v.icon : 'link';
  return iconEl(name);
}
function refModel(t, link) {
  const v = link.view || {}, other = link.kind === 'ticket' ? ticketOf(link.ticket) : null;
  let tool, key = '', title, state = '';
  if (link.kind === 'ticket') {
    tool = 'Ticket'; key = clean(other?.key || ''); title = clean(other?.title) || 'Ticket unavailable'; state = other ? statusWord(other) : 'Unavailable';
  } else if (link.kind === 'artifact' || link.kind === 'file') {
    tool = link.kind === 'artifact' ? 'Result' : 'File'; title = link.name || (link.path + (link.line ? ':' + link.line : ''));
  } else {
    key = refKey(link.url); title = oneLine(clean(v.title), 200) || oneLine(link.url, 200); state = sentence(v.status);
    const group = refGroup(link), site = clean(v.label || v.type || 'Link');
    tool = group === 1 ? site + ' pull request' : group === 0 && /^(GitHub|GitLab)$/.test(site) ? site + ' issue' : site;
  }
  const text = [tool, [key, title].filter(Boolean).join(' '), state].filter(Boolean).join(' · ');
  return {tool, key, title, state, text, tone: refTone(state)};
}
function refRow(t, link, sep) {
  const m = refModel(t, link), n = link.n || array(t.refs).indexOf(link) + 1;
  const attrs = {className:'ref-row', title:m.text, 'aria-label':m.text};
  let tag = 'span';
  if (link.kind === 'ticket') { const other = ticketOf(link.ticket); if (other) { tag = 'a'; attrs.href = href(other.id); } }
  else if (link.kind === 'artifact' || link.kind === 'file') {
    if (!snapshot && !link.local) { tag = 'button'; Object.assign(attrs, {type:'button', 'data-action':link.kind === 'artifact' ? 'file-preview' : 'ref-preview', 'data-ticket':link.kind === 'artifact' ? link.ticket : t.id, 'data-kind':'artifacts', 'data-name':link.name, 'data-n':n}); }
  } else { const url = safeHref(link.url); if (url) Object.assign(attrs, {href:url, target:'_blank', rel:'noopener noreferrer'}), tag = 'a'; }
  const row = h(tag, attrs, refMark(link, link.view), m.key ? h('span', {className:'ref-key'}, m.key) : null, h('span', {className:'ref-text'}, m.title), h('span', {className:'ref-state' + (m.tone ? ' ' + m.tone : '')}, m.state));
  const x = snapshot ? null : h('button', {type:'button', className:'ref-x', title:'Remove this reference', 'aria-label':'Remove reference ' + m.title, 'data-action':'link-remove', 'data-ticket':t.id, 'data-n':n}, iconEl('x'));
  return h('li', {className:sep ? 'ref-sep' : '', 'data-key':'ref-' + n}, row, x);
}
function refRows(t) {
  const rows = referenceRows(t).map(l => [refGroup(l), l]).sort((a, b) => a[0] - b[0]);
  return rows.map(([g, l], i) => refRow(t, l, g === 3 && i > 0 && rows[0][0] < 3 && rows[i - 1][0] < 3));
}
function linksCard(t) {
  const rows = referenceRows(t);
  if (!rows.length && !adding(t, 'links')) return null;
  const refresh = snapshot ? [] : refreshers(t);
  return h('section', {className:'links-card', 'data-key':'links-card'},
    h('h2', {className:'ref-head'}, 'References', rows.length ? h('span', {}, '· ' + rows.length) : null,
      refresh.map(a => h('button', {type:'button', className:'btn ghost xs', title:'Update titles and state (' + addonLabel(a) + ')', 'data-action':'link-refresh', 'data-addon':a.name, 'data-ticket':t.id, 'data-key':'link-refresh-' + a.name}, iconEl('refresh'), refresh.length > 1 ? addonLabel(a) : 'Refresh'))),
    h('ul', {className:'ref-list'}, refRows(t),
      snapshot ? null : h('li', {'data-key':'add-link-' + t.id}, h('button', {type:'button', className:'ref-row ref-add', 'data-action':'link-add', 'data-ticket':t.id}, iconEl('plus'), h('span', {className:'ref-text'}, 'Add reference')))));
}
function referenceRow(t, ref, removable) {
  const other = ticketOf(ref.ticket), n = ref.n || array(t.refs).indexOf(ref) + 1;
  const title = ref.kind === 'ticket' ? clean(other?.title) || 'Ticket unavailable' : ref.name || (ref.path + (ref.line ? ':' + ref.line : ''));
  const sub = ref.local ? 'On this computer only' : ref.kind === 'ticket' ? 'Ticket · ' + (other ? statusWord(other) : 'Unavailable') : ref.kind === 'artifact' ? 'Result' + (other ? ' · ' + clean(other.title) : '') : 'File in this project';
  const attrs = {className:'lk'};
  let tag = 'span';
  if (ref.kind === 'ticket' && other) { tag = 'a'; attrs.href = href(other.id); }
  else if (!snapshot && !ref.local) {
    tag = 'button'; Object.assign(attrs, {type:'button', 'data-action':ref.kind === 'artifact' ? 'file-preview' : 'ref-preview', 'data-ticket':ref.kind === 'artifact' ? ref.ticket : t.id, 'data-kind':'artifacts', 'data-name':ref.name, 'data-n':n});
  }
  return h('div', {className:'lk-row'}, h(tag, attrs, iconEl(ref.kind === 'ticket' ? 'ticket' : 'file'), h('span', {className:'t'}, h('b', {}, title), h('span', {className:'lk-sub'}, sub))),
    removable && !snapshot ? h('button', {type:'button', className:'btn ghost xs', 'data-action':'link-remove', 'data-ticket':t.id, 'data-n':n, 'aria-label':'Remove reference'}, '×') : null);
}
async function startLinkAdd(control) {
  const t = ticketOf(control.dataset.ticket);
  if (!t) return;
  const {d, actions} = dialog('Add reference', 'dialog');
  const tabs = el('div', 'tabs'), body = el('div', 'stack'), err = el('p', 'bad');
  let target = '', mode = 'Ticket';
  const draw = async label => {
    mode = label; target = ''; addBtn.disabled = true; body.replaceChildren();
    tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', b.textContent === mode));
    if (label === 'Result') {
      const select = el('select', 'input'); select.setAttribute('aria-label', 'Result');
      body.append(select);
      try {
        const r = await fetch('/api/artifacts/' + encodeURIComponent(t.id));
        const data = await r.json();
        if (mode !== label) return;
        select.append(new Option('Choose a result', ''));
        array(data.files).forEach(f => select.append(new Option(f.name, 'artifact:' + f.name)));
        select.onchange = () => { target = select.value; addBtn.disabled = !target; };
      } catch (_) { err.textContent = 'The results could not be loaded.'; }
      return;
    }
    const input = el('input', 'input'); input.maxLength = 2000;
    input.placeholder = label === 'Ticket' ? 'Search tickets by number or title' : label === 'File' ? 'Project-relative path' : 'https://…';
    input.setAttribute('aria-label', label);
    const bar = el('div', 'ref-bar'); bar.append(input); body.append(bar);
    if (label === 'Ticket') {
      const results = el('div', 'ref-picks'), count = el('span', 'meta'); body.append(results);
      const pick = (x, row) => { target = x.id; results.querySelectorAll('.ref-pick').forEach(b => b.setAttribute('aria-pressed', String(b === row))); addBtn.disabled = false; };
      const search = () => {
        const found = tickets().filter(x => x.id !== t.id && ((x.key || '') + ' ' + x.title).toLowerCase().includes(input.value.toLowerCase()));
        count.textContent = found.length + (found.length === 1 ? ' ticket' : ' tickets');
        results.replaceChildren(...found.slice(0, 20).map(x => {
          const row = el('button', 'ref-pick'); row.type = 'button'; row.setAttribute('aria-pressed', String(x.id === target));
          const dot = el('span', 'dot ' + (x.status === 'active' ? 'working' : x.status === 'waiting' ? 'needs' : x.status === 'done' ? 'ok' : '')); dot.title = statusWord(x);
          row.append(el('span', 'mono key', x.key || ''), el('span', 'ref-title', clean(x.title)), dot);
          row.onclick = () => pick(x, row);
          return row;
        }));
      };
      input.oninput = () => { target = ''; addBtn.disabled = true; search(); }; search();
      bar.append(count);
    } else input.oninput = () => { target = input.value.trim(); addBtn.disabled = !target; };
    input.focus();
  };
  tabs.setAttribute('role', 'tablist'); tabs.classList.add('ref-tabs');
  ['Ticket', 'Web address', 'File', 'Result'].forEach(label => { const tab = button(label, 'ghost', () => draw(label)); tab.setAttribute('role', 'tab'); tabs.append(tab); });
  const addBtn = button('Add', 'primary', async () => {
    if (!target) { err.textContent = 'Choose a reference first.'; return; }
    const result = await act('ref.add', {ticket:t.id, target});
    if (!result.ok) { err.textContent = result.text; return; }
    window.orch.close(d);
  });
  addBtn.disabled = true; actions.append(addBtn);
  d.append(tabs, body, err, actions); window.orch.open(d); draw('Ticket');
}
async function removeLink(control) {
  control.disabled = true;
  const result = await act('ref.rm', {ticket:control.dataset.ticket, n:Number(control.dataset.n)});
  if (!result.ok) { control.disabled = false; window.orch.toast(result.text, 'error'); }
}
async function previewReference(control) {
  if (snapshot) return;
  const {d, actions} = dialog('File', 'sheet');
  actions.firstChild.textContent = 'Close';
  const stage = el('div', 'preview-stage'); d.append(stage, actions); window.orch.open(d);
  const url = '/api/ref-file?ticket=' + encodeURIComponent(control.dataset.ticket) + '&n=' + control.dataset.n;
  try {
    const r = await fetch(url);
    if (!r.ok) { stage.textContent = await r.text(); return; }
    if ((r.headers.get('Content-Type') || '').startsWith('image/')) { const img = el('img'); img.src = url; img.alt = 'Reference'; stage.append(img); }
    else { const pre = el('pre'); pre.textContent = await r.text(); stage.append(pre); }
  } catch (_) { stage.textContent = 'This file could not be loaded.'; }
}
async function refreshLinks(control) {
  const lock = 'link-refresh-' + control.dataset.ticket;
  if (locks.has(lock)) return;
  locks.add(lock); control.disabled = true; control.classList.add('busy');
  const result = await act('addon.act', {addon:control.dataset.addon, verb:'refresh', target:control.dataset.ticket});
  locks.delete(lock); control.disabled = false; control.classList.remove('busy');
  if (!result.ok) { window.orch.toast(result.text || 'That did not work.', 'error'); return; }
  const r = result.state?.act_result, t = ticketOf(control.dataset.ticket);
  const key = typeof t?.key === 'string' ? t.key + ': ' : '';
  window.orch.toast(key + (clean(r?.say) || (r?.changes ? r.changes + (r.changes === 1 ? ' change' : ' changes') : 'Nothing to update.')), 'ok');
  render();
}
const fieldText = (f, value) => {
  if (value == null || value === '') return '';
  if (f.type === 'choice') return clean(array(f.options).find(o => o.value === value)?.label ?? value);
  if (f.type === 'date') return date(value) || clean(value);
  if (f.type === 'number' && typeof value === 'number') return value.toLocaleString('de-CH');
  return typeof value === 'object' ? '' : clean(value);
};
function fieldSections(t) {
  return addons().filter(a => a.ticket_fields && array(a.ticket_fields.fields).some(f => !f.hidden) && (addonUsed(t, a) || adding(t, 'addon:' + a.name))).map(a => {
    const tf = a.ticket_fields, ext = (t.ext || {})[a.name] || {};
    // a read-only field (filled in by the add-on) shows once it holds something; an editable one always, to change it
    const rows = array(tf.fields).filter(f => !f.hidden && (!f.read_only || fieldText(f, ext[f.key]) !== '')).map(f => {
      const shown = fieldText(f, ext[f.key]);
      let value;
      if (f.read_only || snapshot) value = h('span', {className:'ed-ro' + (shown ? '' : ' empty-v'), title:f.read_only ? 'Filled in by the ' + addonLabel(a) + ' add-on' : null}, f.read_only && f.key && ext[f.key] && KEY.test(String(ext[f.key])) ? linkStatus(String(ext[f.key])) : shown || '—');
      else {
        const node = h('button', {type:'button', className:'ed ed-plain' + (shown ? '' : ' empty-v'), title:'Click to change', 'data-action':'field', 'data-ticket':t.id, 'data-addon':a.name, 'data-field':f.key}, shown || 'Add', shown ? iconEl('pencil') : null);
        value = h('span', {className:'inline-host', 'data-key':'field-' + a.name + '-' + f.key + '-' + t.id}, node);
      }
      return h('div', {}, h('dt', {}, clean(f.title)), h('dd', {}, value));
    });
    return h('section', {className:'rail-group addon-fields', 'data-key':'fields-' + a.name},
      h('div', {className:'rail-sheet-h'}, h('h2', {}, clean(tf.section)), h('span', {className:'addon-pill'}, 'add-on')),
      h('dl', {className:'ticket-details ed-list'}, rows));
  });
}
async function saveAddonField(t, addon, field, value) {
  const result = await act('ticket.field', {ticket:t.id, addon, field, value:String(value), if_revision:(ticketOf(t.id) || t).revision});
  if (!result.ok) window.orch.toast(changeError(result), 'error');
}
function startAddonField(control) {
  const t = ticketOf(control.dataset.ticket), host = control.parentElement;
  const a = addons().find(x => x.name === control.dataset.addon), f = array(a?.ticket_fields?.fields).find(x => x.key === control.dataset.field);
  if (!t || !host || !f || locks.has(host.dataset.key)) return;
  const key = host.dataset.key, before = (t.ext || {})[a.name]?.[f.key];
  const beforeText = before == null ? '' : String(before);
  locks.add(key);
  const end = async value => { if (value !== null && value !== beforeText) await saveAddonField(t, a.name, f.key, value); locks.delete(key); render(); };
  if (f.type === 'date') { pickDate(control, beforeText, end); return; }
  if (f.type === 'choice') {
    const pop = h('div', {className:'menu-pop sel-pop', role:'menu'}, array(f.options).map(o => h('button', {type:'button', className:'menu-item' + (o.value === before ? ' sel' : ''), role:'menuitemradio', 'aria-checked':o.value === before, 'data-value':o.value}, clean(o.label))),
      before != null ? h('button', {type:'button', className:'menu-item muted', role:'menuitem', 'data-value':''}, 'Clear') : null);
    let closed = false;
    const close = value => { if (closed) return; closed = true; document.removeEventListener('mousedown', outside, true); document.removeEventListener('keydown', esc, true); pop.remove(); end(value); };
    const outside = event => { if (!pop.contains(event.target)) close(null); };
    const esc = event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(null); } };
    pop.addEventListener('click', event => { const b = event.target.closest('[data-value]'); if (b) close(b.dataset.value); });
    document.addEventListener('mousedown', outside, true); document.addEventListener('keydown', esc, true);
    const r = control.getBoundingClientRect();  // on the page, not inside the card (a card clips what sticks out)
    pop.style.setProperty('top', Math.round(r.bottom + 4) + 'px');
    pop.style.setProperty('left', Math.round(Math.min(r.left, window.innerWidth - 196)) + 'px');
    document.body.append(pop);
    pop.querySelector('button')?.focus();
    return;
  }
  const input = el('input', 'input inline-input');
  input.type = f.type === 'number' ? 'text' : f.type === 'url' ? 'url' : 'text';
  if (f.type === 'number') input.inputMode = 'decimal';
  input.value = beforeText;
  input.setAttribute('aria-label', f.title);
  host.replaceChildren(input, el('span', 'hint', 'Enter saves · Esc cancels'));
  input.focus();
  let done = false;
  const finish = save => { if (done) return; done = true; end(save ? input.value.trim() : null); };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); finish(true); }
    else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}
// board card: up to 2 link tiles (add-on status as a chip), "+N", and the add-on fields listed in show_on_card
function cardLinks(t) {
  const rows = referenceRows(t);
  const shown = rows.slice(0, 2);
  const chips = addons().flatMap(a => array(a.ticket_fields?.show_on_card).map(k => {
    const f = array(a.ticket_fields.fields).find(x => x.key === k), v = (t.ext || {})[a.name]?.[k];
    if (!f || v == null || v === '') return null;
    return f.read_only && KEY.test(String(v)) ? linkStatus(String(v)) : h('span', {className:'st'}, f.type === 'date' ? date(v) : fieldText(f, v));
  })).filter(Boolean);
  if (!shown.length && !chips.length) return null;
  return h('div', {className:'card-links', 'data-key':'card-links'}, shown.map(l => ['ticket', 'artifact', 'file'].includes(l.kind) ? referenceRow(t, l, false) : h('a', {className:'lnk', href:safeHref(l.url), target:'_blank', rel:'noopener noreferrer', title:browserHost(l.url)}, linkTile(l.view, 'sm'), clean(l.view.title), linkStatus(l.view.status))),
    rows.length > 2 ? h('span', {className:'more'}, '+' + (rows.length - 2)) : null, chips.length ? h('span', {className:'gap'}) : null, chips);
}
function liveLinkFor(t) {
  // the add-on whose page shows the live sessions (manifest [page] live_session): this dashboard draws it (the live page), and
  // its address for one ticket opens that ticket's session in the layer (pages/live.js)
  const a = addons().find(a => a.page?.live_session === true);
  const id = typeof t.id === 'string' && /^[A-Za-z0-9_.-]+$/.test(t.id) && !t.id.includes('..') ? t.id : '';
  return a ? {label:addonLabel(a), url:pageHash(a.name, id ? 't/' + id : a.page.path)} : null;
}
// Live session: the two terminal commands stay behind one small "Copy command". Watch live sits in the helper bar
// (one Stop / Watch live pair); the card shows it only when the bar does not. Watch cannot type; Take over can.
function liveSessionStrip(t) {
  const run = state.runs?.[t.id];
  if (snapshot || !run?.running || run.claim?.mode === 'oneshot') return null;
  const ref = typeof t.key === 'string' && t.key ? t.key : t.id;
  const liveLink = liveLinkFor(t), inBar = Boolean(liveLink && window.DashHelpers?.helperAlive?.(t, run));
  const copy = (label, command) => {
    const control = button('', 'menu-item', async () => {
      try { await navigator.clipboard.writeText(command); window.orch.toast('Copied', 'ok'); }
      catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
    });
    control.dataset.key = 'live-copy-' + (command.includes('--watch') ? 'watch' : 'take');
    control.title = command;
    control.append(iconEl('copy'), label);
    return control;
  };
  const commands = h('details', {className:'menu', 'data-key':'live-commands'}, h('summary', {className:'btn ghost sm'}, 'Copy command'),
    h('div', {className:'menu-pop', role:'menu'}, copy('Watch (read only)', 'orch run attach ' + ref + ' --watch'), copy('Take over (you can type)', 'orch run attach ' + ref)));
  return h('section', {className:'card live-strip', 'data-key':'live-session'}, h('h2', {}, 'Live session'),
    liveLink && !inBar ? h('a', {className:'btn primary sm', href:liveLink.url, 'data-key':'live-open'}, 'Watch live') : null, commands);
}
function agentBar(t) {
  const liveLink = liveLinkFor(t), run = state.runs?.[t.id], alive = window.DashHelpers.helperAlive(t, run);
  const line = window.DashHelpers.agentLine(t, run, Date.now(), liveLink, state.settings);
  const session = array(t.sessions).slice().sort((a, b) => (Date.parse(b.last_used) || 0) - (Date.parse(a.last_used) || 0))[0];
  const step = array(t.checklist).find(task => !task.wont_do && task.state === 'doing');
  // ORCH-61: the core's one state word, and when the helper last wrote to the ticket and what, so working and stuck
  // differ without Watch live; Stop says when the helper sits idle.
  const helper = window.DashHelpers.helperState(run, t), last = run?.last_activity;
  const lastLine = helper && last?.at ? h('p', {className:'meta truncate', 'data-key':'agent-last'},
    'Last activity ' + window.DashHelpers.ago(last.at, Date.now()) + (last.text ? ': ' + clean(window.DashHelpers.historyLine({text:last.text}, t.checklist)) : '')) : null;
  const idle = helper && ['idle', 'stuck'].includes(helper.state);
  // ORCH-415 (UX D2): a start here (Continue, Start, Retry) is outlined, never filled; Answer and Watch live stay filled
  return h('div', {className:'agent-bar', 'data-state':line.state, 'data-key':'agent-bar'},
    h('span', {className:'dot ' + (line.startFailed ? 'error' : run?.running ? 'working' : 'idle'), 'aria-hidden':'true'}),
    line.startFailed ? h('span', {className:'ab-text grow', 'data-key':'start-failed'}, clean(line.status))
      : h('div', {className:'grow'}, h('p', {className:'ab-text truncate'}, h('strong', {}, name(line.agent)), ' · ', clean(line.hold || step?.text || line.status)), lastLine),
    helper && window.UI?.helperPill ? window.UI.helperPill(helper.state, helper.word) : null, line.startFailed ? null : ticketWarmth(t, run, session),
    snapshot ? null : h('div', {className:'ab-actions'}, liveLink && alive ? h('a', {className:'btn primary sm', href:liveLink.url, 'data-key':'watch-live'}, 'Watch live') : null,
      alive ? ticketButton(idle ? 'Stop idle helper' : 'Stop', 'outline sm', () => act('run.stop', {ticket:t.id}), {'data-key':'ticket-stop'})
        // a plain start (Start, Continue, Try again) is the header's one Start button (ORCH-475), never a second one
        // here; Start anyway takes over a stuck run
        : line.primary?.op === 'run.start' && !line.primary.args?.take_over ? null
        : line.primary && !['answer', 'open'].includes(line.primary.op) ? ticketButton(line.primary.label, line.primary.op === 'run.start' ? 'outline' : 'primary', () => { const current = window.DashHelpers.agentLine(ticketOf(t.id), state.runs?.[t.id], Date.now(), liveLinkFor(ticketOf(t.id)), state.settings); if (current.primary && !['answer', 'open'].includes(current.primary.op)) act(current.primary.op, current.primary.args); }) : null));
}

// "X is also changing this folder": one quiet line from the core (orch run status), no banner. A hint, not a lock.
function sharedFolderLine(t) {
  const text = state.runs?.[t.id]?.shared_folder?.line;
  return typeof text === 'string' && text ? h('p', {className:'shared-folder muted', 'data-key':'shared-folder'}, clean(text)) : null;
}
// A ticket that works in its own copy of the project says so behind one small click, under Properties.
// The ticket records branch/base/sub/host only, never the local path (it stays in the machine-local registry).
function copyLine(t) {
  const f = Array.isArray(t.work?.folders) ? t.work.folders.filter(x => x && typeof x.branch === 'string' && x.branch) : [];
  if (!f.length) return null;
  return h('details', {className:'det', 'data-key':'work-copy'}, h('summary', {}, 'Works in a separate copy'),
    h('p', {className:'meta'}, 'Works in a separate copy of your project, so other helpers do not change the same files.'),
    f.map(x => h('p', {className:'mono meta'}, clean(String(x.branch || '')) + (typeof x.path === 'string' && x.path ? ' · ' + clean(x.path) : ''))));
}
const surface = via => clean(via === 'cli' ? 'terminal' : via);
function proofLabel(ev) {
  const kind = ev.type || ev.kind;
  let label = ev.title || ev.text || String(ev.ref || '').split(/[\\/]/).pop() || 'Evidence';
  if (kind === 'pr') {
    const number = ev.number || /(?:pull\/|#|^)(\d+)\b/.exec(String(ev.ref || ev.text || ''))?.[1];
    label = number ? 'PR #' + number : 'PR';
  } else if (kind === 'file') label = window.DashHelpers.fileProofLabel(ev, Date.now());
  else if (kind === 'commit') label = 'Code updated';
  else if (kind === 'command') {
    const passed = /(\d+) passed/.exec([ev.text, ev.summary, ev.ref].filter(Boolean).join(' '));
    if (passed) label = passed[1] + ' checks OK';
  }
  if (kind === 'note') label = ev.text || ev.title || ev.summary || ev.ref || 'Note';
  label = clean(label);
  if (kind === 'note' && label.length > 100) label = label.slice(0, 99) + '…';
  return label;
}
function proofChip(ev) {
  const label = proofLabel(ev), mark = window.DashHelpers.proofMark(ev);
  return h('span', {className:'chip proof-chip'}, h('small', {className:'muted'}, mark.mark + ' ' + mark.label), ' ', label, ev.missing === true ? ' · on another computer' : null);
}
// ---- Files tab (id 'artifacts'): files (orch ticket artifacts), proof, links. Files are read through /api/file (text and pictures only).
const artifactData = new Map();
const PREVIEW_EXT = {text:/\.(txt|md|csv|tsv|json|log|html?|xml|ya?ml|toml|py|js|css|ini)$/i, image:/\.(png|jpe?g|gif|webp)$/i};
const previewable = fileName => PREVIEW_EXT.text.test(fileName) || PREVIEW_EXT.image.test(fileName);
const fileIcon = fileName => PREVIEW_EXT.image.test(fileName) ? 'image' : /\.(csv|tsv)$/i.test(fileName) ? 'table' : /\.(html?|js|py|css|json|xml)$/i.test(fileName) ? 'code' : 'file';
const sizeText = n => n < 1024 ? n + ' B' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
function loadArtifacts(t, selected) {
  if (snapshot) return;
  const hit = artifactData.get(t.id), age = hit ? Date.now() - hit.at : Infinity;
  if (hit?.busy || age < (selected ? 2500 : 30000)) return;
  artifactData.set(t.id, {...hit, busy:true});
  fetch('/api/artifacts/' + encodeURIComponent(t.id)).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    const before = JSON.stringify(artifactData.get(t.id)?.data);
    artifactData.set(t.id, {at:Date.now(), data});
    if (JSON.stringify(data) !== before && route().kind === 'ticket' && ticketOf(route().id)?.id === t.id) render();
  });
}
// A finished ticket with a merged pull request: is the change in the orch installed here? (ORCH-87) orch works it
// out from the merge commit and the installed release (GET /api/release); no answer = no line.
const releaseData = new Map();
const RELEASE_MARK = {installed:['ok', '✓'], released:['warn', '!'], merged:['none', '–']};
function loadRelease(t) {
  if (snapshot || typeof fetch !== 'function' || !['review', 'done'].includes(t.status)) return;
  const hit = releaseData.get(t.id);
  if (hit?.busy || (hit && Date.now() - hit.at < 60000)) return;
  releaseData.set(t.id, {...hit, busy:true});
  fetch('/api/release?ticket=' + encodeURIComponent(t.id), {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null).then(data => {
    const before = JSON.stringify(releaseData.get(t.id)?.data);
    releaseData.set(t.id, {at:Date.now(), data});
    if (JSON.stringify(data) !== before && route().kind === 'ticket' && ticketOf(route().id)?.id === t.id) render();
  });
}
function ticketReleaseLine(t) {
  const r = ['review', 'done'].includes(t.status) ? releaseData.get(t.id)?.data : null;
  if (!r || typeof r.text !== 'string' || !RELEASE_MARK[r.state]) return null;
  const [cls, glyph] = RELEASE_MARK[r.state];
  return h('p', {className:'ticket-proof-line ticket-release', 'data-key':'ticket-release-' + t.id}, h('span', {className:'proof-mark proof-' + cls}, glyph), ' ', h('span', {className:'grow'}, clean(r.text)));
}
const proofRows = t => array(t.checklist).flatMap(task => array(task.evidence).map(ev => ({task, ev})))
  .sort((a, b) => (Date.parse(b.ev.at) || 0) - (Date.parse(a.ev.at) || 0));
const referenceRows = t => array(t.refs).filter(r => r && (['ticket', 'artifact', 'file'].includes(r.kind) || webLinks(t).includes(r))).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
const linkRows = t => referenceRows(t);
const artifactProofs = t => uniqueBy(proofRows(t).filter(({ev}) => evidenceFile(t, ev) || (ev.type || ev.kind) === 'note'), ({ev}) => proofKey(t, ev));
// Files tab rows: artifact files then proofs, merged so a file in both lists shows (and counts) once.
const artifactEntries = t => uniqueBy([...artifactFiles(t).map(file => ({file})), ...artifactProofs(t)], x => x.file ? x.file.name : proofKey(t, x.ev));
const artifactCount = t => artifactEntries(t).length + linkRows(t).length;
// Files tab: all reference kinds, newest first.
function linkGroups(links) {
  const groups = new Map();
  for (const l of links.slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0))) {
    const g = 'References';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(l);
  }
  return [...groups].sort(([a], [b]) => Number(a === 'References') - Number(b === 'References'));
}
// Preview text is cached by file revision; snapshot copies never request local files.
const ticketPreviewText = new Map(), ticketPreviewDone = new Map(), ticketPreviewPending = new Set();
// A web page or PDF shows its first screen, small, over the type icon (kit/fileviewer.js); other files have none.
const shownThumb = (t, kind, file) => snapshot || !window.FileViewer?.thumb ? null : window.FileViewer.thumb({tid:t.id, kind, name:file.name, size:file.size, mtime:file.mtime || ''});
// A short text preview that looks like the file: a CSV as a small table, Markdown rendered, anything else as plain lines.
function previewText(t, kind, file, text) {
  const FV = window.FileViewer;
  if (/\.(csv|tsv)$/i.test(file.name) && FV?.parseDelimited) {
    const rows = text.split('\n').slice(0, 7).join('\n'), data = FV.parseDelimited(rows, /\.tsv$/i.test(file.name) ? '\t' : ',');
    const cols = array(data.columns).slice(0, 4), cut = row => cols.map((_, i) => String(array(row)[i] ?? '').slice(0, 24));
    return h('table', {className:'mini-table', 'data-key':'preview-table'}, h('thead', {}, h('tr', {}, cols.map(c => h('th', {}, String(c).slice(0, 24))))),
      h('tbody', {}, array(data.rows).slice(0, 5).map(r => h('tr', {}, cut(r).map(c => h('td', {}, c))))));
  }
  if (/\.(md|markdown)$/i.test(file.name) && FV?.renderMd) return FV.renderMd(text.split('\n').slice(0, 10).join('\n'), {tid:t.id, kind, name:file.name});
  return h('pre', {}, text.split('\n').slice(0, 8).join('\n'));
}
function ticketPreviewTile(t, file, kind = 'artifacts') {
  const title = (typeof file.title === 'string' && file.title.trim().slice(0, 200)) || String(file.name || '').split('/').pop() || 'Result';
  const tile = h('div', {className:'ticket-preview'}, h('span', {className:'ticket-preview-label'}, title));
  if (!snapshot && /\.pdf$/i.test(file.name)) {  // the browser's own PDF view, from the same-origin file endpoint
    tile.append(h('object', {className:'preview-live', type:'application/pdf', data:fileUrl(t.id, kind, file.name, false, file), 'aria-label':title},
      h('p', {className:'meta'}, 'This browser cannot show the PDF here. Open it to read it.')));
    return tile;
  }
  const html = /\.html?$/i.test(file.name), picture = /\.(png|jpe?g|webp)$/i.test(file.name);
  if (snapshot || html || (!picture && !PREVIEW_EXT.text.test(file.name))) {
    tile.append(h('p', {className:'meta'}, html ? title : 'Preview available when opened'));
    const live = shownThumb(t, kind, file);
    if (live) { tile.classList.add('has-thumb'); tile.append(live); }
    return tile;
  }
  const stamp = window.FileViewer?.stampOf ? window.FileViewer.stampOf(file) : '';  // ORCH-524: the version in the link
  const url = '/api/file?t=' + encodeURIComponent(t.id) + '&k=' + kind + '&n=' + encodeURIComponent(file.name) + (stamp ? '&v=' + encodeURIComponent(stamp) : '');
  const key = url + '|' + (file.mtime || '');
  if (!ticketPreviewText.has(key)) ticketPreviewText.set(key, fetch(url).then(async r => {
    if (r.status === 404) return {missing:true};  // listed, but not on this computer: say so instead of an empty tile
    if (!r.ok) return null;
    const mime = (r.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
    if (picture) return ['image/png', 'image/jpeg', 'image/webp'].includes(mime) ? {blob:await r.blob()} : null;
    const reader = r.body.getReader(), decoder = new TextDecoder();
    let text = '';
    try { while (text.length < 2048) { const part = await reader.read(); if (part.done) break; text += decoder.decode(part.value, {stream:true}); } }
    finally { await reader.cancel(); }
    return {text:text.slice(0, 2048).split('\n').slice(0, 14).join('\n')};
  }).catch(() => null));
  // A finished preview is drawn at once: the page redraws often, and a tile filled later would be thrown away.
  const fill = data => {
    if (data?.missing) tile.append(h('p', {className:'meta file-missing'}, 'This file is missing. It is listed here, but not on this computer.'));
    else if (data?.blob) {
      const src = URL.createObjectURL(data.blob), img = h('img', {src, alt:title, loading:'lazy'});
      img.onload = img.onerror = () => URL.revokeObjectURL(src); tile.append(img);
    } else if (data?.text) tile.append(previewText(t, kind, file, data.text));
  };
  if (ticketPreviewDone.has(key)) fill(ticketPreviewDone.get(key));
  else if (!ticketPreviewPending.has(key)) {  // one redraw per file, however often the page redraws meanwhile
    ticketPreviewPending.add(key);
    ticketPreviewText.get(key).then(data => { ticketPreviewDone.set(key, data); ticketPreviewPending.delete(key); fill(data); if (route().kind === 'ticket') render(); });
  }
  return tile;
}
// A real artifact: its name, what kind it is, a preview and Open. A proof without a file shows no "Completed" filler.
const KIND_WORD = [[/\.(png|jpe?g|gif|webp|svg)$/i, 'Picture'], [/\.pdf$/i, 'PDF'], [/\.xlsx$/i, 'Spreadsheet'], [/\.zip$/i, 'Archive'], [/\.(m4a|aac|mp3|wav|caf|ogg)$/i, 'Sound'], [/\.(mp4|webm|mov|m4v|ogv)$/i, 'Video'], [/\.(csv|tsv)$/i, 'Table'], [/\.md$/i, 'Note'], [/\.html?$/i, 'Page'], [/\.(js|py|css|json|xml|ya?ml|toml|ini)$/i, 'Code'], [/\.(txt|log)$/i, 'Text file']];
const kindWord = fileName => KIND_WORD.find(([re]) => re.test(fileName))?.[1] || 'File';
const evidenceFile = (t, ev) => {
  const prefix = '.orch/tickets/' + t.id + '/evidence/', ref = String(ev.ref || '');
  if ((ev.type || ev.kind) !== 'file' || ev.missing || !ref.startsWith(prefix)) return null;
  const name = ref.slice(prefix.length);  // the server checks again; a path that climbs or is not plain never gets a chip
  if (!name || /[\\\0:]/.test(name) || name.startsWith('/') || name.split('/').some(part => ['', '.', '..'].includes(part))) return null;
  const file = Number.isFinite(ev.size) && ev.size >= 0 ? {name, mtime:ev.at, size:ev.size} : {name, mtime:ev.at};
  if (typeof ev.title === 'string' && ev.title.trim()) file.title = ev.title;  // the title given when the file was attached
  return file;
};
// One file = one entry: lists keep the first item per key; items without a key (notes) all stay.
const uniqueBy = (list, key) => { const seen = new Set(); return list.filter(x => { const k = key(x); if (k == null) return true; if (seen.has(k)) return false; seen.add(k); return true; }); };
const proofKey = (t, ev) => evidenceFile(t, ev)?.name ?? (ev.ref ? (ev.type || ev.kind) + ':' + ev.ref : null);
// ORCH-185: a file a person attached (their history line "Attached <name>" is by a human) is what they asked with, not a result.
const attachedInput = t => new Set(array(t.history).filter(e => e && /^human:/.test(String(e.by || '')) && /^Attached /.test(String(e.text || ''))).map(e => String(e.text).slice(9)));
const allArtifactFiles = t => uniqueBy(array(artifactData.get(t.id)?.data?.files), f => f.name);
const inputFiles = t => { const own = attachedInput(t); return allArtifactFiles(t).filter(f => own.has(f.name)); };
const artifactFiles = t => { const own = attachedInput(t); return allArtifactFiles(t).filter(f => !own.has(f.name)); };
// Every file of the ticket the way the Files tab groups them (the results and the files its steps proved), so the
// Overview cards and the Files tab never disagree about whether a result file exists (ORCH-184).
const resultFiles = t => ticketFileGroups(t).flatMap(g => g.files.map(file => ({kind:g.kind, file})));
const reviewFile = t => t.status === 'review' ? resultFiles(t)[0] || null : null;
function ticketResultCard(t, ev, file = null, kind = 'evidence') {
  const helpers = window.DashHelpers;
  const name = file ? file.name.split('/').pop() : '';
  const title = clean(ev.title) || name || helpers.cleanOutcome(ev.summary) || 'Note';
  const summary = helpers.cleanOutcome(ev.summary);
  const at = ev.at || file?.mtime;
  const who = ev.by ? ticketActor(ev.by) : '';
  const meta = [who, at ? helpers.stamp(at, Date.now()) : ''].filter(Boolean).join(' · ');
  return h('article', {className:'card ticket-result'},
    h('div', {className:'row between'}, h('h3', {}, clean(title)), h('span', {className:'meta'}, file ? kindWord(file.name) : 'Note')),
    summary && summary !== title ? h('p', {}, clean(summary)) : null,
    meta ? h('p', {className:'meta'}, at ? h('time', {datetime:at}, meta) : meta) : null,
    file ? ticketPreviewTile(t, file, kind) : h('div', {className:'ticket-preview'}, h('p', {}, clean(helpers.cleanOutcome(ev.text) || helpers.cleanOutcome(ev.ref) || summary))),
    file && !snapshot ? h('div', {className:'row'}, ticketButton('Open', 'outline', () => previewFile(t.id, kind, file.name)), kind === 'artifacts' ? ticketShareButton(t, file) : null) : null);
}
// "Share with group": only on a ticket that hosts an open group. A file orch could not check for passwords comes
// back with a plain line; the person is asked once and the same click repeats with confirm.
const ticketHostsOpenGroup = t => !snapshot && array(state?.groups?.hosted).some(g => g.ticket === t.id && !g.closed);
function ticketShareButton(t, file) {
  if (!ticketHostsOpenGroup(t)) return null;
  const share = async confirm => {
    const result = await act('group.share', confirm ? {ticket:t.id, file:file.name, confirm:true} : {ticket:t.id, file:file.name});
    if (result.ok) { window.orch.toast('Shared with the group.'); return; }
    if (!confirm && /^We couldn't check this/.test(result.text || '')) {
      const {d, actions} = dialog('Share anyway?', 'dialog');
      d.append(el('p', '', String(result.text).replace(/, so it was not shared\.?$/, '.') + ' Share it anyway?'), actions);
      actions.append(button('Cancel', 'ghost', () => window.orch.close(d)), button('Share anyway', 'primary', async () => { window.orch.close(d); share(true); }));
      window.orch.open(d); return;
    }
    window.orch.toast(clean(result.text) || 'Could not share the file.', 'error');
  };
  return ticketButton('Share with group', 'ghost sm', () => share(false), {'data-key':'file-share-group-' + file.name});
}
// ---- The shared file viewer: name, meta, Open in new tab, Download, Copy link. × Close, Esc and a click outside close it,
// and the opening control gets the cursor back.
// ORCH-524: with the file (its time and size) the link names its version and the browser keeps the picture (kit/fileviewer.js stampOf).
const fileStamp = file => file && window.FileViewer?.stampOf ? window.FileViewer.stampOf(file) : '';
const fileUrl = (tid, kind, fileName, dl = false, file = null) => '/api/file?t=' + encodeURIComponent(tid) + '&k=' + encodeURIComponent(kind) + '&n=' + encodeURIComponent(fileName)
  + (dl ? '&dl=1' : fileStamp(file) ? '&v=' + encodeURIComponent(fileStamp(file)) : '');
const fileTitle = fileName => clean(window.DashHelpers.plainFileName(fileName) || String(fileName).split('/').pop());
// The title given when the file was attached; else the file name made readable.
const oneLineTitle = value => typeof value === 'string' ? clean(value).replace(/\s+/g, ' ').trim().slice(0, 200) : '';
// ORCH-240: the real file name with its extension ("big2mb.txt", not "Big2mb"), so it matches the Files tab and the disk.
const titleOf = file => oneLineTitle(file.title) || clean(shortName(file));
const shortName = file => String(file.name).split('/').pop();
const fileBadge = fileName => (/\.([^./]+)$/.exec(fileName)?.[1] || 'file').slice(0, 4).toUpperCase();
const fileMeta = file => [kindWord(file.name), Number.isFinite(file.size) && file.size >= 0 ? sizeText(file.size) : '', file.mtime ? localStamp(file.mtime) : ''].filter(Boolean).join(' · ');
async function copyFileLink(url) {
  const link = new URL(url, location.href).href;
  if (await window.UI.copyText(link)) window.orch.toast('Link copied', 'ok'); else window.UI.showLink(link);
}
// Every file of a ticket the viewer can step through, with the words the Files tab shows for it.
// The shared viewer (kit/fileviewer.js) names the kind of a file; without it every file is just a file.
const viewerKind = name => window.FileViewer ? window.FileViewer.kindOf(name) : 'other';
const viewerWord = kind => window.FileViewer ? window.FileViewer.word(kind) : 'File';
function ticketFileEntries(t) {
  // The files the person attached themselves belong in the tab and its count too (their Overview card stays), so "Files 0" never reads as lost files.
  const mine = inputFiles(t), groups = mine.length ? [...ticketFileGroups(t), {label:'What was asked', kind:'artifacts', files:mine}] : ticketFileGroups(t);
  const entries = groups.flatMap(g => g.files.map(file => fileEntry(t, g, file)));
  // A web page with its own stylesheet, script and pictures in a folder is ONE website, not four files.
  const sites = new Map(entries.filter(f => f.fileKind === 'page' && f.name.includes('/')).map(f => [f.name.slice(0, f.name.lastIndexOf('/') + 1), f]));
  const parts = new Map();
  const kept = entries.filter(f => {
    const dir = [...sites.keys()].find(d => f.name.startsWith(d) && sites.get(d) !== f);
    if (!dir || f.fileKind === 'page') return true;
    (parts.get(dir) || parts.set(dir, []).get(dir)).push(f);
    return false;
  });
  for (const [dir, rest] of parts) {
    const site = sites.get(dir);
    site.size = (site.size || 0) + rest.reduce((n, f) => n + (f.size || 0), 0);
    site.meta = site.meta.replace(/ · [\d.,]+ (B|KB|MB)/, ' · ' + sizeText(site.size)) + ' · ' + (rest.length + 1) + ' files';
    if (/^index\./i.test(site.name.slice(dir.length))) site.title = fileTitle(dir.slice(0, -1)) + ' website';
  }
  return kept;
}
function fileEntry(t, group, file) {
  const kind = viewerKind(file.name);
  const role = attachedInput(t).has(file.name) ? 'Attached by you' : group.kind === 'evidence' ? 'Evidence' : 'Result', task = group.kind === 'evidence' ? group.label : '';
  const at = file.mtime ? createdText(file.mtime) : '';
  return {tid:t.id, kind:group.kind, name:file.name, size:file.size, mtime:file.mtime || '', fileKind:kind, role, task, created:at,
    title:titleOf(file), named:!!oneLineTitle(file.title),
    meta:[viewerWord(kind), Number.isFinite(file.size) && file.size >= 0 ? sizeText(file.size) : '', at, task ? 'Task: ' + task : '', role].filter(Boolean).join(' · ')};
}
function createdText(at) {
  const text = localStamp(at);
  return text ? 'Created ' + text : '';
}
function previewFile(tid, kind, fileName) {
  if (snapshot || !tid || !fileName) return;
  const t = ticketOf(tid);
  let files = t ? visibleFileEntries(t, ticketFileEntries(t)) : [];
  let index = files.findIndex(f => f.kind === kind && f.name === fileName);
  if (index < 0) {
    const known = array(artifactData.get(tid)?.data?.files).find(f => f.name === fileName) || {name:fileName};
    files = [fileEntry(t || {id:tid}, {kind}, known)]; index = 0;
  }
  // "Share by link…" only when the sharing add-on is on (no hint otherwise); it opens the same Share a file window for this file.
  const share = addons().some(a => a.active !== false && isPublish(a.name)) ? f => shareDialog({name:f.name.split('/').pop(), url:window.FileViewer.urlOf(f)}) : null;
  window.FileViewer.open({files, index, context:t ? clean(t.title || '') : '', share});
}
// One compact file row: type badge, name, meta, Open / Download / Copy link.
function ticketFileActions(t, kind, file) {
  if (snapshot) return null;
  const k = kind + '-' + file.name;
  return h('div', {className:'file-actions'},
    ticketButton('Open', 'ghost sm', () => previewFile(t.id, kind, file.name), {'data-key':'file-open-' + k}),
    h('a', {className:'btn ghost sm', href:fileUrl(t.id, kind, file.name, true), download:file.name.split('/').pop()}, 'Download'),
    ticketButton('Copy link', 'ghost sm', () => copyFileLink(fileUrl(t.id, kind, file.name)), {'data-key':'file-copy-' + k}),
    kind === 'artifacts' ? ticketShareButton(t, file) : null);
}
// ORCH-185: a picture shows itself in its row (the badge stays under it until it has loaded).
const fileThumbImage = (t, kind, file) => h('img', {src:fileUrl(t.id, kind, file.name, false, file), alt:'', loading:'lazy'});
function ticketFileRow(t, kind, file) {
  return h('div', {className:'file-row', 'data-key':'file-' + kind + '-' + file.name},
    (picture => h('span', {className:'file-type' + (picture || shownThumb(t, kind, file) ? ' has-thumb' : ''), 'aria-hidden':'true'}, fileBadge(file.name), picture ? fileThumbImage(t, kind, file) : shownThumb(t, kind, file)))(viewerKind(file.name) === 'image' && !snapshot),
    h('div', {className:'grow'}, h('p', {className:'file-name'}, titleOf(file)), oneLineTitle(file.title) ? h('p', {className:'meta file-real-name'}, shortName(file)) : null, h('p', {className:'meta'}, fileMeta(file))),
    ticketFileActions(t, kind, file));
}
// The result frame: the file heading, then a bounded preview with Expand (the shared viewer).
// A PDF shows as the PDF and a web page as the page (in a frame that cannot reach this app); other files as a short excerpt.
function ticketLivePreview(t, file, kind) {
  if (snapshot) return null;
  const type = viewerKind(file.name), title = titleOf(file);
  if (type === 'pdf') return h('object', {className:'preview-live', type:'application/pdf', data:fileUrl(t.id, kind, file.name, false, file), 'aria-label':title},
    h('p', {className:'meta'}, 'This browser cannot show the PDF here. Open it to read it.'));
  if (type === 'page') return h('iframe', {className:'preview-live', sandbox:'allow-scripts', referrerpolicy:'no-referrer', title, loading:'lazy',
    src:'/view/' + encodeURIComponent(t.id) + '/' + encodeURIComponent(kind) + '/' + file.name.split('/').map(encodeURIComponent).join('/')});
  return null;
}
function ticketResultFrame(t, kind, file) {
  const live = ticketLivePreview(t, file, kind);
  return h('article', {className:'result-frame', 'data-key':'result-frame-' + file.name}, ticketFileRow(t, kind, file),
    h('div', {className:'preview-body' + (live ? ' live' : '')}, live || ticketPreviewTile(t, file, kind),
      snapshot ? null : ticketButton('Expand ↗', 'outline sm preview-expand', () => previewFile(t.id, kind, file.name), {'data-key':'expand-' + file.name})));
}
// Files grouped by the task that produced them; result files no task claims come first.
function ticketFileGroups(t) {
  const owned = new Set(), groups = [];
  for (const task of array(t.checklist)) {
    const files = uniqueBy(array(task.evidence).map(ev => evidenceFile(t, ev)).filter(Boolean), f => f.name).filter(f => !owned.has(f.name));
    files.forEach(f => owned.add(f.name));
    if (files.length) groups.push({label:clean(changeTask(task.text, task.origin)?.title || task.text), kind:'evidence', files});
  }
  const rest = artifactFiles(t).filter(f => !owned.has(f.name));
  if (rest.length) groups.unshift({label:'Results', kind:'artifacts', files:rest});
  return groups;
}
const ticketFileCount = t => ticketFileEntries(t).length;
// ---- Files tab: one card per file (thumbnail, name, kind · size · date); a toolbar (find, sort, cards/list) only above 6 files.
const filesUI = {q:'', sort:'newest', view:'cards', who:'All'};
// Draft E (ORCH-778): who added a file. "You" = files a person attached; "Helper" = results and the files tasks proved.
const fileWho = f => f.role === 'Attached by you' ? 'You' : 'Helper';
// All / Helper / You with counts, only when both kinds are there (one kind needs no filter).
function filesWhoFilter(all) {
  const n = who => all.filter(f => who === 'All' || fileWho(f) === who).length;
  if (!n('Helper') || !n('You')) return null;
  return h('div', {className:'segmented', role:'group', 'aria-label':'Who added it', 'data-key':'files-who'}, ['All', 'Helper', 'You'].map(who =>
    ticketButton([who, ' ', h('span', {className:'seg-count'}, String(n(who)))], '', () => { filesUI.who = who; render(); }, {'aria-pressed':String(filesWho(all) === who), 'data-key':'files-who-' + who})));
}
// The filter only counts while both kinds exist; otherwise every file shows.
const filesWho = all => all.some(f => fileWho(f) === 'You') && all.some(f => fileWho(f) === 'Helper') ? filesUI.who : 'All';
const FILES_TOOLBAR_FROM = 7;
const SORTS = [['newest', 'Newest'], ['oldest', 'Oldest'], ['name', 'Name']];
function sortedEntries(list) {
  const time = f => Date.parse(f.mtime) || 0;
  const by = {newest:(a, b) => time(b) - time(a), oldest:(a, b) => time(a) - time(b), name:(a, b) => a.title.localeCompare(b.title)};
  return list.slice().sort(by[filesUI.sort] || by.newest);
}
function fileThumb(t, f) {
  const thumb = h('div', {className:'file-thumb', 'data-kind':f.fileKind});
  if (f.fileKind === 'image') { thumb.append(h('img', {src:fileUrl(f.tid, f.kind, f.name, false, f), alt:'', loading:'lazy'})); return thumb; }
  if (['md', 'text', 'code', 'table'].includes(f.fileKind) && !(f.size > 2 * 1048576)) {  // size unknown: still draw the capped snippet
    const p = ticketPreviewTile(t, {name:f.name, mtime:f.mtime}, f.kind);
    p.classList.add('file-snippet'); thumb.append(p); return thumb;
  }
  thumb.append(h('span', {className:'file-sym'}, iconEl(fileIcon(f.name)), h('span', {}, viewerWord(f.fileKind))));
  const live = shownThumb(t, f.kind, f);
  if (live) thumb.append(live);
  return thumb;
}
function fileTile(t, f) {
  // Read the list when clicked: a redraw keeps this button, so a list captured now could be out of date.
  const open = () => previewFile(t.id, f.kind, f.name);
  const meta = [viewerWord(f.fileKind), Number.isFinite(f.size) && f.size >= 0 ? sizeText(f.size) : '', f.mtime ? localStamp(f.mtime) : ''].filter(Boolean).join(' · ');
  const link = h('button', {type:'button', className:'file-preview-link', 'aria-label':'Preview ' + f.title + ' · ' + meta, 'data-key':'file-open-' + f.kind + '-' + f.name},
    fileThumb(t, f), h('span', {className:'tile-copy'}, h('strong', {}, f.title), f.named ? h('span', {className:'meta file-real-name'}, shortName(f)) : null, h('span', {className:'meta'}, meta)));
  link.onclick = open;
  return h('article', {className:'file-tile', 'data-key':'file-tile-' + f.kind + '-' + f.name}, link);
}
function visibleFileEntries(t, all) {
  const q = filesUI.q.trim().toLowerCase(), who = filesWho(all);
  return sortedEntries(all.filter(f => (who === 'All' || fileWho(f) === who) && (!q || (f.title + ' ' + f.name).toLowerCase().includes(q))));
}
function filesPanelBody(t, all) {
  const entries = visibleFileEntries(t, all);
  if (!entries.length) return h('p', {className:'muted', 'data-key':'files-none'}, all.length ? (filesUI.q.trim() ? 'No files match. Clear the search.' : 'No files here. Choose All.') : 'No files attached yet. Files your helper attaches appear here.');
  return h('div', {className:'files-collection', 'data-view-mode':filesUI.view === 'list' ? 'list' : 'grid', 'data-key':'files-collection'}, h('div', {className:'file-grid'}, entries.map(f => fileTile(t, f))));
}
function filesToolbar(count) {
  const sort = h('select', {'aria-label':'Sort', 'data-key':'files-sort', 'data-label':'Sort', 'data-prefix':'Sort'}, SORTS.map(([v, text]) => h('option', {value:v}, text)));
  sort.value = filesUI.sort; sort.onchange = () => { filesUI.sort = sort.value; render(); };
  const search = h('input', {type:'search', className:'files-search', placeholder:'Search files', 'aria-label':'Search files', 'data-key':'files-search', value:filesUI.q});
  search.value = filesUI.q;
  search.oninput = () => { filesUI.q = search.value; render(); };
  const view = (id, label) => { const b = h('button', {type:'button', className:'btn sm', 'aria-pressed':String(filesUI.view === id), 'data-key':'files-view-' + id}, label); b.onclick = () => { filesUI.view = id; render(); }; return b; };
  return h('div', {className:'files-toolbar', 'data-key':'files-toolbar'}, search, h('div', {className:'row'}, sort, h('div', {className:'segmented', role:'group', 'aria-label':'File view'}, view('cards', 'Cards'), view('list', 'List'))));
}
function artifactsPanel(t) {
  if (snapshot) {  // a saved copy cannot read files: names only, no controls
    const groups = ticketFileGroups(t);
    return [h('div', {className:'section-head'}, h('h2', {}, 'Files'), h('span', {className:'meta'}, ticketFileCount(t) + (ticketFileCount(t) === 1 ? ' file' : ' files'))),
      groups.length ? groups.map(g => h('section', {className:'file-group', 'data-key':'file-group-' + g.label}, h('h3', {className:'meta'}, g.kind === 'evidence' ? 'For: ' + g.label : g.label), g.files.map(f => ticketFileRow(t, g.kind, f))))
        : h('p', {className:'muted'}, 'No files attached yet.')];
  }
  const all = ticketFileEntries(t);
  if (!all.length && !artifactData.get(t.id)?.data) return [h('div', {className:'file-grid file-skeleton', 'aria-busy':'true', 'aria-label':'Loading files', 'data-key':'files-skeleton'},
    [0, 1, 2].map(i => h('div', {className:'file-tile skeleton-tile', 'data-key':'skeleton-' + i})))];
  const who = filesWhoFilter(all);
  return [who ? h('div', {className:'tab-head', 'data-key':'files-head'}, who) : null, all.length >= FILES_TOOLBAR_FROM ? filesToolbar(all.length) : null, filesPanelBody(t, all)];
}
function ticketActor(by, person) {
  // a line stamped with a person of the list (a phone's line, ORCH-1164) reads as that person, as on the Activity tab
  const listed = window.DashHelpers.listedName && window.DashHelpers.listedName(person || by);
  if (listed) return listed;
  if (typeof chatDmName === 'function' && chatDmName(by)) return chatDmName(by);  // another workspace answered: its contact name
  return /^agent:/.test(by || '') || array(state.settings?.agents).some(a => a.name === by) ? window.DashHelpers.agentLabel(state.settings, {agent:String(by).replace(/^agent:/, '')}) : name(window.DashHelpers.personName(by, state));
}
// A small chip per proof worth opening: a file opens its preview, a PR or web address opens in a new tab.
function taskProofChips(t, task) {
  const chips = uniqueBy(array(task.evidence), ev => proofKey(t, ev)).map(ev => {
    const kind = ev.type || ev.kind, file = evidenceFile(t, ev), label = proofLabel(ev);
    // a real click handler (h() only sets attributes, so an onclick there would be a dead attribute)
    if (file && !snapshot) return Object.assign(button(clean(ev.title || file.name.split('/').pop()), 'chip proof-chip', () => previewFile(t.id, 'evidence', file.name)), {title:'Open'});
    if (file) return h('span', {className:'chip proof-chip'}, clean(ev.title || file.name.split('/').pop()));
    if (['pr', 'url'].includes(kind) && /^https?:\/\//i.test(String(ev.ref || ''))) return h('a', {className:'chip proof-chip', href:safeHref(ev.ref), target:'_blank', rel:'noopener noreferrer'}, label);
    return null;
  }).filter(Boolean);
  return chips.length ? h('div', {className:'task-proofs row'}, chips.slice(0, 4)) : null;
}
// Open task menus and their typed reason, keyed tid:check; kept across render() until submit, Escape or close.
const taskMenus = new Map();
// A change request (origin "change_request", text = the note; older ones are stored as "Change: <note>" without origin) is shown as a
// task title with what you asked below it.
function changeTask(text, origin) {
  const m = origin === 'change_request' ? [null, String(text || '')] : /^Change:\s*([\s\S]+)$/.exec(String(text || '').trim());
  if (!m || !m[1].trim()) return null;
  const asked = m[1].trim();
  const first = asked.split(/\r?\n/)[0].replace(/^(?:please|pls|can you|could you|would you)\s+(?:please\s+)?/i, '').replace(/[.!?\s]+$/, '').slice(0, 80);
  return {title:first ? first.charAt(0).toUpperCase() + first.slice(1) : asked, asked};
}
function taskRows(t) {
  // a task that is gone (removed while its menu was open) must not leave its redraw lock or draft behind
  if (!snapshot) {
    const ids = new Set(array(t.checklist).map(c => c.id));
    for (const key of [...locks]) if (String(key).startsWith('task-menu-') && !ids.has(String(key).slice(10))) locks.delete(key);
    for (const key of [...taskMenus.keys()]) if (key.startsWith(t.id + ':') && !ids.has(key.slice(t.id.length + 1))) taskMenus.delete(key);
  }
  return array(t.checklist).map((task, i) => {
    const doing = !task.wont_do && task.state === 'doing', change = changeTask(task.text, task.origin);
    const mark = snapshot || !task.id ? (task.wont_do ? h('span', {className:'muted'}, '–') : task.done ? h('span', {className:'good'}, iconEl('check')) : h('span', {className:'dot ' + (doing && !window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? 'working' : 'idle')}))
      : h('button', {type:'button', className:'task-check' + (task.wont_do ? ' muted' : task.done ? ' on' : ''), role:task.wont_do ? null : 'checkbox', 'aria-checked':task.wont_do ? null : String(!!task.done), 'aria-label':task.wont_do ? 'Open again' : clean(task.text), 'data-key':'task-check-' + task.id}, task.wont_do ? '–' : task.done ? iconEl('check') : null);
    if (!snapshot && task.id) mark.onclick = () => toggleTask(t.id, task.id);
    let menu = null;
    if (!snapshot && task.id) {
      // The open menu and the typed reason survive render() (the background refresh redraws the row): kept in
      // taskMenus under tid:check until it is submitted, closed or Escaped; never redrawn while the cursor is inside it.
      const menuKey = t.id + ':' + task.id, formKey = 'task-menu-' + task.id;
      const isOpen = taskMenus.has(menuKey);
      const reason = h('input', {type:'text', className:'input', placeholder:'Reason (optional)', 'aria-label':'Reason (optional)', maxlength:200});
      reason.value = taskMenus.get(menuKey) || '';
      const form = h('form', {className:'stack', hidden:!isOpen, 'data-key':formKey},
        window.DashHelpers.resolved(task) ? null : reason,
        h('button', {type:'submit', className:'btn outline sm'}, window.DashHelpers.resolved(task) ? 'Open again' : "Won't do"),
        taskEditRow(t, task, i));
      const closeMenu = () => { taskMenus.delete(menuKey); locks.delete(formKey); form.hidden = true; more.setAttribute('aria-expanded', 'false'); more.focus(); };
      reason.addEventListener('input', () => taskMenus.set(menuKey, reason.value));
      form.addEventListener('focusin', () => locks.add(formKey));
      form.addEventListener('focusout', event => { if (!form.contains(event.relatedTarget)) locks.delete(formKey); });
      form.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeMenu(); } });
      form.onsubmit = async event => {
        event.preventDefault();
        if (window.DashHelpers.resolved(task)) { taskMenus.delete(menuKey); const r = await act('check.reopen', {ticket:t.id, check:task.id}); render(); if (!r.ok) window.orch.toast(r.text, 'error'); return; }
        const lock = 'task-' + t.id + '-' + task.id;
        if (locks.has(lock)) return;
        locks.add(lock);
        const result = await act('check.wont_do', {ticket:t.id, check:task.id, reason:reason.value || ''});
        locks.delete(lock);
        if (result.ok) { taskMenus.delete(menuKey); locks.delete(formKey); }
        render();
        if (!result.ok) window.orch.toast(result.text, 'error');
      };
      const more = h('button', {type:'button', className:'btn outline sm', 'aria-label':'More', 'aria-expanded':String(isOpen)}, '...');
      more.onclick = () => {
        if (taskMenus.has(menuKey)) closeMenu();
        else { taskMenus.set(menuKey, reason.value); form.hidden = false; more.setAttribute('aria-expanded', 'true'); reason.focus(); }
      };
      menu = h('div', {className:'stack'}, more, form);
    }
    return h('div', {className:'card-row ticket-task-row', 'data-key':'task-' + (task.id || i)}, mark,
      h('div', {className:'grow'}, h('h3', {className:task.wont_do ? 'task-wont' : ''}, doing && !window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? h('span', {className:'ticket-spinner', title:'Helper is working', 'aria-label':'Helper is working'}) : null, clean(change ? change.title : task.text)),
        change ? h('p', {className:'meta preserve-lines task-asked'}, 'You asked: ' + clean(change.asked)) : null,
        task.wont_do ? h('p', {className:'meta task-note'}, task.reason ? window.DashHelpers.WONT_DO + ': ' + clean(task.reason) : window.DashHelpers.WONT_DO + '. No reason was given.') : null,
        ticketTaskLine(t, task, doing),
        taskProofChips(t, task)), h('span', {className:'meta task-word' + (taskCheckFailed(t, task) ? ' bad' : '')}, taskCheckFailed(t, task) ? 'Check failed' : taskWord(task)), menu);
  });
}
// ORCH-236: a task can be renamed, moved up or down and removed from its "..." menu (orch check edit / move / remove;
// a removed task stays in the history).
async function taskAct(op, args) {
  const result = await act(op, args);
  if (!result.ok) window.orch.toast(changeError(result), 'error');
  render();
  return result;
}
function taskRename(t, task) {
  const {d, actions} = dialog('Rename task');
  const input = h('input', {className:'input', 'aria-label':'Task', maxlength:500, 'data-key':'task-rename-input'});
  input.value = task.text || '';
  const save = ticketButton('Save', 'primary', async () => {
    const text = input.value.trim(); if (!text || save.disabled) { input.focus(); return; }
    if (text === task.text) { window.orch.close(d); return; }
    save.disabled = true;
    const result = await act('check.edit', {ticket:t.id, check:task.id, text, was:task.text});
    if (result.ok) window.orch.close(d); else { save.disabled = false; window.orch.toast(changeError(result), 'error'); }
  });
  input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } };
  actions.append(save); d.append(input, actions); window.orch.open(d); input.focus();
}
function taskEditRow(t, task, i) {
  const list = array(t.checklist), before = list[i - 1], after = list[i + 1];
  return h('div', {className:'row wrap', 'data-key':'task-edit-' + task.id},
    ticketButton('Rename', 'ghost sm', () => taskRename(t, task), {'data-key':'task-rename-' + task.id}),
    before?.id ? ticketButton('Move up', 'ghost sm', () => taskAct('check.move', {ticket:t.id, check:before.id, after:task.id}), {'data-key':'task-up-' + task.id}) : null,
    after?.id ? ticketButton('Move down', 'ghost sm', () => taskAct('check.move', {ticket:t.id, check:task.id, after:after.id}), {'data-key':'task-down-' + task.id}) : null,
    ticketButton('Remove', 'ghost sm', () => { taskMenus.delete(t.id + ':' + task.id); locks.delete('task-menu-' + task.id); taskAct('check.remove', {ticket:t.id, check:task.id}).then(r => { if (r.ok) window.orch.toast('Removed. It stays in the Activity.', 'ok'); }); }, {'data-key':'task-remove-' + task.id}));
}
// Draft E (ORCH-778): one line under a task. A done task says what came out (its summary or the last evidence) and
// when; the task the helper is on says so; a task still to do shows nothing.
function ticketTaskLine(t, task, doing) {
  if (task.wont_do) return null;
  if (task.done) {
    const ev = array(task.evidence).slice(-1)[0];
    const outcome = window.DashHelpers.outcome(task), said = clean(window.DashHelpers.cleanOutcome(task.summary)) || (outcome === 'Completed.' ? '' : clean(outcome));
    const line = [said, ev?.at ? window.DashHelpers.stamp(ev.at, Date.now()) : ''].filter(Boolean).join(' · ');
    return line ? h('p', {className:'meta task-proof', 'data-key':'task-result-' + (task.id || '')}, line) : null;
  }
  if (!doing) return null;
  return h('p', {className:'meta task-proof'}, window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? 'Not started yet.' : 'The helper is on it.');
}
// Draft E (ORCH-778): the Tasks tab opens with one line: a bar with one step per task, "N of M tasks done" and
// "+ Add a task" (it opens the add box under the line; a ticket without tasks shows the box at once). Then the tasks.
const taskAddOpen = new Set();
function ticketTaskBar(list) {
  const done = list.filter(c => c.done && !c.wont_do).length, open = list.filter(c => !c.wont_do).length;
  return h('div', {className:'progress-steps', role:'progressbar', 'aria-label':'Tasks done', 'aria-valuemin':'0', 'aria-valuemax':String(open), 'aria-valuenow':String(done), 'data-key':'tasks-bar'},
    list.map(c => h('span', {className:c.wont_do ? 'skipped' : c.done ? 'done' : c.state === 'doing' ? 'doing' : null})));
}
function ticketTasksPanel(t) {
  // the count leaves won't-do tasks out and names them (owner words: "7 of 9 tasks done"); the bar still shows them.
  // ORCH-476: the numbers come from the one count source (core progress), the same as Progress and Home.
  const list = array(t.checklist), p = window.DashHelpers.progressOf(state?.counts, t), total = p.total, skipped = p.wont_do, done = p.done;
  const canAdd = !snapshot && t.status !== 'done', open = canAdd && (!total || taskAddOpen.has(t.id) || locks.has('add-task-tasks-' + t.id));
  const add = canAdd && total ? ticketButton([iconEl('plus'), 'Add a task'], 'ghost sm', () => { taskAddOpen.add(t.id); render(); setTimeout(() => document.querySelector('[data-key="add-task-tasks-' + t.id + '"] input')?.focus(), 0); },
    {'aria-expanded':String(open), 'data-key':'tasks-add-' + t.id}) : null;
  return [h('div', {className:'tab-head', 'data-key':'tasks-head'}, total ? ticketTaskBar(list) : null,
    h('strong', {}, total ? done + ' of ' + (total - skipped) + ' tasks done' : 'No tasks yet.'), skipped ? h('span', {className:'meta'}, skipped + ' ' + window.DashHelpers.WONT_DO.toLowerCase()) : null, add),
  open ? addTaskRow(t, 'tasks') : null,
  total ? h('section', {className:'card tasks-list', 'data-key':'tasks'}, taskRows(t)) : null];
}
// "+ Add task": one line, Enter adds it (orch check add). The draft is kept while the page refreshes.
function addTaskRow(t, scope) {
  if (snapshot) return null;
  const key = 'add-task-' + scope + '-' + t.id;
  const input = el('input', 'input');
  Object.assign(input, {type:'text', placeholder:'New task', maxLength:500, name:'task'});
  input.setAttribute('aria-label', 'Add a task');
  const form = el('form', 'row add-task');
  form.dataset.key = key;
  const send = button('Add', 'outline sm', null);
  send.type = 'submit';
  form.append(input, send);
  input.addEventListener('focusin', () => locks.add(key));
  input.addEventListener('blur', () => { if (!input.value.trim()) { locks.delete(key); taskAddOpen.delete(t.id); setTimeout(render, 0); } });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (send.disabled) return;
    if (!text) { window.orch.toast('Type the task first.', 'error'); input.focus(); return; }
    send.disabled = true;
    const result = await act('check.add', {ticket:t.id, text});
    send.disabled = false;
    if (!result.ok) { window.orch.toast(result.text, 'error'); return; }
    input.value = '';
    locks.delete(key);
    render();
    window.orch.toast('Added: ' + (text.length > 40 ? text.slice(0, 40) + '…' : text), 'ok');
  });
  return form;
}
// The selected tab lives on the address (#ticket/<id>?tab=tasks) so a reload or a shared link keeps it.
function writeTicketTab(id, tab) {
  if (typeof history !== 'object' || typeof location !== 'object' || String(location.hash || '').split('?')[0] !== href(id)) return;
  const next = href(id) + (tab && tab !== 'overview' ? '?tab=' + encodeURIComponent(tab) : '');
  if (location.hash !== next) history.replaceState(null, '', next);
}
function tabFromAddress(id) {
  if (typeof location !== 'object') return '';
  const full = String(location.hash || ''), at = full.indexOf('?');
  return full.slice(0, at < 0 ? full.length : at) === href(id) && at >= 0 ? new URLSearchParams(full.slice(at + 1)).get('tab') || '' : '';
}
function selectTicketTab(id, tab, focusQuestion = false) {
  ticketTabs.set(id, tab);
  writeTicketTab(id, tab);
  render();
  if (focusQuestion) {
    const host = main.querySelector('[data-question]');
    if (host) { host.setAttribute('tabindex', '-1'); (host.querySelector('button,input,textarea') || host).focus(); }
  }
}
// ---- Texts from the phone: voice, photos, files, places and feedback shown as people would read them.
const PHONE_IMG = /\.(png|jpe?g|gif|webp)$/i;
function phoneEntry(tid, entry) {
  const p = window.DashHelpers.phoneParts(entry.text, tid);
  if (!p) return null;
  // a phone file is written once, when its text arrives: the text's time names its version (ORCH-524)
  const src = (n, dl) => fileUrl(tid, 'files', n, dl, entry.at ? {mtime:String(entry.at)} : null);
  const body = p.parts.map(x => {
    if (x.type === 'voice') return h('p', {className:'phone-voice'}, iconEl('play'), x.transcript ? '“' + clean(x.transcript) + '”' : 'Voice message (nothing could be understood)', x.lang ? h('span', {className:'meta'}, ' · ' + clean(x.lang)) : null);
    if (x.type === 'sound') return snapshot ? h('p', {className:'meta'}, 'Voice recording') : h('audio', {className:'phone-audio', controls:true, preload:'none', src:src(x.name)});
    if (x.type === 'photo' && PHONE_IMG.test(x.name) && !snapshot) return h('a', {className:'phone-photo', href:src(x.name), target:'_blank', rel:'noopener noreferrer', title:'Open the photo'}, h('img', {className:'phone-thumb', src:src(x.name), alt:clean(x.name), loading:'lazy'}));
    if (x.type === 'photo' || x.type === 'file') return h('p', {className:'phone-file'}, iconEl(x.type === 'photo' ? 'image' : 'file'), snapshot ? clean(x.name) : h('a', {href:src(x.name, true), download:x.name.split('/').pop()}, clean(x.name)));
    if (x.type === 'location') return h('p', {className:'phone-place'}, 'Location' + (x.label ? ': ' + clean(x.label) : ''), ' ', h('a', {href:x.url, target:'_blank', rel:'noopener noreferrer'}, 'Open in Maps'));
    if (x.type === 'feedback') return h('p', {className:'phone-feedback'}, x.approve ? '👍 Looks good on ' : 'Changes wanted on ', h('b', {}, clean(x.title)), x.rev ? h('span', {className:'meta'}, ' · ' + clean(x.rev)) : null);
    if (x.type === 'pin') return h('p', {className:'phone-pin'}, h('span', {className:'chip'}, clean(x.n)), ' ', x.where ? h('span', {className:'meta'}, clean(x.where) + (x.said ? ': ' : '')) : null, clean(x.said));
    return h('p', {className:'meta'}, clean(x.text));
  });
  return h('div', {className:'phone-entry'}, p.text ? h('p', {}, clean(p.text)) : null, body);
}
// Ticket-only controls bind properties: the shared h() serializes attributes.
// The header Answer button (ORCH-234): it only scrolled to the question card, which stands above every tab and so was
// in view already, and focused it without a ring: nothing a person could see. It now opens the same answer window as
// Answer in the ticket list (openNeed). Without a waiting question for this ticket it brings the card to the middle
// and focuses its first answer (no fade: the page never animates needs-you, see test_views).
function focusTicketAnswer(id, trigger) {
  const need = (typeof needsList === 'function' ? needsList() : []).find(n => n && n.ticket === id && window.DashHelpers.needAction(n).kind === 'answer');
  if (need) { openNeed(need, trigger); return 'window'; }
  const card = main.querySelector('.next-question');
  if (!card) return '';
  card.scrollIntoView({block:'center', behavior:'smooth'});
  card.querySelector('[data-question] button, [data-question] input, [data-question] textarea, .ticket-plan-actions button')?.focus({preventScroll:true});
  return 'card';
}
function ticketButton(label, cls, click, attrs = {}) {
  const node = h('button', {type:'button', className:'btn ' + cls, 'data-key':'ticket-button-' + label, ...attrs}, label);
  node.onclick = click;
  return node;
}
// "Changes to add": a dialog shows exactly what the click approves (the tip, the count, the first
// control paths; all made plain on the server) and sends back that same tip, count and path hash.
function ticketBringBackDialog(t) {
  const b = t.bring_back || {}, paths = array(b.paths).map(p => clean(p)), count = Number(b.control_paths) || 0;
  const {d, actions} = dialog('Apply these changes?');
  const more = Math.max(0, count - paths.length);
  const body = [
    h('p', {}, 'Tip ', h('code', {}, clean(String(b.tip || '').slice(0, 12)))),
    Number.isInteger(b.commits) && Number.isInteger(b.files)
      ? h('p', {'data-key':'bring-back-size'}, b.commits + (b.commits === 1 ? ' commit, ' : ' commits, ') + b.files + (b.files === 1 ? ' file changes.' : ' files change.'))
      : null,
    h('p', {'data-key':'bring-back-count'}, count === 1 ? 'It changes 1 file that controls orch or git:' : count ? 'It changes ' + count + ' files that control orch or git:' : 'It changes no files that control orch or git.'),
    paths.length ? h('ul', {className:'bring-back-paths', 'data-key':'bring-back-paths'}, paths.map(p => h('li', {}, h('code', {}, p)))) : null,
    more ? h('p', {className:'meta'}, 'and ' + more + ' more') : null,
  ].filter(Boolean);
  const go = ticketButton('Apply changes', 'primary', async () => {
    if (go.disabled) return;
    go.disabled = true;
    const r = await act('copies.approve', {ticket:t.id, tip:b.tip, control_paths:b.control_paths, paths_hash:b.paths_hash});
    window.orch.close(d);
    window.orch.toast(r.ok ? 'Review submitted' : r.text || 'That did not work.', r.ok ? 'success' : 'error');
  });
  actions.append(go); d.append(...body, actions); window.orch.open(d);
  return d;
}
// "Review changes": a read-only list of what the copy changed (files with + and - counts) and one file's diff.
const keptCopies = new Set();
function keptKey(t) { return 'orch.keptcopy.' + t.id + '.' + String(t.bring_back?.tip || ''); }
function isKept(t) {
  if (keptCopies.has(keptKey(t))) return true;
  try { return sessionStorage.getItem(keptKey(t)) === '1'; } catch (_) { return false; }
}
function ticketChangesDialog(t) {
  const {d, actions} = dialog('What the copy changed');
  const body = el('div', 'stack'), diffBox = el('pre', 'preserve-lines copy-diff');
  diffBox.hidden = true; diffBox.tabIndex = 0;
  body.append(el('p', 'meta', 'Reading the copy…'));
  const showDiff = async file => {
    diffBox.hidden = false; diffBox.textContent = 'Loading…';
    try {
      const r = await fetch('/api/copy-changes?t=' + encodeURIComponent(t.id) + '&path=' + encodeURIComponent(file.path), {cache:'no-store'});
      const data = r.ok ? await r.json() : null;
      diffBox.replaceChildren();
      if (!data) { diffBox.textContent = 'This file could not be shown.'; return; }
      String(data.diff).split('\n').forEach(line => {
        const row = el('span', /^\+(?!\+\+)/.test(line) ? 'diff-add' : /^-(?!--)/.test(line) ? 'diff-del' : '', line + '\n');
        diffBox.append(row);
      });
      if (data.cut) diffBox.append(el('span', 'meta', '\n(The rest of this file is not shown.)'));
    } catch (_) { diffBox.textContent = 'This file could not be shown.'; }
  };
  fetch('/api/copy-changes?t=' + encodeURIComponent(t.id), {cache:'no-store'}).then(r => r.ok ? r.json() : {files:[]}).catch(() => ({files:[]})).then(data => {
    const files = array(data.files);
    body.replaceChildren();
    if (!files.length) { body.append(el('p', 'muted', 'No changed files could be listed.')); return; }
    const list = el('ul', 'copy-files');
    files.forEach(f => {
      const li = el('li'), b = button('', 'ghost sm copy-file', () => showDiff(f));
      b.append(el('span', 'grow', clean(f.path)), el('span', 'meta', f.added == null ? 'binary' : '+' + f.added + ' −' + f.removed));
      li.append(b); list.append(li);
    });
    body.append(list);
    if (data.more) body.append(el('p', 'meta', 'and ' + data.more + ' more files'));
  });
  d.append(body, diffBox, actions);
  actions.firstChild.textContent = 'Close';
  window.orch.open(d);
  return d;
}
function ticketBringBackRow(t) {
  const b = t.bring_back;
  if (b?.state !== 'waiting') return null;
  const ask = !snapshot && b.reason_code === 'update' ? ticketButton('Ask your helper to update', 'ghost sm', async () => {
    const r = await act('copies.ask-update', {ticket:t.id});
    window.orch.toast(r.ok ? 'Asked the helper to update its copy' : r.text || 'That did not work.', r.ok ? 'success' : 'error');
  }) : null;
  const add = !snapshot && b.tip ? ticketButton('Apply changes', 'primary sm', () => ticketBringBackDialog(t)) : null;
  // "Keep as is" is only this page's choice: nothing is changed or signed; the copy stays where it is.
  if (!snapshot && b.tip && isKept(t)) return h('p', {className:'meta kept-line', 'data-key':'bring-back'}, 'Changes kept in a copy · ', ticketButton('Apply changes', 'ghost sm', () => ticketBringBackDialog(t)));
  const review = !snapshot && b.tip ? ticketButton('Review changes', 'outline sm', () => ticketChangesDialog(t)) : null;
  const keep = !snapshot && b.tip ? ticketButton('Keep as is', 'ghost sm', () => {
    keptCopies.add(keptKey(t)); try { sessionStorage.setItem(keptKey(t), '1'); } catch (_) { /* optional */ }
    render();
  }) : null;
  return h('section', {className:'card attention decision bring-back-card', 'data-key':'bring-back'},
    h('p', {className:'meta'}, 'Needs you'), h('h2', {}, 'Changes to add'), h('p', {className:'muted'}, clean(b.reason)),
    h('div', {className:'actions'}, add, review, keep, ask));
}
const ticketHistoryTechnical = false;
let ticketHistoryActor = 'All';
function ticketHistoryWho(entry) {
  const by = String(entry.by || entry.actor || '');
  return /^human:/.test(by) ? 'People' : /^agent:/.test(by) ? 'Helper' : 'System';
}
function ticketHistoryIsTechnical(entry) {
  const kind = String(entry.kind || entry.type || '').toLowerCase(), text = String(entry.text || '');
  if (/answer|verdict|review|created|done/.test(kind) || /^(Marked c\d+ as won't do|Marked as won't do|Created|Answered|Done|Check c\d+ done|Finished a task)|(?:->|to) done\b/i.test(text)) return false;
  if (ticketHistoryWho(entry) === 'People' && (/edit|status/.test(kind) || /^(Edited|Status|Patched status)/i.test(text))) return false;
  return /claim|release|run|session|evidence/.test(kind) || /^(Claimed|Released|Run\b|Session\b|Added evidence|Evidence added|The agent is up|Waiting: the agent is not up)|^\S+ started$/i.test(text) ||
    (ticketHistoryWho(entry) === 'System' && (/status/.test(kind) || /^(Status|Patched status)/i.test(text)));
}
function ticketHistoryEntries(t, actor = ticketHistoryActor, technical = ticketHistoryTechnical) {
  return window.DashHelpers.dedupeHistory(array(t.history), t.checklist)
    .filter(e => (technical || !ticketHistoryIsTechnical(e)) && (actor === 'All' || ticketHistoryWho(e) === actor))
    .sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
}
function ticketHistoryDay(at, now = new Date()) {
  const d = new Date(at), yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (!Number.isFinite(d.getTime())) return 'Earlier';
  return d.toDateString() === now.toDateString() ? 'Today' : d.toDateString() === yesterday.toDateString() ? 'Yesterday' : localStamp(at, false);
}
function ticketHistoryPanel(t) {
  const groups = new Map();
  const views = new Map(window.DashHelpers.historyView(array(t.history), t.checklist, state.me).map(v => [v.entry, v]));
  for (const entry of ticketHistoryEntries(t)) {
    const view = views.get(entry);
    if (!view) continue;
    const day = ticketHistoryDay(entry.at);
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(h('div', {className:'ticket-event'}, entry.via === 'phone' ? phoneEntry(t.id, entry) : null,
      h('p', {}, view.sentence ? clean(view.sentence) : [ticketActor(entry.by), clean(view.line)].filter(Boolean).join(' · '), entry.via === 'phone' ? [' ', h('span', {className:'tag'}, 'Phone')] : null),
      (change => change ? h('p', {className:'meta ticket-change'}, 'Was: ' + clean(change.was) + '  →  Now: ' + clean(change.now)) : null)(window.DashHelpers.historyChange(entry)), h('time', {className:'meta', datetime:entry.at}, time(entry.at))));
  }
  // Draft E (ORCH-778): the master segmented control, each choice with its count (the entries it would show).
  const count = label => ticketHistoryEntries(t, label).filter(e => views.has(e)).length;
  const controls = snapshot ? null : h('div', {className:'tab-head ticket-history-filters', 'data-key':'history-head'}, h('div', {className:'segmented', role:'group', 'aria-label':'Show'},
    ['All', 'People', 'Helper'].map(label => ticketButton([label, ' ', h('span', {className:'seg-count'}, String(count(label)))], '', () => { ticketHistoryActor = label; render(); }, {'aria-pressed':String(ticketHistoryActor === label), 'data-key':'history-show-' + label}))));
  return h('section', {className:'stack ticket-history', 'data-key':'history'}, controls, groups.size ? [...groups].map(([day, rows]) => h('section', {className:'ticket-history-day'}, h('h3', {}, day), rows)) : emptyRow(ticketHistoryActor === 'All' ? 'No history yet.' : 'Nothing here yet. Choose All.'));
}
// ORCH-777 (owner picked draft E, 19 Nov): the Overview tells the ticket's story as one history, newest first, by day.
// Every entry has one owner, so nothing shows twice: an answered question owns its Asked/Answered lines, a file a person
// attached owns its "Attached" line, a task's evidence files sit in its "Finished a task" line, result files are their
// own messages. Rules in full: ORCH-777 artifact history-event-rules.md. The Activity tab keeps every line.
const OVERVIEW_FIRST = 5, OVERVIEW_STEP = 20, OVERVIEW_SNAPSHOT = 50, FILE_GROUP_MS = 10 * 60000, REQUEST_MS = 2 * 60000;
const overviewOpen = new Map();  // ticket id -> how many entries a person revealed (Infinity = Show all); resets on reload
const timeOf = v => { const n = typeof v === 'number' ? v : typeof v === 'string' ? Date.parse(v) : NaN; return Number.isFinite(n) ? n : null; };
const QUESTION_LINE = /^(?:Asked|Answered) (q\d+)\b/, ATTACHED_LINE = /^Attached (.+)$/, TASK_DONE_LINE = /^Check (c\d+) done\b/;
const isPerson = e => /^human:/.test(String(e?.by || ''));
// The lines that tell the story; a line no rule knows shows when a person wrote it (helper and orch lines stay on Activity).
function overviewStoryLine(e) {
  const text = String(e?.text || '').trim();
  if (/^(Created\b|Check c\d+ done\b|Marked c\d+ as won't do|Reopened c\d+|Sent back\b|Summary\b)/.test(text)) return true;
  const status = /^(?:Patched status \(status|Status) \w+ -> (\w+)/.exec(text);
  if (status) return isPerson(e) || ['review', 'done'].includes(status[1]);
  return isPerson(e);
}
// The files that came with the request: attached by a person up to 2 minutes after the ticket was made (all of them
// when the ticket has no time at all), so nothing the person sent goes missing from "What you asked".
function overviewCreated(t) {
  return timeOf(t.created_at) ?? timeOf(t.created) ?? array(t.history).map(e => timeOf(e?.at)).find(v => v != null) ?? null;
}
function overviewEntries(t, files = []) {
  const history = array(t.history), checklist = array(t.checklist), owned = new Set(), out = [], request = [];
  const present = new Map(array(files).filter(f => f && f.name).map(f => [f.name, f])), created = overviewCreated(t);
  const drop = new Set();
  // 1. files a person attached: the request's own, or a message of their own later on
  history.forEach((e, idx) => {
    const m = isPerson(e) && ATTACHED_LINE.exec(String(e.text || '').trim());
    if (!m || !present.has(m[1])) return;  // a deleted file keeps its row "Attached <name>"
    drop.add(e);
    const key = 'artifacts/' + m[1];
    if (owned.has(key)) return;
    owned.add(key);
    const at = timeOf(e.at), file = present.get(m[1]);
    if (created == null || at == null || at <= created + REQUEST_MS) request.push(file);
    else out.push({kind:'attached', at, rank:1, idx, by:e.by, via:e.via, files:[file]});
  });
  // 2. answered (or taken back) questions own their Asked/Answered lines; an open question is on top already
  const shownQ = new Set(), openQ = new Set();
  array(t.questions).forEach((q, idx) => {
    if (!q || !q.id) return;
    if (q.answer == null && !q.taken_back) { if (t.status !== 'done') openQ.add(q.id); return; }  // a Done ticket shows no open question on top
    shownQ.add(q.id);
    out.push({kind:'answer', at:timeOf(q.answered_at) ?? timeOf(q.at) ?? timeOf(q.asked_at), rank:0, idx, q});
  });
  history.forEach(e => { const m = QUESTION_LINE.exec(String(e?.text || '').trim()); if (m && (shownQ.has(m[1]) || openQ.has(m[1]))) drop.add(e); });
  // 3. the other story lines, as the kit words them (same dedupe as Activity)
  const views = window.DashHelpers.historyView(history, checklist, state?.me);
  const events = [];
  for (const view of views) {
    const e = view.entry;
    if (!e || drop.has(e) || !overviewStoryLine(e)) continue;
    const task = TASK_DONE_LINE.exec(String(e.text || '').trim())?.[1] || null;
    events.push({kind:'event', at:timeOf(e.at), rank:2, idx:history.indexOf(e), entry:e, view, task, files:[]});
  }
  // 4. evidence files: inside their task's newest "Finished a task" line, else a message of their own
  for (const task of checklist) {
    const found = [];
    array(task?.evidence).forEach(ev => {
      const file = evidenceFile(t, ev), key = file && 'evidence/' + file.name;
      if (!file || owned.has(key) || owned.has('artifacts/' + file.name)) return;  // a file a person attached, used as evidence
      owned.add(key); found.push({file, at:timeOf(ev.at)});
    });
    if (!found.length) continue;
    const line = events.filter(x => x.task === task.id).sort((a, b) => (b.at ?? -1) - (a.at ?? -1) || b.idx - a.idx)[0];
    if (line) { line.files.push(...found.map(x => ({kind:'evidence', file:x.file}))); continue; }
    const at = found.map(x => x.at).filter(v => v != null).sort((a, b) => b - a)[0] ?? null;
    out.push({kind:'files', at, rank:1, idx:checklist.indexOf(task), label:clean(changeTask(task.text, task.origin)?.title || task.text), files:found.map(x => ({kind:'evidence', file:x.file}))});
  }
  out.push(...events);
  // 5. result files (not attached by a person): one message per 10 minutes, counted from the newest file of the group
  // the Files tab's rule: a result file that is also a task's evidence (same name) is that evidence
  const results = array(files).filter(f => f && f.name && !owned.has('artifacts/' + f.name) && !owned.has('evidence/' + f.name) && !attachedNames(t).has(f.name))
    .map((file, idx) => ({file, at:timeOf(file.mtime), idx})).sort((a, b) => (b.at ?? -Infinity) - (a.at ?? -Infinity) || a.idx - b.idx);
  let group = null;
  for (const r of results) {
    owned.add('artifacts/' + r.file.name);
    const fits = group && (r.at == null ? group.at == null : group.at != null && group.at - r.at <= FILE_GROUP_MS);
    if (!fits) { group = {kind:'files', at:r.at, rank:1, idx:r.idx, files:[]}; out.push(group); }
    group.files.push({kind:'artifacts', file:r.file});
  }
  // newest first; undated entries last in the order they were written; same time: answer, file, line, later first
  out.sort((a, b) => a.at == null || b.at == null ? (a.at == null) - (b.at == null) || a.rank - b.rank || a.idx - b.idx
    : b.at - a.at || a.rank - b.rank || b.idx - a.idx);
  return {entries:out, request};
}
const attachedNames = t => new Set(array(t.history).filter(e => isPerson(e) && ATTACHED_LINE.test(String(e.text || '').trim())).map(e => ATTACHED_LINE.exec(String(e.text).trim())[1]));
function overviewDay(entry) { return entry.at == null ? 'Earlier' : ticketHistoryDay(new Date(entry.at).toISOString()); }
// What a person can still reveal: the rest of the next hidden day, at most 20 entries at a time.
function overviewMore(entries, limit) {
  const rest = entries.slice(limit);
  if (!rest.length) return null;
  const day = overviewDay(rest[0]), n = Math.min(OVERVIEW_STEP, rest.findIndex(x => overviewDay(x) !== day) < 0 ? rest.length : rest.findIndex(x => overviewDay(x) !== day));
  return {day, n, hidden:rest.length};
}
// the day is the group's label already: only the time of day (a time in the future keeps its date)
const overviewTime = entry => entry.at == null ? null : h('time', {className:'meta', datetime:new Date(entry.at).toISOString()},
  (iso => entry.at > Date.now() + 86400000 || !window.UI?.clock ? time(iso) : window.UI.clock(iso))(new Date(entry.at).toISOString()));
// "lume · <tool> started" reads as a sentence: "lume started the helper (<tool>)"
const overviewSentence = (e, view) => view.sentence ? clean(view.sentence)
  : (m => m && isPerson(e) ? (ticketActor(e.by, e.person) || 'Someone') + ' started the helper (' + clean(m[1]) + ')' : null)(/^(\S+) started$/.exec(String(e.text || '').trim()))
  || [ticketActor(e.by, e.person), clean(view.line)].filter(Boolean).join(' · ');
const overviewPhone = via => via === 'phone' ? h('span', {className:'tag'}, 'Phone') : null;
function overviewFiles(t, files, max = 3) {
  return [files.slice(0, max).map(f => ticketFileRow(t, f.kind, f.file)),
    files.length > max ? h('p', {className:'meta'}, '+ ' + (files.length - max) + ' more on the Files tab') : null];
}
function overviewEntry(t, x) {
  if (x.kind === 'answer') {
    const q = x.q, api = typeof reviewApi === 'function' ? reviewApi() : null;
    if (q.decision && typeof q.decision === 'object' && window.UI?.answerRecord) {
      const record = ticketReviewAnswers(t).find(r => r.key === q.id);
      if (record) return h('div', {className:'history-msg', 'data-key':'history-answer-' + q.id}, window.UI.answerRecord(record, {fileUrl:api ? api.fileUrl : () => '', now:new Date(), showTicket:false}));
    }
    const who = (window.DashHelpers.listedName && window.DashHelpers.listedName(q.answered_by))  // a person of the list (ORCH-1164)
      || (typeof chatDmName === 'function' && chatDmName(q.answered_by)) || name(q.answered_by);
    return h('article', {className:'history-msg history-answer', 'data-key':'history-answer-' + q.id},
      h('div', {className:'history-msg-h'}, h('b', {}, 'Helper asked'), overviewPhone(q.via), h('span', {className:'grow'}), overviewTime(x)),
      h('p', {}, clean(q.text)),
      h('blockquote', {className:'history-reply' + (q.taken_back ? ' muted' : '')}, h('b', {className:'preserve-lines'}, clean(q.answer ?? '')),
        h('span', {className:'meta'}, ' · ' + [q.taken_back ? 'Taken back' : 'Answered', who, q.via === 'phone' ? 'on the phone' : surface(q.via)].filter(Boolean).join(' · '))));
  }
  if (x.kind === 'attached') {
    return h('article', {className:'history-msg', 'data-key':'history-attached-' + x.files[0].name},
      h('div', {className:'history-msg-h'}, h('b', {}, ticketActor(x.by) || 'Someone'), overviewPhone(x.via), h('span', {className:'grow'}), overviewTime(x)),
      h('p', {}, 'Added a file'), overviewFiles(t, x.files.map(file => ({kind:'artifacts', file}))));
  }
  if (x.kind === 'files') {
    const n = x.files.length;
    return h('article', {className:'history-msg', 'data-key':'history-files-' + x.files[0].file.name},
      h('div', {className:'history-msg-h'}, h('b', {}, 'Helper'), h('span', {className:'grow'}), overviewTime(x)),
      h('p', {}, x.label ? 'Added ' + (n === 1 ? 'a file' : n + ' files') + ' · ' + x.label : 'Added ' + (n === 1 ? 'a file' : n + ' files')), overviewFiles(t, x.files));
  }
  const e = x.entry, change = window.DashHelpers.historyChange(e);
  return h('div', {className:'history-event' + (x.files.length ? ' with-files' : ''), 'data-key':'history-event-' + x.idx},
    h('div', {className:'history-event-line'}, h('span', {className:'history-dot', 'aria-hidden':'true'}),
      h('p', {className:'grow'}, overviewSentence(e, x.view)), overviewPhone(e.via), overviewTime(x)),
    e.via === 'phone' ? phoneEntry(t.id, e) : null,
    change ? h('p', {className:'meta ticket-change'}, 'Was: ' + clean(change.was) + '  →  Now: ' + clean(change.now)) : null,
    x.files.length ? overviewFiles(t, x.files) : null);
}
// Worked out on the click itself: the page keeps a button with the same key across renders, and with it the handler
// of its first render, so the handler must not carry counts from the render that made it.
function overviewEarlier(id) {
  const t = (typeof ticketOf === 'function' && ticketOf(id)) || null;
  if (!t) return;
  const shown = overviewOpen.get(id) ?? OVERVIEW_FIRST, more = overviewMore(overviewEntries(t, allArtifactFiles(t)).entries, shown);
  if (more) overviewOpen.set(id, shown + more.n);
  render();
}
function overviewHistory(t, entries) {
  if (!entries.length) return null;
  const limit = snapshot ? OVERVIEW_SNAPSHOT : (overviewOpen.get(t.id) ?? OVERVIEW_FIRST), shown = entries.slice(0, limit), more = overviewMore(entries, limit);
  const days = [];
  for (const x of shown) { const day = overviewDay(x); if (!days.length || days[days.length - 1].day !== day) days.push({day, rows:[]}); days[days.length - 1].rows.push(overviewEntry(t, x)); }
  const tail = !more ? null : snapshot ? h('p', {className:'meta history-more', 'data-key':'history-more'}, more.hidden + (more.hidden === 1 ? ' earlier entry is' : ' earlier entries are') + ' on the Activity tab.')
    : h('div', {className:'history-more', 'data-key':'history-more'},
      ticketButton('Show earlier · ' + more.day + ', ' + more.n + ' more', 'ghost sm', () => overviewEarlier(t.id), {'data-key':'history-earlier'}),
      more.n < more.hidden ? ticketButton('Show all', 'ghost sm', () => { overviewOpen.set(t.id, Infinity); render(); }, {'data-key':'history-all'}) : null);
  return h('section', {className:'history-list', 'aria-label':'History', 'data-key':'history-' + t.id},
    days.map(d => h('section', {className:'history-day'}, h('h3', {className:'history-day-h'}, d.day), d.rows)), tail);
}
// What was asked (one heading for the ask, ORCH-415): the person's note (editable in place), the description a helper wrote, and the files that came with it.
// Always the last block of the Overview, right under the history and its Show earlier line, so it never folds away.
function overviewRequest(t, note, files) {
  if (!note && !t.description && !files.length) return null;
  return h('section', {className:'card asked', 'data-key':'brief'},
    h('div', {className:'section-head'}, h('h2', {}, 'What was asked'), overviewCreated(t) != null ? h('span', {className:'meta'}, localStamp(new Date(overviewCreated(t)).toISOString())) : null),
    hasValue(t, 'note') || !t.description ? note : null,  // an empty note under a helper's description is only an empty row (report r-1122-0538)
    t.description ? h('div', {className:'stack', 'data-key':'description'}, h('p', {className:'preserve-lines'}, linkRefs(t, t.description)), t.description_by ? h('p', {className:'meta'}, 'Written by ' + ticketActor(t.description_by)) : null) : null,
    files.map(f => ticketFileRow(t, 'artifacts', f)));
}
function ticketWarmth(t, run, session) {
  const seconds = [session?.seconds_left, session?.warmth?.seconds_left, run?.claim?.warmth?.seconds_left, t.warmth?.seconds_left].find(v => typeof v === 'number' && Number.isFinite(v));
  if (seconds === undefined) return null;
  const remaining = Math.ceil(Math.max(0, seconds) / 60) + ' min';
  return h('span', {className:'ticket-warmth', title:'Session stays ready for ' + remaining}, ticketGlyph('flame'), remaining);
}
function ticketPhone(q) {
  if (q.sent_to_phone !== true && !q.delivered) return null;
  const title = q.delivered ? 'Delivered to your phone' : 'Also sent to your phone';
  return h('span', {className:'ticket-phone', title, 'aria-label':title}, ticketGlyph('phone'));
}
// ORCH-238 (owner, 17 Nov): "Add to this ticket" on the ticket page itself, needs no add-on. A person writes what is
// new, pastes screenshots or adds files; one click puts the files on the ticket (`ticket.attach`) and tells the helper
// (`run.send`, and `run.start` when no helper is on it; `ticket.changes` for a ticket in Review). The helper's live
// screen (the dashboard's read-only /api/term) sits above the box, so the person sees the conversation it goes into.
const TALK_SEND_MAX = 2000;  // run.send's limit (actions.MAX_TEXT)
const TALK_TYPED_MAX = 1500;  // what the box takes; the rest is the line that names the files
const TALK_TYPES = ['txt', 'md', 'csv', 'tsv', 'json', 'log', 'yml', 'yaml', 'toml', 'ini', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'webm', 'ogg', 'm4a', 'mp3', 'wav'];  // orch ticket attach
const TALK_AUDIO = /\.(webm|ogg|m4a|mp3|wav)$/i;
const TALK_FILE_MAX = 25 * 1024 * 1024, TALK_FILES = 10, TALK_POLL = 2000;
// The one feedback box (ORCH-422): words, a pasted screenshot, a dropped or picked file and a voice note, on Send back,
// Add note and Add to this ticket alike. Same limits as every ticket file (orch ticket attach decides).
const FEEDBACK_BOX = {accept:TALK_TYPES, maxFiles:TALK_FILES, maxBytes:TALK_FILE_MAX, voice:true,
  acceptError:'Only text files, pictures and voice recordings can be added.', attachLabel:'Add file'};
function ticketTalkCard(t) {
  if (snapshot || !t || t.status === 'done') return null;
  return h('section', {className:'ticket-talk talk-line', 'aria-label':'Add to this ticket', 'data-key':'ticket-talk-' + t.id},
    h('div', {className:'stack', 'data-ticket-talk':t.id, 'data-key':'ticket-talk-host-' + t.id}));
}
// What the helper is told: the person's words, then one line naming the files (they are on the ticket already).
function ticketTalkText(typed, names) {
  const said = String(typed || '').trim();
  const count = names.length === 1 ? 'a file' : names.length + ' files';
  // a voice note without its words (the browser could not turn it into text on this computer): say so plainly
  const mute = names.some(n => TALK_AUDIO.test(n)) && !/(^|\n)Voice note: /.test(said) ? ' The voice note came without written words.' : '';
  let files = names.length ? 'I added ' + count + ' to this ticket: ' + names.join(', ') + '.' + mute : '';
  if (files && said.length + files.length + 40 > TALK_SEND_MAX) files = 'I added ' + count + ' to this ticket.' + mute;
  if (!said) return files + ' Read ' + (names.length === 1 ? 'it' : 'them') + ' and carry on.';
  return files ? said + '\n\n' + files + ' Read ' + (names.length === 1 ? 'it' : 'them') + ' first.' : said;
}
const talkFailed = result => result.status === 0 ? "Can't reach orch. Nothing was sent." : window.DashHelpers.scrubText(String(result.text || '')).slice(0, 300) || 'That did not work. Try again.';
// The box's files onto the ticket in one ticket.attach call; the names orch kept come back (it may rename "x (2).png").
// feedback: the files of an answer on Review go in the ticket's feedback folder, so the Check card being answered
// does not change under the answer (its own files are the helper's result; ORCH-420 follow-up).
async function ticketAttachFiles(tid, files, feedback = false) {
  const list = array(files);
  if (!list.length) return {ok:true, names:[]};
  const added = await act('ticket.attach', {ticket:tid, files:list.map(f => ({name:f.name, data:String(f.url || '').slice(String(f.url || '').indexOf(',') + 1)})), ...(feedback ? {feedback:true} : {})});
  if (!added.ok) return {ok:false, text:talkFailed(added)};
  if (typeof artifactData !== 'undefined') artifactData.delete(tid);  // the Files tab counts the new files on the next draw
  const saved = array(added.state?.attached?.saved).filter(n => typeof n === 'string');
  const failed = array(added.state?.attached?.failed).filter(n => typeof n === 'string');
  if (failed.length && !saved.length) return {ok:false, text:'These files could not be added: ' + failed.join(', ') + '.'};
  return {ok:true, names:saved.length ? saved : list.map(f => f.name)};
}
async function ticketTalkSend(tid, message) {
  const t = ticketOf(tid);
  if (!t) return {ok:false, text:'This ticket is no longer here.'};
  const files = array(message.files);
  const kept = await ticketAttachFiles(tid, files);
  if (!kept.ok) return kept;
  const text = ticketTalkText(message.text, kept.names);
  const partial = r => ({ok:false, dropFiles:files.length > 0, text:(files.length ? 'The files are on the ticket, but the helper was not told: ' : '') + talkFailed(r)});
  if (t.status === 'review') {  // the same call as Send back: Ready, the note queued, a helper starts from it
    const back = await act('ticket.changes', {ticket:tid, text});
    return back.ok ? {ok:true, said:text, text:'Sent back to the helper with your note.'} : partial(back);
  }
  const sent = await act('run.send', {ticket:tid, text});
  if (!sent.ok) return partial(sent);
  const r = sent.state?.send_result;
  const delivered = !!r && Number.isInteger(r.delivered) && r.delivered > 0;
  if (!delivered && !(r && typeof r.id === 'string' && r.id)) return partial({status:200, text:'orch did not confirm that your message was saved.'});
  if (delivered) return {ok:true, said:text, text:'Sent. The helper reads it now.'};
  if (r.state !== 'none') return {ok:true, said:text, text:'Sent. The helper reads it when it finishes what it is doing.'};
  // nothing on the ticket: start a helper, it reads this first. Through the one starter (ORCH-475): Starting… until it
  // runs, one run for a double click, and the way the person picked in the Start choice (else the usual start).
  const ops = talkStartOps.get(tid) || [['run.start', {ticket:tid}]];
  talkStartOps.delete(tid);
  const starter = window.UI?.startStarter;
  const started = starter ? await starter.start(tid, ops) : await act('run.start', {ticket:tid});
  if (started.again) return {ok:true, said:text, text:'Sent. The helper is starting and reads it first.'};
  if (started.queued) return {ok:true, said:text, text:'Sent. The ticket waits in line for a free helper place; the helper reads it first.'};
  return started.ok ? {ok:true, said:text, text:'Sent. A helper starts and reads it first.'} : {ok:true, said:text, text:'Saved on the ticket. Start the helper to go on.'};
}
// The helper's screen as plain text: colours and cursor codes dropped (the kit's dock shows text only).
function talkScreenText(screen) { return String(screen || '').replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '').replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, '').replace(/\x1b[@-_]/g, '').replace(/\s+$/, ''); }
const talkStartOps = new Map();  // ticket id -> the start picked in the Start choice next to Send and start helper
function ticketTalkLabel(t, run) {
  if (t?.status === 'review') return 'Send back with this';
  return window.DashHelpers.helperAlive(t, run) ? 'Send to helper' : 'Send and start helper';
}
function ticketTalk(host, tid) {
  const dot = el('span', 'live-dot'); dot.setAttribute('aria-hidden', 'true');
  const title = el('b', '', 'Helper conversation'), when = el('span', 'meta');
  const head = el('div', 'session-dock-h'); head.append(dot, title, el('span', 'grow'), when);
  const body = el('div', 'session-dock-b'); body.tabIndex = 0; body.setAttribute('role', 'log'); body.setAttribute('aria-label', 'The helper’s screen, read only');
  const quiet = el('div', 'session-dock-state');
  const dock = el('div', 'session-dock in-card'); dock.dataset.key = 'ticket-talk-dock'; dock.append(head, body, quiet);
  dock.hidden = true;  // until the first look says a helper is live
  const box = el('div'); box.id = 'ticket-composer-' + tid;
  host.append(dock, box);
  const composer = window.UI.composer(box, {...FEEDBACK_BOX, label:'Add to this ticket', placeholder:'Write what is new, paste a screenshot, drop files or record…',
    sendLabel:ticketTalkLabel(ticketOf(tid), state.runs?.[tid]), interrupt:false, maxFiles:TALK_FILES, maxBytes:TALK_FILE_MAX, maxLength:TALK_TYPED_MAX,
    hint:'Text files, pictures and voice notes · Cmd/Ctrl+V pastes a screenshot · Cmd/Ctrl+Enter sends', sendStyle:'outline',  // the page keeps its one filled button (Start, Watch live)
    emptyError:'Write something or add a file.',
    dropTarget:host, dropLabel:'Drop to add to this ticket', sendingText:'Sending…',
    onSend:async message => { const result = await ticketTalkSend(tid, message); render(); return result; }});
  box.classList.add('one-line');  // ORCH-777: one line until it is selected or has text or files (kit composer.css)
  let timer = null, last = null, busy = false;
  const show = (live, text) => {
    // ORCH-777: the box is one line; the helper's screen shows above it only while a helper is live (the send button
    // already says whether it starts one)
    body.hidden = !live; quiet.hidden = live; dot.hidden = !live; dock.hidden = !live;
    if (!live) { if (quiet.textContent !== text) quiet.textContent = text; when.textContent = ''; return; }
    if (text === last) return;
    const atEnd = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
    last = text; body.textContent = text || 'The helper is starting…';
    if (atEnd || !body.dataset.seen) { body.scrollTop = body.scrollHeight; body.dataset.seen = '1'; }
    when.textContent = 'Live';
  };
  const idle = t => t?.status === 'review' ? 'No helper is working on this ticket. What you send goes back to it with Send back.'
    : 'No helper is working on this ticket right now. What you send is read when it starts.';
  async function poll() {
    const t = ticketOf(tid), run = state.runs?.[tid];
    if (!t || busy || document.hidden) return;
    // Any run on the ticket (also one that is starting or could not start) may have a screen worth seeing; no run, no ask.
    if (!run?.claim && !window.DashHelpers.helperAlive(t, run)) { show(false, idle(t)); return; }
    if (run?.claim?.mode === 'oneshot') { show(false, 'The helper works in the background; its screen is not shown here.'); return; }
    busy = true;
    try {
      const res = await fetch('/api/term?ticket=' + encodeURIComponent(tid), {cache:'no-store'});
      const snap = res.ok ? await res.json() : null;
      if (snap?.state === 'live') show(true, talkScreenText(snap.screen));
      else show(false, window.DashHelpers.helperAlive(t, run) ? 'The helper is working; its screen is not available yet.' : idle(t));
    } catch (_) { /* the next poll tries again */ }
    finally { busy = false; }
  }
  const submit = box.querySelector('[type=submit]');
  // Send and start helper has the caret of the one Start button (ORCH-475, mockup ticket/ticket-start.html): a picked way
  // to start sends the box first (when something is in it), then starts that way.
  const caretFacts = () => {
    const t = ticketOf(tid);
    return t && typeof startFacts === 'function' ? {...startFacts(t), caretHidden:ticketTalkLabel(t, state.runs?.[tid]) !== 'Send and start helper'} : null;
  };
  let caret = null;
  if (submit && window.UI?.startButton && caretFacts()) {
    const slot = el('span');
    submit.before(slot);
    caret = window.UI.startButton(slot, {ticket:tid, caretOnly:true, mainEl:submit, label:'Send and start helper', send:(op, args) => act(op, args, {quiet:true}),
      toast:(text, kind, again) => window.orch.toast(text, kind || 'ok', again), ...caretFacts(),
      before:async ops => {
        const typed = box.querySelector('textarea')?.value.trim(), staged = box.querySelectorAll('.attachment-tile').length;
        if (!typed && !staged) return [];  // nothing to send: just start that way
        talkStartOps.set(tid, ops);
        box.querySelector('form')?.requestSubmit();
        return null;
      }});
  }
  return {
    update() {
      const label = ticketTalkLabel(ticketOf(tid), state.runs?.[tid]);
      if (submit && submit.textContent !== label) submit.textContent = label;
      if (caret) { const f = caretFacts(); if (f) caret.update(f); }
      if (!timer) { poll(); timer = setInterval(poll, TALK_POLL); }
    },
    destroy() { clearInterval(timer); timer = null; composer.destroy?.(); },
  };
}
// Called after each render: the box and the screen are built once per ticket page and kept (mounts skip reconcile).
function mountTicketTalk(main) {
  if (!window.UI?.composer) return;
  main.querySelectorAll('[data-ticket-talk]').forEach(host => {
    let mounted = mounts.get(host);
    if (!mounted) { mounted = ticketTalk(host, host.dataset.ticketTalk); mounts.set(host, mounted); }
    mounted.update();
  });
}
async function ticketSendChanges(t, note) {
  const text = String(note || '').trim();
  if (snapshot || !text) return false;
  // One call: the ticket is Ready and the note is queued as your own input; an agent run starts from it.
  const sent = await act('ticket.changes', {ticket:t.id, text});
  window.orch.toast(sent.ok ? 'Changes sent' : changeError(sent), sent.ok ? 'ok' : 'error');
  return sent.ok;
}
function ticketChangesEditor(t) {
  const key = 'ticket-changes-' + t.id;
  const host = h('div', {'data-key':key});
  // B13g: the tip recorded for this review is shown, and Accept sends that same tip: the core tells when
  // new changes arrived after you looked (the Done still happens; bringing them back then needs your OK).
  const tip = typeof t.review_tip === 'string' && /^[0-9a-f]{40,64}$/.test(t.review_tip) ? t.review_tip : '';
  const done = ticketButton('Looks good', 'primary sm', () => moveTicket(t.id, 'done', false, tip ? {review_tip:tip} : {}), {'data-key':'ticket-button-Accept-' + (tip ? tip.slice(0, 20) : 'none')}); // keyed by the tip: a refresh never keeps a handler with a stale one
  // ORCH-250: with a step still open Looks good is off and says why; Send back is the way on.
  const unfinished = array(t.checklist).filter(c => !c.done && !c.wont_do).length;
  // ORCH-548 (owner 18 Nov): an open question stops it too, with the same words as the Review card
  const asks = array(t.questions).filter(q => q && q.answer == null && !q.taken_back).length;
  if (unfinished || asks) { done.disabled = true; done.setAttribute('aria-disabled', 'true'); }
  const askNote = asks ? h('span', {className:'meta warn', 'data-key':'ticket-review-open-question'}, '! ' + (asks === 1 ? 'A question on this ticket still waits for your answer. Answer it first, then press Looks good.' : asks + ' questions on this ticket still wait for your answer. Answer them first, then press Looks good.')) : null;
  const unfinishedNote = unfinished ? h('span', {className:'meta warn', 'data-key':'ticket-review-open-steps'}, '! ' + (unfinished === 1 ? '1 step is' : unfinished + ' steps are') + ' not finished. Send it back to get ' + (unfinished === 1 ? 'it' : 'them') + ' done.') : null;
  const row = h('div', {className:'row ticket-review-actions'});
  const open_parts = array(t.proof?.uncovered).length;
  const uncovered = open_parts ? h('span', {className:'meta warn', 'data-key':'ticket-review-uncovered'}, '! ' + (open_parts === 1 ? '1 part' : open_parts + ' parts') + ' of “Done when” ' + (open_parts === 1 ? 'has' : 'have') + ' no task') : null;
  const shown = tip ? h('span', {className:'meta', 'data-key':'ticket-review-tip'}, 'Changes up to ', h('code', {}, tip.slice(0, 12))) : null;
  const open = ticketButton('Send back', 'outline sm', () => {
    locks.add(key);
    // The feedback box (ORCH-422): words, a pasted screenshot, a file or a voice note; Ctrl/Cmd+Enter sends.
    const box = h('div', {id:'ticket-changes-box-' + t.id});
    let comp = null, sending = false;
    const close = () => { if (sending) return; comp?.destroy?.(); locks.delete(key); host.replaceChildren(row); open.focus(); };
    const cancel = ticketButton('Cancel', 'ghost sm', close, {'data-key':'ticket-ask-cancel'});
    host.replaceChildren(h('div', {className:'stack-sm'}, h('p', {className:'ticket-ask-label'}, 'What should change?'), box, h('div', {className:'row'}, cancel)));
    if (!window.UI?.composer) return;
    comp = window.UI.composer(box, {...FEEDBACK_BOX, label:'What should change?', placeholder:'Write, paste a picture or record', sendLabel:'Send back',
      interrupt:false, maxLength:TALK_TYPED_MAX, hint:'', emptyError:'Write what should change, or add a file or a voice note.', dropTarget:host, dropLabel:'Drop to send back with this', sendingText:'Sending…',
      onSend:async message => {
        sending = true;
        try {
          const kept = await ticketAttachFiles(t.id, message.files);
          if (!kept.ok) return kept;
          const ok = await ticketSendChanges(t, ticketTalkText(message.text, kept.names));
          if (ok) { sending = false; close(); render(); return {ok:true, text:''}; }
          return {ok:false, dropFiles:kept.names.length > 0, text:kept.names.length ? 'The files are on the ticket, but it was not sent back. Try again.' : 'It was not sent back. Try again.'};
        } finally { sending = false; }
      }});
    box.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); close(); } });
    comp.field.focus();
  });
  row.append(...[done, open, unfinishedNote, askNote, uncovered, shown].filter(Boolean)); host.append(row); return host;
}
function ticketQuestion(t, q, next = false) {
  const card = q.card && typeof q.card === 'object' ? q.card : null;
  return h('section', {className:next ? 'card next-step next-question' : 'ticket-question'},
    h('div', {className:'meta ticket-eyeline'}, (next ? 'Next step · ' : '') + clean((card && card.title) || q.title || 'Your answer'), ticketPhone(q)),
    h('h2', {}, clean(window.DashHelpers.questionWords ? window.DashHelpers.questionWords(q.text) : q.text)), typeof questionCommandRows === 'function' ? questionCommandRows(q.text, 'question-' + q.id) : null, card ? ticketCardShown(t, q, card) : snapshot ? h('p', {className:'meta'}, 'Waiting for an answer') : h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
}
// A question with a card (orch ask --draft/--choose/...): the text and the card's pictures together, answered on the
// card itself (Review opens at this card), so the answer keeps what was picked, the comment and the marked spots.
function ticketCardShown(t, q, card) {
  if (card.kind === 'run' && typeof runCardNode === 'function' && !snapshot) { const rc = runCardNode(t.id, q); if (rc) return h('div', {className:'stack', 'data-key':'card-shown-' + q.id}, rc); }
  const api = typeof reviewApi === 'function' ? reviewApi() : null;
  const pv = card.preview?.type === 'options'  // the suggested option is marked on its picture, as on the card
    ? {...card.preview, options:array(card.preview.options).map(o => ({...o, suggested:o.id === q.recommended}))} : card.preview;
  const tiles = window.UI?.cardShown ? window.UI.cardShown({card:{...card, preview:pv}, ticket:t.id}, {fileUrl:api ? api.fileUrl : () => ''}) : null;
  const sug = q.recommended === 'ok' ? 'Suggested: ' + (card.ok_label || 'Looks good') : q.recommended === 'no' ? "Suggested: Don't do" : '';
  const go = snapshot ? h('p', {className:'meta'}, 'Waiting for an answer')
    : h('a', {className:'btn outline sm', href:'#review?card=' + encodeURIComponent('core:q:' + t.id + ':' + q.id), 'data-key':'card-go-' + q.id}, 'Look and answer');
  return h('div', {className:'stack', 'data-key':'card-shown-' + q.id}, tiles, card.why ? (window.UI?.moreText ? window.UI.moreText(clean(card.why)) : h('p', {className:'meta'}, clean(card.why))) : null, h('div', {className:'row'}, go, sug ? h('span', {className:'swipe-sug'}, sug) : null,
    array(q.links).filter(l => l && /^https?:\/\//i.test(String(l.url || ''))).slice(0, 5).map((l, i) => h('a', {className:'btn ghost sm', href:String(l.url), target:'_blank', rel:'noopener', 'data-key':'card-link-' + q.id + '-' + i}, iconEl('link'), clean(l.label)))));
}
// A step is named by its title only; the ticket key is a quiet line under Properties.
const partName = p => clean(p.title);
function ticketAddStep(t) {
  const ask = t.release ? 'What ships in this release?' : t.epic ? 'What needs doing in this ticket?' : 'What is this sub-ticket about?';  // an epic (ORCH-14) or a release (ORCH-37) holds tickets
  const {d, actions} = dialog(ask);
  const input = h('input', {className:'input', 'aria-label':ask, maxlength:200});
  // ORCH-156: or a ticket that already exists moves in (its "Part of" changes). Not this ticket, not one it is
  // part of (a loop), not a closed one, not one already in it. FOLLOW-UP: kit select, a native one until then.
  const all = tickets(), above = new Set([t.id]);
  for (let p = window.DashHelpers.parentOf(all, t); p && !above.has(p.id); p = window.DashHelpers.parentOf(all, p)) above.add(p.id);
  const inside = new Set(window.DashHelpers.childrenOf(all, t).map(c => c.id));
  const existing = all.filter(x => x && !above.has(x.id) && !inside.has(x.id) && !['done', 'dropped'].includes(x.status)).sort((x, y) => window.DashHelpers.creationOrder(y, x));
  const pick = existing.length ? h('select', {className:'input', 'aria-label':'Or pick a ticket that already exists'},
    h('option', {value:''}, 'Or pick a ticket that already exists'),
    existing.map(x => h('option', {value:x.id}, [x.key, clean(x.title)].filter(Boolean).join(' ')))) : null;
  if (pick) pick.onchange = () => { input.hidden = !!pick.value; };
  const send = ticketButton('Add', 'primary', async () => {
    const moved = pick && pick.value ? existing.find(x => x.id === pick.value) : null;
    const title = input.value.trim(); if ((!title && !moved) || send.disabled) return;
    send.disabled = true;
    const result = moved ? await act('ticket.edit', {ticket:moved.id, parent:t.id, if_revision:(ticketOf(moved.id) || moved).revision}) : await act('ticket.new', {title, parent:t.id});
    if (result.ok) window.orch.close(d); else { send.disabled = false; window.orch.toast(changeError(result), 'error'); }
  });
  input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send.click(); } };
  actions.append(send); d.append(h('div', {className:'stack'}, input, pick), actions); window.orch.open(d); input.focus();
}
function ticketParts(t, children) {
  const holds = t.epic || t.release, add = snapshot ? null : ticketButton(holds ? '+ Add a ticket' : '+ Add a sub-ticket', 'ghost add-row', () => ticketAddStep(t));
  // No steps yet: only the add button, so a top-level ticket can get its first step (a step itself gets none).
  if (!children.length) return add && !window.DashHelpers.parentOf(tickets(), t) ? h('div', {className:'row', 'data-key':'parts-add'}, add) : null;
  // ORCH-37: in a release, an epic's row says how far its own tickets are ("Epic · 2 of 4 done").
  const epicLine = child => { if (!t.release || !child.epic) return null; const kids = window.DashHelpers.childrenOf(tickets(), child); return h('span', {className:'meta'}, kids.filter(k => k.status === 'done').length + ' of ' + kids.length + ' parts done'); };
  return card('parts', t.release ? 'Tickets in this release' : t.epic ? 'Parts' : 'Sub-tickets', children.filter(c => c.status === 'done').length + ' of ' + children.length + ' done', [children.map(child => h('a', {className:'card-row ticket-part', href:href(child.id)}, h('span', {className:'grow'}, window.DashHelpers.keyTag(child, h), clean(child.title)), epicLine(child), statusChip(child), h('span', {'aria-hidden':'true'}, '›'))), add]);
}
const ticketPlanEditing = new Set();
function ticketRenameStep(child) {
  const {d, actions} = dialog('Rename sub-ticket');
  const input = h('input', {className:'input', 'aria-label':'Sub-ticket title', maxlength:200, value:child.title});
  const save = ticketButton('Save', 'primary', async () => {
    const title = input.value.trim(); if (!title || save.disabled) return;
    save.disabled = true;
    const result = await act('ticket.edit', {ticket:child.id, title, if_revision:child.revision});
    if (result.ok) window.orch.close(d);
    else { save.disabled = false; window.orch.toast(changeError(result), 'error'); }
  });
  input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } };
  actions.append(save); d.append(input, actions); window.orch.open(d); input.focus();
}
function ticketPlan(t, q, children) {
  const goal = t.plan?.goal, notIn = t.plan?.not_included;
  const editing = ticketPlanEditing.has(t.id);
  const start = snapshot ? null : ticketButton('Start work', 'primary', async () => {
    const lock = 'plan-answer-' + t.id;
    if (locks.has(lock)) return;
    locks.add(lock); start.disabled = true;
    try {
      const result = await act('answer', {ticket:t.id, question:q.id, digest:q.digest, answer:'Start work'});
      window.orch.toast(result.ok ? 'Answered · Start work · dashboard' : result.text, result.ok ? 'ok' : 'error');
      if (result.ok) { ticketPlanEditing.delete(t.id); render(); refresh(); }
    } finally { locks.delete(lock); start.disabled = false; }
  });
  return h('section', {className:'card next-step next-question ticket-plan'},
    chip("Waiting for you · work hasn't started", 'attn'),
    h('h2', {}, clean(q.text)),
    goal ? h('p', {className:'preserve-lines'}, h('strong', {}, 'Goal: '), clean(goal)) : null,
    notIn ? h('p', {className:'meta preserve-lines'}, h('strong', {}, 'Not included: '), clean(notIn)) : null,
    h('ol', {className:'ticket-plan-steps'}, children.filter(c => c.status !== 'dropped').map(child =>
      h('li', {}, h('div', {className:'stack'}, h('strong', {}, clean(child.title)),
        child.done_when ? h('p', {className:'meta preserve-lines'}, 'Done when ' + clean(child.done_when)) : null,
        editing && !snapshot && ['open', 'ready'].includes(child.status) && !array(child.checklist).some(c => c.done)
          ? h('div', {className:'row'},
            ticketButton('Rename', 'outline sm', () => ticketRenameStep(child)),
            ticketButton('Remove', 'outline sm', async function () {
              if (this.disabled) return;
              this.disabled = true;
              const result = await act('ticket.patch', {ticket:child.id, data:{status:'dropped'}, if_revision:child.revision});
              if (!result.ok) { this.disabled = false; window.orch.toast(changeError(result), 'error'); }
              render();
            })) : null)))),
    snapshot ? null : h('div', {className:'row ticket-plan-actions'}, start,
      ticketButton('Change sub-tickets', 'outline', () => { if (editing) ticketPlanEditing.delete(t.id); else ticketPlanEditing.add(t.id); render(); }),
      editing ? [ticketButton('+ Add a sub-ticket', 'ghost', () => ticketAddStep(t)),
        ticketButton('Done editing', 'ghost', () => { ticketPlanEditing.delete(t.id); render(); })] : null));
}
const NOTE_LABELS = [['changed', 'Changed'], ['why', 'Why'], ['not_included', 'Not in this ticket']];
function outcomeOf(t) {
  const o = t && typeof t.outcome === 'object' && t.outcome ? t.outcome : {};
  return Object.fromEntries(NOTE_LABELS.filter(([key]) => typeof o[key] === 'string' && o[key].trim()).map(([key]) => [key, o[key].trim()]));
}
// Done tickets: what changed and why (outcome, written by the agent or a person). Absent outcome = no card.
function ticketOutcomeCard(t) {
  const o = outcomeOf(t);
  if (t.status !== 'done' || !Object.keys(o).length) return null;
  return h('section', {className:'card ticket-outcome', 'data-key':'outcome-' + t.id}, h('div', {className:'card-h'}, h('h2', {}, 'What changed and why')),
    h('dl', {className:'why'}, NOTE_LABELS.filter(([key]) => o[key]).flatMap(([key, label]) => [h('dt', {}, label), h('dd', {className:'preserve-lines'}, clean(o[key]))])));
}
// One honest line about the proof (computed by the core as t.proof): a mark, the line, and one plain row per task.
const PROOF_MARK = {passed:['ok', '✓'], failed:['bad', '×'], changed:['warn', '!'], note:['none', 'i'], missing:['none', '–']};
const PROOF_WORD = {passed:'Check passed', failed:'Check failed', changed:'Changed since the check', note:'Note only', missing:'No evidence yet'};
const RECHECK_TEXT = 'Please run the checks again and record them with orch check record.';
// "#123" in plain text links to that issue or pull request on GitHub. The address comes from the ticket's own GitHub
// links (references, evidence) with that number, else the repository of any GitHub link of this ticket or of another
// ticket here; with no GitHub link anywhere the text stays plain.
const GH_LINK = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(?:issues|pull)\/(\d+)(?:[/?#]|$)/;
const ghUrls = t => [...array(t?.refs).map(r => r && (r.url || r.ref)), ...array(t?.checklist).flatMap(c => array(c?.evidence).map(e => e && e.ref))]
  .map(u => GH_LINK.exec(String(u || ''))).filter(Boolean);
function ghRepo(t) {
  const own = ghUrls(t)[0];
  if (own) return own[1];
  const others = typeof tickets === 'function' ? array(tickets()) : [];
  for (const other of others) { const m = ghUrls(other)[0]; if (m) return m[1]; }
  return null;
}
function linkRefs(t, value) {
  const s = clean(value);
  if (!/(^|[^\w&/])#\d/.test(s)) return s;
  const repo = ghRepo(t);
  if (!repo) return s;
  const exact = new Map(ghUrls(t).map(m => [m[2], m[0].replace(/[/?#]$/, '')]));
  const out = [];
  let last = 0;
  for (const m of s.matchAll(/(^|[^\w&/])#(\d{1,7})\b/g)) {
    const at = m.index + m[1].length, n = m[2];
    out.push(s.slice(last, at), h('a', {href:exact.get(n) || 'https://github.com/' + repo + '/issues/' + n, target:'_blank', rel:'noopener noreferrer'}, '#' + n));
    last = at + 1 + n.length;
  }
  out.push(s.slice(last));
  return out.filter(x => x !== '');
}
// What a finished step's evidence says, under its row while the ticket waits for a check: the completion note, what
// was run (and a failed exit), and the pull request, web address or file it points at.
function stepEvidence(t, task) {
  const said = [], ran = [], links = [];
  array(task.evidence).forEach(ev => {
    if (!ev || typeof ev !== 'object') return;
    const kind = ev.type || ev.kind, ref = String(ev.ref || ev.text || '').trim(), sum = String(ev.summary || '').trim();
    const say = x => { if (x && !said.includes(x)) said.push(x); };
    say(sum);
    if (kind === 'note') say(ref);
    else if (kind === 'command' && ref) ran.push(ref + (Number.isInteger(ev.exit) && ev.exit !== 0 ? ' (failed, exit ' + ev.exit + ')' : ''));
    else if (['pr', 'url'].includes(kind) && /^https?:\/\/\S+$/i.test(ref)) {
      const num = GH_LINK.exec(ref)?.[2];
      links.push(h('a', {className:'chip proof-chip', href:ref, target:'_blank', rel:'noopener noreferrer'}, clean(ev.title || (num ? (kind === 'pr' ? 'PR #' : '#') + num : ref.replace(/^https?:\/\//i, '').slice(0, 60)))));
    } else if (kind === 'file' && ref) links.push(h('span', {className:'chip proof-chip'}, clean(ev.title || ref.split(/[\\/]/).pop())));
  });
  if (!said.length && !ran.length && !links.length) return null;
  return h('div', {className:'proof-evidence', 'data-key':'proof-evidence-' + task.id},
    said.map(x => h('p', {className:'muted preserve-lines'}, linkRefs(t, x))),
    ran.map(x => h('p', {className:'meta mono'}, 'Ran: ' + clean(x))),
    links.length ? h('div', {className:'task-proofs row'}, links) : null);
}
function ticketProofLine(t) {
  const p = t.proof;
  if (!p || typeof p.line !== 'string' || !p.line) return null;
  const per = p.per_item && typeof p.per_item === 'object' ? p.per_item : {};
  const level = ({ok:'ok', note:'none', warn:'warn', fail:'bad'})[p.level] || 'none';
  const mark = {ok:'✓', bad:'×', warn:'!', none:'–'}[level];
  const rows = array(t.checklist).map(task => { const [cls, glyph] = PROOF_MARK[per[task.id]] || PROOF_MARK.missing;
    return h('li', {className:'proof-row'}, h('span', {className:'proof-mark proof-' + cls}, glyph), ' ', clean(task.text), ' ', h('span', {className:'meta'}, PROOF_WORD[per[task.id]] || PROOF_WORD.missing),
      t.status === 'review' ? stepEvidence(t, task) : null); });
  return h('div', {className:'ticket-proof', 'data-key':'ticket-proof-' + t.id},
    h('p', {className:'ticket-proof-line'}, h('span', {className:'proof-mark proof-' + level}, mark), ' ', h('span', {className:'grow'}, p.line)),
    Object.values(per).includes('changed') && t.status === 'review' && !snapshot ? ticketButton('Ask your helper to check again', 'outline sm', () => ticketSendChanges(t, RECHECK_TEXT), {'data-key':'ticket-recheck-' + t.id}) : null,
    rows.length || array(p.uncovered).length ? h('ul', {className:'ticket-proof-rows'}, rows, array(p.uncovered).map(part => h('li', {className:'proof-row'}, h('span', {className:'proof-mark proof-warn'}, '!'), ' “', linkRefs(t, part), '” ', h('span', {className:'meta'}, 'Nothing in the to-do list covers this yet')))) : null);
}

// Header line: only in review (the card shows it there) and done, only with tasks; never a warning on a finished ticket.
function headerProof(t) {
  if (t.status !== 'done' || !array(t.checklist).length || array(t.proof?.uncovered).length) return null;
  return ticketProofLine(t);
}

// The history entry that marked the ticket done; the ticket page and the list both take the finish time from it.
// The last history line that moved the ticket to `status` ("Status active -> review", "Patched status (status ready -> review)").
function ticketMovedBy(t, status) {
  const to = new RegExp('->\\s*' + status + '\\b');
  return array(t.history).slice().reverse().find(e => e && to.test(e.text || '')) || null;
}
// ORCH-235: an epic (or any parent) whose sub-tickets are all finished, at least one Done, while it is still open.
function ticketKidsAllDone(t) {
  if (['done', 'review', 'dropped'].includes(t.status)) return null;
  const kids = window.DashHelpers.childrenOf(tickets(), t);
  return kids.length && kids.every(k => ['done', 'dropped'].includes(k.status)) && kids.some(k => k.status === 'done') ? kids : null;
}
function ticketDoneEvent(t) {
  return array(t.history).slice().reverse().find(e => e && (e.kind === 'done' || /(?:->|to) done\b|^Done\b/i.test(e.text || '')));
}
function ticketDoneLine(t) {
  if (t.status !== 'done') return null;
  const event = ticketDoneEvent(t);
  const at = window.DashHelpers.doneAt(t);
  return h('p', {className:'ticket-done'}, '✓ Finished' + (at ? ' ' + localStamp(at) : '') + (event?.by ? ' by ' + ticketActor(event.by) : ''));
}
// One local format for every time on the ticket page (master UI.stamp): "today 10:32", "Mon 08:00", "14 Nov 2026, 10:32".
function localStamp(at, withTime = true) {
  return window.UI?.stamp ? window.UI.stamp(at, {time:withTime}) : '';
}
// A ticket a helper already worked on (it has sessions) but that is not running now is paused, not new.
// Tasks a person typed before any helper ran do not make it paused.
function ticketPaused(t, run) {
  return ['open', 'ready'].includes(t.status) && !run?.running && array(t.sessions).length > 0;
}
// ---- The ticket page: header (actions, title, one state line, stepper), tabs Overview / Tasks / Files / Activity, Properties.
const openChanges = t => array(t.checklist).filter(c => !c.done && !c.wont_do && changeTask(c.text, c.origin));
// One strip at the top of the ticket in every state: one status pill, one sentence, one main action (no stepper).
// Pill names are the master's status icons: todo, working, needs, check, done. The helper is just "Helper".
const stripHelperPill = helper => { const p = window.UI.helperPill(helper.state, helper.word); p.dataset.key = 'status-helper-' + helper.state; return p; };
// ORCH-742 (look B, picked by the owner 19 Nov; draft ORCH-730 section 6): Prepare on a saved ticket. While it is in
// Backlog the sentence under the title says where Prepare stands; the Prepared mark means described, not checked.
const PREPARE_STATES = ['waiting', 'preparing', 'prepared', 'not_prepared'];
function ticketPrepare(t) {
  const p = t && t.prepare;
  return p && typeof p === 'object' && PREPARE_STATES.includes(p.state) && t.status === 'open' ? p : null;
}
// Preparing is not Working: no live header, no helper bar, and Start stays on the page (a Start goes on into the work)
const ticketPreparing = t => ticketPrepare(t)?.state === 'preparing';
function ticketPrepareSentence(m) {
  if (m.prepare === 'preparing') return h('span', {className:'prepare-line', role:'status', 'data-key':'prepare-line'}, h('span', {className:'spinner', 'aria-hidden':'true'}), m.sentence);
  if (m.prepare === 'prepared') return [h('span', {className:'prepared-word', title:'Described by the helper, not checked', 'data-key':'prepared-mark'}, '☰ Prepared'), m.sentence.replace(/^Prepared/, '')];
  return m.sentence;
}
function ticketStripModel(t, run, fresh) {
  const q = questions(t)[0], asked = window.DashHelpers.askedAt(t, typeof needsList === 'function' ? needsList() : []), at = asked ? time(asked) : '';
  // the pill and its word come from the kit's one rule (ORCH-71): every page shows the same for the same ticket
  // ORCH-415: a helper that may be stuck is passed too (helperState gives null when none runs), so the pill never says no helper
  const s = window.UI.ticketState(t, window.DashHelpers.helperState(run, t));
  const m = sentence => ({pill:s.pill, word:s.word, helper:s.helper || undefined, sentence});
  // ORCH-548: Looks good given on the Review page and still being saved (Undo there for a few seconds)
  if (t.status === 'done' && t.accept_saving) return m('Done: your Looks good is being saved.');
  if (t.status === 'done') {
    const ev = ticketDoneEvent(t), when = window.DashHelpers.doneAt(t);
    return m('Done' + (when ? ' ' + time(when) : '') + (ev?.by ? ' · checked by ' + ticketActor(ev.by) : '') + '.');
  }
  if (q) {
    const ask = clean(window.DashHelpers.questionWords ? window.DashHelpers.questionWords(q.text || '') : q.text || '').replace(/\s+/g, ' ').trim();
    // who asked: the agent on the ticket by its own name (as Home says it), "Helper" only when none is known
    const asker = window.DashHelpers?.agentLabel ? window.DashHelpers.agentLabel(state?.settings, (run || state?.runs?.[t.id])?.claim) : 'Helper';
    return m(asker + ' asks: ' + (ask.length > 110 ? ask.slice(0, 107) + '…' : ask));
  }
  // ORCH-235: a dated or outside wait says what it waits for and until when, never "Needs you"
  if (s.word === 'Waiting') return m((clean(window.DashHelpers.waitWords(t, tickets(), v => localStamp(v))) || 'Waiting, with no date or reason given') + '.');
  if (t.status === 'review') {
    // a person moved it to Check by hand: say who, never that a helper finished
    const moved = ticketMovedBy(t, 'review');
    if (moved && !/^agent:/.test(moved.by || '') && moved.by !== 'orch') return m('Moved to Check by ' + ticketActor(moved.by) + (moved.at ? ' ' + time(moved.at) : '') + '.');
    return m('Helper finished' + (at ? ' ' + at : '') + '.');
  }
  if (t.bring_back?.state === 'waiting') return m('Helper has changes waiting for you.');
  const prep = ticketPrepare(t);
  if (prep) {
    const said = {waiting:'In line to be prepared. Start still works.', preparing:'Preparing: reading the links and filling in the ticket.',
      prepared:'Prepared' + (prep.at ? ' ' + time(prep.at) : '') + '. Press Start to begin.', not_prepared:'Not prepared yet. Start still works.'}[prep.state];
    return {...m(said), prepare:prep.state};
  }
  if (run?.running || run?.state === 'maybe-stale') {
    // the core's one helper state (ORCH-61): a helper that sits idle or is stuck never reads "Working" here
    if (s.helper) return m((s.helper.detail || s.word) + '.');
    return m(openChanges(t).length ? 'Helper is working on your change.' : 'Helper is working.');
  }
  if (window.DashHelpers.changesAsked(t) && (fresh || !run?.running)) return m('Sent back. Your helper makes a new version when it starts; press Start to begin now.');
  if (fresh) return m('Not started. Your helper begins when you press Start.');
  if (ticketPaused(t, run)) return m('Paused' + (at ? ' ' + at : '') + '.');
  // ORCH-415: In progress with no helper says so, as the Add to this ticket box below does
  if (t.status === 'active' && run?.state !== 'maybe-stale') return m('No helper is working on it right now.');
  return m(at ? 'Updated ' + at + '.' : '');
}
const taskTitle = task => clean(changeTask(task.text, task.origin)?.title || task.text);
// ORCH-904: the newest recorded run of this task failed: say so on the task, not only on the Overview.
const taskCheckFailed = (t, task) => !task.wont_do && t.proof?.per_item?.[task.id] === 'failed';
// ORCH-476: one word for a task that will not be done, the same as its button and the core ("Won't do", never "Skipped")
const taskWord = task => task.wont_do ? window.DashHelpers.WONT_DO : task.done ? 'Done' : task.state === 'doing' ? 'Working' : 'To do';
// The core's progress (state.counts, ORCH-476): the same numbers as every other page.
function ticketProgressCounts(t) {
  const p = window.DashHelpers.progressOf(state?.counts, t);
  return [p.done && p.done + ' done', p.wont_do && p.wont_do + " won't do", p.doing && p.doing + ' in progress', p.todo && p.todo + ' to do'].filter(Boolean).join(' · ');
}
// "Progress": counts and one row per task; the task the helper works on now is highlighted.
function ticketProgress(t, run) {
  const list = array(t.checklist);
  if (!list.length) return null;
  const current = run?.running ? list.find(c => !c.done && !c.wont_do && c.state === 'doing') : null;
  return h('section', {className:'card progress-card', 'data-key':'progress'}, h('div', {className:'section-head'}, h('h2', {}, 'Progress'), h('span', {className:'meta'}, ticketProgressCounts(t))),
    h('ol', {className:'task-list'}, list.map((c, i) => c === current
      ? h('li', {className:'current-task', 'data-key':'progress-' + (c.id || i)}, h('span', {className:'task-mark working', 'aria-hidden':'true'}, '◉'), h('div', {className:'grow'}, h('h3', {}, taskTitle(c)), h('p', {className:'meta'}, (hs => ['working', 'starting'].includes(hs?.state) ? 'Your helper is working on this task.' : (hs?.state === 'waiting' && hs.detail ? hs.detail : 'Your helper is on this task.'))(window.DashHelpers.helperState(run, t)))))
      : h('li', {className:'task-row' + (c.wont_do ? ' skipped' : ''), 'data-key':'progress-' + (c.id || i)}, h('span', {className:'task-mark' + (c.done && !c.wont_do ? ' good' : ''), 'aria-hidden':'true'}, c.wont_do ? '–' : c.done ? '✓' : '○'),
        h('div', {className:'grow'}, h('p', {className:'task-title'}, taskTitle(c)), c.wont_do && c.reason ? h('p', {className:'task-note meta'}, clean(c.reason)) : null), h('span', {className:'meta'}, taskWord(c))))));
}
// The helper's browser, live, next to the steps (ORCH-1494): only after a click on its small preview (the address
// says ?browser=open); side by side when the column has room, else on top of the steps (kit .bview-beside).
function ticketProgressBeside(t, progress) {
  if (snapshot || typeof browseViewIn !== 'function' || !browseViewIn(t.id)) return progress;
  return h('div', {className:'bview-beside', 'data-key':'bview-beside-' + t.id}, h('div', {className:'bview-beside-grid'},
    progress ? h('div', {className:'bview-steps'}, progress) : null,
    h('div', {className:'bview-host', 'data-live-browse':t.id, 'data-key':'bview-host-' + t.id})));
}
// The review card: "Result" = in short + the result preview (the verdict buttons live in the header strip).
function ticketReviewCard(t) {
  const found = reviewFile(t), file = found?.file, count = ticketFileEntries(t).filter(f => fileWho(f) === 'Helper').length;
  return h('section', {className:'card attention decision review-card', 'data-key':'review-card-' + t.id},
    h('div', {className:'section-head'}, h('h2', {}, 'Result'), count ? h('span', {className:'meta'}, count + (count === 1 ? ' file' : ' files')) : null),
    t.summary ? h('p', {className:'preserve-lines', 'data-key':'summary'}, h('strong', {}, 'In short. '), linkRefs(t, t.summary)) : null,
    t.verdict_needed ? h('p', {className:'meta', 'data-key':'ticket-verdict-needed'}, 'Marked done without your OK. Check the work, then click Looks good.') : null,
    file ? ticketResultFrame(t, found.kind, file) : h('p', {className:'meta'}, array(t.checklist).length ? 'No result file is attached. Each task below shows what was done and how it was checked.' : 'No result file and no tasks are attached.'),
    t.done_when ? h('p', {className:'review-check'}, 'Is this what you asked for? “', linkRefs(t, t.done_when), '”') : null,
    ticketProofLine(t));
}
// "What the helper did": the finished tasks as a short plain list (Check and Done); the full list is on the Tasks tab.
function ticketHelperDid(t) {
  if (!['review', 'done'].includes(t.status)) return null;
  const done = array(t.checklist).filter(c => c.done && !c.wont_do);
  if (!done.length) return null;
  const shown = done.slice(0, 6);
  return h('section', {className:'card helper-did', 'data-key':'helper-did'}, h('div', {className:'section-head'}, h('h2', {}, 'What the helper did')),
    h('ul', {className:'lines'}, shown.map(c => h('li', {}, taskTitle(c))), done.length > shown.length ? h('li', {className:'meta'}, '+ ' + (done.length - shown.length) + ' more on the Tasks tab') : null));
}
// What the helper (or you) said when a task was finished: the note shown in Results of a Done ticket.
function completionNotes(t) {
  if (t.status !== 'done') return [];
  const notes = [];
  array(t.checklist).forEach(c => { if (c.done && !c.wont_do) array(c.evidence).forEach(ev => {
    if ((ev.type || ev.kind) !== 'note') return;
    const body = clean(window.DashHelpers.cleanOutcome(ev.text) || window.DashHelpers.cleanOutcome(ev.ref)), head = clean(window.DashHelpers.cleanOutcome(ev.summary));
    if (head || body) notes.push({at:ev.at, head:head || body, body:head && body !== head ? body : ''});
  }); });
  notes.sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
  return notes.slice(0, 3);
}
function ticketCompletionNote(n, t) {
  return h('article', {className:'completion-note', 'data-key':'completion-note'}, h('p', {className:'meta eyebrow'}, 'Completion note' + (n.at ? ' · ' + time(n.at) : '')),
    h('h2', {}, linkRefs(t, n.head)), n.body ? h('p', {className:'muted preserve-lines'}, linkRefs(t, n.body)) : null);
}
function ticketResultsCard(t) {
  // ORCH-240: newest first, the same order as the Files tab opens with
  const time = x => Date.parse(x.file.mtime) || 0;
  const all = resultFiles(t).map((x, i) => [x, i]).sort((a, b) => time(b[0]) - time(a[0]) || a[1] - b[1]).map(x => x[0]), files = all.map(x => x.file), notes = completionNotes(t);
  if (!files.length && !notes.length) return null;
  const count = [notes.length ? notes.length + (notes.length === 1 ? ' note' : ' notes') : '', files.length ? files.length + (files.length === 1 ? ' file' : ' files') : ''].filter(Boolean).join(' · ');
  return h('section', {className:'card results', 'data-key':'results'}, h('div', {className:'section-head'}, h('h2', {}, 'Result'), h('span', {className:'meta'}, count)),
    notes.map(n => ticketCompletionNote(n, t)),
    all.length ? (t.status === 'done' ? ticketResultFrame(t, all[0].kind, all[0].file) : ticketFileRow(t, all[0].kind, all[0].file)) : null, all.slice(1, 4).map(x => ticketFileRow(t, x.kind, x.file)), files.length ? headerProof(t) : null);
}
// The ticket's results as the same widgets as on the live wall (ORCH-697, draft D), the notes of its finished steps above
// them; a click opens the big overlay. A read-only copy keeps the Result card above, and so does a ticket that hosts an
// open group: its file rows carry Share with group, which the widgets do not have yet (bundle ORCH-1185, issue 2280).
function ticketWidgets(t) {
  return !snapshot && typeof resultsHost === 'function' && !!window.UI?.result && !ticketHostsOpenGroup(t);
}
function ticketWidgetsCard(t) {
  const notes = t.status === 'review' ? [] : completionNotes(t);
  return h('section', {className:'card results', 'data-key':'results-widgets'}, h('div', {className:'section-head'}, h('h2', {}, 'Results')),
    notes.map(n => ticketCompletionNote(n, t)),
    resultsHost(t.id, {key:'ticket-results-' + t.id, empty:'Nothing yet. Pictures, pages and tables show up here.'}));
}
// A change you asked for: what you asked, and that new changes wait for your approval.
function ticketRequestCard(t) {
  const open = openChanges(t);
  if (!open.length || t.status === 'done') return null;
  return h('section', {className:'card change-request', 'data-key':'your-request'}, h('h2', {}, 'Your request'),
    open.map(c => h('div', {className:'request-row'}, h('p', {className:'preserve-lines'}, 'You asked: “' + clean(changeTask(c.text, c.origin).asked) + '”'), h('p', {className:'meta'}, c.state === 'doing' ? 'Your helper is on it' : 'To do yet'))),
    h('p', {className:'meta request-note'}, 'New changes wait for your approval before they count as done.'));
}
const TAB_ALIAS = {questions:'overview', history:'activity', artifacts:'files'};
function ticketSelectedTab(t) {
  const raw = tabFromAddress(t.id) || ticketTabs.get(t.id), tab = TAB_ALIAS[raw] || raw;
  return ['overview', 'tasks', 'files', 'activity'].includes(tab) ? tab : 'overview';
}
// The answers given through the Review stack (a question answered there carries a `decision`), newest first, in the
// shape of the kit's answer record. They show under the ticket's questions, not on a tab of their own.
function ticketReviewAnswers(t) {
  return array(t.questions).filter(q => q.answer != null && q.decision && typeof q.decision === 'object')
    .map(q => ({id:'core:q:' + t.id + ':' + q.id, ticket:t.id, key:q.id, text:q.text, by:(window.DashHelpers.listedName && window.DashHelpers.listedName(q.answered_by)) || q.answered_by, via:q.via, at:q.at, card:q.card || {}, shown:q.shown, decision:q.decision}))
    .sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
}
const ticketTabList = t => [['overview', 'Overview', null], ['tasks', 'Tasks', array(t.checklist).length], ['files', 'Files', ticketFileCount(t)], ['activity', 'Activity', ticketHistoryEntries(t, 'All').length]];
// ORCH-581 (owner picked draft E, 19 Nov): Properties shows only what is filled in. Everything empty, and every add-on
// this ticket has not used yet, comes back from one "+ Add" menu; a pick shows its row and opens its editor. Human
// review needed always shows (a safety switch, ORCH-424). Below 1100 px the same rail is a sheet behind a
// Properties button (railOpen), so there is one copy of every control.
const propsAdding = new Map();  // ticket id -> keys a person picked from + Add (their rows show while still empty)
const adding = (t, key) => !snapshot && !!propsAdding.get(t.id)?.has(key);
const hasValue = (t, f) => t[f] != null && String(t[f]).trim() !== '';
// An add-on is used on a ticket once one of its visible fields holds a value (false and 0 count; '' and [] do not).
function addonUsed(t, a) {
  const ext = (t.ext || {})[a.name];
  if (!ext || typeof ext !== 'object') return false;
  return array(a.ticket_fields?.fields).some(f => !f.hidden && f.key in ext && fieldText(f, ext[f.key]) !== '');
}
const addonEditable = a => array(a.ticket_fields?.fields).some(f => !f.hidden && !f.read_only);
const repeatsSet = t => addonViewRows(t, false).some(([, , addon]) => addon === repeatsAddon());
function ticketProperties(t, parent) {
  const field = (label, value, key, cls) => h('div', {'data-key':key ? 'prop-' + key + '-' + t.id : null, className:cls || null}, h('dt', {}, label), h('dd', {}, value));
  const done = t.status === 'done';
  const show = (key, filled) => filled || adding(t, key);
  return h('aside', {className:'side-panel properties' + (done ? ' compact' : ''), 'aria-labelledby':'ticket-properties-' + t.id, 'data-key':'properties-' + t.id},
    h('div', {className:'rail-sheet-h'}, h('h2', {id:'ticket-properties-' + t.id}, 'Properties'),
      snapshot ? null : ticketButton(iconEl('x'), 'ghost icon sm narrow-only', () => railToggle(t, false), {'aria-label':'Close Properties', 'data-key':'props-close-' + t.id})),
    h('dl', {className:'ticket-details ed-list'},
      show('partOf', !!parent) ? field('Part of', snapshot ? h('a', {href:href(parent.id)}, partName(parent)) : partOfField(t, parent), 'part-of') : null,
      show('release', !!t.release) ? field('Release', releaseField(t), 'release') : null,
      field('Human review needed', humanReviewField(t)),
      show('owner', hasValue(t, 'owner')) ? field('Owner', inlineField(t, 'owner'), 'owner') : null,
      show('due', hasValue(t, 'due')) ? field('Due', inlineField(t, 'due'), 'due') : null,
      show('done_when', hasValue(t, 'done_when')) ? field('Done when', inlineField(t, 'done_when'), 'done-when', 'rail-long') : null,
      costValue(t) ? field('Time · cost', costValue(t)) : null, addonPropertyRows(t),
      show('priority', prioritySet(t)) ? field('Priority', priorityField(t), 'priority') : null,
      show('model', !!modelChoice(t)) ? field('Helper strength', modelField(t), 'model') : null,
      show('kind', !!t.kind?.name) ? field('Kind', kindField(t), 'kind') : null),
    propertiesAddMenu(t, parent),
    linksCard(t),
    copyLine(t));
}
// Created and updated (or finished) in one quiet line at the foot of the rail.
function railStamp(t) {
  const finished = t.status === 'done' ? window.DashHelpers.doneAt(t) : null;
  const stamp = [t.created_at ? 'Created ' + localStamp(t.created_at) : '',
    t.status === 'done' ? (finished ? 'finished ' + localStamp(finished) : '') : (t.updated_at ? 'updated ' + localStamp(t.updated_at) : '')].filter(Boolean).join(' · ');
  return stamp ? h('p', {className:'meta', 'data-key':'ticket-stamp-' + t.id}, stamp) : null;
}
// The one place every empty property and every unused add-on comes back (draft E's "+ Add").
function propertiesAddMenu(t, parent) {
  if (snapshot) return null;
  const item = (key, label) => ticketButton(label, 'menu-item', e => propAdd(t, key, e?.currentTarget), {role:'menuitem', 'data-key':'prop-add-' + key + '-' + t.id});
  const props = [
    [!parent, 'partOf', 'Part of'], [!hasValue(t, 'owner'), 'owner', 'Owner'], [!hasValue(t, 'due'), 'due', 'Due'],
    [!hasValue(t, 'done_when'), 'done_when', 'Done when'], [!t.release, 'release', 'Mark as a release'],
    [!prioritySet(t), 'priority', 'Priority'], [!modelChoice(t), 'model', 'Helper strength'], [!t.kind?.name, 'kind', 'Kind'], [!referenceRows(t).length, 'links', 'Reference']]
    .filter(([missing, key]) => missing && !adding(t, key)).map(([, key, label]) => item(key, label));
  const fromAddons = addons().filter(a => addonEditable(a) && !addonUsed(t, a) && !adding(t, 'addon:' + a.name))
    .map(a => item('addon:' + a.name, clean(a.ticket_fields.section) || addonLabel(a)));
  if (repeatsAddon() && !repeatsSet(t)) fromAddons.push(item('repeat', 'Repeat…'));
  if (!props.length && !fromAddons.length) return null;
  return h('details', {className:'menu props-add', 'data-key':'props-add-' + t.id},
    h('summary', {className:'btn ghost xs', 'aria-label':'Add a property'}, iconEl('plus'), 'Add'),
    h('div', {className:'menu-pop', role:'menu'}, props.length ? [h('p', {className:'eyebrow'}, 'Properties'), props] : null,
      fromAddons.length ? [h('p', {className:'eyebrow'}, 'From add-ons'), fromAddons] : null));
}
// A pick from + Add: Release and Repeat act at once; every other pick shows its row and opens its editor.
async function propAdd(t, key, trigger) {
  trigger?.closest('details')?.removeAttribute('open');
  if (key === 'repeat') return repeatsDialog(t.id, repeatsAddon());
  if (key === 'release') {
    const result = await act('ticket.edit', {ticket:t.id, release:true, if_revision:(ticketOf(t.id) || t).revision});
    if (!result.ok) window.orch.toast(changeError(result), 'error');
    return;
  }
  if (!propsAdding.has(t.id)) propsAdding.set(t.id, new Set());
  propsAdding.get(t.id).add(key);
  render();
  const rail = document.getElementById('ticket-rail-' + t.id) || document;
  const at = key === 'links' ? '[data-action="link-add"]' : key.startsWith('addon:') ? '[data-action="field"][data-addon="' + CSS.escape(key.slice(6)) + '"]'
    : key === 'partOf' ? 'select[aria-label="Part of"]' : key === 'model' ? 'select[aria-label="Helper strength"]' : key === 'priority' ? 'select[aria-label="Priority"]' : key === 'kind' ? 'select[aria-label="Kind"]' : '[data-action="inline"][data-field="' + key + '"]';
  const target = rail.querySelector(at);
  if (target?.tagName === 'SELECT') target.focus(); else target?.click();
}
// How many filled things the rail holds besides owner and due (those stay in the line under the title when narrow).
function railCount(t, parent) {
  const used = addons().filter(a => a.ticket_fields && addonUsed(t, a)).length;
  return [!!parent, !!t.release, hasValue(t, 'done_when'), !!costValue(t), !!modelChoice(t), referenceRows(t).length > 0].filter(Boolean).length + addonPropertyRows(t).length + used;
}
const railOpen = {id:null, trigger:null, keys:false};
const railNarrow = () => !window.matchMedia || window.matchMedia('(max-width:1099px)').matches;
function railToggle(t, open, trigger) {
  if (open && !railOpen.keys) {
    railOpen.keys = true;
    document.addEventListener('keydown', railKeys);
    // wider than the sheet needs: the rail is back in the page, so the sheet closes without moving the keyboard
    window.matchMedia?.('(min-width:1100px)').addEventListener?.('change', e => { if (e.matches && railOpen.id) { railOpen.id = null; render(); } });
  }
  railOpen.id = open ? t.id : null;
  if (open) railOpen.trigger = trigger?.dataset?.key || null;
  render();
  const back = open ? document.querySelector('[data-key="props-close-' + t.id + '"]') : railOpen.trigger && document.querySelector('[data-key="' + CSS.escape(railOpen.trigger) + '"]');
  back?.focus();
}
// While the sheet is open: Esc closes it (the keyboard goes back to Properties) and Tab stays inside it.
function railKeys(e) {
  const rail = railOpen.id && railNarrow() ? document.getElementById('ticket-rail-' + railOpen.id) : null;
  if (!rail) return;
  if (e.key === 'Escape') { e.preventDefault(); railToggle({id:railOpen.id}, false); return; }
  if (e.key !== 'Tab') return;
  const stops = [...rail.querySelectorAll('button, select, input, textarea, summary, a[href], [tabindex="0"]')].filter(n => !n.disabled && n.offsetParent !== null);
  if (!stops.length) return;
  const first = stops[0], last = stops[stops.length - 1], at = document.activeElement;
  if (e.shiftKey ? at === first || !rail.contains(at) : at === last || !rail.contains(at)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
}
// A click beside the open sheet closes it (narrow screens only).
function railScrim(t) {
  const scrim = h('div', {className:'rail-scrim narrow-only', 'aria-hidden':'true', 'data-key':'rail-scrim-' + t.id});
  scrim.onclick = () => railToggle(t, false);
  return scrim;
}
// Narrow screens only: Properties (with how many things it holds) and the owner / due line under the title.
function railButton(t) {
  if (snapshot) return null;
  const n = railCount(t, window.DashHelpers.parentOf(tickets(), t)), open = railOpen.id === t.id;
  return ticketButton(['Properties', n ? h('span', {className:'chip'}, String(n)) : null], 'ghost sm narrow-only', e => railToggle(t, !open, e?.currentTarget),
    {'aria-haspopup':'dialog', 'aria-expanded':String(open), 'aria-controls':'ticket-rail-' + t.id, 'data-key':'props-open-' + t.id});
}
function railFacts(t) {
  const parts = [hasValue(t, 'owner') ? 'Owner ' + name(String(t.owner)) : '', hasValue(t, 'due') ? 'Due ' + dueText(t) : ''].filter(Boolean);
  return parts.length ? h('p', {className:'t-meta narrow-only', 'data-key':'rail-facts-' + t.id}, parts.join(' · ')) : null;
}

// A ticket made outside this page (command line, a helper) may not be in the state we hold yet: read the workspace
// fresh, a few times for about 5 s, before saying it is gone.
const ticketLookups = new Map();
let ticketLookupWait = 1000, ticketLookupLimit = 5000;
async function lookupTicket(id, entry) {
  // a finished ticket is not in the live state (ORCH-522): read it alone first
  if (!fullMissing.has(String(id)) && await loadFullTicket(id) && ticketOf(id)) { ticketLookups.delete(id); return; }
  const stop = Date.now() + ticketLookupLimit;
  for (;;) {
    try {
      const res = await fetch('/api/state?fresh=1', {cache:'no-store'});
      if (res.ok) { mutation++; accept(await res.json()); if (ticketOf(id)) { ticketLookups.delete(id); return; } }
    } catch (_) { /* Try again until the time is up. */ }
    if (Date.now() >= stop) break;
    await new Promise(done => setTimeout(done, ticketLookupWait));
  }
  entry.gone = true;
  render();
}
function missingTicket(id) {
  if (snapshot || !id) return ticketNotFound();
  let entry = ticketLookups.get(id);
  if (!entry) { entry = {gone:false}; ticketLookups.set(id, entry); lookupTicket(id, entry); }
  return entry.gone ? ticketNotFound() : skeletonFor('ticket');
}
// ORCH-742 (look B): What I found, folded into one line under What was asked (what Prepare read, ORCH-740). The sources
// it could not open stay in sight below the fold (same box), each with one action: attach it in Add to this ticket.
// Written by a helper: shown as text, links only when they are web addresses.
function ticketFound(t) {
  const f = t && t.found;
  if (!f || typeof f !== 'object') return null;
  const all = array(f.sources).filter(s => s && typeof s === 'object' && typeof s.name === 'string' && s.name.trim());
  const read = all.filter(s => s.opened === true), closed = all.filter(s => s.opened !== true);
  const facts = array(f.facts).filter(x => typeof x === 'string' && x.trim());
  if (!all.length && !facts.length) return null;
  const web = s => /^https?:\/\/[^\s]+$/i.test(String(s.link || '').trim()) ? String(s.link).trim() : null;
  const attach = !snapshot && t.status !== 'done';
  const row = (s, i, shut) => h('li', {className:'found-src' + (shut ? ' found-closed' : ''), 'data-key':(shut ? 'found-closed-' : 'found-read-') + i},
    h('b', {}, clean(s.name)),
    shut ? (attach ? ticketButton('Attach it', 'outline sm', () => ticketFocusTalk(t.id), {'data-key':'found-attach-' + i}) : null)
      : web(s) ? h('a', {className:'btn ghost sm', href:web(s), target:'_blank', rel:'noopener noreferrer'}, 'Open ↗') : null,
    (shut ? s.why : s.lines) ? h('p', {}, clean(shut ? s.why : s.lines)) : null);
  const count = read.length ? read.length + (read.length === 1 ? ' source read' : ' sources read') : 'Nothing could be read';
  const body = [facts.length ? h('ul', {className:'found-facts', 'aria-label':'Key facts'}, facts.map(x => h('li', {}, clean(x)))) : null,
    read.length ? h('ul', {className:'found-sources', 'aria-label':'Sources read'}, read.map((s, i) => row(s, i, false))) : null,
    f.at ? h('p', {className:'meta'}, 'Read ' + time(f.at)) : null];
  return h('section', {className:'card asked found-card', 'data-key':'found-card'},
    h('details', {className:'found-fold', 'data-key':'found'},
      h('summary', {}, h('h2', {}, 'What I found'), h('span', {className:'meta'}, count),
        closed.length ? h('span', {className:'chip warning'}, '! ' + closed.length + ' could not be opened') : null,
        h('span', {className:'found-chev', 'aria-hidden':'true'}, '›')),
      h('div', {className:'found-body'}, body)),
    closed.length ? h('ul', {className:'found-sources found-closed-list', 'aria-label':'Could not open', 'data-key':'found-closed'}, closed.map((s, i) => row(s, i, true))) : null);
}
function ticketFocusTalk(tid) {
  const host = document.querySelector('[data-ticket-talk="' + CSS.escape(tid) + '"]');
  if (!host) return;
  host.scrollIntoView({block:'center', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  host.querySelector('textarea, input, button')?.focus({preventScroll:true});
}
// The header strip (master .strip): pill, title, one sentence, the main action, then the tabs.
function ticketStrip(t, run, fresh, planQ, menu, tabs, selected) {
  const m = ticketStripModel(t, run, fresh), actions = [], kidsDone = !questions(t).length && !run?.running ? ticketKidsAllDone(t) : null;
  if (kidsDone) { m.sentence = (kidsDone.length === 1 ? 'Its sub-ticket is done.' : 'All ' + kidsDone.length + ' sub-tickets are done.') + ' Mark it Done when nothing else is left.'; delete m.prepare; }
  const quiet = t.quiet_since ? window.DashHelpers.quietWords(t.quiet_since, now()) : '';  // G2
  if (quiet) m.sentence = (/^(Updated |No helper is working on it)/.test(m.sentence || '') || !m.sentence ? '' : m.sentence + ' ') + quiet + '.';  // one line: Quiet since replaces Updated (and the no-helper line, ORCH-415)
  if (!snapshot) {
    // Reopen puts it back in To do (ORCH-235): Working is only shown while a helper runs
    if (t.status === 'done') actions.push(ticketButton('Reopen', 'outline sm', () => moveTicket(t.id, 'ready'), {'data-key':'ticket-reopen'}));
    else if (t.status === 'review') actions.push(ticketChangesEditor(t));
    else if (m.pill === 'needs' && questions(t).length) { if (!planQ) actions.push(ticketButton('Answer', 'primary sm', e => focusTicketAnswer(t.id, e?.currentTarget), {'data-key':'ticket-answer'})); }
    else if (kidsDone) actions.push(ticketButton('Mark Done', 'primary sm', () => moveTicket(t.id, 'done'), {'data-key':'ticket-kids-done'}));
    // ORCH-255: a start is on the page in every state while no helper runs. ORCH-475: it is the one Start button (pages/start.js):
    // Continue when an earlier session can be reopened, else Start helper; the caret opens the Start choice. Never filled (ORCH-415).
    // ORCH-415 (UX D2): the start's cost sits above it and a cheaper choice beside it; next to Reopen, Answer or the changes
    // box it stays the plain Start button. A helper that may be stuck is started again with the agent bar's Start anyway.
    // While Prepare runs (ORCH-742) Start still shows: the prepare run is not the work.
    if ((!run?.running || ticketPreparing(t)) && run?.state !== 'maybe-stale') actions.push(ticketStartPick(t, actions.length > 0));
    // one start button (owner, ORCH-1466): the live layer opens from the ⋯ menu (ticketFocusMenuItem), not a second start here
    const chatBtn = typeof ticketChatButton === 'function' ? ticketChatButton(t) : null;  // the ticket's chat (ORCH-1168)
    if (chatBtn) actions.push(chatBtn);
    actions.push(railButton(t));
    if (menu) actions.push(menu);
  }
  const icon = window.UI?.statusIcon ? window.UI.statusIcon(m.pill) : null;
  if (ticketHelperLive(t, run)) return ticketWorkingStrip(t, run, m, quiet, menu, tabs);
  return h('section', {className:'strip ticket-strip', 'data-key':'ticket-strip-' + t.id},
    h('div', {className:'strip-h'},
      m.helper && window.UI?.helperPill ? stripHelperPill(m.helper) : h('span', {className:'pill status-change ' + m.pill, 'data-key':'status-' + t.status + '-' + m.pill}, icon, m.word),
      h('div', {className:'grow ticket-strip-text'}, h('h1', {className:'t-row'}, window.DashHelpers.keyTag(t, h), window.DashHelpers.kindTag(t, h), inlineField(t, 'title')), h('p', {className:'t-meta', 'data-key':'ticket-sentence'}, ticketPrepareSentence(m)), railFacts(t)),
      actions.length ? h('div', {className:'row ticket-strip-actions'}, actions) : null),
    tabs);
}
// ORCH-415 (UX D2): the start button outlined, its cost in one line above it. One start button (owner, ORCH-1466): the
// cheaper model is picked in the caret's Start choice (Fresh start: Model), not with a second button beside it.
function ticketStartPick(t, compact = false) {
  // ORCH-1663 (click-through finding 18): Start helper here opens the session in the live pane, as Watch live does
  const host = startHost(t, 'ticket-start', {started:x => { if (typeof liveFocusButton === 'function' && liveFocusButton(x) && window.LiveLayer?.open) window.LiveLayer.open(x.id, true); }});
  if (compact || !host) return host;
  const m = modelChoice(t), verb = array(t.sessions).length ? 'Continue' : 'Start helper';
  return h('div', {className:'cost-pick', 'data-key':'ticket-start-pick', role:'group', 'aria-label':verb},
    h('p', {className:'meta', 'data-key':'ticket-start-cost', id:'start-cost-' + t.id}, window.DashHelpers.startCostWords(t, m ? MODEL_NAMES[m.name] : '')),
    h('div', {className:'row'}, host));
}
// Open in <layer name>, first in the ⋯ menu while no helper runs (owner, ORCH-1466: the live layer stays findable without
// a second start); a running helper's header keeps its Watch button. The name comes from the add-on (liveLayerName).
function ticketFocusMenuItem(t, run) {
  if (ticketHelperLive(t, run) || typeof liveFocusButton !== 'function' || !liveFocusButton(t)) return null;
  return ticketButton('Open in ' + liveLayerName(), 'menu-item', () => window.LiveLayer.open(t.id, true), {role:'menuitem', 'data-key':'ticket-open-layer'});
}
// ORCH-70 (owner 16 Nov, as drawn): while a helper runs the header holds it all. One line above the title (key, the
// ORCH-61 state word, the helper, minutes), one Watch live, Stop and the terminal commands in the ⋯ menu. No helper
// bar and no Live session card below it; the box goes, so the page reads calmer.
const ticketHelperLive = (t, run) => !snapshot && window.DashHelpers.helperAlive(t, run) && run?.claim?.mode !== 'oneshot' && !questions(t).length && !ticketPreparing(t);
function ticketWorkingStrip(t, run, m, quiet, menu, tabs) {
  const helper = window.DashHelpers.helperState(run, t) || {state:'working', word:'Working', detail:''};
  const agent = window.DashHelpers.agentLine(t, run, Date.now(), null, state.settings).agent;
  const minutes = Number.isFinite(run?.age_seconds) ? Math.max(1, Math.floor(run.age_seconds / 60)) + ' min' : '';
  const key = window.DashHelpers.ticketKey(t), dot = () => h('span', {'aria-hidden':'true'}, '·');
  const pill = window.UI?.helperPill ? stripHelperPill(helper) : h('span', {className:'pill working', 'data-key':'status-helper-' + helper.state}, helper.word);
  const kind = window.DashHelpers.kindTag(t, h)?.[1] || null;  // ORCH-906: 'ORCH-7 · Epic · Working'
  const parts = [key ? h('span', {className:'key'}, key) : null, kind, pill, agent ? name(agent) : null, minutes].filter(Boolean);
  const kicker = h('p', {className:'t-meta strip-kicker', 'data-key':'ticket-kicker'}, parts.flatMap((x, i) => i ? [dot(), typeof x === 'string' ? h('span', {}, x) : x] : [x]));
  // a helper that is not plain working (idle, stuck, waits) still says why in one quiet line; so does "Quiet since"
  const why = helper.state !== 'working' && helper.detail ? clean(helper.detail) + '.' : '';
  const sentence = [why, quiet ? quiet + '.' : ''].filter(Boolean).join(' ');
  const focusBtn = typeof liveFocusButton === 'function' ? liveFocusButton(t, true) : null;
  if (focusBtn) focusBtn.className = 'btn primary sm';  // the one filled button while a helper runs
  const actions = [focusBtn, typeof ticketChatButton === 'function' ? ticketChatButton(t) : null, railButton(t), menu].filter(Boolean);
  return h('section', {className:'strip strip-plain ticket-strip', 'data-key':'ticket-strip-' + t.id},
    h('div', {className:'strip-h'},
      h('div', {className:'grow ticket-strip-text'}, kicker, h('h1', {className:'t-title'}, inlineField(t, 'title')),
        sentence ? h('p', {className:'t-meta', 'data-key':'ticket-sentence'}, sentence) : null, railFacts(t)),
      actions.length ? h('div', {className:'row ticket-strip-actions'}, actions) : null),
    tabs);
}
// The ⋯ menu items for a running helper: Stop first, then the two terminal commands (Watch is read only, Take over types).
function ticketHelperMenuItems(t, run) {
  if (!ticketHelperLive(t, run)) return null;
  const helper = window.DashHelpers.helperState(run, t), idle = helper && ['idle', 'stuck'].includes(helper.state);
  const ref = typeof t.key === 'string' && t.key ? t.key : t.id;
  const copy = (label, command, k) => ticketButton([iconEl('copy'), label], 'menu-item', async () => {
    try { await navigator.clipboard.writeText(command); window.orch.toast('Copied', 'ok'); }
    catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
  }, {role:'menuitem', title:command, 'data-key':'live-copy-' + k});
  return [ticketButton(idle ? 'Stop idle helper' : 'Stop', 'menu-item', () => act('run.stop', {ticket:t.id}), {role:'menuitem', 'data-key':'ticket-stop'}),
    run?.claim?.mode === 'oneshot' ? null : copy('Copy watch command', 'orch run attach ' + ref + ' --watch', 'watch'),
    run?.claim?.mode === 'oneshot' ? null : copy('Copy take-over command', 'orch run attach ' + ref, 'take')];
}
// ORCH-248: "Show me the plan first" stays visible on the ticket after it was made (the plan card only shows while the plan waits).
function ticketPlanFirstLine(t, planShown) {
  if (!t.plan_first || planShown || ['done', 'dropped'].includes(t.status)) return null;
  const planned = array(t.questions).some(q => String(q.text || '').startsWith('Plan ready') && q.answer != null);
  return h('p', {className:'meta ticket-plan-first', 'data-key':'plan-first-' + t.id}, planned ? 'You asked to see the plan first. You have approved it.' : 'You asked to see the plan first. The helper waits for your OK before work starts.');
}
// ORCH-235: the ticket page offers the same places as the board and the list (Waiting asks for a date and a reason,
// Superseded for the ticket that replaces it); the lane the ticket is in now is left out.
function ticketMoveItems(t) {
  const here = window.DashHelpers.laneOf(t, t.status, questions(t).length > 0);
  return MOVE_CHOICES.filter(([lane]) => lane !== here).map(([lane, label]) => ticketButton(label, 'menu-item', () => moveToLane(t.id, lane), {role:'menuitem', 'data-key':'ticket-move-' + lane}));
}
function detail(t) {
  if (!t) return missingTicket(route().id);
  // a live row cut short (ORCH-522): read the whole ticket once, the row itself only when that read failed
  if (t.slim && !snapshot && !fullMissing.has(String(t.id))) { loadFullTicket(t.id); return skeletonFor('ticket'); }
  ticketLookups.delete(t.id);
  const openQuestions = questions(t), selected = ticketSelectedTab(t);
  const run = state.runs?.[t.id], sessions = array(t.sessions);
  const parent = window.DashHelpers.parentOf(tickets(), t), children = window.DashHelpers.childrenOf(tickets(), t);
  loadArtifacts(t, selected === 'files');
  loadRelease(t);
  const fresh = (!sessions.length && !run?.running || !!ticketPrepare(t)) && ['open', 'ready'].includes(t.status) && !(typeof justStarted === 'function' && justStarted(t.id));
  const planQ = t.status !== 'done' && t.plan_first && openQuestions[0] && String(openQuestions[0].text || '').startsWith('Plan ready') ? openQuestions[0] : null;
  const working = !fresh && !planQ && !['done', 'review'].includes(t.status), helperLive = ticketHelperLive(t, run);
  const filled = f => t[f] != null && String(t[f]).trim() !== '';
  const note = snapshot ? (filled('note') ? h('p', {className:'muted preserve-lines', 'data-key':'note'}, clean(t.note)) : null) : h('div', {className:'ticket-note', 'data-key':'ticket-note'}, inlineField(t, 'note'));
  const menuFor = () => snapshot || (t.status === 'done' && !repeatsAddon()) ? null : h('details', {className:'menu', 'data-key':'ticket-menu-' + t.id}, h('summary', {className:'btn ghost icon sm', 'aria-label':'More ticket actions'}, iconEl('more')),
    h('div', {className:'menu-pop', role:'menu'}, ticketFocusMenuItem(t, run), ticketHelperMenuItems(t, run), t.status === 'done' ? null : ticketMoveItems(t),
      repeatsAddon() ? [ticketButton('Repeat…', 'menu-item', () => repeatsDialog(t.id, repeatsAddon()), {role:'menuitem', 'data-key':'ticket-repeat'})] : null));
  // ORCH-827: a ticket that runs by itself gets the role page (draft A2): runs, schedule and chat instead of tasks
  if (typeof roleOf === 'function' && roleOf(t)) return roleDetail(t, run, parent, menuFor());
  const menu = menuFor();
  const tabs = ticketTabList(t);
  const panel = (id, label, body) => h('section', {id:'ticket-panel-' + id, role:snapshot ? null : 'tabpanel', 'aria-labelledby':snapshot ? null : 'ticket-tab-' + id, className:'stack ticket-panel', hidden:!snapshot && selected !== id, tabindex:'0'}, snapshot ? h('h2', {}, label) : null, body);
  const story = overviewEntries(t, allArtifactFiles(t)), request = overviewRequest(t, note, story.request);
  const overview = [
    ticketBringBackRow(t),
    t.status !== 'done' && openQuestions.length ? (planQ ? ticketPlan(t, planQ, children) : ticketQuestion(t, openQuestions[0], true)) : null,
    t.status !== 'done' ? openQuestions.slice(1).map(q => ticketQuestion(t, q)) : null,
    ticketPlanFirstLine(t, !!planQ),
    ticketReleaseLine(t),
    t.status === 'review' ? ticketReviewCard(t) : null,
    ticketRequestCard(t),
    working && !helperLive ? agentBar(t) : null, working && !helperLive ? sharedFolderLine(t) : null, working && !helperLive ? liveSessionStrip(t) : null,
    ticketFound(t),
    t.summary && t.status !== 'review' ? h('p', {className:'muted preserve-lines', 'data-key':'summary'}, 'In short: ', linkRefs(t, t.summary)) : null,
    working && helperLive ? sharedFolderLine(t) : null,
    // a Done ticket keeps its result on top; while it is worked on, its files are messages in the history
    ticketWidgets(t) ? ticketWidgetsCard(t) : t.status === 'done' ? ticketResultsCard(t) : null,
    ticketHelperDid(t),
    ticketOutcomeCard(t),
    // the helper's browser, small and live (ORCH-1494): right above the steps, so it shows without scrolling
    typeof browsePeekHost === 'function' ? browsePeekHost(t.id, 'ticket') : null,
    ticketProgressBeside(t, planQ || ['review', 'done'].includes(t.status) ? null : ticketProgress(t, run)),
    planQ ? null : ticketParts(t, children),
    addonRows(t), ticketLinks(t),
    // ORCH-777: the one-line write box, the history newest first, and what you asked always last
    ticketTalkCard(t),
    window.UI?.appliesNow && ticketReviewAnswers(t).length ? window.UI.appliesNow(ticketReviewAnswers(t), {fileUrl:(typeof reviewApi === 'function' ? reviewApi() : null)?.fileUrl || (() => ''), now:new Date(), showTicket:false}) : null,
    overviewHistory(t, story.entries),
    request];
  return fragment(h('div', {className:'ticket-page', 'data-key':'ticket-page-' + t.id},
    parent ? h('a', {href:href(parent.id), className:'muted ticket-parent'}, (parent.release ? 'Part of the release ' : parent.epic ? 'Part of ' : 'Sub-ticket of ') + partName(parent)) : null,
    ticketStrip(t, run, fresh, planQ, menu, snapshot ? null : h('div', {className:'tabs ticket-tabs', role:'tablist', 'aria-label':'Ticket'}, tabs.map(([id, label, count]) =>
      ticketButton([label, count != null ? ' ' : null, count != null ? h('span', {className:'tab-count'}, String(count)) : null], 'ghost', null,
        {id:'ticket-tab-' + id, role:'tab', 'aria-selected':String(selected === id), 'aria-controls':'ticket-panel-' + id, tabindex:selected === id ? '0' : '-1', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':id, 'data-key':'ticket-tab-' + id}))), selected),
    h('div', {className:'columns ticket-layout' + (selected === 'files' ? ' wide' : '')},
      h('div', {className:'stack story'},
        panel('overview', 'Overview', overview),
        panel('tasks', 'Tasks', ticketTasksPanel(t)),
        panel('files', 'Files', artifactsPanel(t)),
        panel('activity', 'Activity', ticketHistoryPanel(t))),
      // a read-only copy keeps the rail in the page at every width (it has no Properties button)
      h('div', {className:'stack ticket-side' + (snapshot ? '' : ' rail-sheet'), id:'ticket-rail-' + t.id, 'data-open':String(railOpen.id === t.id), 'aria-label':'Properties', 'data-key':'ticket-rail-' + t.id,
        role:railOpen.id === t.id ? 'dialog' : null, 'aria-modal':railOpen.id === t.id ? 'true' : null},
        ticketProperties(t, parent), fieldSections(t), railStamp(t)),
      snapshot || railOpen.id !== t.id ? null : railScrim(t))));
}

// ORCH-189: Time · cost, only when the helper estimated it or worked on it (read-only).
function costValue(t) {
  const text = window.DashHelpers.costLine(t);
  return text ? h('span', {className:'meta', 'data-key':'ticket-cost'}, text) : null;
}
const MULTILINE = ['note', 'done_when'];
const FIELD_LABEL = {title:'title', owner:'owner', due:'due date', note:'what you asked', done_when:'what done looks like'};
const FIELD_HINT = {title:'Untitled', owner:'Not chosen yet', due:'Not set', note:'Add a note', done_when:'Say what should be true when it is done'};
// A value on the ticket page: a plain click turns it into a field; Enter or leaving it saves, Esc cancels.
// The model this ticket's helper runs on (ORCH-49): orch picks Sonnet or Opus before each start until a person
// chooses one here; "Auto" hands it back. Haiku (fast) and Fable (drafts) only a person picks (owner
// 17 Nov, ORCH-257). A running helper switches when its turn ends, else it applies from the next start.
const MODEL_NAMES = {haiku:'Haiku', sonnet:'Sonnet', opus:'Opus', fable:'Fable'};
function modelChoice(t) {
  const m = t.model && MODEL_NAMES[t.model.name] ? t.model : null;
  return m ? {name:m.name, auto:m.by === 'orch', why:m.why ? clean(String(m.why)) : ''} : null;
}
// ORCH-156: what this ticket is part of (an epic, another ticket); a person puts it under one that exists or takes
// it out. Never itself or a ticket inside it; epics first. FOLLOW-UP: kit select, a native one like Model until then.
function partOfField(t, parent) {
  const was = parent ? parent.id : '';
  const select = h('select', {'aria-label':'Part of', 'data-key':'part-of-' + t.id},
    h('option', {value:''}, 'Not part of another ticket'),
    window.DashHelpers.parentChoices(tickets(), t).map(p => h('option', {value:p.id}, [p.key, clean(p.title)].filter(Boolean).join(' ') + (p.release ? ' (release)' : p.epic ? ' (has parts)' : ''))));
  select.value = was;
  select.onchange = async () => {
    const result = await act('ticket.edit', {ticket:t.id, parent:select.value || null, if_revision:(ticketOf(t.id) || t).revision});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); select.value = was; }
  };
  return select;
}
// ORCH-37 (owner picked B): a release is a ticket of its own; the epics and tickets that ship together sit under it.
// One switch marks this ticket as a release or takes the mark off; its tickets stay where they are.
function releaseField(t) {
  const on = !!t.release;
  if (snapshot) return el('span', 'ed-ro', on ? 'Yes, its tickets go live together' : 'No');
  const sw = h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':String(on), 'aria-label':'This ticket is a release', title:on ? 'Its tickets go live together' : 'Mark it as a release', 'data-key':'release-' + t.id});
  sw.onclick = async () => {
    if (sw.disabled) return;
    sw.disabled = true; sw.setAttribute('aria-checked', String(!on));
    const result = await act('ticket.edit', {ticket:t.id, release:!on, if_revision:(ticketOf(t.id) || t).revision});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); sw.setAttribute('aria-checked', String(on)); }
    sw.disabled = false;
  };
  return sw;
}
// ORCH-424: Human review needed. On unless the person turns it off (no field = on, also for older tickets); while
// it is on nothing on this ticket is accepted without a person. The same switch as Release.
function humanReviewField(t) {
  const on = t.human_review !== false;
  if (snapshot) return el('span', 'ed-ro', on ? 'Yes, nothing is accepted without you' : 'No');
  const sw = h('button', {type:'button', className:'switch', role:'switch', 'aria-checked':String(on), 'aria-label':'Human review needed', title:on ? 'Nothing is accepted without you' : 'Work may be accepted without you', 'data-key':'human-review-' + t.id});
  sw.onclick = async () => {
    if (sw.disabled) return;
    sw.disabled = true; sw.setAttribute('aria-checked', String(!on));
    const result = await act('ticket.edit', {ticket:t.id, human_review:!on, if_revision:(ticketOf(t.id) || t).revision});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); sw.setAttribute('aria-checked', String(on)); }
    sw.disabled = false;
  };
  return sw;
}
// What kind of work this ticket is (ORCH-645): the helper that tidies a new ticket sets it; a person changes it
// here. Settings says which kinds are accepted for the person by themselves; Draft or design never.
const KIND_NAMES = {bug:'Bug', small_bug:'Small bug', feature:'New feature', small_feature:'Small feature', draft:'Draft or design', other:'Other'};
function kindField(t) {
  const was = t.kind && KIND_NAMES[t.kind.name] ? t.kind.name : '';
  if (snapshot) return el('span', 'ed-ro', was ? KIND_NAMES[was] : 'Not set yet');
  const select = h('select', {'aria-label':'Kind', 'data-key':'kind-' + t.id},
    was ? null : h('option', {value:''}, 'Not set yet'),
    Object.entries(KIND_NAMES).map(([k, label]) => h('option', {value:k}, label)));
  select.value = was;
  select.onchange = async () => {
    const result = await act('ticket.kind', {ticket:t.id, kind:select.value});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); select.value = was; }
  };
  return select;
}
// ORCH-813: the ticket's priority. When helpers wait for a free slot, high tickets start first, low ones last.
// No field = normal. The same native select as Helper strength.
const PRIORITY_NAMES = {high:'High, starts first', normal:'Normal', low:'Low, starts last'};
function prioritySet(t) { return ['high', 'low'].includes(t.priority); }
function priorityField(t) {
  const was = ['high', 'low'].includes(t.priority) ? t.priority : 'normal';
  if (snapshot) return el('span', 'ed-ro', PRIORITY_NAMES[was]);
  const select = h('select', {'aria-label':'Priority', 'data-key':'priority-' + t.id, title:'When helpers wait for a free slot, higher priority starts first'},
    ['high', 'normal', 'low'].map(p => h('option', {value:p}, PRIORITY_NAMES[p])));
  select.value = was;
  select.onchange = async () => {
    const result = await act('ticket.edit', {ticket:t.id, priority:select.value, if_revision:(ticketOf(t.id) || t).revision});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); select.value = was; }
  };
  return select;
}
function modelField(t) {
  const m = modelChoice(t);
  const said = m ? MODEL_NAMES[m.name] + (m.auto ? ' (picked by orch' + (m.why ? ': ' + m.why : '') + ')' : '') : 'orch picks it when work starts';
  if (snapshot) return el('span', 'ed-ro', said);
  // Plain choices; the model names sit behind "More" (ORCH-300, owner's word list item 31).
  const select = h('select', {'aria-label':'Helper strength', 'data-key':'model-' + t.id},
    h('option', {value:'auto'}, 'Auto'),
    h('option', {value:'haiku'}, 'Fastest'), h('option', {value:'sonnet'}, 'Faster'),
    h('option', {value:'opus'}, 'Stronger'),
    h('option', {value:'fable'}, 'Drafts to pick from'));
  select.value = m && !m.auto ? m.name : 'auto';
  select.onchange = async () => {
    const result = await act('ticket.model', {ticket:t.id, model:select.value});
    if (!result.ok) { window.orch.toast(changeError(result), 'error'); select.value = m && !m.auto ? m.name : 'auto'; }
  };
  const more = h('details', {className:'disclosure', 'data-key':'model-more-' + t.id}, h('summary', {}, 'More'),
    el('p', 'meta', 'Model: ' + said + '. Fastest is Haiku, Faster is Sonnet, Stronger is Opus, Drafts to pick from is Fable.'));
  return h('div', {className:'stack'}, select, more);
}
function inlineField(t, field) {
  const raw = t[field] == null ? '' : String(t[field]);
  const shown = field === 'due' ? dueText(t) : field === 'owner' ? name(raw) : clean(raw);
  if (snapshot) return el('span', MULTILINE.includes(field) ? 'ed-ro preserve-lines' : 'ed-ro', shown || (field === 'title' ? '' : FIELD_HINT[field]));
  const host = el('span', 'inline-host');
  host.dataset.key = 'inline-' + field + '-' + t.id;
  const plain = field !== 'title', setDue = field === 'due' && !shown;
  const node = el('button', 'ed' + (plain ? ' ed-plain' : '') + (setDue ? ' ed-link' : shown ? '' : ' empty-v') + (MULTILINE.includes(field) ? ' preserve-lines' : '') + (field === 'title' ? ' ed-title' : ''), setDue ? 'Set a due date' : shown || FIELD_HINT[field]);
  if (plain && !setDue) node.append(iconEl('pencil'));
  Object.assign(node, {type:'button', title:MULTILINE.includes(field) ? 'Click to change · Enter saves, Shift+Enter new line' : 'Click to change'});
  node.setAttribute('aria-label', 'Change ' + FIELD_LABEL[field]);
  Object.assign(node.dataset, {action:'inline', field, ticket:t.id});
  host.append(node);
  return host;
}
async function saveField(t, field, value) {
  const same = o => String(o?.[field] ?? '') === String(t[field] ?? '');
  const result = await actRetry('ticket.edit', () => ({ticket:t.id, [field]:value, if_revision:(ticketOf(t.id) || t).revision}), () => same(ticketOf(t.id)));
  if (result.ok) return;
  const now = ticketOf(t.id), theirs = now ? String(now[field] ?? '') : '';
  if (result.status === 409 && now && !same(now) && theirs !== String(value)) {
    // ORCH-903: someone changed this field while it was being edited: keep what was typed, one click applies it.
    const shown = v => (field === 'owner' ? name(v) : clean(v)) || 'empty';
    const mine = () => actRetry('ticket.edit', () => ({ticket:t.id, [field]:value, if_revision:(ticketOf(t.id) || t).revision}), () => true)
      .then(r => { if (!r.ok) window.orch.toast(changeError(r), 'error'); });
    mine.label = 'Use mine';
    window.orch.toast('Someone just changed ' + FIELD_LABEL[field] + ' to "' + shown(theirs) + '". You typed "' + shown(value) + '".', 'error', mine);
    return;
  }
  window.orch.toast(changeError(result), 'error');
}
function startInline(control) {
  const t = ticketOf(control.dataset.ticket), field = control.dataset.field, host = control.parentElement;
  if (!t || !host || locks.has(host.dataset.key)) return;
  const key = host.dataset.key;
  const before = field === 'owner' ? name(t.owner) : t[field] == null ? '' : String(t[field]);
  if (field === 'due') {
    locks.add(key);
    pickDate(control, before, async value => { if (value !== null && value !== before) await saveField(t, 'due', value); locks.delete(key); render(); }, true);
    return;
  }
  const input = el(MULTILINE.includes(field) ? 'textarea' : 'input', 'input inline-input');
  if (MULTILINE.includes(field)) input.rows = 3; else input.type = 'text';
  if (field === 'title') input.maxLength = 200;
  input.value = before;
  input.setAttribute('aria-label', capitalise(field));
  locks.add(key);
  const hint = el('span', 'hint', MULTILINE.includes(field) ? 'Enter saves · Shift+Enter new line · Esc cancels' : 'Enter saves · Esc cancels');
  host.replaceChildren(input, hint);
  if (field === 'owner') ownerChoices(input, hint);
  input.focus();
  if (MULTILINE.includes(field)) {
    // Small by default (3 rows, from the top); "Show all" opens the whole note, "Show less" goes back.
    let open = false;
    const fit = () => { input.style.height = open ? 'auto' : ''; if (open) input.style.height = Math.min(input.scrollHeight + 2, window.innerHeight * 0.6) + 'px'; };
    const more = button('Show all', 'ghost xs', () => { open = !open; more.textContent = open ? 'Show less' : 'Show all'; fit(); input.scrollTop = 0; input.focus(); });
    more.type = 'button';
    more.addEventListener('mousedown', event => event.preventDefault());  // keep the box focused, so it does not save
    input.setSelectionRange(0, 0); input.scrollTop = 0;
    if (input.scrollHeight > input.clientHeight + 2) host.append(more);
    input.addEventListener('input', () => { if (open) fit(); });
  }
  let done = false;
  const finish = async save => {
    if (done) return;
    done = true;
    const value = MULTILINE.includes(field) ? input.value : input.value.trim();
    if (save && field === 'title' && !value && before) window.orch.toast('A ticket needs a title. The old one is kept.', 'error');  // ORCH-185: never restore it silently
    else if (save && value !== before) await saveField(t, field, value);
    locks.delete(key);
    render();
  };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !(MULTILINE.includes(field) && event.shiftKey)) { event.preventDefault(); finish(true); }
    else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

// ORCH-240: the owner box offers the workspace's people and existing owners, and says when a name is not one of them
// (it is still saved as written: a person may own a ticket before they use the dashboard).
const knownOwners = () => [...new Set([...array(state?.people?.people), ...tickets().map(x => String(x.owner || '').trim()).filter(Boolean).map(o => name(o) || o)].map(String))].sort((a, b) => a.localeCompare(b));
function ownerChoices(input, hint) {
  const known = knownOwners(), list = el('datalist', '');
  list.id = 'owner-choices';
  known.forEach(n => list.append(h('option', {value:n})));
  input.setAttribute('list', list.id);
  input.after(list);
  const plain = hint.textContent;
  const check = () => {
    const v = input.value.trim(), fresh = v && !known.some(n => n.toLowerCase() === v.toLowerCase());
    hint.replaceChildren(fresh ? h('span', {className:'warn'}, v + ' is not one of your people yet') : '', fresh ? ' · Enter saves · Esc cancels' : plain);
  };
  input.addEventListener('input', check);
  check();
}
// A small calendar in the orch look instead of the browser's own picker. cb(value) with 'YYYY-MM-DD' (or 'YYYY-MM-DDTHH:MM' when withTime and a time is set), '' (clear) or null (closed).
function pickDate(anchor, current, cb, withTime = false) {
  document.querySelectorAll('.cal').forEach(n => n.remove());
  const iso = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  const todayIso = iso(new Date());
  const start = parse(current) || new Date();
  let view = new Date(start.getFullYear(), start.getMonth(), 1), closed = false;
  const currentDay = String(current || '').slice(0, 10);
  const timeInput = withTime ? el('input', 'input') : null;
  if (timeInput) { timeInput.type = 'time'; timeInput.value = String(current || '').slice(11, 16); timeInput.setAttribute('aria-label', 'Time (optional)'); }
  const withClock = day => day && timeInput && timeInput.value ? day + 'T' + timeInput.value : day;
  const pop = el('div', 'cal');
  pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'Choose a day');
  const close = value => {
    if (closed) return;
    closed = true;
    document.removeEventListener('mousedown', outside, true);
    document.removeEventListener('keydown', key, true);
    pop.remove();
    // ORCH-240: a day in the past is kept (the person may mean it) but never without a word
    if (value && String(value).slice(0, 10) < todayIso) window.orch.toast('That day has already passed, so the ticket shows as late.', 'info');
    cb(value);
  };
  const outside = event => { if (!pop.contains(event.target)) close(null); };
  const key = event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(null); } };
  const draw = () => {
    pop.replaceChildren();
    const head = el('div', 'cal-h');
    const nav = (label, text, delta) => { const b = button(text, 'ghost icon sm', () => { view = new Date(view.getFullYear(), view.getMonth() + delta, 1); draw(); }); b.setAttribute('aria-label', label); return b; };
    head.append(nav('Previous month', '‹', -1), el('strong', '', view.toLocaleDateString('en-GB', {month:'long', year:'numeric'})), nav('Next month', '›', 1));
    const grid = el('div', 'cal-g');
    for (const d of ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']) grid.append(el('span', 'cal-d', d));
    const lead = (view.getDay() + 6) % 7, days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    for (let i = 0; i < lead; i++) grid.append(el('span'));
    for (let n = 1; n <= days; n++) {
      const value = iso(new Date(view.getFullYear(), view.getMonth(), n));
      const b = el('button', 'cal-x' + (value === todayIso ? ' today' : '') + (value === currentDay ? ' sel' : ''), String(n));
      b.type = 'button'; b.setAttribute('aria-label', value);
      b.addEventListener('click', () => close(withClock(value)));
      grid.append(b);
    }
    const foot = el('div', 'cal-f');
    foot.append(button('Clear', 'ghost sm', () => close('')), button('Today', 'outline sm', () => close(withClock(todayIso))));
    const clock = timeInput ? el('label', 'row') : null;
    if (clock) clock.append(el('span', 'meta', 'Time (optional)'), timeInput);
    pop.append(head, grid, ...(clock ? [clock] : []), foot);
  };
  draw();
  // Inside a dialog the calendar must live in the dialog and in the top layer, or the dialog hides it.
  const host = anchor.closest('dialog');
  if (host) {
    host.append(pop);
    try { pop.setAttribute('popover', 'manual'); pop.showPopover(); } catch (_) { pop.removeAttribute('popover'); }
  } else document.body.append(pop);
  // ORCH-240: the visible width and height (innerWidth counts the scrollbar, so the right edge was cut off)
  const r = anchor.getBoundingClientRect(), vw = document.documentElement.clientWidth || innerWidth, vh = document.documentElement.clientHeight || innerHeight;
  pop.style.top = Math.min(r.bottom + 6, Math.max(8, vh - pop.offsetHeight - 8)) + 'px';
  pop.style.left = Math.max(8, Math.min(r.left, vw - pop.offsetWidth - 8)) + 'px';
  setTimeout(() => { document.addEventListener('mousedown', outside, true); document.addEventListener('keydown', key, true); }, 0);
  (pop.querySelector('.today, .sel') || pop.querySelector('.cal-x'))?.focus();
}

// An answer still in its Undo window is sent at once when the page is left, so it is not lost.
const sends = new WeakMap();
function flushPending() {
  if (typeof mounts === 'undefined') return;  // the page was left before app.js loaded (e.g. the launch reload)
  window.DashHelpers.flushPending([...mounts.values()].map(m => ({state:m.state, send:sends.get(m)})));
}
addEventListener('pagehide', flushPending);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushPending(); });
function mountQuestion(host, q, context = {}) {
  let sendAnswer;
  const mounted = window.QuestionCard.mount(host, {...q, title:clean(q.title), text:clean(q.text)}, {
    send: sendAnswer = async answer => {
      const lock = context.lock || host.dataset.key;
      if (lock) locks.add(lock);
      const result = await act('answer', {ticket:q.ticket, question:q.id, digest:q.digest, answer});
      if (!result.ok) {
        let fresh = result.state;
        try {
          if (!fresh) {
            const res = await fetch('/api/state', {cache:'no-store'});
            if (res.ok) fresh = await res.json();
          }
        } catch (_) { /* Keep the original send error if the refresh also fails. */ }
        const win = window.DashHelpers.winningAnswer(fresh?.tickets, q.ticket, q.id);
        // Keep the mounted card and any open dialog intact while accepting the refresh.
        if (fresh) { mutation++; accept(fresh); }
        if (lock && !context.dialog) locks.delete(lock);
        if (win !== null) return {status:409, other:{text:win.text, who:name(win.who), via:win.via}};
        return {status:0, message:result.text};
      }
      const answered = array(ticketOf(q.ticket)?.questions).find(x => x.id === q.id);
      const who = name(answered?.answered_by || result.state.who) || 'You';
      // Let the shared card finish its send transition before releasing its host.
      setTimeout(async () => {
        window.orch.toast('Answered · ' + who + ' · dashboard', 'ok');
        context.onAnswered?.();
        if (context.dialog) {
          context.dialog.dataset.resolving = 'true';
          await window.orch.close(context.dialog);
        }
        if (context.row?.isConnected) await window.orch.resolve(context.row);
        if (lock) locks.delete(lock);
        if (host.isConnected && mounts.has(host)) { mounts.get(host).destroy(); mounts.delete(host); }
        render();
        if (!document.querySelector('dialog[open]') && !document.activeElement?.closest('button,a,input,textarea')) {
          main.querySelector('h1')?.setAttribute('tabindex', '-1');
          main.querySelector('h1')?.focus({preventScroll:true});
        }
        refresh();
      }, 0);
      return {status:200, who, via:'dashboard'};
    }
  });
  if (host.closest('.ticket-page')) {
    const labelAnswer = () => { const other = host.querySelector('.qoptions .quiet'); if (other && other.textContent !== 'Write your own answer') other.textContent = 'Write your own answer'; };
    labelAnswer();
    const observer = new MutationObserver(labelAnswer); observer.observe(host, {childList:true, subtree:true});
    const destroy = mounted.destroy.bind(mounted); mounted.destroy = () => { observer.disconnect(); destroy(); };
  }
  // The shared component uses the real key for persistence; only its visible label changes.
  const label = host.querySelector('.qmeta .muted');
  if (label) label.textContent = clean(ticketOf(q.ticket)?.title) || 'Ticket';
  mounts.set(host, mounted);
  sends.set(mounted, sendAnswer);
}
async function openNeed(row, trigger) {
  if (!row) return;
  const action = window.DashHelpers.needAction(row);
  if (action.kind === 'run') {
    if (trigger.disabled) return;
    trigger.disabled = true;
    const result = await act('run.start', {ticket:row.ticket});
    trigger.disabled = false;
    window.orch.toast(result.ok ? 'Started again' : result.text, result.ok ? 'ok' : 'error');
    return;
  }
  if (action.kind === 'start') {  // a background add-on stopped: one press starts it (no dialog to read first)
    if (trigger.disabled) return;
    trigger.disabled = true;
    const result = await act('addon.start', {});
    trigger.disabled = false;
    window.orch.toast(result.ok ? 'Started' : result.text, result.ok ? 'ok' : 'error');
    return;
  }
  if (action.kind === 'answer' || action.kind === 'review') {
    const {d, actions} = dialog(row.title, 'dialog', 'needs-you');
    const host = el('div');
    d.append(host, actions);
    mountQuestion(host, {ticket:row.ticket, id:row.answer.question, digest:row.answer.digest, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
    window.orch.open(d);
    // "Write your own…" opens the answer box with its Send button at once, not a second page of choices
    if (trigger.dataset?.write === 'own') d.querySelector('.qoptions .quiet')?.click();
  } else if (row.ticket) location.hash = href(row.ticket);
  else {
    const a = addons().find(a => a.dashboard && (a.name === row.source || String(row.kind).startsWith(a.name + ':')));
    if (a) location.hash = '#addon/' + encodeURIComponent(a.name);
    else window.orch.toast(clean(row.text || row.title || 'Nothing to do here.'));  // nothing to press: say it, no dead-end dialog
  }
}

// A shipped add-on page (the Factory) may ask the dashboard to show one open question in its own card. The message only
// NAMES a ticket and a question; it never carries text, options or an answer, and it never answers anything. The person
// presses an option in the native card, which sends the answer through the normal proof path.
const EMBED_TICKET = /^t_[a-z0-9]{6,16}$/, EMBED_QUESTION = /^q[A-Za-z0-9_-]{0,31}$/;
// The frame of the shown page of an add-on shipped with orch, when this message came from it (same origin); else null.
function shippedFrame(e) {
  // the shipped add-on page is sandboxed (origin "null"); the frame check below is what counts
  const chan = e.origin === 'null' && !!e.data?.chan && e.data.chan === globalThis.orchFrameChan?.();  // its per-frame code
  if ((e.origin !== location.origin && !chan) || snapshot) return null;  // a shared read-only copy acts on nothing
  const r = route();
  if (r.kind !== 'page' || !addons().find(a => a.name === r.id)?.shipped) return null;
  const frame = document.querySelector('iframe.embed[data-key="embed"]');
  if (!frame || !frame.contentWindow || e.source !== frame.contentWindow) return null;
  return {frame, addon:r.id};
}
// A bridge action (idea, ask, Looks good, send) runs only right after a real click or key press of the person: the
// browser counts one inside the add-on frame for this page too, and no script can make one up (ORCH-186 review M2).
const personClicked = () => !!globalThis.navigator?.userActivation?.isActive;
const NO_CLICK = 'Click the button again to do this.';
function embedQuestionRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.question') return null;
  const frame = shippedFrame(e)?.frame;
  if (!frame) return null;
  if (typeof data.ticket !== 'string' || typeof data.question !== 'string' || !EMBED_TICKET.test(data.ticket) || !EMBED_QUESTION.test(data.question)) return null;
  return {ticket:data.ticket, question:data.question, frame};
}
let embedDialog = null;  // one embed question at a time: repeated asks never stack dialogs
let embedReading = false;
// The question may be seconds old: read the workspace fresh (never the cached copy) before saying it is gone.
async function openEmbedQuestion(req) {
  if (embedReading || (embedDialog && embedDialog.isConnected && embedDialog.open)) return;
  embedReading = true;
  try {
    const res = await fetch('/api/state?fresh=1', {cache:'no-store'});
    if (res.ok) { mutation++; accept(await res.json()); }
  } catch (_) { /* Fall back to what the page already has. */ }
  finally { embedReading = false; }
  if (embedDialog && embedDialog.isConnected && embedDialog.open) return;
  const t = ticketOf(req.ticket);
  const q = array(t?.questions).find(x => x.id === req.question);
  const open = q && q.answer == null && t.id === req.ticket;
  const {d, actions} = dialog(open ? (clean(t.title) || 'Question') : 'Question', 'dialog', 'needs-you');
  embedDialog = d;
  d.addEventListener('close', () => { if (embedDialog === d) embedDialog = null; });
  if (!open) {
    d.append(el('p', '', 'This question is no longer waiting for you.'), actions);
    window.orch.open(d);
    return;
  }
  const host = el('div');
  d.append(host, actions);
  const done = () => { try { req.frame.contentWindow?.postMessage({type:'orch.question.done', ticket:req.ticket, question:req.question}, '*'); } catch (_) { /* The page was left. */ } };
  mountQuestion(host, {ticket:t.id, key:typeof t.key === 'string' ? t.key : undefined, id:q.id, digest:q.digest, title:q.text, text:'', kind:q.kind, options:array(q.options).map(o => ({text:o, suggested:o === q.recommended}))}, {dialog:d, lock:'needs-you', onAnswered:done});
  window.orch.open(d);
}
addEventListener('message', e => { const req = embedQuestionRequest(e); if (req) openEmbedQuestion(req); });

// The Factory idea box: ONE click files the idea as the person's own action. The shown shipped add-on page names only
// the text; the dashboard runs that add-on's `idea` act through its own op (`addon.act`, which needs this page's
// session: the person's click, never an agent's or a foreign frame's) and tells the page the new order, or why not.
const EMBED_IDEA_ID = /^[a-z0-9]{8,32}$/, IDEA_MAX = 500;
// eslint-disable-next-line no-control-regex
const IDEA_HIDDEN = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g;
function embedIdeaRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.idea') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id) || typeof data.text !== 'string') return null;
  const text = data.text.replace(IDEA_HIDDEN, ' ').replace(/\s+/g, ' ').trim().replace(/^-+\s*/, '');
  if (!text) return null;
  return {...shown, id:data.id, text, clicked:personClicked()};
}
let embedIdeaBusy = false;  // one idea at a time: a second click while saving is dropped
async function fileEmbedIdea(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.idea.failed', error:NO_CLICK});
  if (req.text.length > IDEA_MAX) return reply({type:'orch.idea.failed', error:'An idea here has at most ' + IDEA_MAX + ' characters.'});
  if (embedIdeaBusy) return;
  embedIdeaBusy = true;
  try {
    const result = await act('addon.act', {addon:req.addon, verb:'idea', target:req.text});
    const answer = result.ok ? result.state?.act_answer : null;
    const order = answer && answer.addon === req.addon ? answer.answer?.order : null;
    if (typeof order === 'string' && EMBED_TICKET.test(order)) {
      reply({type:'orch.idea.done', order});
      if (typeof answer.answer.text === 'string') window.orch.toast(answer.answer.text.slice(0, 200));
    } else {
      reply({type:'orch.idea.failed', error:result.ok ? '' : String(result.text || '').slice(0, 300)});
    }
  } finally { embedIdeaBusy = false; }
}
addEventListener('message', e => { const req = embedIdeaRequest(e); if (req) fileEmbedIdea(req); });

// "Looks good" on a Factory stage review (all of the stage's results at once): the SAME Looks good as on each ticket page (the status move with the
// recorded review tip), for the listed tickets that still wait in review. One toast for the batch, with one Undo.
const EMBED_BATCH_MAX = 10;
function embedLooksGoodRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.looksgood') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (!Array.isArray(data.tickets) || !data.tickets.length || data.tickets.length > EMBED_BATCH_MAX) return null;
  if (!data.tickets.every(x => typeof x === 'string' && EMBED_TICKET.test(x))) return null;
  return {...shown, id:data.id, tickets:[...new Set(data.tickets)], clicked:personClicked()};
}
let embedLooksGoodBusy = false;  // one batch at a time
async function looksGoodAll(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.looksgood.failed', error:NO_CLICK});
  // never a silent drop (ORCH-419): the page waits for an answer and says so
  if (embedLooksGoodBusy) return reply({type:'orch.looksgood.failed', error:'Still saving the last Looks good. Try again in a moment.'});
  embedLooksGoodBusy = true;
  try {
    try {  // a read that hangs must not hold every later Looks good (ORCH-419)
      const res = await fetch('/api/state?fresh=1', {cache:'no-store', signal:AbortSignal.timeout(10000)});
      if (res.ok) { mutation++; accept(await res.json()); }
    } catch (_) { /* Fall back to what the page already has. */ }
    // only results of this add-on (tickets that carry its data), as with sending: never another page's tickets
    const listed = req.tickets.map(ticketOf);
    if (listed.some(t => t && (!t.ext || typeof t.ext !== 'object' || !t.ext[req.addon]))) return reply({type:'orch.looksgood.failed', error:'Only this page\u2019s own results can get Looks good here.'});
    const waiting = listed.filter(t => t && t.status === 'review');
    if (!waiting.length) return reply({type:'orch.looksgood.failed', error:'Nothing here is waiting for your Looks good any more.'});
    await Promise.all(waiting.map(t => {
      const tip = typeof t.review_tip === 'string' && /^[0-9a-f]{40,64}$/.test(t.review_tip) ? t.review_tip : '';
      return moveTicket(t.id, 'done', false, {quiet:true, ...(tip ? {review_tip:tip} : {})});
    }));
    const moved = waiting.filter(t => ticketOf(t.id)?.status === 'done');
    if (!moved.length) return reply({type:'orch.looksgood.failed', error:'Looks good could not be saved. Try again.'});
    const toast = window.orch.toast('Looks good on ' + (moved.length === 1 ? '1 result' : moved.length + ' results'), 'ok');
    if (toast?.querySelector) {
      const undo = h('button', {type:'button', className:'btn ghost sm', 'data-action':'undo-move'}, 'Undo');
      undo.addEventListener('click', () => { toast.remove(); for (const t of moved) moveTicket(t.id, 'review', true, {quiet:true}); });
      toast.querySelector('button[aria-label="Dismiss notification"]')?.before(undo);
    }
    if (moved.length < waiting.length) window.orch.toast((waiting.length - moved.length) + ' could not be saved. Try those again from their tickets.', 'error');
    reply({type:'orch.looksgood.done', moved:moved.length});
  } finally { embedLooksGoodBusy = false; }
}
addEventListener('message', e => { const req = embedLooksGoodRequest(e); if (req) looksGoodAll(req); });

// A shipped add-on page's own setting (Usage: a limit, the order, on/off, an end date, switching by itself): the shown
// page names only one of ITS add-on's verbs and a plain target; the dashboard runs `orch <that add-on> act <verb> -- <target>`
// through its own op (the person's click with this page's session) and tells the page the add-on's answer or why not.
// The add-on checks the target itself; nothing here names an add-on. Same origin and shipped-frame fences as orch.idea.
const EMBED_ACT_VERB = /^[a-z][a-z-]{0,20}$/, EMBED_ACT_MAX = 200, EMBED_ACT_HIDDEN = new RegExp(IDEA_HIDDEN.source);
function embedActRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.act') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (typeof data.verb !== 'string' || !EMBED_ACT_VERB.test(data.verb) || data.verb === 'refresh') return null;
  const t = data.target;
  if (typeof t !== 'string' || !t || t.length > EMBED_ACT_MAX || t.startsWith('-') || t !== t.trim() || EMBED_ACT_HIDDEN.test(t)) return null;
  return {...shown, id:data.id, verb:data.verb, target:t};
}
let embedActBusy = false;  // one setting at a time: a second click while saving is dropped
async function runEmbedAct(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (embedActBusy) return reply({type:'orch.act.failed', error:'Still saving the last change. Try again in a moment.'});
  embedActBusy = true;
  try {
    const result = await act('addon.act', {addon:req.addon, verb:req.verb, target:req.target});
    const answer = result.ok ? result.state?.act_answer : null;
    if (result.ok) reply({type:'orch.act.done', answer:answer && answer.addon === req.addon && answer.answer && typeof answer.answer === 'object' ? {changed:answer.answer.changed !== false} : {}});
    else reply({type:'orch.act.failed', error:String(result.text || '').slice(0, 300)});
  } finally { embedActBusy = false; }
}
addEventListener('message', e => { const req = embedActRequest(e); if (req) runEmbedAct(req); });

// Save in a shipped add-on page's editor (Skills, ORCH-840): the shown page names an opaque item id of ITS add-on,
// the revision it loaded and the text. Only right after the person's own click (Save), one at a time. The dashboard
// runs `orch <that add-on> act save --value=<revision> -- <id>` with the text on stdin; the add-on resolves the id,
// refuses a stale revision and keeps a copy before it writes. The text never goes into this page's DOM.
const EMBED_SAVE_TARGET = /^e_[0-9a-f]{24}$/, EMBED_SAVE_REV = /^[0-9a-f]{64}$/, EMBED_SAVE_MAX = 160 * 1024;
function embedSaveRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.save') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (typeof data.target !== 'string' || !EMBED_SAVE_TARGET.test(data.target)) return null;
  if (typeof data.revision !== 'string' || !EMBED_SAVE_REV.test(data.revision)) return null;
  if (typeof data.text !== 'string' || !data.text || data.text.includes('\u0000')) return null;
  return {...shown, id:data.id, target:data.target, revision:data.revision, text:data.text, clicked:personClicked()};
}
let embedSaveBusy = false;
async function runEmbedSave(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.save.failed', error:NO_CLICK});
  if (new TextEncoder().encode(req.text).length > EMBED_SAVE_MAX) return reply({type:'orch.save.failed', error:'That is too long to save here.'});
  if (embedSaveBusy) return reply({type:'orch.save.failed', error:'Still saving. Try again in a moment.'});
  embedSaveBusy = true;
  try {
    const result = await act('addon.act', {addon:req.addon, verb:'save', target:req.target, value:req.revision, text:req.text});
    const answer = result.ok ? result.state?.act_answer : null;
    const a = answer && answer.addon === req.addon && answer.answer && typeof answer.answer === 'object' ? answer.answer : null;
    if (result.ok && a && typeof a.revision === 'string' && EMBED_SAVE_REV.test(a.revision)) reply({type:'orch.save.done', revision:a.revision, changed:a.changed !== false});
    else reply({type:'orch.save.failed', error:result.ok ? 'orch did not confirm the save. Open it again to check.' : String(result.text || '').slice(0, 300), stale:result.status === 409});
  } finally { embedSaveBusy = false; }
}
addEventListener('message', e => { const req = embedSaveRequest(e); if (req) runEmbedSave(req); });

// Ask another workspace at a stop (Factory, 816 A): modelled on the idea box. The shown shipped add-on page names a
// target ("<order>:s<N>:<workspace>:<items>"); the dashboard runs that add-on's `ask` act (a person's click with this
// page's session) and tells the page whether it went out. Same origin and shipped-frame fences as orch.idea.
const EMBED_ASK_TARGET = /^t_[a-z0-9]{6,16}:s[1-9][0-9]{0,3}:ws_[a-z0-9]{6,32}:(-|[0-9]{1,2}(,[0-9]{1,2}){0,11})$/;
function embedAskRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.ask') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (typeof data.target !== 'string' || !EMBED_ASK_TARGET.test(data.target)) return null;
  return {...shown, id:data.id, target:data.target, clicked:personClicked()};
}
let embedAskBusy = false;  // one ask at a time: a second click while sending is dropped
async function fileEmbedAsk(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.ask.failed', error:NO_CLICK});
  if (embedAskBusy) return;
  embedAskBusy = true;
  try {
    const result = await act('addon.act', {addon:req.addon, verb:'ask', target:req.target});
    const answer = result.ok ? result.state?.act_answer : null;
    const state = answer && answer.addon === req.addon ? answer.answer?.state : null;
    if (state === 'delivered' || state === 'queued') reply({type:'orch.ask.done', state});
    else if (state === 'partial') reply({type:'orch.ask.done', state, said:String(answer.answer?.said || '').slice(0, 300)});
    else reply({type:'orch.ask.failed', error:result.ok ? 'orch did not confirm that it was sent.' : String(result.text || '').slice(0, 300)});
  } finally { embedAskBusy = false; }
}
addEventListener('message', e => { const req = embedAskRequest(e); if (req) fileEmbedAsk(req); });

// Start on a parked Factory order (ORCH-277): the shown shipped add-on page names one of ITS orders. The dashboard runs
// that add-on's `start` act (a person's click with this page's session), which asks the same proposal again, then
// opens that new question in its own card: the person's Start there is what starts the run, never this click.
function embedStartRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.start') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (typeof data.order !== 'string' || !EMBED_TICKET.test(data.order)) return null;
  return {...shown, id:data.id, order:data.order, clicked:personClicked()};
}
let embedStartBusy = false;  // one start at a time
async function startEmbedOrder(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.start.failed', error:NO_CLICK});
  if (embedStartBusy) return;
  embedStartBusy = true;
  try {
    const t = ticketOf(req.order);
    if (t && (!t.ext || typeof t.ext !== 'object' || !t.ext[req.addon])) return reply({type:'orch.start.failed', error:'Only this page\u2019s own orders can be started here.'});
    const result = await act('addon.act', {addon:req.addon, verb:'start', target:req.order});
    const answer = result.ok ? result.state?.act_answer : null;
    const question = answer && answer.addon === req.addon ? answer.answer?.question : null;
    if (typeof question !== 'string' || !EMBED_QUESTION.test(question)) return reply({type:'orch.start.failed', error:result.ok ? '' : String(result.text || '').slice(0, 300)});
    reply({type:'orch.start.done', question});
    openEmbedQuestion({ticket:req.order, question, frame:req.frame});
  } finally { embedStartBusy = false; }
}
addEventListener('message', e => { const req = embedStartRequest(e); if (req) startEmbedOrder(req); });

// Plan the run / Ask for changes on a Factory draft: the shown shipped add-on page names a ticket of ITS OWN (one that
// carries that add-on's data) and the words. The dashboard sends them as the person's message with its own proven op
// (`run.send`, the same click as writing to the agent on the ticket page) and, when no agent works on it, starts one
// (`run.start`). Both need this page's session: never an agent's request or a foreign frame's.
const EMBED_SEND_MAX = 2000;
function embedSendRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.send') return null;
  const shown = shippedFrame(e);
  if (!shown || typeof data.id !== 'string' || !EMBED_IDEA_ID.test(data.id)) return null;
  if (typeof data.ticket !== 'string' || !EMBED_TICKET.test(data.ticket) || typeof data.text !== 'string') return null;
  const t = ticketOf(data.ticket);
  if (!t || t.id !== data.ticket || !t.ext || typeof t.ext !== 'object' || !t.ext[shown.addon]) return null;  // only its own tickets
  const text = data.text.replace(IDEA_HIDDEN, m => m === '\n' ? '\n' : ' ').trim();
  if (!text) return null;
  return {...shown, id:data.id, ticket:data.ticket, text, clicked:personClicked()};
}
let embedSendBusy = false;  // one message at a time: a second click while sending is dropped
async function sendEmbedMessage(req) {
  const reply = msg => { try { req.frame.contentWindow?.postMessage({...msg, id:req.id}, '*'); } catch (_) { /* The page was left. */ } };
  if (!req.clicked) return reply({type:'orch.send.failed', error:NO_CLICK});  // sending and starting a helper: a click
  if (req.text.length > EMBED_SEND_MAX) return reply({type:'orch.send.failed', error:'That is too long (at most ' + EMBED_SEND_MAX + ' characters).'});
  if (embedSendBusy) return;
  embedSendBusy = true;
  try {
    const sent = await act('run.send', {ticket:req.ticket, text:req.text});
    if (!sent.ok) return reply({type:'orch.send.failed', error:String(sent.text || '').slice(0, 300)});
    // orch says what it did: delivered to the agent now, or queued for it (an id). Anything else was not saved.
    const r = sent.state?.send_result;
    const delivered = !!r && Number.isInteger(r.delivered) && r.delivered > 0;
    const queued = !!r && typeof r.id === 'string' && r.id !== '';
    if (!delivered && !queued) return reply({type:'orch.send.failed', error:'orch did not confirm that your message was saved. Nothing was sent.'});
    // Start an agent only when orch says nothing is on the ticket (state "none"): a live session took or keeps the
    // words itself, and a second start would only be refused (422) and toast an error.
    const nothingOn = r.state === 'none' && !delivered;
    const started = nothingOn ? await act('run.start', {ticket:req.ticket}) : null;
    reply({type:'orch.send.done', ticket:req.ticket, delivered, queued, started:!!started?.ok});
  } finally { embedSendBusy = false; }
}
addEventListener('message', e => { const req = embedSendRequest(e); if (req) sendEmbedMessage(req); });
