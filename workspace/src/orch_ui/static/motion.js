/* Local, opt-in motion. No polling, network, or animation on reload. */
(() => {
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const resume = () => delete document.documentElement.dataset.refresh;
  if (performance.getEntriesByType('navigation')[0]?.type === 'reload') document.documentElement.dataset.refresh = '';
  ['pointerdown','keydown'].forEach(type => document.addEventListener(type, resume, {once:true}));
  const overlayState = new WeakMap();
  const loading = new WeakMap();
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
      host.replaceChildren();const item=document.createElement('div');item.className=`toast ${kind==='error'?'error':''}`;item.dataset.state='opening';item.setAttribute('role',kind==='error'?'alert':'status');
      const mark=document.createElement('span');mark.innerHTML=window.icon?.(kind==='ok'?'check':kind==='error'?'stop':'note',16)||'';
      const copy=document.createElement('span');copy.className='grow';copy.textContent=text;
      const close=document.createElement('button');close.className='btn ghost icon sm';close.setAttribute('aria-label','Dismiss notification');close.innerHTML=window.icon?.('x',16)||'×';
      let timer,remaining=4000,started=0,hovered=false,focused=false;
      const dismiss=()=>{if(item.dataset.state==='closing')return;clearTimeout(timer);item.dataset.state='closing';setTimeout(()=>item.remove(),reduce()?0:200);};
      const pause=()=>{clearTimeout(timer);if(started){remaining-=Date.now()-started;started=0;}};
      const start=()=>{if(kind!=='error'&&!hovered&&!focused){clearTimeout(timer);started=Date.now();timer=setTimeout(dismiss,Math.max(0,remaining));}};
      close.onclick=dismiss;item.append(mark,copy,close);
      host.append(item);start();
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
      overlayState.set(dialog,{trigger:document.activeElement});
      dialog.dataset.state='opening';dialog.showModal();
      dialog.oncancel=e=>{e.preventDefault();api.close(dialog);};
    },
    async close(dialog) {
      if(typeof dialog==='string') dialog=document.querySelector(dialog);
      if(!dialog?.open || dialog.dataset.state==='closing') return;
      dialog.dataset.state='closing';await wait(reduce()?0:200);dialog.close();delete dialog.dataset.state;
      const state=overlayState.get(dialog);state?.trigger?.focus();
    },
    reduce,
    /* A thing grows or moves from where it was (`from`, a DOMRect) to where it is now: transform and opacity only,
       --dur-slow with --ease-move (draft D's zoom, pin and split). `scale:false` only slides. Still with reduced
       motion, on a refresh and when nothing moved; never blocks input (the element is already in its new place). */
    flip(el, from, o={}) {
      if (!el || !from || !el.animate || reduce() || document.documentElement.dataset.refresh !== undefined) return null;
      el.getAnimations?.().forEach(a => { if (a.id === 'orch-flip') a.cancel(); });
      const to = el.getBoundingClientRect();
      if (!to.width || !to.height || !from.width || !from.height) return null;
      // a move still running (a second pin, a quick close): the caller measured `from` with it, so it stops here first
      const dx = from.left - to.left, dy = from.top - to.top, sx = from.width / to.width, sy = from.height / to.height;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(sx - 1) < .01 && Math.abs(sy - 1) < .01) return null;
      const cs = getComputedStyle(document.documentElement);
      const move = `translate(${dx}px,${dy}px)` + (o.scale === false ? '' : ` scale(${sx},${sy})`);
      const a = el.animate([{transformOrigin:'0 0', transform:move, opacity:o.fade ?? (o.scale === false ? 1 : .6)}, {transformOrigin:'0 0', transform:'none', opacity:1}],
        {duration:parseFloat(cs.getPropertyValue('--dur-slow')) || 240, easing:cs.getPropertyValue('--ease-move').trim() || 'ease-out'});
      a.id = 'orch-flip';
      return a;
    },
    /* Rects of the elements under `root` matching `sel`, by the value of `attr`: what flip() needs from before a repaint. */
    rects(root, sel, attr) {
      const out = new Map();
      root?.querySelectorAll(sel).forEach(el => { const k = el.getAttribute(attr), r = el.getBoundingClientRect(); if (k && r.width && r.height && !out.has(k)) out.set(k, r); });
      return out;
    },
    /* A thing that was just taken out of the page leaves: it stays where it was for --dur-exit, fades and drops 8 px
       with --ease-exit, then goes (ids and data-key removed; kept in `host`, the body by default, so its styles stay). Inert and hidden from screen readers meanwhile; gone at once with reduced motion. */
    leave(el, rect, host=document.body) {
      if (!el || !rect || !rect.width || !el.animate || reduce() || document.documentElement.dataset.refresh !== undefined) return null;
      const cs = getComputedStyle(document.documentElement);
      // only a picture of what was there: no ids or data-key left, so nothing finds it as the real thing
      for (const x of [el, ...el.querySelectorAll('[id], [data-key]')]) { x.removeAttribute('id'); x.removeAttribute('data-key'); }
      el.inert = true; el.setAttribute('aria-hidden', 'true'); el.dataset.leaving = '';
      Object.assign(el.style, {position:'fixed', left:rect.left + 'px', top:rect.top + 'px', width:rect.width + 'px', height:rect.height + 'px',
        margin:'0', zIndex:'90', pointerEvents:'none', animation:'none'});
      host.append(el);
      const a = el.animate([{opacity:1, transform:'none'}, {opacity:0, transform:'translateY(8px)'}],
        {duration:parseFloat(cs.getPropertyValue('--dur-exit')) || 120, easing:cs.getPropertyValue('--ease-exit').trim() || 'ease-in', fill:'forwards'});
      const done = () => el.remove();
      a.onfinish = done; a.oncancel = done;
      return a;
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
