/* Workspace look in the mockup: Pilatus = wallet/amber, Home = house/teal, Rigi = no pick (letter, Automatic colour). */
(function(){
  const looks={pilatus:{icon:'<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',c:'#fbbf24'},
    home:{icon:'<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',c:'#2fc6a3'},
    rigi:{c:'#818cf8'}};
  const prev=window.avatar;
  window.avatar=function(c,showPresence){
    const html=prev(c,showPresence),l=looks[c];
    if(!l)return html;
    const inner=l.icon?`<svg viewBox="0 0 24 24" aria-hidden="true">${l.icon}</svg>`:names[c][0];
    const dot=html.includes('avatar-presence')?'<span class="avatar-presence" role="img" aria-label="Online"></span>':'';
    return `<span class="avatar look" style="--c:${l.c}">${inner}${dot}</span>`;
  };
})();
