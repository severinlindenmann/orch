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
    working:['The plan lists three stories: new opening hours, the spring workshop and a customer spotlight.', 'The short intro task was completed at 12:26. No separate note was attached.', "Won't do: we have no new photos this month.", 'No evidence yet. The test mail task is unfinished; the helper stopped before finishing.'],
    change:['The table compares old and new prices for three items.', 'The shared sheet was updated at 12:26, before the shipping-cost request.', 'You asked: “Please also add the shipping costs to the list.” Received at 12:28; no result yet.'],
    copy:['The sign was printed and hung by the door at 12:32.'],
    done:['Completion note: the page now says Sunday 9:00 – 13:00.']
  };
  // W-030 / O-09 (owner, 28 Nov): the files beside the one that shows itself are rows: a data file and the presentation itself
  const extra = {review:[{name:'survey-answers.json', kind:'Code', size:'4 KB', when:'12:25'}, {name:'survey-deck.pptx', kind:'Presentation', size:'48 KB', when:'12:26'}]};
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
    const activityCount=(activity?.children.length||0)+(extraActivity?[...extraActivity.querySelectorAll('p.meta')].filter(p=>/·/.test(p.textContent)).length:0);
    const mine=kind==='change'&&!empty?1:0;  // the change page has a file you attached
    const tabs=el('nav','ticket-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Ticket sections');header.after(tabs);
    const panels={Overview:overview};
    for(const name of ['Tasks','Files','Activity']) {
      const panel=el('section','ticket-tab-panel stack');panel.id='ticket-'+name.toLowerCase();panel.hidden=true;overview.after(panel);panels[name]=panel;
    }
    const more=empty?[]:(extra[kind]||[]);
    const counts={Tasks:empty?0:rows.length,Files:empty?0:(files[kind]?1:0)+mine+more.length,Activity:empty?0:activityCount};
    Object.entries(panels).forEach(([name,panel],i)=>{
      const b=el('button','btn ghost',name+(name==='Overview'?'':' '+counts[name]));b.type='button';b.id='tab-'+name.toLowerCase();b.dataset.ticketTab=panel.id;b.setAttribute('role','tab');b.setAttribute('aria-controls',panel.id);b.setAttribute('aria-selected',String(i===0));b.tabIndex=i===0?0:-1;tabs.append(b);
      panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',b.id);panel.tabIndex=0;
    });
    // Draft E (ORCH-778): one head line (one step per task, count, Add a task), then each task with what came out.
    const state=r=>r.classList.contains('current-task')?'doing':r.querySelector('.task-mark, .tick')?.textContent.trim()==='✓'?'done':/Won't do|Skipped|photos from the shop/.test(r.textContent)?'skipped':'';
    const states=empty?[]:rows.map(state), doneN=states.filter(x=>x==='done').length,skipN=states.filter(x=>x==='skipped').length;
    const head=el('div','tab-head');
    if(states.length){const bar=el('div','progress-steps');bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','Tasks done');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax',String(states.length-skipN));bar.setAttribute('aria-valuenow',String(doneN));states.forEach(x=>bar.append(el('span',x)));head.append(bar);}
    head.append(el('strong','',states.length?doneN+' of '+(states.length-skipN)+' tasks done':'No tasks yet.'));if(skipN)head.append(el('span','meta',skipN+" won't do"));
    const addBtn=el('button','btn ghost sm','+ Add a task');addBtn.type='button';
    const addForm=el('form','row add-task');addForm.hidden=!!states.length||kind==='done';const addIn=el('input','input');addIn.placeholder='New task';addIn.setAttribute('aria-label','Add a task');const addGo=el('button','btn outline sm','Add');addForm.append(addIn,addGo);addForm.onsubmit=e=>e.preventDefault();
    addBtn.onclick=()=>{addForm.hidden=false;addIn.focus();};
    if(states.length&&kind!=='done')head.append(addBtn);
    panels.Tasks.append(head,addForm);
    // O-12 (owner, 28 Nov): the one compact task list lives here: a mark, the title, one grey line of evidence, the state word.
    if(states.length){const list=el('div','task-list tasks-list');rows.forEach((row,i)=>{
      const r=el('div','task-row');const box=el('span','grow');box.append(el('span',states[i]==='skipped'?'task-wont':'',taskNames[i]));
      const line=states[i]==='done'?((notes[kind]?.[i]||'').replace(/^No evidence yet.*$/,'')||'12:26 · Helper'):states[i]==='doing'?'The helper is on it.':states[i]==='skipped'?(notes[kind]?.[i]||"Won't do."):'';
      if(line)box.append(el('span','task-note meta',line));
      if(states[i]==='done'&&files[kind]?.tasks.includes(i))box.append(fileButton());
      r.append(el('span','task-mark'+(states[i]==='done'?' good':states[i]==='doing'?' working':''),states[i]==='done'?'✓':states[i]==='doing'?'◉':states[i]==='skipped'?'–':'○'),box,el('span','meta task-word',{done:'Done',doing:'Working',skipped:"Won't do"}[states[i]]||'To do'));list.append(r);});
      panels.Tasks.append(list);}
    // Draft E: All / Helper / You with counts when both kinds are there (the change page has a file you attached).
    const helperFiles=counts.Files-mine;
    if(helperFiles&&mine){const seg=el('div','segmented');seg.setAttribute('role','group');seg.setAttribute('aria-label','Who added it');
      [['All',counts.Files],['Helper',helperFiles],['You',mine]].forEach(([w,n],j)=>{const b=el('button','btn',w+' ');b.type='button';b.setAttribute('aria-pressed',String(j===0));b.append(el('span','seg-count',String(n)));b.onclick=()=>{seg.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));panels.Files.querySelectorAll('[data-who]').forEach(c=>c.hidden=w!=='All'&&c.dataset.who!==w);};seg.append(b);});
      const fh=el('div','tab-head');fh.append(seg);panels.Files.append(fh);}
    // O-10 (owner chose B, 28 Nov): a compact list like a file explorer (the master's file list): name with tags, kind,
    // size, date; the column heads sort; a click on a row opens the file viewer. No tiles, no preview pane.
    if(helperFiles){const f=files[kind];
      const listed=[{name:f.name,kind:f.meta.split(' · ')[0],size:'12 KB',when:'12:26',tag:f.tasks.length?'Evidence for task '+(f.tasks[f.tasks.length-1]+1):'Result',who:'Helper',opens:true},
        ...more.map(x=>({...x,tag:'Result',who:'Helper'})),...(mine?[{name:'Shipping costs.png',kind:'Picture',size:'210 KB',when:'12:28',tag:'Added by you',who:'You'}]:[])];
      const mid=el('div','files-mid'),head=el('div','files-head'),rowsBox=el('div','files-list');
      const draw=()=>{rowsBox.replaceChildren(...listed.map(x=>{const r=el('div','files-row');r.setAttribute('role','button');r.tabIndex=0;r.dataset.who=x.who;if(x.opens)r.dataset.ticketPreview='';
        const nm=el('div','files-name'),title=el('span','',x.name);title.append(el('span','tag',x.tag));nm.append(title,el('span','sub phone',[x.kind,x.size,x.when].join(' · ')));
        r.append(nm,el('span','kindcol cut',x.kind),el('span','num',x.size),el('span','cut',x.when),el('span'));
        r.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();r.click();}};return r;}));};
      let sorted='changed',dir=-1;
      [['name','Name',''],['kind','Kind','kindcol'],['size','Size',''],['changed','Changed','']].forEach(([key,label,cls])=>{const b=el('button',cls,label);b.type='button';b.setAttribute('aria-sort',key===sorted?'descending':'none');b.setAttribute('aria-label','Sort by '+label.toLowerCase());const c=el('span','chev');c.setAttribute('aria-hidden','true');b.append(c);
        b.onclick=()=>{dir=sorted===key?-dir:(key==='changed'||key==='size'?-1:1);sorted=key;const val=x=>key==='name'?x.name:key==='kind'?x.kind:key==='size'?parseInt(x.size,10):x.when;listed.sort((a,z)=>dir*(val(a)>val(z)?1:val(a)<val(z)?-1:0));head.querySelectorAll('button').forEach(o=>o.setAttribute('aria-sort',o===b?(dir>0?'ascending':'descending'):'none'));draw();};head.append(b);});
      head.append(el('span'));draw();mid.append(head,rowsBox);panels.Files.append(mid);
    }else panels.Files.append(el('p','muted','No files attached yet. Files your helper attaches appear here.'));
    // Draft E: the master segmented filter with counts; a Phone tag on what came from the phone.
    if(!empty && activity){const list=activity.cloneNode(true);if(extraActivity)list.append(...[...extraActivity.querySelectorAll('p.meta')].filter(p=>/·/.test(p.textContent)).map(p=>{const d=el('div');const [t,...rest]=p.textContent.split(' · ');d.append(el('time','',t),el('span','',rest.join(' · ')));return d;}));list.removeAttribute('id');
      const who=d=>/^(You|Anna|Ben)\b/.test(d.textContent.replace(/^\s*\d+:\d+\s*/,''))?'People':/^Helper\b/.test(d.textContent.replace(/^\s*\d+:\d+\s*/,''))?'Helper':'';
      const items=[...list.children];items.forEach(d=>{d.dataset.who=who(d);if(/phone/i.test(d.textContent)){const tag=el('span','tag','Phone');d.querySelector('span')?.append(' ',tag);}});
      const seg=el('div','segmented');seg.setAttribute('role','group');seg.setAttribute('aria-label','Show');
      ['All','People','Helper'].forEach((w,j)=>{const n=items.filter(d=>w==='All'||d.dataset.who===w).length;const b=el('button','btn',w+' ');b.type='button';b.setAttribute('aria-pressed',String(j===0));b.append(el('span','seg-count',String(n)));b.onclick=()=>{seg.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));items.forEach(d=>d.hidden=w!=='All'&&d.dataset.who!==w);};seg.append(b);});
      const ah=el('div','tab-head');ah.append(seg);panels.Activity.append(ah,list);}else panels.Activity.append(el('p','muted','No activity yet.'));
    // O-07 (owner chose A, 28 Nov): the Overview is one compact screen. The task list and the history are harvested
    // above for their tabs; here they become one tasks line and the last three events with one button to Activity.
    const jump=(label,tab)=>{const b=el('button','btn ghost sm',label);b.type='button';b.onclick=()=>document.getElementById('tab-'+tab).click();return b;};
    const taskBox=rows[0]?.closest('.story-section, .progress-card, section');
    if(taskBox&&!empty){const line=el('div','tab-head');const bar=el('div','progress-steps');bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','Tasks done');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax',String(states.length-skipN));bar.setAttribute('aria-valuenow',String(doneN));states.forEach(x=>bar.append(el('span',x)));
      const open=states.length-skipN;line.append(bar,el('strong','',doneN+' of '+open+(open===1?' task done':' tasks done')));if(skipN)line.append(el('span','meta',skipN+" won't do"));
      const now=states.indexOf('doing');if(now>=0)line.append(el('span','meta','The helper is on: '+taskNames[now]));
      line.append(jump('Open tasks','tasks'));taskBox.replaceWith(line);}
    if(activity&&!empty){const box=activity.closest('.story-section, section')||activity;const head=box.querySelector('.section-head');
      [...activity.children].slice(3).forEach(n=>n.remove());extraActivity?.remove();
      if(head){head.replaceChildren(el('h2','','Latest'));if(activityCount>3)head.append(jump('Show all '+activityCount+' in Activity','activity'));}}
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
