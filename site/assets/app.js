
(function(){
  var LEADS = [];
  var DIVERSE = [];
  var SB = window.STRIP_BASE || 'results/strips/';
  function debounce(fn,ms){var t;return function(){var a=arguments,c=this;clearTimeout(t);t=setTimeout(function(){fn.apply(c,a)},ms)}}
  var prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function stripUrl(n){return n ? SB + n : '';}
  // count-up
  function animateCount(el){var t=+el.dataset.count,dur=1300,t0=performance.now();
    function step(now){var p=Math.min(1,(now-t0)/dur);el.textContent=Math.round(t*(1-Math.pow(1-p,3))).toLocaleString();
      if(p<1)requestAnimationFrame(step);}requestAnimationFrame(step);}
  if('IntersectionObserver'in window){var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){animateCount(e.target);io.unobserve(e.target);}});});
    document.querySelectorAll('[data-count]').forEach(function(e){io.observe(e);});}
  else{document.querySelectorAll('[data-count]').forEach(animateCount);}

  // starfield - respects reduced-motion, mobile, and visibility
  var c=document.getElementById('stars');if(c && !prefersReducedMotion){var x=c.getContext('2d'),w,h,st=[],raf=null;
    function rs(){w=c.width=innerWidth;h=c.height=innerHeight;st=[];var isMob=window.innerWidth<720;var n=Math.min(isMob?60:120,Math.floor(w*h/12000));
      for(var i=0;i<n;i++)st.push({x:Math.random()*w,y:Math.random()*h,r:Math.random()*1.3+.2,s:Math.random()*.25+.04});}
    function draw(){if(document.hidden){raf=requestAnimationFrame(draw);return;}x.clearRect(0,0,w,h);for(var i=0;i<st.length;i++){var p=st[i];p.y+=p.s;if(p.y>h){p.y=0;p.x=Math.random()*w;}
      x.fillStyle='rgba(180,205,255,'+(0.4+Math.random()*0.5)+')';x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fill();}
      raf=requestAnimationFrame(draw);}rs();draw();addEventListener('resize',debounce(rs,250));
    document.addEventListener('visibilitychange',function(){});
  } else if(c){c.style.display='none';}

  // lightbox / dossier — grouped: one distinct anomaly holds all band views
  var lb=document.getElementById('lb'),lbBox=document.getElementById('lbDossier');
  var LEADMAP={};
  function stripFrom(r){
    // grouped feature may carry strip at top level or inside variants[0]
    if(r.strip) return r.strip;
    if(r.variants && r.variants[0] && r.variants[0].strip) return r.variants[0].strip;
    if(r.members && r.members[0] && r.members[0].strip) return r.members[0].strip;
    return '';
  }
  function cropFrom(r){
    if(r.crop) return r.crop;
    if(r.variants && r.variants[0] && r.variants[0].crop) return r.variants[0].crop;
    if(r.members && r.members[0] && r.members[0].crop) return r.members[0].crop;
    return null;
  }
  function cropDiv(r){
    var s=stripUrl(stripFrom(r)), c=cropFrom(r);
    if(!s||!c) return '<div class="ph">no strip — enhancements pending</div>';
    var fw=c[2], fh=c[3];
    var bx = fw>=1?0:(c[0]/(1-fw)*100);
    var by = fh>=1?0:(c[1]/(1-fh)*100);
    return '<div class="crop" style="background-image:url('+s+');background-size:'+(100/fw)+'% '+(100/fh)+'%;background-position:'+bx+'% '+by+'%"></div>';
  }
  function cropDivLazy(r){
    var s=stripUrl(stripFrom(r)), c=cropFrom(r);
    if(!s||!c) return '<div class="ph">no strip — enhancements pending</div>';
    var fw=c[2], fh=c[3];
    var bx = fw>=1?0:(c[0]/(1-fw)*100);
    var by = fh>=1?0:(c[1]/(1-fh)*100);
    return '<div class="crop" data-bg="'+s+'" data-size="'+(100/fw)+'% '+(100/fh)+'%" data-pos="'+bx+'% '+by+'%" style="background-color:#05070a;min-height:160px"></div>';
  }
  function initLazyCrops(){
    var els=document.querySelectorAll('.crop[data-bg]');
    if(!els.length) return;
    if(!('IntersectionObserver' in window)){
      els.forEach(function(el){el.style.backgroundImage='url('+el.dataset.bg+')';el.style.backgroundSize=el.dataset.size;el.style.backgroundPosition=el.dataset.pos;el.style.backgroundRepeat='no-repeat';el.removeAttribute('data-bg');});
      return;
    }
    var io=new IntersectionObserver(function(entries){entries.forEach(function(e){if(e.isIntersecting){var el=e.target;el.style.backgroundImage='url('+el.dataset.bg+')';el.style.backgroundSize=el.dataset.size;el.style.backgroundPosition=el.dataset.pos;el.style.backgroundRepeat='no-repeat';el.removeAttribute('data-bg');io.unobserve(el);}});},{rootMargin:'200px'});
    els.forEach(function(el){io.observe(el);});
  }
  function escH(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  // --- LOOP STATE for gallery carousel ---
  var GLOOP={i:0,timer:null};
  function cycleGallery(dir){
    var figs=document.querySelectorAll('#galLoop figure');
    if(!figs.length) return;
    figs[GLOOP.i].style.outline='';
    GLOOP.i=(GLOOP.i+dir+figs.length)%figs.length;
    figs.forEach(function(f,j){ f.style.display=j===GLOOP.i?'block':'none'; f.style.outline=j===GLOOP.i?'2px solid var(--accent)':''; });
    var cap=document.getElementById('galCap'); if(cap) cap.textContent=(GLOOP.i+1)+'/'+figs.length+' — '+figs[GLOOP.i].getAttribute('data-label');
  }
  function startGalLoop(){ stopGalLoop(); GLOOP.timer=setInterval(function(){ cycleGallery(1); }, 2600); }
  function stopGalLoop(){ if(GLOOP.timer){ clearInterval(GLOOP.timer); GLOOP.timer=null; } }

  function dossierHTML(r){
    // grouped vs legacy flat: support both
    var variants = r.variants || r.members || [r];
    var isGrouped = variants.length>1 || r.base;
    var primaryStrip=cropDiv(r);
    // build LOOPING gallery of every image of this anomaly
    var gallery='';
    if(isGrouped && variants.length>1){
      // carousel that LOOPS infinitely (wrap-around) — auto-cycles every 2.6s, manual prev/next also loop
      gallery='<div id="galWrap" style="position:relative">'
        +'<div id="galLoop" class="gallery" style="display:block">'
        +variants.map(function(v,idx){
        var su=stripUrl(v.strip||stripFrom(v));
        var c=v.crop, style='';
        if(su && c){
          var fw=c[2],fh=c[3],bx=fw>=1?0:(c[0]/(1-fw)*100),by=fh>=1?0:(c[1]/(1-fh)*100);
          style='background-image:url('+su+');background-size:'+(100/fw)+'% '+(100/fh)+'%;background-position:'+bx+'% '+by+'%';
        }
        var thumb = (su&&c) ? '<div class="crop" style="'+style+'"></div>' : '<div class="ph" style="padding:18px">'+escH(v.image||v.band||'no strip')+'</div>';
        var disp=idx===0?'block':'none';
        var outl=idx===0?'2px solid var(--accent)':'';
        return '<figure data-label="'+escH(v.band||'')+' '+escH(v.image||'')+' — '+v.score+' / c'+v.contrast+'" style="display:'+disp+';outline:'+outl+'"><div style="position:relative;aspect-ratio:16/9;background:#05070a;overflow:hidden">'+thumb+'</div><figcaption>'+escH(v.band||'')+' '+escH(v.image||'')+' — '+v.score+' / c'+v.contrast+'</figcaption></figure>';
      }).join('')+'</div>'
        +'<div style="display:flex;gap:.5rem;justify-content:center;margin:.45rem 0">'
        +'<button class="btn" onclick="cycleGallery(-1);event.stopPropagation();" style="padding:.25rem .7rem">‹ Prev</button>'
        +'<span id="galCap" style="font-family:var(--mono);font-size:.72rem;color:var(--muted);align-self:center">1/'+variants.length+' — '+escH(variants[0].band||'')+' '+escH(variants[0].image||'')+'</span>'
        +'<button class="btn" onclick="cycleGallery(1);event.stopPropagation();" style="padding:.25rem .7rem">Next ›</button>'
        +'<button class="btn" id="galPlay" onclick="if(GLOOP.timer){stopGalLoop();this.textContent=\'▶ Auto-loop\';}else{startGalLoop();this.textContent=\'⏸ Pause\';}event.stopPropagation();" style="padding:.25rem .7rem">⏸ Pause</button>'
        +'</div>'
        +'<div style="font-family:var(--mono);font-size:.72rem;color:var(--muted);margin-top:.35rem">Looping gallery: all '+variants.length+' views of this physical anomaly cycle infinitely (same crater/rock seen in '+(r.bands?r.bands.join(' / '):variants.map(function(v){return v.band;}).join(' / '))+' ). The grid shows this as one card.</div></div>';
    } else {
      gallery='';
    }
    var ctx = (stripUrl(stripFrom(r)) && cropFrom(r))
      ? '<div class="db-ctx"><img src="'+stripUrl(stripFrom(r))+'">'
        +'<span class="box" style="left:'+(cropFrom(r)[0]*100)+'%;top:'+(cropFrom(r)[1]*100)
        +'%;width:'+(cropFrom(r)[2]*100)+'%;height:'+(cropFrom(r)[3]*100)+'%"></span></div>'
      : '';
    var prod=(r.base||r.image||'').split('.')[0].split('_').slice(0,3).join('_'), pfx=(r.image||r.base||'').split('_')[0];
    // for files like ESP_013236_1410 we want the full prod id as stored in base
    var fullProd=(r.base||r.image||'').split('.')[0];
    var extras='https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/RDR/'+pfx+'/'+fullProd+'/';
    var view='https://www.uahirise.org/'+fullProd.toLowerCase();
    function f(k,v){return '<div class="df"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>';}
    var sc=r.max_score!=null?r.max_score:r.score, ct=r.max_contrast!=null?r.max_contrast:r.contrast;
    var flagsDisp = r.flags ? (Array.isArray(r.flags)?r.flags.join(', '):r.flags) : (variants.map(function(v){return v.flags;}).filter(Boolean).join(', ')||'—');
    var info='<h3>Dossier — '+(isGrouped? (variants.length+' views grouped'): 'single view')+'</h3>'
      +f('ANOMALY', escH(r.base||r.image||'—') + (isGrouped?' <span class="vcount">'+variants.length+' variants — '+((r.bands||[]).join(' / ') || 'bands')+'</span>':''))
      +f('VERDICT',r.verdict|| (r.verdicts?r.verdicts.join(' / '):'—'))+f('CONFIDENCE',r.confidence||'—')+f('SCORE (best)',sc)
      +f('POLARITY / CLASS',(r.polarity||'—')+' / '+(r.evidence_class||'—'))
      +f('CONTRAST (best)',ct)+f('AREA (px)',r.area_px||'—')+f('SIZE',(r.w||'?')+'×'+(r.h||'?')+' px')
      +f('PIXEL (x,y)','x'+r.x+' y'+r.y + (isGrouped?' — representative':''))
      +f('AGREE / DISAGREE',(r.agrees||'?')+' / '+(r.disagrees||'?'))
      +f('PERSISTENCE',r.persistence||'—')+f('COMPACTNESS',r.compactness||'—')
      +f('EDGE SHARP',r.edge_sharpness||'—')+f('FDR Q',r.fdr_q||'—')
      +f('SOLAR EL/AZ',(r.solar_elevation_deg||'?')+'° / '+(r.solar_azimuth_deg||'?')+'°')
      +f('FLAGS',flagsDisp);
    // per-variant table
    var perBand='';
    if(isGrouped){
      perBand='<div class="sect" style="margin-top:.9rem">Every image of this anomaly</div><table style="width:100%;font-size:.74rem;border-collapse:collapse"><tr style="color:var(--muted);font-family:var(--mono)"><th style="text-align:left;padding:.2rem .4rem">band</th><th>image</th><th>score</th><th>contrast</th><th>x,y</th><th>box</th></tr>'
        +variants.map(function(v){return '<tr><td style="padding:.2rem .4rem">'+escH(v.band||'')+'</td><td style="font-family:var(--mono);font-size:.70rem;word-break:break-all">'+escH(v.image)+'</td><td>'+v.score+'</td><td>'+v.contrast+'</td><td>'+v.x+','+v.y+'</td><td>'+v.w+'×'+v.h+'</td></tr>';}).join('')
        +'</table>';
    }
    var verify='<div class="sect">Verify This Lead</div><ul class="verify">'
      +'<li>EDR original: hirise-pds.lpl.arizona.edu/EXTRAS</li>'
      +'<li>Mars Trek geolocate: trek.nasa.gov/mars</li>'
      +'<li>Cross-band persistence: '+(r.agrees||'?')+' agree / '+(r.disagrees||'?')+' disagree — now collapsed into one card</li>'
      +'<li>Seek independent pass, different solar angle — see.gallery</li>'
      +'<li>FDR q='+(r.fdr_q||'?')+' vs negative-control baseline</li></ul>'
      +'<div class="src-chip">ORIGINAL: <a href="'+extras+'" target="_blank" rel="noopener">'+extras+'</a></div>'
        +'<div class="src-chip">VIEW: <a href="'+view+'" target="_blank" rel="noopener">'+view+'</a></div>'
        +perBand
        +'<button id="copyLink" class="btn" style="margin-top:.6rem;width:100%">Copy shareable link</button>';
        return '<div class="dossier-board"><div class="db-img">'+primaryStrip+'</div>'
      +'<div class="db-cap">TARGET LOCK // '+escH(r.base||r.image)+' — '+(isGrouped? variants.length+' views': '1 view')+'</div>'+ctx+gallery+'</div>'
      +'<div class="dossier-info">'+info+verify+'</div>';
  }
   function keyOf(r){return r.base || r.image || '';}
  function openDossier(img){var r=LEADMAP[img];if(!r){
    for(var k in LEADMAP){ if(LEADMAP[k] && (LEADMAP[k].base===img || LEADMAP[k].image===img)){ r=LEADMAP[k]; break; } }
    if(!r) return;
  }
   GLOOP.i=0; lbBox.innerHTML=dossierHTML(r);lbBox.addEventListener('click',function(e){e.stopPropagation();});
   lb.classList.add('open');history.replaceState(null,'','#dossier='+encodeURIComponent(keyOf(r)));
   // start looping gallery auto-cycle — loops infinitely, wrap-around
   setTimeout(function(){ GLOOP.i=0; startGalLoop(); }, 400);
  var cb=lbBox.querySelector('#copyLink');
  if(cb){cb.addEventListener('click',function(e){e.stopPropagation();
    navigator.clipboard.writeText(location.href).then(function(){cb.textContent='Link copied';setTimeout(function(){cb.textContent='Copy shareable link';},1500);});
  });}
  // keyboard loop: ← / → cycles gallery, Esc closes
  }
  window.openDossier=openDossier;
  window.openLightbox=function(src,cap){openDossier(cap&&cap.indexOf('//')<0?cap:'');};
  function closeLb(){stopGalLoop(); lb.classList.remove('open');history.replaceState(null,'',location.pathname+location.search);}lb.addEventListener('click',closeLb);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape') closeLb();
    if(lb.classList.contains('open')){
      if(e.key==='ArrowLeft'){ cycleGallery(-1); }
      if(e.key==='ArrowRight'){ cycleGallery(1); }
    }
  });

  // leads explorer (initialised after leads.json loads) — now grouped features
  function initExplorer(){
    var grid=document.getElementById('leadsGrid');
    if(!grid)return;
    var state={q:'',minC:0,vs:new Set(),sort:'score',limit:200,cur:[]};
    function isCL(r){var v=r.verdict|| (r.verdicts&&r.verdicts[0]) ||''; return v.indexOf('CONFIRMED')===0;}
    function card(r){
      var cl=isCL(r);
      var stamp=cl?'<div class="stamp">CONFIRMED LEAD</div>':'';
      var strip=cropDivLazy(r);
      var variants = r.variants || r.members || [];
      var vc = variants.length>1 ? '<span class="vcount">'+variants.length+' views</span>' : '';
      var bands = (r.bands||[]).map(function(b){return '<span class="pill p-'+r.verdict+'" style="background:#0d1a21;color:#7fd4e8;border:1px solid #16404d;font-size:.62rem">'+b+'</span>';}).join('');
      // show base as title, with count; still index by base so dossier groups open
      var title = escH(r.base||r.image);
      var scoreDisp = r.max_score!=null?r.max_score:r.score;
      var contrastDisp = r.max_contrast!=null?r.max_contrast:r.contrast;
      var verdictDisp = r.verdict|| (r.verdicts?r.verdicts[0]:'');
      return '<div class="lead" data-img="'+escH(r.base||r.image)+'" data-strip="'+escH(r.strip||'')+'" role="button" tabindex="0" aria-label="Open dossier for '+escH(r.base||r.image)+'">'
        +'<div class="thumb">'+strip+stamp+'<div class="corner-ref">x'+r.x+' y'+r.y+'</div></div>'
        +'<div class="body"><div class="name">'+title+' '+vc+'</div>'
        +'<div class="row"><span class="pill p-'+verdictDisp+'">'+verdictDisp+'</span><span>'+scoreDisp+'</span></div>'
        +'<div class="row" style="flex-wrap:wrap;gap:.25rem">'+bands+(r.bands&&r.bands.length?'':'')+'<span style="margin-left:auto;color:var(--muted)">c '+contrastDisp+' · '+r.w+'×'+r.h+(variants.length>1?' · '+variants.length+' images':'')+'</span></div></div></div>';}
    function escH(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
    function effScore(r){return r.max_score!=null?r.max_score: (+r.score||0);}
    function effContrast(r){return r.max_contrast!=null?r.max_contrast: (+r.contrast||0);}
    function effArea(r){return +r.area_px||0;}
    function baseRows(){if(state.q===''&&state.vs.size===0&&state.minC===0&&state.sort==='score')return DIVERSE;return LEADS;}
    function render(){var rows=baseRows().filter(function(r){
      var vlist = r.verdicts||[r.verdict];
      if(state.vs.size){var hit=false; for(var i=0;i<vlist.length;i++) if(state.vs.has(vlist[i])) hit=true; if(!hit) return false; }
      if(effContrast(r)<state.minC)return false;
      if(state.q){
        var q=state.q.toLowerCase();
        var hay=(r.base||'')+' '+(r.image||'')+' '+(r.flags||'')+' '+(r.verdict||'')+' '+(r.bands||[]).join(' ')+' '+((r.variants||r.members||[]).map(function(m){return m.image+' '+m.band+' '+m.flags;}).join(' '));
        if(hay.toLowerCase().indexOf(q)<0) return false;
      }
      return true;});
      if(rows!==DIVERSE){
        rows.sort(function(a,b){
          if(state.sort==='score') return effScore(b)-effScore(a);
          if(state.sort==='contrast') return effContrast(b)-effContrast(a);
          if(state.sort==='area_px') return effArea(b)-effArea(a);
          if(state.sort==='w') return (+b.w||0)-(+a.w||0);
          return 0;
        });
      }
      var note=document.getElementById('leadNote');
  var cap=Math.min(rows.length,state.limit);
  note.innerHTML = rows.length ? ('Showing '+cap+' of '+rows.length+' distinct anomalies (one card = all views of that anomaly — '+(LEADS.length?LEADS.length:rows.length)+' grouped features total, dup bands collapsed). Click a card to see every image.')
 : 'No anomalies match the current filters - press Reset.';
  state.cur=rows;
  grid.innerHTML=rows.slice(0,state.limit).map(card).join('');
  setTimeout(initLazyCrops,50);
      var lm=document.getElementById('loadMore');
      if(lm){
        lm.style.display = rows.length ? 'inline-block' : 'none';
        // LOOP label: continuous — at end show wrap option
        if(state.limit>=rows.length) lm.textContent='↺ Loop to start — '+rows.length+' total (click to restart at top)';
        else lm.textContent='Load more — '+cap+' / '+rows.length+' (loops at end)';
      }
      Array.prototype.forEach.call(grid.querySelectorAll('.lead'),function(el){
        el.addEventListener('click',function(){openDossier(el.getAttribute('data-img'));});
        el.addEventListener('keydown',function(e){if(e.key==='Enter' || e.key===' '){e.preventDefault();openDossier(el.getAttribute('data-img'));}});});}
    var q=document.getElementById('q'),mc=document.getElementById('minC'),sort=document.getElementById('sort');
    q.addEventListener('input',debounce(function(){state.q=q.value;render();},250));
    mc.addEventListener('input',debounce(function(){state.minC=+mc.value;document.getElementById('minCval').textContent=mc.value;render();},100));
    sort.addEventListener('change',function(){state.sort=sort.value;render();});
    var resetBtn=document.getElementById('reset');
    if(resetBtn){resetBtn.addEventListener('click',function(){
      q.value='';mc.value=0;document.getElementById('minCval').textContent='0';
      sort.value='score';state.q='';state.minC=0;state.sort='score';state.vs.clear();state.limit=200;
      nl.querySelectorAll('.chip').forEach(function(c){c.classList.remove('on');});
      render();});}
  var lmBtn=document.getElementById('loadMore');
  if(lmBtn){lmBtn.addEventListener('click',function(){
    // LOOP: when at end, wrap back to start instead of stopping
    if(state.limit>=state.cur.length){
      state.limit=200; grid.scrollIntoView({behavior:'smooth'});
    } else {
      state.limit+=200;
      lmBtn.scrollIntoView({behavior:'smooth',block:'center'});
    }
    render();
    // update label to show looping state
    var rows=state.cur.length;
    lmBtn.textContent = state.limit>=rows ? '↺ Loop to start ('+rows+' total)' : 'Load more ('+Math.min(state.limit+200,rows)+' / '+rows+')';
  });}
  var exBtn=document.getElementById('export');
  if(exBtn){exBtn.addEventListener('click',function(){
  var rows=state.cur||LEADS;
  // export one row per variant so CSV stays flat but includes grouping key
  var cols=['base','image','band','x','y','w','h','contrast','score','verdict','confidence','evidence_class','agrees','disagrees','area_px','flags','strip'];
  var lines=[cols.join(',')];
   rows.forEach(function(f){
     var vars=f.variants||f.members||[f];
     vars.forEach(function(r){
       var rec={base:f.base||f.image, image:r.image||f.image, band:r.band||'', x:r.x||f.x, y:r.y||f.y, w:r.w||f.w, h:r.h||f.h, contrast:r.contrast, score:r.score, verdict:r.verdict||f.verdict, confidence:f.confidence, evidence_class:f.evidence_class, agrees:f.agrees, disagrees:f.disagrees, area_px:f.area_px, flags:r.flags||f.flags, strip:r.strip};
       var parts=cols.map(function(c){var v=rec[c]==null?'':(''+rec[c]);
         return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;});
       lines.push(parts.join(','));
     });
  });
  var blob=new Blob([lines.join('\n')],{type:'text/csv'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='hirise_leads_grouped.csv';a.click();
  URL.revokeObjectURL(a.href);});}
    document.querySelectorAll('.chip').forEach(function(ch){ch.addEventListener('click',function(){var v=ch.dataset.v;
      if(state.vs.has(v)){state.vs.delete(v);ch.classList.remove('on');}else{state.vs.add(v);ch.classList.add('on');}render();});});
    render();
  }
  function diverseOrder(arr){
    // grouped already spread — just sort by score and interleave bases for visual variety
    var byBase={}, bases=[];
    arr.forEach(function(f){var b=f.base||f.image; if(!byBase[b]){byBase[b]=[]; bases.push(b);} byBase[b].push(f);});
    bases.forEach(function(b){byBase[b].sort(function(a,b2){return (b2.max_score||b2.score)-(a.max_score||a.score);});});
    // if each base only has one grouped feature (normal), just return arr sorted
    if(bases.length===arr.length) return arr.slice().sort(function(a,b){return (b.max_score||b.score)-(a.max_score||a.score);});
    var out=[], i=0, rem=true;
    while(rem){rem=false; for(var j=0;j<bases.length;j++){var g=byBase[bases[j]]; if(i<g.length){out.push(g[i]); rem=true;}} i++;}
    return out;
  }
  function boot(){var url='assets/leads.json'+(window.LEADS_VER?('?v='+window.LEADS_VER):'');
    fetch(url).then(function(r){return r.json();}).then(function(d){
      // normalize: support both old flat payload and new grouped payload
      LEADS=d;LEADMAP={};d.forEach(function(r){
        var k=r.base||r.image;
        LEADMAP[k]=r;
        // also index by each member image so old #dossier links still resolve
        if(r.variants) r.variants.forEach(function(v){LEADMAP[v.image]=r;});
        if(r.members) r.members.forEach(function(v){LEADMAP[v.image]=r;});
        LEADMAP[r.image]=r;
      });DIVERSE=diverseOrder(LEADS);
        initExplorer();
        var h=location.hash||'';if(h.indexOf('dossier=')>=0){var img=decodeURIComponent(h.split('dossier=')[1]);if(LEADMAP[img]){openDossier(img);}}
        }).catch(function(e){console.error('leads load failed',e);
      var g=document.getElementById('leadsGrid');if(g)g.innerHTML='<div class="ph">candidate feed offline</div>';});
  }
  if(document.readyState!=='loading')boot();else document.addEventListener('DOMContentLoaded',boot);

  // findings toggle
  document.querySelectorAll('.finding-card').forEach(function(c){
    c.querySelector('.fc-head').addEventListener('click',function(){c.classList.toggle('open');});});
  var fs=document.getElementById('fSearch');
  if(fs){fs.addEventListener('input',debounce(function(){
    var q=fs.value.toLowerCase().trim();
    document.querySelectorAll('#findings .finding-card').forEach(function(c){
      var hay=(c.getAttribute('data-search')||'').toLowerCase();
      c.style.display = (!q || hay.indexOf(q)>=0) ? '' : 'none';
    });},200));}

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

  // mobile nav toggle
  var nt=document.querySelector('.nav-toggle'), nl=document.querySelector('.nav-links');
  if(nt&&nl){nt.addEventListener('click',function(){var isOpen=nl.classList.toggle('open');nt.setAttribute('aria-expanded', isOpen?'true':'false');});
    nl.querySelectorAll('a').forEach(function(a){a.addEventListener('click',function(){nl.classList.remove('open');nt.setAttribute('aria-expanded','false');});});
    document.addEventListener('click',function(e){if(!nl.contains(e.target) && !nt.contains(e.target)){nl.classList.remove('open');nt.setAttribute('aria-expanded','false');}});
    document.addEventListener('keydown',function(e){if(e.key==='Escape' && nl.classList.contains('open')){nl.classList.remove('open');nt.setAttribute('aria-expanded','false');nt.focus();}});}

  // scroll reveal
  (function(){
    var rs=document.querySelectorAll('section');
    if(!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches){
      rs.forEach(function(s){s.classList.add('in');});return;
    }
    var ro=new IntersectionObserver(function(es){es.forEach(function(e){
      if(e.isIntersecting){e.target.classList.add('in');ro.unobserve(e.target);}});},{rootMargin:'0px 0px -8% 0px'});
    rs.forEach(function(s){ro.observe(s);});
  })();

  // back-to-top
  var toTop=document.getElementById('toTop');
  if(toTop){
    window.addEventListener('scroll',function(){toTop.classList.toggle('show',window.scrollY>600);},{passive:true});
    toTop.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});
  }

  // explorer loading shimmer (until leads.json resolves)
  var g0=document.getElementById('leadsGrid');
  if(g0 && !g0.children.length){g0.innerHTML="<div class='ph'>acquiring candidate feed &hellip;</div>";}

  // live data-freshness indicator
  (function(){
    var ep=window.BUILD_EPOCH, el=document.getElementById('ago');
    if(!ep||!el)return;
    function upd(){var s=Math.floor(Date.now()/1000)-ep;
      var t=s<60?s+'s':s<3600?Math.floor(s/60)+'m':Math.floor(s/3600)+'h';
      el.textContent='('+t+' ago)';}
    upd();setInterval(upd,30000);
  })();

  // live uplink window countdown
  (function(){
    var end=window.UPLINK_END; if(!end)return;
    var box=document.getElementById('uplink'), clk=document.getElementById('uplinkClock');
    if(!box||!clk)return;
    function pad(n){return (n<10?'0':'')+n;}
    function tick(){var r=end*1000-Date.now();
      if(r<=0){clk.textContent='WINDOW CLOSED';box.classList.add('closed');return;}
      r=Math.floor(r/1000);var h=Math.floor(r/3600),m=Math.floor((r%3600)/60),s=r%60;
      clk.textContent=pad(h)+':'+pad(m)+':'+pad(s);
      setTimeout(tick,1000);}
    tick();
  })();
})();
