// Renew from the warning (ORCH-46). Every warning row and the list of what helpers need call renewButton(item, opts)
// for their button slot: a Renew button when orch can start the tool's own sign-in (item.renew), a Replace button when
// the check names a key (item.key), else null (the row keeps its own Check again).
// The window: orch starts the sign-in and shows its link; a code the page shows is pasted once and goes straight to the
// tool; a new key is typed hidden and goes to orch's key store. Nothing here is kept, logged or shown again.
// Words: docs/wording.md (Renew, Replace, Needs renewing). Mockup: proposals/login-warning (3a-3e).

const RENEW_POLL_MS = 1500;
const RENEW_FINAL = ['done', 'failed', 'stopped', 'none'];

// One call to the server, without the page's busy state or a full re-render (it is polled while the sign-in runs).
async function renewCall(op, args) {
  try {
    const body = JSON.stringify({op, args});
    const res = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json', 'X-Orch-Op':op}, body});
    if (res.status !== 200) return {ok:false, text:(await res.text()) || 'That did not work.'};
    const next = await res.json();
    const answer = next.renew_result || {state:'failed'};
    if (['done', 'works', 'soon'].includes(answer.state) && typeof accept === 'function') accept(next);  // the warning goes
    return {ok:true, answer};
  } catch (err) {
    return {ok:false, text:'Could not reach orch. Try again.'};
  }
}

function renewWhen(iso) {
  return iso && window.UI?.stamp ? window.UI.stamp(iso, {time:false}) : '';
}

function renewDoneText(item, answer) {
  const until = renewWhen(answer.ends_at);
  const what = item.key ? `${item.label} replaced.` : `${item.label} login renewed.`;
  const went = (answer.went_on || []).length;
  return what + (until ? ` Good until ${until}.` : '') + (went ? ` Helpers go on with ${went === 1 ? '1 ticket' : went + ' tickets'}.` : '');
}

function renewDone(body, actions, item, answer, d) {
  body.replaceChildren(h('div', {className:'banner success', role:'status'}, h('p', {className:'grow'}, renewDoneText(item, answer))));
  const done = button('Done', 'primary', () => window.orch.close(d));
  actions.replaceChildren(done);
  done.focus();
}

function renewFailed(body, actions, text, retry) {
  body.replaceChildren(h('div', {className:'banner error', role:'alert'}, h('p', {className:'grow'}, text)));
  const again = button('Try again', 'primary', retry);
  actions.replaceChildren(again);
  again.focus();
}

// A tool login: orch starts the tool's own sign-in, the person opens its page and signs in there.
function renewLogin(item) {
  const {d, actions} = dialog(`Renew the ${item.label} login`);
  const body = h('div', {className:'stack'});
  d.append(body, actions);
  let timer = null, opened = false, ended = false;
  const stop = () => { clearTimeout(timer); timer = null; };
  d.addEventListener('close', () => {
    stop();
    if (!ended) renewCall('logins.cancel', {name:item.name});  // the tool's sign-in ends with the window
  });
  const cancel = actions.firstChild;

  const showWaiting = () => {
    body.replaceChildren(
      h('p', {className:'meta', role:'status'}, h('span', {className:'spinner', 'aria-hidden':'true'}), ' Starting the sign-in…'),
    );
    actions.replaceChildren(cancel);
  };
  const showLink = link => {
    if (body.dataset.link === link) return;
    body.dataset.link = link;
    const open = h('a', {className:'btn primary', href:link, target:'_blank', rel:'noopener noreferrer'}, 'Open the sign-in page');
    open.addEventListener('click', () => { opened = true; showCode(link); });
    const copy = button('Copy link', 'ghost', () => window.UI?.copy ? window.UI.copy(link) : null);
    body.replaceChildren(
      h('p', {className:'muted'}, `orch started the ${item.label} sign-in. Open the link and sign in with your account. orch never sees or keeps your password.`),
    );
    actions.replaceChildren(cancel, copy, open);
    open.focus();
  };
  const showCode = link => {
    const input = h('input', {className:'input', id:'renew-code-' + item.name, autocomplete:'off', spellcheck:'false', autocapitalize:'off'});
    const error = h('p', {className:'meta bad', role:'alert', hidden:true});
    const go = button('Continue', 'primary', async () => {
      if (!input.value.trim()) { error.textContent = 'Paste the code from the sign-in page first.'; error.hidden = false; input.focus(); return; }
      go.disabled = true;
      const r = await renewCall('logins.code', {name:item.name, value:input.value});
      input.value = '';
      go.disabled = false;
      if (!r.ok) { error.textContent = r.text; error.hidden = false; return; }
      error.hidden = true;
      body.replaceChildren(h('p', {className:'meta', role:'status'}, h('span', {className:'spinner', 'aria-hidden':'true'}), ' Checking the login…'));
      actions.replaceChildren(cancel);
    });
    const again = h('a', {className:'btn ghost', href:link, target:'_blank', rel:'noopener noreferrer'}, 'Open the page again');
    body.replaceChildren(
      h('p', {className:'muted', role:'status'}, 'Waiting for you to sign in…'),
      h('label', {className:'field', for:input.id}, 'Does the page show a code? Paste it here.', input),
      error,
    );
    input.addEventListener('keydown', e => { if (e.key === 'Enter') go.click(); });
    actions.replaceChildren(cancel, again, go);
    input.focus();
  };

  const tick = async () => {
    timer = null;
    const r = await renewCall('logins.status', {name:item.name});
    if (!d.open) return;
    const a = r.ok ? r.answer : {state:'failed'};
    if (a.state === 'done') { ended = true; renewDone(body, actions, item, a, d); return; }
    if (a.state === 'failed' || a.state === 'stopped' || a.state === 'none') {
      ended = true;
      renewFailed(body, actions, 'The sign-in did not finish. Nothing was changed.', begin);
      return;
    }
    if (a.state === 'link' && a.link && !opened) showLink(a.link);
    timer = setTimeout(tick, RENEW_POLL_MS);
  };
  async function begin() {
    ended = false; opened = false; delete body.dataset.link;
    showWaiting();
    const r = await renewCall('logins.renew', {name:item.name});
    if (!d.open) return;
    if (!r.ok) { ended = true; renewFailed(body, actions, r.text, begin); return; }
    if (r.answer.state === 'link' && r.answer.link) showLink(r.answer.link);
    stop();
    timer = setTimeout(tick, RENEW_POLL_MS);
  }
  d.showModal();
  begin();
}

// A key: typed hidden, saved in orch's key store on this computer, checked again. Never shown again.
function renewKey(item) {
  const {d, actions} = dialog(`Replace the ${item.label}`);
  const input = h('input', {className:'input', id:'renew-key-' + item.name, type:'password', autocomplete:'off', spellcheck:'false'});
  const error = h('p', {className:'meta bad', role:'alert', hidden:true});
  const body = h('div', {className:'stack'},
    h('label', {className:'field', for:input.id}, 'New key (hidden while you type)', input),
    h('p', {className:'meta'}, 'Kept on this computer. Never shown again.'),
    error,
  );
  const save = button('Save key', 'primary', async () => {
    if (!input.value) { error.textContent = 'Paste the new key first.'; error.hidden = false; input.focus(); return; }
    save.disabled = true;
    const r = await renewCall('logins.replace', {name:item.name, value:input.value});
    input.value = '';
    save.disabled = false;
    if (!r.ok) { error.textContent = r.text; error.hidden = false; input.focus(); return; }
    if (['works', 'soon'].includes(r.answer.state)) { renewDone(body, actions, item, r.answer, d); return; }
    error.textContent = 'The new key is saved, but the check still fails. Look at the key and try again.';
    error.hidden = false;
    input.focus();
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') save.click(); });
  actions.append(save);
  d.append(body, actions);
  d.showModal();
  input.focus();
}

// The button for one row (state.logins.items). opts.quiet: the row works (a ghost button); opts.key: a stable key.
function renewButton(item, opts = {}) {
  if (!item || typeof item.name !== 'string' || typeof snapshot !== 'undefined' && snapshot) return null;
  const kind = item.key ? 'replace' : item.renew ? 'renew' : null;
  if (!kind) return null;
  const label = kind === 'replace' ? 'Replace' : 'Renew';
  const b = button(label, (opts.quiet ? 'ghost' : 'primary') + ' sm', () => (kind === 'replace' ? renewKey : renewLogin)(item));
  b.dataset[kind] = item.name;
  if (opts.key) b.dataset.key = opts.key;
  b.setAttribute('aria-label', kind === 'replace' ? `Replace the ${item.label}` : `Renew the ${item.label} login`);
  return b;
}
