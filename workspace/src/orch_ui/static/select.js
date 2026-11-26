/* Native select remains the form value and validation source. */
(()=>{'use strict';const UI=window.UI=window.UI||{};let active=null,uid=0;const controls=new Map();
function close(restore=true){if(!active)return false;const {button,pop}=active;pop.hidePopover();button.setAttribute('aria-expanded','false');active=null;if(restore)button.focus();return true}
UI.closeSelect=close;
const printable=e=>[...e.key].length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!e.isComposing;
/* Type to jump, as in a native select: keys typed within `wait` ms form one prefix ("SALES-097"), searched from the
   focused item on; one key pressed again and again cycles through the items starting with it; a pause starts over. */
function typeahead(wait=1000,now=()=>Date.now()){let buf='',at=-Infinity;
 return {reset(){buf=''},typing:()=>buf!==''&&now()-at<=wait,
  find(key,labels,cur){const t=now();if(t-at>wait)buf='';at=t;buf+=key.toLocaleLowerCase();
   const same=[...buf].every(c=>c===buf[0]),q=same?buf[0]:buf,n=labels.length,from=same?cur+1:Math.max(cur,0);
   for(let k=0;k<n;k++){const i=(from+k)%n;if(String(labels[i]??'').trimStart().toLocaleLowerCase().startsWith(q))return i}return -1}}}
function enhance(s){if(controls.has(s)||s.hidden||s.multiple||s.closest('[inert],.loading-copy'))return;
 const had=document.activeElement===s;const wrapper=document.createElement('span');wrapper.className='ui-select';s.before(wrapper);wrapper.append(s);s.classList.add('ui-native-select');s.tabIndex=-1;s.setAttribute('aria-hidden','true');
 const button=document.createElement('button');button.type='button';button.className='ui-select-trigger';button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');const pop=document.createElement('div');pop.className='ui-select-list';pop.id='ui-list-'+(++uid);pop.setAttribute('popover','manual');pop.setAttribute('role','listbox');button.setAttribute('aria-controls',pop.id);wrapper.append(button,pop);
 const label=s.dataset.label||s.getAttribute('aria-label')||[...s.labels||[]].map(l=>[...l.childNodes].filter(n=>n.nodeType===3||n.classList?.contains('sr-only')).map(n=>n.textContent).join(' ').trim()).join(' ')||'Choose';
 pop.setAttribute('aria-label',label);
 function sync(){const t=document.createElement('span');t.className='ui-select-text';t.textContent=(s.dataset.prefix?s.dataset.prefix+': ':'')+(s.selectedOptions[0]?.textContent||'Choose');const c=document.createElement('span');c.className='chev';c.setAttribute('aria-hidden','true');button.replaceChildren(t,c);button.setAttribute('aria-label',label+': '+(s.selectedOptions[0]?.textContent||'Choose'));button.disabled=s.disabled;button.setAttribute('aria-invalid',s.getAttribute('aria-invalid')||'false');if(s.getAttribute('aria-describedby'))button.setAttribute('aria-describedby',s.getAttribute('aria-describedby'));}
 function open(){if(button.disabled)return;close(false);sync();ta.reset();pop.replaceChildren();[...s.options].forEach((o,i)=>{const b=document.createElement('button');b.type='button';b.className='ui-option';b.setAttribute('role','option');b.setAttribute('aria-selected',String(o.selected));b.textContent=o.textContent;if(o.selected){const c=document.createElement('span');c.className='ui-option-check';c.setAttribute('aria-hidden','true');c.textContent=' ✓';b.append(c)}b.dataset.label=o.label||o.textContent;b.disabled=o.disabled;b.onclick=()=>{s.selectedIndex=i;s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));sync();close()};pop.append(b)});active={button,pop};pop.showPopover();const r=button.getBoundingClientRect();pop.style.width=Math.max(r.width,180)+'px';pop.style.left=Math.min(r.left,innerWidth-Math.max(r.width,180)-8)+'px';pop.style.top=Math.max(8,Math.min(r.bottom+4,innerHeight-pop.offsetHeight-8))+'px';button.setAttribute('aria-expanded','true');(pop.querySelector('[aria-selected=true]:not(:disabled)')||pop.querySelector('button:not(:disabled)'))?.focus()}
 const ta=typeahead();
 // typed keys only move focus; Enter, Space or a click on an option is what chooses it (the form value)
 const seek=e=>{const a=[...pop.querySelectorAll('button:not(:disabled)')],i=ta.find(e.key,a.map(b=>b.dataset.label),a.indexOf(document.activeElement));if(i>=0)a[i].focus()};
 button.onclick=()=>active?.button===button?close():open();button.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open()}else if(printable(e)&&e.key!==' '){e.preventDefault();open();seek(e)}};
 pop.onkeydown=e=>{const a=[...pop.querySelectorAll('button:not(:disabled)')],i=a.indexOf(document.activeElement);let n;if(e.key==='Escape'){e.preventDefault();e.stopPropagation();ta.reset();close();return}if(e.key==='Tab'){ta.reset();close(false);return}if(e.key==='ArrowDown')n=(i+1)%a.length;if(e.key==='ArrowUp')n=(i-1+a.length)%a.length;if(e.key==='Home')n=0;if(e.key==='End')n=a.length-1;if(n!==undefined){e.preventDefault();ta.reset();a[n]?.focus()}else if(printable(e)&&(e.key!==' '||ta.typing())){e.preventDefault();seek(e)}};
 s.addEventListener('change',sync);s.addEventListener('invalid',e=>{e.preventDefault();button.setAttribute('aria-invalid','true');button.focus()});s.form?.addEventListener('reset',()=>setTimeout(sync));new MutationObserver(sync).observe(s,{attributes:true,childList:true,subtree:true});controls.set(s,{sync});sync();
 // the native select is hidden: focus given to it (a dialog that opens with select.focus()) goes to the trigger
 s.addEventListener('focus',()=>button.focus());if(had)button.focus();
}
UI.select={enhance,typeahead,sync:()=>controls.forEach(c=>c.sync())};
document.addEventListener('pointerdown',e=>{if(active&&!active.button.contains(e.target)&&!active.pop.contains(e.target))close(false)},true);window.addEventListener('resize',()=>close(false));document.addEventListener('scroll',e=>{if(active&&!active.pop.contains(e.target))close(false)},true);
document.addEventListener('DOMContentLoaded',()=>{const scan=()=>document.querySelectorAll('select').forEach(enhance);scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});document.addEventListener('click',()=>setTimeout(()=>UI.select.sync()));});
})();
