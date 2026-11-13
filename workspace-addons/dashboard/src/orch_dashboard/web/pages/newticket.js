'use strict';
const EMPTY_TICKET = 'Describe what needs doing before you continue.';
const ticketFileTypes = {text:/\.(txt|md|csv|tsv|json|log|yml|yaml|toml|ini)$/i, image:/\.(png|jpg|jpeg|gif|webp)$/i};
function ticketFileType(name) {
  return ticketFileTypes.text.test(name) ? 'text' : ticketFileTypes.image.test(name) ? 'image' : '';
}
function ticketFileError(file, files) {
  if (!ticketFileType(file.name)) return file.name + ': only text files and pictures';
  if (file.size > 2 * 1024 * 1024) return file.name + ' is over 2 MB';
  if (files.reduce((sum, item) => sum + item.size, file.size) > 3.5 * 1024 * 1024) return 'Files are over 3.5 MB';
  return '';
}
function ticketTextTitle(text, limit) {
  return (text.split(/\r?\n/).map(line => line.trim()).find(Boolean) || '').slice(0, limit);
}
// "Pasted text (about 3 pages)": about 3000 characters to a page.
function pastedLabel(text) {
  const pages = Math.round(String(text || '').length / 3000);
  return 'Pasted text' + (pages <= 1 ? ' (about 1 page)' : ' (about ' + pages + ' pages)');
}
function ticketBase64(dataURL) {
  return dataURL.slice(dataURL.indexOf(',') + 1);
}
// Helpers the workspace really has: one entry per helper, the default first, never two with the same label.
function ticketHelpers(settings) {
  const out = [], labels = new Set();
  const agents = (Array.isArray(settings?.agents) ? settings.agents : []).filter(a => a && typeof a.name === 'string' && a.found !== false);
  agents.sort((a, b) => (b.chosen === true) - (a.chosen === true));
  for (const a of agents) {
    if (out.some(h => h.name === a.name)) continue;
    const plain = String(a.label || a.name).replace(/^(agent|human):/, '');
    let label = plain.charAt(0).toUpperCase() + plain.slice(1);
    if (labels.has(label.toLowerCase())) label += ' (' + a.name + ')';
    labels.add(label.toLowerCase());
    out.push({name:a.name, label, description:typeof a.description === 'string' ? a.description.slice(0, 120) : '', chosen:a.chosen === true});
  }
  return out;
}
function ticketIso(d) {
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
}
function ticketDueLabel(value) {
  if (!value) return 'No date';
  return new Date(value + 'T00:00').toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short', year:'numeric'});
}
// Due date: a month grid with quick choices; arrow keys move between days, Esc closes it.
// FOLLOW-UP: move to kit (shared date picker from the foundation PR).
function ticketDatePicker(input) {
  const wrap = el('div', 'new-ticket-date');
  const toggle = button('', 'btn new-ticket-date-toggle', () => (pop.hidden ? show() : hide()));
  toggle.id = 'field-' + serial + '-due'; toggle.setAttribute('aria-expanded', 'false');
  const pop = el('div', 'new-ticket-cal'); pop.hidden = true;
  pop.setAttribute('role', 'group'); pop.setAttribute('aria-label', 'Choose due date');
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const shift = (base, days) => { const d = new Date(base); d.setDate(d.getDate() + days); return d; };
  let view = today(), focusDay = today(), days = new Map();
  const label = () => { toggle.textContent = '▦ ' + ticketDueLabel(input.value); };
  const hide = () => { pop.hidden = true; toggle.setAttribute('aria-expanded', 'false'); };
  const pick = value => { input.value = value; label(); hide(); toggle.focus(); };
  const draw = () => {
    pop.replaceChildren(); days = new Map();
    const quick = el('div', 'new-ticket-cal-quick');
    for (const [text, n] of [['Today', 0], ['Tomorrow', 1], ['Next week', 7], ['No date', null]]) quick.append(button(text, 'new-ticket-cal-quickday', () => pick(n === null ? '' : ticketIso(shift(today(), n)))));
    const head = el('div', 'new-ticket-cal-head');
    const nav = (text, name, delta) => {
      const b = button(text, 'btn ghost sm', () => { view = new Date(view.getFullYear(), view.getMonth() + delta, 1); focusDay = new Date(view); draw(); });
      b.setAttribute('aria-label', name); return b;
    };
    const month = el('strong', '', view.toLocaleDateString('en-GB', {month:'long', year:'numeric'})); month.setAttribute('aria-live', 'polite');
    head.append(nav('‹', 'Previous month', -1), month, nav('›', 'Next month', 1));
    const grid = el('div', 'new-ticket-cal-grid');
    for (const w of ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']) { const s = el('span', 'new-ticket-cal-week', w); s.setAttribute('aria-hidden', 'true'); grid.append(s); }
    const lead = (view.getDay() + 6) % 7, count = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    for (let i = 0; i < lead; i++) grid.append(el('span'));
    const focusIso = ticketIso(focusDay), todayIso = ticketIso(today());
    for (let n = 1; n <= count; n++) {
      const day = new Date(view.getFullYear(), view.getMonth(), n), value = ticketIso(day);
      const b = button(String(n), 'new-ticket-cal-day', () => pick(value));
      b.setAttribute('aria-label', day.toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long', year:'numeric'}));
      b.tabIndex = value === focusIso ? 0 : -1;
      if (value === input.value) b.setAttribute('aria-pressed', 'true');
      if (value === todayIso) b.setAttribute('aria-current', 'date');
      days.set(value, b); grid.append(b);
    }
    pop.append(quick, head, grid);
  };
  const focusOn = d => {
    focusDay = d;
    if (d.getMonth() !== view.getMonth() || d.getFullYear() !== view.getFullYear()) { view = new Date(d.getFullYear(), d.getMonth(), 1); draw(); }
    for (const [value, b] of days) b.tabIndex = value === ticketIso(d) ? 0 : -1;
    days.get(ticketIso(d))?.focus();
  };
  const show = () => {
    focusDay = input.value ? new Date(input.value + 'T00:00') : today();
    view = new Date(focusDay.getFullYear(), focusDay.getMonth(), 1);
    draw(); pop.hidden = false; toggle.setAttribute('aria-expanded', 'true'); focusOn(focusDay);
  };
  pop.addEventListener('keydown', event => {
    const step = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-7, ArrowDown:7}[event.key];
    if (step && event.target?.className === 'new-ticket-cal-day') { event.preventDefault(); focusOn(shift(focusDay, step)); }
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation?.(); hide(); toggle.focus(); }  // closes the calendar, not the window
  });
  label(); wrap.append(toggle, input, pop);
  return {wrap, toggle, pop, hide, show};
}
// New ticket / edit ticket dialog.
function ticketForm(t) {
  const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : 'new-ticket');
  const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
  // The window closes with X, Esc (window.orch.open) and a click on the backdrop; dialog() puts the cursor back where it was.
  const closeX = button('✕', 'btn ghost sm new-ticket-close', () => window.orch.close(d));
  closeX.setAttribute('aria-label', t ? 'Close edit ticket' : 'Close new ticket'); d.append(closeX);
  d.addEventListener('click', event => { if (event.target === d) window.orch.close(d); });
  let helpers = [], helperSelect = null;
  let pastedText = '', files = [], reading = Promise.resolve(), closed = false;
  let updateAttachments = () => {}, grow = () => {};
  const updateValidity = () => {
    if (t) return;
    const empty = !inputs.text.value.trim() && !pastedText && !files.length;
    inputs.text.required = empty;
    inputs.text.setCustomValidity(empty ? EMPTY_TICKET : '');
  };
  d.addEventListener('close', () => {
    closed = true;
    for (const file of files) if (file.url) URL.revokeObjectURL(file.url);
  });
  if (!t) {
    const label = el('label', '', 'What needs doing?');
    const input = el('textarea', 'input new-ticket-text');
    input.name = 'text'; input.id = 'field-' + serial + '-text';
    input.rows = 4; input.maxLength = 500000; input.required = true;
    input.placeholder = 'Paste or write it here. A short title or a long text with many points: the agent splits it into tasks.';
    // Grows with the text (about 4 lines at first); CSSOM height, no style attribute.
    grow = () => { if (!input.style) return; input.style.height = 'auto'; if (input.scrollHeight) input.style.height = Math.min(input.scrollHeight + 2, 480) + 'px'; };
    input.addEventListener('input', updateValidity); input.addEventListener('input', grow);
    label.htmlFor = input.id; label.append(input); fields.append(label); inputs.text = input;
    const zone = el('div', 'new-ticket-drop');
    const attach = button('＋ Add files or drop them here', 'new-ticket-attach', () => picker.click());
    zone.append(attach, el('p', 'meta new-ticket-file-hint', 'Add as many files as you need · text files and pictures, up to 2 MB each'));
    const picker = el('input'); picker.type = 'file'; picker.multiple = true; picker.hidden = true;
    picker.accept = '.txt,.md,.csv,.tsv,.json,.log,.yml,.yaml,.toml,.ini,.png,.jpg,.jpeg,.gif,.webp';
    const fileError = el('p', 'bad new-ticket-file-error'); fileError.setAttribute('role', 'alert');
    const chips = el('ul', 'new-ticket-files'); chips.setAttribute('aria-label', 'Added files');
    const status = el('p', 'meta new-ticket-reading'); status.setAttribute('role', 'status');
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
        const row = el('li', 'new-ticket-file');
        const body = button('', 'new-ticket-file-main', () => preview(file));
        body.append(el('span', '', pasted ? pastedLabel(file.text) : file.name));
        if (!pasted && typeof sizeText === 'function') body.append(el('span', 'meta', sizeText(file.size)));
        const x = button('Remove', 'btn ghost xs new-ticket-file-remove', remove); x.setAttribute('aria-label', 'Remove ' + (pasted ? 'pasted text' : file.name));
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
        if (incoming.length) status.textContent = 'Reading ' + (incoming.length === 1 ? 'the file' : incoming.length + ' files') + '…';
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
        status.textContent = '';
        fileError.textContent = errors.join('\n');
      });
    };
    picker.addEventListener('change', () => { addFiles(Array.from(picker.files)); picker.value = ''; });
    for (const target of [form]) {
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
    fields.append(zone, picker, status, fileError, chips, help); updateAttachments();
    // Helper: only the helpers this workspace has. One helper is fixed text; none is a plain empty state.
    // FOLLOW-UP: move to kit (shared custom select from the foundation PR); a native select until then.
    helpers = ticketHelpers(typeof state !== 'undefined' && state ? state.settings : null);
    const helperBox = el('div', 'new-ticket-helper');
    if (helpers.length > 1) {
      const helperLabel = el('label', '', 'Helper');
      helperSelect = el('select', 'input'); helperSelect.name = 'helper'; helperSelect.id = 'field-' + serial + '-helper';
      for (const h of helpers) { const option = el('option', '', h.label + (h.chosen ? ' (default)' : '')); option.value = h.name; helperSelect.append(option); }
      helperSelect.value = helpers[0].name;
      const about = el('p', 'meta new-ticket-helper-about');
      const describe = () => { about.textContent = helpers.find(h => h.name === helperSelect.value)?.description || ''; about.hidden = !about.textContent; };
      helperSelect.addEventListener('change', describe); describe();
      helperLabel.htmlFor = helperSelect.id; helperLabel.append(helperSelect); helperBox.append(helperLabel, about);
    } else {
      helperBox.append(el('span', 'new-ticket-label', 'Helper'));
      if (helpers.length) {
        helperBox.append(el('p', 'new-ticket-helper-fixed', helpers[0].label));
        if (helpers[0].description) helperBox.append(el('p', 'meta new-ticket-helper-about', helpers[0].description));
      } else helperBox.append(el('p', 'meta new-ticket-empty', 'No helper is set up yet. The ticket is kept and waits until one is ready.'));
    }
    const dueInput = el('input'); dueInput.type = 'hidden'; dueInput.name = 'due'; inputs.due = dueInput;
    const due = ticketDatePicker(dueInput);
    const dueLabel = el('label', '', 'Due date (optional)'); dueLabel.htmlFor = due.toggle.id;
    const dueBox = el('div', 'new-ticket-due'); dueBox.append(dueLabel, due.wrap);
    form.addEventListener('mousedown', event => { if (!due.wrap.contains(event.target)) due.hide(); });
    const options = el('div', 'new-ticket-options'); options.append(helperBox, dueBox); fields.append(options);
    const doneLabel = el('label', '', 'Done when (optional)');
    const done = el('textarea', 'input'); done.name = 'done_when'; done.id = 'field-' + serial + '-done_when';
    done.rows = 2; done.maxLength = 2000; done.placeholder = 'What should be true when it is done? Say it in your own words.';
    doneLabel.htmlFor = done.id; doneLabel.append(done); fields.append(doneLabel); inputs.done_when = done;
  }
  for (const field of (t ? ['owner', 'due', 'note', 'done_when'] : [])) {
    const label = el('label', '', field === 'done_when' ? 'What should be true when it is done?' : field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
    const input = el(['note', 'done_when'].includes(field) ? 'textarea' : 'input', 'input');
    input.name = field; input.id = 'field-' + serial + '-' + field;
    if (!['note', 'done_when'].includes(field)) input.type = 'text';
    if (field === 'done_when') {
      input.rows = 4; input.maxLength = 2000;
      input.placeholder = 'Optional. Say it in your own words, the helper turns it into tasks.';
    }
    if (field === 'due') {
      input.readOnly = true; input.placeholder = 'Pick a day';
      input.addEventListener('click', () => pickDate(input, input.value, v => { if (v !== null) input.value = v; }));
      input.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    }
    if (field === 'title') { input.required = true; input.maxLength = 200; }
    input.value = t?.[field] || '';
    label.htmlFor = input.id; label.append(input); fields.append(label); inputs[field] = input;
  }
  const error = el('p', 'bad'); error.setAttribute('role', 'alert');
  const reload = button('Reload ticket', 'outline sm', async () => { await refresh(); await window.orch.close(d); const latest = ticketOf(t?.id); if (latest) ticketForm(latest); });
  reload.hidden = true;
  const submit = el('button', 'btn primary', t ? 'Save changes' : 'Start'); submit.type = 'submit';
  let startAfter = !t;
  // One main button (Start) and Cancel; the plan choice is a plain box, "Create without starting" a text link.
  let planBox = null;
  if (!t) {
    const planLabel = el('label', 'new-ticket-check');
    planBox = el('input'); planBox.type = 'checkbox'; planBox.name = 'plan_first';
    planLabel.append(planBox, el('span', '', 'Show me the plan first'), el('span', 'meta', 'The helper waits for your OK before work starts.'));
    fields.append(planLabel);
  }
  const plain = t ? null : button('Create without starting', 'new-ticket-link', () => { startAfter = false; form.requestSubmit(); });
  if (plain) submit.addEventListener('click', () => { startAfter = true; });
  actions.append(submit);
  if (plain) fields.append(plain);
  const startNow = async () => {
    if (t || !startAfter || !created) return;
    const run = await act('run.start', {ticket:created.id});
    window.orch.toast(run.ok ? 'Helper started' : 'The ticket was created, but the helper did not start: ' + run.text, run.ok ? 'ok' : 'error');
  };
  form.append(fields, error, reload, actions); d.append(form);
  let created = null, creationUnresolved = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    await reading;
    if (closed) return;
    updateValidity();
    if (!t && inputs.text.required) error.textContent = EMPTY_TICKET;
    if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
    submit.disabled = true; error.textContent = ''; reload.hidden = true;
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, key === 'done_when' ? input.value : input.value.trim()]));
    // A helper other than the default is kept as the ticket's owner. FOLLOW-UP: run.start takes no helper yet.
    if (!t) values.owner = helperSelect && helperSelect.value !== helpers[0].name ? 'agent:' + helperSelect.value : '';
    let result;
    if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, done_when:values.done_when, if_revision:t.revision});
    else {
      const fullText = inputs.text.value;
      if (fullText.length > 1500) {
        const combined = pastedText ? pastedText + '\n\n' + fullText : fullText;
        if (combined.length > 500000) { error.textContent = 'Text is over 500000 characters'; submit.disabled = false; return; }
        pastedText = combined; inputs.text.value = ''; grow(); updateAttachments();
      }
      const longText = pastedText, shortText = inputs.text.value;
      values.title = ticketTextTitle(fullText.trim() ? fullText : longText || files[0]?.name.replace(/\.[^.]+$/, '') || '', longText || files.length ? 80 : 200);
      // The agent may rewrite the title only when the person did not type one: it came from the pasted text or a
      // file name, or the typed first line was clipped (a sentence, not a title). A typed title stays as typed.
      const typedFirst = ticketTextTitle(fullText, Infinity), titleAuto = fullText.trim() ? typedFirst.length >= 80 : true;
      values.note = shortText.length <= 1500 && (/[\r\n]/.test(shortText) || shortText.trim() !== values.title) ? shortText : '';
      if (!created) {
        const previous = new Set(tickets().map(t => t.id));
        const planFirst = startAfter && !!planBox?.checked;
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
      if (created) { inputs.text.disabled = true; submit.textContent = 'Save details'; if (plain) plain.hidden = true; }
      return;
    }
    window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
    await window.orch.close(d);
    await startNow();
  });
  window.orch.open(d);
}
