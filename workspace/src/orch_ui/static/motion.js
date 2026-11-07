/* Local, opt-in motion. No polling, network, or animation on reload. */
(() => {
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const resume = () => delete document.documentElement.dataset.refresh;
  if (performance.getEntriesByType('navigation')[0]?.type === 'reload') document.documentElement.dataset.refresh = '';
  ['pointerdown','keydown'].forEach(type => document.addEventListener(type, resume, {once:true}));
  const overlayState = new WeakMap();
  const loading = new WeakMap();
  const toastQueue = [];
  const drainToasts = () => {
    const host=document.querySelector('.toasts');
    while(host && host.children.length<2 && toastQueue.length) toastQueue.shift()();
  };
  const api = window.orch = {
    enter(el) {
      if (!el || reduce()) return;
      el.classList.remove('page-enter'); void el.offsetWidth;
      const rows = [...el.querySelectorAll('[data-row]:not(.needs-in)')].slice(0,8);
      rows.forEach((row,i) => {row.dataset.stagger='';row.style.setProperty('--row-delay',`${i*20}ms`);});
      el.classList.add('page-enter');
      setTimeout(() => {el.classList.remove('page-enter');rows.forEach(row=>delete row.dataset.stagger);}, 340);
    },
    live: false,
    /* A "needs you" row that arrives while the page is open gets one soft fade. Never on load, reload or
       refresh, and taking the class away again ends the animation, it does not start another one. */
    needsIn(row) {
      if (!row || !api.live || reduce() || document.documentElement.dataset.refresh !== undefined) return false;
      row.classList.add('needs-in');
      row.addEventListener('animationend', () => row.classList.remove('needs-in'), {once:true});
      return true;
    },
    toast(text, kind='info') {
      let host = document.querySelector('.toasts');
      if (!host) {host=document.createElement('div');host.className='toasts';host.setAttribute('role','group');host.setAttribute('aria-label','Notifications');document.body.append(host);}
      const item=document.createElement('div');item.className=`toast ${kind==='error'?'error':''}`;item.dataset.state='opening';item.setAttribute('role',kind==='error'?'alert':'status');
      const mark=document.createElement('span');mark.innerHTML=window.icon?.(kind==='ok'?'check':kind==='error'?'stop':'note',16)||'';
      const copy=document.createElement('span');copy.className='grow';copy.textContent=text;
      const close=document.createElement('button');close.className='btn ghost icon sm';close.setAttribute('aria-label','Dismiss notification');close.innerHTML=window.icon?.('x',16)||'×';
      let timer,remaining=6000,started=0,hovered=false,focused=false;
      const dismiss=()=>{if(item.dataset.state==='closing')return;clearTimeout(timer);item.dataset.state='closing';setTimeout(()=>{item.remove();drainToasts();},reduce()?0:200);};
      const pause=()=>{clearTimeout(timer);if(started){remaining-=Date.now()-started;started=0;}};
      const start=()=>{if(kind!=='error'&&!hovered&&!focused){clearTimeout(timer);started=Date.now();timer=setTimeout(dismiss,Math.max(0,remaining));}};
      close.onclick=dismiss;item.append(mark,copy,close);
      toastQueue.push(()=>{host.append(item);start();});drainToasts();
      item.onmouseenter=()=>{hovered=true;pause();};item.onmouseleave=()=>{hovered=false;start();};
      item.onfocusin=()=>{focused=true;pause();};item.onfocusout=()=>{focused=false;start();};
      return item;
    },
    async skeleton(el, ms=900) {
      if(loading.has(el)) return;
      const token={shown:false};loading.set(el,token);el.setAttribute('aria-busy','true');
      const timer=setTimeout(()=>{
        token.shown=true;token.at=performance.now();
        const bounds=el.getBoundingClientRect();
        const cover=document.createElement('div');cover.className='skeleton-cover';cover.setAttribute('aria-hidden','true');cover.inert=true;
        /* Measure the real text/icon blocks; keep the actual layout in place. */
        el.querySelectorAll('h1,h2,h3,p,svg,.btn,.chip').forEach(node=>{
          const box=node.getBoundingClientRect();if(!box.width||!box.height)return;
          const block=document.createElement('span');block.className='skeleton';
          Object.assign(block.style,{position:'absolute',left:`${box.left-bounds.left}px`,top:`${box.top-bounds.top}px`,width:`${box.width}px`,height:`${box.height}px`});cover.append(block);
        });
        el.classList.add('skeleton-region');el.append(cover);token.cover=cover;
      },120);
      await wait(ms);clearTimeout(timer);
      if(token.shown) await wait(Math.max(0,300-(performance.now()-token.at)));
      token.cover?.remove();el.classList.remove('skeleton-region');el.removeAttribute('aria-busy');loading.delete(el);
    },
    open(dialog) {
      if(typeof dialog==='string') dialog=document.querySelector(dialog);
      if(!dialog || dialog.open) return;
      overlayState.set(dialog,{trigger:document.activeElement,overflow:document.body.style.overflow});document.body.style.overflow='hidden';
      dialog.dataset.state='opening';dialog.showModal();
      dialog.oncancel=e=>{e.preventDefault();api.close(dialog);};
    },
    async close(dialog) {
      if(typeof dialog==='string') dialog=document.querySelector(dialog);
      if(!dialog?.open || dialog.dataset.state==='closing') return;
      dialog.dataset.state='closing';await wait(reduce()?0:200);dialog.close();delete dialog.dataset.state;
      const state=overlayState.get(dialog);document.body.style.overflow=state?.overflow||'';state?.trigger?.focus();
    },
    async resolve(row, focusTarget) {
      row.style.setProperty('--row-height',`${row.getBoundingClientRect().height}px`);row.classList.add('row-out');focusTarget?.focus();await wait(reduce()?0:160);row.remove();
    }
  };
  window.addEventListener('load',()=>setTimeout(()=>{api.live=true;},0));
  document.addEventListener('DOMContentLoaded',()=>{
    const nav=performance.getEntriesByType('navigation')[0];
    if(nav?.type!=='reload' && document.referrer && new URL(document.referrer).pathname!==location.pathname) api.enter(document.querySelector('main'));
    document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=window.icon(el.dataset.icon,16));
    document.querySelectorAll('[data-open]').forEach(button=>button.addEventListener('click',()=>api.open(button.dataset.open)));
    document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>api.close(button.closest('dialog'))));
    document.querySelectorAll('[role=switch]').forEach(button=>button.addEventListener('click',()=>button.setAttribute('aria-checked',button.getAttribute('aria-checked')!=='true')));
  });
})();
