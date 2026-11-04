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
  let toastTimer;
  const unauthorized = new Error('Sign in to continue.');
  const path = (kind, id) => `/admin/api/${kind}/${encodeURIComponent(id)}`;

  let lastUpdated = 0;
  let copied = false;
  let flash = {};
  function notify(message, undo) {
    const toast = document.querySelector('#toast');
    toast.replaceChildren(Object.assign(document.createElement('span'), { textContent: message }));
    if (undo) {
      const b = Object.assign(document.createElement('button'), { textContent: 'Undo', className: 'small' });
      b.addEventListener('click', () => { toast.hidden = true; clearTimeout(toastTimer); void undo(); });
      toast.append(b);
    }
    toast.hidden = false;
    const arm = () => { clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, undo ? 8000 : 6000); };
    toast.onmouseenter = toast.onfocusin = () => clearTimeout(toastTimer);
    toast.onmouseleave = toast.onfocusout = arm;
    arm();
  }

  // Confirm dialog whose button names the action (instead of window.confirm "OK").
  function confirmDialog(title, message, verb) {
    return new Promise(resolve => {
      const d = document.createElement('dialog');
      d.className = 'confirm';
      d.setAttribute('aria-labelledby', 'cd-title');
      d.innerHTML = `<h2 id="cd-title">${esc(title)}</h2><p>${esc(message)}</p><div class="actions"><button class="danger" value="yes">${esc(verb)}</button><button value="no" autofocus>Cancel</button></div>`;
      const opener = document.activeElement;
      d.addEventListener('click', e => { const v = e.target.closest('button')?.value; if (v) d.close(v); });
      d.addEventListener('close', () => { const ok = d.returnValue === 'yes'; d.remove(); opener?.focus?.(); resolve(ok); });
      document.body.append(d);
      d.showModal();
    });
  }

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
      const hadToken = Boolean(token);
      const failed = token;
      token = '';
      readyData = null;
      try { sessionStorage.removeItem('orch_admin'); } catch (_) { /* Storage may be blocked. */ }
      document.cookie = 'orch_admin=; path=/; SameSite=Strict; Max-Age=0';
      generation++;
      login(hadToken ? 'That access key didn’t work. Check it for typing mistakes and try again.' : '', failed);
      throw unauthorized;
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw Object.assign(new Error(data?.message || 'Something went wrong. Please try again.'), { status: response.status });
    return data;
  }

  function head(title, subtitle, action = '') {
    return `<div class="heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${action}</div>`;
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
    try { await action(); } catch (error) {
      if (error !== unauthorized) onError(error.message);
    } finally { busy?.removeAttribute('aria-busy'); controls.forEach((el, i) => { el.disabled = disabled[i]; }); }
  }

  function setSignedIn(on) {
    document.body.classList.toggle('signed-out', !on);
  }

  function login(message = '', keep = '') {
    view.removeAttribute('aria-busy');
    setSignedIn(false);
    showAlert('');
    document.querySelector('#crumb').textContent = 'Sign in';
    view.innerHTML = `<form id="login-form" class="card pad login" novalidate><h1>Sign in</h1><p>Enter your admin access key to manage workspaces, files and apps.</p><div class="field"><label for="admin-token">Admin access key</label><div class="pw"><input id="admin-token" name="token" type="password" autocomplete="current-password" aria-describedby="login-error" ${message ? 'class="invalid" aria-invalid="true"' : ''}><button type="button" class="small quiet" id="pw-toggle" aria-pressed="false">Show</button></div><p class="field-error" id="login-error" role="alert" ${message ? '' : 'hidden'}>${esc(message)}</p></div><button class="primary" type="submit">Continue</button><details class="help"><summary>Where do I find this?</summary><p>It is the admin key that was set when orch publish was installed. Ask the person who set up the server, or look for the file <code>admin-token</code> on the server.</p></details></form>`;
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
    const more = `<fieldset><legend>What it can publish</legend>${[
        ['permanent', 'Permanent files', 'Keep files until they are deleted.'],
        ['files', 'Temporary files', 'Share files with an expiry date.'],
        ['apps', 'Apps', 'Publish websites and small applications.']
      ].map(([key, label, hint]) => `<label class="check"><input name="${key}" type="checkbox" ${rights[key] ? 'checked' : ''}><span>${label}<small>${hint}</small></span></label>`).join('')}</fieldset>
      <div class="field field-spaced"><label for="sharing">Sharing</label><select id="sharing" name="public"><option value="false" ${!rights.public ? 'selected' : ''}>Private only</option><option value="true" ${rights.public ? 'selected' : ''}>Public links allowed</option></select></div>`;
    const descr = `<div class="field"><label for="description">Description <span class="muted">(optional)</span></label><textarea id="description" name="description" maxlength="280" placeholder="What is this workspace for?">${esc(workspace.description)}</textarea><small class="muted">Your agent can suggest this later. You approve it first.</small></div>
      <div class="field"><label for="tags">Tags <span class="muted">(optional)</span></label><input id="tags" name="tags" type="text" value="${esc((workspace.tags || []).join(', '))}" placeholder="home, reports"><small class="muted">Separate tags with commas.</small></div>`;
    return `<div class="field"><label for="name">Workspace name</label><input id="name" name="name" type="text" value="${esc(workspace.name)}" placeholder="e.g. Pilatus Workspace" maxlength="60" autocomplete="off" aria-describedby="name-error"><p class="field-error" id="name-error" role="alert" hidden></p></div>
      ${isNew ? `<details class="more"><summary>More options</summary>${descr}${more}</details>` : descr + `<details class="more"><summary>More options</summary>${more}</details>`}
      <p class="field-error form-error" role="alert" hidden></p>`;
  }

  function readFields(form) {
    const data = new FormData(form);
    return { name: data.get('name').trim(), description: data.get('description').trim(),
      tags: data.get('tags').split(',').map(tag => tag.trim()).filter(Boolean),
      rights: { permanent: data.has('permanent'), files: data.has('files'), apps: data.has('apps'), public: data.get('public') === 'true' } };
  }

  function fieldError(form, name, message) {
    const input = form.elements[name];
    const err = form.querySelector(`#${name}-error`);
    input.classList.toggle('invalid', Boolean(message));
    if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    err.textContent = message || ''; err.hidden = !message;
  }

  function bindSave(form, save) {
    const formError = form.querySelector('.form-error');
    form.elements.name.addEventListener('input', () => fieldError(form, 'name', ''));
    form.addEventListener('submit', event => {
      event.preventDefault();
      const body = readFields(form);
      formError.hidden = true;
      if (!body.name) { fieldError(form, 'name', 'Enter a name for this workspace.'); form.elements.name.focus(); return; }
      void run(form, () => save(body), message => { formError.textContent = message; formError.hidden = false; });
    });
  }

  const initials = n => String(n || '?').trim().split(/\s+/).slice(0, 2).map(x => Array.from(x)[0] || '').join('').toUpperCase() || '?';
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  // The change a workspace proposed for itself: current vs proposed, Approve / Reject (bound to this exact proposal).
  function reviewCard(w, i) {
    const p = w.pending, list = t => (t && t.length ? t.join(', ') : 'none');
    const line = (label, now, next) => `<div class="review-line"><strong>${label}</strong><p class="muted">Now: ${esc(now)}</p><p>Proposed: ${esc(next)}</p></div>`;
    const special = /[^\x00-\x7f]/.test(p.description || '') ? '<p class="muted">Contains special characters.</p>' : '';
    return `<section class="review" data-review="${i}" role="group" aria-label="Change to review for ${esc(w.name)}"><h4 tabindex="-1">${esc(w.name)} wants to change how it is described</h4>${p.description !== null && p.description !== undefined ? line('Description', w.description || 'none', p.description) : ''}${p.tags ? line('Tags', list(w.tags), list(p.tags)) : ''}${special}<p class="muted">The old text stays in use until you approve.</p><div class="actions"><button class="primary" data-act="approve">Approve</button><button data-act="reject">Reject</button></div><p class="review-result" role="alert">${esc(flash[w.id] || '')}</p></section>`;
  }

  function bindReview(box, w) {
    const result = box.querySelector('.review-result');
    box.querySelectorAll('[data-act]').forEach(button => button.addEventListener('click', async () => {
      if (box.dataset.busy) return;
      box.dataset.busy = '1';
      const label = button.textContent;
      button.textContent = button.dataset.act === 'approve' ? 'Approving…' : 'Rejecting…';
      button.setAttribute('aria-busy', 'true');
      box.querySelectorAll('button').forEach(b => { b.disabled = true; });
      result.classList.remove('field-error');
      try {
        await api(`${path('workspaces', w.id)}/profile/${button.dataset.act}`, 'POST', { rev: w.pending.rev });
        flash[w.id] = button.dataset.act === 'approve' ? 'Approved by you. The new text is now in use.' : 'Rejected. The old text stays.';
        await render();
        return;
      } catch (error) {
        if (error === unauthorized) return;
        if (error.status === 409) {
          flash[w.id] = `${w.name} sent a newer version while you were looking. Check the text, then approve or reject.`;
          await render();
          return;
        }
        result.textContent = `${error.message} Try again.`;
        result.classList.add('field-error');
        button.textContent = label;
        button.removeAttribute('aria-busy');
        box.querySelectorAll('button').forEach(b => { b.disabled = false; });
      } finally { delete box.dataset.busy; }
    }));
  }

  function showWorkspaces(items) {
    const files = items.reduce((n, w) => n + (Number(w.files) || 0), 0);
    const apps = items.reduce((n, w) => n + (Number(w.apps) || 0), 0);
    view.innerHTML = head('Your workspaces', 'One place for everything your workspaces share.', items.length ? '<a class="button primary" href="#add">＋ Add workspace</a>' : '') +
      (items.some(w => w.pending) ? `<p class="notice" role="status"><a href="#review-first" data-first-review>${plural(items.filter(w => w.pending).length, 'change needs', 'changes need')} your review</a></p>` : '') +
      (items.length ? `<p class="summary-line">${plural(items.length, 'workspace', 'workspaces')} · ${plural(files, 'encrypted file', 'encrypted files')} · ${plural(apps, 'app', 'apps')}</p>` : '') +
      `<div id="editor"></div>${items.length ? `<section class="card">${items.map((w, i) => {
        const rights = w.rights || {};
        const labels = [rights.permanent && 'Permanent files', rights.files && 'Temporary files', rights.apps && 'Apps', rights.public ? 'Public links allowed' : 'Private only'].filter(Boolean);
        return `<article class="workspace"><div class="avatar" aria-hidden="true">${esc(initials(w.name))}</div><div><h3>${esc(w.name)}${w.pending ? ' <span class="badge">Needs your review</span>' : ''}</h3>${w.description ? `<p>${esc(w.description)}</p>` : '<p class="muted">No description yet.</p>'}<div class="workspace-tags">${(w.tags || []).map(tag => `<span class="workspace-tag">${esc(tag)}</span>`).join('')}</div><p class="rights">${esc(labels.join(' · '))}</p><p class="counts-inline">${esc(plural(Number(w.files) || 0, 'file', 'files'))} · ${esc(plural(Number(w.apps) || 0, 'app', 'apps'))}</p>${!w.pending && flash[w.id] ? `<p class="review-done" role="status">${esc(flash[w.id])}</p>` : ''}${w.pending ? reviewCard(w, i) : ''}</div><div class="number">${esc(w.files)}<small>${Number(w.files) === 1 ? 'file' : 'files'}</small></div><div class="number">${esc(w.apps)}<small>${Number(w.apps) === 1 ? 'app' : 'apps'}</small></div><button class="small" data-edit="${i}" aria-label="Edit ${esc(w.name)}">Edit</button></article>`;
      }).join('')}</section>` : '<section class="card empty-card"><h2>No workspaces yet</h2><p>A workspace is one project or person that shares files and apps. Add the first one, then connect your agent to it.</p><a class="button primary" href="#add">＋ Add your first workspace</a></section>'}<div class="helper"><div><b>Private by design.</b> Files are encrypted before they leave your workspace.</div><a href="#files">View files →</a></div>`;
    view.querySelectorAll('[data-review]').forEach(box => bindReview(box, items[Number(box.dataset.review)]));
    view.querySelectorAll('[data-edit]').forEach(button => button.addEventListener('click', () => edit(items[Number(button.dataset.edit)])));
    view.querySelector('[data-first-review]')?.addEventListener('click', e => {
      e.preventDefault();
      const h = view.querySelector('.review h4');
      h?.scrollIntoView({ block: 'center' }); h?.focus();
    });
    const flashed = view.querySelector('.review-result:not(:empty)');
    if (flashed) { const h = flashed.closest('.review').querySelector('h4'); h.scrollIntoView({ block: 'center' }); h.focus(); }
    flash = {};
  }

  function edit(workspace) {
    const editor = document.querySelector('#editor');
    editor.innerHTML = `<form class="card form pad workspace-edit" novalidate><h2>Edit ${esc(workspace.name)}</h2><div class="field-spaced">${fields(workspace)}</div><div class="actions"><button class="primary" type="submit">Save changes</button><button type="button" data-cancel>Cancel</button></div><section class="danger-zone"><h3>Danger zone</h3><p>Make a new access key if the old one leaked, or remove the workspace for good.</p><div class="actions"><button type="button" data-new-token>Make a new access key</button><button class="danger quiet" type="button" data-delete>Delete workspace</button></div></section></form>`;
    const form = editor.querySelector('form');
    form.elements.name.focus();
    form.scrollIntoView({ block: 'nearest' });
    form.querySelector('[data-cancel]').addEventListener('click', () => { editor.replaceChildren(); });
    bindSave(form, async body => {
      await api(path('workspaces', workspace.id), 'PATCH', body);
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
      void run(form, async () => { await api(path('workspaces', workspace.id), 'DELETE'); await render(); notify('Workspace deleted.'); });
    });
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(String(text)); notify('Copied. Paste it to your agent.'); }
    catch (_) {
      const field = document.createElement('textarea');
      const focused = document.activeElement;
      field.className = 'copy-fallback'; field.value = String(text); document.body.append(field); field.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) { /* Offer manual copy below. */ }
      field.remove(); focused?.focus();
      notify(ok ? 'Copied. Paste it to your agent.' : 'Select the text and copy it manually.');
    }
  }

  function showReady() {
    if (!readyData) {
      view.innerHTML = head('This setup link was already used', 'For safety the access key is shown only once.') +
        '<section class="card form pad"><p>Need to connect the workspace again? Open it in the list and choose “Make a new access key”.</p><div class="actions"><a class="button primary" href="#workspaces">Back to workspaces</a></div></section>';
      return;
    }
    const name = readyData.name || 'Your workspace';
    view.innerHTML = head(readyData.renewed ? 'New access key ready' : 'Your workspace is ready', 'Connect it to the agent you already use.') +
      `<section class="card form pad"><div class="success-icon" aria-hidden="true">✓</div><h2>Connect your agent</h2><p class="section-note">Copy this and paste it into your agent, in the project that should use “${esc(name)}”. The agent connects itself and then describes the workspace.</p><button class="primary copy-prompt" data-copy="prompt">Copy for your agent</button><p class="section-note">This is shown only once. Copy it before you leave this page.</p><details class="more"><summary>Show what will be copied</summary><pre>${esc(readyData.prompt)}</pre></details><details class="more"><summary>Technical details</summary><div class="credential"><div><small>Workspace ID</small><code>${esc(readyData.id)}</code></div><button class="small" data-copy="id" aria-label="Copy workspace ID">Copy</button></div></details><div class="actions"><a class="button quiet" href="#workspaces">Done</a></div></section>`;
    copied = false;
    view.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', () => { copied = true; void copy(readyData[button.dataset.copy]); }));
    view.querySelector('a[href="#workspaces"].quiet')?.addEventListener('click', async e => {
      if (copied) return;
      e.preventDefault();
      if (await confirmDialog('Leave without copying?', 'The access key is shown only once. After you leave you must make a new key.', 'Leave anyway')) location.hash = 'workspaces';
    });
  }

  function expiry(value) {
    if (value == null) return 'Permanent';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const days = Math.ceil((date.getTime() - Date.now()) / 86400000);
    return days <= 0 ? 'Expired' : `${days} ${days === 1 ? 'day' : 'days'} left`;
  }
  function size(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return '';
    return value >= 1048576 ? `${(value / 1048576).toFixed(1).replace(/\.0$/, '')} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
  }
  function workspaceName(id) { return workspaces.find(w => w.id === id)?.name || 'Unknown workspace'; }
  function safeUrl(value) {
    if (!value) return '';
    try {
      const url = new URL(value, location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (_) { return ''; }
  }

  function showFiles(items) {
    view.innerHTML = head('Encrypted files', 'You can manage files. Only people with the sharing link can read them.') +
      (items.length ? `<section class="card">${items.map((file, i) => `<article class="item"><div class="item-main"><h3>Encrypted file · ${esc(size(file.size))} · ${esc(expiry(file.expires_at))}</h3><p>${esc(workspaceName(file.workspace))}</p><details class="more"><summary>Technical details</summary><code>${esc(file.id)}</code></details></div><button class="small danger quiet" data-delete="${i}" aria-label="Delete this file from ${esc(workspaceName(file.workspace))}">Delete</button></article>`).join('')}</section><p class="section-note">File names and contents are encrypted. Not even the admin can read them.</p>` :
      '<section class="card empty-card"><h2>No files yet</h2><p>When one of your workspaces shares a file, it shows up here. Ask your agent to share a file to try it.</p></section>');
    view.querySelectorAll('[data-delete]').forEach(button => button.addEventListener('click', async () => {
      const file = items[Number(button.dataset.delete)];
      if (!await confirmDialog('Delete this file?', 'Its sharing link will stop working. This cannot be undone.', 'Delete file')) return;
      void run(button.parentElement, async () => { await api(path('files', file.id), 'DELETE'); await render(); notify('File deleted.'); });
    }));
  }

  const STATUS = { running: ['green', 'Running'], stopped: ['muted', 'Stopped'], failed: ['danger', 'Not responding'] };

  function showApps(items) {
    view.innerHTML = head('Apps', 'Small apps, published from your workspaces.') +
      (items.length ? `<div class="app-list">${items.map((app, i) => {
        const [tone, label] = STATUS[app.status] || ['muted', app.status];
        const url = safeUrl(app.url);
        const main = app.status === 'running'
          ? (url ? `<a class="button small" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open ↗</a>` : '')
          : `<button class="small primary" data-app="${i}" data-action="restart">Start</button>`;
        return `<article class="card app-card"><div class="app-top"><div class="app-name"><h3>${esc(app.name)}</h3><p>${esc(workspaceName(app.workspace))}</p></div><span class="status ${tone}"><span class="dot" aria-hidden="true"></span>${label}</span></div><p class="app-meta">${app.public ? 'Public' : 'Private'} · ${esc(expiry(app.expires_at))}</p><div class="app-actions">${main}<details class="menu"><summary class="button small" aria-label="Manage ${esc(app.name)}">Manage ▾</summary><div class="menu-pop">${app.status === 'stopped' ? '' : `<button data-app="${i}" data-action="restart">Restart</button>`}${app.status === 'running' ? `<button data-app="${i}" data-action="stop">Stop</button>` : ''}<button class="danger" data-app="${i}" data-action="delete">Delete…</button></div></details></div><details class="more"><summary>Technical details</summary><div class="detail-lines">Type: ${esc(app.stack || 'None')}<br>Storage: ${esc(app.store || 'None')}<br>Address: <code>${esc(app.url || '')}</code></div></details></article>`;
      }).join('')}</div>` : '<section class="card empty-card"><h2>No apps yet</h2><p>Apps published by your workspaces show up here. Ask your agent to publish a small page or tool to try it.</p><a class="button" href="#workspaces">See your workspaces</a></section>');
    view.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', async () => {
      const app = items[Number(button.dataset.app)];
      const action = button.dataset.action;
      if (action === 'delete' && !await confirmDialog(`Delete “${app.name}”?`, 'Its code and data are removed. This cannot be undone.', 'Delete app')) return;
      void run(button.closest('.app-card'), async () => {
        await api(path('apps', app.name) + (action === 'delete' ? '' : `/${action}`), action === 'delete' ? 'DELETE' : 'POST');
        await render();
        if (action === 'stop') notify(`${app.name} is stopped. Visitors see “This app is paused.”`, async () => { try { await api(path('apps', app.name) + '/restart', 'POST'); await render(); notify(`${app.name} is running again.`); } catch (e) { if (e !== unauthorized) notify(`Could not start ${app.name}. Try Start on its card.`); } });
        else notify(action === 'delete' ? 'App deleted.' : `${app.name} is running.`);
      });
    }));
    document.addEventListener('click', closeMenus, { once: true });
  }
  function closeMenus(event) {
    document.querySelectorAll('details.menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
    if (document.querySelector('details.menu[open]')) document.addEventListener('click', closeMenus, { once: true });
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
    view.innerHTML = head('API reference', 'For developers. Your agent does all of this for you.') +
      `<div class="card pad" style="margin-bottom:20px"><h2>Server address</h2><p class="section-note"><code>${esc(address)}</code></p><p class="section-note">Send the workspace ID and access key with every request.</p><details class="more"><summary>Set up your terminal</summary><pre>export ORCH_WORKSPACE='your-workspace-id'\nexport ORCH_TOKEN='your-access-key'</pre><p class="section-note">Keep the key out of source control.</p></details></div><section class="card api">${examples.map(([method, label, code], i) => `<details ${i === 0 ? 'open' : ''}><summary><span class="method">${method}</span>${esc(label)}</summary><pre>${esc(code)}</pre>${i === 1 ? '<p class="section-note">Encrypt first, then upload only the encrypted bytes. The key stays in the share link after the #. Default 7 days; permanent files need permission.</p>' : ''}</details>`).join('')}</section>`;
  }

  async function render() {
    const current = ++generation;
    let route = location.hash.slice(1) || 'workspaces';
    if (!['workspaces', 'add', 'ready', 'files', 'apps', 'api'].includes(route)) route = 'workspaces';
    if (route !== 'ready') readyData = null;
    showAlert('');
    document.querySelector('#toast').hidden = true;
    document.querySelector('#crumb').textContent = { workspaces: 'Workspaces', add: 'Add workspace', ready: 'Connect your agent', files: 'Files', apps: 'Apps', api: 'API reference' }[route];
    document.title = `orch publish · ${document.querySelector('#crumb').textContent}`;
    document.querySelectorAll('.side-nav a').forEach(link => {
      const active = link.hash === `#${['add', 'ready'].includes(route) ? 'workspaces' : route}`;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    if (!token) { login(); return; }
    view.setAttribute('aria-busy', 'true');
    view.innerHTML = '<div class="skeleton-wrap" role="status" aria-label="Loading"><div class="skeleton sk-title"></div><div class="skeleton sk-line"></div><div class="skeleton sk-card"></div><div class="skeleton sk-card"></div></div>';
    try {
      // Validate the token even when opening a form directly after signing in.
      const workspaceData = await api('/admin/api/workspaces?limit=100');
      if (current !== generation) return;
      setSignedIn(true);
      workspaces = workspaceData.items || [];
      lastUpdated = Date.now(); tickUpdated();
      const sum = k => workspaces.reduce((n, w) => n + (Number(w[k]) || 0), 0);
      document.querySelector('#count-workspaces').textContent = workspaces.length;
      document.querySelector('#count-files').textContent = sum('files');
      document.querySelector('#count-apps').textContent = sum('apps');
      if (route === 'api') showApi();
      if (route === 'workspaces') showWorkspaces(workspaces);
      if (route === 'add') {
        view.innerHTML = head('Add a workspace', 'Give it a name. You can change everything later.') + `<form class="card form pad" novalidate>${fields({}, true)}<div class="actions"><button class="primary" type="submit">Create workspace →</button><a class="button quiet" href="#workspaces">Cancel</a></div></form>`;
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
        (route === 'files' ? showFiles : showApps)(result.items || []);
      }
    } catch (error) {
      if (error === unauthorized) return;
      if (current !== generation) return;
      view.innerHTML = `<section class="card pad"><h2>Could not load this page</h2><p class="section-note">${esc(error.message)}${lastUpdated ? ` The page may be out of date (updated ${esc(ago(lastUpdated))}).` : ''}</p><button id="retry">Try again</button></section>`;
      document.querySelector('#retry').addEventListener('click', () => void render());
    } finally { if (current === generation) view.removeAttribute('aria-busy'); }
  }

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const open = document.querySelector('details.menu[open]');
    if (open) { open.open = false; open.querySelector('summary').focus(); return; }
    const editor = document.querySelector('#editor');
    if (editor?.firstChild && !document.querySelector('dialog[open]')) editor.replaceChildren();
  });
  window.addEventListener('hashchange', () => { void render(); window.scrollTo(0, 0); });
  void render();
})();
