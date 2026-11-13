/* Shared, collapsed preview switcher. Existing page handlers keep their hooks. */
(()=>{
 const old=document.querySelector('[aria-label="Preview controls"],.preview-controls,.preview-ctl,.pvbar,.pc');
 const pill=document.createElement('details');pill.className='preview-controls shared-preview';pill.setAttribute('aria-label','Preview controls');
 pill.innerHTML='<summary>Preview</summary><div class="preview-options"><button data-preview-state="loaded">Loaded</button><button data-preview-state="loading">Loading</button><button data-preview-state="empty">Empty</button><button data-preview-replay>Replay</button></div>';
 if(old){old.hidden=true;old.style.setProperty('display','none','important');old.classList.remove('preview-controls');}
 (document.querySelector('dialog[open]')||document.body).append(pill);
 pill.addEventListener('click',e=>{const state=e.target.dataset.previewState;if(state){const u=new URL(location);u.searchParams.set('state',state);location.href=u.href;}if(e.target.hasAttribute('data-preview-replay')){const hook=old?.querySelector('[data-replay],#replay,#replay-btn');if(hook)hook.click();else{const main=document.querySelector('main');main.classList.remove('enter','page-enter');void main.offsetWidth;main.classList.add('enter','page-enter')}pill.open=false;}});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')pill.open=false});
 document.addEventListener('click',e=>{if(!pill.contains(e.target))pill.open=false});
})();
