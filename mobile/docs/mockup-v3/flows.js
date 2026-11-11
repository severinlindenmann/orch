/* Round 3 product flows. app.js owns the durable message, audio and outbox engine. */
'use strict';
const actionButton = (a, label, value='', cls='wide-btn') => `<button class="${cls}" data-action="${a}" data-value="${esc(value)}">${label}</button>`;
const topicDefaults = {
 ticket:{title:'Q3 summary for the board',status:'Needs your OK',done:4,total:5},
 pil13:{title:'Reconcile October invoices',status:'Working',done:2,total:4},
 pil14:{title:'Plan next week',status:'Open',done:0,total:3},
 rig4:{title:'A new home for Rigi',status:'Needs your OK',done:4,total:5},
 done1:{title:'September close',status:'Done',done:5,total:5},
 stopped1:{title:'Supplier comparison',status:'Stopped',done:2,total:4},
 failed1:{title:'Import the archive',status:"Didn't work",done:1,total:3}
};
state.topics ||= structuredClone(topicDefaults);
state.workspaces ||= {pilatus:{name:'Pilatus'},rigi:{name:'Rigi Shop'},home:{name:'Home'}};
state.topicParents ||= {done1:'pilatus',stopped1:'pilatus',failed1:'pilatus'};
state.topicKeys ||= {done1:'PIL-9',stopped1:'PIL-10',failed1:'PIL-11'};
state.settings.notify ??= true;
function restoreCatalog(){
 Object.entries(state.workspaces).forEach(([id,w])=>{names[id]=w.name;state.messages[id] ||= [];});
 Object.entries(state.topicParents).forEach(([id,w])=>{parent[id]=w;names[id]=state.topicKeys[id];state.messages[id] ||= [msg(uid(),'text',`${state.topics[id]?.status} — ${state.topics[id]?.title}`)];});
}
restoreCatalog();
const artifacts = {
 landing:{title:'Rigi · landing page',kind:'Web page preview'},
 variant:{title:'Rigi · quieter direction',kind:'Web page preview'},
 pdf:{title:'Q3 board summary',kind:'PDF'},
 image:{title:'Launch whiteboard',kind:'Image'},
 pr:{title:'PR #42 · Fix mobile images',kind:'Pull request'},
 commit:{title:'Compress images',kind:'Commit'},
 file:{title:'revenue-q3.csv',kind:'File'},
 url:{title:'Published launch page',kind:'Published link'},
 command:{title:'npm test · 24 checks passed',kind:'Command'},
 note:{title:'Launch readiness',kind:'Note'},
 github:{title:'Launch milestone',kind:'github · github.com'},
 jira:{title:'Launch',kind:'jira · rigi.atlassian.net'},
 teams:{title:'Board review',kind:'teams · teams.microsoft.com'},
 ticket:{title:'Board summary',kind:'Topic · Pilatus'}
};
if(!state.round3Seeded){
 state.messages.rig4.unshift(msg('artifact-landing','artifact','',{artifact:'landing'}));
 state.messages.ticket.unshift(msg('artifact-pdf','artifact','',{artifact:'pdf'}));
 state.messages.ticket.push(msg('free-answer','question','What should the board focus on?',{options:[],questionKind:'Free text'}));
 state.messages.rig4.push(msg('variants','question','Which version should we develop?',{options:['Version A','Version B'],previews:['landing','variant'],recommended:'Version A',questionKind:'Design:comparison'}));
 state.messages.rig4.push(msg('approval','question','Accept the page for publishing?',{options:['Accept','Ask for changes'],previews:['landing'],questionKind:'Accept with preview'}));
 state.messages.ticket.find(m=>m.type==='allow').options=['Allow once','Always','Ignore'];
 state.round3Seeded=true;persist();
}
let topicSegment='Open', currentWorkspace='pilatus', selectedWorkspace=localStorage.getItem('orch-last-workspace')||'pilatus';
let navigationStack=[], viewer=null, newTopicDraft=false, pairingError='', storyTimers=[], storyActive=false;
const baseRender=render, baseChat=renderChat, baseBubble=bubble, baseAnswer=answerHTML, baseReview=review, baseContext=openContext, baseSend=sendMessage;
const workspaces=()=>Object.keys(state.workspaces);
const statusFor=c=>waiting(c)?'Needs your OK':state.topics[c]?.status||'Working';
const topicTitle=c=>state.topics[c]?.title||'New topic';
const waitingQuestions=()=>Object.entries(state.messages).flatMap(([c,ms])=>ms.filter(m=>['question','allow'].includes(m.type)&&!state.answers[m.id]).map(m=>({c,m}))).filter(({c})=>state.workspaces[workspace(c)]);

// Navigation keeps snapshots only during the transform animation; live messages stay in place.
navigate=function(to){
 if(recording)cancelRecord();
 $$('.nav-snapshot').forEach(n=>n.remove());
 const previous={screen,chat,currentWorkspace,html:contentRoot().innerHTML};
 const old=$('#app').cloneNode(true);old.removeAttribute('id');old.classList.add('nav-snapshot');old.setAttribute('aria-hidden','true');old.inert=true;old.querySelectorAll('[id],[data-action]').forEach(n=>{n.removeAttribute('id');n.removeAttribute('data-action');});
 if(screen==='chat')scrolls[chat]=$('#messages')?.scrollTop||0;
 closeModal(true);reply=null;
 if(to==='back'){
  const prev=navigationStack.pop()||{screen:'chats',chat:'pilatus',currentWorkspace:'pilatus'};
  screen=prev.screen;chat=prev.chat;currentWorkspace=prev.currentWorkspace;
 }else{
  if(to!=='chats')navigationStack.push(previous);else navigationStack=[];
  if(state.workspaces[to]){currentWorkspace=to;screen='topics';}
  else if(to.startsWith('general:')){chat=to.slice(8);currentWorkspace=chat;screen='chat';}
  else if(parent[to]){chat=to;currentWorkspace=workspace(to);screen='chat';entryUnread[chat]=state.messages[chat].filter(m=>m.unread).map(m=>m.id);}
  else screen=to;
 }
 render();
 if(!$('#phone').classList.contains('reduce-motion')&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
  $('#app').before(old);const back=to==='back';
  old.animate([{transform:'translateX(0)',opacity:1},{transform:back?'translateX(100%)':'translateX(-25%)',opacity:back?1:.5}],{duration:330,easing:'cubic-bezier(.2,.9,.25,1)'}).onfinish=()=>old.remove();
  $('#app').animate([{transform:back?'translateX(-25%)':'translateX(100%)',opacity:back?.5:1},{transform:'translateX(0)',opacity:1}],{duration:330,easing:'cubic-bezier(.2,.9,.25,1)'});
 }
};
render=function(){
 if(screen==='topics')renderTopics();else if(screen==='start')renderStart();else baseRender();
 renderMini();updateReview();
};
listRows=function(){
 const q=query.toLowerCase();
 if(q)return `<div class="eyebrow">WORKSPACES</div>${workspaces().filter(c=>names[c].toLowerCase().includes(q)).map(workspaceRow).join('')}<div class="eyebrow">CHATS</div>${Object.keys(parent).filter(c=>state.workspaces[parent[c]]&&topicTitle(c).toLowerCase().includes(q)).map(topicRow).join('')}<div class="eyebrow">MESSAGES</div>${Object.entries(state.messages).flatMap(([c,ms])=>ms.filter(m=>(m.text+' '+(m.transcript||'')).toLowerCase().includes(q)).map(m=>actionButton('search-result',`${esc(parent[c]?topicTitle(c):names[c])}<small>${esc(m.text||m.transcript)}</small>`,m.id))).join('')||'<p class="empty">No match on this phone.</p>'}`;
 return workspaces().filter(c=>filter==='All'||filter==='Unread'&&[c,...children(c)].some(k=>unread(k))||filter==='Needs your OK'&&[c,...children(c)].some(waiting)).sort((a,b)=>!!state.workspaces[b].pinned-!!state.workspaces[a].pinned).map(workspaceRow).join('')||'<div class="empty"><img class="quiet-logo" src="logo.svg" alt=""><p>Nothing needs you right now.</p></div>';
};
function workspaceRow(c){
 const ids=[c,...children(c)],ms=ids.flatMap(k=>state.messages[k]||[]).sort((a,b)=>a.at-b.at),last=ms.at(-1),n=ids.reduce((sum,k)=>sum+unread(k),0),w=waitingQuestions().filter(x=>workspace(x.c)===c).length;
 return `<div class="workspace-entry" data-key="${c}"><button class="row-content" data-action="navigate" data-value="${c}">${avatar(c,true)}<span class="fill"><span class="title">${esc(names[c])}${state.workspaces[c].pinned?' · ⌖':''}${state.workspaces[c].muted?' · ◌':''}</span><span class="preview">${esc(ids.map(k=>state.drafts[k]).find(Boolean)?'Draft: '+ids.map(k=>state.drafts[k]).find(Boolean):last?.text||'Say hello to '+names[c])}</span>${w?`<span class="waiting-label">${w===1?'1 needs your OK':w+' need your OK'}</span>`:''}</span><span class="meta">${last?time(last):''}${n?`<span class="badge ${state.workspaces[c].muted?'muted':''}">${n}</span>`:''}</span></button>${btn('navigate','Open workspace','chevron',`data-value="${c}"`)}</div>`;
}
renderChats=function(){
 contentRoot().innerHTML=`<div class="list-head">${btn('navigate','Settings','settings','data-value="settings"')}<h2 data-title="Chats">${title('Chats')}</h2><div>${btn('compose-menu','Compose','plus')}</div></div><div id="mini-slot"></div><div class="search revealed">${icon('search')}<input id="search" placeholder="Search chats and messages" aria-label="Search chats and messages" value="${esc(query)}"></div><div class="chips">${['All','Unread','Needs your OK'].map(f=>actionButton('filter',f,f,`chip ${filter===f?'active':''}`)).join('')}</div>${waitingQuestions().length?`<div class="waiting-strip">${waitingQuestions().slice(0,3).map(({c,m})=>actionButton('search-result',`<small>${esc(names[workspace(c)])} · Needs your OK</small><strong>${esc(m.text)}</strong>`,m.id,'waiting-card')).join('')}${actionButton('all-questions','See all','','waiting-card')}</div>`:''}<div class="scroll" id="chat-list">${workspaces().length?listRows():`<div class="empty"><img class="quiet-logo" src="logo.svg" alt=""><h3>No workspaces</h3><p>Pair a workspace to bring your work here.</p>${actionButton('pair','Pair a workspace')}</div>`}</div>`;
 $('#search').oninput=e=>{query=e.target.value;$('#chat-list').innerHTML=listRows();};
}
function topicRow(c){const t=state.topics[c],m=state.messages[c]?.at(-1);if(!t)return '';return `<button class="row-content topic-row" data-action="navigate" data-value="${c}"><span class="topic-symbol ${statusFor(c)==='Needs your OK'?'amber':''}">#</span><span class="fill"><span class="title">${esc(topicTitle(c))}</span><span class="topic-status ${statusFor(c)==='Needs your OK'?'amber':''}">${esc(topicDay(c))} · ${esc(statusFor(c))}</span><span class="preview">${esc(m?.text||'Updates and results show up here.')}</span></span>${unread(c)?`<span class="badge">${unread(c)}</span>`:icon('chevron')}</button>`;}
function renderTopics(){
 const ids=children(currentWorkspace), finished=['Done','Stopped',"Didn't work"];
 const status=c=>state.topics[c]?.pending?'Working':({'Review':'Ready for review','Open':'Not started','Backlog':'Not started'}[statusFor(c)]||statusFor(c));
 const group=label=>{const topics=ids.filter(c=>status(c)===label);return topics.length?`<section><h3 class="status-group">${esc(label)}</h3><div class="topic-group">${topics.map(topicRow).join('')}</div></section>`:'';};
 const count=ids.filter(c=>finished.includes(status(c))).length;
 contentRoot().innerHTML=nav(names[currentWorkspace],'back',presence(currentWorkspace).label)+`<div class="scroll"><button class="row-content general" data-action="navigate" data-value="general:${currentWorkspace}">${avatar(currentWorkspace)}<span class="fill"><span class="title">Your helper <small>⌖</small></span><span class="preview">Talk to ${esc(names[currentWorkspace])}</span></span>${icon('chevron')}</button>${['Needs your OK','Working','Ready for review','Not started'].map(group).join('')}${count?`<details class="done-topics"><summary id="done-toggle">Done (${count})</summary><div class="topic-group">${ids.filter(c=>finished.includes(status(c))).map(topicRow).join('')}</div></details>`:''}${!ids.length?'<div class="empty"><img class="quiet-logo" src="logo.svg" alt=""><h3>Nothing here yet.</h3><p>Start a topic when you have something to work on.</p></div>':''}</div>${actionButton('new-chat','New topic',currentWorkspace,'wide-btn topic-compose')}`;
}

renderChat=function(){
 baseChat();if(["Didn't work",'Stopped'].includes(statusFor(chat)))$('#composer').insertAdjacentHTML('afterbegin',actionButton('retry-topic','Try again','','wide-btn'));const heading=$('.nav h2');heading.dataset.title=state.topics[chat]?.pending?'Getting started…':parent[chat]?topicTitle(chat):'Your helper';heading.innerHTML=title(heading.dataset.title);
 $('.nav [data-action="navigate"]').dataset.value='back';
 $('.nav .subtitle').innerHTML=chatPresence();
 if(parent[chat])$('.nav').insertAdjacentHTML('afterend',actionButton('checklist',`${state.topics[chat]?.done||0} of ${state.topics[chat]?.total||5} · ${statusFor(chat)} <span>⌄</span>`,'','progress-pin'));
 if(state.pinned?.[chat]&&findMessage(state.pinned[chat]))$('.nav').insertAdjacentHTML('afterend',actionButton('quote','⌖ '+esc(findMessage(state.pinned[chat]).m.text||'Voice memo'),state.pinned[chat],'progress-pin'));
 
};
stamp=function(m){return `<div class="stamp">${m.type==='voice'?actionButton('voice-menu',esc(m.lang||'English')+' ·',m.id,'tiny-language'):''}${time(m)}${m.mine?`<span class="ticks ${m.state}" aria-label="${{pending:'Still on this phone',sent:'Sent',delivered:'On your computer',seen:'Helper started'}[m.state]}">${m.state==='pending'?'◷':m.state==='sent'?'✓':'✓✓'}${m.state==='seen'&&parent[chat]?'<small> Working</small>':''}</span>`:''}</div>`;};

// Artifacts are local renderings: no iframe is allowed to execute scripts or load a URL.
function landingPage(variant=false){return `<!doctype html><html><meta name="viewport" content="width=device-width"><style>body{margin:0;color:#163e34;background:${variant?'#e3eee8':'#f5f1e7'};font:15px Georgia}nav,footer{padding:22px;display:flex;justify-content:space-between;border-bottom:1px solid #b9c7bc}main{padding:36px 25px}small{letter-spacing:2px}h1{font-size:48px;line-height:1.03;font-weight:400;margin:20px 0}p{line-height:1.7}button{background:#174c3d;color:white;border:0;border-radius:30px;padding:14px 24px}.hill{height:140px;border-radius:90% 50% 0 0;background:#588775;margin:30px -25px 0}.prices{display:flex;gap:12px}.prices section{flex:1;padding:16px;background:#fff8;border:1px solid #bacabd;border-radius:12px}h2{font-weight:400}</style><nav><b>rigi.</b><span>Made for the everyday</span></nav><main><small>LESS, BUT BETTER</small><h1>${variant?'A little more space.':'Good things.<br>Simply made.'}</h1><p>Considered essentials for a slower, brighter everyday. Designed in Switzerland, made to stay.</p><button>Explore the collection →</button><div class="hill"></div><h2>Find your everyday.</h2><div class="prices"><section><b>Essentials</b><h2>CHF 29</h2><p>Your daily favourites.</p></section><section><b>Complete</b><h2>CHF 59</h2><p>A little of everything.</p></section></div><p>Thoughtful materials. Less packaging. More possibility.</p></main><footer>rigi. <span>Contact · Our story · © 2026</span></footer></html>`;}
function artifactThumb(id){const a=artifacts[id];if(['landing','variant','url'].includes(id))return `<div class="web-thumb ${id==='variant'?'alternate':''}"><small>rigi. / EVERYDAY ESSENTIALS</small><strong>${id==='variant'?'A little more space.':'Good things. Simply made.'}</strong><span>Explore the collection →</span><i></i></div>`;if(id==='image')return whiteboard();if(id==='pdf')return '<div class="paper-thumb"><small>PILATUS / Q3</small><strong>The quarter,<br>in perspective.</strong><div>▂ ▄ ▆ █</div></div>';return `<div class="evidence-thumb">${icon(id==='pr'?'share':'file')}<strong>${esc(a.title)}</strong><small>${esc(a.kind)} · result</small></div>`;}
function artifactCard(id){return `<button class="artifact-card" data-action="artifact" data-value="${id}">${artifactThumb(id)}<span class="artifact-label"><strong>${esc(artifacts[id].title)}</strong><small>${esc(artifacts[id].kind)}</small><b>Open ↗</b></span></button>`;}
bubble=function(m){if(m.type==='artifact')return artifactCard(m.artifact)+stamp(m);if(m.type==='feedback')return `<strong>Feedback · ${m.pins.length} comments</strong><div class="feedback-thumbs">${m.pins.map((p,i)=>`<div>${artifactThumb(m.artifact)}<b>${i+1}</b></div>`).join('')}</div>${m.pins.map((p,i)=>`<p><b>${i+1}.</b> ${esc(p.text)}${p.voice?' · 🎤':''}</p>`).join('')}${stamp(m)}`;return baseBubble(m);};
answerHTML=function(m){if(state.answers[m.id])return baseAnswer(m);let previews=(m.previews||[]).map(artifactCard).join('');return `<small class="question-kind">${esc(m.questionKind|| (m.type==='allow'?'Permission':'Choose an option'))}</small>${previews?`<div class="question-previews">${previews}</div>`:''}${m.options.length?baseAnswer(m).replace(esc(m.recommended||m.options[0])+'</button>',esc(m.recommended||m.options[0])+' <small>Suggested</small></button>'):`<textarea class="caption-input" data-free-answer="${m.id}" aria-label="Your answer" placeholder="Your answer…"></textarea>${actionButton('free-answer','Send answer',m.id)}`}`;};
function openArtifact(id,keep=false){
 if(!keep)viewer={id,c:chat,pins:[],comment:false,zoom:1};
 const a=artifacts[id];let body;
 if(['landing','variant','url'].includes(id))body=`<iframe title="${esc(a.title)}" sandbox srcdoc="${esc(landingPage(id==='variant'))}"></iframe>`;
 else if(id==='pdf')body=`<div class="pdf-pages">${[1,2,3].map(n=>`<div class="pdf-paper"><small>PILATUS / BOARD REVIEW</small><h2>${['The quarter, in perspective.','Revenue overview','Next quarter'][n-1]}</h2><p>Revenue grew 8%. Online sales grew 12%.</p><div class="pdf-bars"><i></i><i></i><i></i></div><p>Page ${n} of 3</p></div>`).join('')}</div>`;
 else if(id==='image')body=`<div class="zoom-image" style="transform:scale(${viewer.zoom})">${whiteboard()}</div>`;
 else body=`<div class="evidence-body"><small>${esc(a.kind)} · ${['command','commit'].includes(id)?'check':'result'}</small><h2>${esc(a.title)}</h2><p>${id==='pr'?'Mobile image aspect ratio corrected. 3 files changed, +24 −8. All checks passed.':id==='file'?'Month, Revenue CHF, Change\nJuly, 42800, +6%\nAugust, 46200, +9%\nSeptember, 49100, +9%':'Ready for review. Supporting evidence for the launch is attached to this topic.'}</p><pre>${id==='commit'?'+ loading="lazy"\n+ width="1200" height="800"':id==='command'?'✓ 24 passed · 0 failed\nExit code 0':'Reviewed · 6 November 2026'}</pre></div>`;
 sheet(a.title,`<div class="viewer-meta">${esc(a.kind)}${id==='image'?actionButton('zoom','Zoom '+viewer.zoom+'×','','chip'):''}${actionButton('artifact-share','Share','','chip')}</div><p class="pin-hint">${viewer.comment?'Tap a spot to leave a comment.':'Take a look. Tell your helper what you think.'}</p><div class="artifact-stage ${viewer.comment?'comment-mode':''}">${body}${viewer.comment?'<div class="pin-layer" aria-label="Tap preview to add feedback pin" role="button" tabindex="0"></div>':''}${viewer.pins.map((p,i)=>`<button class="feedback-pin" style="left:${p.x*100}%;top:${p.y*100}%" data-action="pin-edit" data-value="${i}" aria-label="Edit comment ${i+1}">${i+1}</button>`).join('')}</div><div id="pin-editor"></div><div class="artifact-actions">${viewer.comment?actionButton('send-feedback',`Send ${viewer.pins.length} comments`,'','wide-btn primary'):actionButton('artifact-approve','👍 Looks good','','wide-btn')+actionButton('comment-mode','Change something','','wide-btn')+actionButton('voice-feedback','🎤 Voice comment','','wide-btn')}</div>`,true);
 const layer=$('.pin-layer');if(layer){layer.onclick=e=>{const r=layer.getBoundingClientRect();editPin({x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height,text:''});};layer.onkeydown=e=>{if(e.key==='Enter')editPin({x:.5,y:.5,text:''});};}
}
function editPin(pin,index=-1){viewer.edit={...pin,index};$('#pin-editor').innerHTML=`<label>Comment ${index<0?viewer.pins.length+1:index+1}<textarea id="pin-text" class="caption-input" placeholder="What should change?">${esc(pin.text)}</textarea></label><div class="pin-editor-actions">${actionButton('pin-voice','🎤 Speak','','chip')}${actionButton('pin-save','Save comment','','chip')}${actionButton('pin-cancel','Cancel','','chip')}</div>`;$('#pin-text').focus();}
function sendFeedback(){if(!viewer.pins.length){toast('Add a comment on the preview first.');return;}const v=viewer;closeModal(true);navigate(v.c);sendMessage('feedback','',{artifact:v.id,pins:v.pins});toast('Feedback sent to your helper');}

// A workspace-scoped composer creates a topic for text, voice and attachments alike.
function newChat(w=selectedWorkspace){selectedWorkspace=state.workspaces[w]?w:workspaces()[0];if(!selectedWorkspace){pair();return;}chat=selectedWorkspace;newTopicDraft=true;sheet('New topic',`<div class="destination-row"><span>To:</span>${actionButton('workspace-picker',esc(names[selectedWorkspace])+' ▾','','destination-button')}</div><footer class="composer" id="composer"></footer><p class="sheet-note">Start something with ${esc(names[selectedWorkspace])}.</p>`);renderComposer();requestAnimationFrame(()=>$('#message-input')?.focus());}
function createTopic(w,text){
 const id='topic-'+uid(),prefix=w==='rigi'?'RIG':w==='pilatus'?'PIL':names[w].slice(0,3).toUpperCase();
 const max=Math.max(12,...Object.keys(parent).filter(c=>parent[c]===w).map(c=>Number(names[c]?.split('-').at(-1))||0));
 state.topicKeys[id]=`${prefix}-${max+1}`;state.topicParents[id]=w;state.topics[id]={title:(text||'Voice request').slice(0,58),status:'Working',pending:true,done:0,total:5};state.messages[id]=[];parent[id]=w;names[id]=state.topicKeys[id];state.textLanguages[id]=state.ownerSpoke[w]||state.textLanguages[w]||'English';state.ownerSpoke[id]=state.ownerSpoke[w]||state.textLanguages[id];persist();return id;
}
sendMessage=function(type,text='',extra={}){
 if(newTopicDraft){
  const w=newTopicDraft?selectedWorkspace:chat;newTopicDraft=false;selectedWorkspace=w;localStorage.setItem('orch-last-workspace',w);
  const id=createTopic(w,text||extra.transcript||(type==='voice'?'A new request by voice':'Shared '+type));closeModal(true);navigate(id);
  $('.nav h2').textContent='Getting started…';
 }
 return baseSend(type,text,extra);
};

// Invitation URLs preserve the existing contract; code entry supplies the local demo relay.
function renderStart(){screen='start';contentRoot().innerHTML=`<div class="onboarding"><img class="quiet-logo" src="logo.svg" alt="orch"><h1>Let's get connected.</h1><p>Use your invitation to bring your workspaces along.</p>${actionButton('scan-invite','Scan invitation QR code','','wide-btn primary')}${actionButton('paste-invite','Paste invitation link')}<p class="sheet-note">Ask the person who invited you for a link or QR code.</p></div>`;}
function pair(){newTopicDraft=false;sheet('Add workspace',`<p class="sheet-note">Use the invitation for your workspace.</p>${actionButton('scan-invite','Scan invitation QR code','','wide-btn primary')}${actionButton('paste-invite','Paste invitation link')}`);}
function scanInvite(){sheet('Scan invitation QR code',`<div class="viewfinder"><div class="qr-art">▦</div><div class="scan-line"></div></div><p class="sheet-note">Point your camera at the invitation.</p>${actionButton('found-invite','Use sample invitation','','wide-btn primary')}<p class="sheet-note">No camera here. Use the invitation link.</p>${actionButton('paste-invite','Paste invitation link')}`,true);}
function pasteInvite(manual=false){sheet(manual?'Enter invitation code':'Paste invitation link',`<label>${manual?'Invitation code':'Invitation link'}<input id="invitation" class="caption-input" placeholder="${manual?'pc_…':'orch://pair?…'}" autocomplete="off"></label><p id="invitation-error" class="error-line" role="alert"></p>${actionButton(manual?'validate-code':'validate-invite','Continue','','wide-btn primary')}`);}
function foundInvite(){sheet('Add Rigi Shop?',`<h2>Add Rigi Shop?</h2><p class="sheet-note">Server: relay.orch.local</p><details><summary>Connection details</summary><p class="sheet-note">Server: relay.orch.local<br>This phone: iPhone · invitation access</p></details><label>Workspace name<input class="caption-input" id="workspace-name" value="Rigi Shop" maxlength="40"></label><p id="pair-error" class="error-line" role="alert"></p>${actionButton('connect-phone','Add workspace','','wide-btn primary')}`);}
async function connectPhone(){const epoch=reviewEpoch;
 if(pairingError||!online()){$('#pair-error').textContent=pairingError==='expired'?'This invitation has expired or was already used. Ask the person who invited you for a new one.':"Can't reach the server. Check your connection, then tap Connect this phone again.";return;}
 const name=$('#workspace-name').value.trim()||'Studio';$('[data-action="connect-phone"]').textContent='Connecting this phone…';await delay(800);if(epoch!==reviewEpoch)return;
 state.signedOut=false;const id='workspace-'+uid();state.workspaces[id]={name};state.messages[id]=[];names[id]=name;persist();
 sheet("You're connected.",`<div class="pair-success">✓</div><h2>You're connected.</h2><p class="sheet-note">${workspaces().length} workspaces are ready.</p><div class="setting-block"><h3>Know when you're needed.</h3><p class="sheet-note">Get notified when your work needs an answer.</p><p>${workspaces().map(c=>esc(names[c])).join(' · ')}</p></div>${actionButton('allow-notifications','Allow notifications','','wide-btn primary')}${actionButton('finish-pair','Not now')}`);
}
renderSettings=function(){
 contentRoot().innerHTML=nav('Settings','chats')+`<div class="scroll settings-body"><p class="sheet-note">Your connection, in one place.</p><h3>Connection</h3><div class="setting-block">${actionButton('connection-details',`<span>Your workspace server<small>${phase?'● Checking…':online()? '● Connected · last updated just now':"● Can't reach the server"}</small></span><span>Details ›</span>`,'','setting-row')}</div><h3>Your workspaces · ${workspaces().length}</h3><div class="setting-block">${workspaces().map(c=>actionButton('manage-workspace',`<span>${esc(names[c])}<small>${presenceHTML(c)}</small></span><span>›</span>`,c,'setting-row')).join('')}${actionButton('pair','Add workspace +','','setting-row')}</div><h3>Preferences</h3><div class="setting-block">${actionButton('global-voice','<span>Voice</span><span>›</span>','','setting-row')}${actionButton('notify-toggle',`<span>Notify me when I'm needed</span><span class="ios-toggle ${state.settings.notify?'on':''}"></span>`,'','setting-row')}</div>${actionButton('signout','Sign out','','wide-btn danger')}<p class="settings-footer"><img src="logo.svg" alt=""> orch for iOS · 3.0 (mockup)</p></div>`;
};
renderInfo=function(){
 const ms=state.messages[chat]||[],ids=tab==='Artifacts'?ms.filter(m=>m.type==='artifact').map(m=>m.artifact):tab==='Files'?ms.filter(m=>m.type==='file').map(m=>m.text.endsWith('.pdf')?'pdf':'file'):ms.filter(m=>m.type==='link').map(()=> 'url');
 contentRoot().innerHTML=nav('Chat info','back')+`<div class="scroll info-body"><div class="info-profile"><h2>${esc(parent[chat]?topicTitle(chat):names[chat])}</h2><p>${parent[chat]?statusFor(chat):'Online'} · Updated just now</p></div><div class="setting-block"><details><summary>Details</summary><p class="sheet-note">${parent[chat]?esc(names[chat])+' · ':''}${esc(names[workspace(chat)])}</p></details><p>Summary</p><p class="sheet-note">${state.topics[chat]?.done||0} tasks complete. ${parent[chat]?statusFor(chat):children(chat).length+' topics'}</p>${actionButton('chat-voice',`<span>Voice & reply language</span><span>›</span>`,'','setting-row')}</div><div class="info-tabs">${['Artifacts','Files','References'].map(t=>actionButton('info-tab',t,t,tab===t?'active':'')).join('')}</div>${ids.map(artifactCard).join('')||'<p class="empty">Nothing shared yet.</p>'}</div>`;
};
openContext=function(id){baseContext(id);const m=findMessage(id)?.m;if(!m)return;$('.context-menu').insertAdjacentHTML('beforeend',`${['Forward','Pin','Select','Delete','Info'].map(a=>actionButton('message-'+a.toLowerCase(),a,id,'')).join('')}${m.mine&&m.type==='voice'?actionButton('voice-menu','Correct language / Edit',id,''):''}`);$('.sheet').style.maxHeight=($('#overlay').clientHeight-parseFloat($('.sheet').style.top||0)-12)+'px';};
function voiceMenu(id){sheet('Voice note',`${actionButton('language','Correct language',id)}${actionButton('edit','Edit transcript',id)}${actionButton('message-info','Info',id)}`);}
const reviewGroups=[
 ['Start',[['start','Onboarding'],['pair-found','Invitation ready'],['empty','No workspaces'],['loading','Loading & retry']]],
 ['Chats',[['chats','Workspaces'],['search-demo','Search messages']]],
 ['Workspace topics',[['pilatus','Pilatus · Status groups'],['done-topics','Done / Stopped / Failed']]],
 ['Topic chat',[['ticket','Board summary'],['general','Your helper'],['checklist-demo','Task checklist']]],
 ['Artifacts & feedback',[['artifact-demo','HTML preview'],['feedback-demo','Comment pins'],['gallery','All artifact kinds'],['info','Artifacts · Files · References']]],
 ['Questions',[['question-options','Options'],['question-allow','Permission'],['question-free','Free text'],['question-variants','A / B previews'],['question-approval','Accept preview'],['stale-demo-view','Already answered']]],
 ['Voice',[['rigi-voice','My voice note'],['record','Hold to record'],['locked','Hands-free'],['voice-errors','Capture errors']]],
 ['Media',[['attach','Attachments'],['camera','Camera & scan'],['preview','Photo caption'],['files','Documents'],['location','Location']]],
 ['New topic',[['new-chat-demo','Choose & compose']]],
 ['Add workspace',[['pair-demo','QR / invitation link'],['pair-errors','Pairing errors']]],
 ['Settings',[['settings','Connection & workspaces'],['voice-settings-demo','Voice defaults'],['signed-out','Signed out · 401']]],
 ['Offline',[['offline','Durable outbox'],['computer-off-demo','Computer asleep']]],
 ['Push',[['push','Question / result / failure / stopped / text']]]
];
updateReview=function(key=reviewKey){reviewKey=key;$('#screen-nav').innerHTML=reviewGroups.map(([group,items])=>`<div class="review-group"><h3>${group}</h3>${items.map(([id,label])=>actionButton('review',label,id,`screen-button ${id===reviewKey?'active':''}`)).join('')}</div>`).join('');$('#why').innerHTML='<li>Workspace → topics → conversation. General stays a conversation; New topic starts focused work.</li><li>Open artifacts, place pins, and send all comments as one message.</li><li>Receipts show sent, on your computer, and helper started.</li>';$('#offline').checked=state.offline;$('#computer').checked=!state.computerOn;$('#network-label').textContent=state.offline?'Offline · saved on this phone':'Online · up to date';$('#owner-language').value=state.ownerSpoke[chat]||lastLanguage(chat)||'English';};
review=function(key){
 resetReviewState();if(recording)cancelRecord();closeModal(true);newTopicDraft=false;
 const questionTargets={'question-options':['ticket','t4'],'question-allow':['ticket','t5'],'question-free':['ticket','free-answer'],'question-variants':['rig4','variants'],'question-approval':['rig4','approval']};
 if(key==='chats'){query='';filter='All';navigate('chats');}
 else if(questionTargets[key]){const [c,id]=questionTargets[key];navigate(c);jumpTo(id);}
 else if(key==='start')navigate('start');
 else if(key==='pair-found')foundInvite();
 else if(key==='empty'){navigate('chats');$('#chat-list').innerHTML='<div class="empty"><img src="logo.svg" class="quiet-logo" alt=""><h3>No workspaces</h3><p>Pair a workspace to bring your work here.</p>'+actionButton('pair','Pair a workspace')+'</div>';$('.waiting-strip')?.remove();}
 else if(key==='loading'){navigate('chats');$('#chat-list').innerHTML='<div class="skeleton"></div><div class="skeleton"></div><p class="error-line">⚠︎ Could not load your chats.</p>'+actionButton('retry-list','Try again');}
 else if(key==='search-demo'){navigate('chats');$('#search').value=query='summary';$('#chat-list').innerHTML=listRows();}
 else if(key==='done-topics'){topicSegment='Done';navigate('pilatus');}
 else if(key==='pilatus'){topicSegment='Open';navigate('pilatus');}
 else if(key==='general')navigate('general:pilatus');
 else if(key==='checklist-demo'){navigate('ticket');showChecklist();}
 else if(key==='artifact-demo'){navigate('rig4');openArtifact('landing');}
 else if(key==='feedback-demo'){navigate('rig4');openArtifact('landing');viewer.comment=true;openArtifact('landing',true);}
 else if(key==='gallery')artifactGallery();
 else if(key==='info'){tab='Artifacts';navigate('ticket');navigate('info');}
 else if(key==='rigi-voice'){navigate('general:rigi');jumpTo('r2');}
 else if(key==='stale-demo-view'){state.answers.t4={value:'In the total',stale:true};navigate('ticket');jumpTo('t4');}
 else if(key==='voice-errors')showVoiceErrors();
 else if(key==='new-chat-demo')newChat();
 else if(key==='pair-demo')pair();
 else if(key==='pair-errors'){pair();$('#pair-debug').hidden=false;}
 else if(key==='voice-settings-demo'){navigate('settings');scope='global';navigate('voice-settings');}
 else if(key==='signed-out'){navigate('start');toast('This phone was signed out. Open the invitation you were sent to connect again.');}
 else if(key==='settings')navigate('settings');
 else if(key==='computer-off-demo'){state.computerOn=false;persist();navigate('ticket');}
 else if(key==='push'){navigate('push');}
 else if(['record','locked','attach','camera','preview','files','location','offline'].includes(key)){
  navigate('ticket');
  if(key==='record'||key==='locked')startRecord(key==='locked');
  else if(key==='attach')attach();else if(key==='camera')camera();else if(key==='preview')preview();else if(key==='files')files();else if(key==='location')showLocation();
  else {setOffline(true);if(!state.messages.ticket.some(m=>m.demoQueue)){sendMessage('text','Please check these when you’re back.',{demoQueue:true});sendMessage('voice','',{demoQueue:true,clip:'me-en-note',lang:'English',transcript:transcripts['me-en-note']});sendMessage('photo','The board notes.',{demoQueue:true,upload:15});}scrollBottom();}
 }else baseReview(key);
 updateReview(key);
};
function artifactGallery(){sheet('Artifacts & evidence',Object.entries(artifacts).map(([id])=>artifactCard(id)).join(''),true);}
function showChecklist(){sheet('Tasks',`<p class="sheet-note">${esc(topicTitle(chat))} · ${statusFor(chat)}</p>${['Read source material','Check the figures','Prepare the draft','Run checks','Get your approval'].map((t,i)=>`<div class="checklist-row"><span>${i<(state.topics[chat]?.done||0)?'✓':'○'}</span>${t}</div>`).join('')}`);}
function showVoiceErrors(){sheet('Microphone',`${['Allow the microphone in Settings to dictate.','Could not start the microphone.','Too many recordings in a row. Wait a moment and try again.','That recording is too long. Keep it under 2 minutes.'].map(t=>`<div class="error-line">⚠︎ ${t}</div>`).join('')}${actionButton('record-retry','Try again')}`);}
renderPush=function(){
 const kinds=[['question','Q3 summary: Marketingkosten separat zeigen?'],['result','Launch: Preview is ready'],['failure','Import: Didn’t work'],['stopped','Suppliers: Stopped'],['text','Q3 summary: The figures are ready.']];
 contentRoot().innerHTML=`<div class="lockscreen scroll"><div class="lock-date">Friday, 6 November</div><div class="lock-time">14:02</div>${kinds.map(([kind,text])=>`<button class="notification" data-action="open-push-kind" data-value="${kind}"><div class="notification-head"><img src="logo.svg" alt="">orch <span>now</span></div><strong>${text}</strong><small>Tap to open</small></button>`).join('')}<p class="notification-hint">Quiet while working. Notified when you’re needed.</p></div>`;
};
// Extra actions are separate from the message engine's delegated handler.
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el||el.disabled)return;const a=el.dataset.action,v=el.dataset.value;
 switch(a){
 case 'compose-menu':sheet('Compose',`${actionButton('new-chat','New topic')}${actionButton('pair','Add workspace')}`);break;
 case 'new-chat':newChat(v||selectedWorkspace);break;
 case 'pick-workspace':if(recording)cancelRecord();newChat(v);break;
 case 'topic-segment':topicSegment=v;renderTopics();enhanceScreen();break;
 case 'checklist':showChecklist();break;
 case 'retry-topic':state.topics[chat].status='Working';persist();sendMessage('text','Please try this task again.');renderChat();break;
 case 'search-result':{const f=findMessage(v);if(f){navigate(parent[f.c]?f.c:'general:'+f.c);jumpTo(v);}break;}
 case 'retry-list':query='';renderChats();break;
 case 'artifact':openArtifact(v);break;
 case 'artifact-gallery':artifactGallery();break;
 case 'quicklook':{const m=findMessage(v)?.m;if(m)openArtifact(m.text.endsWith('.pdf')?'pdf':m.text.endsWith('.svg')?'image':'file');break;}
 case 'comment-mode':viewer.comment=true;openArtifact(viewer.id,true);break;
 case 'view-photo':openArtifact('image');break;
 case 'zoom':viewer.zoom=viewer.zoom===1?2:1;openArtifact(viewer.id,true);break;
 case 'pin-edit':editPin(viewer.pins[+v],+v);break;
 case 'pin-cancel':$('#pin-editor').innerHTML='';delete viewer.edit;break;
 case 'pin-voice':viewer.edit.voice=true;$('#pin-text').value=replyLanguage(viewer.c)==='German'?'Bitte die Überschrift kürzen.':'Please make this heading shorter.';toast('Voice comment transcribed');break;
 case 'pin-save':{const text=$('#pin-text').value.trim();if(!text){toast('Write or speak a comment first.');break;}const {index,...p}=viewer.edit;p.text=text;if(index<0)viewer.pins.push(p);else viewer.pins[index]=p;updatePins();break;}
 case 'voice-feedback':viewer.comment=true;openArtifact(viewer.id,true);editPin({x:.5,y:.25,text:'',voice:true});toast('Tap Speak to record your comment');break;
 case 'send-feedback':sendFeedback();break;
 case 'artifact-approve':{const id=viewer.id,c=viewer.c;closeModal(true);navigate(parent[c]?c:'general:'+c);sendMessage('text','👍 Looks good · '+artifacts[id].title,{artifactRef:{id,rev:1}});break;}
 case 'artifact-share':sheet('Share artifact',`<p>${esc(artifacts[viewer.id].title)}</p>${actionButton('copy-share','Copy title',artifacts[viewer.id].title)}${actionButton('save-artifact','Save local copy',viewer.id)}`);break;
 case 'save-artifact':if(['landing','variant','url'].includes(v)){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([landingPage(v==='variant')],{type:'text/html'}));a.download='rigi-preview.html';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}else saveFile({text:v==='image'?'whiteboard.svg':v==='file'?'revenue-q3.csv':'q3-summary.pdf'});toast('Saved local copy');break;
 case 'free-answer':answering=v;renderComposer();$('#message-input').focus();break;
 case 'voice-menu':voiceMenu(v);break;
 case 'message-info':{const m=findMessage(v)?.m;if(m)sheet('Message info',`<div class="receipt-list"><p>Sent ${m.state==='pending'?'— waiting for network':time({at:m.sentAt||m.at})}</p><p>On your computer ${['delivered','seen'].includes(m.state)?time({at:m.deliveredAt||m.at}):'— waiting'}</p><p>Started ${m.state==='seen'?time({at:m.startedAt||m.at+60000}):'— waiting'}</p></div>`);break;}
 case 'message-delete':{const f=findMessage(v);if(f){state.messages[f.c]=state.messages[f.c].filter(m=>m.id!==v);$('#msg-'+v)?.remove();persist();closeModal();}break;}
 case 'message-select':closeModal(true);$('#msg-'+v)?.classList.toggle('selected-message');toast('Message selected');break;
 case 'message-pin':state.pinned ||= {};state.pinned[chat]=v;persist();closeModal(true);$('.progress-pin')?.insertAdjacentHTML('afterend',actionButton('quote','⌖ '+esc(findMessage(v).m.text||'Voice memo'),v,'progress-pin'));break;
 case 'message-forward':menuMessage=v;sheet('Forward to topic',Object.keys(parent).filter(c=>state.workspaces[parent[c]]).map(c=>actionButton('forward-to',esc(topicTitle(c)),c)).join(''));break;
 case 'forward-to':{const m=findMessage(menuMessage)?.m;if(m){navigate(v);sendMessage(m.type,m.text,{clip:m.clip,lang:m.lang,transcript:m.transcript,artifact:m.artifact,pins:m.pins});}break;}
 case 'pair':pair();break;
 case 'scan-invite':scanInvite();break;
 case 'paste-invite':pasteInvite();break;
 case 'manual-invite':pasteInvite(true);break;
 case 'found-invite':foundInvite();break;
 case 'validate-code':case 'validate-invite':{const input=$('#invitation').value.trim();let valid=false;if(a==='validate-code')valid=/^pc_[A-Za-z0-9_-]{22}$/.test(input);else try{const u=new URL(input);valid=u.protocol==='orch:'&&u.hostname==='pair'&&/^https?:/.test(u.searchParams.get('relay')||'')&&/^pc_[A-Za-z0-9_-]{22}$/.test(u.searchParams.get('code')||'');}catch{}if(valid)foundInvite();else $('#invitation-error').textContent=!input?'Paste the link you were sent first. It starts with orch://.':'That link does not look right. Check you copied the whole link, or ask the person who invited you for a new one.';break;}
 case 'connect-phone':connectPhone();break;
 case 'stage-pair-error':pairingError=v;foundInvite();break;
 case 'allow-notifications':state.settings.notify=true;query='';filter='All';persist();navigate('chats');toast('Notifications allowed');break;
 case 'finish-pair':query='';filter='All';navigate('chats');break;
 case 'notify-toggle':state.settings.notify=!state.settings.notify;persist();renderSettings();break;
 case 'connection-details':sheet('Connection details',`<div class="setting-block"><p class="sheet-note">Server</p><p>relay.orch.local</p><p class="sheet-note">This phone</p><p>iPhone · connected</p></div><p class="sheet-note">Access is managed by whoever invited you.</p>${actionButton('check-connection','Check connection')}`);break;
 case 'check-connection':{const epoch=reviewEpoch;toast('Checking…');await delay(700);if(epoch===reviewEpoch)toast(online()?'Connected · last updated just now':"Can't reach the server");break;}
 case 'manage-workspace':sheet('Workspace',`<label>Name<input id="rename-workspace" class="caption-input" value="${esc(names[v])}"></label>${actionButton('rename-workspace','Save name',v)}${actionButton('mute-workspace',state.workspaces[v].muted?'Unmute workspace':'Mute workspace',v)}${actionButton('remove-workspace','Remove workspace',v,'wide-btn danger')}`);break;
 case 'rename-workspace':{const name=$('#rename-workspace').value.trim();if(!name){toast('Enter a name');break;}state.workspaces[v].name=names[v]=name;persist();closeModal(true);render();break;}
 case 'remove-workspace':sheet('Remove workspace?',`<p>Remove ${esc(names[v])} from this phone? You can pair it again with a new invitation.</p>${actionButton('confirm-remove','Remove workspace',v,'wide-btn danger')}${actionButton('close','Cancel')}`);break;
 case 'confirm-remove':delete state.workspaces[v];persist();closeModal(true);navigate('settings');break;
 case 'workspace-menu':sheet(names[v],`${actionButton('pin-workspace',state.workspaces[v].pinned?'Unpin':'Pin',v)}${actionButton('unread-workspace','Mark unread',v)}${actionButton('mute-workspace',state.workspaces[v].muted?'Unmute':'Mute',v)}${actionButton('manage-workspace','Workspace settings',v)}`);break;
 case 'pin-workspace':state.workspaces[v].pinned=!state.workspaces[v].pinned;persist();closeModal(true);renderChats();break;
 case 'mute-workspace':sheet('Mute workspace', ['1 h','Until tomorrow','Always','Unmute'].map(t=>actionButton('mute-duration',t,v+'|'+t)).join(''));break;
 case 'unread-workspace':{const m=[v,...children(v)].flatMap(c=>state.messages[c]).findLast(m=>!m.mine);if(m)m.unread=true;persist();closeModal(true);renderChats();break;}
 case 'signout':sheet('Disconnect this phone?',`<p>You will need a new invitation to connect again.</p>${actionButton('confirm-signout','Sign out of this phone','','wide-btn danger')}${actionButton('close','Cancel')}`);break;
 case 'confirm-signout':state.signedOut=true;persist();navigate('start');break;
 case 'record-retry':closeModal(true);navigate('ticket');startRecord(true);break;
 case 'open-push-kind':{const targets={question:['ticket','t4'],result:['rig4','artifact-landing'],failure:['failed1',null],stopped:['stopped1',null],text:['general:pilatus','p6']};const [c,id]=targets[v];navigate(c);if(id)jumpTo(id);break;}
 case 'story':playStory();break;
 case 'stop-story':stopStory();break;
 }
});
// The story is deliberately 60 seconds and can be interrupted from the review panel.
function stopStory(){storyTimers.forEach(clearTimeout);storyTimers=[];storyActive=false;$('#story-status').textContent='Demo stopped';}
function playStory(){
 stopStory();storyActive=true;state.offline=false;state.computerOn=true;phase='';state.ownerSpoke.rigi='English';persist();navigate('chats');
 let storyChat;const cue=(seconds,label,fn)=>storyTimers.push(setTimeout(()=>{if(!storyActive)return;$('#story-status').textContent=`${seconds}s / 60s · ${label}`;fn();},seconds*1000));
 cue(1,'Start a new topic',()=>newChat('rigi'));
 cue(5,'Record a request',()=>startRecord(true));
 cue(10,'Send voice note',()=>{sendRecord();storyChat=chat;});
 cue(14,'Your computer received it',()=>toast('✓✓ On your computer'));
 cue(18,'Helper is working',()=>{state.topics[storyChat].done=4;renderChat();});
 cue(25,'A preview arrives',()=>{addMessage(storyChat,{type:'artifact',artifact:'landing'});scrollBottom();});
 cue(30,'Review the page',()=>openArtifact('landing'));
 cue(35,'Leave feedback',()=>{viewer.comment=true;openArtifact('landing',true);});
 cue(39,'Pin the headline',()=>{viewer.pins.push({x:.42,y:.24,text:'Make the headline shorter.',anchor:{selector:'.html-document h1',text_quote:'Good things. Simply made.',scroll_offset:0}});openArtifact('landing',true);});
 cue(43,'Pin the pricing',()=>{viewer.pins.push({x:.72,y:.72,text:'Mention that delivery is included.',voice:true,voice_blob_id:'local-story-voice',transcript:'Mention that delivery is included.',anchor:{selector:'.html-document .prices',text_quote:'Essentials CHF 29',scroll_offset:600}});openArtifact('landing',true);});
 cue(47,'Send comments together',sendFeedback);
 cue(54,'Helper responds in your language',()=>{addMessage(storyChat,{type:'text',text:'I’ll shorten the headline and add delivery to the pricing. Here’s the launch summary.'});addMessage(storyChat,{type:'voice',clip:'agent-en-memo',lang:'English'});scrollBottom();});
 cue(60,'Complete',()=>{storyActive=false;toast('Full story complete');});
}
$('.review-controls').insertAdjacentHTML('beforebegin',`${actionButton('story','▶ Play the full story · 60 seconds','','wide-btn primary')}${actionButton('stop-story','Stop demo','','chip')}<p id="story-status" class="sheet-note">Voice → topic → preview → feedback → memo</p>`);
if(state.signedOut)screen='start';
render();

// Reset the versioned store atomically, including workspace/topic metadata.
document.addEventListener('click',e=>{const a=e.target.closest('[data-action]')?.dataset.action;if(a==='reset'){e.stopImmediatePropagation();localStorage.removeItem(STORE);location.reload();}if(a==='close'&&newTopicDraft){if(recording)cancelRecord();newTopicDraft=false;}},true);
