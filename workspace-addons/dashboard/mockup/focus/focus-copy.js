(()=>{
 let timer;
 document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-copy-link]');if(!button)return;
  e.preventDefault();e.stopImmediatePropagation();
  const url=new URL(button.dataset.copyLink,location.href).href;
  let copied=false;
  try{await navigator.clipboard.writeText(url);copied=true}catch{
   const input=document.createElement('textarea');input.value=url;input.style.cssText='position:fixed;opacity:0';(button.closest('dialog')||document.body).append(input);input.select();try{copied=document.execCommand('copy')}catch{}input.remove();button.focus();
  }
  let toast=document.getElementById('focus-copy-toast');if(!toast){toast=document.createElement('p');toast.id='focus-copy-toast';toast.setAttribute('role','status');toast.style.cssText='position:fixed;bottom:64px;left:50%;transform:translateX(-50%);z-index:9999;padding:10px 18px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);box-shadow:var(--lift-shadow)';}
  (button.closest('dialog')||document.body).append(toast);toast.hidden=false;toast.textContent=copied?'Link copied':'Copy unavailable. Select this link: '+url;clearTimeout(timer);if(copied)timer=setTimeout(()=>toast.hidden=true,2400);
 },true);
})();
