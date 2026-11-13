/* Ticket sections and the shared file-viewer pattern, using this ticket's evidence. */
(() => {
  const page = location.pathname.split('/').pop();
  const kind = page.includes('opus') ? 'review' : page.replace('ticket-', '').replace('.html', '');
  const files = {
    review: {name:'Survey results', meta:'Page · 12:26 today', path:'assets/survey-results.html', tasks:[1]},
    working: {name:'Newsletter plan', meta:'Markdown · 12:26 today', path:'assets/newsletter-plan.md', tasks:[0,1]},
    change: {name:'New price list', meta:'Table · 12:26 today · Before your request', path:'assets/price-list.csv', tasks:[0,1]}
  };
  const notes = {
    review:['112 of 112 answers read · reported by the helper.', 'The one-page summary was finished at 12:26. Check the page before accepting.'],
    working:['The plan lists three stories: new opening hours, the spring workshop and a customer spotlight.', 'The short intro task was completed at 12:26. No separate note was attached.', 'Skipped: we have no new photos this month.', 'No evidence yet. The test mail task is unfinished; the helper stopped before finishing.'],
    change:['The table compares old and new prices for three items.', 'The shared sheet was updated at 12:26, before the shipping-cost request.', 'You asked: “Please also add the shipping costs to the list.” Received at 12:28; no result yet.'],
    copy:['The sign was printed and hung by the door at 12:32.'],
    done:['Completion note: the page now says Sunday 9:00 – 13:00.']
  };
  let previewContent, taskNames = [];
  const el = (tag, cls, text) => {const n=document.createElement(tag); if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  const fileButton = () => {const b=el('button','btn outline sm','Preview '+files[kind].name);b.type='button';b.dataset.ticketPreview='';return b;};
  window.ticketRefresh = function(mode) {
    const root=document.querySelector('#ticket-loaded, #ticket');
    if(!root || root.querySelector('.ticket-tabs')) return;
    const header=root.querySelector('.ticket-heading, .t-head');
    let overview=root.querySelector('#story-loaded');
    if(!overview){overview=el('div','story');header.after(overview);while(overview.nextElementSibling)overview.append(overview.nextElementSibling);}
    overview.id='ticket-overview';
    // Keep the original state handler's lookup intact on the standard pages.
    if(root.id==='ticket-loaded')overview.id='story-loaded';
    const empty=mode==='empty';
    const rows=[...overview.querySelectorAll('.task-row, .task, .current-task')];
    taskNames=rows.map(r=>{const title=(r.querySelector('.task-title, .grow, .title, h3')||r).cloneNode(true);title.querySelectorAll('.task-note, .task-detail').forEach(n=>n.remove());return title.textContent.trim();});
    previewContent=overview.querySelector('.preview-body, .frame-box')?.cloneNode(true);
    previewContent?.querySelectorAll('a, .skeleton').forEach(n=>n.remove());
    const activity=overview.querySelector('.activity-list, #activity');
    const extraActivity=overview.querySelector('.more-activity, .more-history');
    const activityCount=(activity?.children.length||0)+(extraActivity?.querySelectorAll('li, p').length||0);
    const tabs=el('nav','ticket-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Ticket sections');header.after(tabs);
    const panels={Overview:overview};
    for(const name of ['Tasks','Files','Activity']) {
      const panel=el('section','ticket-tab-panel');panel.id='ticket-'+name.toLowerCase();panel.hidden=true;overview.after(panel);panels[name]=panel;
    }
    const counts={Tasks:empty?0:rows.length,Files:empty?0:files[kind]?1:0,Activity:empty?0:activityCount};
    Object.entries(panels).forEach(([name,panel],i)=>{
      const b=el('button','btn ghost',name+(name==='Overview'?'':' '+counts[name]));b.type='button';b.id='tab-'+name.toLowerCase();b.dataset.ticketTab=panel.id;b.setAttribute('role','tab');b.setAttribute('aria-controls',panel.id);b.setAttribute('aria-selected',String(i===0));b.tabIndex=i===0?0:-1;tabs.append(b);
      panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',b.id);panel.tabIndex=0;
    });
    panels.Tasks.append(el('h2','','Tasks'),el('p','muted','Open a task to see its notes, files and links.'));
    if(!empty)rows.forEach((row,i)=>{
      const detail=el('details','task-evidence');const summary=el('summary');const title=el('span','grow',taskNames[i]);const note=row.querySelector('.task-note');if(note)title.append(el('span','task-note meta',note.textContent));summary.append(title,el('span','meta',row.querySelector('.task-mark, .tick')?.textContent.trim()==='✓'?'Done':/Skipped|photos from the shop/.test(row.textContent)?'Skipped':'Working'));detail.append(summary);
      const body=el('div','evidence-body');body.append(el('h3','','Notes'),el('p','muted',notes[kind]?.[i]||'No notes attached yet.'),el('h3','','Files'));
      if(files[kind]?.tasks.includes(i))body.append(fileButton());else body.append(el('p','meta','No files attached to this task.'));
      body.append(el('h3','','Links'),el('p','meta','No separate links attached to this task.'));detail.append(body);panels.Tasks.append(detail);
    });
    if(!counts.Tasks)panels.Tasks.append(el('p','muted','No tasks yet. Tasks and their evidence will appear here when the work is planned.'));
    panels.Files.append(el('h2','','Files'));
    if(counts.Files){const f=files[kind];const card=el('article','card ticket-file');card.append(el('h3','',f.name),el('p','meta',f.meta),el('p','muted','Evidence for: '+f.tasks.map(i=>taskNames[i]).join(' · ')),fileButton());panels.Files.append(card);}else panels.Files.append(el('p','muted','No files attached. Completion notes appear with their tasks.'));
    const grid=el('a','btn ghost sm','Browse the full file grid ↗');grid.href='../previews/files.html';panels.Files.append(grid);
    panels.Activity.append(el('h2','','Activity'));
    if(!empty && activity){panels.Activity.append(activity.cloneNode(true));if(extraActivity)panels.Activity.append(extraActivity.cloneNode(true));panels.Activity.querySelectorAll('[id]').forEach(n=>n.removeAttribute('id'));}else panels.Activity.append(el('p','muted','No activity yet.'));
    // All entry points use the same viewer and the actual ticket file.
    overview.querySelectorAll('a[href="../previews/viewer.html"], .preview-expand, a[href="#open"]').forEach(a=>{a.dataset.ticketPreview='';a.href=files[kind]?.path||'#';});
    overview.querySelectorAll('a[href="#download"]').forEach(a=>{a.href=files[kind].path;a.download='';});
    overview.querySelectorAll('[data-copy]').forEach(b=>b.dataset.copy=files[kind]?.path||'');
  };
  const dialog=el('dialog','ticket-file-viewer');dialog.setAttribute('aria-labelledby','ticket-viewer-title');
  dialog.innerHTML='<header class="ticket-viewer-header"><div><h2 id="ticket-viewer-title"></h2><p class="meta" id="ticket-viewer-meta"></p></div><button class="btn outline sm" data-close-viewer autofocus>× Close <kbd>Esc</kbd></button></header><div class="ticket-viewer-actions"><a class="btn outline sm" data-original target="_blank" rel="noopener">Open in new tab ↗</a><a class="btn ghost sm" data-download download>Download</a><button class="btn ghost sm" data-viewer-copy>Copy link</button><span role="status" data-copy-status></span></div><div class="ticket-viewer-stage"></div>';
  document.body.append(dialog);let opener;
  dialog.querySelector('[data-close-viewer]').onclick=()=>dialog.close();
  document.addEventListener('click',async e=>{
    const tab=e.target.closest('[data-ticket-tab]');
    if(tab){const root=tab.closest('#ticket-loaded, #ticket');root.querySelectorAll('[data-ticket-tab]').forEach(b=>{const selected=b===tab;b.setAttribute('aria-selected',selected);b.tabIndex=selected?0:-1;document.getElementById(b.dataset.ticketTab).hidden=!selected||(b.textContent==='Overview'&&new URLSearchParams(location.search).get('state')==='empty'&&!!root.querySelector('#story-empty'));});const empty=root.querySelector('#story-empty');if(empty)empty.hidden=tab.textContent!=='Overview'||new URLSearchParams(location.search).get('state')!=='empty';return;}
    const trigger=e.target.closest('[data-ticket-preview]');
    if(trigger){e.preventDefault();opener=trigger;const f=files[kind];dialog.querySelector('h2').textContent=f.name;dialog.querySelector('#ticket-viewer-meta').textContent=f.meta;dialog.querySelector('[data-original]').href=f.path;dialog.querySelector('[data-download]').href=f.path;dialog.querySelector('[data-copy-status]').textContent='';const stage=dialog.querySelector('.ticket-viewer-stage');stage.replaceChildren();if(kind==='review'){const frame=el('iframe');frame.title=f.name;frame.setAttribute('sandbox','allow-same-origin');frame.src=f.path;frame.addEventListener('load',()=>frame.contentDocument?.addEventListener('keydown',event=>{if(event.key==='Escape')dialog.close();}));stage.append(frame);}else if(previewContent)stage.append(previewContent.cloneNode(true));dialog.showModal();}
    if(e.target.closest('[data-viewer-copy]')){const status=dialog.querySelector('[data-copy-status]');try{await navigator.clipboard.writeText(new URL(files[kind].path,location.href).href);status.textContent='Link copied';}catch{status.textContent='Copy this link: '+new URL(files[kind].path,location.href).href;}}
  });

  window.ticketRefresh(new URLSearchParams(location.search).get('state')||'loaded');
})();
