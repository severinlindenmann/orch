'use strict';

(() => {
  const view = document.querySelector('#view');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]);
  let token = '';
  try { token = sessionStorage.getItem('orch_admin') || ''; } catch (_) { /* Login remains usable without storage. */ }
  let readyData = null;
  let workspaces = [];
  let generation = 0;
  const unauthorized = new Error('Sign in to continue.');
  const path = (kind, id) => `/admin/api/${kind}/${encodeURIComponent(id)}`;
  let verified = false, afterRender = null, skTimer, lastUpdated = 0, copied = false, flash = {};
  let enteredRoute = location.hash.slice(1) || 'workspaces';
  function notify(message, undo, kind = 'ok') {
    orch.toast(message, kind, undo ? { label: 'Undo', run: undo } : undefined);
  }

  // Confirm dialog whose button names the action (instead of window.confirm "OK").
  function confirmDialog(title, message, verb) {
    return new Promise(resolve => {
      const d = document.createElement('dialog');
      d.className = 'dialog';
      d.setAttribute('aria-labelledby', 'cd-title');
      d.innerHTML = `<h2 id="cd-title">${esc(title)}</h2><p>${esc(message)}</p><div class="actions"><button class="quiet" value="no" autofocus>Cancel</button><button class="danger" value="yes">${esc(verb)}</button></div>`;
      const opener = document.activeElement;
      d.addEventListener('click', e => { const v = e.target.closest('button')?.value; if (v) { d.returnValue = v; void orch.close(d); } });
      d.addEventListener('close', () => { const ok = d.returnValue === 'yes'; d.remove(); opener?.focus?.(); resolve(ok); });
      document.body.append(d);
      decorate(d);
      orch.open(d);
    });
  }

  const withRetry = m => (/try again/i.test(String(m)) ? String(m).trim() : `${String(m).trim()} Try again.`);
  function ago(ms) {
    const s = Math.round((Date.now() - ms) / 1000);
    return s < 20 ? 'just now' : s < 90 ? 'a minute ago' : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
  }
  function tickUpdated() {
    const el = document.querySelector('#updated');
    if (el) el.textContent = lastUpdated ? `Updated ${ago(lastUpdated)}` : '';
  }
  setInterval(tickUpdated, 20000);

  async function api(url, method = 'GET', body) {
    let response;
    try {
      response = await fetch(url, {
        method, credentials: 'same-origin', cache: 'no-store',
        headers: { 'X-Orch-Admin': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
      });
    } catch (_) { throw new Error('Could not connect. Check your connection and try again.'); }
    if (response.status === 401) {
      const expired = verified;
      const hadToken = Boolean(token);
      const failed = token;
      verified = false;
      token = '';
      readyData = null;
      try { sessionStorage.removeItem('orch_admin'); } catch (_) { /* Storage may be blocked. */ }
      document.cookie = 'orch_admin=; path=/; SameSite=Strict; Max-Age=0';
      generation++;
      if (expired) login('Your session ended. Sign in again.');
      else login(hadToken ? 'That access key didn’t work. Check it for typing mistakes and try again.' : '', failed);
      throw unauthorized;
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (response.status >= 500) throw Object.assign(new Error('Something went wrong on our side. Try again in a moment.'), { status: response.status });
    if (!response.ok) throw Object.assign(new Error(data?.message || 'Something went wrong. Try again.'), { status: response.status });
    return data;
  }

  function head(title, subtitle, action = '') {
    return `<div class="page-heading"><h1 tabindex="-1">${esc(title)}</h1>${subtitle ? `<p class="muted">${esc(subtitle)}</p>` : ''}${action}</div>`;
  }

  function showAlert(message) {
    const el = document.querySelector('#alert');
    el.textContent = message || '';
    el.hidden = !message;
  }

  // Disable the whole form/action group to prevent overlapping destructive requests.
  async function run(container, action, onError = showAlert) {
    const controls = [...container.querySelectorAll('button, input, textarea, select')];
    const disabled = controls.map(el => el.disabled);
    controls.forEach(el => { el.disabled = true; });
    showAlert('');
    const busy = container.contains(document.activeElement) && document.activeElement.tagName === 'BUTTON' ? document.activeElement : container.querySelector('button[type=submit]');
    busy?.setAttribute('aria-busy', 'true');
    let failed = false;
    try { await action(); } catch (error) {
      if (error !== unauthorized) { failed = true; onError(error.message); }
    } finally {
      busy?.removeAttribute('aria-busy'); controls.forEach((el, i) => { el.disabled = disabled[i]; });
      if (failed && busy?.isConnected) busy.focus();
    }
  }

  function setSignedIn(on) {
    document.body.classList.toggle('signed-out', !on);
  }

  function login(message = '', keep = '') {
    view.removeAttribute('aria-busy');
    setSignedIn(false);
    showAlert('');
    document.querySelector('#crumb').textContent = 'Sign in';
    view.innerHTML = `<form id="login-form" class="card pad login" novalidate><header class="page-heading"><h1>Sign in</h1><p class="muted">Enter your admin access key to manage workspaces, files and apps.</p></header><div class="field"><label for="admin-token">Admin access key</label><div class="password"><input id="admin-token" name="token" type="password" autocomplete="current-password" aria-describedby="login-error" ${message ? 'class="invalid" aria-invalid="true"' : ''}><button type="button" class="small quiet" id="pw-toggle" aria-pressed="false">Show</button></div><p class="field-error" id="login-error" role="alert" ${message ? '' : 'hidden'}>${esc(message)}</p></div><button class="primary" type="submit">Sign in</button></form>`;
    decorate(view);
    const input = document.querySelector('#admin-token');
    input.value = keep;
    input.focus();
    input.select();
    document.querySelector('#pw-toggle').addEventListener('click', e => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      e.currentTarget.textContent = show ? 'Hide' : 'Show';
      e.currentTarget.setAttribute('aria-pressed', String(show));
    });
    input.addEventListener('input', () => { input.classList.remove('invalid'); input.removeAttribute('aria-invalid'); document.querySelector('#login-error').hidden = true; });
    document.querySelector('#login-form').addEventListener('submit', event => {
      event.preventDefault();
      const candidate = new FormData(event.currentTarget).get('token').trim();
      if (!candidate) {
        input.classList.add('invalid'); input.setAttribute('aria-invalid', 'true');
        const err = document.querySelector('#login-error');
        err.textContent = 'Enter your admin access key.'; err.hidden = false;
        input.focus();
        return;
      }
      token = candidate;
      try { sessionStorage.setItem('orch_admin', token); } catch (_) { /* Works until reload. */ }
      void render();
    });
  }

  function fields(workspace = {}, isNew = false) {
    const rights = workspace.rights || { permanent: false, files: true, apps: true, public: false };
    return `<div class="field"><label for="name">Workspace name</label><input id="name" name="name" value="${esc(workspace.name)}" maxlength="60" autocomplete="off" aria-describedby="name-error"><p class="field-error" id="name-error" role="alert" hidden></p></div>
      <div class="field"><label for="description">Description <span class="muted">(optional)</span></label><textarea id="description" name="description" maxlength="280" aria-describedby="description-error">${esc(workspace.description)}</textarea><p class="field-error" id="description-error" role="alert" hidden></p></div>
      <div class="field"><label for="tag-entry">Tags</label><input id="tags" name="tags" value="${esc((workspace.tags || []).join(', '))}" aria-describedby="tags-error"><p class="field-error" id="tags-error" role="alert" hidden></p></div>
      <fieldset><legend>What it can publish</legend>${[['permanent','Permanent files','kept until you remove them'],['files','Temporary files','removed after 7 days by default'],['apps','Apps','small web pages and tools']].map(([key,label,help]) => `<label class="check"><input name="${key}" type="checkbox" ${rights[key] ? 'checked' : ''}><span>${label}<small class="muted"> · ${help}</small></span></label>`).join('')}</fieldset>
      <div class="field"><label for="sharing">Sharing</label><select id="sharing" name="public"><option value="false" ${!rights.public ? 'selected' : ''}>Private only</option><option value="true" ${rights.public ? 'selected' : ''}>Public links allowed</option></select><small class="muted">Private apps open only with their access link. Public apps can be opened by anyone.</small></div><p class="field-error form-error" role="alert" hidden></p>`;
  }

  function bindTags(form) {
    const hidden = form.elements.tags;
    const box = document.createElement('div'); box.className = 'tag-input'; hidden.before(box);
    hidden.type = 'hidden'; hidden.id = 'tags-value'; box.append(hidden);
    const input = document.createElement('input'); input.id = 'tag-entry'; input.className = 'input'; input.setAttribute('aria-describedby', 'tags-error'); input.setAttribute('aria-label', 'Add tag'); box.append(input);
    let tags = [...new Set(hidden.value.split(',').map(t => t.trim().toLowerCase()).filter(Boolean))];
    function draw() {
      box.querySelectorAll('.tag-pill').forEach(p => p.remove()); hidden.value = tags.join(',');
      tags.forEach(tag => {
        const pill = document.createElement('span'); pill.className = 'chip tag-pill'; pill.append(document.createTextNode(tag));
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove tag ' + tag);
        remove.onclick = () => { tags = tags.filter(t => t !== tag); draw(); fieldError(form, 'tags', ''); input.focus(); };
        pill.append(remove); box.insertBefore(pill, input);
      });
    }
    function add() {
      const next = [...new Set([...tags, ...input.value.split(',').map(t => t.trim().toLowerCase()).filter(Boolean)])];
      const error = checks.tags(next.join(',')); fieldError(form, 'tags', error);
      if (error) return false;
      tags = next; input.value = ''; draw(); return true;
    }
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); }
      else if (e.key === 'Backspace' && !input.value) { tags.pop(); draw(); }
    });
    input.addEventListener('input', () => { fieldError(form, 'tags', ''); if (input.value.includes(',')) add(); });
    input.addEventListener('blur', e => { if (e.relatedTarget?.type !== 'submit') add(); });
    form.commitTags = add; draw();
  }

  function readFields(form) {
    const data = new FormData(form);
    return { name: data.get('name').trim(), description: data.get('description').trim(),
      tags: data.get('tags').split(',').map(tag => tag.trim()).filter(Boolean),
      rights: { permanent: data.has('permanent'), files: data.has('files'), apps: data.has('apps'), public: data.get('public') === 'true' } };
  }

  function fieldError(form, name, message) {
    const input = name === 'tags' ? form.querySelector('#tag-entry') : form.elements[name];
    const err = form.querySelector(`#${name}-error`);
    input.classList.toggle('invalid', Boolean(message));
    if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    err.textContent = message || ''; err.hidden = !message;
  }

  const checks = {
    name: v => (v.trim() ? '' : 'Enter a name for this workspace.'),
    description: v => (v.length > 280 ? 'Use at most 280 characters.' : /[\r\n]/.test(v) ? 'Keep it on one line.' : ''),
    tags: v => {
      const list = v.split(',').map(t => t.trim()).filter(Boolean);
      if (list.length > 8) return 'Use at most 8 tags.';
      return list.every(t => /^[a-z0-9-]{1,24}$/.test(t)) ? '' : 'Tags use lowercase letters, numbers and hyphens, up to 24 characters each.';
    }
  };
  function validate(form, name) {
    const message = checks[name](form.elements[name].value);
    fieldError(form, name, message);
    return !message;
  }

  function bindSave(form, save) {
    bindTags(form);
    const formError = form.querySelector('.form-error');
    Object.keys(checks).forEach(name => {
      form.elements[name].addEventListener('input', () => fieldError(form, name, ''));
      form.elements[name].addEventListener('blur', e => { if (e.relatedTarget?.type === 'submit') return; validate(form, name); });
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!form.commitTags()) { form.querySelector('#tag-entry').focus(); return; }
      const body = readFields(form);
      formError.hidden = true;
      const bad = Object.keys(checks).filter(name => !validate(form, name));
      if (bad.length) {
        const first = bad[0] === 'tags' ? form.querySelector('#tag-entry') : form.elements[bad[0]];
        const more = first.closest('details.more'); if (more) more.open = true;
        first.focus(); return;
      }
      void run(form, () => save(body), message => { formError.textContent = message; formError.hidden = false; });
    });
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  // The change a workspace proposed for itself: current vs proposed, Approve / Keep current (bound to this exact proposal).
  function reviewCard(w, i) {
    const p = w.pending, list = t => (t && t.length ? t.join(', ') : 'none');
    const line = (label, now, next) => `<span class="diff-label">${label}</span><span class="muted">${esc(now)}</span><span class="proposed">${esc(next)}</span>`;
    const special = /[^\x00-\x7f]/.test(p.description || '') ? '<p class="muted">Contains special characters.</p>' : '';
    return `<section class="review review-body" data-review="${i}" role="group" aria-label="Change waiting for your approval for ${esc(w.name)}"><h3 tabindex="-1">${esc(w.name)} wants to change how it is described</h3><div class="review-diff"><span class="diff-corner"></span><span class="diff-head">Now</span><span class="diff-head">Proposed</span>${p.description !== null && p.description !== undefined && p.description !== (w.description || '') ? line('Description', w.description || 'none', p.description) : ''}${p.tags && list(p.tags) !== list(w.tags) ? line('Tags', list(w.tags), list(p.tags)) : ''}</div>${special}<p class="meta">The old text stays in use until you approve.</p><div class="actions"><button class="primary small" data-act="approve">Approve</button><button class="small" data-act="reject">Keep current</button></div><p class="review-result" role="alert">${esc(flash[w.id] || '')}</p></section>`;
  }

  function bindReview(box, w) {
    const result = box.querySelector('.review-result');
    box.querySelectorAll('[data-act]').forEach(button => button.addEventListener('click', async () => {
      if (box.dataset.busy) return;
      box.dataset.busy = '1';
      const label = button.textContent;
      button.textContent = button.dataset.act === 'approve' ? 'Approving…' : 'Keeping…';
      button.setAttribute('aria-busy', 'true');
      box.querySelectorAll('button').forEach(b => { b.disabled = true; });
      result.classList.remove('field-error');
      try {
        await api(`${path('workspaces', w.id)}/profile/${button.dataset.act}`, 'POST', { rev: w.pending.rev });
        flash[w.id] = button.dataset.act === 'approve' ? 'Approved by you. The new text is now in use.' : 'Kept the current text.';
        await render();
        return;
      } catch (error) {
        if (error === unauthorized) return;
        if (error.status === 409) {
          flash[w.id] = `${w.name} sent a newer version while you were looking. Check the text, then approve or reject.`;
          await render();
          return;
        }
        result.textContent = withRetry(error.message);
        result.classList.add('field-error');
        button.textContent = label;
        button.removeAttribute('aria-busy');
        box.querySelectorAll('button').forEach(b => { b.disabled = false; });
        button.focus();
      } finally { delete box.dataset.busy; }
    }));
  }

  // A proposal equal to the live text is not a change: hide it.

  const proposalChanges = w => w.pending && ((w.pending.description != null && w.pending.description !== (w.description || '')) || (w.pending.tags && w.pending.tags.join(',') !== (w.tags || []).join(',')));
  function showWorkspaces(items) {
    items = items.map(w => (w.pending && !proposalChanges(w) ? { ...w, pending: null } : w));
    const files = items.reduce((n, w) => n + (Number(w.files) || 0), 0);
    const apps = items.reduce((n, w) => n + (Number(w.apps) || 0), 0);
    const pending = items.filter(w => w.pending);
    view.innerHTML = head('Your workspaces', items.length ? `${plural(items.length, 'workspace', 'workspaces')} · ${plural(files, 'encrypted file', 'encrypted files')} · ${plural(apps, 'app', 'apps')}` : '') +
      (pending.length ? `<section class="card"><div class="card-h"><h2>Waiting for your approval<span class="muted"> · ${pending.length}</span></h2></div>${items.map((w,i) => w.pending ? reviewCard(w,i) : '').join('')}</section>` : '') +
      (items.length ? `<section class="card"><div class="card-h"><h2>Workspaces<span class="muted"> · ${items.length}</span></h2></div>${items.map((w,i) => {
        const r = w.rights || {};
        const labels = [w.description || 'No description yet.', plural(Number(w.files)||0,'file','files'), plural(Number(w.apps)||0,'app','apps'), r.permanent && 'Permanent files', r.files && 'Temporary files', r.apps && 'Apps', r.public ? 'Public links allowed' : 'Private only'].filter(Boolean);
        return `<div class="workspace-entry"><div class="card-row" data-row>${icon('workspace')}<div class="grow"><h3>${esc(w.name)} ${w.pending ? '<span class="chip outline">Waiting for your approval</span>' : ''}</h3><p class="meta">${esc(labels.join(' · '))}</p><div class="row">${(w.tags || []).map(t => `<span class="chip outline">${esc(t)}</span>`).join('')}</div>${!w.pending && flash[w.id] ? `<p class="review-done" role="status" tabindex="-1">${esc(flash[w.id])}</p>` : ''}</div><button class="small" data-edit="${i}" data-edit-id="${esc(w.id)}" aria-expanded="false" aria-label="Edit ${esc(w.name)}">Edit</button></div></div>`;
      }).join('')}</section>` : '<section class="card empty"><h2>No workspaces yet</h2><div class="actions space-top"><a class="button primary" href="#add">Add your first workspace</a></div></section>');
    view.querySelectorAll('[data-review]').forEach(box => bindReview(box, items[Number(box.dataset.review)]));
    view.querySelectorAll('[data-edit]').forEach(button => button.addEventListener('click', () => edit(items[Number(button.dataset.edit)])));
    const done = view.querySelector('.review-done');
    const flashed = view.querySelector('.review-result:not(:empty)');
    if (done) { done.scrollIntoView({ block: 'center' }); done.focus(); }
    else if (flashed) { const h = flashed.closest('.review').querySelector('h3'); h.scrollIntoView({ block: 'center' }); h.focus(); }
    flash = {};
  }

  function closeEditor(id) {
    document.querySelector('#editor')?.remove();
    document.querySelectorAll('[data-edit]').forEach(b => b.setAttribute('aria-expanded', 'false'));
    const back = id ? [...document.querySelectorAll('[data-edit-id]')].find(b => b.dataset.editId === id) : null;
    back?.focus();
  }
  let editingId = '';
  function edit(workspace) {
    closeEditor(editingId);
    const button = [...view.querySelectorAll('[data-edit-id]')].find(b => b.dataset.editId === workspace.id);
    const editor = document.createElement('div'); editor.id = 'editor'; editor.className = 'editor';
    button.closest('.workspace-entry').append(editor); button.setAttribute('aria-expanded', 'true');
    editingId = workspace.id;
    editor.innerHTML = `<form class="form workspace-edit" novalidate><div class="field-spaced">${fields(workspace)}</div><div class="actions"><button class="primary" type="submit">Save changes</button><button class="quiet" type="button" data-cancel>Cancel</button></div><section class="danger-zone"><h3>Danger zone</h3><div class="actions"><button class="small" type="button" data-new-token>Make a new access key</button><button class="danger small" type="button" data-delete>Delete workspace</button></div></section></form>`;
    const form = editor.querySelector('form');
    form.elements.name.focus();
    form.scrollIntoView({ block: 'nearest' });
    form.querySelector('[data-cancel]').addEventListener('click', () => closeEditor(workspace.id));
    decorate(form);
    if (window.OrchLookAdmin) form.querySelector('.field-spaced').append(window.OrchLookAdmin.row(workspace, b => api(path('workspaces', workspace.id), 'PATCH', b))); // look hook
    bindSave(form, async body => {
      await api(path('workspaces', workspace.id), 'PATCH', body);
      afterRender = () => document.querySelector(`[data-edit-id="${CSS.escape(workspace.id)}"]`)?.focus();
      await render(); notify('Workspace saved.');
    });
    form.querySelector('[data-new-token]').addEventListener('click', async () => {
      if (!await confirmDialog('Make a new access key?', 'The current key stops working and you must reconnect this workspace.', 'Make new key')) return;
      void run(form, async () => {
        const result = await api(`${path('workspaces', workspace.id)}/token`, 'POST');
        readyData = { ...result, id: workspace.id, name: workspace.name, renewed: true };
        location.hash = 'ready';
      });
    });
    form.querySelector('[data-delete]').addEventListener('click', async () => {
      if (!await confirmDialog(`Delete “${workspace.name}”?`, 'Its files and apps are removed. This cannot be undone.', 'Delete workspace')) return;
      void run(form, async () => { await api(path('workspaces', workspace.id), 'DELETE'); editingId = ''; await render(); notify('Workspace deleted.'); });
    });
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(String(text)); notify('Copied. Paste it to your agent.'); return true; }
    catch (_) {
      const field = document.createElement('textarea');
      const focused = document.activeElement;
      field.className = 'copy-fallback'; field.value = String(text); document.body.append(field); field.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) { /* Offer manual copy below. */ }
      field.remove(); focused?.focus();
      notify(ok ? 'Copied. Paste it to your agent.' : 'Select the text and copy it manually.');
      return ok;
    }
  }

  function showReady() {
    if (!readyData) {
      view.innerHTML = head('This setup link was already used', '') + '<p><a href="#workspaces">Back to workspaces</a></p>';
      return;
    }
    const name = readyData.name || 'Your workspace';
    view.innerHTML = head(readyData.renewed ? 'New access key ready' : 'Your workspace is ready', '') +
      `<p>Paste this into your agent in the project that should use “${esc(name)}”.</p><div class="copy-wrap"><pre class="copy-box">${esc(readyData.prompt)}</pre><button class="primary small" data-copy="prompt">Copy</button></div><p class="section-note">This is shown only once. Copy it before you leave this page.</p><p class="fact">Workspace ID <code>${esc(readyData.id)}</code> <button class="small quiet icon" data-copy="id" aria-label="Copy workspace ID">${icon('copy')}</button></p><div class="actions"><a class="button quiet" href="#workspaces">Done</a></div>`;
    copied = false;
    view.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
      const data = readyData;
      const ok = await copy(data[button.dataset.copy]);
      if (ok && readyData === data && button.dataset.copy === 'prompt') copied = true;
    }));
  }

  function expiry(value) {
    if (value == null) return 'Permanent';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const days = Math.ceil((date.getTime() - Date.now()) / 86400000);
    return days <= 0 ? 'Expired' : `${days} ${days === 1 ? 'day' : 'days'} left`;
  }
  const STACK = { static: 'Web page', python: 'Python app', node: 'Node app' };
  const STORE = { json: 'Saves data', markdown: 'Saves notes', sqlite: 'Saves data' };
  function shared(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return '';
    return 'Shared ' + date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
  function size(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return '';
    if (value < 1024) return `${value} ${value === 1 ? 'byte' : 'bytes'}`;
    return value < 1048576 ? `${(value / 1024).toFixed(1).replace(/\.0$/, '')} KB` : `${(value / 1048576).toFixed(1).replace(/\.0$/, '')} MB`;
  }
  function workspaceName(id) { return workspaces.find(w => w.id === id)?.name || 'Unknown workspace'; }
  function safeUrl(value) {
    if (!value) return '';
    try {
      const url = new URL(value, location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (_) { return ''; }
  }

  // Files are loaded page by page; the portal says how many of the total are shown.
  const expMs = f => (f.expires_at == null ? Infinity : new Date(f.expires_at).getTime() || Infinity);
  function showFiles(items, next, total) {
    const groups = new Map();
    items.forEach(f => { if (!groups.has(f.workspace)) groups.set(f.workspace, []); groups.get(f.workspace).push(f); });
    const list = [...groups].map(([id, rows]) => ({ id, rows: rows.slice().sort((a, b) => expMs(a) - expMs(b)) }));
    list.sort((a, b) => expMs(a.rows[0]) - expMs(b.rows[0]));
    const all = !next;
    const row = f => `<article class="item card-row" data-row>${icon('lock')}<div class="grow"><h3>${esc(size(f.size))} · ${esc(expiry(f.expires_at))}</h3><p class="meta">${esc(shared(f.created_at))}</p></div>${menu(`Manage this file from ${workspaceName(f.workspace)}`, `<button class="danger" data-delete="${esc(f.id)}">Delete…</button>`)}</article>`;
    view.innerHTML = head('Encrypted files', '') + (items.length ? `<p class="meta">${all ? plural(items.length, 'file', 'files') : `Showing ${items.length} of ${total}`} · soonest to expire first</p>` : '') +
      (items.length ? `<section class="card">${list.map(g => {
        const count = all ? g.rows.length : Math.max(g.rows.length, Number(workspaces.find(w => w.id === g.id)?.files) || 0);
        const bytes = g.rows.reduce((n, f) => n + (Number(f.size) || 0), 0);
        return `<section class="flat-section"><div class="card-h"><h2>${esc(workspaceName(g.id))} <span class="meta">${esc(plural(count, 'file', 'files'))}${all ? ` · ${esc(size(bytes))}` : ''} · ${esc(expiry(g.rows[0].expires_at))}</span></h2></div><div class="fold-body">${g.rows.map(row).join('')}</div></section>`;
      }).join('')}</section>${all ? '' : `<p class="load-more"><button class="small" id="more-files">Load more</button></p>`}` : '<section class="card empty"><h2>No files yet</h2></section>') + '<p class="section-note">File names and contents are encrypted. Not even the admin can read them.</p>';
    decorate(view);
    view.querySelector('#more-files')?.addEventListener('click', e => run(e.currentTarget.parentElement, async () => {
      const current = generation;
      const page = await api(`/admin/api/files?limit=100&after=${encodeURIComponent(next)}`);
      if (current !== generation) return;
      showFiles(items.concat(page.items || []), page.next, total);
      view.querySelector('#more-files')?.focus();
    }));
    view.querySelectorAll('[data-delete]').forEach(button => button.addEventListener('click', async () => {
      const file = items.find(f => f.id === button.dataset.delete);
      if (!await confirmDialog('Delete this file?', 'Its sharing link will stop working. This cannot be undone.', 'Delete file')) return;
      void run(button.closest('.item'), async () => {
        const current = generation;
        await api(path('files', file.id), 'DELETE');
        if (current !== generation) return;
        const left = items.filter(f => f !== file);
        const c = document.querySelector('#count-files'); if (c) c.textContent = Math.max(0, Number(c.textContent) - 1);
        showFiles(left, next, Math.max(0, total - 1));
        notify('File deleted.');
      });
    }));
  }

  const STATUS = { running: ['green', 'Running'], stopped: ['muted', 'Stopped'], failed: ['danger', 'Not responding'] };

  function showApps(items, next) {
    const rank = a => (a.status === 'failed' ? 0 : a.status === 'running' ? 1 : 2);
    const order = items.map((app, i) => i).sort((x, y) => rank(items[x]) - rank(items[y]));
    const stopped = order.filter(i => items[i].status !== 'running' && items[i].status !== 'failed');
    const active = order.filter(i => !stopped.includes(i));
    const n = st => items.filter(a => a.status === st).length;
    const soon = items.filter(a => a.expires_at != null && new Date(a.expires_at).getTime() - Date.now() < 3 * 86400000).length;
    const summary = [`${n('running')} running`, `${stopped.length} stopped`, n('failed') ? `${n('failed')} not responding` : '', soon ? `${soon} expire within 3 days` : ''].filter(Boolean).join(' · ');
    const card = i => { const app = items[i];
        const [, label] = STATUS[app.status] || ['muted', app.status];
        const url = safeUrl(app.url);
        const main = app.status === 'running'
          ? (url ? `<a class="button small" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open ↗</a>` : '')
          : `<button class="small" data-app="${i}" data-action="restart">Start</button>`;
        return `<article class="app-card card-row" data-row>${icon('app')}<div class="grow"><h3>${esc(app.name)}</h3><p class="meta">${esc([workspaceName(app.workspace), app.public ? 'Public' : 'Private', STACK[app.stack], STORE[app.store], expiry(app.expires_at)].filter(Boolean).join(' · '))}</p></div><span class="status ${app.status === 'running' ? 'running' : app.status === 'failed' ? 'failed' : ''}"><span class="dot" aria-hidden="true"></span>${esc(label)}</span>${main}${menu(`Manage ${app.name}`, `${app.status === 'stopped' ? '' : `<button data-app="${i}" data-action="restart">Restart</button>`}${app.status === 'running' ? `<button data-app="${i}" data-action="stop">Stop</button>` : ''}<button class="danger" data-app="${i}" data-action="delete">Delete…</button>`)}</article>`;
    };
    view.innerHTML = head('Apps', items.length ? summary : '') +
      (items.length ? `<section class="card">${active.map(card).join('')}${stopped.length ? `<div class="card-h">Stopped · ${stopped.length}</div>${stopped.map(card).join('')}` : ''}</section>${next ? '<p class="load-more"><button id="more-apps">Load more</button></p>' : ''}` : '<section class="card empty"><h2>No apps yet</h2></section>');
    decorate(view);
    view.querySelector('#more-apps')?.addEventListener('click', e => run(e.currentTarget.parentElement, async () => {
      const current = generation;
      const page = await api(`/admin/api/apps?limit=100&after=${encodeURIComponent(next)}`);
      if (current !== generation) return;
      showApps(items.concat(page.items || []), page.next);
      view.querySelector('#more-apps')?.focus();
    }));
    view.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', async () => {
      const app = items[Number(button.dataset.app)];
      const action = button.dataset.action;
      if (action === 'delete' && !await confirmDialog(`Delete “${app.name}”?`, 'Its code and data are removed. This cannot be undone.', 'Delete app')) return;
      void run(button.closest('.app-card'), async () => {
        await api(path('apps', app.name) + (action === 'delete' ? '' : `/${action}`), action === 'delete' ? 'DELETE' : 'POST');
        await render();
        if (action === 'stop') notify(`${app.name} is stopped. Visitors see “This app is paused.”`, async () => { try { await api(path('apps', app.name) + '/restart', 'POST'); await render(); notify(`${app.name} is running again.`); } catch (e) { if (e !== unauthorized) notify(`Could not start ${app.name}. Try Start on its card.`, null, 'error'); } });
        else notify(action === 'delete' ? 'App deleted.' : `${app.name} is running.`);
      });
    }));
  }
  function menu(label, contents) {
    return `<div class="more-menu"><button type="button" class="btn ghost icon sm" data-menu aria-expanded="false" aria-label="${esc(label)}">${icon('more')}</button><div class="menu-items" hidden>${contents}</div></div>`;
  }
  function closeMenus(event) {
    document.querySelectorAll('[data-menu][aria-expanded="true"]').forEach(b => {
      if (!event || !b.parentElement.contains(event.target)) { b.setAttribute('aria-expanded', 'false'); b.nextElementSibling.hidden = true; }
    });
  }
  function decorate(root) {
    root.querySelectorAll('button, a.button').forEach(b => { if (b.closest('.tag-pill')) return; b.classList.add('btn'); if (!b.matches('.primary,.danger,.quiet,.ghost')) b.classList.add('outline'); if (b.classList.contains('small')) b.classList.add('sm'); });
    root.querySelectorAll('input:not([type=checkbox]):not([type=hidden]),textarea,select').forEach(el => el.classList.add('input'));
  }


  function showApi() {
    const address = (document.querySelector('meta[name="publish-url"]')?.content || location.origin).replace(/\/$/, '');
    const base = `${address}/v1`, auth = '  -H "Authorization: Bearer $ORCH_TOKEN" \\\n  -H "X-Orch-Workspace: $ORCH_WORKSPACE"';
    const examples = [
      ['GET', 'List your files', `curl "${base}/files" \\\n${auth}`],
      ['POST', 'Upload an encrypted file', `curl -X POST "${base}/files?days=7" \\\n${auth} \\\n  --data-binary @encrypted.bin`],
      ['GET', 'List your apps', `curl "${base}/apps" \\\n${auth}`],
      ['POST', 'Restart an app', `curl -X POST "${base}/apps/my-app/restart" \\\n${auth}`],
      ['POST', 'Stop an app', `curl -X POST "${base}/apps/my-app/stop" \\\n${auth}`],
      ['PATCH', 'Describe your workspace', `curl -X PATCH "${base}/me" \\\n${auth} \\\n  -H "Content-Type: application/json" \\\n  -d '{"description":"What it is","tags":["a","b"]}'`],
      ['DELETE', 'Delete a file or app', `curl -X DELETE "${base}/files/FILE_ID" \\\n${auth}\n\n# Or delete an app\ncurl -X DELETE "${base}/apps/my-app" \\\n${auth}`]
    ];
    view.innerHTML = head('API reference', '') +
      `<section class="card"><div class="card-h"><h2>Server address</h2></div><div class="form-body"><code>${esc(address)}</code><pre>export ORCH_WORKSPACE='your-workspace-id'
export ORCH_TOKEN='your-access-key'</pre></div></section><section class="card">${examples.map(([method,label,code]) => `<div class="flat-section"><div class="card-h"><span class="chip outline mono">${esc(method)}</span>${esc(label)}</div><div class="fold-body"><pre>${esc(code)}</pre></div></div>`).join('')}</section>`;
  }

  function loadingMarkup(route) {
    const rows = ['add', 'ready', 'api'].includes(route) ? 2 : 4;
    return `<div class="loading-bar" aria-hidden="true"></div><div class="stack" role="status" aria-label="Loading page"><div class="skeleton skeleton-heading"></div><div class="skeleton skeleton-line"></div><section class="card">${Array.from({length: rows}, () => '<div class="loading-row"><span class="skeleton sk-icon"></span><div class="skeleton skeleton-line"></div></div>').join('')}</section></div>`;
  }

  async function render() {
    const current = ++generation;
    let route = location.hash.slice(1) || 'workspaces';
    if (!['workspaces', 'add', 'ready', 'files', 'apps', 'api'].includes(route)) route = 'workspaces';
    if (route !== 'ready') readyData = null;
    showAlert('');
    document.querySelector('#add-workspace').hidden = true;
    document.querySelector('.portal-footer').hidden = route === 'ready';
    document.querySelector('#crumb').textContent = { workspaces: 'Workspaces', add: 'Add workspace', ready: 'Connect your agent', files: 'Files', apps: 'Apps', api: 'API reference' }[route];
    document.title = `orch publish · ${document.querySelector('#crumb').textContent}`;
    document.querySelectorAll('.side-nav a').forEach(link => {
      const active = link.hash === `#${route}`;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    if (!token) { login(); return; }
    view.setAttribute('aria-busy', 'true');
    clearTimeout(skTimer);
    skTimer = setTimeout(() => { if (current === generation) view.innerHTML = loadingMarkup(route); }, 300);
    try {
      // Validate the token even when opening a form directly after signing in.
      const workspaceData = await api('/admin/api/workspaces?limit=100');
      if (current !== generation) return;
      verified = true;
      setSignedIn(true);
      workspaces = workspaceData.items || [];
      lastUpdated = Date.now(); tickUpdated();
      const sum = k => workspaces.reduce((n, w) => n + (Number(w[k]) || 0), 0);
      document.querySelector('#count-workspaces').textContent = workspaces.length;
      document.querySelector('#count-files').textContent = sum('files');
      document.querySelector('#count-apps').textContent = sum('apps');
      document.querySelector('#add-workspace').hidden = route !== 'workspaces' || !workspaces.length;
      if (route === 'api') showApi();
      if (route === 'workspaces') showWorkspaces(workspaces);
      if (route === 'add') {
        view.innerHTML = head('Add a workspace', '') + `<form class="card form form-body" novalidate>${fields({}, true)}<div class="actions"><button class="primary" type="submit">Create workspace</button><a class="button quiet" href="#workspaces">Cancel</a></div></form>`;
        const form = view.querySelector('form');
        form.elements.name.focus();
        bindSave(form, async body => {
          const result = await api('/admin/api/workspaces', 'POST', body);
          readyData = { ...result, name: body.name };
          location.hash = 'ready';
        });
      }
      if (route === 'ready') showReady();
      if (route === 'files' || route === 'apps') {
        const result = await api(`/admin/api/${route}?limit=100`);
        if (current !== generation) return;
        if (route === 'files') showFiles(result.items || [], result.next, sum('files'));
        else showApps(result.items || [], result.next);
      }
    } catch (error) {
      if (error === unauthorized) return;
      if (current !== generation) return;
      view.innerHTML = `<section class="card empty stack"><h2 tabindex="-1">Could not load this page</h2><p class="section-note">${esc(error.message)}${lastUpdated ? ` The page may be out of date (updated ${esc(ago(lastUpdated))}).` : ''}</p><button id="retry">Try again</button></section>`;
      document.querySelector('#retry').addEventListener('click', () => void render());
    } finally {
      if (current === generation) {
        decorate(view);
        if (verified && enteredRoute !== route) { orch.enter(view); enteredRoute = route; }
        clearTimeout(skTimer);
        view.removeAttribute('aria-busy');
        const cb = afterRender; afterRender = null;
        const a = document.activeElement;
        if (cb) cb();
        else if (!a || a === document.body || a === view || !a.isConnected) view.querySelector('h1, h2[tabindex]')?.focus({ preventScroll: true });
      }
    }
  }

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    const open = document.querySelector('[data-menu][aria-expanded="true"]');
    if (open) { closeMenus(); open.focus(); return; }
    const editor = document.querySelector('#editor');
    if (editor?.firstChild && !document.querySelector('dialog[open]')) { closeEditor(editingId); }
  });
  document.addEventListener('click', async e => {
    const link = e.target.closest('a[href^="#"]');
    if (link && readyData && !copied && location.hash === '#ready' && link.hash !== '#ready') {
      e.preventDefault();
      if (!document.querySelector('dialog[open]') && await confirmDialog('Leave without copying?', 'The access key is shown only once. After you leave you must make a new key.', 'Leave anyway')) location.hash = link.hash;
      return;
    }
    const b = e.target.closest('[data-menu]');
    if (b) { const open = b.getAttribute('aria-expanded') !== 'true'; closeMenus(); b.setAttribute('aria-expanded', String(open)); b.nextElementSibling.hidden = !open; }
    else closeMenus(e);
  });
  document.querySelector('#menu-toggle').addEventListener('click', e => {
    const open = e.currentTarget.getAttribute('aria-expanded') !== 'true';
    e.currentTarget.setAttribute('aria-expanded', String(open)); document.querySelector('.sidebar').dataset.open = String(open);
  });
  window.addEventListener('hashchange', () => { document.querySelector('.sidebar').dataset.open = 'false'; document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false'); void render(); window.scrollTo(0, 0); });
  void render();
})();
