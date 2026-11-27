// New ticket, option A (ORCH-2162, owner 25 Nov): files in a row under the request, parts as short rows, the helper
// as a short list (only the helpers this workspace has, names only), Save ticket and Start now side by side.
(()=>{
const $=s=>document.querySelector(s),files=[],mk=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
function chip(f,remove){const li=mk('li','new-ticket-file'),main=mk('button','new-ticket-file-main');main.type='button';if(/^image\//.test(f.type||'')){const img=mk('img','thumbnail');img.alt='';img.src=URL.createObjectURL(f);main.append(img)}else{const k=mk('span','new-ticket-file-kind',((f.name.match(/\.([a-z0-9]{1,4})$/i)||[])[1]||'file').toUpperCase());k.setAttribute('aria-hidden','true');main.append(k)}main.append(mk('span','',f.name),mk('span','meta',f.size<1e6?Math.max(1,Math.round(f.size/1000))+' KB':(f.size/1e6).toFixed(1)+' MB'));const x=mk('button','btn ghost xs new-ticket-file-remove','Remove');x.type='button';x.setAttribute('aria-label','Remove '+f.name);x.onclick=remove;li.append(main,x);return li}
function renderFiles(){$('#file-list').replaceChildren(...files.map((f,i)=>chip(f,()=>{files.splice(i,1);renderFiles()})))}
function addFiles(added){const rejected=[];for(const f of added){if(f.size>25000000)rejected.push(f.name);else files.push(f)}renderFiles();$('#file-error').textContent=rejected.length?'These files are over 25 MB: '+rejected.join(', '):'';$('#attachments').value=''}
$('#attach-btn').onclick=()=>$('#attachments').click();
$('#attachments').onchange=e=>addFiles(e.target.files);const form=$('#ticket-form');form.addEventListener('dragover',e=>e.preventDefault());form.addEventListener('drop',e=>{e.preventDefault();addFiles(e.dataTransfer.files)});
// the lines under the buttons name the helper picked on the right
function sayWhat(){const who=(document.querySelector('[name=helper]:checked')||{}).value||'Your helper';$('[data-save-line]').textContent='Goes to Tickets. '+who+' may prepare a short plan; no work starts.';$('[data-start-line]').textContent=who+' begins at once. This may cost money.';$('[data-plan-note]').textContent=who+' waits for your OK before work begins.'}
document.querySelectorAll('[name=helper]').forEach(r=>r.onchange=sayWhat);
UI.date($('#due-date'),$('#date-toggle'),$('#date-picker'));
// Keep the shared calendar, but host it as a popover within this modal form.
const dateToggle=$('#date-toggle'),calendar=document.getElementById(dateToggle.getAttribute('aria-controls'));
calendar.setAttribute('popover','manual');
calendar.setAttribute('role','group');
calendar.dataset.overlayReady='true';
dateToggle.removeAttribute('aria-haspopup');
($('#new-dialog')||document.body).append(calendar);
const dateOpen=dateToggle.onclick,closeOtherPopover=UI.closePopover;
const dateIsOpen=()=>calendar.matches(':popover-open');
calendar.showModal=()=>{
  closeOtherPopover?.();
  calendar.showPopover();
  const r=dateToggle.getBoundingClientRect();
  calendar.style.left=Math.max(8,Math.min(r.right-calendar.offsetWidth,innerWidth-calendar.offsetWidth-8))+'px';
  calendar.style.top=Math.max(8,r.top-calendar.offsetHeight-8)+'px';
};
calendar.close=()=>{
  if(!dateIsOpen())return;
  calendar.hidePopover();
  calendar.dispatchEvent(new Event('close'));
  dateToggle.focus({preventScroll:true});
};
dateToggle.onclick=()=>dateIsOpen()?calendar.close():dateOpen();
UI.closePopover=()=>{if(dateIsOpen()){calendar.close();return true}return closeOtherPopover?.()||false};
document.addEventListener('click',e=>{
  if(dateIsOpen()&&!calendar.contains(e.target)&&!dateToggle.contains(e.target)){
    calendar.close();
    // An outside click dismisses this layer only, including the parent backdrop.
    e.preventDefault();e.stopImmediatePropagation();
  }
},true);
$('#new-dialog')?.addEventListener('close',()=>calendar.close());
window.addEventListener('resize',()=>calendar.close());
// Parts (ORCH-14): each part becomes its own ticket inside this one, with its own text and files.
const epicList=$('#epic-tickets'),epicAdd=$('#epic-add');
function renumberEpic(){const rows=[...epicList.children];rows.forEach((b,i)=>{b.querySelector('.new-ticket-step-name').textContent='Part '+(i+1);b.querySelector('textarea').setAttribute('aria-label','Part '+(i+1)+': what needs doing?');b.querySelector('[data-remove]').setAttribute('aria-label','Remove part '+(i+1))});$('#epic-help').hidden=!rows.length;epicAdd.textContent=rows.length?'＋ Add another part':'＋ Split into parts';(rows.length?$('#epic-foot'):$('.new-ticket-file-bar')).append(epicAdd)}
epicAdd.onclick=()=>{const box=mk('div','new-ticket-step'),row=mk('div','new-ticket-step-row'),text=mk('textarea','input'),pick=mk('input'),add=mk('button','btn ghost sm new-ticket-step-files','＋ Files'),rm=mk('button','btn ghost sm','Remove'),list=mk('ul','new-ticket-files');text.rows=1;text.placeholder='What needs doing in this part?';pick.type='file';pick.multiple=true;pick.hidden=true;add.type=rm.type='button';rm.dataset.remove='';add.onclick=()=>pick.click();pick.onchange=e=>{for(const f of e.target.files)list.append(chip(f,ev=>ev.target.closest('li').remove()))};rm.onclick=()=>{box.remove();renumberEpic()};row.append(mk('span','meta new-ticket-step-name'),text,add,rm);box.append(row,pick,list);epicList.append(box);renumberEpic();text.focus()};
form.addEventListener('reset',()=>{files.length=0;renderFiles();$('#file-error').textContent='';epicList.replaceChildren();renumberEpic()});
})();

// ORCH-1852: Save ticket (filled) is the default, also Enter with Cmd or Ctrl; Start now is the explicit, outlined
// choice beside it. Preview "No helper" (?helper=none): no Start now, no Helper box, Optional takes the right column,
// the plan choice moves there and the line under Save says nothing starts, with a link to set one up.
(()=>{
const $=s=>document.querySelector(s),form=$('#ticket-form'),start=$('[data-start]'),button=$('[data-helper]');if(!form||!start||!button)return;
start.onclick=()=>{form.dataset.intent='start';form.requestSubmit()};
form.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();form.requestSubmit()}});
const save=$('[data-save-line]'),saveText=save.textContent;
function helper(none){document.body.dataset.helper=none?'none':'ready';button.setAttribute('aria-pressed',none);$('[data-start-cell]').hidden=none;$('[data-helper-row]').hidden=none;form.classList.toggle('no-helper',none);
  const plan=$('#plan-label');if(none){$('#more .new-ticket-check').after(plan);$('[data-plan-note]').textContent='When it starts, the helper waits for your OK before work begins.';save.textContent='Goes to Tickets. No helper is set up yet, so nothing starts. ';const a=document.createElement('a');a.className='new-ticket-link';a.href='../settings/settings-helper.html';a.textContent='Set up a helper';save.append(a)}else{$('[data-start-cell]').append(plan);save.textContent=saveText;document.querySelector('[name=helper]:checked')?.dispatchEvent(new Event('change'))}
  const u=new URL(location.href);if(none)u.searchParams.set('helper','none');else u.searchParams.delete('helper');try{history.replaceState(null,'',u)}catch{}}
button.onclick=()=>helper(document.body.dataset.helper!=='none');
helper(new URLSearchParams(location.search).get('helper')==='none');
})();
