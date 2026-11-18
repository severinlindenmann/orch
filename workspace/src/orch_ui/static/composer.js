/* Shared attachment composer: write, paste screenshots, pick or drop files, send.
   Without options it is the gallery/mockup demo (FileReader progress, demo status lines). A real page passes its own
   limits and an onSend that returns a promise of {ok, text}: the draft and the files stay when sending fails, and the
   status line shows the page's own words (ORCH-238, the ticket page). {ok:false, dropFiles:true} keeps only the text
   (the files already landed, a second send must not add them again).
   voice:true adds a Record button (ORCH-422): the recording lands as a file in the tray (voice-note-HHMM.webm/ogg/m4a);
   its words go into the text box only when the browser can turn speech into text on this computer (never a server),
   else the sound file alone. Hidden where the browser cannot record. send:false hides the send button and the
   limits line: the page's own buttons send (the Review comment sheet). */
(()=>{'use strict';window.UI=window.UI||{};
const DEMO_EXT=['png','jpg','jpeg','webp','pdf','txt','md','csv','docx','xlsx'];
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const mb=n=>Math.round(n/1048576);
UI.composer=(root,options={})=>{
const ext=(options.accept||DEMO_EXT).map(e=>String(e).toLowerCase()),maxFiles=options.maxFiles||10,maxBytes=options.maxBytes||100*1024*1024;
const interrupt=options.interrupt!==false,maxLength=options.maxLength||0;
const hint=options.hint!=null?`<p class="meta">${esc(options.hint)}</p>`:'<p class="meta">Read after the current operation · Cmd/Ctrl+V to paste screenshots.<br>Images (PNG, JPG, WebP), PDF, TXT, MD, CSV, DOCX, XLSX. Local demo uploads.</p>';
root.classList.add('attachment-composer');root.innerHTML=`<form><label class="sr-only" for="${esc(root.id)}-message">${esc(options.label||'Instruction for Helper')}</label><textarea id="${esc(root.id)}-message" rows="2"${maxLength?` maxlength="${maxLength}"`:''} placeholder="${esc(options.placeholder||'Write an instruction, paste a screenshot, or drop files…')}"></textarea><div class="staged-files"></div><p class="attachment-error" role="alert"></p><div class="composer-actions"><button class="btn sm" type="button" data-attach>${esc(options.attachLabel||'Attach')}</button><input type="file" multiple hidden accept="${ext.map(e=>'.'+e).join(',')}"><span data-voice-slot hidden></span>${options.send===false?'':`<span class="meta">${maxFiles} files · ${mb(maxBytes)} MB each</span><button class="btn ${options.sendStyle==='outline'?'outline':'primary'} sm" type="submit">${esc(options.sendLabel||'Queue instruction')}</button>`}${interrupt?'<button class="btn sm" type="button" data-interrupt>Interrupt now</button>':''}</div>${hint}<p class="meta" data-delivery role="status"></p></form>`;
const field=root.querySelector('textarea'),input=root.querySelector('input'),list=root.querySelector('.staged-files'),error=root.querySelector('[role=alert]'),delivery=root.querySelector('[data-delivery]'),submit=root.querySelector('[type=submit]');let files=[],busy=false;
field.value=options.draft||'';field.oninput=()=>options.onDraft?.(field.value);
function draw(){list.replaceChildren();files.forEach(f=>{const tile=document.createElement('div');tile.className='attachment-tile';if(f.url&&String(f.type).startsWith('image/')){const img=new Image();img.src=f.url;img.alt=f.name;tile.append(img)}const label=document.createElement('span');label.textContent=f.name+' · '+(f.size/1048576).toFixed(2)+' MB';tile.append(label);const progress=document.createElement('progress');progress.max=100;progress.value=f.progress;progress.setAttribute('aria-label','Upload '+f.name);tile.append(progress);const text=document.createElement('small');text.textContent=f.failed?'Could not read file.':f.progress===100?'Ready to attach':`Uploading ${f.progress}%`;tile.append(text);if(f.failed){const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';retry.onclick=()=>read(f);tile.append(retry)}const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove '+f.name);remove.onclick=()=>{f.reader?.abort();files=files.filter(x=>x!==f);draw()};tile.append(remove);list.append(tile)});if(submit)submit.disabled=busy||files.some(f=>f.progress<100||f.failed);options.onFiles?.(files)}
function read(f){f.failed=false;f.progress=0;const r=f.reader=new FileReader();r.onprogress=e=>{if(e.lengthComputable){f.progress=Math.round(e.loaded/e.total*99);draw()}};r.onload=()=>{f.url=r.result;f.progress=100;draw()};r.onerror=()=>{f.failed=true;draw()};r.readAsDataURL(f.file);draw()}
function add(incoming){error.textContent='';for(const file of incoming){const dot=file.name.lastIndexOf('.'),kind=dot>0?file.name.slice(dot+1).toLowerCase():'';if(file.size>maxBytes){error.textContent+=`This file is larger than ${mb(maxBytes)} MB. `;continue}if(!ext.includes(kind)){error.textContent+=options.acceptError?options.acceptError+' ':"This kind of file can't be attached. ";continue}if(files.length>=maxFiles){error.textContent+=`Attach up to ${maxFiles} files at a time. `;continue}const f={file,name:file.name,size:file.size,type:file.type,progress:0};files.push(f);read(f)}}
root.querySelector('[data-attach]').onclick=()=>input.click();input.onchange=()=>{add(input.files);input.value=''};root.addEventListener('paste',e=>{const pasted=UI.pastedFiles(e);if(pasted.length){e.preventDefault();add(pasted)}});
const target=options.dropTarget||root,overlay=document.createElement('div');overlay.className='attachment-drop';overlay.textContent=options.dropLabel||'Drop to attach to this ticket';overlay.hidden=true;target.append(overlay);let depth=0;
const onEnter=e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();depth++;overlay.hidden=false}},onOver=e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault()},onLeave=()=>{if(--depth<=0){depth=0;overlay.hidden=true}},onDrop=e=>{if(!e.dataTransfer.types.includes('Files'))return;e.preventDefault();depth=0;overlay.hidden=true;add(e.dataTransfer.files)};
target.addEventListener('dragenter',onEnter);target.addEventListener('dragover',onOver);target.addEventListener('dragleave',onLeave);target.addEventListener('drop',onDrop);
let voice=null;if(options.voice&&UI.voiceRecorder){voice=UI.voiceRecorder({lang:options.lang,onError:m=>{error.textContent=m},onDone:(file,words)=>{add([file]);if(words){field.value=(field.value.trim()?field.value.replace(/\s+$/,'')+'\n':'')+'Voice note: '+words;field.dispatchEvent(new Event('input',{bubbles:true}))}}});if(voice){const slot=root.querySelector('[data-voice-slot]');slot.replaceWith(voice.button)}}
function clear(){field.value='';files=[];draw();options.onDraft?.('')}
async function send(stop){if(busy)return;if(files.some(f=>f.progress<100||f.failed)){error.textContent='Wait for the files to finish uploading.';return}if(!field.value.trim()&&!files.length){error.textContent=options.emptyError||'Write an instruction or attach a file.';field.focus();return}
error.textContent='';const message={text:field.value,files:files.map(({name,size,type,url})=>({name,size,type,url})),interrupt:stop};
if(!options.onSend){UI.toast?.('Attached to this ticket in the demo.');clear();demoStatus(stop);return}
let result;busy=true;draw();delivery.textContent=options.sendingText||'';
try{result=await options.onSend(message)}catch(err){result={ok:false,text:String(err?.message||err)}}finally{busy=false}
if(result===undefined){clear();demoStatus(stop);return}  // a mockup's onSend: the old demo lines
if(result&&result.ok){clear();delivery.textContent=result.text||''}else{if(result&&result.dropFiles)files=[];draw();delivery.textContent='';error.textContent=(result&&result.text)||'That did not work. Try again.'}}
function demoStatus(stop){delivery.textContent=stop?'Stopping… Completed actions cannot be undone.':'Queued · Read after the current operation';if(stop)setTimeout(()=>delivery.textContent='Stopped in this demo · Instruction received',600)}
root.querySelector('form').onsubmit=e=>{e.preventDefault();send(false)};root.querySelector('[data-interrupt]')?.addEventListener('click',()=>send(true));
field.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();send(false)}});
return {field,add,clear,files:()=>files.slice(),restore:message=>{field.value=message.text;files=message.files.map(f=>({...f,progress:100}));draw();options.onDraft?.(field.value);field.focus()},
recorder:voice,destroy(){voice?.destroy();target.removeEventListener('dragenter',onEnter);target.removeEventListener('dragover',onOver);target.removeEventListener('dragleave',onLeave);target.removeEventListener('drop',onDrop);overlay.remove();files.forEach(f=>f.reader?.abort())}};
};
/* UI.voiceRecorder({onDone(file, words), onError(message), lang, maxSecs}) -> {button, stop(), destroy()} or null where the
   browser cannot record (no microphone access, or an http address that is not this computer). One click starts, one stops;
   it stops by itself after maxSecs (5 minutes). Words only from speech recognition that runs on this computer. */
const VOICE_TYPES=[['audio/webm;codecs=opus','webm'],['audio/webm','webm'],['audio/ogg;codecs=opus','ogg'],['audio/mp4','m4a']];
UI.voiceRecorder=(o={})=>{
 const MR=window.MediaRecorder,md=navigator.mediaDevices;if(!MR||!md||!md.getUserMedia)return null;
 const kind=VOICE_TYPES.find(([t])=>!MR.isTypeSupported||MR.isTypeSupported(t))||VOICE_TYPES[0],maxSecs=o.maxSecs||300;
 const icon=n=>(window.icon?window.icon(n,16):'');
 const button=document.createElement('button');button.type='button';button.className='btn sm voice-record';
 const idle=()=>{button.innerHTML=icon('mic')+'<span>Record</span>';button.classList.remove('rec');button.setAttribute('aria-pressed','false');button.title='Record a voice note';button.setAttribute('aria-label','Record a voice note');button.disabled=false};idle();
 let rec=null,stream=null,chunks=[],t0=0,timer=null,speech=null,words=[],gone=false;
 const secs=()=>Math.max(1,Math.round((Date.now()-t0)/1000)),clock=n=>Math.floor(n/60)+':'+String(n%60).padStart(2,'0');
 const tick=()=>{const n=secs();button.lastChild.textContent='Stop · '+clock(n);if(n>=maxSecs)stop()};
 const release=()=>{clearInterval(timer);timer=null;stream?.getTracks().forEach(t=>t.stop());stream=null;try{speech?.stop()}catch(_){/* already ended */}speech=null};
 async function listen(){  /* speech to words, only on this computer (Chrome's on-device recognition); else none */
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR||!('processLocally' in SR.prototype)||typeof SR.available!=='function')return;
  if(navigator.webdriver)return;/* a test browser has no on-device speech, and asking it crashed the headless one */
  const lang=o.lang||navigator.language||'en-US';
  try{if(await Promise.race([SR.available({langs:[lang],processLocally:true}),new Promise(r=>setTimeout(()=>r('slow'),1500))])!=='available')return}catch(_){return}
  if(!rec||rec.state!=='recording')return;
  const r=new SR();r.lang=lang;r.processLocally=true;r.continuous=true;r.interimResults=false;
  r.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++)if(e.results[i].isFinal)words.push(e.results[i][0].transcript.trim())};
  r.onerror=()=>{};try{r.start();speech=r}catch(_){/* no words, the sound file is kept */}}
 async function start(){if(rec||gone)return;button.disabled=true;
  try{stream=await md.getUserMedia({audio:true})}catch(e){idle();o.onError?.(e&&e.name==='NotAllowedError'?'The microphone is blocked. Allow it for this page in the browser, then record again.':'No microphone was found.');return}
  if(gone){release();return}
  chunks=[];words=[];try{rec=new MR(stream,{mimeType:kind[0]})}catch(_){rec=new MR(stream)}
  rec.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
  rec.onstop=()=>{const n=secs(),type=rec.mimeType||kind[0];rec=null;release();idle();if(gone||!chunks.length)return;
   const ext=/mp4/.test(type)?'m4a':/ogg/.test(type)?'ogg':'webm',d=new Date(),name='voice-note-'+String(d.getHours()).padStart(2,'0')+String(d.getMinutes()).padStart(2,'0')+'.'+ext;
   const file=new File(chunks,name,{type:type.split(';')[0]});o.onDone?.(file,words.join(' ').trim(),n)};
  rec.start(1000);t0=Date.now();button.disabled=false;button.classList.add('rec');button.setAttribute('aria-pressed','true');button.title='Stop recording';button.setAttribute('aria-label','Stop recording');
  button.innerHTML=icon('stop')+'<span></span>';tick();timer=setInterval(tick,500);listen()}
 function stop(){if(rec&&rec.state!=='inactive'){try{speech?.stop()}catch(_){/* ended */}setTimeout(()=>{if(rec&&rec.state!=='inactive')rec.stop()},speech?400:0)}}
 button.onclick=()=>rec?stop():start();
 return {button,stop,get recording(){return !!rec},destroy(){gone=true;if(rec&&rec.state!=='inactive')rec.stop();release()}};
};
document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('[data-composer-demo]').forEach(root=>UI.composer(root,root.dataset.composerDemo==='voice'?{voice:true,accept:[...DEMO_EXT,'webm','ogg','m4a'],attachLabel:'Add file'}:{})));})();
