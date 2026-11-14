/* The single lifecycle for native dialogs, sheets and full-screen viewers. */
(()=>{'use strict';
const UI=window.UI=window.UI||{}, stack=[], nativeShow=HTMLDialogElement.prototype.showModal,nativeClose=HTMLDialogElement.prototype.close;
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
let previousOverflow='', locked=false;
// The page is locked (no scrolling) only while a modal dialog really is open in it. A dialog that a re-render took out of
// the page never fires `close`, so every check drops dead entries first and gives the scrolling back when none is left.
function release(){for(let i=stack.length-1;i>=0;i--)if(!stack[i].isConnected||!stack[i].open)stack.splice(i,1);if(!stack.length&&locked){document.documentElement.style.overflow=previousOverflow;locked=false}}
const focusables=d=>[...d.querySelectorAll('button,a[href],input,textarea,select,summary,[tabindex]')].filter(n=>!n.disabled&&n.tabIndex>=0&&!n.closest('[inert]')&&n.getClientRects().length);
function prepare(d){if(d.dataset.overlayReady)return;d.dataset.overlayReady='true';d.setAttribute('aria-modal','true');if(!d.hasAttribute('aria-label')&&!d.hasAttribute('aria-labelledby'))d.setAttribute('aria-label',d.querySelector('h1,h2,h3')?.textContent||'Preview');
 const x=document.createElement('button');x.type='button';x.className='btn outline sm ui-overlay-close';x.textContent=d.classList.contains('ui-fullscreen')?'× Exit full screen':'× Close';x.setAttribute('aria-label',x.textContent.slice(2));x.onclick=()=>d.close();d.prepend(x);
 d.addEventListener('cancel',e=>{e.preventDefault();e.stopImmediatePropagation();d.close()},true);
 d.addEventListener('click',e=>{if(e.target!==d)return;const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){e.stopImmediatePropagation();d.close()}},true);
 d.addEventListener('submit',e=>{if((e.submitter?.formMethod||e.target.method)==='dialog'){e.preventDefault();d.close(e.submitter?.value||'')}},true);
 d.addEventListener('close',()=>{const i=stack.indexOf(d);if(i!==-1)stack.splice(i,1);d.classList.remove('ui-closing');release();UI.placePreview?.();const target=d._uiOpener;if(target?.isConnected&&!target.closest('[inert]'))target.focus({preventScroll:true});else document.querySelector('main')?.focus({preventScroll:true});});
}
HTMLDialogElement.prototype.showModal=function(){prepare(this);if(this.open)return;this._uiOpener=document.activeElement;release();if(!locked){previousOverflow=document.documentElement.style.overflow;document.documentElement.style.overflow='hidden';locked=true}stack.push(this);nativeShow.call(this);this.classList.remove('ui-closing');UI.placePreview?.();};
HTMLDialogElement.prototype.close=function(value){if(!this.open||this.classList.contains('ui-closing'))return;this.classList.add('ui-closing');const d=this;setTimeout(()=>nativeClose.call(d,value),reduced()?0:100)};
UI.overlay={open:d=>d.showModal(),close:d=>d.close(),top:()=>stack.at(-1)};
document.addEventListener('keydown',e=>{const d=stack.at(-1);if(!d)return;if(e.key==='Escape'){if(UI.closePopover?.()) {e.preventDefault();e.stopImmediatePropagation();return}e.preventDefault();e.stopImmediatePropagation();d.close()}if(e.key==='Tab'){const a=focusables(d),i=a.indexOf(document.activeElement);if(!a.length){e.preventDefault();d.focus()}else if(e.shiftKey&&(i<=0)||!e.shiftKey&&(i===a.length-1||i<0)){e.preventDefault();a[e.shiftKey?a.length-1:0].focus()}}},true);
UI.fullscreen=(node,opener)=>{if(node.closest('.ui-fullscreen')){node.closest('dialog').close();return}const slot=document.createComment('full-screen return');node.before(slot);const d=document.createElement('dialog');d.className='ui-fullscreen';document.body.append(d);d.append(node);d.addEventListener('close',()=>{slot.replaceWith(node);d.remove();opener?.focus()},{once:true});d.showModal();d._uiOpener=opener||d._uiOpener;};
function frames(){document.querySelectorAll('iframe').forEach(f=>{if(f.dataset.escapeReady)return;f.dataset.escapeReady='true';const bind=()=>{try{f.contentDocument?.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();stack.at(-1)?.close()}})}catch{}};f.addEventListener('load',bind);bind();if(f.srcdoc&&!f.srcdoc.includes('ui-preview-escape'))f.srcdoc+='<script id="ui-preview-escape">addEventListener("keydown",e=>{if(e.key==="Escape")parent.postMessage("ui-preview-escape","*")})<\/script>';});}
window.addEventListener('message',e=>{if(e.data==='ui-preview-escape'&&[...document.querySelectorAll('iframe')].some(f=>f.contentWindow===e.source&&stack.at(-1)?.contains(f)))stack.at(-1)?.close()});
document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('dialog').forEach(prepare);frames();new MutationObserver(()=>{frames();release()}).observe(document.body,{childList:true,subtree:true});});
})();
