(()=>{
 const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
 const initial=document.body.dataset.initialMode;
 let saved={};try{saved=JSON.parse(sessionStorage.getItem('focus-work-session')||'{}')}catch{}
 let remembered=false;try{remembered=localStorage.getItem('focus-terminal')==='true'}catch{}
 let terminal=initial!=='compact'||remembered,fullscreen=initial==='fullscreen',paused=!!saved.paused;
 const params=new URLSearchParams(location.search);const state=['loading','empty'].includes(params.get('state'))?params.get('state'):'loaded';
 $$('[data-view]').forEach(v=>v.hidden=v.dataset.view!==state);
 function persist(){saved.paused=paused;try{sessionStorage.setItem('focus-work-session',JSON.stringify(saved))}catch{}}
 function mode(){document.body.classList.toggle('terminal-mode',terminal);document.body.classList.toggle('focus-fullscreen',fullscreen);$('#terminal-toggle').setAttribute('aria-pressed',terminal);$('#full-toggle').textContent=fullscreen?'Exit full screen · Esc':'Full screen';$('#full-toggle').setAttribute('aria-pressed',fullscreen)}
 function toggleTerminal(){terminal=!terminal;try{localStorage.setItem('focus-terminal',terminal)}catch{}mode()}
 $('#terminal-toggle').onclick=toggleTerminal;$('#show-terminal').onclick=()=>{if(!terminal)toggleTerminal();$('.terminal-pane').scrollIntoView({block:'start'});$('#terminal-toggle').focus()};
 $('#full-toggle').onclick=()=>{fullscreen=!fullscreen;mode()};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('dialog[open]')){fullscreen=false;mode()}});mode();
 const lines=['$ cd newsletter', '$ node tools/newsletter.mjs build --draft autumn', '✓ Loaded three stories and the short intro', '✓ Skipped shop photos: no new photos this month', '✓ Wrote preview/autumn-newsletter.html', '$ node tools/newsletter.mjs check-links --draft autumn'];
 function renderTerminal(){ $('#terminal-output').textContent=lines.join('\n');$('#terminal-peek').textContent=[...lines,$('#terminal-current').textContent].slice(-5).join('\n') }
 function event(text,author='Helper'){const a=document.createElement('article');a.className='stream-event live-entry';const label=document.createElement('span');label.className='meta';label.textContent=author+' · just now';const p=document.createElement('p');p.textContent=text;a.append(label,p);$('#activity').append(a)}
 function status(){ $('#pause').textContent=paused?'Continue work':'Pause work';$('#work-status').textContent=paused?'Working · paused':saved.sent?'Check · Test ready':saved.answer?'Working · Live':'Working · Live';$('#terminal-current').textContent=paused?'Paused — continue when you’re ready':saved.sent?'Test ready for review ▍':saved.answer?'Preparing the team test… ▍':'Waiting for recipient choice ▍';renderTerminal() }
 $('#pause').onclick=()=>{paused=!paused;persist();status()};
 function answered(value){saved.answer=value;$('#question .badge').textContent='Done · Answered';$('#question .badge').className='badge';$('#answer-status').textContent='Your answer: '+value;$$('[data-answer],#other-answer').forEach(b=>b.disabled=true);$('#current-step').textContent='Preparing a test mail for '+value+'.';persist();status()}
 $$('[data-answer]').forEach(b=>b.onclick=()=>{answered(b.dataset.answer);event(b.dataset.answer,'You');event('I’ll prepare the test for '+b.dataset.answer+'.');lines.push('$ node tools/newsletter.mjs test --draft autumn --recipients "'+b.dataset.answer+'" --preview-only');renderTerminal()});
 $('#other-answer').onclick=()=>{$('#message').value='Send the test to ';$('#message').dataset.answer='true';$('#message').focus();$('#message-status').textContent='Add the names or addresses, then send your answer.'};
 $('#message-form').onsubmit=e=>{e.preventDefault();const input=$('#message'),value=input.value.trim();if(!value)return;event(value,'You');saved.messages=saved.messages||[];saved.messages.push(value);if(input.dataset.answer){answered(value);delete input.dataset.answer}else persist();input.value='';$('#message-status').textContent='Message added to this demo conversation.'};
 $$('[data-open]').forEach(b=>b.onclick=()=>$('#'+b.dataset.open).showModal());$$('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
 $('#approve').onclick=()=>{saved.reviewed=true;persist();$('#review-status').textContent='Done · Reviewed by you';$('#review-feedback').textContent='Review recorded in this preview. The website has not been changed.';$('#approve').disabled=true};
 $('#request-changes').onclick=()=>{$('#review').close();$('#message').value='For the opening hours page, please ';$('#message').focus()};
 if(saved.answer)answered(saved.answer);if(saved.messages)saved.messages.forEach(m=>event(m,'You'));if(saved.reviewed){$('#review-status').textContent='Done · Reviewed by you';$('#approve').disabled=true}status();
 const updates=[['✓ All newsletter links respond','The newsletter links work, including the opening hours page.'],['✓ Subject and plain-text version checked','The subject line and text-only version are ready.'],['✓ Preview fits a phone screen','The draft fits a phone screen. You can open it above.']];
 let step=0;const timer=setInterval(()=>{if(paused||state!=='loaded'||document.hidden)return;if(step<updates.length){const [line,plain]=updates[step++];lines.push(line);event(plain);renderTerminal()}else if(saved.answer&&!saved.sent){saved.sent=true;lines.push('✓ Test mail prepared (preview only; nothing sent)');event('The test mail is prepared. Open the newsletter draft to check it. This demo does not send mail.');$('#current-step').textContent='Test mail prepared for '+saved.answer+'. Ready for your check.';persist();status();clearInterval(timer)}},4500);
 if(saved.sent){$('#current-step').textContent='Test mail prepared for '+saved.answer+'. Ready for your check.';lines.push('✓ Test mail prepared (preview only; nothing sent)');status()}
 if(['#draft','#review'].includes(location.hash)&&state==='loaded')$(location.hash).showModal();
})();
