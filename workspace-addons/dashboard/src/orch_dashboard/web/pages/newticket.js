'use strict';
// New ticket / edit ticket dialog.
function ticketForm(t) {
  const {d, actions} = dialog(t ? 'Edit ticket' : 'New ticket', t ? 'sheet' : 'dialog', t ? 'ticket-meta' : '');
  const form = el('form'), fields = el('div', 'form-fields'), inputs = {};
  for (const field of (t ? ['owner', 'due', 'note'] : ['title', 'owner', 'due', 'note'])) {
    const label = el('label', '', field.charAt(0).toUpperCase() + field.slice(1) + (field === 'title' ? '' : ' (optional)'));
    const input = el(field === 'note' ? 'textarea' : 'input', 'input');
    input.name = field; input.id = 'field-' + serial + '-' + field;
    if (field !== 'note') input.type = 'text';
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
  const submit = el('button', 'btn primary', t ? 'Save changes' : 'Create & Start'); submit.type = 'submit';
  let startAfter = !t;
  const plain = t ? null : el('button', 'btn outline', 'Create');
  if (plain) { plain.type = 'button'; plain.addEventListener('click', () => { startAfter = false; form.requestSubmit(); }); submit.addEventListener('click', () => { startAfter = true; }); }
  actions.append(...(plain ? [plain, submit] : [submit]));
  const startNow = async () => {
    if (t || !startAfter || !created) return;
    const run = await act('run.start', {ticket:created.id});
    window.orch.toast(run.ok ? 'Agent started' : 'The ticket was created, but the agent did not start: ' + run.text, run.ok ? 'ok' : 'error');
  };
  form.append(fields, error, reload, actions); d.append(form);
  let created = null, creationUnresolved = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity() || submit.disabled || creationUnresolved) return;
    submit.disabled = true; error.textContent = ''; reload.hidden = true;
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]));
    let result;
    if (t) result = await act('ticket.edit', {ticket:t.id, owner:values.owner, due:values.due, note:values.note, if_revision:t.revision});
    else {
      if (!created) {
        const previous = new Set(tickets().map(t => t.id));
        result = await act('ticket.new', {title:values.title, ...Object.fromEntries(['owner', 'due', 'note'].filter(k => values[k]).map(k => [k, values[k]]))});  // one write, one history line
        if (result.ok) {
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
      error.textContent = result.text + (result.status === 409 ? ' Reload the ticket before trying again.' : '');
      reload.hidden = !(t && result.status === 409);
      if (created) { inputs.title.disabled = true; submit.textContent = 'Save details'; if (plain) plain.hidden = true; }
      return;
    }
    window.orch.toast(t ? 'Ticket updated' : 'Ticket created', 'ok');
    await window.orch.close(d);
    await startNow();
  });
  window.orch.open(d);
}
