/* vendored from drafts-portals/kit (orch-core look) */
/* One icon set (24px grid, 1.75 stroke, currentColor), replaces the mixed unicode glyphs. Usage: icon('check', 16). */
(function () {
  const P = {
    home: '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    webhook: '<circle cx="12" cy="5" r="3"/><path d="m10 8-5 9h14l-4-7"/><circle cx="5" cy="17" r="3"/><circle cx="19" cy="17" r="3"/>',
    swap: '<path d="M3 7h18l-4-4M21 17H3l4 4"/>',
    message: '<path d="M3 4h18v13H8l-5 4z"/>',
    tools: '<path d="m14 6 4-4a6 6 0 0 1-7 8L4 20l-3-3 10-7a6 6 0 0 1 3-8z"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m6 8 4 4-4 4M13 16h5"/>',
    folder: '<path d="M3 5h6l2 3h10v12H3z"/>',
    app: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
    group: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6M15.5 14.2c3 0 5.5 2.2 5.5 5.8"/>',
    workspace: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 4V2M16 4V2M3 10h18M9 10v11"/>',
    key: '<circle cx="8" cy="8" r="5"/><path d="m12 12 9 9M16 16l3-3M19 19l3-3"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    upload: '<path d="M12 16V3M7 8l5-5 5 5M3 16v5h18v-5"/>',
    'chevron-right': '<path d="m9 5 7 7-7 7"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    compare: '<path d="M12 3v18M8 7H4v10h4M16 7h4v10h-4"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
    text: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4"/>',
    test: '<path d="M9 11l2 2 4-4"/><rect x="3" y="3" width="18" height="18" rx="3"/>',
    metric: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    note: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    page: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 8h18"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    up: '<path d="m6 15 6-6 6 6"/>', down: '<path d="m6 9 6 6 6-6"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    send: '<path d="M4 12 20 4l-6 16-3-7z"/>',
  };
  window.icon = (name, size = 16, cls = '') =>
    `<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
})();

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
      const rows = [...el.querySelectorAll('[data-row]')].slice(0,8);
      rows.forEach((row,i) => {row.dataset.stagger='';row.style.setProperty('--row-delay',`${i*20}ms`);});
      el.classList.add('page-enter');
      setTimeout(() => {el.classList.remove('page-enter');rows.forEach(row=>delete row.dataset.stagger);}, 340);
    },
    toast(text, kind='info') {
      let host = document.querySelector('.toasts');
      if (!host) {host=document.createElement('div');host.className='toasts';host.setAttribute('aria-label','Notifications');document.body.append(host);}
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
      const state=overlayState.get(dialog);document.body.style.overflow=document.querySelector('dialog[open]')?'hidden':(state?.overflow==='hidden'?'':state?.overflow||'');state?.trigger?.focus();
    },
    async resolve(row, focusTarget) {
      row.style.setProperty('--row-height',`${row.getBoundingClientRect().height}px`);row.classList.add('row-out');focusTarget?.focus();await wait(reduce()?0:160);row.remove();
    }
  };
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=window.icon(el.dataset.icon,16));
    document.querySelectorAll('[data-open]').forEach(button=>button.addEventListener('click',()=>api.open(button.dataset.open)));
    document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>api.close(button.closest('dialog'))));
    document.querySelectorAll('[role=switch]').forEach(button=>button.addEventListener('click',()=>button.setAttribute('aria-checked',button.getAttribute('aria-checked')!=='true')));
  });
})();
