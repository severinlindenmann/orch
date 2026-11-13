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
  return h('section', {className:'links-card', 'data-key':'links-card'},
    h('div', {className:'card-h'}, h('h2', {className:'grow'}, 'References'), rows.length ? h('span', {className:'meta'}, String(rows.length)) : null,
      refresh.map(a => h('button', {type:'button', className:'btn ghost xs', title:'Update titles and status (' + addonLabel(a) + ')', 'data-action':'link-refresh', 'data-addon':a.name, 'data-ticket':t.id, 'data-key':'link-refresh-' + a.name}, iconEl('refresh'), refresh.length > 1 ? addonLabel(a) : 'Refresh'))),
    h('div', {className:'links'}, rows.map(l => linkRow(t, l, true)),
      snapshot ? null : h('div', {className:'add-link', 'data-key':'add-link-' + t.id}, h('button', {type:'button', className:'btn ghost sm', 'data-action':'link-add', 'data-ticket':t.id}, '＋ Add reference'))));
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
  const step = array(t.checklist).find(task => !task.wont_do && task.state === 'doing');
  return h('div', {className:'agent-bar', 'data-state':line.state, 'data-key':'agent-bar'},
    h('span', {className:'dot ' + (line.startFailed ? 'error' : run?.running ? 'working' : 'idle'), 'aria-hidden':'true'}),
    line.startFailed ? h('span', {className:'ab-text grow', 'data-key':'start-failed'}, clean(line.status))
      : h('span', {className:'ab-text grow'}, h('strong', {}, name(line.agent)), ' · ', clean(line.hold || step?.text || line.status)), line.startFailed ? null : ticketWarmth(t, run, session),
    snapshot ? null : h('div', {className:'ab-actions'}, liveLink ? h('a', {className:'btn outline', href:liveLink.url}, 'Watch live') : null,
      run?.running ? ticketButton('Stop', 'outline', () => act('run.stop', {ticket:t.id})) : line.primary && !['answer', 'open'].includes(line.primary.op) ? ticketButton(line.primary.label, 'primary', () => { const current = window.DashHelpers.agentLine(ticketOf(t.id), state.runs?.[t.id], Date.now(), liveLinkFor(ticketOf(t.id)), state.settings); if (current.primary && !['answer', 'open'].includes(current.primary.op)) act(current.primary.op, current.primary.args); }) : null));
}

// "X is also changing this folder": one quiet line from the core (orch run status), no banner. A hint, not a lock.
function sharedFolderLine(t) {
  const text = state.runs?.[t.id]?.shared_folder?.line;
  return typeof text === 'string' && text ? h('p', {className:'shared-folder muted', 'data-key':'shared-folder'}, clean(text)) : null;
}
// Draft 1b: a ticket that works in its own copy of the project says so, in one quiet line (branch behind a click).
// The ticket records branch/base/sub/host only, never the local path (it stays in the machine-local registry).
function copyLine(t) {
  const f = Array.isArray(t.work?.folders) ? t.work.folders.filter(x => x && typeof x.branch === 'string' && x.branch) : [];
  if (!f.length) return null;
  return h('div', {className:'shared-folder muted', 'data-key':'work-copy'}, h('span', {}, 'Works in a separate copy of your project, so other helpers do not change the same files.'),
    h('details', {className:'det'}, h('summary', {}, 'Details'), h('div', {}, f.map(x => h('p', {className:'mono'}, clean(String(x.branch || '')) + (typeof x.path === 'string' && x.path ? ' · ' + clean(x.path) : ''))))));
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
function ticketPreviewTile(t, file, kind = 'artifacts') {
  const title = window.DashHelpers.plainFileName(file.name) || 'Result';
  const tile = h('div', {className:'ticket-preview'}, h('span', {className:'ticket-preview-label'}, title));
  const html = /\.html?$/i.test(file.name), picture = /\.(png|jpe?g|webp)$/i.test(file.name);
  if (snapshot || html || (!picture && !PREVIEW_EXT.text.test(file.name))) {
    tile.append(h('p', {className:'meta'}, html ? title : 'Preview available when opened'));
    const live = shownThumb(t, kind, file);
    if (live) { tile.classList.add('has-thumb'); tile.append(live); }
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
  // A finished preview is drawn at once: the page redraws often, and a tile filled later would be thrown away.
  const fill = data => {
    if (data?.blob) {
      const src = URL.createObjectURL(data.blob), img = h('img', {src, alt:title, loading:'lazy'});
      img.onload = img.onerror = () => URL.revokeObjectURL(src); tile.append(img);
    } else if (data?.text) tile.append(h('pre', {}, data.text));
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
  return {name, mtime:ev.at};
};
// One file = one entry: lists keep the first item per key; items without a key (notes) all stay.
const uniqueBy = (list, key) => { const seen = new Set(); return list.filter(x => { const k = key(x); if (k == null) return true; if (seen.has(k)) return false; seen.add(k); return true; }); };
const proofKey = (t, ev) => evidenceFile(t, ev)?.name ?? (ev.ref ? (ev.type || ev.kind) + ':' + ev.ref : null);
const artifactFiles = t => uniqueBy(array(artifactData.get(t.id)?.data?.files), f => f.name);
const reviewFile = t => t.status === 'review' ? artifactFiles(t)[0] : null;
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
  return ticketButton('Share with group', 'outline', () => share(false));
}
// ---- The shared file viewer: name, meta, Open in new tab, Download, Copy link. × Close, Esc and a click outside close it,
// and the opening control gets the cursor back.
const fileUrl = (tid, kind, fileName, dl = false) => '/api/file?t=' + encodeURIComponent(tid) + '&k=' + encodeURIComponent(kind) + '&n=' + encodeURIComponent(fileName) + (dl ? '&dl=1' : '');
const fileTitle = fileName => clean(window.DashHelpers.plainFileName(fileName) || String(fileName).split('/').pop());
const fileBadge = fileName => (/\.([^./]+)$/.exec(fileName)?.[1] || 'file').slice(0, 4).toUpperCase();
const fileMeta = file => [kindWord(file.name), Number.isFinite(file.size) && file.size >= 0 ? sizeText(file.size) : '', file.mtime ? localStamp(file.mtime) : ''].filter(Boolean).join(' · ');
async function copyFileLink(url) {
  try { await navigator.clipboard.writeText(new URL(url, location.href).href); window.orch.toast('Link copied', 'ok'); }
  catch (_) { window.orch.toast('Could not copy the link.', 'error'); }
}
// Every file of a ticket the viewer can step through, with the words the Files tab shows for it.
// The shared viewer (kit/fileviewer.js) names the kind of a file; without it every file is just a file.
const viewerKind = name => window.FileViewer ? window.FileViewer.kindOf(name) : 'other';
const viewerWord = kind => window.FileViewer ? window.FileViewer.word(kind) : 'File';
function ticketFileEntries(t) {
  const entries = ticketFileGroups(t).flatMap(g => g.files.map(file => fileEntry(t, g, file)));
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
  const role = group.kind === 'evidence' ? 'Evidence' : 'Result', task = group.kind === 'evidence' ? group.label : '';
  const at = file.mtime ? createdText(file.mtime) : '';
  return {tid:t.id, kind:group.kind, name:file.name, size:file.size, mtime:file.mtime || '', fileKind:kind, role, task, created:at,
    title:fileTitle(file.name),
    meta:[viewerWord(kind), Number.isFinite(file.size) && file.size >= 0 ? sizeText(file.size) : '', at, task ? 'Task: ' + task : '', role].filter(Boolean).join(' · ')};
}
function createdText(at) {
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return '';
  return 'Created ' + d.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}) + ' · ' + d.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
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
  window.FileViewer.open({files, index, context:t ? clean(t.title || '') : ''});
}
// One compact file row: type badge, name, meta, Open / Download / Copy link.
function ticketFileActions(t, kind, file) {
  if (snapshot) return null;
  const k = kind + '-' + file.name;
  return h('div', {className:'file-actions'},
    ticketButton('Open', 'ghost sm', () => previewFile(t.id, kind, file.name), {'data-key':'file-open-' + k}),
    h('a', {className:'btn ghost sm', href:fileUrl(t.id, kind, file.name, true), download:file.name.split('/').pop()}, 'Download'),
    ticketButton('Copy link', 'ghost sm', () => copyFileLink(fileUrl(t.id, kind, file.name)), {'data-key':'file-copy-' + k}));
}
function ticketFileRow(t, kind, file) {
  return h('div', {className:'file-row', 'data-key':'file-' + kind + '-' + file.name},
    h('span', {className:'file-type' + (shownThumb(t, kind, file) ? ' has-thumb' : ''), 'aria-hidden':'true'}, fileBadge(file.name), shownThumb(t, kind, file)),
    h('div', {className:'grow'}, h('p', {className:'file-name'}, fileTitle(file.name)), h('p', {className:'meta'}, fileMeta(file))),
    ticketFileActions(t, kind, file));
}
// The result frame: the file heading, then a bounded preview with Expand (the shared viewer).
// A PDF shows as the PDF and a web page as the page (in a frame that cannot reach this app); other files as a short excerpt.
function ticketLivePreview(t, file, kind) {
  if (snapshot) return null;
  const type = viewerKind(file.name), title = fileTitle(file.name);
  if (type === 'pdf') return h('object', {className:'preview-live', type:'application/pdf', data:fileUrl(t.id, kind, file.name), 'aria-label':title},
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
// ---- Files tab: toolbar (find, type, sort, group, grid/list), groups of picture tiles, one shared viewer.
const filesUI = {q:'', type:'all', sort:'important', group:'task', view:'grid', all:false, open:new Map(), more:new Set()};
const FILE_TYPES = [['all', 'All types'], ['image', 'Pictures'], ['docs', 'Documents'], ['table', 'Tables'], ['code', 'Code'], ['media', 'Sound and video'], ['other', 'Other']];
const typeGroup = kind => ({image:'image', pdf:'docs', page:'docs', md:'docs', text:'docs', table:'table', xlsx:'table', code:'code', audio:'media', video:'media'}[kind] || 'other');
const SORTS = [['important', 'Most important'], ['newest', 'Newest'], ['oldest', 'Oldest'], ['name', 'Name']];
const GROUPS = [['task', 'By task'], ['role', 'By role'], ['none', 'None']];
function sortedEntries(list) {
  const time = f => Date.parse(f.mtime) || 0;
  const by = {important:(a, b) => (a.role === b.role ? 0 : a.role === 'Result' ? -1 : 1) || time(b) - time(a), newest:(a, b) => time(b) - time(a), oldest:(a, b) => time(a) - time(b), name:(a, b) => a.title.localeCompare(b.title)};
  return list.slice().sort(by[filesUI.sort] || by.important);
}
function fileThumb(t, f) {
  const thumb = h('div', {className:'file-thumb', 'data-kind':f.fileKind});
  if (f.fileKind === 'image') { thumb.append(h('img', {src:fileUrl(f.tid, f.kind, f.name), alt:'', loading:'lazy'})); return thumb; }
  if (['md', 'text', 'code', 'table'].includes(f.fileKind) && f.size <= 2 * 1048576) {
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
  const link = h('button', {type:'button', className:'file-preview-link', 'aria-label':'Preview ' + f.title + ' · ' + f.meta.split(' · ').slice(0, 2).join(' · '), 'data-key':'file-open-' + f.kind + '-' + f.name},
    fileThumb(t, f), h('span', {className:'tile-copy'}, h('strong', {}, f.title), h('span', {className:'meta'}, [viewerWord(f.fileKind), Number.isFinite(f.size) ? sizeText(f.size) : ''].filter(Boolean).join(' · '))));
  link.onclick = open;
  const task = f.task ? h('button', {type:'button', className:'task-link', 'data-key':'file-task-' + f.kind + '-' + f.name}, 'Task: ' + f.task) : null;
  if (task) task.onclick = () => { ticketTabs.set(t.id, 'tasks'); render(); };
  return h('article', {className:'file-tile', 'data-key':'file-tile-' + f.kind + '-' + f.name}, link,
    h('div', {className:'file-context'}, h('span', {className:'role-chip', 'data-role':f.role}, f.role), task, f.created ? h('span', {className:'created-time meta'}, f.created) : null));
}
function fileGroups(entries) {
  if (filesUI.group === 'none') return [{label:'', files:entries, key:'all'}];
  const map = new Map();
  for (const f of entries) {
    const label = filesUI.group === 'role' ? (f.role === 'Result' ? 'Results' : 'Evidence') : (f.task || 'Results');
    if (!map.has(label)) map.set(label, []);
    map.get(label).push(f);
  }
  return [...map].map(([label, files]) => ({label, files, key:label}));
}
function visibleFileEntries(t, all) {
  const q = filesUI.q.trim().toLowerCase();
  return sortedEntries(all.filter(f => (filesUI.type === 'all' || typeGroup(f.fileKind) === filesUI.type) && (!q || (f.title + ' ' + f.name + ' ' + f.task).toLowerCase().includes(q))));
}
function filesPanelBody(t, all) {
  const entries = visibleFileEntries(t, all);
  if (!entries.length) return h('p', {className:'muted', 'data-key':'files-none'}, all.length ? 'No files match. Clear the search or choose All types.' : 'No files attached yet. Files your helper attaches appear here, with the task they belong to.');
  const groups = fileGroups(entries), tasks = new Set(entries.map(f => f.task).filter(Boolean)).size;
  const summary = h('div', {className:'collection-summary'}, h('p', {className:'meta'}, entries.length + (entries.length === 1 ? ' file' : ' files') + (tasks ? ' · ' + tasks + (tasks === 1 ? ' finished step' : ' finished steps') : '')),
    groups.length > 2 && filesUI.group !== 'none' ? ticketButton(filesUI.all ? 'Collapse groups' : 'Show all files', 'ghost sm', () => { filesUI.all = !filesUI.all; filesUI.open.clear(); render(); }, {'data-key':'files-show-all'}) : null);
  const body = groups.map((g, gi) => {
    const grid = open => {
      const limit = 8, more = !filesUI.more.has(g.key) && !filesUI.all && g.files.length > limit && filesUI.view === 'grid';
      const shown = more ? g.files.slice(0, 5) : g.files;
      const tiles = open ? shown.map(f => fileTile(t, f)) : [];
      if (more) {
        const rest = h('button', {type:'button', className:'file-tile file-more', 'data-key':'file-more-' + g.key}, '+' + (g.files.length - 5) + ' more');
        rest.onclick = () => { filesUI.more.add(g.key); render(); };
        tiles.push(rest);
      }
      return h('div', {className:'file-grid'}, tiles);
    };
    if (filesUI.group === 'none') return h('div', {className:'file-group flat', 'data-key':'file-group-all'}, grid(true));
    const isOpen = filesUI.open.has(g.key) ? filesUI.open.get(g.key) : filesUI.all || gi < 2;
    const det = h('details', {className:'file-group', 'data-key':'file-group-' + g.key}, h('summary', {}, h('strong', {}, g.label), h('span', {className:'meta group-count'}, g.files.length + (g.files.length === 1 ? ' file' : ' files'))), grid(isOpen));
    det.open = isOpen;
    det.addEventListener('toggle', () => { if (filesUI.open.get(g.key) !== det.open) { filesUI.open.set(g.key, det.open); render(); } });
    return det;
  });
  return h('div', {className:'files-collection', 'data-view-mode':filesUI.view, 'data-key':'files-collection'}, summary, body);
}
function filesToolbar(count) {
  const select = (label, opts, key, extra) => {
    const s = h('select', {'aria-label':label, 'data-key':'files-' + key, 'data-label':label, ...(extra || {})}, opts.map(([v, text]) => h('option', {value:v}, text)));
    s.value = filesUI[key]; s.onchange = () => { filesUI[key] = s.value; render(); };
    return s;
  };
  const search = h('input', {type:'search', className:'files-search', placeholder:'Find a file…', 'aria-label':'Find a file', 'data-key':'files-search', value:filesUI.q});
  search.value = filesUI.q;
  search.oninput = () => { filesUI.q = search.value; render(); };
  const view = (id, label) => { const b = h('button', {type:'button', className:'btn sm', 'aria-pressed':String(filesUI.view === id), 'data-key':'files-view-' + id}, label); b.onclick = () => { filesUI.view = id; render(); }; return b; };
  return h('div', {className:'files-toolbar', 'data-key':'files-toolbar'}, h('h2', {}, 'Files', h('span', {className:'meta'}, count)), search,
    select('File type', FILE_TYPES, 'type'), select('Sort', SORTS, 'sort', {'data-prefix':'Sort'}), select('Group', GROUPS, 'group', {'data-prefix':'Group'}),
    h('div', {className:'view-switch', role:'group', 'aria-label':'File view'}, view('grid', '▦ Grid'), view('list', '☰ List')));
}
function artifactsPanel(t) {
  if (snapshot) {  // a saved copy cannot read files: names only, no controls
    const groups = ticketFileGroups(t);
    return [h('div', {className:'section-head'}, h('h2', {}, 'Files'), h('span', {className:'meta'}, ticketFileCount(t) + (ticketFileCount(t) === 1 ? ' file' : ' files'))),
      groups.length ? groups.map(g => h('section', {className:'file-group', 'data-key':'file-group-' + g.label}, h('h3', {className:'meta'}, g.kind === 'evidence' ? 'For: ' + g.label : g.label), g.files.map(f => ticketFileRow(t, g.kind, f))))
        : h('p', {className:'muted'}, 'No files attached yet.')];
  }
  const all = ticketFileEntries(t);
  if (!all.length && !artifactData.get(t.id)?.data) return [filesToolbar(0), h('div', {className:'file-grid file-skeleton', 'aria-busy':'true', 'aria-label':'Loading files', 'data-key':'files-skeleton'},
    [0, 1, 2].map(i => h('div', {className:'file-tile skeleton-tile', 'data-key':'skeleton-' + i})))];
  return [filesToolbar(all.length), filesPanelBody(t, all)];
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
  const target = card.querySelector('[data-question] button, [data-question] input, [data-question] textarea, .ticket-plan-actions button');
  target?.focus({preventScroll:true});
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
    const meta = [ticketActor(task.owner || task.by), clean(window.DashHelpers.cleanOutcome(task.summary))].filter(Boolean).join(' · ');
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
        h('button', {type:'submit', className:'btn outline sm'}, window.DashHelpers.resolved(task) ? 'Open again' : "Won't do"));
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
        task.wont_do ? h('p', {className:'meta task-note'}, task.reason ? 'Skipped: ' + clean(task.reason) : 'Skipped. No reason was given.') : null,
        array(task.evidence).filter(ev => (ev.type || ev.kind) === 'note' && (ev.text || ev.title)).map(ev => h('p', {className:'preserve-lines task-evidence-note'}, clean(ev.text || ev.title))),
        meta ? h('p', {className:'meta'}, meta) : null,
        task.wont_do ? null : h('p', {className:'meta task-proof'}, doing && window.DashHelpers.startFailure(t, state.runs?.[t.id], state.settings) ? 'Not started yet.' : ticketTaskOutcome(task)),
        taskProofChips(t, task)), h('span', {className:'meta task-word'}, taskWord(task)), menu);
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
// "Changes to add": a dialog shows exactly what the click approves (the tip, the count, the first
// control paths; all made plain on the server) and sends back that same tip, count and path hash.
function ticketBringBackDialog(t) {
  const b = t.bring_back || {}, paths = array(b.paths).map(p => clean(p)), count = Number(b.control_paths) || 0;
  const {d, actions} = dialog('Add these changes to your files?');
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
  const go = ticketButton('Add to my files', 'primary', async () => {
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
  const ask = !snapshot && b.reason_code === 'update' ? ticketButton('Ask the helper to update', 'ghost sm', async () => {
    const r = await act('copies.ask-update', {ticket:t.id});
    window.orch.toast(r.ok ? 'Asked the helper to update its copy' : r.text || 'That did not work.', r.ok ? 'success' : 'error');
  }) : null;
  const add = !snapshot && b.tip ? ticketButton('Add to my files', 'primary sm', () => ticketBringBackDialog(t)) : null;
  // "Keep as is" is only this page's choice: nothing is changed or signed; the copy stays where it is.
  if (!snapshot && b.tip && isKept(t)) return h('p', {className:'meta kept-line', 'data-key':'bring-back'}, 'Changes kept in a copy · ', ticketButton('Add to my files', 'ghost sm', () => ticketBringBackDialog(t)));
  const review = !snapshot && b.tip ? ticketButton('Review changes', 'outline sm', () => ticketChangesDialog(t)) : null;
  const keep = !snapshot && b.tip ? ticketButton('Keep as is', 'ghost sm', () => {
    keptCopies.add(keptKey(t)); try { sessionStorage.setItem(keptKey(t), '1'); } catch (_) { /* optional */ }
    render();
  }) : null;
  return h('section', {className:'card attention decision bring-back-card', 'data-key':'bring-back'},
    h('p', {className:'meta'}, 'Approval needed'), h('h2', {}, 'Changes to add'), h('p', {className:'muted'}, clean(b.reason)),
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
  const controls = snapshot ? null : h('div', {className:'ticket-history-filters', role:'group', 'aria-label':'Show'}, ['All', 'People', 'Helper'].map(label => ticketButton(label, 'outline sm', () => { ticketHistoryActor = label; render(); }, {'aria-pressed':String(ticketHistoryActor === label)})));
  return card('history', 'Activity', '', [controls, groups.size ? [...groups].map(([day, rows]) => h('section', {className:'ticket-history-day'}, h('h3', {}, day), rows)) : emptyRow('No history yet.')]);
}
function ticketStepState(t, run) {
  const step = ({open:'Plan', ready:'Plan', active:'Work', waiting:'Work', review:'Check', done:'Done'})[t.status] || 'Plan';
  const who = t.status === 'done' ? 'done' : array(t.questions).some(q => q.answer == null) || t.status === 'review' ? 'person' : t.status === 'active' && run?.running === true ? 'agent' : ['open', 'ready'].includes(t.status) ? 'person' : '';
  return {step, who};
}
function ticketStepper(t, run) {
  const current = ticketStepState(t, run), steps = ['Plan', 'Work', 'Check', 'Done'], at = steps.indexOf(current.step);
  return h('ol', {className:'stepper ticket-stepper', 'aria-label':'Ticket progress'}, steps.map((label, i) => {
    const done = i < at || t.status === 'done', now = i === at && !done;
    const hint = now ? ({person:'You are needed', agent:'Helper is working'})[current.who] || 'Now' : done ? 'Done' : 'Later';
    return h('li', {'aria-current':i === at ? 'step' : null, title:hint}, h('span', {className:'phase' + (done ? ' done' : now ? ' current' : ''), 'aria-hidden':'true'}, done ? '✓' : now ? '' : String(i + 1)), label, h('span', {className:'sr-only'}, ' · ' + hint));
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
  // B13g: the tip recorded for this review is shown, and Accept sends that same tip: the core tells when
  // new changes arrived after you looked (the Done still happens; bringing them back then needs your OK).
  const tip = typeof t.review_tip === 'string' && /^[0-9a-f]{40,64}$/.test(t.review_tip) ? t.review_tip : '';
  const done = ticketButton('Looks good', 'primary sm', () => moveTicket(t.id, 'done', false, tip ? {review_tip:tip} : {}), {'data-key':'ticket-button-Accept-' + (tip ? tip.slice(0, 20) : 'none')}); // keyed by the tip: a refresh never keeps a handler with a stale one
  const row = h('div', {className:'row ticket-review-actions'});
  const shown = tip ? h('span', {className:'meta', 'data-key':'ticket-review-tip'}, 'Changes up to ', h('code', {}, tip.slice(0, 12))) : null;
  const open = ticketButton('Ask for changes', 'outline sm', () => {
    locks.add(key);
    let sending = false;
    const input = h('input', {type:'text', className:'input', placeholder:'What should change?', 'aria-label':'What should change?'});
    const close = () => { if (sending) return; locks.delete(key); host.replaceChildren(row); open.focus(); };
    const send = ticketButton('Send request', 'primary sm', async () => {
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
    host.replaceChildren(h('label', {className:'ticket-ask-label'}, 'What should change?'), h('div', {className:'ticket-ask-line'}, input, send, cancel)); input.focus();
  });
  row.append(...[done, open, shown].filter(Boolean)); host.append(row); return host;
}
function ticketQuestion(t, q, next = false) {
  return h('section', {className:next ? 'card next-step next-question' : 'ticket-question'},
    h('div', {className:'meta ticket-eyeline'}, (next ? 'Next step · ' : '') + clean(q.title || 'Your answer'), ticketPhone(q)),
    h('h2', {}, clean(q.text)), snapshot ? h('p', {className:'meta'}, 'Waiting for an answer') : h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
}
// A step is named by its title only; the ticket key is a quiet line under Properties.
const partName = p => clean(p.title);
function ticketAddStep(t) {
  const {d, actions} = dialog('What is this step about?');
  const input = h('input', {className:'input', 'aria-label':'What is this step about?', maxlength:200});
  const send = ticketButton('Add', 'primary', async () => {
    const title = input.value.trim(); if (!title || send.disabled) return;
    send.disabled = true;
    const result = await act('ticket.new', {title, parent:t.id});
    if (result.ok) window.orch.close(d); else { send.disabled = false; window.orch.toast(changeError(result), 'error'); }
  });
  input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send.click(); } };
  actions.append(send); d.append(input, actions); window.orch.open(d); input.focus();
}
function ticketParts(t, children) {
  const add = snapshot ? null : ticketButton('+ Add a step', 'ghost add-row', () => ticketAddStep(t));
  // No steps yet: only the add button, so a top-level ticket can get its first step (a step itself gets none).
  if (!children.length) return add && !window.DashHelpers.parentOf(tickets(), t) ? h('div', {className:'row', 'data-key':'parts-add'}, add) : null;
  return card('parts', 'Steps', children.filter(c => c.status === 'done').length + ' of ' + children.length + ' done', [children.map(child => h('a', {className:'card-row ticket-part', href:href(child.id)}, h('span', {className:'grow'}, clean(child.title)), statusChip(child), h('span', {'aria-hidden':'true'}, '›'))), add]);
}
const ticketPlanEditing = new Set();
function ticketRenameStep(child) {
  const {d, actions} = dialog('Rename step');
  const input = h('input', {className:'input', 'aria-label':'Step title', maxlength:200, value:child.title});
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
      ticketButton('Change a step', 'outline', () => { if (editing) ticketPlanEditing.delete(t.id); else ticketPlanEditing.add(t.id); render(); }),
      editing ? [ticketButton('+ Add a step', 'ghost', () => ticketAddStep(t)),
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
const PROOF_WORD = {passed:'Check passed', failed:'Check failed', changed:'Changed since the check', note:'Note only', missing:'No proof yet'};
const RECHECK_TEXT = 'Please run the checks again and record them with orch check record.';
function ticketProofLine(t) {
  const p = t.proof;
  if (!p || typeof p.line !== 'string' || !p.line) return null;
  const per = p.per_item && typeof p.per_item === 'object' ? p.per_item : {};
  const level = ({ok:'ok', note:'none', warn:'warn', fail:'bad'})[p.level] || 'none';
  const mark = {ok:'✓', bad:'×', warn:'!', none:'–'}[level];
  const rows = array(t.checklist).map(task => { const [cls, glyph] = PROOF_MARK[per[task.id]] || PROOF_MARK.missing;
    return h('li', {className:'proof-row'}, h('span', {className:'proof-mark proof-' + cls}, glyph), ' ', clean(task.text), ' ', h('span', {className:'meta'}, PROOF_WORD[per[task.id]] || PROOF_WORD.missing)); });
  return h('div', {className:'ticket-proof', 'data-key':'ticket-proof-' + t.id},
    h('p', {className:'ticket-proof-line'}, h('span', {className:'proof-mark proof-' + level}, mark), ' ', h('span', {className:'grow'}, p.line)),
    Object.values(per).includes('changed') && t.status === 'review' && !snapshot ? ticketButton('Ask the helper to check again', 'outline sm', () => ticketSendChanges(t, RECHECK_TEXT), {'data-key':'ticket-recheck-' + t.id}) : null,
    rows.length || array(p.uncovered).length ? h('ul', {className:'ticket-proof-rows'}, rows, array(p.uncovered).map(part => h('li', {className:'proof-row'}, h('span', {className:'proof-mark proof-warn'}, '!'), ' “' + clean(part) + '” ', h('span', {className:'meta'}, 'No task covers this')))) : null);
}

// Header line: only in review (the card shows it there) and done, only with tasks; never a warning on a finished ticket.
function headerProof(t) {
  if (t.status !== 'done' || !array(t.checklist).length || array(t.proof?.uncovered).length) return null;
  return ticketProofLine(t);
}

// The history entry that marked the ticket done; the ticket page and the list both take the finish time from it.
function ticketDoneEvent(t) {
  return array(t.history).slice().reverse().find(e => e && (e.kind === 'done' || /(?:->|to) done\b|^Done\b/i.test(e.text || '')));
}
function ticketDoneLine(t) {
  if (t.status !== 'done') return null;
  const event = ticketDoneEvent(t);
  const at = event?.at || t.done_at || t.updated_at;
  return h('p', {className:'ticket-done'}, '✓ Finished' + (at ? ' ' + localStamp(at) : '') + (event?.by ? ' by ' + name(event.by) : ''));
}
// One local format for every time on the ticket page: "Thu 12 Nov, 14:03" (the year only when it is not this year).
function localStamp(at, withTime = true) {
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return '';
  const opts = {weekday:'short', day:'numeric', month:'short', ...(d.getFullYear() !== new Date().getFullYear() ? {year:'numeric'} : {}), ...(withTime ? {hour:'2-digit', minute:'2-digit'} : {})};
  return d.toLocaleString(undefined, opts);
}
// A ticket a helper already worked on (it has sessions) but that is not running now is paused, not new.
// Tasks a person typed before any helper ran do not make it paused.
function ticketPaused(t, run) {
  return ['open', 'ready'].includes(t.status) && !run?.running && array(t.sessions).length > 0;
}
// ---- The ticket page: header (actions, title, one state line, stepper), tabs Overview / Tasks / Files / Activity, Properties.
function ticketStatusWord(t, run) {
  if (t.status === 'done') return ['good', '✓ Done'];
  if (questions(t).length) return ['warn', '! Needs you'];
  if (t.status === 'review') return ['warn', '◇ Check'];
  if (t.bring_back?.state === 'waiting') return ['warn', '! Changes waiting'];
  if (run?.running) return ['working', '◉ Working'];
  return ['', ({open:'Open', ready:'Ready', active:'In progress', waiting:'Waiting'})[t.status] || 'Open'];
}
const openChanges = t => array(t.checklist).filter(c => !c.done && !c.wont_do && changeTask(c.text, c.origin));
function ticketStateSentence(t, run, fresh) {
  const join = (...parts) => parts.filter(Boolean).join(' · ');
  if (t.status === 'done') {
    const ev = ticketDoneEvent(t), n = array(t.checklist).filter(c => c.done && !c.wont_do).length, at = ev?.at || t.done_at || t.updated_at;
    return join('Finished' + (ev?.by ? ' by ' + name(ev.by) : ''), at ? time(at) : '', n ? n + (n === 1 ? ' task completed' : ' tasks completed') : '');
  }
  const q = questions(t)[0];
  if (q) return join(run?.running ? 'Your helper is waiting' : 'Your helper is paused', 'waiting for your answer' + (t.updated_at ? ' since ' + time(t.updated_at) : ''));
  if (t.status === 'review') return join('Your helper finished', t.updated_at ? time(t.updated_at) : '', 'waiting for your review');
  if (run?.running) return openChanges(t).length ? 'Working on your change' : 'Your helper is working';
  if (fresh) return 'Nothing has happened yet';
  if (ticketPaused(t, run)) return join('Paused', t.updated_at ? localStamp(t.updated_at) : '');
  return t.updated_at ? 'Updated ' + localStamp(t.updated_at) : '';
}
const taskTitle = task => clean(changeTask(task.text, task.origin)?.title || task.text);
const taskWord = task => task.wont_do ? 'Skipped' : task.done ? 'Done' : task.state === 'doing' ? 'Working' : 'To do';
function ticketProgressCounts(t) {
  const list = array(t.checklist), n = f => list.filter(f).length;
  const done = n(c => c.done && !c.wont_do), skipped = n(c => c.wont_do), doing = n(c => !c.done && !c.wont_do && c.state === 'doing');
  const todo = list.length - done - skipped - doing;
  return [done && done + ' done', skipped && skipped + ' skipped', doing && doing + ' in progress', todo && todo + ' to do'].filter(Boolean).join(' · ');
}
// "Progress": counts and one row per task; the task the helper works on now is highlighted.
function ticketProgress(t, run) {
  const list = array(t.checklist);
  if (!list.length) return null;
  const current = run?.running ? list.find(c => !c.done && !c.wont_do && c.state === 'doing') : null;
  return h('section', {className:'card progress-card', 'data-key':'progress'}, h('div', {className:'section-head'}, h('h2', {}, 'Progress'), h('span', {className:'meta'}, ticketProgressCounts(t))),
    h('ol', {className:'task-list'}, list.map((c, i) => c === current
      ? h('li', {className:'current-task', 'data-key':'progress-' + (c.id || i)}, h('span', {className:'task-mark working', 'aria-hidden':'true'}, '◉'), h('div', {className:'grow'}, h('h3', {}, taskTitle(c)), h('p', {className:'meta'}, 'Your helper is working on this task.')))
      : h('li', {className:'task-row' + (c.wont_do ? ' skipped' : ''), 'data-key':'progress-' + (c.id || i)}, h('span', {className:'task-mark' + (c.done && !c.wont_do ? ' good' : ''), 'aria-hidden':'true'}, c.wont_do ? '–' : c.done ? '✓' : '○'),
        h('div', {className:'grow'}, h('p', {className:'task-title'}, taskTitle(c)), c.wont_do && c.reason ? h('p', {className:'task-note meta'}, clean(c.reason)) : null), h('span', {className:'meta'}, taskWord(c))))));
}
// The review card: the result first, then the question, the proof and the verdict.
function ticketReviewCard(t) {
  const file = reviewFile(t), count = artifactFiles(t).length;
  return h('section', {className:'card attention decision review-card', 'data-key':'review-card-' + t.id},
    h('div', {className:'section-head'}, h('h2', {}, 'Your review'), count ? h('span', {className:'meta'}, count + (count === 1 ? ' result' : ' results')) : null),
    t.summary ? h('p', {className:'muted preserve-lines', 'data-key':'summary'}, 'In short: ' + clean(t.summary)) : null,
    t.verdict_needed ? h('p', {className:'meta', 'data-key':'ticket-verdict-needed'}, 'Marked done without your OK. Check the work, then click Looks good.') : null,
    file ? ticketResultFrame(t, 'artifacts', file) : h('p', {className:'meta'}, 'No result file is attached. The tasks and the activity show what was done.'),
    h('p', {className:'review-check'}, t.done_when ? 'Does this match “' + clean(t.done_when) + '”?' : 'Does this look right?'),
    ticketProofLine(t), snapshot ? null : ticketChangesEditor(t));
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
function ticketCompletionNote(n) {
  return h('article', {className:'completion-note', 'data-key':'completion-note'}, h('p', {className:'meta eyebrow'}, 'Completion note' + (n.at ? ' · ' + time(n.at) : '')),
    h('h2', {}, n.head), n.body ? h('p', {className:'muted preserve-lines'}, n.body) : null);
}
function ticketResultsCard(t) {
  const files = artifactFiles(t), notes = completionNotes(t);
  if (!files.length && !notes.length) return null;
  const count = [notes.length ? notes.length + (notes.length === 1 ? ' note' : ' notes') : '', files.length ? files.length + (files.length === 1 ? ' file' : ' files') : ''].filter(Boolean).join(' · ');
  return h('section', {className:'card results', 'data-key':'results'}, h('div', {className:'section-head'}, h('h2', {}, 'Results'), h('span', {className:'meta'}, count)),
    notes.map(ticketCompletionNote),
    files.length ? (t.status === 'done' ? ticketResultFrame(t, 'artifacts', files[0]) : ticketFileRow(t, 'artifacts', files[0])) : null, files.slice(1, 4).map(f => ticketFileRow(t, 'artifacts', f)), files.length ? headerProof(t) : null);
}
// A change you asked for: what you asked, and that new changes wait for your approval.
function ticketRequestCard(t) {
  const open = openChanges(t);
  if (!open.length || t.status === 'done') return null;
  return h('section', {className:'card change-request', 'data-key':'your-request'}, h('h2', {}, 'Your request'),
    open.map(c => h('div', {className:'request-row'}, h('p', {className:'preserve-lines'}, 'You asked: “' + clean(changeTask(c.text, c.origin).asked) + '”'), h('p', {className:'meta'}, c.state === 'doing' ? 'Your helper is on it' : 'To do yet'))),
    h('p', {className:'meta request-note'}, 'New changes wait for your approval before they count as done.'));
}
function ticketEmptyCard(t) {
  return h('section', {className:'card empty empty-ticket', 'data-key':'ticket-empty'}, h('span', {className:'empty-mark', 'aria-hidden':'true'}, '＋'),
    h('h2', {}, 'Nothing has happened yet'), h('p', {className:'muted'}, 'Start the helper. It will plan the work, ask you if unsure, and leave the result here.'),
    snapshot ? null : ticketButton('Start helper', 'primary sm', () => act('run.start', {ticket:t.id}), {'data-key':'ticket-start'}));
}
const TAB_ALIAS = {questions:'overview', history:'activity', artifacts:'files'};
function ticketSelectedTab(t) {
  const raw = ticketTabs.get(t.id), tab = TAB_ALIAS[raw] || raw;
  return ['overview', 'tasks', 'files', 'activity'].includes(tab) ? tab : 'overview';
}
const ticketTabList = t => [['overview', 'Overview', null], ['tasks', 'Tasks', array(t.checklist).length], ['files', 'Files', ticketFileCount(t)], ['activity', 'Activity', ticketHistoryEntries(t).length]];
function ticketProperties(t, parent, agent) {
  const field = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));
  return h('aside', {className:'side-panel properties', 'aria-labelledby':'ticket-properties-' + t.id, 'data-key':'properties-' + t.id},
    h('h2', {id:'ticket-properties-' + t.id}, 'Properties'),
    h('dl', {className:'ticket-details ed-list'}, parent ? field('Step of', h('a', {href:href(parent.id)}, partName(parent))) : null,
      field('Owner', inlineField(t, 'owner')), field('Due', inlineField(t, 'due')), field('Done when', inlineField(t, 'done_when')), t.updated_at ? field('Updated', localStamp(t.updated_at)) : null),
    h('section', {className:'property-details'}, h('p', {className:'meta'}, 'Reference'), h('p', {className:'meta'}, 'Created ' + localStamp(t.created_at))),
    linksCard(t),
    t.status === 'review' ? h('section', {className:'next-up', 'data-key':'next-up'}, h('h2', {}, 'What happens next'),
      h('p', {className:'muted'}, 'Looks good moves this ticket to Done. Ask for changes sends it back to the helper, who updates the page and asks you again.')) : null,
    h('p', {className:'meta ticket-meta-line'}, [typeof t.key === 'string' && t.key ? 'Ticket ' + t.key : '', agent ? 'Helper: ' + agent : ''].filter(Boolean).join(' · ')));
}

function detail(t) {
  if (!t) return ticketNotFound();
  const openQuestions = questions(t), selected = ticketSelectedTab(t);
  const run = state.runs?.[t.id], sessions = array(t.sessions);
  const agent = window.DashHelpers.agentLabel(state.settings, run?.claim);
  const parent = window.DashHelpers.parentOf(tickets(), t), children = window.DashHelpers.childrenOf(tickets(), t);
  loadArtifacts(t, selected === 'files');
  const fresh = !sessions.length && !run?.running && ['open', 'ready'].includes(t.status);
  const planQ = t.status !== 'done' && t.plan_first && openQuestions[0] && String(openQuestions[0].text || '').startsWith('Plan ready') ? openQuestions[0] : null;
  const working = !fresh && !planQ && !['done', 'review'].includes(t.status);
  const filled = f => t[f] != null && String(t[f]).trim() !== '';
  const answered = array(t.questions).filter(q => q.answer != null).slice().reverse().map(q => h('div', {className:'card-row', 'data-key':'answered-' + q.id},
    h('div', {className:'grow'}, h('h3', {}, clean(q.text), ticketPhone(q)), h('p', {className:'preserve-lines'}, clean(q.answer)), h('p', {className:'meta'}, ['Answered', name(q.answered_by), surface(q.via)].filter(Boolean).join(' · ')))));
  const note = snapshot ? (filled('note') ? h('p', {className:'muted preserve-lines', 'data-key':'note'}, clean(t.note)) : null) : h('div', {className:'ticket-note', 'data-key':'ticket-note'}, inlineField(t, 'note'));
  const menu = snapshot || (t.status === 'done' && !repeatsAddon()) ? null : h('details', {className:'menu', 'data-key':'ticket-menu-' + t.id}, h('summary', {className:'btn ghost icon sm', 'aria-label':'More ticket actions'}, iconEl('more')),
    h('div', {className:'menu-pop', role:'menu'}, t.status === 'done' ? null : MOVE_CHOICES.map(([status, label]) => ticketButton(label, 'menu-item', () => moveTicket(t.id, status), {role:'menuitem', 'data-key':'ticket-move-' + status})),
      repeatsAddon() ? [ticketButton('Repeat…', 'menu-item', () => repeatsDialog(t.id, repeatsAddon()), {role:'menuitem', 'data-key':'ticket-repeat'})] : null));
  const live = run?.running ? liveLinkFor(t) : null;
  const [tone, word] = ticketStatusWord(t, run);
  const actions = snapshot ? null : h('div', {className:'plain-actions'},
    t.status === 'done' ? ticketButton('Reopen ticket', 'ghost sm', () => moveTicket(t.id, 'active'), {'data-key':'ticket-reopen'}) : null,
    run?.running ? ticketButton('Stop helper', 'ghost sm', () => act('run.stop', {ticket:t.id}), {'data-key':'ticket-stop'}) : null, menu);
  const stateLine = h('p', {className:'state-line'}, t.owner ? h('span', {}, 'for ' + name(t.owner)) : null,
    h('strong', {className:'status-word status-change ' + tone, 'data-key':'status-' + t.status + '-' + tone}, word),
    h('span', {className:'muted'}, ticketStateSentence(t, run, fresh)),
    !snapshot && !planQ && openQuestions.length && t.status !== 'done' ? ticketButton('Answer', 'primary sm', focusTicketAnswer) : null,
    live ? h('a', {className:'btn primary sm', href:live.url, 'data-key':'watch-live'}, 'Watch live ↗') : null);
  const tabs = ticketTabList(t);
  const panel = (id, label, body) => h('section', {id:'ticket-panel-' + id, role:snapshot ? null : 'tabpanel', 'aria-labelledby':snapshot ? null : 'ticket-tab-' + id, className:'stack ticket-panel', hidden:!snapshot && selected !== id, tabindex:'0'}, snapshot ? h('h2', {}, label) : null, body);
  const total = array(t.checklist).length, done = array(t.checklist).filter(window.DashHelpers.resolved).length;
  const overview = [
    ticketBringBackRow(t),
    t.status !== 'done' && openQuestions.length ? (planQ ? ticketPlan(t, planQ, children) : ticketQuestion(t, openQuestions[0], true)) : null,
    t.status !== 'done' ? openQuestions.slice(1).map(q => ticketQuestion(t, q)) : null,
    t.status === 'review' ? ticketReviewCard(t) : null,
    ticketRequestCard(t),
    fresh ? ticketEmptyCard(t) : null,
    !fresh && !openQuestions.length && ticketPaused(t, run) ? h('section', {className:'card paused', 'data-key':'ticket-paused'}, h('p', {className:'meta'}, 'Paused' + (t.updated_at ? ' ' + localStamp(t.updated_at, false) : '')), snapshot ? null : ticketButton('Resume', 'primary sm', () => act('run.start', {ticket:t.id}))) : null,
    working ? agentBar(t) : null, working ? sharedFolderLine(t) : null, copyLine(t), working ? liveSessionStrip(t) : null,
    t.description ? h('section', {className:'card asked', 'data-key':'description'}, h('h2', {}, 'What was asked'), h('p', {className:'preserve-lines'}, clean(t.description)), t.description_by ? h('p', {className:'meta'}, 'Written by ' + ticketActor(t.description_by)) : null) : null,
    t.summary && t.status !== 'review' ? h('p', {className:'muted preserve-lines', 'data-key':'summary'}, 'In short: ' + clean(t.summary)) : null,
    note,
    t.status !== 'review' ? ticketResultsCard(t) : null,
    ticketOutcomeCard(t),
    planQ ? null : ticketProgress(t, run),
    planQ ? null : ticketParts(t, children),
    addonRows(t), ticketLinks(t),
    answered.length ? h('section', {className:'card answered', 'data-key':'answered'}, h('h2', {}, 'Earlier answers'), answered) : null];
  return fragment(h('div', {className:'ticket-page', 'data-key':'ticket-page-' + t.id},
    h('header', {className:'ticket-heading'},
      parent ? h('a', {href:href(parent.id), className:'muted'}, 'Step of ' + partName(parent)) : null,
      actions,
      h('h1', {}, inlineField(t, 'title')), stateLine, ticketStepper(t, run)),
    snapshot ? null : h('div', {className:'tabs ticket-tabs', role:'tablist', 'aria-label':'Ticket'}, tabs.map(([id, label, count]) =>
      ticketButton([label, count != null ? ' ' : null, count != null ? h('span', {className:'tab-count'}, String(count)) : null], 'ghost', null,
        {id:'ticket-tab-' + id, role:'tab', 'aria-selected':String(selected === id), 'aria-controls':'ticket-panel-' + id, tabindex:selected === id ? '0' : '-1', 'data-action':'ticket-tab', 'data-ticket':t.id, 'data-tab':id, 'data-key':'ticket-tab-' + id}))),
    h('div', {className:'columns ticket-layout' + (selected === 'files' ? ' wide' : '')},
      h('div', {className:'stack story'},
        panel('overview', 'Overview', overview),
        panel('tasks', 'Tasks', card('tasks', 'Tasks', total ? done + ' of ' + total + ' done' : '', [total ? taskRows(t) : emptyRow('No tasks yet.'), t.status === 'done' ? null : addTaskRow(t, 'tasks')])),
        panel('files', 'Files', artifactsPanel(t)),
        panel('activity', 'Activity', ticketHistoryPanel(t))),
      h('div', {className:'stack ticket-side'}, ticketProperties(t, parent, agent), fieldSections(t)))));
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
    mountQuestion(host, {ticket:row.ticket, id:row.answer.question, digest:row.answer.digest, title:row.title, text:row.text, options:array(row.answer.options).map(o => ({text:o, suggested:o === row.answer.recommended}))}, {dialog:d, row:trigger.closest('[data-need-row]'), lock:'needs-you'});
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
