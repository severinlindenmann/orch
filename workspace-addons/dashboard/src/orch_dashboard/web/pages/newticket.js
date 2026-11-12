'use strict';
const ticketFileTypes = {text:/\.(txt|md|csv|tsv|json|log|yml|yaml|toml|ini)$/i, image:/\.(png|jpg|jpeg|gif|webp)$/i};
function ticketFileType(name) {
  return ticketFileTypes.text.test(name) ? 'text' : ticketFileTypes.image.test(name) ? 'image' : '';
}
function ticketFileError(file, files) {
  if (!ticketFileType(file.name)) return file.name + ': only text files and pictures';
  if (file.size > 2 * 1024 * 1024) return file.name + ' is over 2 MB';
  if (files.length >= 4) return 'At most 4 files';
  if (files.reduce((sum, item) => sum + item.size, file.size) > 3.5 * 1024 * 1024) return 'Files are over 3.5 MB';
  return '';
}
function ticketTextTitle(text, limit) {
  return (text.split(/\r?\n/).map(line => line.trim()).find(Boolean) || '').slice(0, limit);
}
function ticketBase64(dataURL) {
  return dataURL.slice(dataURL.indexOf(',') + 1);
}
// New ticket / edit ticket dialog.
function ticketForm(t) {
  const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : 'new-ticket');
  const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
  let optionalFields = fields;
  let pastedText = '', files = [], reading = Promise.resolve(), closed = false;
  let updateAttachments = () => {};
  const updateValidity = () => {
    if (t) return;
    const empty = !inputs.text.value.trim() && !pastedText && !files.length;
    inputs.text.required = empty;
    inputs.text.setCustomValidity(empty ? 'What needs doing?' : '');
  };
  d.addEventListener('close', () => {
    closed = true;
    for (const file of files) if (file.url) URL.revokeObjectURL(file.url);
  });
  if (!t) {
    const label = el('label', '', 'What needs doing?');
    const input = el('textarea', 'input new-ticket-text');
    input.name = 'text'; input.id = 'field-' + serial + '-text';
    input.rows = 10; input.maxLength = 500000; input.required = true;
    input.placeholder = 'Paste or write it here. A short title or a long text with many points: the agent splits it into tasks.';
    input.addEventListener('input', updateValidity);
    label.htmlFor = input.id; label.append(input); fields.append(label); inputs.text = input;
    const zone = button('Drop files here (e.g. .md, .txt) or paste any amount of text', 'new-ticket-drop', () => picker.click());
    const picker = el('input'); picker.type = 'file'; picker.multiple = true; picker.hidden = true;
    picker.accept = '.txt,.md,.csv,.tsv,.json,.log,.yml,.yaml,.toml,.ini,.png,.jpg,.jpeg,.gif,.webp';
    const fileError = el('p', 'bad new-ticket-file-error'); fileError.setAttribute('role', 'alert');
    const chips = el('div', 'new-ticket-files');
    const help = el('p', 'meta new-ticket-help', 'Long text is kept as a file. The agent writes the title and a short description.');
    const preview = file => {
      const {d:previewDialog, actions:previewActions} = dialog(file.name, 'sheet');
      previewActions.firstChild.textContent = 'Close';
      const stage = el('div', 'new-ticket-preview');
      if (file.type === 'image') {
        const img = el('img'); img.alt = file.name; img.src = file.url; stage.append(img);
      } else {
        const pre = el('pre'); pre.textContent = file.text.slice(0, 200000); stage.append(pre);
      }
      previewDialog.append(stage, previewActions); window.orch.open(previewDialog);
    };
    updateAttachments = () => {
      chips.replaceChildren();
      const addChip = (file, remove, pasted = false) => {
        const row = el('div', 'chip new-ticket-file');
        const body = button('', 'new-ticket-file-main', () => preview(file));
        body.append(el('span', '', file.name), el('span', 'meta', sizeText(file.size) + (pasted ? ' (pasted text)' : '')));
        const x = button('×', 'new-ticket-file-remove', remove); x.setAttribute('aria-label', 'Remove ' + file.name);
        row.append(body, x); chips.append(row);
      };
      if (pastedText) addChip({name:'note.md', text:pastedText, size:new Blob([pastedText]).size, type:'text'}, () => { pastedText = ''; updateAttachments(); }, true);
      for (const file of files) addChip(file, () => {
        files = files.filter(item => item !== file);
        if (file.url) URL.revokeObjectURL(file.url);
        updateAttachments();
      });
      help.hidden = !pastedText; updateValidity();
    };
    const addFiles = incoming => {
      reading = reading.then(async () => {
        fileError.textContent = '';
        const errors = [];
        for (const file of incoming) {
          if (closed) break;
          const problem = ticketFileError(file, files);
          if (problem) { errors.push(problem); continue; }
          try {
            const type = ticketFileType(file.name);
            const item = {name:file.name, size:file.size, type};
            if (type === 'text') {
              const bytes = new Uint8Array(await file.arrayBuffer());
              try { item.text = new TextDecoder('utf-8', {fatal:true}).decode(bytes); }
              catch (_) { item.data = btoa(Array.from(bytes, b => String.fromCharCode(b)).join('')); }  // not UTF-8: orch refuses it, we do not alter it
            } else item.data = ticketBase64(await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result); reader.onerror = () => reject(reader.error);
              reader.readAsDataURL(file);
            }));
            if (closed) break;
            if (type === 'image') item.url = URL.createObjectURL(file);
            files.push(item); updateAttachments();
          } catch (_) { errors.push(file.name + ': could not read'); }
        }
        fileError.textContent = errors.join('\n');
      });
    };
    picker.addEventListener('change', () => { addFiles(Array.from(picker.files)); picker.value = ''; });
    for (const target of [input, zone]) {
      target.addEventListener('dragover', event => { if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault(); });
      target.addEventListener('drop', event => {
        if (!event.dataTransfer?.files.length) return;
        event.preventDefault(); addFiles(Array.from(event.dataTransfer.files));
      });
    }
    input.addEventListener('paste', event => {
      const text = event.clipboardData?.getData('text/plain') || '';
      if (text.length <= 1500) return;
      event.preventDefault();
      const combined = pastedText ? pastedText + '\n\n' + text : text;
      if (combined.length > 500000) { fileError.textContent = 'Text is over 500000 characters'; return; }
      pastedText = combined; updateAttachments();
    });
    fields.append(zone, picker, fileError, chips, help); updateAttachments();
    const options = el('details', 'new-ticket-options');
    optionalFields = el('div', 'form-fields');
    options.append(el('summary', '', 'More options'), optionalFields); fields.append(options);
  }
  for (const field of (t ? ['owner', 'due', 'note', 'done_when'] : ['owner', 'due', 'done_when'])) {
    const label = el('label', '', field === 'done_when' ? 'What should be true when it is done?' : field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
    const input = el(['note', 'done_when'].includes(field) ? 'textarea' : 'input', 'input');
    input.name = field; input.id = 'field-' + serial + '-' + field;
    if (!['note', 'done_when'].includes(field)) input.type = 'text';
    if (field === 'done_when') {
      input.rows = 4; input.maxLength = 2000;
      input.placeholder = 'Optional. Say it in your own words, the agent turns it into tasks.';
    }
    if (field === 'due') {
      input.readOnly = true; input.placeholder = 'Pick a day';
      input.addEventListener('click', () => pickDate(input, input.value, v => { if (v !== null) input.value = v; }));
      input.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    }
    if (field === 'title') { input.required = true; input.maxLength = 200; }
    input.value = t?.[field] || '';
    label.htmlFor = input.id; label.append(input); optionalFields.append(label); inputs[field] = input;
  }
  const error = el('p', 'bad'); error.setAttribute('role', 'alert');
  const reload = button('Reload ticket', 'outline sm', async () => { await refresh(); await window.orch.close(d); const latest = ticketOf(t?.id); if (latest) ticketForm(latest); });
  reload.hidden = true;
  const submit = el('button', 'btn primary', t ? 'Save changes' : 'Create & Start'); submit.type = 'submit';
  let startAfter = !t, planFirst = false;
  const plain = t ? null : el('button', 'btn outline', 'Create');
  if (plain) { plain.type = 'button'; plain.addEventListener('click', () => { startAfter = false; planFirst = false; form.requestSubmit(); }); submit.addEventListener('click', () => { startAfter = true; planFirst = false; }); }
  const plan = t ? null : button('Show plan first', 'outline', () => { startAfter = true; planFirst = true; form.requestSubmit(); });
  actions.append(...(plain ? [plain, submit, plan] : [submit]));
  if (plan) fields.append(el('p', 'meta', '"Show plan first" waits for you before work starts.'));
  const startNow = async () => {
    if (t || !startAfter || !created) return;
    const run = await act('run.start', {ticket:created.id});
    window.orch.toast(run.ok ? 'Agent started' : 'The ticket was created, but the agent did not start: ' + run.text, run.ok ? 'ok' : 'error');
  };
  form.append(fields, error, reload, actions); d.append(form);
  let created = null, creationUnresolved = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    await reading;
    if (closed) return;
    updateValidity();
    if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
    submit.disabled = true; error.textContent = ''; reload.hidden = true;
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, key === 'done_when' ? input.value : input.value.trim()]));
    let result;
    if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, done_when:values.done_when, if_revision:t.revision});
    else {
      const fullText = inputs.text.value;
      if (fullText.length > 1500) {
        const combined = pastedText ? pastedText + '\n\n' + fullText : fullText;
        if (combined.length > 500000) { error.textContent = 'Text is over 500000 characters'; submit.disabled = false; return; }
        pastedText = combined; inputs.text.value = ''; updateAttachments();
      }
      const longText = pastedText, shortText = inputs.text.value;
      values.title = ticketTextTitle(fullText.trim() ? fullText : longText || files[0]?.name.replace(/\.[^.]+$/, '') || '', longText || files.length ? 80 : 200);
      // The agent may rewrite the title only when the person did not type one: it came from the pasted text or a
      // file name, or the typed first line was clipped (a sentence, not a title). A typed title stays as typed.
      const typedFirst = ticketTextTitle(fullText, Infinity), titleAuto = fullText.trim() ? typedFirst.length >= 80 : true;
      values.note = shortText.length <= 1500 && (/[\r\n]/.test(shortText) || shortText.trim() !== values.title) ? shortText : '';
      if (!created) {
        const previous = new Set(tickets().map(t => t.id));
        const args = {title:values.title, ...(planFirst ? {plan_first:true} : {}), title_auto:titleAuto, ...Object.fromEntries(['owner', 'due', 'note', 'done_when'].filter(k => values[k]).map(k => [k, values[k]])), ...(longText ? {long_text:longText} : {}), ...(files.length ? {files:files.map(({name, text, data}) => text !== undefined ? {name, text} : {name, data})} : {})};
        if (new Blob([JSON.stringify({op:'ticket.new', args})]).size > 4900000) {  // the server takes 5 MB per request
          error.textContent = 'This is too big to send at once (over 4.9 MB). Remove a file or shorten the text.' + (longText ? ' The long text is kept as the note.md chip.' : '');
          submit.disabled = false; return;
        }
        result = await act('ticket.new', args);  // one write, one history line
        if (result.ok) {
          if (result.state?.attached?.failed?.length) window.orch.toast('The ticket was created. Not saved: ' + result.state.attached.failed.join(', '), 'error');
          created = tickets().filter(t => t.title === values.title && !previous.has(t.id)).sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))[0];
          if (!created) {
            creationUnresolved = true;
            result = {ok:false, status:0, text:'The ticket was created, but could not be found in the reply. Close this dialog and reload before trying again.'};
          }
        }
      } else result = {ok:true};
      if (result.ok && created) {
        window.orch.toast('Ticket created', 'ok');
        window.orch.close(d);
        await startNow();
        return;
      }
    }
    submit.disabled = creationUnresolved;
    if (!result.ok) {
      error.textContent = window.DashHelpers.scrubText(result.text);
      reload.hidden = !(t && result.status === 409);
      if (created) { inputs.text.disabled = true; submit.textContent = 'Save details'; if (plain) plain.hidden = true; if (plan) plan.hidden = true; }
      return;
    }
    window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
    await window.orch.close(d);
    await startNow();
  });
  window.orch.open(d);
}
