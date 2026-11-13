/* 11 Nov: shipped group, result and review states. Local fixtures, no services. */
(() => {
  const entries = [['groups','Chats · Groups'],['group-open','Group · open'],['group-sent','Group · after send'],['group-done','Group · done'],['done-groups','Earlier'],['info-collapsed','Ticket info · collapsed'],['info-expanded','Ticket info · expanded'],['info-job','Ticket info · job result'],['ticket-review','Ticket · ready for review'],['ticket-no-question','Ticket · no review question']];
  reviewGroups.unshift(['11 Nov · Visual challenge', entries]);
  const custom = new Set(['group-open','group-sent','group-done','done-groups','earlier-day','ticket-review','ticket-no-question']);
  let earlierWorkspace = 'pilatus', earlierDay = '';
  let sent = [], muted = false, verdict = '', infoTab = 'Photos', agentOpen = false, jobOpen = false;
  const go = (id, text, cls = '') => actionButton('navigate', text, id, cls);
  const badges = () => '<span class="vc-badges" aria-label="Finance, Home, Bank"><i>F</i><i>H</i><i>B</i></span>';
  const pill = text => `<div class="vc-system"><span>${text}</span></div>`;
  const chart = () => '<svg class="vc-chart" viewBox="0 0 360 150" role="img" aria-label="Q3 chart: four revenue bars"><rect width="360" height="150" rx="10" fill="#15181d"/><path fill="#204e46" d="M30 100h60v40H30zM110 70h60v70h-60zM190 80h60v60h-60z"/><path fill="#2fc6a3" d="M270 15h60v125h-60z"/></svg>';
  const row = done => go(done?'group-done':'group-open',`${badges()}<span class="fill"><strong>Pay car tax ${done?'2026':'2027'}</strong><span class="preview">${done?'finished Tue 10 Nov':'3 helpers · started 14:30'}</span></span>${icon('chevron')}`,`vc-group-row ${done?'vc-muted':''}`);
  const oldRows = listRows;
  /* The open demo group: read, no open question. Same filter rule as workspace rows (unread / needs you). */
  const groupUnread = 0, groupNeedsYou = false, finishedGroups = 1;
  const groupMatches = () => filter==='All' || filter==='Unread'&&groupUnread>0 || filter==='Needs your OK'&&groupNeedsYou;
  listRows = function(){return oldRows() + ((!query || /group|car|fin|reports/i.test(query)) && groupMatches()?`<section data-key="vc-groups" class="vc-groups"><h3>Groups</h3>${row(false)}</section>`:'') + (!query && filter==='All' && finishedGroups>0 ? go('done-groups',`<span class="fill">Finished groups</span><span class="vc-count">${finishedGroups}</span>${icon('chevron')}`,'vc-done-link vc-finished-row') : '');};
  const oldWorkspaceRow = workspaceRow;
  workspaceRow = function(c){return oldWorkspaceRow(c).replace('Say hello to '+esc(names[c]),'No messages yet');};
  function header(done=false, ticket=false){return `<header class="vc-header">${btn('navigate','Back','back','data-value="back"')}${ticket?'':badges()}<div class="fill"><h2>${ticket?(screen==='ticket-no-question'?'Finished work':'Test HTML page about fish'):'Pay car tax '+(done?'2026':'2027')}</h2>${ticket?'<small>Pilatus · 4 Nov</small>':actionButton('vc-source','From ticket ›','','vc-source')}</div>${done?'':btn('vc-mute',muted?'Unmute notifications':'Mute notifications','bell',`aria-pressed="${muted}"`)}${btn(ticket?'vc-ticket-info':'vc-details','Info','info')}</header>`;}
  function bubbleText(text, sender='', mine=false){return `<div class="vc-message ${mine?'vc-own':''}">${sender?`<div class="vc-sender"><i class="vc-member ${sender.toLowerCase()}">${sender[0]}</i>${sender}</div>`:''}<div class="vc-bubble">${esc(text)}<small>14:${mine?'33':'30'} ${mine?'<span aria-label="Delivered">✓✓</span>':''}</small></div></div>`;}
  function composer(group){return `<footer class="vc-compose">${group?'<p class="vc-thinking">Home is thinking…</p><p class="vc-recipients">To: Finance, Home, Bank</p>':''}<form class="vc-compose-row"><input name="message" aria-label="${group?'Message the group':'Message'}" placeholder="${group?'Message the group':'Message…'}" autocomplete="off"><button type="submit" class="icon-button" aria-label="Send message">${icon('arrow')}</button></form>${group?`<p class="vc-hint">Everyone in this group sees what you write here · ${actionButton('vc-details','Details','','vc-inline')}</p>`:''}</footer>`;}
  function draw(){
    if(!custom.has(screen))return;
    const done=screen==='group-done', ticket=screen.startsWith('ticket-');
    if(screen==='done-groups'){
      const today=new Date();if(today.getHours()<4)today.setDate(today.getDate()-1);today.setHours(4,0,0,0);
      const days=workspaces().flatMap(c=>[...new Set(state.messages[c].filter(m=>m.at<today.getTime()).map(m=>{const d=new Date(m.at);if(d.getHours()<4)d.setDate(d.getDate()-1);return d.toLocaleDateString('en-CA');}))].sort().reverse().map(day=>actionButton('vc-earlier-day',`${esc(day)} · ${esc(names[c])}`,c+'|'+day)));
      contentRoot().innerHTML=nav('Earlier','back')+`<div class="scroll vc-content"><h3>Earlier days</h3>${days.join('')||'<p>No earlier days yet.</p>'}<h3>Finished groups</h3>${row(true)}</div>`;return;
    }
    if(screen==='earlier-day'){
      const messages=state.messages[earlierWorkspace].filter(m=>{const d=new Date(m.at);if(d.getHours()<4)d.setDate(d.getDate()-1);return d.toLocaleDateString('en-CA')===earlierDay;});
      contentRoot().innerHTML=nav(names[earlierWorkspace],'back')+`<div class="vc-system">${esc(earlierDay)} · you can read, not reply</div><div class="scroll vc-feed">${messages.map(m=>bubbleText(m.text||({voice:'Voice memo',photo:'Photo'}[m.type]||'Shared item'),'',m.mine)).join('')}</div>${actionButton('vc-today','Back to today')}`;return;
    }
    contentRoot().innerHTML=header(done,ticket)+(ticket?`<div class="vc-progress"><span>${verdict==='Accept'?'Done':'Ready for review'}</span><small>3 of 3 tasks done</small>${actionButton('vc-tasks',icon('down'),'','icon-button')}</div>`:'')+`<div class="scroll vc-feed">${ticket?`<div class="day">Today</div><div class="vc-bubble vc-result"><b>Result</b><p>${screen==='ticket-no-question'?'The helper finished the work.':'Your fish test page is ready.'}</p>${screen==='ticket-review'?`<button class="vc-artifact" data-action="vc-artifact"><div class="vc-fish" role="img" aria-label="Fish test page preview"><span>THE UNDERWATER WORLD</span><strong>Meet the fish</strong><svg viewBox="0 0 240 80" aria-hidden="true"><path d="M45 40Q100-15 175 40Q100 95 45 40M175 40l35-28v56z" fill="#2fc6a3"/><circle cx="75" cy="34" r="4" fill="#06231c"/></svg></div><span>Fish test page <b>Open ↗</b></span></button>`:''}<small>14:33</small></div>${verdict?pill(verdict==='Accept'?'Accepted':'Changes requested'):''}`:pill('Group started')+bubbleText(done?'The car tax is paid.':'I’ve brought Home and Bank into this group.','Finance')+(done?pill('This group is done'):bubbleText('We’ll check the payment details here.')+bubbleText('I found last year’s payment.','Bank')+`<button class="vc-task" data-action="vc-source"><small>Task</small><strong>Check last year’s payment</strong><span>Done ${icon('chevron')}</span></button>`+sent.map(t=>bubbleText(t,'',true)).join(''))}</div>`+(done?'<footer class="vc-readonly">Read only</footer>':`${ticket&&screen==='ticket-review'&&!verdict?`<div class="vc-review-bar">${actionButton('vc-verdict','Accept','Accept','vc-verdict primary')}${actionButton('vc-verdict','Ask for changes','Ask for changes','vc-verdict')}</div>`:''}${composer(!ticket)}`);
    if(screen==='group-sent'){const feed=contentRoot().querySelector('.vc-feed');feed.scrollTop=feed.scrollHeight;}
    const form=contentRoot().querySelector('form');if(form)form.onsubmit=e=>{e.preventDefault();const input=form.elements.message;if(!input.value.trim())return;if(ticket){contentRoot().querySelector('.vc-feed').insertAdjacentHTML('beforeend',bubbleText(input.value,'',true));input.value='';}else{sent.push(input.value.trim());screen='group-sent';draw();}const feed=contentRoot().querySelector('.vc-feed');feed.scrollTop=feed.scrollHeight;};
  }
  const oldRender=render, oldNavigate=navigate, oldReview=review, oldInfo=renderInfo;
  render=function(){oldRender();draw();};
  navigate=function(to,...args){oldNavigate(to,...args);draw();};
  review=function(key){
    if(key==='question-approval')key='ticket-review';
    if(!entries.some(([id])=>id===key))return oldReview(key);
    resetReviewState();sent=key==='group-sent'?['I can bring dessert']:[];verdict='';muted=false;
    if(key==='groups'){navigate('chats');contentRoot().querySelector('.vc-groups')?.scrollIntoView({block:'end'});}
    else if(key.startsWith('info-')){agentOpen=key!=='info-collapsed';jobOpen=key==='info-job';infoTab='Photos';navigate('ticket');navigate('info');if(jobOpen)contentRoot().querySelector('#vc-job').scrollIntoView({block:'start'});}
    else navigate(key);
    updateReview(key);
  };
  // contracts/blocks.md keeps agent source labels; this display uses helper wording.
  function resultCard(job){const open=job?jobOpen:agentOpen;return `<section class="vc-result-card" ${job?'id="vc-job"':''}><button data-action="vc-result-toggle" data-value="${job?'job':'agent'}" aria-expanded="${open}"><span><small>${job?'Reported by the job':'Checked by the helper'} · 31 Oct</small><strong>${job?'Q3 export':'Q3 totals checked'}</strong></span><span class="vc-chevron ${open?'expanded':''}">${icon('chevron')}</span></button>${open?`<div class="vc-result-body">${job?'<table><thead><tr><th>Region</th><th>Amount</th></tr></thead><tbody><tr><td>North</td><td>420000</td></tr><tr><td>South</td><td>384300</td></tr><tr><td>West</td><td>400000</td></tr></tbody></table><small>3 of 40 rows</small><p>Rows exported</p><progress value="40" max="40" aria-label="Rows exported"></progress><small>40 of 40</small>':`<p>Q3 totals match the finance sheet.</p><dl><dt>Sheet total</dt><dd>CHF 1 204 300</dd><dt>Report total</dt><dd>CHF 1 204 300</dd></dl><button class="vc-file" data-action="vc-chart">${icon('file')} Q3 chart${chart()}</button>`}</div>`:''}</section>`;}
  renderInfo=function(){if(chat!=='ticket')return oldInfo();const y=contentRoot().querySelector('.vc-info')?.scrollTop||0;contentRoot().innerHTML=nav('Conversation info','back')+`<div class="scroll vc-content vc-info"><div class="vc-info-heading"><h2>Q3 summary for the board</h2><details><summary>Details</summary><small>PIL-12 · Pilatus Workspace</small></details><span class="vc-status">Done</span><p class="vc-description" title="Pulled the numbers, drew the charts, the board deck is ready.">Pulled the numbers, drew the charts, the board deck is ready.</p><p>5 tasks · 4 references</p></div><h3>Results</h3>${resultCard(false)}${resultCard(true)}<div class="vc-tabs" role="tablist" aria-label="Shared items">${[['Photos',1],['Files',1],['References',4],['Artifacts',1]].map(([t,n])=>`<button role="tab" aria-selected="${infoTab===t}" data-action="vc-tab" data-value="${t}">${t} (${n})</button>`).join('')}</div><div role="tabpanel" class="vc-tab-content">${infoTab==='Photos'?`<button data-action="vc-chart" aria-label="Open Q3 chart">${chart()}</button>`:infoTab==='Files'?actionButton('vc-file-preview',icon('file')+' q3-summary.pdf','','vc-file'):infoTab==='References'?referenceExamples():artifactCard('pdf')}</div></div>`;contentRoot().querySelector('.vc-info').scrollTop=y;};
  document.addEventListener('click',e=>{const el=e.target.closest('[data-action]');if(!el)return;const a=el.dataset.action,v=el.dataset.value;
    if(a==='vc-earlier-day'){[earlierWorkspace,earlierDay]=v.split('|');navigate('earlier-day');}
    if(a==='vc-today')navigate('general:'+earlierWorkspace);
    if(a==='vc-result-toggle'){if(v==='job')jobOpen=!jobOpen;else agentOpen=!agentOpen;renderInfo();}
    if(a==='vc-tab'){infoTab=v;renderInfo();}
    if(a==='vc-chart')sheet('Q3 chart',chart(),true);
    if(a==='vc-file-preview')sheet('q3-summary.pdf','<div class="pdf-paper"><h2>Q3 board summary</h2><p>Revenue: CHF 1 204 300</p><p>Q3 totals match the finance sheet.</p></div>',true);
    if(a==='vc-artifact')sheet('Fish test page',contentRoot().querySelector('.vc-fish').outerHTML,true);
    if(a==='vc-mute'){muted=!muted;el.setAttribute('aria-pressed',String(muted));el.setAttribute('aria-label',muted?'Unmute notifications':'Mute notifications');toast(muted?'Notifications muted':'Notifications on');}
    if(a==='vc-details')sheet('Group details',`${badges()}<h3>Pay car tax ${screen==='group-done'?'2026':'2027'}</h3><p class="sheet-note">Finance · Home · Bank</p><p>Everyone in this group sees what you write here.</p>`);
    if(a==='vc-source')sheet('From ticket','<h3>Pay car tax</h3><p class="sheet-note">Finance · Home · Bank</p><div class="checklist-row">✓ Check last year’s payment</div><div class="checklist-row">○ Prepare this year’s payment</div>');
    if(a==='vc-tasks')sheet('Tasks',['Prepare the page','Run checks','Deliver the result'].map(t=>`<div class="checklist-row">✓ ${t}</div>`).join(''));
    if(a==='vc-ticket-info'){chat='ticket';navigate('info');}
    if(a==='vc-verdict'){if(v==='Ask for changes')sheet('Ask for changes','<textarea id="vc-feedback" class="caption-input" aria-label="Requested changes" placeholder="What would you like changed?"></textarea>'+actionButton('vc-submit-changes','Send changes','','wide-btn primary'));else{verdict=v;draw();}}
    if(a==='vc-submit-changes'){const text=$('#vc-feedback').value.trim();if(!text)return;closeModal(true);verdict='Ask for changes';draw();contentRoot().querySelector('.vc-feed').insertAdjacentHTML('beforeend',bubbleText(text,'',true));}
  });
  // Retire the publishing question fixture; the review bar is its replacement.
  for(const target of [state,reviewBaseline])target.messages.rig4=target.messages.rig4.filter(m=>m.id!=='approval');
  reviewGroups.forEach(([,items])=>items.forEach(item=>{if(item[0]==='question-approval')item[1]='Accept / Ask for changes';}));
  render();
})();
