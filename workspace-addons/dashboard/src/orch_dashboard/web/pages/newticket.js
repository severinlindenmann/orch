'use strict';
const EMPTY_TICKET = 'Describe what needs doing before you continue.';
const ticketFileTypes = {text:/\.(txt|md|csv|tsv|json|log|yml|yaml|toml|ini)$/i, image:/\.(png|jpg|jpeg|gif|webp)$/i};
function ticketFileType(name) {
  return ticketFileTypes.text.test(name) ? 'text' : ticketFileTypes.image.test(name) ? 'image' : '';
}
function ticketFileError(file, files) {
  if (!ticketFileType(file.name)) return file.name + ': only text files and pictures';
  if (file.size > 25 * 1024 * 1024) return file.name + ' is over 25 MB';
  if (files.reduce((sum, item) => sum + item.size, file.size) > 100 * 1024 * 1024) return 'Files are over 100 MB';
  return '';
}
// ORCH-62: a first line longer than the limit is cut at a whole word, never right after an abbreviation such as
// "e.g." (it read like the end of a sentence), and ends with "…" so it reads as cut. The core cuts the same way.
const TITLE_ABBR = /(?:^|\s)(?:e\.\s?g\.|i\.\s?e\.|etc\.|z\.\s?B\.|d\.\s?h\.|u\.\s?a\.|bzw\.|vs\.|ca\.|approx\.)$/i;
const TITLE_TAIL = /\s(?:and|or|but|then|for|to|of|the|a|an|with|in|on|at|by|like|und|oder|dann|für|mit|der|die|das|zu)$/i;  // a cut never ends on a small word
function ticketTextTitle(text, limit) {
  const line = (text.split(/\r?\n/).map(l => l.trim()).find(Boolean) || '').replace(/\s+/g, ' ');
  if (line.length <= limit) return line;
  let cut = line.slice(0, limit - 1);
  const space = cut.lastIndexOf(' ');
  if (line[limit - 1] !== ' ' && space > limit / 2) cut = cut.slice(0, space);
  for (let prev = ''; prev !== cut;) { prev = cut; cut = cut.replace(TITLE_ABBR, '').replace(/[\s,;:.\-–—(]+$/, ''); if (cut.length > limit / 2) cut = cut.replace(TITLE_TAIL, ''); }
  return (cut || line.slice(0, limit - 1).trim()) + '…';
}
// "Pasted text (about 3 pages)": about 3000 characters to a page.
function pastedLabel(text) {
  const pages = Math.round(String(text || '').length / 3000);
  return 'Pasted text' + (pages <= 1 ? ' (about 1 page)' : ' (about ' + pages + ' pages)');
}
function ticketBase64(dataURL) {
  return dataURL.slice(dataURL.indexOf(',') + 1);
}
// One picked, dropped or pasted file as the dialog keeps it: {name, size, type, text | data[, url]}.
async function ticketReadFile(file) {
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
  return item;
}
const ticketSendFiles = files => files.map(({name, text, data}) => text !== undefined ? {name, text} : {name, data});
function ticketPreview(file) {
  const {d:previewDialog, actions:previewActions} = dialog(file.name, 'sheet');
  previewActions.firstChild.textContent = 'Close';
  const stage = el('div', 'new-ticket-preview');
  if (file.type === 'image') {
    const img = el('img'); img.alt = file.name; img.src = file.url; stage.append(img);
  } else {
    const pre = el('pre'); pre.textContent = file.text.slice(0, 200000); stage.append(pre);
  }
  previewDialog.append(stage, previewActions); window.orch.open(previewDialog);
}
function ticketFileChip(file, remove, label = file.name) {
  const row = el('li', 'new-ticket-file');
  const body = button('', 'new-ticket-file-main', () => ticketPreview(file));
  if (file.type === 'image' && file.url) { const thumb = el('img', 'thumbnail'); thumb.alt = ''; thumb.src = file.url; body.append(thumb); }  // ORCH-185: a picture shows itself
  body.append(el('span', '', label));
  if (label === file.name && typeof sizeText === 'function') body.append(el('span', 'meta', sizeText(file.size)));
  const x = button('Remove', 'btn ghost xs new-ticket-file-remove', remove); x.setAttribute('aria-label', 'Remove ' + (label === file.name ? file.name : 'pasted text'));
  row.append(body, x); return row;
}
// What one ticket of the dialog sends: the title from the first typed line, else the long text, else the first file.
// The agent may rewrite the title only when the person did not type one (it came from a paste or a file name, or the
// typed first line was clipped: a sentence, not a title).
// typed: all the text in the box (for the title); short: what stays in the box (the note); long: the text kept as note.md.
// ORCH-185: what was typed in New ticket survives Cancel, Esc, the backdrop and Back; the next New ticket brings it
// back (with a Discard link) until the ticket is made. Pictures and files are not kept, only the text.
let ticketDraft = null;
const TITLE_MAX = 200, TITLE_PLACEHOLDER = 80, WISH_MIN = 40;
function ticketFromText(typed, short, longText, files) {
  // ORCH-185: a first line over 200 characters is never cut and dropped: it is a sentence, so the title is a short
  // placeholder (the agent writes the real one) and every word stays in the note or in the long text.
  const firstLine = ticketTextTitle(typed, Infinity), wordy = firstLine.length > TITLE_MAX;
  const title = ticketTextTitle(typed.trim() ? typed : longText || files[0]?.name.replace(/\.[^.]+$/, '') || '', longText || files.length || wordy ? TITLE_PLACEHOLDER : TITLE_MAX);
  const titleAuto = typed.trim() ? firstLine.length >= TITLE_PLACEHOLDER : true;
  // A one-sentence wish stays under "What you asked" too, not only a title (a short label such as "Fix login" is just the title).
  const note = short.length <= 1500 && (/[\r\n]/.test(short) || short.trim() !== title || short.trim().length > WISH_MIN) ? short : '';
  return {title, title_auto:titleAuto, ...(note ? {note} : {}), ...(longText ? {long_text:longText} : {}), ...(files.length ? {files:ticketSendFiles(files)} : {})};
}
// A ticket inside the epic: long text (over 1500 characters) is kept as note.md, like the main box; an empty one is skipped.
function ticketStepArgs(text, files, parent, owner) {
  if (!text.trim() && !files.length) return null;
  const long = text.length > 1500;
  return {...ticketFromText(text, long ? '' : text, long ? text : '', files), parent, ...(owner ? {owner} : {})};
}
const ticketTooBig = args => new Blob([JSON.stringify({op:'ticket.new', args})]).size > 4900000;  // the server takes 5 MB per request
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
// The due date uses the shared date picker (kit/date.js: UI.date); a hidden input keeps the chosen day for the form.
// New ticket / edit ticket dialog.
function ticketForm(t) {
  const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : 'new-ticket');
  const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
  if (!t) { d.className = (d.className ? d.className + ' ' : '') + 'new-ticket ui-bottom-close'; d.querySelector?.('h2')?.after?.(el('p', 'meta new-ticket-sub', 'Give your helper something to work on.')); }
  // The window closes with its Close button, Esc and a click on the backdrop (kit/overlay.js); dialog() puts the cursor back where it was.
  let helpers = [], helperSelect = null, doneWrap = null;
  let pastedText = '', files = [], reading = Promise.resolve(), closed = false;
  let updateAttachments = () => {}, grow = () => {}, readInto = null;
  const steps = [];  // ORCH-14: an epic. Each entry becomes its own ticket inside the new one, with its own text and files
  const updateValidity = () => {
    if (t) return;
    const empty = !inputs.text.value.trim() && !pastedText && !files.length;
    inputs.text.required = empty;
    inputs.text.setCustomValidity(empty ? EMPTY_TICKET : '');
  };
  let sent = false;
  d.addEventListener('close', () => {
    closed = true;
    if (!t) {
      const draft = {text:inputs.text.value, pasted:pastedText, done:inputs.done_when?.value || '', steps:steps.map(step => step.input.value)};
      const has = draft.text.trim() || draft.pasted || draft.done.trim() || draft.steps.some(x => x.trim());
      ticketDraft = !sent && has ? draft : null;
    }
    for (const file of [...files, ...steps.flatMap(step => step.files)]) if (file.url) URL.revokeObjectURL(file.url);
  });
  if (!t) {
    const label = el('label', '', 'What needs doing?');
    const input = el('textarea', 'input new-ticket-text');
    input.name = 'text'; input.id = 'field-' + serial + '-text';
    input.rows = 3; input.maxLength = 500000; input.required = true;
    input.placeholder = 'What should the helper do? A sentence or a long text; it is split into steps.';
    // Grows with the text (about 4 lines at first); CSSOM height, no style attribute.
    grow = () => { if (!input.style) return; input.style.height = 'auto'; if (input.scrollHeight) input.style.height = Math.min(input.scrollHeight + 2, 480) + 'px'; };
    input.addEventListener('input', updateValidity); input.addEventListener('input', grow);
    label.htmlFor = input.id; label.append(input); fields.append(label); inputs.text = input;
    const zone = el('div', 'new-ticket-drop');
    const attach = button('＋ Add files: pick, drop or paste them here', 'new-ticket-attach', () => picker.click());
    zone.append(attach, el('p', 'meta new-ticket-file-hint', 'Add as many files as you need · text files and pictures, up to 25 MB each'));
    const picker = el('input'); picker.type = 'file'; picker.multiple = true; picker.hidden = true;
    picker.accept = '.txt,.md,.csv,.tsv,.json,.log,.yml,.yaml,.toml,.ini,.png,.jpg,.jpeg,.gif,.webp';
    const fileError = el('p', 'bad new-ticket-file-error'); fileError.setAttribute('role', 'alert');
    const chips = el('ul', 'new-ticket-files'); chips.setAttribute('aria-label', 'Added files');
    const status = el('p', 'meta new-ticket-reading'); status.setAttribute('role', 'status');
    const help = el('p', 'meta new-ticket-help', 'Long text is kept as a file. The agent writes the title and a short description.');
    updateAttachments = () => {
      chips.replaceChildren();
      if (pastedText) chips.append(ticketFileChip({name:'note.md', text:pastedText, size:new Blob([pastedText]).size, type:'text'}, () => { pastedText = ''; updateAttachments(); }, pastedLabel(pastedText)));
      for (const file of files) chips.append(ticketFileChip(file, () => {
        files.splice(files.indexOf(file), 1);
        if (file.url) URL.revokeObjectURL(file.url);
        updateAttachments();
      }));
      help.hidden = !pastedText; updateValidity();
    };
    // Reads picked, dropped or pasted files into a list (the ticket's own or a step's), one after the other: the
    // submit waits for `reading`, so nothing is sent half read.
    readInto = (incoming, list, errorEl, changed) => {
      reading = reading.then(async () => {
        errorEl.textContent = '';
        const errors = [];
        if (incoming.length) status.textContent = 'Reading ' + (incoming.length === 1 ? 'the file' : incoming.length + ' files') + '…';
        for (const file of incoming) {
          if (closed) break;
          const problem = ticketFileError(file, list);
          if (problem) { errors.push(problem); continue; }
          try {
            const item = await ticketReadFile(file);
            if (closed) break;
            if (item.type === 'image') item.url = URL.createObjectURL(file);
            list.push(item); changed();
          } catch (_) { errors.push(file.name + ': could not read'); }
        }
        status.textContent = '';
        errorEl.textContent = errors.join('\n');
      });
    };
    const addFiles = incoming => readInto(incoming, files, fileError, updateAttachments);
    picker.addEventListener('change', () => { addFiles(Array.from(picker.files)); picker.value = ''; });
    for (const target of [form]) {
      target.addEventListener('dragover', event => { if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault(); });
      target.addEventListener('drop', event => {
        if (!event.dataTransfer?.files.length) return;
        event.preventDefault(); addFiles(Array.from(event.dataTransfer.files));
      });
    }
    input.addEventListener('paste', event => {
      const pasted = window.UI?.pastedFiles?.(event) || [];  // a pasted screenshot or file: same path as a picked file
      if (pasted.length) { event.preventDefault(); addFiles(pasted); return; }
      const text = event.clipboardData?.getData('text/plain') || '';
      if (text.length <= 1500) return;
      event.preventDefault();
      const combined = pastedText ? pastedText + '\n\n' + text : text;
      if (combined.length > 500000) { fileError.textContent = 'Text is over 500000 characters'; return; }
      pastedText = combined; updateAttachments();
    });
    fields.append(zone, picker, status, fileError, chips, help); updateAttachments();
    // Epic: several tickets at once (owner, ORCH-14). The text above is the epic; each entry below becomes its own
    // ticket inside it (the epic page lists them), with its own text, screenshots and files.
    const stepList = el('div', 'stack new-ticket-steps');
    const stepHelp = el('p', 'meta new-ticket-help', 'This ticket becomes an epic. Each ticket below is made inside it, with its own files.');
    const renumber = () => {
      steps.forEach((step, i) => {
        step.head.textContent = 'Ticket ' + (i + 1);
        step.input.setAttribute('aria-label', 'Ticket ' + (i + 1) + ': what needs doing?');
        step.remove.setAttribute('aria-label', 'Remove ticket ' + (i + 1));
      });
      stepHelp.hidden = !steps.length;
      addStep.textContent = steps.length ? '＋ Add another ticket' : '＋ Make it an epic with several tickets';
    };
    const newStep = () => {
      const step = {files:[]}, box = el('section', 'card pad stack new-ticket-step'), top = el('div', 'row between');
      step.head = el('strong');
      step.remove = button('Remove', 'btn ghost xs', () => {
        for (const file of step.files) if (file.url) URL.revokeObjectURL(file.url);
        steps.splice(steps.indexOf(step), 1); box.remove(); renumber();
      });
      top.append(step.head, step.remove);
      const text = el('textarea', 'input'); text.name = 'step'; text.rows = 2; text.maxLength = 500000;
      text.placeholder = 'What needs doing in this ticket?';
      const stepPicker = el('input'); stepPicker.type = 'file'; stepPicker.multiple = true; stepPicker.hidden = true; stepPicker.accept = picker.accept;
      const stepAttach = button('＋ Add files', 'new-ticket-attach', () => stepPicker.click());
      const stepError = el('p', 'bad new-ticket-file-error'); stepError.setAttribute('role', 'alert');
      const stepChips = el('ul', 'new-ticket-files'); stepChips.setAttribute('aria-label', 'Files for this ticket');
      const draw = () => stepChips.replaceChildren(...step.files.map(file => ticketFileChip(file, () => {
        step.files.splice(step.files.indexOf(file), 1);
        if (file.url) URL.revokeObjectURL(file.url);
        draw();
      })));
      const add = incoming => readInto(incoming, step.files, stepError, draw);
      stepPicker.addEventListener('change', () => { add(Array.from(stepPicker.files)); stepPicker.value = ''; });
      box.addEventListener('drop', event => {  // a drop on a ticket box is that ticket's, not the epic's
        if (!event.dataTransfer?.files.length) return;
        event.preventDefault(); event.stopPropagation?.(); add(Array.from(event.dataTransfer.files));
      });
      text.addEventListener('paste', event => {
        const pasted = window.UI?.pastedFiles?.(event) || [];
        if (pasted.length) { event.preventDefault(); add(pasted); }
      });
      box.append(top, text, stepAttach, stepPicker, stepError, stepChips);
      Object.assign(step, {box, input:text});
      steps.push(step); stepList.append(box); renumber(); text.focus();
      return step;
    };
    d.newStep = newStep;
    const addStep = button('', 'new-ticket-attach new-ticket-add-step', newStep);
    fields.append(stepHelp, stepList, addStep); renumber();
    // Helper: only the helpers this workspace has. One helper is fixed text; none is a plain empty state.
    // FOLLOW-UP: move to kit (shared custom select from the foundation PR); a native select until then.
    helpers = ticketHelpers(typeof state !== 'undefined' && state ? state.settings : null);
    const helperBox = el('div', 'new-ticket-helper');
    const noHelperRow = helpers.length === 1 && /^helper$/i.test(helpers[0].label) && !helpers[0].description;
    if (helpers.length > 1) {
      const helperLabel = el('label', '', 'Helper');
      helperSelect = el('select', 'input'); helperSelect.name = 'helper'; helperSelect.id = 'field-' + serial + '-helper';
      for (const h of helpers) { const option = el('option', '', h.label + (h.chosen ? ' (default)' : '')); option.value = h.name; helperSelect.append(option); }
      helperSelect.value = helpers[0].name;
      const about = el('p', 'meta new-ticket-helper-about');
      const describe = () => { about.textContent = helpers.find(h => h.name === helperSelect.value)?.description || ''; about.hidden = !about.textContent; };
      helperSelect.addEventListener('change', describe); describe();
      helperLabel.htmlFor = helperSelect.id; helperLabel.append(helperSelect); helperBox.append(helperLabel, about);
    } else if (noHelperRow) {
      // one helper that is just called "Helper": a "Helper / Helper" row says nothing
    } else {
      helperBox.append(el('span', 'new-ticket-label', 'Helper'));
      if (helpers.length) {
        helperBox.append(el('p', 'new-ticket-helper-fixed', helpers[0].label));
        if (helpers[0].description) helperBox.append(el('p', 'meta new-ticket-helper-about', helpers[0].description));
      } else helperBox.append(el('p', 'meta new-ticket-empty', 'No helper is set up yet. The ticket is kept and waits until one is ready.'));
    }
    const dueInput = el('input'); dueInput.type = 'hidden'; dueInput.name = 'due'; dueInput.id = 'field-' + serial + '-due-value'; inputs.due = dueInput;
    const dueToggle = el('button', 'btn outline new-ticket-date-toggle', '▦ No date'); dueToggle.type = 'button'; dueToggle.id = 'field-' + serial + '-due';
    const dueLabel = el('label', '', 'Due date (optional)'); dueLabel.htmlFor = dueToggle.id;
    const dueBox = el('div', 'new-ticket-due'); dueBox.append(dueLabel, dueToggle, dueInput);
    if (window.UI?.date) window.UI.date(dueInput, dueToggle, null, {time:true});
    const options = el('div', 'new-ticket-options'); options.append(...(noHelperRow ? [] : [helperBox]), dueBox); fields.append(options);
    const doneLabel = el('label', '', 'Done when (optional)');
    const done = el('textarea', 'input'); done.name = 'done_when'; done.id = 'field-' + serial + '-done_when';
    done.rows = 2; done.maxLength = 2000; done.placeholder = 'What should be true when it is done? Say it in your own words.';
    doneLabel.htmlFor = done.id; doneLabel.append(done); fields.append(doneLabel); inputs.done_when = done; doneWrap = doneLabel;
  }
  for (const field of (t ? ['owner', 'due', 'note', 'done_when'] : [])) {
    const label = el('label', '', field === 'done_when' ? 'What should be true when it is done?' : field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
    const input = el(['note', 'done_when'].includes(field) ? 'textarea' : 'input', 'input');
    input.name = field; input.id = 'field-' + serial + '-' + field;
    if (!['note', 'done_when'].includes(field)) input.type = 'text';
    if (field === 'done_when') {
      input.rows = 4; input.maxLength = 2000;
      input.placeholder = 'Optional. Say it in your own words, the helper turns it into steps.';
    }
    if (field === 'due') {
      input.readOnly = true; input.placeholder = 'Pick a day';
      input.addEventListener('click', () => pickDate(input, input.value.replace(' ', 'T'), v => { if (v !== null) input.value = v.replace('T', ' '); }, true));  // shown as "2026-11-15 18:30", saved the same way (the core takes both)
      input.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
    }
    if (field === 'title') { input.required = true; input.maxLength = 200; }
    input.value = field === 'due' ? String(t?.[field] || '').replace('T', ' ') : t?.[field] || '';
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
    if (doneWrap && typeof fields.insertBefore === 'function' && doneWrap.parentNode === fields) fields.insertBefore(planLabel, doneWrap); else fields.append(planLabel);
  }
  const plain = t ? null : button('Save without starting', 'new-ticket-link', () => { startAfter = false; form.requestSubmit(); });
  if (plain) submit.addEventListener('click', () => { if (!created) startAfter = true; });  // a retry keeps the first choice
  actions.append(submit);
  if (plain) actions.prepend(plain);
  const startNow = async () => {
    if (t || !startAfter || !created) return;
    const run = await act('run.start', {ticket:created.id});
    window.orch.toast(run.ok ? 'Helper started' : 'The ticket was created, but the helper did not start: ' + run.text, run.ok ? 'ok' : 'error');
  };
  form.append(fields, error, reload, actions); d.append(form);
  let created = null, creationUnresolved = false, epicMade = false, epicProblems = [], togetherDone = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    await reading;
    if (closed) return;
    updateValidity();
    if (!t && inputs.text.required) error.textContent = EMPTY_TICKET;
    if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
    submit.disabled = true; error.textContent = ''; reload.hidden = true;
    // At once: the button that was pressed says what is happening (the helper start can take a while).
    const busy = t || startAfter || !plain ? submit : plain, busyText = busy.textContent;
    busy.textContent = t || !startAfter ? 'Saving…' : 'Starting…'; busy.setAttribute('aria-busy', 'true'); if (plain) plain.disabled = true;
    const idle = () => { busy.textContent = busyText; busy.removeAttribute?.('aria-busy'); busy.ariaBusy = null; if (plain) plain.disabled = false; };
    togetherDone = false; epicProblems = [];
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, key === 'done_when' ? input.value : input.value.trim()]));
    // A helper other than the default is kept as the ticket's owner. FOLLOW-UP: run.start takes no helper yet.
    if (!t) values.owner = helperSelect && helperSelect.value !== helpers[0].name ? 'agent:' + helperSelect.value : '';
    let result;
    if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, done_when:values.done_when, if_revision:t.revision});
    else {
      const fullText = inputs.text.value;
      if (fullText.length > 1500) {
        const combined = pastedText ? pastedText + '\n\n' + fullText : fullText;
        if (combined.length > 500000) { error.textContent = 'Text is over 500000 characters'; submit.disabled = false; idle(); return; }
        pastedText = combined; inputs.text.value = ''; grow(); updateAttachments();
      }
      const longText = pastedText, shortText = inputs.text.value;
      const base = ticketFromText(fullText, shortText, longText, files);
      values.title = base.title;
      // Every ticket is checked before anything is created, so a too-big one never leaves half the tickets behind.
      const bigStep = steps.findIndex(step => ticketTooBig(ticketStepArgs(step.input.value, step.files, 'x', values.owner) || {}));
      if (bigStep >= 0) { error.textContent = 'Ticket ' + (bigStep + 1) + ' is too big to send at once (over 4.9 MB). Remove a file or shorten its text.'; submit.disabled = false; idle(); return; }
      if (!created) {
        const previous = new Set(tickets().map(t => t.id));
        const planFirst = startAfter && !!planBox?.checked;
        const epic = epicMade = steps.some(step => ticketStepArgs(step.input.value, step.files, 'x'));
        const args = {...base, ...(planFirst ? {plan_first:true} : {}), ...(epic ? {epic:true} : {}), ...Object.fromEntries(['owner', 'due', 'done_when'].filter(k => values[k]).map(k => [k, values[k]]))};
        // ORCH-185: the epic and its tickets go in ONE request (all checked before anything is made) when they fit; a
        // bigger set (many pictures) still goes one ticket at a time, as before.
        const filled = epic ? steps.filter(step => ticketStepArgs(step.input.value, step.files, 'x')) : [];
        const bodies = filled.map(step => { const {parent, ...body} = ticketStepArgs(step.input.value, step.files, 'x', values.owner); return body; });
        if (epic && !ticketTooBig({...args, steps:bodies})) args.steps = bodies;
        if (ticketTooBig(args)) {
          error.textContent = 'This is too big to send at once (over 4.9 MB). Remove a file or shorten the text.' + (longText ? ' The long text is kept as the note.md chip.' : '');
          submit.disabled = false; idle(); return;
        }
        result = await act('ticket.new', args);  // one write, one history line
        if (result.ok) {
          if (result.state?.attached?.failed?.length) window.orch.toast('The ticket was created. Not saved: ' + result.state.attached.failed.join(', '), 'error');
          if (args.steps && result.state?.steps) {  // the tickets inside came with the same answer
            togetherDone = true;
            const {made = [], failed: notMade = []} = result.state.steps;
            for (const m of made) { filled[m.index]?.remove.click(); if (m.attached?.failed?.length) window.orch.toast('Ticket ' + (m.index + 1) + ' was created. Not saved: ' + m.attached.failed.join(', '), 'error'); }
            if (notMade.length) epicProblems = notMade.map(f => 'Ticket ' + (f.index + 1) + ': ' + window.DashHelpers.scrubText(f.message));
          }
          // The reply names the new ticket; the title match is only for an older server without that.
          const newId = result.state?.created?.id || result.state?.attached?.id;
          created = newId ? tickets().find(t => t.id === newId) : null;
          if (!created) created = tickets().filter(t => t.title === values.title && !previous.has(t.id)).sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))[0];
          if (!created) {
            creationUnresolved = true;
            result = {ok:false, status:0, text:'The ticket was created, but could not be found in the reply. Close this dialog and reload before trying again.'};
          }
        }
      } else result = {ok:true};
      // The epic's tickets, one each inside it, in order. One that was made leaves the list, so pressing the button
      // again only sends the ones that failed.
      if (result.ok && created) {
        const failed = [...epicProblems];
        for (const step of togetherDone ? [] : [...steps]) {
          const args = ticketStepArgs(step.input.value, step.files, created.id, values.owner);
          if (!args) continue;
          const made = await act('ticket.new', args);
          if (made.ok) {
            if (made.state?.attached?.failed?.length) window.orch.toast('Ticket ' + (steps.indexOf(step) + 1) + ' was created. Not saved: ' + made.state.attached.failed.join(', '), 'error');
            step.remove.click();
          } else failed.push('Ticket ' + (steps.indexOf(step) + 1) + ': ' + window.DashHelpers.scrubText(made.text));
        }
        if (failed.length) result = {ok:false, status:0, text:'The epic was created, but not every ticket in it. ' + failed.join(' ') + ' Press the button again to send the rest.'};
      }
      if (result.ok && created) {
        sent = true;
        window.orch.toast(startAfter ? (epicMade ? 'Epic created' : 'Ticket created') : 'Saved. The ' + (epicMade ? 'epic' : 'ticket') + ' is open; start it when you are ready.', 'ok');
        window.orch.close(d);
        await startNow();
        if (typeof href === 'function') location.hash = href(created.id);  // Start and Save without starting both open the new ticket
        return;
      }
    }
    submit.disabled = creationUnresolved; idle();
    if (!result.ok) {
      error.textContent = window.DashHelpers.scrubText(result.text);
      reload.hidden = !(t && result.status === 409);
      if (created) { inputs.text.disabled = true; submit.textContent = steps.length ? 'Send the rest' : 'Save details'; if (plain) plain.hidden = true; }
      return;
    }
    window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
    await window.orch.close(d);
    await startNow();
  });
  if (!t && ticketDraft) {
    const draft = ticketDraft;
    inputs.text.value = draft.text; pastedText = draft.pasted; inputs.done_when.value = draft.done;
    for (const text of draft.steps) { const step = d.newStep?.(); if (step) step.input.value = text; }
    updateAttachments(); updateValidity(); grow();
    const note = el('p', 'meta new-ticket-draft', 'Your unsent text from before is back. ');
    note.append(button('Discard', 'new-ticket-link', () => {
      ticketDraft = null; inputs.text.value = ''; inputs.done_when.value = ''; pastedText = ''; updateAttachments(); updateValidity(); grow(); note.remove();
    }));
    fields.prepend(note);
  }
  window.orch.open(d);
}
