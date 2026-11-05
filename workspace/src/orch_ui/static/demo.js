(function () {
  'use strict';
  const make = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const cases = [
    {label: 'Suggested answer', title: 'Send the report on Friday this week?', text: 'Task: Send the weekly report to the team leads.', options: [{text: 'No'}, {text: 'Yes', suggested: true}]},
    {label: 'Answered on another device', title: 'Include the draft invoices?', text: 'Task: Choose which invoices belong in the export.', options: [{text: 'Yes', suggested: true}, {text: 'No'}], result: {status: 409, other: {text: 'No', who: 'Marco', via: 'phone'}}},
    {label: 'Try again after an error', title: 'Save a copy of the report?', text: 'Task: Keep a copy with this week’s invoices.', options: [{text: 'Yes', suggested: true}, {text: 'No'}], result: {status: 503, message: 'Could not save your answer. Try again.'}},
    {label: 'Long answers', title: 'Who should receive the invoice summary?', text: 'Task: Share the export. Some invoices include private customer details.', options: [
      {text: 'Send only to the finance team, with customer details included for reconciliation.', suggested: true},
      {text: 'Share with all team leads, with customer names and email addresses removed.'},
      {text: 'Keep the summary here for now so I can review every invoice before sharing it.'}
    ]}
  ];
  cases.forEach((item, i) => {
    const wrapper = make('div', 'demo-case');
    const header = make('header');
    const reset = make('button', 'btn quiet', 'Reset');
    reset.type = 'button';
    reset.setAttribute('aria-label', 'Reset: ' + item.label);
    header.append(make('span', '', item.label), reset);
    const host = make('div');
    wrapper.append(header, host);
    document.getElementById('questions').append(wrapper);
    // A fresh state per reset also isolates any already-in-flight fake response.
    let controller;
    function mount() {
      controller = window.QuestionCard.mount(host, {ticket: 'demo-' + (i + 1), id: 'answer', title: item.title, text: item.text, options: item.options}, {
        send: () => new Promise(resolve => setTimeout(() => resolve(item.result || {status: 200, who: 'Marco', via: 'dashboard'}), 300))
      });
    }
    reset.addEventListener('click', () => { controller.destroy(); mount(); });
    mount();
  });
  const csv = 'Invoice,Customer,Amount CHF,Status\r\n' + [
    'INV-2041,Bäckerei Huber,1240.00,Paid',
    'INV-2042,Velo Meier AG,3980.50,Open',
    'INV-2043,Café Lindengarten,612.00,Paid',
    'INV-2044,Schreinerei Graf,8450.00,Overdue',
    'INV-2045,Praxis Dr. Kunz,1905.00,Open',
    'INV-2046,"Studio Nord, Zürich",720.00,Paid',
    'INV-2047,Buchladen West,430.00,Paid',
    'INV-2048,"Atelier ""Süd""",980.00,Open'
  ].join('\r\n');
  const proofs = [
    [{type: 'file', ref: 'out/invoice-export.csv', summary: '8 invoices · October'}, {csv}],
    [{type: 'file', ref: 'shots/export.png', summary: 'Export ready'}, {url: 'demo-image.svg'}],
    [{type: 'file', ref: 'report.html', summary: 'Weekly report'}, {url: 'demo-page.html'}],
    [{type: 'command', ref: 'python -m pytest tests/invoices', summary: '48 checks passed', text: 'Invoice export checks\n48 passed in 3.1 seconds\nCSV columns, quoted customer names and totals verified.'}, {}],
    [{type: 'note', ref: 'review/export', summary: 'Checked by Marco', text: 'The exported invoices match the October ledger. Customer names and amounts look right.'}, {}],
    [{type: 'file', ref: 'archive/september.csv', summary: 'September invoices'}, {missing: true}]
  ];
  proofs.forEach(([ev, ctx], i) => {
    const card = make('article', 'card proof-card');
    card.id = 'proof-' + i;
    card.tabIndex = -1;
    card.append(make('h3', '', ev.summary));
    const view = make('div');
    // These renderers escape every dynamic value before producing HTML.
    view.innerHTML = window.Evidence.full(ev, ctx);
    card.append(view);
    document.getElementById('proof-views').append(card);
    const template = document.createElement('template');
    template.innerHTML = window.Evidence.chip(ev, ctx);
    const chip = template.content.firstElementChild;
    chip.setAttribute('aria-controls', card.id);
    chip.addEventListener('click', () => { card.scrollIntoView({block: 'start'}); card.focus({preventScroll: true}); });
    document.getElementById('proof-chips').append(chip);
  });
})();
