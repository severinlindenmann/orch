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

  function notify(message) {
    const toast = document.querySelector('#toast');
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
  }

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
      token = '';
      readyData = null;
      try { sessionStorage.removeItem('orch_admin'); } catch (_) { /* Storage may be blocked. */ }
      document.cookie = 'orch_admin=; path=/; SameSite=Strict; Max-Age=0';
      generation++;
      login();
      throw unauthorized;
    }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.message || 'Something went wrong. Please try again.');
    return data;
  }

  function head(title, subtitle, action = '') {
    return `<div class="heading"><div><div class="eyebrow">Publish</div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${action}</div>`;
  }

  // Disable the whole form/action group to prevent overlapping destructive requests.
  async function run(container, action) {
    const controls = [...container.querySelectorAll('button, input, textarea, select')];
    const disabled = controls.map(el => el.disabled);
    controls.forEach(el => { el.disabled = true; });
    try { await action(); } catch (error) {
      notify(error === unauthorized ? 'Enter a valid admin token to continue.' : error.message);
    } finally { controls.forEach((el, i) => { el.disabled = disabled[i]; }); }
  }

  function login() {
    view.removeAttribute('aria-busy');
    document.querySelector('#crumb').textContent = 'Sign in';
    view.innerHTML = `<form id="login-form" class="card pad login"><div class="eyebrow">Admin access</div><h1>Enter the admin token</h1><p>Use your admin token to manage workspaces, files, and apps.</p><div class="field"><label for="admin-token">Admin token</label><input id="admin-token" name="token" type="password" autocomplete="current-password" required></div><button class="primary" type="submit">Continue</button></form>`;
    document.querySelector('#admin-token').focus();
    document.querySelector('#login-form').addEventListener('submit', event => {
      event.preventDefault();
      const candidate = new FormData(event.currentTarget).get('token').trim();
      if (!candidate) return;
      token = candidate;
      try { sessionStorage.setItem('orch_admin', token); } catch (_) { notify('Session storage is unavailable. You may need to sign in again after reloading.'); }
      void render();
    });
  }

  function fields(workspace = {}) {
    const rights = workspace.rights || { permanent: true, files: true, apps: true, public: false };
    return `<div class="field"><label for="name">Workspace name</label><input id="name" name="name" type="text" value="${esc(workspace.name)}" placeholder="e.g. Pilatus Workspace" required></div>
      <div class="field"><label for="description">Description</label><textarea id="description" name="description" placeholder="What is this workspace for?">${esc(workspace.description)}</textarea></div>
      <div class="field"><label for="tags">Tags</label><input id="tags" name="tags" type="text" value="${esc((workspace.tags || []).join(', '))}" placeholder="Home, reports"><small class="muted">Separate tags with commas.</small></div>
      <fieldset><legend>Publishing permissions</legend>${[
        ['permanent', 'Permanent files', 'Keep files until they are deleted.'],
        ['files', 'Temporary files', 'Share files with an expiry date.'],
        ['apps', 'Apps', 'Publish websites and small applications.']
      ].map(([key, label, hint]) => `<label class="check"><input name="${key}" type="checkbox" ${rights[key] ? 'checked' : ''}><span>${label}<small>${hint}</small></span></label>`).join('')}</fieldset>
      <div class="field field-spaced"><label for="sharing">Sharing</label><select id="sharing" name="public"><option value="false" ${!rights.public ? 'selected' : ''}>Private only</option><option value="true" ${rights.public ? 'selected' : ''}>Public links allowed</option></select></div>`;
  }

  function readFields(form) {
    const data = new FormData(form);
    return { name: data.get('name').trim(), description: data.get('description').trim(),
      tags: data.get('tags').split(',').map(tag => tag.trim()).filter(Boolean),
      rights: { permanent: data.has('permanent'), files: data.has('files'), apps: data.has('apps'), public: data.get('public') === 'true' } };
  }

  function bindSave(form, save) {
    form.addEventListener('submit', event => {
      event.preventDefault();
      const body = readFields(form);
      if (!body.name) { notify('Enter a workspace name.'); form.elements.name.focus(); return; }
      void run(form, () => save(body));
    });
  }

  function showWorkspaces(items) {
    view.innerHTML = head('Your workspaces', 'One place for everything your workspaces share.', '<a class="button primary" href="#add">＋ Add workspace</a>') +
      `<p class="summary-line">${items.length} workspaces · ${items.reduce((n, w) => n + (Number(w.files) || 0), 0)} encrypted files · ${items.reduce((n, w) => n + (Number(w.apps) || 0), 0)} apps</p><div id="editor"></div><section class="card"><div class="card-head"><h2>Workspaces</h2><span>${items.length} shown</span></div>${items.length ? items.map((w, i) => {
        const rights = w.rights || {};
        const labels = [rights.permanent && 'Permanent files', rights.files && 'Temporary files', rights.apps && 'Apps', rights.public ? 'Public links allowed' : 'Private only'].filter(Boolean);
        return `<article class="workspace"><div class="avatar">${esc(Array.from(w.name || '?')[0].toUpperCase())}</div><div><h3>${esc(w.name)}</h3><p>${esc(w.description)}</p><div class="workspace-tags">${(w.tags || []).map(tag => `<span class="workspace-tag">${esc(tag)}</span>`).join('')}</div><p class="rights">${esc(labels.join(' · '))}</p></div><div class="number">${esc(w.files)}<small>files</small></div><div class="number">${esc(w.apps)}<small>apps</small></div><button class="small" data-edit="${i}" aria-label="Edit ${esc(w.name)}">Edit</button></article>`;
      }).join('') : '<p class="empty">No workspaces yet. Add a workspace to start sharing files and apps.</p>'}</section><div class="helper"><div><b>Private by design.</b> Files are encrypted before they leave your workspace.</div><a href="#files">View files →</a></div>`;
    view.querySelectorAll('[data-edit]').forEach(button => button.addEventListener('click', () => edit(items[Number(button.dataset.edit)])));
  }

  function edit(workspace) {
    const editor = document.querySelector('#editor');
    editor.innerHTML = `<form class="card form pad workspace-edit"><h2>Edit workspace</h2><div class="field-spaced">${fields(workspace)}</div><div class="actions"><button class="primary" type="submit">Save changes</button><button type="button" data-cancel>Cancel</button></div><div class="actions"><button type="button" data-new-token>New token</button><button class="danger quiet" type="button" data-delete>Delete workspace</button></div></form>`;
    const form = editor.querySelector('form');
    form.elements.name.focus();
    form.querySelector('[data-cancel]').addEventListener('click', () => { editor.replaceChildren(); });
    bindSave(form, async body => {
      await api(path('workspaces', workspace.id), 'PATCH', body);
      await render(); notify('Workspace updated.');
    });
    form.querySelector('[data-new-token]').addEventListener('click', () => {
      if (!window.confirm('Create a new token? The current token will stop working. You will need to reconnect this workspace.')) return;
      void run(form, async () => {
        const result = await api(`${path('workspaces', workspace.id)}/token`, 'POST');
        readyData = { ...result, id: workspace.id };
        location.hash = 'ready';
      });
    });
    form.querySelector('[data-delete]').addEventListener('click', () => {
      if (!window.confirm(`Delete “${workspace.name}”? Its files and apps are removed. This cannot be undone.`)) return;
      void run(form, async () => { await api(path('workspaces', workspace.id), 'DELETE'); await render(); notify('Workspace deleted.'); });
    });
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(String(text)); notify('Copied to clipboard.'); }
    catch (_) {
      const field = document.createElement('textarea');
      const focused = document.activeElement;
      field.className = 'copy-fallback'; field.value = String(text); document.body.append(field); field.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) { /* Offer manual copy below. */ }
      field.remove(); focused?.focus();
      notify(ok ? 'Copied to clipboard.' : 'Select the text and copy it manually.');
    }
  }

  function showReady() {
    if (!readyData) { location.replace('#workspaces'); return; }
    view.innerHTML = head('Your workspace is ready', 'Connect it to the agent you already use.') +
      `<section class="card form pad"><div class="success-icon" aria-hidden="true">✓</div><p>This token is shown only once. Copy it before leaving this page.</p>${[['id', 'Workspace ID'], ['token', 'Workspace token']].map(([key, label]) => `<div class="credential"><div><small>${label}</small><code>${esc(readyData[key])}</code></div><button class="small" data-copy="${key}" aria-label="Copy ${label.toLowerCase()}">Copy</button></div>`).join('')}<h2 class="setup-heading">Connect your agent</h2><p class="section-note">Copy this prompt into your agent, in the workspace you want to connect.</p><pre>${esc(readyData.prompt)}</pre><button class="primary copy-prompt" data-copy="prompt">Copy setup prompt</button><div class="actions"><a class="button quiet" href="#workspaces">Done</a></div></section>`;
    view.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', () => void copy(readyData[button.dataset.copy])));
  }

  function expiry(value) {
    if (value == null) return 'Permanent';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Expiry unavailable';
    const days = Math.ceil((date.getTime() - Date.now()) / 86400000);
    return `${date.toLocaleDateString()} · ${days <= 0 ? 'Expired' : `${days} ${days === 1 ? 'day' : 'days'} left`}`;
  }
  function size(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value < 0) return 'Size unavailable';
    return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${(value / 1024).toFixed(1)} KB`;
  }
  function workspaceName(id) { return workspaces.find(w => w.id === id)?.name || id; }
  function safeLink(value) {
    if (!value) return '';
    try {
      const url = new URL(value, location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? `<a class="text-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Open app ↗</a>` : '';
    } catch (_) { return ''; }
  }

  function showFiles(items) {
    view.innerHTML = head('Encrypted files', 'You can manage files. Only their recipients can read them.') +
      `<section class="card"><div class="card-head"><h2>Files</h2><span>${items.length} shown</span></div>${items.length ? `<div class="table-wrap"><table><thead><tr><th>File</th><th>Workspace</th><th>Encrypted size</th><th>Expires</th><th>Controls</th></tr></thead><tbody>${items.map((file, i) => `<tr><td><strong>Name hidden</strong><small>${esc(file.id)} · encrypted</small></td><td>${esc(workspaceName(file.workspace))}</td><td>${esc(size(file.size))}</td><td>${esc(expiry(file.expires_at))}</td><td><button class="small danger quiet" data-delete="${i}" aria-label="Delete file ${esc(file.id)}">Delete</button></td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">No files yet. Files shared by your workspaces will appear here.</p>'}</section><p class="section-note">File names and contents are encrypted. Only people with the complete sharing link can open them.</p>`;
    view.querySelectorAll('[data-delete]').forEach(button => button.addEventListener('click', () => {
      const file = items[Number(button.dataset.delete)];
      if (!window.confirm(`Delete file ${file.id}? Its sharing link will stop working. This cannot be undone.`)) return;
      void run(button.parentElement, async () => { await api(path('files', file.id), 'DELETE'); await render(); notify('File deleted.'); });
    }));
  }

  function showApps(items) {
    view.innerHTML = head('Apps', 'Small apps, published from your workspaces.') +
      `<section class="card"><div class="card-head"><h2>Published apps</h2><span>${items.filter(a => a.status === 'running').length} running · ${items.length} shown</span></div>${items.length ? `<div class="table-wrap"><table><thead><tr><th>App / workspace</th><th>Status</th><th>Details</th><th>Controls</th></tr></thead><tbody>${items.map((app, i) => `<tr><td><strong>${esc(app.name)}</strong><small>${esc(workspaceName(app.workspace))}</small></td><td><span class="status ${app.status === 'running' ? 'green' : app.status === 'failed' ? 'danger' : 'muted'}"><span class="dot" aria-hidden="true"></span>${esc(app.status)}</span></td><td><div class="detail-lines">Stack: ${esc(app.stack || 'None')}<br>Store: ${esc(app.store || 'None')}<br>${app.public ? 'Public' : 'Private'}<br>${esc(expiry(app.expires_at))}</div>${safeLink(app.url)}</td><td>${['restart', 'stop', 'delete'].map(action => `<button class="small ${action === 'delete' ? 'danger quiet' : ''}" data-app="${i}" data-action="${action}" aria-label="${action} ${esc(app.name)}">${action[0].toUpperCase() + action.slice(1)}</button>`).join('')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">No apps yet. Apps published by your workspaces will appear here.</p>'}</section>`;
    view.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => {
      const app = items[Number(button.dataset.app)];
      const action = button.dataset.action;
      if (action === 'delete' && !window.confirm(`Delete “${app.name}”? This cannot be undone.`)) return;
      void run(button.parentElement, async () => {
        await api(path('apps', app.name) + (action === 'delete' ? '' : `/${action}`), action === 'delete' ? 'DELETE' : 'POST');
        await render();
        notify(action === 'delete' ? 'App deleted.' : action === 'restart' ? 'App restart requested.' : 'App stop requested.');
      });
    }));
  }

  function showApi() {
    const base = 'https://YOUR-PUBLISH-ADDRESS/v1', auth = '  -H "Authorization: Bearer $ORCH_TOKEN"';
    const examples = [
      ['GET', 'List your files', `curl "${base}/files" \\\n${auth}`],
      ['POST', 'Upload an encrypted file', `curl -X POST "${base}/files?days=7" \\\n${auth} \\\n  --data-binary @encrypted.bin`],
      ['GET', 'List your apps', `curl "${base}/apps" \\\n${auth}`],
      ['POST', 'Restart an app', `curl -X POST "${base}/apps/my-app/restart" \\\n${auth}`],
      ['POST', 'Stop an app', `curl -X POST "${base}/apps/my-app/stop" \\\n${auth}`],
      ['DELETE', 'Delete a file or app', `curl -X DELETE "${base}/files/FILE_ID" \\\n${auth}\n\n# Or delete an app\ncurl -X DELETE "${base}/apps/my-app" \\\n${auth}`]
    ];
    view.innerHTML = head('Workspace API', 'Manage only the files and apps that belong to your workspace.') +
      `<div class="card pad" style="margin-bottom:20px"><h2>Workspace token</h2><p class="section-note">Send the workspace token in the Authorization header. It identifies the workspace.</p><details style="margin-top:15px"><summary>Set up your terminal</summary><pre>export ORCH_TOKEN='your-workspace-token'</pre><p class="section-note">Use the token from onboarding. Keep it out of source control.</p></details></div><section class="card api">${examples.map(([method, label, code], i) => `<details ${i === 0 ? 'open' : ''}><summary><span class="method">${method}</span>${esc(label)}</summary><pre>${esc(code)}</pre>${i === 1 ? '<p class="section-note">Encrypt in the browser first, then upload only the encrypted bytes. Keep the key in the share link after the #. Expiry: 7 days by default; permanent files need permission.</p>' : ''}</details>`).join('')}</section>`;
  }
  async function render() {
    const current = ++generation;
    let route = location.hash.slice(1) || 'workspaces';
    if (!['workspaces', 'add', 'ready', 'files', 'apps', 'api'].includes(route)) route = 'workspaces';
    if (route !== 'ready') readyData = null;
    document.querySelector('#crumb').textContent = { workspaces: 'Workspaces', add: 'Add workspace', ready: 'Workspace ready', files: 'Files', apps: 'Apps', api: 'API reference' }[route];
    document.title = `orch publish · ${document.querySelector('#crumb').textContent}`;
    document.querySelectorAll('.side-nav a').forEach(link => {
      const active = link.hash === `#${['add', 'ready'].includes(route) ? 'workspaces' : route}`;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    if (!token) { login(); return; }
    view.setAttribute('aria-busy', 'true');
    view.innerHTML = '<p class="empty" role="status">Loading…</p>';
    try {
      // Validate the token even when opening a form directly after signing in.
      const workspaceData = await api('/admin/api/workspaces?limit=100');
      if (current !== generation) return;
      workspaces = workspaceData.items || [];
      const sum = k => workspaces.reduce((n, w) => n + (Number(w[k]) || 0), 0);
      document.querySelector('#count-workspaces').textContent = workspaces.length;
      document.querySelector('#count-files').textContent = sum('files');
      document.querySelector('#count-apps').textContent = sum('apps');
      if (route === 'api') showApi();
      if (route === 'workspaces') showWorkspaces(workspaces);
      if (route === 'add') {
        view.innerHTML = head('Add a workspace', 'Choose what this workspace can publish.') + `<form class="card form pad">${fields()}<div class="actions"><button class="primary" type="submit">Create workspace →</button><a class="button quiet" href="#workspaces">Cancel</a></div></form>`;
        bindSave(view.querySelector('form'), async body => {
          const result = await api('/admin/api/workspaces', 'POST', body);
          readyData = result;
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
      if (error === unauthorized) { notify('Enter a valid admin token to continue.'); return; }
      if (current !== generation) return;
      view.innerHTML = '<section class="card pad"><h2>Could not load this page</h2><p class="section-note">Please try again.</p><button id="retry">Try again</button></section>';
      document.querySelector('#retry').addEventListener('click', () => void render());
      notify(error.message);
    } finally { if (current === generation) view.removeAttribute('aria-busy'); }
  }

  window.addEventListener('hashchange', () => { void render(); window.scrollTo(0, 0); });
  void render();
})();
