/* One snapshot shared by every editable screen. No synthetic live events. */
(()=>{
const data=window.demoData=Object.freeze({needs:3,helper:'Helper',newsletter:{title:'Plan the autumn newsletter',owner:'Anna',minutes:23,progress:'3 of 4 steps'},survey:{title:'Summarise the customer survey',owner:'Anna',finished:'12:26'},sign:{title:'Prepare the new opening hours sign',owner:'Anna',finished:'12:32'},typo:{title:'Fix the typo on the opening hours page',owner:'Anna',finished:'12:27'},question:{title:'Which supplier for the gift boxes?',owner:'Ben',minutes:27}});
const state=new URLSearchParams(location.search).get('state')||'loaded';
document.querySelectorAll('.sidebar .count,#waitn').forEach(e=>{e.textContent=state==='empty'?'0':data.needs;e.setAttribute('aria-label',e.textContent+' need you')});
const main=document.querySelector('main');if(!main)return;
const heading=main.querySelector('.page-header,.page-heading,.ticket-heading,.fhead');
if(heading&&!heading.textContent.includes('Updated just now')){const updated=document.createElement('p');updated.className='meta updated-at';updated.textContent='Updated just now';heading.append(updated)}
if(!main.querySelector('h1')){const h=document.createElement('header');h.className='page-header';h.innerHTML='<div><h1>Tickets</h1><p>Every ticket, from To do to Done.</p><p class="meta">Updated just now</p></div>';main.prepend(h)}
const thumb='<span class="preview-thumbnail" aria-label="Preview of survey summary"><span>Survey</span><i></i><i></i><i></i></span>';
document.querySelectorAll('[data-ticket]').forEach(row=>{const title=row.dataset.title||'';const owner=/gift boxes|workshop|logo|thank-you|customer emails/.test(title)?'Ben':'Anna';const agent=row.querySelector('.agent-chip');if(agent)agent.textContent=owner;const cell=row.matches('tr')?row.children[2]:null;if(cell)cell.textContent=owner;const info=row.querySelector('.attention-line');if(info&&title.includes('gift boxes'))info.textContent='Question for you · asked 27 min ago';if(title.includes('opening hours sign')&&!row.textContent.includes('Changes to add')){const a=document.createElement('a');a.className='meta warn';a.href='../ticket/ticket-done.html#changes';a.textContent='Changes to add';(row.matches('tr')?row.firstElementChild:row).append(a)}});
document.querySelectorAll('#helper').forEach(e=>{e.setAttribute('aria-label','Person');for(const o of e.options){o.textContent=o.value==='all'?'Everyone':o.value==='A'?'Anna':'Ben'}});
document.querySelectorAll('.file-type').forEach(e=>{if(e.textContent.trim()==='HTML')e.innerHTML='▤'});
if(location.pathname.endsWith('ticket-done.html')){const story=document.querySelector('#story-loaded');if(story){const box=document.createElement('section');box.id='changes';box.className='card decision';box.innerHTML='<h2>Changes to add</h2><p>Add the changes from “Prepare the new opening hours sign” to your files?</p><button class="btn primary sm">Add to my files</button><p role="status" class="meta"></p>';box.querySelector('button').onclick=e=>{e.target.disabled=true;box.querySelector('[role=status]').textContent='Changes added in this preview.'};story.prepend(box)}}
})();
(()=>{const d=window.demoData;const values={'newsletter-time':d.newsletter.minutes+' min ago','newsletter-duration':d.newsletter.minutes+' min','survey-time':d.survey.finished,'sign-time':d.sign.finished,'typo-time':d.typo.finished};document.querySelectorAll('[data-demo]').forEach(e=>e.textContent=values[e.dataset.demo]||'');})();
(()=>{
 const d=window.demoData;
 const facts={
 'plan the autumn newsletter':['Anna','Helper working','23 min ago','3 of 4 steps'],
 'book the spring workshop room':['Ben','Helper working','24 min ago','1 of 3 steps'],
 'update the price list':['Anna','Helper working','24 min ago','2 of 3 steps'],
 'which supplier for the gift boxes?':['Ben','Question for you · asked 27 min ago','27 min ago','Needs you'],
 'summarise the customer survey':['Anna','Check · Finished '+d.survey.finished,d.survey.finished,'2 of 2 steps'],
 'prepare the new opening hours sign':['Anna','Changes to add',d.sign.finished,'2 of 2 steps'],
 'fix the typo on the opening hours page':['Anna','Done',d.typo.finished,'1 of 1 steps'],
 'set up the weekly sales report':['Anna','To do','Added yesterday','0 of 2 steps'],
 'redesign the logo':['Ben','Paused','2 days ago','1 of 2 steps'],
 'thank-you notes for our top customers':['Ben','To do','Added Mon','To do'],
 'answer customer emails from last week':['Ben','To do','Added Mon','To do']};
 document.querySelectorAll('[data-ticket]').forEach(row=>{const fact=facts[row.dataset.title];if(!fact)return;if(row.matches('tr')){row.children[2].textContent=fact[0];row.children[4].textContent=fact[2];if(!row.firstElementChild.querySelector('.ticket-info')){const sub=document.createElement('div');sub.className='meta ticket-info';sub.textContent=fact[1];row.firstElementChild.append(sub)}}});
 const kind=new URLSearchParams(location.search).get('ticket');
 if(location.pathname.endsWith('focus-ticket.html')&&['price','workshop'].includes(kind)){
 const title=kind==='price'?'Update the price list':'Book the spring workshop room';const fact=facts[title.toLowerCase()];const loaded=document.querySelector('[data-view=loaded]');loaded.querySelector('h1').textContent=title;loaded.querySelector('.page-header p').textContent='Follow the current work for '+fact[0]+'.';loaded.querySelector('#work-status').textContent='Working · 24 min';loaded.querySelector('.now-card h2').textContent=kind==='price'?'Waiting for the next update':'Compare two rooms';loaded.querySelector('.recent-steps').replaceChildren();loaded.querySelector('.now-card details')?.remove();loaded.querySelector('.result-preview')?.closest('section')?.remove();const panel=loaded.querySelector('.task-panel');panel.innerHTML='<h2>Progress</h2><p>'+fact[3]+'</p><p class="meta">Waiting for the next update</p>';}
})();
