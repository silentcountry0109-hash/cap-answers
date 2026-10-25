
(function(){
  // lazy images inside <details>
  document.querySelectorAll('details.stem').forEach(function(d){
    d.addEventListener('toggle',function(){
      if(d.open){d.querySelectorAll('img[data-src]').forEach(function(im){im.src=im.getAttribute('data-src');im.removeAttribute('data-src');});}
    });
  });
  // jump to question
  var inp=document.getElementById('jumpn');
  if(inp){
    var go=function(){
      var v=(inp.value||'').trim(); if(!v) return;
      var el=document.getElementById('q'+v)||document.getElementById('q'+v+'-1')||document.getElementById('p'+v);
      if(el){el.scrollIntoView({behavior:'smooth',block:'start'}); history.replaceState(null,'','#'+el.id); inp.blur();}
      else{inp.setCustomValidity('本章沒有第 '+v+' 題'); inp.reportValidity(); setTimeout(function(){inp.setCustomValidity('')},1500);}
    };
    inp.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();go();}});
    inp.addEventListener('change',go);
  }
  // mask answers
  var btn=document.querySelector('.mask-t');
  var KEY='danlu-cap-mask';
  function setMask(on){
    document.body.classList.toggle('masked',on);
    if(btn){btn.setAttribute('aria-pressed',on?'true':'false'); btn.textContent=on?'顯示答案':'遮住答案';}
    document.querySelectorAll('.show').forEach(function(x){x.classList.remove('show')});
    try{localStorage.setItem(KEY,on?'1':'0')}catch(e){}
  }
  if(btn){
    var init=false; try{init=localStorage.getItem(KEY)==='1'}catch(e){}
    setMask(init);
    btn.addEventListener('click',function(){setMask(!document.body.classList.contains('masked'))});
  }
  document.addEventListener('click',function(e){
    if(!document.body.classList.contains('masked')) return;
    var li=e.target.closest('.bubbles li');
    if(li){ if(!li.classList.contains('show')){e.preventDefault(); li.classList.add('show');} return; }
    var m=e.target.closest('.mark');
    if(m){ m.classList.add('show'); var box=m.closest('.sub')||m.closest('.qb'); if(box) box.classList.add('show'); }
  });
  // lightbox for 解析 images
  document.addEventListener('click',function(e){
    var z=e.target.closest('.zoom'); if(!z) return;
    var im=z.querySelector('img'); if(!im) return;
    var lb=document.createElement('div'); lb.className='lb'; lb.setAttribute('role','dialog'); lb.setAttribute('aria-label','放大檢視');
    var big=document.createElement('img'); big.src=im.currentSrc||im.src; big.alt=im.alt;
    var close=document.createElement('button'); close.type='button'; close.textContent='關閉';
    lb.appendChild(big); lb.appendChild(close); document.body.appendChild(lb); close.focus();
    var done=function(){lb.remove(); z.focus();};
    close.addEventListener('click',done);
    lb.addEventListener('click',function(ev){if(ev.target===lb) done();});
    document.addEventListener('keydown',function k(ev){if(ev.key==='Escape'){done();document.removeEventListener('keydown',k);}});
  });
})();
