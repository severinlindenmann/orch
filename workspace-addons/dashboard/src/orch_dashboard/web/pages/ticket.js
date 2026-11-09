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
  const result = await act('check.set', {ticket:t.id, check:cid, done:!task.done});
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
function pageLinks() {
  return addons().filter(a => a.page && array(state.services).some(s => s.addon === a.name && s.running === true))
    .map(a => ({label:addonLabel(a), url:pageHash(a.name, a.page.path)}));
}
function addonUrl(addon) {
  return array(state.services).filter(s => s.addon === addon && s.running === true).map(s => localUrl(s.url)).find(Boolean) || null;
}
function addonLink(addon, path, label, startLabel = addon) {
  if (!/^[a-z][a-z0-9-]{1,31}$/.test(addon) || typeof path !== 'string' || !/^[A-Za-z0-9_./-]*$/.test(path) || path.includes('..')) return null;
  const base = addonUrl(addon);
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
  if (row.format === 'time') return [date(value), time(value)].filter(Boolean).join(' ');
  if (row.format === 'cron-human') return window.DashHelpers.cronHuman(value);
  if (row.format === 'yes-no') return value === true ? 'Yes' : value === false ? 'No' : '';
  if (row.format === 'chips') return h('div', {className:'chips'}, array(value).map(v => chip(clean(v))));
  return typeof value === 'object' ? '' : clean(value);
}
function addonRows(ticket) {
  const rows = addons().flatMap(a => array(a.ticket_view).map(r => [r, (ticket.ext || {})[a.name], a.name]))
    .map(([r, ext, addon]) => [r, ext && typeof ext === 'object' ? (r.format === 'open-page' ? addonLink(addon, ext[r.field], r.label, r.label) : addonValue(r, ext[r.field])) : '']).filter(([, v]) => v);
  return rows.length ? h('dl', {className:'addon-rows'}, rows.map(([r, v]) => r.format === 'open-page' ? h('dd', {className:'addon-page'}, v) : [h('dt', {}, r.label), h('dd', {}, v)])) : null;
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
function linksCard(t) {
  const rows = referenceRows(t);
  if (snapshot && !rows.length) return null;
  const refresh = snapshot ? [] : refreshers(t);
  return h('section', {className:'card links-card', 'data-key':'links-card'},
    h('div', {className:'card-h'}, h('h2', {className:'grow'}, 'References'), rows.length ? h('span', {className:'meta'}, String(rows.length)) : null,
      refresh.map(a => h('button', {type:'button', className:'btn ghost xs', title:'Update titles and status (' + addonLabel(a) + ')', 'data-action':'link-refresh', 'data-addon':a.name, 'data-ticket':t.id, 'data-key':'link-refresh-' + a.name}, iconEl('refresh'), refresh.length > 1 ? addonLabel(a) : 'Refresh'))),
    h('div', {className:'links'}, rows.map(l => linkRow(t, l, true)),
      snapshot ? null : h('div', {className:'add-link', 'data-key':'add-link-' + t.id}, h('button', {type:'button', className:'add-row', 'data-action':'link-add', 'data-ticket':t.id}, iconEl('plus'), 'Add reference'))));
}
function referenceRow(t, ref, removable) {
  const other = ticketOf(ref.ticket), n = ref.n || array(t.refs).indexOf(ref) + 1;
  const title = ref.kind === 'ticket' ? clean(other?.title) || 'Ticket unavailable' : ref.name || (ref.path + (ref.line ? ':' + ref.line : ''));
  const sub = ref.local ? 'On this computer only' : ref.kind === 'ticket' ? 'Ticket · ' + (other ? statusWord(other) : 'Unavailable') : ref.kind === 'artifact' ? 'Artifact' + (other ? ' · ' + clean(other.title) : '') : 'File in this project';
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
    if (label === 'Artifact') {
      const select = el('select', 'input'); select.setAttribute('aria-label', 'Artifact');
      body.append(select);
      try {
        const r = await fetch('/api/artifacts/' + encodeURIComponent(t.id));
        const data = await r.json();
        if (mode !== label) return;
        select.append(new Option('Choose an artifact', ''));
        array(data.files).forEach(f => select.append(new Option(f.name, 'artifact:' + f.name)));
        select.onchange = () => { target = select.value; addBtn.disabled = !target; };
      } catch (_) { err.textContent = 'The artifacts could not be loaded.'; }
      return;
    }
    const input = el('input', 'input'); input.maxLength = 2000;
    input.placeholder = label === 'Ticket' ? 'Search tickets by key or title' : label === 'File' ? 'Project-relative path' : 'https://…';
    input.setAttribute('aria-label', label);
    const bar = el('div', 'ref-bar'); bar.append(input); body.append(bar);
    if (label === 'Ticket') {
      const results = el('div', 'ref-list'), count = el('span', 'meta'); body.append(results);
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
  ['Ticket', 'Web address', 'File', 'Artifact'].forEach(label => { const tab = button(label, 'ghost', () => draw(label)); tab.setAttribute('role', 'tab'); tabs.append(tab); });
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
  if (f.type === 'date') return parse(value)?.toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short', year:'numeric'}) || clean(value);
  if (f.type === 'number' && typeof value === 'number') return value.toLocaleString('de-CH');
  return typeof value === 'object' ? '' : clean(value);
};
function fieldSections(t) {
  return addons().filter(a => a.ticket_fields && array(a.ticket_fields.fields).some(f => !f.hidden)).map(a => {
    const tf = a.ticket_fields, ext = (t.ext || {})[a.name] || {};
    const rows = array(tf.fields).filter(f => !f.hidden).map(f => {
      const shown = fieldText(f, ext[f.key]);
      let value;
      if (f.read_only || snapshot) value = h('span', {className:'ed-ro' + (shown ? '' : ' empty-v'), title:f.read_only ? 'Filled in by the ' + addonLabel(a) + ' add-on' : null}, f.read_only && f.key && ext[f.key] && KEY.test(String(ext[f.key])) ? linkStatus(String(ext[f.key])) : shown || '—');
      else {
        const node = h('button', {type:'button', className:'ed' + (shown ? '' : ' empty-v'), title:'Click to change', 'data-action':'field', 'data-ticket':t.id, 'data-addon':a.name, 'data-field':f.key}, shown || 'Add');
        value = h('span', {className:'inline-host', 'data-key':'field-' + a.name + '-' + f.key + '-' + t.id}, node);
      }
      return h('div', {}, h('dt', {}, clean(f.title)), h('dd', {}, value));
    });
    return h('section', {className:'card ticket-aside addon-fields', 'data-key':'fields-' + a.name},
      h('div', {className:'card-h'}, h('h2', {className:'grow'}, clean(tf.section)), h('span', {className:'addon-pill'}, 'add-on')),
      h('dl', {className:'ticket-details ed-list'}, rows));
  });
}
async function saveAddonField(t, addon, field, value) {
  const result = await act('ticket.field', {ticket:t.id, addon, field, value:String(value), if_revision:t.revision});
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
  const a = addons().find(a => a.page && array(state.services).some(s => s.addon === a.name && s.running === true));
  if (!a) return null;
  const own = (t.ext || {})[a.name]?.page;
  return {label:addonLabel(a), url:pageHash(a.name, typeof own === 'string' && /^[A-Za-z0-9_./-]+$/.test(own) && !own.includes('..') ? own : a.page.path)};
}
// Live session: two commands to copy. Watch cannot type; Take over can (the agent waits while you type).
function liveSessionStrip(t) {
  const run = state.runs?.[t.id];
  if (snapshot || !run?.running || run.claim?.mode === 'oneshot') return null;
  const ref = typeof t.key === 'string' && t.key ? t.key : t.id;
  const copy = (label, command) => {
    const control = button('', 'outline', async () => {
      try { await navigator.clipboard.writeText(command); window.orch.toast('Copied', 'ok'); }
      catch (_) { window.orch.toast('Could not copy. Select the text and copy it.', 'error'); }
    });
    control.dataset.key = 'live-copy-' + (command.includes('--watch') ? 'watch' : 'take');
    control.title = command;
    control.append(iconEl('copy'), label, h('span', {className:'meta'}, 'Copy'));
    return control;
  };
  return h('section', {className:'card live-strip', 'data-key':'live-session'}, h('h2', {}, 'Live session'),
    copy('Watch (read only)', 'orch run attach ' + ref + ' --watch'), copy('Take over (you can type)', 'orch run attach ' + ref));
}
function agentBar(t) {
  const liveLink = liveLinkFor(t), run = state.runs?.[t.id];
  const line = window.DashHelpers.agentLine(t, run, Date.now(), liveLink, state.settings);
  const session = array(t.sessions).slice().sort((a, b) => (Date.parse(b.last_used) || 0) - (Date.parse(a.last_used) || 0))[0];
  const step = array(t.checklist).find(task => task.state === 'doing');
  return h('div', {className:'agent-bar', 'data-state':line.state, 'data-key':'agent-bar'},
    h('span', {className:'dot ' + (line.startFailed ? 'error' : run?.running ? 'working' : 'idle'), 'aria-hidden':'true'}),
    line.startFailed ? h('span', {className:'ab-text grow', 'data-key':'start-failed'}, clean(line.status))
      : h('span', {className:'ab-text grow'}, h('strong', {}, name(line.agent)), ' · ', clean(step?.text || line.status)), line.startFailed ? null : ticketWarmth(t, run, session),
    snapshot ? null : h('div', {className:'ab-actions'}, liveLink ? h('a', {className:'btn outline', href:liveLink.url}, 'Watch live') : null,
      run?.running ? ticketButton('Stop', 'outline', () => act('run.stop', {ticket:t.id})) : line.primary && !['answer', 'open'].includes(line.primary.op) ? ticketButton(line.primary.label, 'primary', () => { const current = window.DashHelpers.agentLine(ticketOf(t.id), state.runs?.[t.id], Date.now(), liveLinkFor(ticketOf(t.id)), state.settings); if (current.primary && !['answer', 'open'].includes(current.primary.op)) act(current.primary.op, current.primary.args); }) : null));
}

const surface = via => clean(via === 'cli' ? 'terminal' : via);
function proofLabel(ev) {
  const kind = ev.type || ev.kind;
  let label = ev.title || ev.text || String(ev.ref || '').split(/[\\/]/).pop() || 'Proof';
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
// ---- Artifacts tab: files (orch ticket artifacts), proof, links. Files are read through /api/file (text and pictures only).
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
const proofRows = t => array(t.checklist).flatMap(task => array(task.evidence).map(ev => ({task, ev})))
  .sort((a, b) => (Date.parse(b.ev.at) || 0) - (Date.parse(a.ev.at) || 0));
const referenceRows = t => array(t.refs).filter(r => r && (['ticket', 'artifact', 'file'].includes(r.kind) || webLinks(t).includes(r))).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
const linkRows = t => referenceRows(t);
const artifactCount = t => (artifactData.get(t.id)?.data?.files?.length || 0) + proofRows(t).length + linkRows(t).length;
// Artifacts tab: all reference kinds, newest first.
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
const ticketPreviewText = new Map();
function ticketPreviewTile(t, file, kind = 'artifacts') {
  const title = window.DashHelpers.plainFileName(file.name) || 'Result';
  const tile = h('div', {className:'ticket-preview'}, h('span', {className:'ticket-preview-label'}, title));
  const html = /\.html?$/i.test(file.name), picture = /\.(png|jpe?g|webp)$/i.test(file.name);
  if (snapshot || html || (!picture && !PREVIEW_EXT.text.test(file.name))) {
    tile.append(h('p', {className:'meta'}, html ? title : 'Preview available when opened'));
    return tile;
  }
  const url = '/api/file?t=' + encodeURIComponent(t.id) + '&k=' + kind + '&n=' + encodeURIComponent(file.name);
  const key = url + '|' + (file.mtime || '');
  if (!ticketPreviewText.has(key)) ticketPreviewText.set(key, fetch(url).then(async r => {
    if (!r.ok) return null;
    const mime = (r.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
    if (picture) return ['image/png', 'image/jpeg', 'image/webp'].includes(mime) ? {blob:await r.blob()} : null;
    const reader = r.body.getReader(), decoder = new TextDecoder();
    let text = '';
    try { while (text.length < 2048) { const part = await reader.read(); if (part.done) break; text += decoder.decode(part.value, {stream:true}); } }
    finally { await reader.cancel(); }
    return {text:text.slice(0, 2048).split('\n').slice(0, 8).join('\n')};
  }).catch(() => null));
  ticketPreviewText.get(key).then(data => {
    if (data?.blob) {
      const src = URL.createObjectURL(data.blob), img = h('img', {src, alt:title, loading:'lazy'});
      img.onload = img.onerror = () => URL.revokeObjectURL(src); tile.append(img);
    } else if (data?.text) tile.append(h('pre', {}, data.text));
  });
  return tile;
}
function ticketResultCard(t, ev, file = null, kind = 'evidence') {
  const helpers = window.DashHelpers;
  const title = helpers.cleanOutcome(ev.title) || (file || (ev.type || ev.kind) === 'file' ? helpers.plainFileName(file?.name || ev.ref) : helpers.cleanOutcome(ev.summary)) || 'Result';
  const summary = helpers.cleanOutcome(ev.summary) || helpers.cleanOutcome(ev.text) || 'Completed.';
  const at = ev.at || file?.mtime;
  return h('article', {className:'card ticket-result'}, h('h3', {}, clean(title)), h('p', {}, clean(summary)),
    at ? h('time', {className:'meta', datetime:at}, helpers.stamp(at, Date.now())) : null,
    file ? ticketPreviewTile(t, file, kind) : h('div', {className:'ticket-preview'}, h('p', {}, clean(summary))),
    file && !snapshot ? ticketButton('Open', 'outline', () => previewFile(t.id, kind, file.name)) : null,
    file && kind === 'artifacts' ? ticketShareButton(t, file) : null);
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
  return ticketButton('Share with group', 'outline', () => share(false));
}
function ticketReviewTile(t, file) {
  if (!file) return null;
  const ext = /\.([^.\/]+)$/.exec(file.name)?.[1].toLowerCase();
  const type = /^(html?|pdf)$/.test(ext || '') ? (ext === 'pdf' ? 'PDF' : 'Page') : ext?.toUpperCase();
  const meta = [type, typeof file.size === 'number' && Number.isFinite(file.size) && file.size >= 0 ? sizeText(file.size) : null].filter(Boolean).join(' · ');
  return h('div', {className:'ticket-review-tile'}, iconEl('file'),
    h('span', {className:'ticket-review-name'}, clean(window.DashHelpers.plainFileName(file.name) || 'Result')),
    meta ? h('span', {className:'meta'}, meta) : null,
    snapshot ? null : ticketButton('Open', 'outline', () => previewFile(t.id, 'artifacts', file.name)));
}
function artifactsPanel(t) {
  const files = array(artifactData.get(t.id)?.data?.files), proofs = proofRows(t), links = linkRows(t);
  if (!files.length && !proofs.length && !links.length) return h('div', {className:'card artifacts-empty'}, h('h2', {}, 'Nothing here yet'), h('p', {className:'meta'}, 'Results and references from this ticket show up here.'));
  return h('div', {className:'stack artifact-stack'}, h('h2', {}, 'Artifacts'),
    files.map(file => ticketResultCard(t, {}, file, 'artifacts')),
    proofs.map(({ev}) => {
      const prefix = '.orch/tickets/' + t.id + '/evidence/';
      const ref = String(ev.ref || '');
      const file = (ev.type || ev.kind) === 'file' && !ev.missing && ref.startsWith(prefix) ? {name:ref.slice(prefix.length), mtime:ev.at} : null;
      return ticketResultCard(t, ev, file);
    }),
    links.length ? h('section', {}, h('h2', {}, 'References'), links.map(l => linkRow(t, l, false))) : null);
}
async function previewFile(tid, kind, fileName) {
  if (snapshot || !tid || !fileName) return;
  const {d, actions} = dialog(fileName, 'sheet');
  actions.firstChild.textContent = 'Close';
  const q = '?t=' + encodeURIComponent(tid) + '&k=' + encodeURIComponent(kind) + '&n=' + encodeURIComponent(fileName);
  const stage = el('div', 'preview-stage');
  const dl = h('a', {className:'btn outline', href:'/api/file' + q + '&dl=1', download:fileName.split('/').pop()}, 'Download');
  actions.append(dl);
  d.append(stage, actions);
  window.orch.open(d);
  if (PREVIEW_EXT.image.test(fileName)) { const img = el('img'); img.alt = fileName; img.src = '/api/file' + q; stage.append(img); return; }
  try {
    const r = await fetch('/api/file' + q);
    if (!r.ok) throw new Error('no');
    const pre = el('pre'); pre.textContent = (await r.text()).slice(0, 200000);
    stage.append(pre);
  } catch (_) { stage.append(el('p', 'meta pad', 'This file cannot be shown here.')); }
}
function ticketActor(by) {
  return /^agent:/.test(by || '') || array(state.settings?.agents).some(a => a.name === by) ? window.DashHelpers.agentLabel(state.settings, {agent:String(by).replace(/^agent:/, '')}) : name(by);
}
function ticketTaskOutcome(task) {
  const ev = array(task.evidence).slice(-1)[0];
  return window.DashHelpers.outcome(task) + (ev?.at ? ' · ' + window.DashHelpers.stamp(ev.at, Date.now()) : '') + (ev?.by ? ' — ' + ticketActor(ev.by) : '');
}
function focusTicketAnswer() {
  const card = main.querySelector('.next-question');
  if (!card) return;
  card.scrollIntoView({block:'center', behavior:'smooth'});
  const target = card.querySelector('[data-question] button, [data-question] input, [data-question] textarea');
  target?.focus({preventScroll:true});
}
function taskRows(t) {
  return array(t.checklist).map((task, i) => {
    const meta = [ticketActor(task.owner || task.by), clean(window.DashHelpers.cleanOutcome(task.summary))].filter(Boolean).join(' · ');
    const mark = snapshot || !task.id ? (task.done ? h('span', {className:'good'}, iconEl('check')) : h('span', {className:'dot ' + (task.state === 'doing' && !window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? 'working' : 'idle')}))
      : h('button', {type:'button', className:'task-check' + (task.done ? ' on' : ''), role:'checkbox', 'aria-checked':String(!!task.done), 'aria-label':clean(task.text), 'data-key':'task-check-' + task.id}, task.done ? iconEl('check') : null);
    if (!snapshot && task.id) mark.onclick = () => toggleTask(t.id, task.id);
    return h('div', {className:'card-row ticket-task-row', 'data-key':'task-' + (task.id || i)}, mark,
      h('div', {className:'grow'}, h('h3', {}, task.state === 'doing' && !window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? h('span', {className:'ticket-spinner', title:'Agent is working', 'aria-label':'Agent is working'}) : null, clean(task.text)), meta ? h('p', {className:'meta'}, meta) : null,
        h('p', {className:'meta task-proof'}, task.state === 'doing' && window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? 'Not started yet.' : ticketTaskOutcome(task))));
  });
}
// "+ Add task": one line, Enter adds it (orch check add). The draft is kept while the page refreshes.
function addTaskRow(t, scope) {
  if (snapshot) return null;
  const key = 'add-task-' + scope + '-' + t.id;
  const input = el('input', 'input');
  Object.assign(input, {type:'text', placeholder:'+ Add task', maxLength:500, name:'task'});
  input.setAttribute('aria-label', 'Add a task');
  const form = el('form', 'card-row add-task');
  form.dataset.key = key;
  const send = button('Add', 'outline sm', null);
  send.type = 'submit';
  form.append(input, send);
  input.addEventListener('focusin', () => locks.add(key));
  input.addEventListener('blur', () => { if (!input.value.trim()) { locks.delete(key); setTimeout(render, 0); } });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
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
function selectTicketTab(id, tab, focusQuestion = false) {
  ticketTabs.set(id, tab);
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
  const src = (n, dl) => '/api/file?t=' + encodeURIComponent(tid) + '&k=files&n=' + encodeURIComponent(n) + (dl ? '&dl=1' : '');
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
function ticketButton(label, cls, click, attrs = {}) {
  const node = h('button', {type:'button', className:'btn ' + cls, 'data-key':'ticket-button-' + label, ...attrs}, label);
  node.onclick = click;
  return node;
}
let ticketHistoryTechnical = false;
let ticketHistoryActor = 'All';
function ticketHistoryWho(entry) {
  const by = String(entry.by || entry.actor || '');
  return /^human:/.test(by) ? 'People' : /^agent:/.test(by) ? 'Agent' : 'System';
}
function ticketHistoryIsTechnical(entry) {
  const kind = String(entry.kind || entry.type || '').toLowerCase(), text = String(entry.text || '');
  if (/answer|verdict|review|created|done/.test(kind) || /^(Created|Answered|Done|Check c\d+ done|Finished a task)|(?:->|to) done\b/i.test(text)) return false;
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
  return d.toDateString() === now.toDateString() ? 'Today' : d.toDateString() === yesterday.toDateString() ? 'Yesterday' : d.toLocaleDateString(undefined, {day:'numeric', month:'short', year:'numeric'});
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
      h('p', {}, view.sentence ? clean(view.sentence) : [ticketActor(entry.by), clean(view.line)].filter(Boolean).join(' · ')), h('time', {className:'meta', datetime:entry.at}, time(entry.at))));
  }
  const controls = snapshot ? null : h('div', {className:'ticket-history-filters'}, ['All', 'People', 'Agent'].map(label => ticketButton(label, 'outline', () => { ticketHistoryActor = label; render(); }, {'aria-pressed':ticketHistoryActor === label})),
    ticketButton('Show technical steps', 'ghost', () => { ticketHistoryTechnical = !ticketHistoryTechnical; render(); }, {role:'switch', 'aria-checked':ticketHistoryTechnical}));
  return card('history', 'History', '', [controls, groups.size ? [...groups].map(([day, rows]) => h('section', {className:'ticket-history-day'}, h('h3', {}, day), rows)) : emptyRow('No history yet.')]);
}
function ticketStepState(t, run) {
  const step = ({open:'Plan', ready:'Plan', active:'Work', waiting:'Work', review:'Check', done:'Done'})[t.status] || 'Plan';
  const who = t.status === 'done' ? 'done' : array(t.questions).some(q => q.answer == null) || t.status === 'review' ? 'person' : t.status === 'active' && run?.running === true ? 'agent' : ['open', 'ready'].includes(t.status) ? 'person' : '';
  return {step, who};
}
function ticketStepper(t, run) {
  const current = ticketStepState(t, run);
  return h('nav', {className:'ticket-stepper', 'aria-label':'Ticket progress'}, ['Plan', 'Work', 'Check', 'Done'].map(label => {
    const who = label === current.step ? current.who : '', hint = who === 'person' ? 'You are needed' : who === 'agent' ? 'Agent is working' : who === 'done' ? 'Done' : label;
    return h(label === current.step ? 'strong' : 'span', {className:'step-' + who, title:hint, 'aria-label':label + ' · ' + hint, 'aria-current':label === current.step ? 'step' : null}, who ? ticketGlyph(who === 'person' ? 'user' : who === 'agent' ? 'robot' : 'check') : null, label);
  }));
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
  const done = ticketButton('Accept', 'primary', () => moveTicket(t.id, 'done'));
  const row = h('div', {className:'row ticket-review-actions'});
  const open = ticketButton('Ask for changes', 'outline', () => {
    locks.add(key);
    let sending = false;
    const input = h('input', {type:'text', className:'input', placeholder:'What should change?', 'aria-label':'What should change?'});
    const close = () => { if (sending) return; locks.delete(key); host.replaceChildren(row); open.focus(); };
    const send = ticketButton('Send', 'primary sm', async () => {
      if (!input.value.trim() || sending) return;
      sending = true; send.disabled = true; input.disabled = true; cancel.disabled = true;
      let sent = false;
      try { sent = await ticketSendChanges(t, input.value); }
      finally { sending = false; input.disabled = false; cancel.disabled = false; send.disabled = !input.value.trim(); }
      if (sent) { close(); render(); }
    });
    const cancel = ticketButton(iconEl('x'), 'ghost icon', close, {'aria-label':'Cancel', 'data-key':'ticket-ask-cancel'});
    send.disabled = true;
    input.oninput = () => { send.disabled = sending || !input.value.trim(); };
    input.onkeydown = e => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send.click(); }
    };
    host.replaceChildren(h('div', {className:'ticket-ask-line'}, input, send, cancel)); input.focus();
  });
  row.append(done, open); host.append(row); return host;
}
function ticketQuestion(t, q, next = false) {
  return h('section', {className:next ? 'card next-step next-question' : 'ticket-question'},
    h('div', {className:'meta ticket-eyeline'}, (next ? 'Next step · ' : '') + clean(q.title || 'Your answer'), ticketPhone(q)),
    h('h2', {}, clean(q.text)), snapshot ? h('p', {className:'meta'}, 'Waiting for an answer') : h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
}
// "PIL-2 · Title": the key says which ticket, the title what it is.
const partName = p => (typeof p.key === 'string' && p.key ? p.key + ' · ' : '') + clean(p.title);
function ticketParts(t, children) {
  const add = snapshot ? null : ticketButton('+ Add a part', 'ghost add-row', () => {
    const {d, actions} = dialog('What is this part about?');
    const input = h('input', {className:'input', 'aria-label':'What is this part about?', maxlength:200});
    const send = ticketButton('Add', 'primary', async () => {
      const title = input.value.trim(); if (!title || send.disabled) return;
      send.disabled = true;
      const result = await act('ticket.new', {title, parent:t.id});
      if (result.ok) window.orch.close(d); else { send.disabled = false; window.orch.toast(changeError(result), 'error'); }
    });
    input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send.click(); } };
    actions.append(send); d.append(input, actions); window.orch.open(d); input.focus();
  });
  return card('parts', 'Parts', children.filter(c => c.status === 'done').length + ' of ' + children.length + ' parts done', [!children.length ? emptyRow('No parts yet.') : null, children.map(child => h('a', {className:'card-row ticket-part', href:href(child.id)}, h('span', {className:'meta'}, child.key || ''), h('span', {className:'grow'}, clean(child.title)), statusChip(child), h('span', {'aria-hidden':'true'}, '›'))), add]);
}
function ticketDoneLine(t) {
  if (t.status !== 'done') return null;
  const event = array(t.history).slice().reverse().find(e => /(?:->|to) done\b|^Done\b/i.test(e.text || '') || e.kind === 'done');
  const at = event?.at || t.updated_at;
  return h('p', {className:'ticket-done'}, '✓ Done' + (at ? ' ' + window.DashHelpers.ago(at, Date.now()) : '') + (event?.by ? ' by ' + name(event.by) : ''));
}

function detail(t) {
  if (!t) return ticketNotFound();
  const openQuestions = questions(t), selected = ticketTabs.get(t.id) || 'overview';
  const run = state.runs?.[t.id], sessions = array(t.sessions).slice().sort((a, b) => (Date.parse(b.last_used) || 0) - (Date.parse(a.last_used) || 0));
  const agent = window.DashHelpers.agentLabel(state.settings, run?.claim);
  const total = array(t.checklist).length, done = array(t.checklist).filter(task => task.done).length;
  const parent = window.DashHelpers.parentOf(tickets(), t), children = window.DashHelpers.childrenOf(tickets(), t);
  const field = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));
  const tasksCard = key => t.status === 'done'
    ? h('details', {className:'card ticket-task-collapse', 'data-key':key}, h('summary', {}, 'Tasks · ' + done + ' of ' + total + ' done'), taskRows(t))
    : card(key, 'Tasks', done + ' of ' + total + ' done', [total ? taskRows(t) : emptyRow('No tasks yet.'), addTaskRow(t, key)]);
  loadArtifacts(t, selected === 'artifacts');
  const tabs = [['overview', 'Overview'], ['tasks', 'Tasks ' + done + '/' + total], ['questions', 'Questions' + (openQuestions.length ? ' (' + openQuestions.length + ')' : '')], ['artifacts', 'Artifacts' + (artifactCount(t) ? ' ' + artifactCount(t) : '')], ['history', 'History']];
  const panel = (id, body) => h('section', {id:'ticket-panel-' + id, role:snapshot ? null : 'tabpanel', 'aria-labelledby':snapshot ? null : 'ticket-tab-' + id, className:'stack', hidden:!snapshot && selected !== id, tabindex:'0'}, snapshot ? h('h2', {}, capitalise(id)) : null, body);
  const answered = array(t.questions).filter(q => q.answer != null).slice().reverse().map(q => h('div', {className:'card-row', 'data-key':'answered-' + q.id},
    h('div', {className:'grow'}, h('h3', {}, clean(q.text), ticketPhone(q)), h('p', {className:'preserve-lines'}, clean(q.answer)), h('p', {className:'meta'}, ['Answered', name(q.answered_by), surface(q.via)].filter(Boolean).join(' · ')))));
  const fresh = !total && !sessions.length && !run?.running && ['open', 'ready'].includes(t.status);
  let next = null;
  if (t.status !== 'done') {
    // Review buttons are there whenever the status is Review, even with an open question: the question comes first.
    const file = array(artifactData.get(t.id)?.data?.files)[0];
    const at = file?.mtime;
    const review = t.status === 'review' ? h('section', {className:'card next-step'},
      h('p', {className:'meta'}, 'Next step · Your review'),
      h('h2', {}, agent + ' finished' + (file ? ': ' + clean(window.DashHelpers.plainFileName(file.name)) : '')),
      at ? h('p', {className:'meta'}, 'Completed ' + window.DashHelpers.stamp(at, Date.now())) : null,
      ticketReviewTile(t, file), snapshot ? null : ticketChangesEditor(t)) : null;
    if (openQuestions.length || review) next = [openQuestions.length ? ticketQuestion(t, openQuestions[0], true) : null, review];
    else if (fresh) next = h('section', {className:'card next-step'}, h('p', {className:'meta'}, 'Next step'), h('h2', {}, 'Ready to work on ' + clean(t.title) + '?'), snapshot ? null : ticketButton('Start agent', 'primary', () => act('run.start', {ticket:t.id})));
  }
  const menu = snapshot ? null : h('details', {className:'menu', 'data-key':'ticket-menu-' + t.id}, h('summary', {className:'btn ghost icon', 'aria-label':'More ticket actions'}, iconEl('more')),
    h('div', {className:'menu-pop', role:'menu'}, t.status === 'done' ? ticketButton('Reopen', 'menu-item', () => moveTicket(t.id, 'active'), {role:'menuitem'}) : MOVE_CHOICES.map(([status, label]) => ticketButton(label, 'menu-item', () => moveTicket(t.id, status), {role:'menuitem', 'data-key':'ticket-move-' + status})),
      repeatsAddon() ? [ticketButton('Copy ticket', 'menu-item', () => copyTicket(t), {role:'menuitem', 'data-key':'ticket-copy'}), ticketButton('Repeat…', 'menu-item', () => repeatsDialog('repeat', t.id, repeatsAddon()), {role:'menuitem', 'data-key':'ticket-repeat'})] : null));
  return fragment(h('div', {className:'ticket-page', 'data-key':'ticket-page-' + t.id}, h('header', {className:'stack ticket-heading'},
    parent ? h('a', {href:href(parent.id), className:'muted'}, 'Part of ' + partName(parent)) : null,
    typeof t.key === 'string' ? h('span', {className:'meta'}, t.key) : null,
    h('div', {className:'row'}, h('h1', {className:'grow'}, inlineField(t, 'title')), openQuestions.length && t.status !== 'done' ? chip('Needs you', 'attn') : statusChip(t), !snapshot && openQuestions.length && t.status !== 'done' ? ticketButton('Answer', 'primary', focusTicketAnswer) : null, menu),
    ticketStepper(t, run), ticketDoneLine(t)),
    h('div', {className:'columns ticket-columns'}, h('div', {className:'stack ticket-main'}, next,
      !fresh && !['done', 'review'].includes(t.status) ? agentBar(t) : null, !fresh && !['done', 'review'].includes(t.status) ? liveSessionStrip(t) : null,
      snapshot ? null : h('div', {className:'tabs', role:'tablist', 'aria-label':'Ticket'}, tabs.map(([id, label]) => ticketButton(label, 'ghost', () => selectTicketTab(t.id, id), {id:'ticket-tab-' + id, role:'tab', 'aria-selected':selected === id, 'aria-controls':'ticket-panel-' + id}))),
      panel('overview', [t.summary ? h('p', {className:'muted preserve-lines', 'data-key':'summary'}, clean(t.summary)) : null, children.length || (!parent && !t.parent) ? ticketParts(t, children) : null, tasksCard('overview-tasks'), addonRows(t), ticketLinks(t)]),
      panel('tasks', tasksCard('tasks')),
      panel('questions', [(snapshot || selected === 'questions') ? openQuestions.slice(t.status === 'done' ? 0 : 1).map(q => ticketQuestion(t, q)) : null, openQuestions.length <= (t.status === 'done' ? 0 : 1) ? emptyRow('No other open questions') : null, answered.length ? h('section', {}, h('h2', {}, 'Earlier answers'), answered) : null]),
      panel('artifacts', artifactsPanel(t)), panel('history', ticketHistoryPanel(t))),
    h('div', {className:'stack ticket-side'}, h('aside', {className:'card ticket-aside'}, h('div', {className:'card-h'}, h('h2', {}, 'Details')),
      h('dl', {className:'ticket-details ed-list'}, field('Part of', parent ? h('a', {href:href(parent.id)}, partName(parent)) : h('span', {className:'muted'}, 'No parent ticket')), field('Owner', inlineField(t, 'owner')), field('Due', inlineField(t, 'due')), field('Note', inlineField(t, 'note')), field('Done when', inlineField(t, 'done_when')), field('Agent', agent), field('Created', date(t.created_at)), field('Updated', t.updated_at ? window.DashHelpers.ago(t.updated_at, Date.now()) : ''))), linksCard(t), fieldSections(t)))));
}

const MULTILINE = ['note', 'done_when'];
const FIELD_HINT = {title:'Untitled', owner:'Not chosen yet', due:'Not set', note:'Add a note', done_when:'Say what should be true when it is done'};
// A value on the ticket page: a plain click turns it into a field; Enter or leaving it saves, Esc cancels.
function inlineField(t, field) {
  const raw = t[field] == null ? '' : String(t[field]);
  const shown = field === 'due' ? date(raw) : field === 'owner' ? name(raw) : clean(raw);
  if (snapshot) return el('span', MULTILINE.includes(field) ? 'ed-ro preserve-lines' : 'ed-ro', shown || (field === 'title' ? '' : FIELD_HINT[field]));
  const host = el('span', 'inline-host');
  host.dataset.key = 'inline-' + field + '-' + t.id;
  const node = el('button', 'ed' + (shown ? '' : ' empty-v') + (MULTILINE.includes(field) ? ' preserve-lines' : '') + (field === 'title' ? ' ed-title' : ''), shown || FIELD_HINT[field]);
  Object.assign(node, {type:'button', title:'Click to change'});
  Object.assign(node.dataset, {action:'inline', field, ticket:t.id});
  host.append(node);
  return host;
}
async function saveField(t, field, value) {
  const same = o => String(o?.[field] ?? '') === String(t[field] ?? '');
  const result = await actRetry('ticket.edit', () => ({ticket:t.id, [field]:value, if_revision:(ticketOf(t.id) || t).revision}), () => same(ticketOf(t.id)));
  if (!result.ok) window.orch.toast(changeError(result), 'error');
}
function startInline(control) {
  const t = ticketOf(control.dataset.ticket), field = control.dataset.field, host = control.parentElement;
  if (!t || !host || locks.has(host.dataset.key)) return;
  const key = host.dataset.key;
  const before = field === 'owner' ? name(t.owner) : t[field] == null ? '' : String(t[field]);
  if (field === 'due') {
    locks.add(key);
    pickDate(control, before, async value => { if (value !== null && value !== before) await saveField(t, 'due', value); locks.delete(key); render(); });
    return;
  }
  const input = el(MULTILINE.includes(field) ? 'textarea' : 'input', 'input inline-input');
  if (MULTILINE.includes(field)) input.rows = 3; else input.type = 'text';
  if (field === 'title') input.maxLength = 200;
  input.value = before;
  input.setAttribute('aria-label', capitalise(field));
  locks.add(key);
  host.replaceChildren(input, el('span', 'hint', MULTILINE.includes(field) ? 'Enter saves · Shift+Enter new line · Esc cancels' : 'Enter saves · Esc cancels'));
  input.focus();
  let done = false;
  const finish = async save => {
    if (done) return;
    done = true;
    const value = MULTILINE.includes(field) ? input.value : input.value.trim();
    if (save && value !== before && !(field === 'title' && !value)) await saveField(t, field, value);
    locks.delete(key);
    render();
  };
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !(MULTILINE.includes(field) && event.shiftKey)) { event.preventDefault(); finish(true); }
    else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

// A small calendar in the orch look instead of the browser's own picker. cb(value) with 'YYYY-MM-DD', '' (clear) or null (closed).
function pickDate(anchor, current, cb) {
  document.querySelectorAll('.cal').forEach(n => n.remove());
  const iso = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  const todayIso = iso(new Date());
  const start = parse(current) || new Date();
  let view = new Date(start.getFullYear(), start.getMonth(), 1), closed = false;
  const pop = el('div', 'cal');
  pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'Choose a day');
  const close = value => {
    if (closed) return;
    closed = true;
    document.removeEventListener('mousedown', outside, true);
    document.removeEventListener('keydown', key, true);
    pop.remove();
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
      const b = el('button', 'cal-x' + (value === todayIso ? ' today' : '') + (value === current ? ' sel' : ''), String(n));
      b.type = 'button'; b.setAttribute('aria-label', value);
      b.addEventListener('click', () => close(value));
      grid.append(b);
    }
    const foot = el('div', 'cal-f');
    foot.append(button('Clear', 'ghost sm', () => close('')), button('Today', 'outline sm', () => close(todayIso)));
    pop.append(head, grid, foot);
  };
  draw();
  // Inside a dialog the calendar must live in the dialog and in the top layer, or the dialog hides it.
  const host = anchor.closest('dialog');
  if (host) {
    host.append(pop);
    try { pop.setAttribute('popover', 'manual'); pop.showPopover(); } catch (_) { pop.removeAttribute('popover'); }
  } else document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 6, Math.max(8, innerHeight - pop.offsetHeight - 8)) + 'px';
  pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + 'px';
  setTimeout(() => { document.addEventListener('mousedown', outside, true); document.addEventListener('keydown', key, true); }, 0);
  (pop.querySelector('.today, .sel') || pop.querySelector('.cal-x'))?.focus();
}

// An answer still in its Undo window is sent at once when the page is left, so it is not lost.
const sends = new WeakMap();
function flushPending() {
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
      const result = await act('answer', {ticket:q.ticket, question:q.id, answer});
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
  if (action.kind === 'answer' || action.kind === 'review') {
    const {d, actions} = dialog(row.title, 'dialog', 'needs-you');
    const host = el('div');
    d.append(host, actions);
    mountQuestion(host, {ticket:row.ticket, id:row.answer.question, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
    window.orch.open(d);
  } else if (row.ticket) location.hash = href(row.ticket);
  else {
    const a = addons().find(a => a.dashboard && (a.name === row.source || String(row.kind).startsWith(a.name + ':')));
    if (a) location.hash = '#addon/' + encodeURIComponent(a.name);
    else {
      const {d, actions} = dialog(row.title);
      d.append(el('p', 'preserve-lines', clean(row.text || 'No further details.')), actions);
      window.orch.open(d);
    }
  }
}
