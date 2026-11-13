(() => {
  const look = document.getElementById('dialog-look');
  let saved = {icon:'D', colour:'#61d5b8'}, draft = {...saved};
  function paint() {
    document.querySelectorAll('[data-look-chip],.workspace .ws-switch .wsb').forEach(chip => {
      chip.textContent = draft.icon; chip.style.color = draft.colour; chip.style.background = draft.colour+'26';
    });
    look.querySelectorAll('[data-icon]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.icon===draft.icon));
    look.querySelectorAll('[data-colour]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.colour===draft.colour));
    const icon=look.querySelector('[data-icon][aria-pressed=true]').getAttribute('aria-label');
    const colour=look.querySelector('[data-colour][aria-pressed=true]').getAttribute('aria-label');
    document.querySelectorAll('[data-look-summary]').forEach(n=>n.textContent=icon+' · '+colour);
  }
  paint();
  look.addEventListener('close',()=>{draft={...saved};paint()});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.icon){draft.icon=b.dataset.icon;paint()}
    if(b.dataset.colour){draft.colour=b.dataset.colour;paint()}
    if(b.hasAttribute('data-look-save')){saved={...draft};look.close();announce('Appearance saved in this preview')}
    if(b.hasAttribute('data-look-cancel'))look.close();
    if(b.hasAttribute('data-copy-path')){
      try{await navigator.clipboard.writeText('/Users/lume/.orch-test/demo-dash/ws/Demo');announce('Folder path copied')}
      catch{const path=b.closest('.setting-row').querySelector('[data-folder-path]');const selection=window.getSelection();const range=document.createRange();range.selectNodeContents(path);selection.removeAllRanges();selection.addRange(range);announce('Select the full path to copy it')}
    }
    if(b.hasAttribute('data-reconnect')){
      b.disabled=true; const label=b.closest('.setting-row').querySelector('[data-relay-status]');label.textContent='Connecting…';
      setTimeout(()=>{label.textContent='Connected';b.disabled=false;enablePairing();announce('Relay reconnected in this preview')},700);
    }
  });
  function enablePairing(){
    document.querySelectorAll('#panel-phone [data-dialog="pair"]').forEach(b=>b.disabled=false);
    document.querySelectorAll('[data-relay-hint]').forEach(n=>n.hidden=true);
  }
  document.getElementById('dialog-pair').addEventListener('close',()=>{
    const pill=document.querySelector('#dialog-pair .shared-preview');
    if(pill)document.body.append(pill);
  });
  const params=new URLSearchParams(location.search);
  if(params.get('relay')==='disconnected'){
    document.querySelectorAll('[data-relay-status]').forEach(n=>{n.textContent='Not connected';n.className='muted'});
    document.querySelectorAll('#panel-phone [data-dialog="pair"]').forEach(b=>{
      b.disabled=true;
      const value=b.closest('.setting-row').querySelector('.row-value');
      if(!value.querySelector('[data-relay-hint]'))value.insertAdjacentHTML('beforeend','<p class="meta" data-relay-hint>Connect to your relay first</p>');
    });
  }
  document.getElementById('relay-form').onsubmit=e=>{
    e.preventDefault(); const address=new FormData(e.target).get('address');
    if(!/^https?:\/\//.test(address)){e.target.elements.address.setCustomValidity('Use an address starting with https://');e.target.reportValidity();return}
    document.querySelectorAll('[data-relay-status]').forEach(n=>{n.textContent='Connected';n.className='good'});
    document.querySelectorAll('[data-relay-address]').forEach(n=>n.textContent=address);
    document.querySelector('[data-pair-relay]').textContent=address;
    enablePairing();document.getElementById('dialog-relay').close();announce('Relay connected in this preview');
  };
  document.querySelector('#relay-form input').oninput=e=>e.target.setCustomValidity('');
  if(location.pathname.endsWith('settings-phone-pair.html')&&!['empty','loading'].includes(params.get('state'))&&params.get('relay')!=='disconnected')document.getElementById('dialog-pair').showModal();
})();
