(()=>{
const $=s=>document.querySelector(s),files=[];
function renderFiles(){const list=$('#file-list');list.replaceChildren();files.forEach((f,i)=>{const li=document.createElement('li'),name=document.createElement('span'),remove=document.createElement('button');name.textContent=f.name+' · '+(f.size/1000000).toFixed(1)+' MB';remove.type='button';remove.className='btn ghost xs';remove.textContent='Remove';remove.setAttribute('aria-label','Remove '+f.name);remove.onclick=()=>{files.splice(i,1);renderFiles()};li.append(name,remove);list.append(li)})}
function addFiles(added){const rejected=[];for(const f of added){if(f.size>100000000)rejected.push(f.name);else files.push(f)}renderFiles();$('#file-error').textContent=rejected.length?'These files are over 100 MB: '+rejected.join(', '):'';$('#attachments').value=''}
$('#attachments').onchange=e=>addFiles(e.target.files);const drop=$('#drop-zone');for(const name of ['dragenter','dragover'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag-over')});drop.addEventListener('dragleave',()=>drop.classList.remove('drag-over'));drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('drag-over');addFiles(e.dataTransfer.files)});
$('#ticket-helper').onchange=e=>$('#helper-description').textContent={default:'Helps with everyday tasks and planning.',coding:'Builds and fixes websites and code.',writing:'Writes and improves drafts, emails and notes.'}[e.target.value];
UI.date($('#due-date'),$('#date-toggle'),$('#date-picker'));
$('#ticket-form').addEventListener('reset',()=>{files.length=0;renderFiles();$('#file-error').textContent=''});
})();
