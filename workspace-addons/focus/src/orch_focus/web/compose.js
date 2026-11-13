// Owns the composer's files: paste a screenshot (Cmd/Ctrl+V), drop files anywhere on the page, thumbnails, remove,
// plain limits, and sending them to the ticket as attachments. textContent only, never innerHTML.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, TID, toast, els, act} = S;

  /* what the core takes (orch.tickets ATTACH_*): text and pictures, 2 MB each, five at a time */
  const EXT = ['txt', 'md', 'csv', 'tsv', 'json', 'log', 'yml', 'yaml', 'toml', 'ini', 'png', 'jpg', 'jpeg', 'gif', 'webp'];
  const MAX = 2 * 1024 * 1024, MAX_FILES = 5;
  const TYPES = 'PNG, JPG, GIF, WebP, TXT, MD, CSV, JSON or LOG';
  const staged = [];  // {file, id, url|null}
  let chips, error, hint, drop, input, send, interrupt;

  const size = n => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB');
  const ext = name => (String(name).split('.').pop() || '').toLowerCase();
  const say = text => { error.textContent = text; error.hidden = !text; };

  function render() {
    chips.replaceChildren(...staged.map(f => {
      const thumb = f.url ? h('img', {class: 'fx-thumb', src: f.url, alt: ''}) : h('span', {class: 'fx-thumb fx-thumb-file', 'aria-hidden': 'true', text: ext(f.file.name).toUpperCase().slice(0, 4)});
      const rm = h('button', {type: 'button', class: 'btn ghost icon sm', 'aria-label': 'Remove ' + f.file.name, text: '×'});
      rm.addEventListener('click', () => { remove(f); els.msg.focus(); });
      return h('li', {class: 'fx-chip-file'}, thumb, h('span', {class: 'fx-chip-text'}, h('span', {class: 'fx-chip-name', text: f.file.name}),
        h('span', {class: 'meta', text: f.state === 'sending' ? 'Adding… ' + size(f.file.size) : f.state === 'failed' ? 'Not added. ' + (f.why || '') : size(f.file.size) + ' · Ready'})), rm);
    }));
    chips.hidden = !staged.length;
    els.form.classList.toggle('has-files', staged.length > 0);
  }
  function remove(f) { const i = staged.indexOf(f); if (i >= 0) staged.splice(i, 1); render(); }

  function add(files) {
    say('');
    for (const file of files) {
      if (staged.length >= MAX_FILES) { say('You can add up to ' + MAX_FILES + ' files at a time.'); break; }
      if (!EXT.includes(ext(file.name))) { say('This kind of file can’t be added: ' + file.name.slice(0, 60) + '. Choose ' + TYPES + '.'); continue; }
      if (file.size > MAX) { say(file.name.slice(0, 60) + ' is over 2 MB. Choose a smaller file.'); continue; }
      const item = {file, url: null, state: 'ready'};
      staged.push(item);
      if (file.type.startsWith('image/')) { const r = new FileReader(); r.onload = () => { item.url = String(r.result); render(); }; r.readAsDataURL(file); }  /* a data: address: the page's own rules allow it */
    }
    render();
  }

  const toBase64 = file => new Promise((ok, no) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = () => no(r.error);
    r.readAsDataURL(file);
  });

  /* the staged files reach the helper as attachments of this ticket; true when all were added */
  async function upload() {
    if (!staged.length) return true;
    const batch = staged.slice();
    for (const f of batch) f.state = 'sending';
    render();
    let files;
    try { files = await Promise.all(batch.map(async f => ({name: f.file.name, data: await toBase64(f.file)}))); }
    catch (e) { for (const f of batch) f.state = 'failed'; render(); return false; }
    const r = await act('ticket.attach', {ticket: TID, files});
    if (!r.ok) { for (const f of batch) { f.state = 'failed'; f.why = ''; } render(); say(r.message || 'The files could not be added.'); return false; }
    for (const f of batch) remove(f);
    toast(batch.length === 1 ? 'File added to the ticket.' : batch.length + ' files added to the ticket.', 'ok');
    return true;
  }

  function mount() {
    els.attachFile = h('button', {type: 'button', class: 'btn ghost icon sm', 'aria-label': 'Add a file', title: 'Add a file', text: '+'});
    input = h('input', {type: 'file', multiple: true, hidden: true, 'aria-label': 'Choose files'});
    chips = h('ul', {class: 'fx-chips', hidden: true, 'aria-label': 'Files to add'});
    error = h('p', {class: 'fx-file-error', role: 'alert', hidden: true});
    hint = h('p', {class: 'meta fx-compose-hint', text: 'Paste a screenshot or drop files · up to 2 MB each'});
    interrupt = h('button', {type: 'button', class: 'btn sm', 'data-act': 'interrupt', hidden: true, title: 'Stop what the helper is doing and read this now', text: 'Interrupt now'});
    send = els.form.querySelector('button');
    send.textContent = 'Send';
    send.title = 'Queue this instruction: the helper reads it after the current step';
    els.form.prepend(chips);
    els.form.append(els.attachFile, input, interrupt);
    els.compose.append(error, hint);
    els.attachFile.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { add([...input.files]); input.value = ''; });
    /* paste: a screenshot (or any file) from the clipboard becomes a file; plain text stays text */
    els.msg.addEventListener('paste', e => {
      const files = [...(e.clipboardData?.files || [])];
      if (!files.length) return;
      e.preventDefault();
      add(files.map(f => (f.name && f.name !== 'image.png' ? f : new File([f], 'screenshot-' + new Date().toISOString().slice(11, 19).replace(/:/g, '') + '.png', {type: f.type}))));
    });
    /* drop anywhere on the page */
    drop = h('div', {class: 'fx-drop', hidden: true, 'aria-hidden': 'true'}, h('p', {text: 'Drop files to add them to this ticket'}));
    S.root.append(drop);
    let depth = 0;
    const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
    document.addEventListener('dragenter', e => { if (hasFiles(e) && !els.compose.hidden) { depth++; drop.hidden = false; } });
    document.addEventListener('dragleave', e => { if (hasFiles(e) && --depth <= 0) { depth = 0; drop.hidden = true; } });
    document.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
    document.addEventListener('drop', e => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; drop.hidden = true; if (!els.compose.hidden) add([...e.dataTransfer.files]); });
    interrupt.addEventListener('click', () => submit(true));
    els.form.addEventListener('submit', e => { e.preventDefault(); submit(false); });
    render();
  }

  let busy = false;
  async function submit(now) {
    if (busy) return;
    const text = els.msg.value.trim();
    if (!text && !staged.length) return;
    busy = true; send.disabled = interrupt.disabled = true;
    try {
      if (!(await upload())) return;
      if (!text) return;
      els.msg.value = ''; els.msg.style.height = 'auto';
      if (now) { const stopped = await act('run.stop', {ticket: TID}); if (!stopped.ok) { els.msg.value = text; toast(stopped.message, 'error'); return; } }
      const r = await act('run.send', {ticket: TID, text});
      if (!r.ok) { els.msg.value = text; toast(r.message, 'error'); return; }
      if (now) { const again = await act('run.start', {ticket: TID}); toast(again.ok ? 'Interrupted. The helper reads it now.' : again.message, again.ok ? 'ok' : 'error'); }
      else toast(r.note || 'Queued. The helper reads it after the current step.', 'ok');
    } finally { busy = false; send.disabled = interrupt.disabled = false; }
  }

  /* Interrupt only makes sense while the helper works */
  function update(v) { if (interrupt) interrupt.hidden = !v.run.running; }

  S.register('compose', {mount, add, update, submit, files: () => staged});
  S.subscribe(update);
})();
