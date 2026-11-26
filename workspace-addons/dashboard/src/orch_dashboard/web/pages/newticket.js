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
  else { const kind = el('span', 'new-ticket-file-kind', (file.name.match(/\.([a-z0-9]{1,4})$/i)?.[1] || 'file').toUpperCase()); kind.setAttribute('aria-hidden', 'true'); body.append(kind); }  // ORCH-2162: MD, CSV, …
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
  // A one-sentence wish stays under "What was asked" too, not only a title (a short label such as "Fix login" is just the title).
  const note = short.length <= 1500 && (/[\r\n]/.test(short) || short.trim() !== title || short.trim().length > WISH_MIN) ? short : '';
  return {title, title_auto:titleAuto, ...(note ? {note} : {}), ...(longText ? {long_text:longText} : {}), ...(files.length ? {files:ticketSendFiles(files)} : {})};
}
// A ticket inside the epic: long text (over 1500 characters) is kept as note.md, like the main box; an empty one is skipped.
function ticketStepArgs(text, files, parent, owner) {
  if (!text.trim() && !files.length) return null;
  const long = text.length > 1500;
  return {...ticketFromText(text, long ? '' : text, long ? text : '', files), parent, ...(owner ? {owner} : {})};
}
const ticketTooBig = args => new Blob([JSON.stringify({op:'ticket.new', args})]).size > 139 * 1024 * 1024;  // the server takes 140 MB for a new ticket (MAX_BIG_BODY): 100 MB of files as base64 plus the text
// Helpers this workspace can really use (owner, 25 Nov: only the active ones, by name only): one entry per helper,
// the default first, never two with the same label. A helper not found on this computer is left out.
function ticketHelpers(settings) {
  const out = [], labels = new Set();
  const agents = (Array.isArray(settings?.agents) ? settings.agents : []).filter(a => a && typeof a.name === 'string' && a.found !== false && a.status !== 'not found');
  agents.sort((a, b) => (b.chosen === true) - (a.chosen === true));
  for (const a of agents) {
    if (out.some(h => h.name === a.name)) continue;
    const plain = String(a.label || a.name).replace(/^(agent|human):/, '');
    let label = plain.charAt(0).toUpperCase() + plain.slice(1);
    if (labels.has(label.toLowerCase())) label += ' (' + a.name + ')';
    labels.add(label.toLowerCase());
    out.push({name:a.name, label, chosen:a.chosen === true});
  }
  return out;
}
// ORCH-1037: New ticket is its own page (#new), not a window over another page. Every New ticket button goes there;
// Cancel goes back to the page it came from.
let newTicketFrom = '';
function openNewTicket() {
  if (typeof snapshot !== 'undefined' && snapshot) return;
  const here = (location.hash || '#home').split('?')[0];
  if (here === '#new') { document.querySelector('.new-ticket-page .new-ticket-text')?.focus(); return; }
  newTicketFrom = location.hash || '#home';
  location.hash = '#new';
}
function newTicketPage() {
  // render() reconciles main with the CHILDREN of what a page returns, so the column goes in a fragment
  return fragment(h('div', {className:'form-page new-ticket-page', 'data-key':'new-ticket-page'}, h('div', {'data-new-ticket-host':'', 'data-key':'new-ticket-host'})));
}
// Built once per visit (mounts skip reconcile, so typing is never redrawn); leaving the page keeps an unsent draft.
function mountNewTicket(main) {
  main.querySelectorAll('[data-new-ticket-host]').forEach(host => { if (!mounts.has(host)) mounts.set(host, ticketForm(null, {host})); });
}
// The page's stand-in for dialog(): a card with the same title and actions, closed by leaving the page.
function ticketFormPage(host) {
  const d = el('section', 'new-ticket new-ticket-on-page');
  const title = el('h1', 'new-ticket-title', 'New ticket'); title.id = 'new-ticket-title-' + (++serial);
  d.setAttribute('aria-labelledby', title.id); d.append(title);
  const actions = el('div', 'actions');
  const back = () => { const to = newTicketFrom && newTicketFrom.split('?')[0] !== '#new' ? newTicketFrom : '#home'; newTicketFrom = ''; location.hash = to; };
  actions.append(button('Cancel', 'ghost', back));
  let done = false;
  const close = () => { if (done) return; done = true; d.dispatchEvent(new Event('close')); };
  host.append(d);
  return {d, actions, close};
}
// The due date uses the shared date picker (kit/date.js: UI.date); a hidden input keeps the chosen day for the form.
// New ticket (its own page, or a window where no page host is given) / edit ticket (a sheet).
function ticketForm(t, {host = null} = {}) {
  const onPage = !t && !!host;
  const {d, actions, close: pageClose} = onPage ? ticketFormPage(host) : dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : 'new-ticket');
  // ORCH-2162 (owner chose option A, 25 Nov): two columns on a wide screen. Left: the request, its files and parts,
  // then Save ticket and Start now side by side, each with one line under it. Right: the helper, then the optional
  // settings. On a phone one column: request, helper, the two buttons, then the optional settings.
  const form = el('form', t ? '' : 'new-ticket-form'), fields = el('div', t ? 'form-fields' : 'form-fields new-ticket-main'), more = t ? fields : el('section', 'form-fields new-ticket-more'), inputs = {};
  if (!t) { if (!onPage) d.className = (d.className ? d.className + ' ' : '') + 'new-ticket ui-bottom-close'; d.querySelector?.(onPage ? 'h1' : 'h2')?.after?.(el('p', 'meta new-ticket-sub', 'One sentence is enough. Everything else is optional.')); }
  // The window closes with its Close button, Esc and a click on the backdrop (kit/overlay.js); dialog() puts the cursor back where it was.
  let helpers = [], helperBox = null, sayWhat = () => {};
  const helperRadios = [];
  const helperChoice = () => helperRadios.find(r => r.checked)?.value || helpers[0]?.name || '';
  let planBox = null, planLabel = null, reviewBox = null;
  const reviewDefault = !(typeof state !== 'undefined' && state && state.settings?.auto_reviewer_on === true);
  let pastedText = '', files = [], reading = Promise.resolve(), closed = false;
  let updateAttachments = () => {}, grow = () => {}, readInto = null;
  const steps = [];  // ORCH-14: an epic. Each entry becomes its own ticket inside the new one, with its own text and files
  const updateValidity = () => {
    if (t) return;
    const empty = !inputs.text.value.trim() && !pastedText && !files.length;
    inputs.text.required = empty;
    inputs.text.setCustomValidity(empty ? EMPTY_TICKET : '');
  };
  let sent = false, noHelper = false;
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
    input.placeholder = 'What should the helper do? A sentence or a long text; it is split into tasks.';
    // Grows with the text (about 4 lines at first); CSSOM height, no style attribute.
    grow = () => { if (!input.style) return; input.style.height = 'auto'; if (input.scrollHeight) input.style.height = Math.min(input.scrollHeight + 2, 480) + 'px'; };
    input.addEventListener('input', updateValidity); input.addEventListener('input', grow);
    label.htmlFor = input.id; label.append(input); inputs.text = input;
    fields.append(label);
    // ORCH-2162 (owner chose option A): the files sit in a row right under the request, with Add files and Split
    // into parts as two plain buttons beside them; drops anywhere on the form land here.
    const picker = el('input'); picker.type = 'file'; picker.multiple = true; picker.hidden = true;
    picker.accept = '.txt,.md,.csv,.tsv,.json,.log,.yml,.yaml,.toml,.ini,.png,.jpg,.jpeg,.gif,.webp';
    const attach = button('＋ Add files', 'btn outline sm new-ticket-attach', () => picker.click());
    const fileError = el('p', 'bad new-ticket-file-error'); fileError.setAttribute('role', 'alert');
    const chips = el('ul', 'new-ticket-files'); chips.setAttribute('aria-label', 'Added files');
    const fileBar = el('div', 'new-ticket-file-bar');
    const status = el('p', 'meta new-ticket-reading'); status.setAttribute('role', 'status');
    const hint = el('p', 'meta new-ticket-file-hint', 'or drop or paste files and pictures on this page · up to 25 MB each');
    const help = el('p', 'meta new-ticket-help', 'Long text is kept as a file. The helper writes the title and a short description.');
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
    // Reads picked, dropped or pasted files into a list (the ticket's own or a part's), one after the other: the
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
    // Epic: several tickets at once (owner, ORCH-14). The text above is the epic; each part below becomes its own
    // ticket inside it (the epic page lists them), with its own text, screenshots and files. One word on screen: part.
    const stepList = el('div', 'new-ticket-steps');
    const stepHelp = el('p', 'meta new-ticket-help', 'Each part becomes its own ticket inside this one, with its own files.');
    const stepFoot = el('div', 'new-ticket-step-foot');
    const renumber = () => {
      steps.forEach((step, i) => {
        step.head.textContent = 'Part ' + (i + 1);
        step.input.setAttribute('aria-label', 'Part ' + (i + 1) + ': what needs doing?');
        step.remove.setAttribute('aria-label', 'Remove part ' + (i + 1));
        step.attach.setAttribute('aria-label', 'Add files to part ' + (i + 1));
      });
      stepHelp.hidden = !steps.length;
      addStep.textContent = steps.length ? '＋ Add another part' : '＋ Split into parts';
      // the first press sits beside Add files; once there are parts, "Add another part" follows the last one
      (steps.length ? stepFoot : fileBar).append(addStep);
    };
    const newStep = () => {
      const step = {files:[]}, box = el('div', 'new-ticket-step'), top = el('div', 'new-ticket-step-row');
      step.head = el('span', 'meta new-ticket-step-name');
      step.remove = button('Remove', 'btn ghost sm', () => {
        for (const file of step.files) if (file.url) URL.revokeObjectURL(file.url);
        steps.splice(steps.indexOf(step), 1); box.remove(); renumber();
      });
      const text = el('textarea', 'input'); text.name = 'step'; text.rows = 1; text.maxLength = 500000;
      text.placeholder = 'What needs doing in this part?';
      const stepPicker = el('input'); stepPicker.type = 'file'; stepPicker.multiple = true; stepPicker.hidden = true; stepPicker.accept = picker.accept;
      step.attach = button('＋ Files', 'btn ghost sm new-ticket-step-files', () => stepPicker.click());
      top.append(step.head, text, step.attach, step.remove);
      const stepError = el('p', 'bad new-ticket-file-error'); stepError.setAttribute('role', 'alert');
      const stepChips = el('ul', 'new-ticket-files'); stepChips.setAttribute('aria-label', 'Files for this part');
      const draw = () => stepChips.replaceChildren(...step.files.map(file => ticketFileChip(file, () => {
        step.files.splice(step.files.indexOf(file), 1);
        if (file.url) URL.revokeObjectURL(file.url);
        draw();
      })));
      const add = incoming => readInto(incoming, step.files, stepError, draw);
      stepPicker.addEventListener('change', () => { add(Array.from(stepPicker.files)); stepPicker.value = ''; });
      box.addEventListener('drop', event => {  // a drop on a part is that part's, not the epic's
        if (!event.dataTransfer?.files.length) return;
        event.preventDefault(); event.stopPropagation?.(); add(Array.from(event.dataTransfer.files));
      });
      text.addEventListener('paste', event => {
        const pasted = window.UI?.pastedFiles?.(event) || [];
        if (pasted.length) { event.preventDefault(); add(pasted); }
      });
      box.append(top, stepPicker, stepError, stepChips);
      Object.assign(step, {box, input:text});
      steps.push(step); stepList.append(box); renumber(); text.focus();
      return step;
    };
    d.newStep = newStep;
    const addStep = button('', 'btn outline sm new-ticket-add-step', newStep);
    fileBar.append(chips, attach);
    fields.append(status, fileBar, picker, fileError, hint, help, stepHelp, stepList, stepFoot); updateAttachments(); renumber();
    // Helper (owner, 25 Nov): only the helpers this workspace really has, by name only (no "good at" lines). Several:
    // a short list to pick from; one: its name; one that is just called "Helper", or none: no box at all.
    helpers = ticketHelpers(typeof state !== 'undefined' && state ? state.settings : null);
    noHelper = helpers.length === 0;
    const noHelperRow = helpers.length === 1 && /^helper$/i.test(helpers[0].label);
    if (helpers.length && !noHelperRow) {
      helperBox = el('section', 'form-fields new-ticket-helper');
      helperBox.append(el('h2', 'new-ticket-side-title', 'Helper'));
      if (helpers.length > 1) {
        const list = el('div', 'sync-options new-ticket-helper-list'); list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', 'Helper');
        for (const one of helpers) {
          const row = el('label', 'new-ticket-helper-opt'), radio = el('input');
          radio.type = 'radio'; radio.name = 'helper'; radio.value = one.name; radio.checked = one === helpers[0];
          radio.addEventListener('change', () => sayWhat());
          row.append(radio, el('span', '', one.label));
          if (one.chosen) row.append(el('span', 'chip active def', 'Default'));
          list.append(row); helperRadios.push(radio);
        }
        helperBox.append(list);
      } else helperBox.append(el('p', 'new-ticket-helper-fixed', helpers[0].label));
    }
    const dueInput = el('input'); dueInput.type = 'hidden'; dueInput.name = 'due'; dueInput.id = 'field-' + serial + '-due-value'; inputs.due = dueInput;
    const dueToggle = el('button', 'btn outline new-ticket-date-toggle', '▦ No date'); dueToggle.type = 'button'; dueToggle.id = 'field-' + serial + '-due';
    const dueLabel = el('label', '', 'Due date'); dueLabel.htmlFor = dueToggle.id;
    const dueBox = el('div', 'new-ticket-due'); dueBox.append(dueLabel, dueToggle, dueInput);
    if (window.UI?.date) window.UI.date(dueInput, dueToggle, null, {time:true});
    // ORCH-424: ticked unless the Auto Reviewer is on (owner: it then checks every new ticket unless they tick it).
    const reviewLabel = el('label', 'new-ticket-check');
    reviewBox = el('input'); reviewBox.type = 'checkbox'; reviewBox.name = 'human_review'; reviewBox.checked = reviewDefault;
    reviewLabel.append(reviewBox, el('span', '', 'Human review needed'), el('span', 'meta', 'Nothing is accepted without you.'));
    // With a helper the plan choice sits under Start now (moved there below); with none it stays here, kept on the
    // ticket for when it starts.
    planLabel = el('label', 'new-ticket-check new-ticket-plan');
    planBox = el('input'); planBox.type = 'checkbox'; planBox.name = 'plan_first';
    planLabel.append(planBox, el('span', '', 'Show me the plan first'), el('span', 'meta', 'When it starts, the helper waits for your OK before work begins.'));
    more.append(el('h2', 'new-ticket-side-title', 'Optional'), reviewLabel, planLabel, dueBox);
    const doneLabel = el('label', '', 'Done when');
    const done = el('textarea', 'input new-ticket-text'); done.name = 'done_when'; done.id = 'field-' + serial + '-done_when';
    done.rows = 2; done.maxLength = 2000; done.placeholder = 'What should be true when it is done?';
    doneLabel.htmlFor = done.id; doneLabel.append(done); more.append(doneLabel); inputs.done_when = done;
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
  const submit = el('button', 'btn primary', t ? 'Save changes' : 'Save ticket'); submit.type = 'submit';
  // ORCH-1852: Save ticket is the main button (and Enter with Cmd or Ctrl); Start now is the explicit, outlined
  // choice beside it, offered only when this workspace has a helper. Nothing starts a helper without that press.
  const startBtn = t || noHelper ? null : button('Start now', 'outline new-ticket-save-btn', () => { if (!created) startAfter = true; form.requestSubmit(); });
  let startAfter = false;
  let go = null, startCell = null;
  if (!t) {
    // Save ticket and Start now side by side, each with one line under it saying what it does with the helper
    // picked on the right (owner, ORCH-2162 option A); Cancel last.
    const whoName = () => { const one = helpers.find(x => x.name === helperChoice()); return one && !/^helper$/i.test(one.label) ? one.label : 'Your helper'; };
    const prepares = !(typeof state !== 'undefined' && state && state.settings?.prepare_on_save === false);
    const saveLine = el('p', 'meta new-ticket-what'), startLine = el('p', 'meta new-ticket-what');
    saveLine.setAttribute('role', 'status');
    sayWhat = () => {
      if (!startBtn) return;
      const who = whoName();
      saveLine.textContent = prepares ? 'Goes to Tickets. ' + who + ' may prepare a short plan; no work starts.' : 'Goes to Tickets as you wrote it. Nothing starts.';
      startLine.textContent = who + ' begins at once. This may cost money.';
      planLabel.children[2].textContent = who + ' waits for your OK before work begins.';
    };
    if (!startBtn) {
      saveLine.textContent = 'Goes to Tickets. No helper is set up yet, so nothing starts. ';
      const setup = el('a', 'new-ticket-link', 'Set up a helper'); setup.href = '#settings/helper';
      saveLine.append(setup);
    }
    submit.addEventListener('click', () => { if (!created) startAfter = false; });  // a retry keeps the first choice
    submit.className = 'btn primary new-ticket-save-btn';
    const saveCell = el('div', 'new-ticket-choice'); saveCell.append(submit, saveLine);
    const buttons = el('div', 'new-ticket-buttons'); buttons.append(saveCell);
    if (startBtn) { startCell = el('div', 'new-ticket-choice'); startCell.append(startBtn, startLine, planLabel); buttons.append(startCell); }
    actions.className = 'actions new-ticket-cancel'; buttons.append(actions);
    go = el('div', 'new-ticket-go'); go.append(error, buttons);
    sayWhat();
  } else actions.append(submit);
  const startNow = async (quiet = false) => {
    // Save ticket prepares the ticket in the background (ORCH-738): no word on screen when it cannot
    // run now; the ticket then says "Not prepared yet" and Start still works.
    // An epic is not prepared: the person wrote its tickets already (core skips it too). With no helper there is
    // nobody to prepare it, so nothing is asked (the form says so, ORCH-1852).
    if (!t && !startAfter && created && !epicMade && startBtn) { Promise.resolve(act('run.start', {ticket:created.id, prepare:true}, {quiet:true})).catch(() => {}); return false; }
    if (t || !startAfter || !created) return false;
    const run = await act('run.start', {ticket:created.id});
    if (run.ok && quiet) return true;  // the starting animation already says it
    window.orch.toast(run.ok ? 'Helper started' : 'The ticket was created, but the helper did not start: ' + run.text, run.ok ? 'ok' : 'error');
    return run.ok;
  };
  if (t) form.append(fields, error, reload, actions);
  else {
    form.append(fields, ...(helperBox ? [helperBox] : []), go, more, reload);
    if (!helperBox) form.className += ' no-helper';  // the optional settings take the whole right column
  }
  d.append(form);
  const steps_ = () => steps.filter(step => step.input.value.trim() || step.files.length);
  let launch = null, launchAt = 0;
  const heads = () => [d.querySelector?.('h1'), d.querySelector?.('.new-ticket-sub')].filter(Boolean);  // the starting moment stands alone
  const pause = ms => new Promise(done => setTimeout(done, window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : ms));
  // Each step shows for a moment (at least ~0.45 s) so the move to the new ticket reads as one calm motion, not a jump.
  const atLeast = async ms => { const left = launchAt + ms - Date.now(); if (left > 0) await pause(left); };
  const launchInto = async made => {
    // left, or left and came back to a fresh form: this (closed) form never moves the person
    const leftPage = () => closed || (location.hash || '').split('?')[0] !== '#new';
    if (!launch) { await startNow(); if (!leftPage() && typeof href === 'function') location.hash = href(made.id); return; }
    await atLeast(450);
    let n = 1;
    launch.step(n);
    let started = false;
    if (startAfter) {
      started = await startNow(true);
      if (!started) launch.warn(n, 'Helper not started. Your ticket is saved.');  // at once: the toast says why
      await atLeast(1000); launch.step(++n);
    } else await startNow(true);  // Save ticket: the same quiet prepare request as in the window (ORCH-1852)
    await atLeast(startAfter ? 1400 : 900);
    launch.finish(started ? 'Started' : 'Saved');  // a helper that did not start says so in its toast
    await pause(380);
    if (leftPage()) { window.orch.toast((epicMade ? 'Epic' : 'Ticket') + ' created', 'ok'); return; }  // the person went elsewhere meanwhile
    newTicketFrom = '';
    if (typeof href === 'function') location.hash = href(made.id);
  };
  let created = null, newActIdOnce = null, creationUnresolved = false, epicMade = false, epicProblems = [], togetherDone = false;
  // Cmd+Enter (Ctrl+Enter) saves from any field, like the Save button.
  form.addEventListener('keydown', event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.defaultPrevented) { event.preventDefault(); if (!created) startAfter = false; form.requestSubmit(); } });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    await reading;
    if (closed) return;
    updateValidity();
    if (!t && inputs.text.required) error.textContent = EMPTY_TICKET;
    if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
    submit.disabled = true; error.textContent = ''; reload.hidden = true;
    // At once: the button that was pressed says what is happening (the helper start can take a while).
    const busy = startAfter && startBtn && !startBtn.hidden ? startBtn : submit, busyText = busy.textContent;
    busy.textContent = t || !startAfter ? 'Saving…' : 'Starting…'; busy.setAttribute('aria-busy', 'true'); if (startBtn) startBtn.disabled = true;
    const idle = () => { launch?.fail(); launch = null; form.hidden = false; heads().forEach(n => { n.hidden = false; }); busy.textContent = busyText; busy.removeAttribute?.('aria-busy'); busy.ariaBusy = null; if (startBtn) startBtn.disabled = creationUnresolved; };
    togetherDone = false; epicProblems = [];
    // On the page the form steps aside for the starting moment at once (ORCH-1037); a refusal brings it back.
    if (onPage && window.UI?.launch) {
      const labels = ['Creating the ' + (steps_().length ? 'tickets' : 'ticket'), ...(startAfter ? ['Starting your helper'] : []), 'Opening it'];
      launch = window.UI.launch({title:startAfter ? 'Starting…' : 'Saving…', sub:ticketTextTitle(inputs.text.value || pastedText || files[0]?.name || '', 80), steps:labels});
      launchAt = Date.now(); form.hidden = true; heads().forEach(n => { n.hidden = true; }); d.append(launch.el);
    }
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, key === 'done_when' ? input.value : input.value.trim()]));
    // A helper other than the default is kept as the ticket's owner. FOLLOW-UP: run.start takes no helper yet.
    if (!t) values.owner = helperRadios.length && helperChoice() !== helpers[0].name ? 'agent:' + helperChoice() : '';
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
      // ORCH-156: an empty ticket box is refused with a plain message (it used to drop out silently, and an epic
      // with only empty boxes was saved as a plain ticket with no epic mark).
      const emptyStep = steps.findIndex(step => !ticketStepArgs(step.input.value, step.files, 'x'));
      if (emptyStep >= 0) {
        error.textContent = 'Part ' + (emptyStep + 1) + ' is empty. Write what needs doing in it, or remove it.';
        steps[emptyStep].input.focus(); submit.disabled = false; idle(); return;
      }
      // Every ticket is checked before anything is created, so a too-big one never leaves half the tickets behind.
      const bigStep = steps.findIndex(step => ticketTooBig(ticketStepArgs(step.input.value, step.files, 'x', values.owner) || {}));
      if (bigStep >= 0) { error.textContent = 'Part ' + (bigStep + 1) + ' is too big to send at once (over 139 MB). Remove a file or shorten its text.'; submit.disabled = false; idle(); return; }
      if (!created) {
        const previous = new Set(tickets().map(t => t.id));
        const planFirst = (startAfter || !startBtn) && !!planBox?.checked;
        const epic = epicMade = steps.some(step => ticketStepArgs(step.input.value, step.files, 'x'));
        const args = {...base, ...(planFirst ? {plan_first:true} : {}), ...(epic ? {epic:true} : {}), ...(reviewBox && reviewBox.checked !== reviewDefault ? {human_review:reviewBox.checked} : {}), ...Object.fromEntries(['owner', 'due', 'done_when'].filter(k => values[k]).map(k => [k, values[k]]))};
        // ORCH-185: the epic and its tickets go in ONE request (all checked before anything is made) when they fit; a
        // bigger set (many pictures) still goes one ticket at a time, as before.
        const filled = epic ? steps.filter(step => ticketStepArgs(step.input.value, step.files, 'x')) : [];
        const bodies = filled.map(step => { const {parent, ...body} = ticketStepArgs(step.input.value, step.files, 'x', values.owner); return body; });
        if (epic && !ticketTooBig({...args, steps:bodies})) args.steps = bodies;
        if (ticketTooBig(args)) {
          error.textContent = 'This is too big to send at once (over 139 MB). Remove a file or shorten the text.' + (longText ? ' The long text is kept as the note.md chip.' : '');
          submit.disabled = false; idle(); return;
        }
        // One id for this ticket until it is made (ORCH-580): a Retry after a lost answer, or a second press, gets
        // the ticket that was made instead of a second one.
        newActIdOnce = newActIdOnce || window.orchActId?.();
        result = await act('ticket.new', args, {id:newActIdOnce});  // one write, one history line
        if (result.ok) {
          if (result.state?.attached?.failed?.length) window.orch.toast('The ticket was created. Not saved: ' + result.state.attached.failed.join(', '), 'error');
          if (args.steps && result.state?.steps) {  // the tickets inside came with the same answer
            togetherDone = true;
            const {made = [], failed: notMade = []} = result.state.steps;
            for (const m of made) { filled[m.index]?.remove.click(); if (m.attached?.failed?.length) window.orch.toast('Part ' + (m.index + 1) + ' was created. Not saved: ' + m.attached.failed.join(', '), 'error'); }
            if (notMade.length) epicProblems = notMade.map(f => 'Part ' + (f.index + 1) + ': ' + window.DashHelpers.scrubText(f.message));
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
          if (reviewBox && reviewBox.checked !== reviewDefault) args.human_review = reviewBox.checked;  // ORCH-424: like the epic above
          step.actId = step.actId || window.orchActId?.();  // the same id when the button is pressed again
          const made = await act('ticket.new', args, {id:step.actId});
          if (made.ok) {
            if (made.state?.attached?.failed?.length) window.orch.toast('Part ' + (steps.indexOf(step) + 1) + ' was created. Not saved: ' + made.state.attached.failed.join(', '), 'error');
            step.remove.click();
          } else failed.push('Part ' + (steps.indexOf(step) + 1) + ': ' + window.DashHelpers.scrubText(made.text));
        }
        if (failed.length) result = {ok:false, status:0, text:'The ticket was created, but not all of its parts. ' + failed.join(' ') + ' Press the button again to send the rest.'};
      }
      if (result.ok && created) {
        sent = true;
        if (onPage) { await launchInto(created); return; }
        window.orch.toast(startAfter ? (epicMade ? 'Ticket and its parts created' : 'Ticket created') : 'Saved. The ' + (epicMade ? 'ticket and its parts are' : 'ticket is') + ' open; start it when you are ready.', 'ok');
        window.orch.close(d);
        await startNow();
        if (typeof href === 'function') location.hash = href(created.id);  // Start now and Save ticket both open the new ticket
        return;
      }
    }
    submit.disabled = creationUnresolved; idle();
    if (!result.ok) {
      error.textContent = window.DashHelpers.scrubText(result.text);
      reload.hidden = !(t && result.status === 409);
      if (created) { inputs.text.disabled = true; submit.textContent = steps.length ? 'Send the rest' : 'Save details'; if (startBtn) { startBtn.hidden = true; startCell.hidden = true; } }
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
  if (onPage) {
    inputs.text.focus({preventScroll:true});
    return {destroy() { pageClose(); }};
  }
  window.orch.open(d);
}
