(()=>{
const $=s=>document.querySelector(s),files=[];
function renderFiles(){const list=$('#file-list');list.replaceChildren();files.forEach((f,i)=>{const li=document.createElement('li'),name=document.createElement('span'),remove=document.createElement('button');name.textContent=f.name+' · '+(f.size/1000000).toFixed(1)+' MB';remove.type='button';remove.className='btn ghost xs';remove.textContent='Remove';remove.setAttribute('aria-label','Remove '+f.name);remove.onclick=()=>{files.splice(i,1);renderFiles()};li.append(name,remove);list.append(li)})}
function addFiles(added){const rejected=[];for(const f of added){if(f.size>100000000)rejected.push(f.name);else files.push(f)}renderFiles();$('#file-error').textContent=rejected.length?'These files are over 100 MB: '+rejected.join(', '):'';$('#attachments').value=''}
$('#attachments').onchange=e=>addFiles(e.target.files);const drop=$('#drop-zone');for(const name of ['dragenter','dragover'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag-over')});drop.addEventListener('dragleave',()=>drop.classList.remove('drag-over'));drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('drag-over');addFiles(e.dataTransfer.files)});
$('#ticket-helper').onchange=e=>$('#helper-description').textContent={default:'Helps with everyday tasks and planning.',coding:'Builds and fixes websites and code.',writing:'Writes and improves drafts, emails and notes.'}[e.target.value];
UI.date($('#due-date'),$('#date-toggle'),$('#date-picker'));
// Keep the shared calendar, but host it as a popover within this modal form.
const dateToggle=$('#date-toggle'),calendar=document.getElementById(dateToggle.getAttribute('aria-controls'));
calendar.setAttribute('popover','manual');
calendar.setAttribute('role','group');
calendar.dataset.overlayReady='true';
dateToggle.removeAttribute('aria-haspopup');
$('#new-dialog').append(calendar);
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
$('#new-dialog').addEventListener('close',()=>calendar.close());
window.addEventListener('resize',()=>calendar.close());
// Epic (ORCH-14): each ticket box becomes its own ticket inside this one, with its own text and files.
const epicList=$('#epic-tickets'),epicAdd=$('#epic-add');
function renumberEpic(){const boxes=[...epicList.children];boxes.forEach((b,i)=>{b.querySelector('strong').textContent='Ticket '+(i+1);b.querySelector('textarea').setAttribute('aria-label','Ticket '+(i+1)+': what needs doing?');b.querySelector('[data-remove]').setAttribute('aria-label','Remove ticket '+(i+1))});$('#epic-help').hidden=!boxes.length;epicAdd.textContent=boxes.length?'＋ Add another ticket':'＋ Make it an epic with several tickets'}
epicAdd.onclick=()=>{const box=document.createElement('section');box.className='card pad stack';box.innerHTML='<div class="row between"><strong></strong><button type="button" class="btn ghost xs" data-remove>Remove</button></div><textarea class="input" rows="2" placeholder="What needs doing in this ticket?"></textarea><label class="btn ghost sm">＋ Add files<input type="file" class="sr-only" multiple></label><ul class="meta"></ul>';box.querySelector('[data-remove]').onclick=()=>{box.remove();renumberEpic()};box.querySelector('input[type=file]').onchange=e=>{const ul=box.querySelector('ul');for(const f of e.target.files){const li=document.createElement('li');li.textContent=f.name;ul.append(li)}};epicList.append(box);renumberEpic();box.querySelector('textarea').focus()};
$('#ticket-form').addEventListener('reset',()=>{files.length=0;renderFiles();$('#file-error').textContent='';epicList.replaceChildren();renumberEpic()});
})();
