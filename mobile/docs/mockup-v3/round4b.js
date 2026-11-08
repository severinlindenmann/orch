/* Shared motion, focus and geometry policy. Relay remains a local simulation. */
document.addEventListener('scroll',e=>{if(e.target.id==='chat-list')lastListInteraction=Date.now();},true);
document.addEventListener('pointerdown',e=>{if(e.target.closest('#chat-list')){listTouch=true;lastListInteraction=Date.now();}});
for(const type of ['pointerup','pointercancel'])document.addEventListener(type,()=>{listTouch=false;lastListInteraction=Date.now();});
paths.moon='M20 14A9 9 0 0 1 10 4a9 9 0 1 0 10 10';
paths.check='m5 12 4 4L19 6';paths.clock='M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0';
const polishListRows=listRows;
listRows=function(){const html=polishListRows();return html.includes('Nothing needs you right now')?`<div class="empty"><h3>${filter==='Unread'?'No unread chats':'All caught up'}</h3><p>${filter==='Unread'?'You’ve read every conversation.':'There are no questions waiting for you.'}</p>${actionButton('filter','Show all chats','All','text-button')}</div>`:html;};
const composerObserver=new ResizeObserver(entries=>{for(const {target} of entries){const page=target.closest('.screen-page');if(page)page.style.setProperty('--composer-height',target.getBoundingClientRect().height+'px');}});
const polishComposer=renderComposer;
renderComposer=function(){polishComposer();const c=$('#composer');if(c)composerObserver.observe(c);};
document.addEventListener('click',e=>{if(e.target.closest('[data-action="free-answer"],[data-action="reply"],[data-action="new-chat"]'))requestAnimationFrame(()=>$('#message-input')?.focus());});
document.addEventListener('input',e=>{if(e.target.id==='message-input'){const el=e.target;el.style.height='44px';el.style.height=Math.max(44,Math.min(el.scrollHeight,parseFloat(getComputedStyle(el).lineHeight)*5+22))+'px';}});
// Replace status-only glyphs; preserve authored messages and document text.
function polishIcons(){const nodes=document.querySelectorAll('.statusbar>span,.ticks,.selected-answer,.working-receipt,.topic-symbol,.general small,.setting-row small,.workspace-entry .title');for(const node of nodes){for(const child of [...node.childNodes])if(child.nodeType===3&&/[✓◷⟳⌖◌●▮▰#]/.test(child.textContent)){const span=document.createElement('span');span.innerHTML=esc(child.textContent).replace(/✓✓|✓/g,marks=>icon('check').repeat(marks.length)).replace(/◷|⟳|◌|●/g,icon('clock')).replace(/⌖|#/g,icon('chat')).replace(/▮▮▮/g,'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 15h4v6H3zm7-6h4v12h-4zm7-6h4v18h-4z"/></svg>').replace(/▰/g,'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="6" width="18" height="12" rx="2" fill="none" stroke="currentColor"/><path stroke="currentColor" d="M22 10v4"/><path fill="currentColor" d="M4 8h14v8H4z"/></svg>');child.replaceWith(span);}}}
let polishFrame;new MutationObserver(()=>{cancelAnimationFrame(polishFrame);polishFrame=requestAnimationFrame(polishIcons);}).observe(document.getElementById('phone'),{childList:true,subtree:true});
render();
