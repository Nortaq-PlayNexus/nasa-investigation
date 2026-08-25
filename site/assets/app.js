
(function(){
  var LEADS = window.LEADS || [];
  // count-up
  function animateCount(el){var t=+el.dataset.count,dur=1300,t0=performance.now();
    function step(now){var p=Math.min(1,(now-t0)/dur);el.textContent=Math.round(t*(1-Math.pow(1-p,3))).toLocaleString();
      if(p<1)requestAnimationFrame(step);}requestAnimationFrame(step);}
  if('IntersectionObserver'in window){var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){animateCount(e.target);io.unobserve(e.target);}});});
    document.querySelectorAll('[data-count]').forEach(function(e){io.observe(e);});}
  else{document.querySelectorAll('[data-count]').forEach(animateCount);}

  // starfield
  var c=document.getElementById('stars');if(c){var x=c.getContext('2d'),w,h,st=[];
    function rs(){w=c.width=innerWidth;h=c.height=innerHeight;st=[];var n=Math.min(160,Math.floor(w*h/9000));
      for(var i=0;i<n;i++)st.push({x:Math.random()*w,y:Math.random()*h,r:Math.random()*1.3+.2,s:Math.random()*.25+.04});}
    function draw(){x.clearRect(0,0,w,h);for(var i=0;i<st.length;i++){var p=st[i];p.y+=p.s;if(p.y>h){p.y=0;p.x=Math.random()*w;}
      x.fillStyle='rgba(180,205,255,'+(0.4+Math.random()*0.5)+')';x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fill();}
      requestAnimationFrame(draw);}rs();draw();addEventListener('resize',rs);}

  // lightbox / dossier
  var lb=document.getElementById('lb'),lbBox=document.getElementById('lbDossier');
  var LEADMAP={};LEADS.forEach(function(r){LEADMAP[r.image]=r;});
  function dossierHTML(r){
    var strip=r.strip?'<img src="'+r.strip+'" alt="'+r.image+'">':'<div class="ph">no strip</div>';
    var prod=(r.image||'').split('.')[0], pfx=prod.split('_')[0];
    var extras='https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/RDR/'+pfx+'/'+prod+'/';
    var view='https://www.uahirise.org/'+prod.toLowerCase();
    function f(k,v){return '<div class="df"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>';}
    var info='<h3>Dossier</h3>'
      +f('VERDICT',r.verdict)+f('CONFIDENCE',r.confidence||'—')+f('SCORE',r.score)
      +f('POLARITY / CLASS',(r.polarity||'—')+' / '+(r.evidence_class||'—'))
      +f('CONTRAST',r.contrast)+f('AREA (px)',r.area_px||'—')+f('SIZE',(r.w||'?')+'x'+(r.h||'?')+' px')
      +f('PIXEL (x,y)','x'+r.x+' y'+r.y)
      +f('AGREE / DISAGREE',(r.agrees||'?')+' / '+(r.disagrees||'?'))
      +f('PERSISTENCE',r.persistence||'—')+f('COMPACTNESS',r.compactness||'—')
      +f('EDGE SHARP',r.edge_sharpness||'—')+f('FDR Q',r.fdr_q||'—')
      +f('SOLAR EL/AZ',(r.solar_elevation_deg||'?')+'° / '+(r.solar_azimuth_deg||'?')+'°')
      +f('FLAGS',r.flags||'—');
    var verify='<div class="sect">Verify This Lead</div><ul class="verify">'
      +'<li>EDR original: hirise-pds.lpl.arizona.edu/EXTRAS</li>'
      +'<li>Mars Trek geolocate: trek.nasa.gov/mars</li>'
      +'<li>Cross-band persistence: '+(r.agrees||'?')+' agree / '+(r.disagrees||'?')+' disagree</li>'
      +'<li>Seek independent pass, different solar angle</li>'
      +'<li>FDR q='+(r.fdr_q||'?')+' vs negative-control baseline</li></ul>'
      +'<div class="src-chip">ORIGINAL: <a href="'+extras+'" target="_blank" rel="noopener">'+extras+'</a></div>'
      +'<div class="src-chip">VIEW: <a href="'+view+'" target="_blank" rel="noopener">'+view+'</a></div>';
    return '<div class="dossier-board"><div class="db-img">'+strip+'</div><div class="db-cap">TARGET LOCK // '+r.image+'</div></div>'
      +'<div class="dossier-info">'+info+verify+'</div>';
  }
  function openDossier(img){var r=LEADMAP[img];if(!r)return;
    lbBox.innerHTML=dossierHTML(r);lbBox.addEventListener('click',function(e){e.stopPropagation();});
    lb.classList.add('open');}
  window.openDossier=openDossier;
  window.openLightbox=function(src,cap){openDossier(cap&&cap.indexOf('//')<0?cap:'');};
  function closeLb(){lb.classList.remove('open');}lb.addEventListener('click',closeLb);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeLb();});

  // leads explorer
  var grid=document.getElementById('leadsGrid');
  if(grid){
    var state={q:'',minC:0,vs:new Set(),sort:'score'};
    function verdictColor(v){return v;}
    function card(r){var isCL=r.verdict.indexOf('CONFIRMED')===0;
      var stamp=isCL?'<div class="stamp">CONFIRMED LEAD</div>':'';
      var strip=r.strip?'<img loading="lazy" src="'+r.strip+'" alt="'+r.image+'">':'<div class="ph">no strip</div>';
      return '<div class="lead" data-img="'+r.image+'" data-strip="'+r.strip+'" data-cap="'+r.image+' — score '+r.score+' / contrast '+r.contrast+'">'
        +'<div class="thumb">'+strip+stamp+'<div class="corner-ref">x'+r.x+' y'+r.y+'</div></div>'
        +'<div class="body"><div class="name">'+r.image+'</div>'
        +'<div class="row"><span class="pill p-'+r.verdict+'">'+r.verdict+'</span><span>'+r.score+'</span></div>'
        +'<div class="row"><span>contrast '+r.contrast+'</span><span>'+r.w+'x'+r.h+'</span></div></div></div>';}
    function render(){var rows=LEADS.filter(function(r){
        if(state.vs.size&&!state.vs.has(r.verdict))return false;
        if(+r.contrast<state.minC)return false;
        if(state.q){var q=state.q.toLowerCase();if((r.image+'').toLowerCase().indexOf(q)<0&&(r.flags+'').toLowerCase().indexOf(q)<0)return false;}
        return true;});
      rows.sort(function(a,b){return +b[state.sort]-+a[state.sort];});
      var note=document.getElementById('leadNote');
      var cap=Math.min(rows.length,200);
      note.textContent='Showing '+cap+' of '+rows.length+' candidates (filtered). Click a card to enlarge.';
      grid.innerHTML=rows.slice(0,200).map(card).join('');
      Array.prototype.forEach.call(grid.querySelectorAll('.lead'),function(el){
        el.addEventListener('click',function(){openDossier(el.getAttribute('data-img'));});});}
    var q=document.getElementById('q'),mc=document.getElementById('minC'),sort=document.getElementById('sort');
    q.addEventListener('input',function(){state.q=q.value;render();});
    mc.addEventListener('input',function(){state.minC=+mc.value;document.getElementById('minCval').textContent=mc.value;render();});
    sort.addEventListener('change',function(){state.sort=sort.value;render();});
    document.querySelectorAll('.chip').forEach(function(ch){ch.addEventListener('click',function(){var v=ch.dataset.v;
      if(state.vs.has(v)){state.vs.delete(v);ch.classList.remove('on');}else{state.vs.add(v);ch.classList.add('on');}render();});});
    render();
  }

  // findings toggle
  document.querySelectorAll('.finding-card').forEach(function(c){
    c.querySelector('.fc-head').addEventListener('click',function(){c.classList.toggle('open');});});

  // sortable tables
  document.querySelectorAll('table.sortable').forEach(function(t){
    t.querySelectorAll('th[data-key]').forEach(function(th){th.addEventListener('click',function(){
      var key=th.dataset.key,asc=!th.classList.contains('asc');var tb=t.tBodies[0];
      var rows=Array.prototype.slice.call(tb.querySelectorAll('tr'));
      rows.sort(function(a,b){var x=a.children[th.cellIndex].textContent,b2=b.children[th.cellIndex].textContent;
        var nx=parseFloat(x.replace(/[^0-9.\-]/g,'')),ny=parseFloat(b2.replace(/[^0-9.\-]/g,''));
        if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;return asc?x.localeCompare(b2):b2.localeCompare(x);});
      rows.forEach(function(r){tb.appendChild(r);});
      t.querySelectorAll('th').forEach(function(h){h.classList.remove('asc','desc');});
      th.classList.add(asc?'asc':'desc');});});});
})();
