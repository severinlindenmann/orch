/* The single lifecycle for native dialogs, sheets and full-screen viewers. */
(()=>{'use strict';
const UI=window.UI=window.UI||{}, stack=[], nativeShow=HTMLDialogElement.prototype.showModal,nativeClose=HTMLDialogElement.prototype.close;
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
let previousOverflow='', locked=false;
// The page is locked (no scrolling) only while a modal dialog really is open in it. A dialog that a re-render took out of
// the page never fires `close`, so every check drops dead entries first and gives the scrolling back when none is left.
function release(){for(let i=stack.length-1;i>=0;i--)if(!stack[i].isConnected||!stack[i].open)stack.splice(i,1);if(!stack.length&&locked){document.documentElement.style.overflow=previousOverflow;locked=false}if(!stack.length&&document.body?.style?.overflow==='hidden')document.body.style.overflow=''}
const focusables=d=>[...d.querySelectorAll('button,a[href],input,textarea,select,summary,[tabindex]')].filter(n=>!n.disabled&&n.tabIndex>=0&&!n.closest('[inert]')&&n.getClientRects().length);
/* where focus goes back to: the opener, or, when it was an item of a menu that has closed since, that menu's button */
const back=t=>{if(!t?.isConnected||t.closest('[inert]'))return null;if(t.getClientRects().length)return t;const s=t.closest('details')?.querySelector(':scope>summary');return s?.getClientRects().length?s:null};
function prepare(d){if(d.dataset.overlayReady)return;d.dataset.overlayReady='true';d.setAttribute('aria-modal','true');if(!d.hasAttribute('aria-label')&&!d.hasAttribute('aria-labelledby'))d.setAttribute('aria-label',d.querySelector('h1,h2,h3')?.textContent||'Preview');
 /* class ui-bottom-close: the dialog has its own Cancel/Close row at the bottom, so no top × Close (Esc and a click outside still close it) */
 const x=document.createElement('button');x.type='button';x.className='btn outline sm ui-overlay-close';x.textContent=d.classList.contains('ui-fullscreen')?'× Exit full screen':'× Close';x.setAttribute('aria-label',x.textContent.slice(2));x.onclick=()=>d.close();if(!d.classList.contains('ui-bottom-close'))d.prepend(x);
 /* one close button: a dialog's own plain "Close" button repeats the × Close above, so it goes (and its empty row with it) */
 d.querySelectorAll?.('button').forEach(b=>{if(b!==x&&!b.classList.contains('ui-overlay-close')&&b.textContent.trim()==='Close'){const row=b.parentElement;b.remove();if(row&&row!==d&&!row.children.length&&!row.textContent.trim())row.remove()}});
 d.addEventListener('cancel',e=>{e.preventDefault();e.stopImmediatePropagation();d.close()},true);
 d.addEventListener('click',e=>{if(e.target!==d)return;const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){e.stopImmediatePropagation();d.close()}},true);
 d.addEventListener('submit',e=>{if((e.submitter?.formMethod||e.target.method)==='dialog'){e.preventDefault();d.close(e.submitter?.value||'')}},true);
 d.addEventListener('close',()=>{if(!d.open)finish(d)});
}
HTMLDialogElement.prototype.showModal=function(){prepare(this);if(this.open){if(pending.has(this))stopClose(this);return}const from=document.activeElement;this._uiOpener=from;this._uiNear=neighbours(from);this._uiFinished=false;release();if(!locked){previousOverflow=document.documentElement.style.overflow;document.documentElement.style.overflow='hidden';locked=true}stack.push(this);nativeShow.call(this);this.classList.remove('ui-closing');UI.placePreview?.();};
/* The one close lifecycle (ORCH-2060). Cancel, Escape, × Close, a click outside, form method=dialog, orch.close and
   dialog.close() all come here. The dialog fades for the exit token (--dur-exit; none with reduced motion), then it is
   closed for real, leaves the stack and focus goes back, and only then the promise settles: whoever awaits it finds
   dialog.open false, the page no longer inert and focus on the opener. A second close while it fades gets the same
   promise. A Tab pressed while it fades is kept and done from where focus lands, so it reaches the next control. */
const pending=new Map();let queuedTab=0;
const exitMs=()=>{if(reduced())return 0;const ms=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--dur-exit'));return Number.isFinite(ms)?ms:120};
function closeDialog(d,value){if(pending.has(d))return pending.get(d).promise;if(!d.open){if(stack.includes(d))finish(d);return Promise.resolve()}
 prepare(d);let resolve;const promise=new Promise(r=>resolve=r),job={promise,resolve,value};pending.set(d,job);d.classList.add('ui-closing');
 const ms=exitMs();if(ms)job.timer=setTimeout(()=>end(d,job),ms);else end(d,job);return promise}
function end(d,job){if(pending.get(d)!==job)return;if(d.open)nativeClose.call(d,job.value);finish(d);pending.delete(d);job.resolve()}
HTMLDialogElement.prototype.close=function(value){return closeDialog(this,value)};
function stopClose(d){const job=pending.get(d);clearTimeout(job.timer);pending.delete(d);d.classList.remove('ui-closing');job.resolve()}
function finish(d){if(d._uiFinished!==false)return;d._uiFinished=true;const i=stack.indexOf(d);if(i!==-1)stack.splice(i,1);d.classList.remove('ui-closing');delete d.dataset.state;release();UI.placePreview?.();d._uiRestore?.();giveBack(d);const tab=queuedTab;queuedTab=0;if(tab)step(tab)}
/* Where focus goes back: the opener; else the control with its data-key or id (a re-render replaced it); else the
   control that came after it (or before it) when the dialog opened; else the nearest part of the page still there. */
const tabbable=n=>n?.isConnected&&!n.disabled&&!n.closest('[inert]')&&n.getClientRects().length>0&&!n.closest('dialog:not([open])');
const pageFocusables=()=>{const top=UI.overlay.top();return top?focusables(top):[...document.querySelectorAll('button,a[href],input,textarea,select,summary,[tabindex]')].filter(n=>n.tabIndex>=0&&tabbable(n)&&!n.closest('dialog'))};
function neighbours(from){if(!from||from===document.body)return {};const all=pageFocusables(),i=all.indexOf(from),up=[];for(let n=from.parentElement;n&&n!==document.body;n=n.parentElement)up.push(n);return {after:all[i+1],before:all[i-1],up}}
function giveBack(d){const top=UI.overlay.top(),inside=n=>!top||top.contains(n);let t=d._uiOpener;
 if(t&&!t.isConnected){const k=t.dataset?.key,id=t.id;t=(k&&document.querySelector('[data-key="'+CSS.escape(k)+'"]'))||(id&&document.getElementById(id))||null}
 const near=d._uiNear||{};for(const n of [t,back(d._uiOpener),near.after,near.before])if(n&&n!==document.body&&tabbable(n)&&inside(n)){n.focus({preventScroll:true});if(document.activeElement===n)return}
 if(top){(focusables(top)[0]||top).focus({preventScroll:true});return}
 const spot=(near.up||[]).find(n=>n.isConnected&&!n.closest('[inert]'))||document.querySelector('main');if(!spot)return;
 if(!spot.hasAttribute('tabindex')){spot.tabIndex=-1;spot.addEventListener('blur',()=>spot.removeAttribute('tabindex'),{once:true})}spot.focus({preventScroll:true})}
function step(dir){const a=pageFocusables(),from=document.activeElement;let i=a.indexOf(from);
 if(i===-1){const after=from&&a.findIndex(n=>from.compareDocumentPosition(n)&Node.DOCUMENT_POSITION_FOLLOWING);i=dir>0?(after>-1?after-1:a.length-1):(after>-1?after:a.length)}
 const n=a[i+dir];if(n)n.focus()}
/* top(): the dialog the person is in. One that is closing (orch.close waits for its fade, then close() waits again) is
   no longer it: a toast put into it left with it, so a refusal said in a toast was gone at once (ORCH-1771). */
const closing=d=>!d.open||d.isConnected===false||d.classList.contains('ui-closing')||d.dataset?.state==='closing';
UI.overlay={open:d=>d.showModal(),close:(d,value)=>closeDialog(d,value),top:()=>{for(let i=stack.length-1;i>=0;i--)if(!closing(stack[i]))return stack[i]}};
/* Escape closes the dialog the person is in (not one already fading). Tab stays inside it; while the last one fades,
   the Tab waits for focus to come back (see finish), so it never lands on a control that is going away. */
document.addEventListener('keydown',e=>{if(!stack.length)return;const d=UI.overlay.top();if(e.key==='Escape'){if(UI.closePopover?.()) {e.preventDefault();e.stopImmediatePropagation();return}e.preventDefault();e.stopImmediatePropagation();d?.close()}if(e.key==='Tab'){if(!d){e.preventDefault();queuedTab=e.shiftKey?-1:1;return}if(stack.at(-1)!==d&&closing(stack.at(-1))){e.preventDefault();queuedTab=e.shiftKey?-1:1;return}const a=focusables(d),i=a.indexOf(document.activeElement);if(!a.length){e.preventDefault();d.focus()}else if(e.shiftKey&&(i<=0)||!e.shiftKey&&(i===a.length-1||i<0)){e.preventDefault();a[e.shiftKey?a.length-1:0].focus()}}},true);
UI.fullscreen=(node,opener)=>{if(node.closest('.ui-fullscreen')){node.closest('dialog').close();return}const slot=document.createComment('full-screen return');node.before(slot);const d=document.createElement('dialog');d.className='ui-fullscreen';document.body.append(d);d.append(node);d._uiRestore=()=>{slot.replaceWith(node);d.remove()};d.showModal();if(opener){d._uiOpener=opener;d._uiNear=neighbours(opener)}};
function frames(){document.querySelectorAll('iframe').forEach(f=>{if(f.dataset.escapeReady)return;f.dataset.escapeReady='true';const bind=()=>{try{f.contentDocument?.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();UI.overlay.top()?.close()}})}catch{}};f.addEventListener('load',bind);bind();if(f.srcdoc&&!f.srcdoc.includes('ui-preview-escape'))f.srcdoc+='<script id="ui-preview-escape">addEventListener("keydown",e=>{if(e.key==="Escape")parent.postMessage("ui-preview-escape","*")})<\/script>';});}
window.addEventListener('message',e=>{if(e.data==='ui-preview-escape'&&[...document.querySelectorAll('iframe')].some(f=>f.contentWindow===e.source&&UI.overlay.top()?.contains(f)))UI.overlay.top()?.close()});
document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('dialog').forEach(prepare);frames();new MutationObserver(()=>{frames();release()}).observe(document.body,{childList:true,subtree:true});});
})();
