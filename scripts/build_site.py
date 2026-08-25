"""Build the public GitHub Pages site for the NASA HiRISE investigation.

Produces a self-contained, committable ``site/`` tree with a cinematic,
interactive "facility" front-end:

    site/
      index.html              landing + interactive leads explorer + findings + methodology
      report/index.html      detailed, sortable Anomaly Analysis Report
      results/                public adjudication data (CSVs, SUMMARY, findings, strips)
      assets/                shared CSS, JS, logo, social image
      .nojekyll

Reads local adjudication outputs (data/anomalies/, which stay gitignored).
Run:  python scripts/build_site.py
"""

from __future__ import annotations

import base64
import csv
import html
import json
import mimetypes
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
STRIPS = CONC / "strips"
LEADS_DIR = CONC / "leads"
DOCS = ROOT / "docs"
BRAND = ROOT / "assets" / "branding"
SITE = ROOT / "site"

REPO = "Nortaq-PlayNexus/nasa-investigation"
BASE = f"https://github.com/{REPO}"
SITE_URL = "https://nortaq-playnexus.github.io/nasa-investigation"

# --------------------------------------------------------------------------
# design system
# --------------------------------------------------------------------------
CSS = r"""
:root{
  --bg0:#0d111c; --bg1:#060910;
  --panel:rgba(11,15,24,0.92); --panel2:rgba(15,20,32,0.92);
  --border:rgba(255,255,255,0.08); --border2:rgba(255,196,48,0.30);
  --text:#e9edf5; --muted:#8c95a8; --faint:#6b7888;
  --accent:#ffc430; --accent2:#ffd866; --red:#e23c3a;
  --amber:#ffc430; --green:#3fb950; --purple:#a371f7;
  --mono:ui-mono,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --radius:16px; --shadow:0 18px 50px rgba(0,0,0,.55);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:var(--sans);color:var(--text);line-height:1.55;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;
  background:linear-gradient(180deg,var(--bg0),var(--bg1)) fixed;}
a{color:var(--accent2);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:0 1.4rem}

/* card chrome: top rule, grid, scanlines, corner brackets, starfield */
.toprule{height:15px;background:linear-gradient(180deg,var(--red) 0 8px,var(--accent) 8px 15px)}
.ticker{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  background:#080a10;color:var(--red);font-family:var(--mono);font-size:.72rem;
  letter-spacing:.2em;text-transform:uppercase;padding:.42rem 1.6rem;border-bottom:1px solid rgba(255,255,255,.06)}
.ticker .eyes{border:1px solid var(--accent);color:var(--accent);border-radius:8px;padding:.12rem .6rem;letter-spacing:.12em;white-space:nowrap}
.ticker .ref{color:var(--muted);letter-spacing:.12em}
.bg-glow{position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:.5;
  background:radial-gradient(1100px 520px at 78% -8%,rgba(255,196,48,.10),transparent 60%),
             radial-gradient(900px 480px at 10% 4%,rgba(226,60,58,.10),transparent 55%);}
.grid-ov{position:fixed;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
  background-size:60px 60px;}
.scan{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.45;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.06) 0 2px,transparent 2px 4px);}
.brackets span{position:fixed;width:54px;height:54px;border:3px solid var(--accent);z-index:5;pointer-events:none;opacity:.7}
.brackets .tl{top:16px;left:16px;border-right:none;border-bottom:none}
.brackets .tr{top:16px;right:16px;border-left:none;border-bottom:none}
.brackets .bl{bottom:16px;left:16px;border-right:none;border-top:none}
.brackets .br{bottom:16px;right:16px;border-left:none;border-top:none}
canvas#stars{position:fixed;inset:0;width:100%;height:100%;z-index:-3;opacity:.32}

/* nav */
nav{position:sticky;top:0;z-index:50;backdrop-filter:blur(10px);
  background:rgba(6,9,16,.80);border-bottom:1px solid var(--border)}
.nav-in{max-width:1180px;margin:0 auto;padding:.7rem 1.4rem;display:flex;align-items:center;gap:1rem}
.brand{display:flex;align-items:center;gap:.6rem;font-weight:700;letter-spacing:.02em}
.brand img{height:30px;width:30px;border-radius:7px;background:#0b0f17;padding:3px;border:1px solid var(--border2)}
.brand small{color:var(--accent);font-family:var(--mono);font-weight:700;font-size:.66rem;display:block;letter-spacing:.18em;text-transform:uppercase}
.nav-links{margin-left:auto;display:flex;gap:1.1rem;flex-wrap:wrap}
.nav-links a{color:var(--muted);font-size:.9rem}
.nav-links a:hover{color:var(--accent);text-decoration:none}

/* buttons */
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.55rem 1rem;border-radius:10px;
  font-weight:600;font-size:.9rem;border:1px solid var(--border2);color:var(--text);background:var(--panel2)}
.btn:hover{text-decoration:none;border-color:var(--accent);box-shadow:0 0 0 1px var(--border2)}
.btn.primary{background:linear-gradient(135deg,var(--accent),#e0a513);border-color:transparent;color:#1a1206}
.btn.primary:hover{filter:brightness(1.06)}

/* hero */
.hero{position:relative;padding:4.2rem 0 3rem;text-align:center}
.hero .tag{color:var(--red);font-family:var(--mono);font-weight:700;letter-spacing:.24em;text-transform:uppercase;font-size:.78rem}
.hero h1{font-size:clamp(2.1rem,5vw,3.4rem);margin:.6rem 0 .4rem;letter-spacing:-.5px;line-height:1.05}
.hero h1 .grad{background:linear-gradient(120deg,#fff,#ffd866 55%,var(--red));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p.lead{max-width:760px;margin:.6rem auto 0;color:var(--muted);font-size:1.05rem}

/* stats */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.9rem;margin:2.2rem 0}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:1.1rem 1rem;text-align:left;position:relative;overflow:hidden;box-shadow:var(--shadow);backdrop-filter:blur(4px)}
.stat:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
.stat:nth-child(2):before{background:var(--red)}
.stat:nth-child(3):before{background:var(--green)}
.stat:nth-child(4):before{background:var(--purple)}
.stat b{display:block;font-size:2rem;font-variant-numeric:tabular-nums;line-height:1;color:var(--text)}
.stat span{color:var(--accent);font-family:var(--mono);font-size:.7rem;text-transform:uppercase;letter-spacing:.08em}

/* sections */
section{padding:2.6rem 0}
.sec-head{display:flex;align-items:baseline;gap:.8rem;margin-bottom:1.1rem;flex-wrap:wrap}
.sec-head h2{margin:0;font-size:1.2rem;text-transform:uppercase;letter-spacing:.14em;color:var(--text)}
.sec-head h2::before{content:"";display:inline-block;width:9px;height:9px;background:var(--accent);
  margin-right:.6rem;transform:rotate(45deg);vertical-align:middle}
.sec-head .hint{color:var(--faint);font-family:var(--mono);font-size:.78rem}
.card-link{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem}
.tile{display:block;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:1.15rem;color:var(--text);transition:.15s;box-shadow:var(--shadow)}
.tile:hover{transform:translateY(-3px);border-color:var(--accent);text-decoration:none}
.tile .badge{font-family:var(--mono);font-size:.66rem;color:#1a1206;background:var(--accent);border-radius:20px;padding:.12rem .6rem;letter-spacing:.05em}
.tile h3{margin:.5rem 0 .3rem;font-size:1.05rem}
.tile p{margin:0;color:var(--muted);font-size:.85rem}

/* explorer */
.controls{display:flex;gap:.8rem;flex-wrap:wrap;align-items:center;margin-bottom:1.1rem}
.controls input,.controls select{background:#0a0e16;border:1px solid var(--border2);color:var(--text);
  border-radius:9px;padding:.5rem .7rem;font-size:.9rem;font-family:var(--sans)}
.controls input[type=range]{accent-color:var(--accent)}
.controls input[type=search]{min-width:230px;flex:1}
.chips{display:flex;gap:.4rem;flex-wrap:wrap}
.chip{cursor:pointer;font-family:var(--mono);font-size:.72rem;padding:.3rem .7rem;border-radius:20px;border:1px solid var(--border2);
  color:var(--muted);background:var(--panel);user-select:none;letter-spacing:.04em}
.chip.on{background:var(--accent);border-color:transparent;color:#1a1206}
.count-note{color:var(--faint);font-family:var(--mono);font-size:.8rem;margin:.2rem 0 .9rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1rem}
.lead{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;
  cursor:pointer;transition:.15s;display:flex;flex-direction:column;box-shadow:var(--shadow)}
.lead:hover{transform:translateY(-3px);border-color:var(--accent)}
.lead .thumb{aspect-ratio:16/9;background:#05070a;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}
.lead .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.lead .thumb .ph{color:var(--faint);font-size:.75rem}
.lead .stamp{position:absolute;top:9px;left:9px;transform:rotate(-7deg);
  border:2px solid var(--red);color:var(--red);font-family:var(--mono);font-size:.58rem;font-weight:700;
  padding:.16rem .42rem;border-radius:4px;letter-spacing:.05em;background:rgba(3,5,9,.45);pointer-events:none;white-space:nowrap}
.lead .corner-ref{position:absolute;right:8px;bottom:6px;font-family:var(--mono);font-size:.6rem;color:var(--muted);background:rgba(3,5,9,.5);padding:.05rem .35rem;border-radius:4px;pointer-events:none}
.lead .body{padding:.7rem .8rem;font-size:.82rem}
.lead .body .name{font-family:var(--mono);font-size:.74rem;color:var(--text);word-break:break-all}
.lead .body .row{display:flex;justify-content:space-between;color:var(--muted);margin-top:.25rem}
.pill{display:inline-block;font-family:var(--mono);font-size:.66rem;font-weight:700;padding:.1rem .5rem;border-radius:20px;letter-spacing:.03em}
.p-CONFIRMED-LEAD{background:#3a2a00;color:var(--accent)}
.p-PROMISING{background:#0d2a3a;color:#79c0ff}
.p-TERRAIN{background:#1a2e1f;color:var(--green)}
.p-NOISE{background:#2a1a1a;color:var(--red)}
.p-EXPLAINED-ARTIFACT{background:#2a2233;color:var(--purple)}
.p-WEAK{background:#2a2a2a;color:var(--faint)}

/* findings */
.findings{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem}
.finding-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
.fc-head{padding:.9rem 1rem;cursor:pointer;display:flex;align-items:center;gap:.6rem}
.fc-head .fid{font-family:var(--mono);font-size:.8rem;color:var(--accent)}
.fc-head .ft{margin-left:auto;color:var(--faint);transition:.2s}
.finding-card.open .ft{transform:rotate(45deg)}
.fc-body{max-height:0;overflow:hidden;transition:max-height .3s ease;padding:0 1rem}
.finding-card.open .fc-body{max-height:1200px;padding:0 1rem 1rem}
.fc-body .meta{color:var(--muted);font-size:.82rem}
.fc-body h4{margin:.8rem 0 .3rem;color:var(--text)}
.fc-sub{font-family:var(--mono);font-size:.7rem;color:var(--muted);padding:.1rem 1rem .55rem;letter-spacing:.03em}
.f-stamp{font-family:var(--mono);font-size:.58rem;font-weight:700;color:var(--red);border:2px solid var(--red);
  border-radius:4px;padding:.12rem .42rem;letter-spacing:.05em;transform:rotate(-5deg);margin-left:.4rem;white-space:nowrap}

/* methodology / prose */
.prose{max-width:900px}
.prose h2{font-size:1.3rem;border-bottom:1px solid var(--border);padding-bottom:.4rem;margin-top:2rem;
  color:var(--accent);text-transform:uppercase;letter-spacing:.08em}
.prose h3{font-size:1.1rem;margin-top:1.4rem;color:#cdd9e5}
.prose h4{margin:.9rem 0 .3rem;color:#b9c6d4}
.prose p,.prose li{color:#c4cfdb}
.prose code{font-family:var(--mono);background:#0b0f17;border:1px solid var(--border);border-radius:5px;padding:.05rem .35rem;font-size:.85em;color:var(--accent2)}
.prose blockquote{border-left:3px solid var(--accent);margin:1rem 0;padding:.2rem 1rem;color:var(--muted)}
.prose hr{border:none;border-top:1px solid var(--border);margin:1.4rem 0}

/* report table */
table.sortable{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.82rem}
table.sortable th,table.sortable td{border:1px solid var(--border);padding:.35rem .6rem;text-align:left}
table.sortable th{background:var(--panel2);cursor:pointer;position:sticky;top:54px;user-select:none;
  color:var(--accent);font-family:var(--mono);text-transform:uppercase;font-size:.72rem;letter-spacing:.05em}
table.sortable th:hover{color:var(--accent2)}
table.sortable tr:nth-child(even){background:rgba(255,255,255,.025)}

/* lightbox / dossier */
.lb{position:fixed;inset:0;background:rgba(3,5,9,.94);display:none;align-items:flex-start;justify-content:center;z-index:100;padding:3rem 1.5rem;overflow:auto}
.lb.open{display:flex}
.lb .x{position:fixed;top:1.2rem;right:1.6rem;font-size:2rem;color:var(--muted);cursor:pointer;line-height:1;z-index:2}
.lb .x:hover{color:var(--accent)}
.dossier{display:grid;grid-template-columns:minmax(280px,1.05fr) minmax(300px,1fr);gap:1.2rem;
  width:min(1000px,94vw);background:rgba(10,14,22,.97);border:1px solid var(--border2);border-radius:16px;
  padding:1.1rem;box-shadow:var(--shadow);position:relative}
.dossier-board{display:flex;flex-direction:column;gap:.5rem}
.db-img{background:#05070a;border:2px solid var(--border2);border-radius:10px;overflow:hidden;aspect-ratio:16/9;
  display:flex;align-items:center;justify-content:center}
.db-img img{width:100%;height:100%;object-fit:cover;display:block}
.db-cap{font-family:var(--mono);font-size:.72rem;color:var(--accent);letter-spacing:.08em}
.dossier-info{font-family:var(--mono);font-size:.8rem;color:var(--text)}
.dossier-info h3{margin:.1rem 0 .6rem;font-size:1rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);
  border-bottom:1px solid var(--border);padding-bottom:.4rem}
.df{display:flex;justify-content:space-between;gap:1rem;padding:.16rem 0;border-bottom:1px dashed rgba(255,255,255,.06)}
.df .k{color:var(--accent);letter-spacing:.03em}
.df .v{color:var(--text);text-align:right}
.dossier-info .sect{margin-top:.8rem;color:var(--accent);text-transform:uppercase;letter-spacing:.1em;font-size:.74rem}
.verify{list-style:none;margin:.3rem 0 0;padding:0;color:var(--muted);font-size:.74rem;line-height:1.7}
.verify li:before{content:"\203A ";color:var(--accent)}
.src-chip{border:1px solid var(--border2);border-radius:8px;padding:.4rem .6rem;margin-top:.5rem;word-break:break-all;font-size:.7rem}
.src-chip a{color:var(--accent2)}
@media(max-width:720px){.dossier{grid-template-columns:1fr}}

footer{border-top:3px solid var(--red);color:var(--muted);font-size:.78rem;text-align:left;
  padding:1.3rem 1.4rem 2.2rem;margin-top:2rem;background:#080a10;font-family:var(--mono)}
footer .fwrap{max-width:1180px;margin:0 auto;display:flex;flex-wrap:wrap;gap:.5rem 2rem;align-items:center}
footer a{color:var(--accent2)}
footer .src{color:var(--accent)}
footer .view{color:var(--faint)}
@media (max-width:640px){.nav-links{display:none}.stats{grid-template-columns:repeat(2,1fr)}.brackets span{display:none}}
"""

JS = r"""
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
"""

import hashlib


def _ver(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]


CSS_VER = _ver(CSS)
JS_VER = _ver(JS)

# --------------------------------------------------------------------------
# markdown -> html (lightweight)
# --------------------------------------------------------------------------
def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out, i = [], 0
    in_ul = in_ol = False

    def close():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        s = lines[i].strip()
        if not s:
            close()
            i += 1
            continue
        if s == "---":
            close()
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("# "):
            close()
            out.append(f"<h2>{inline(s[2:].strip())}</h2>")
        elif s.startswith("## "):
            close()
            out.append(f"<h3>{inline(s[3:].strip())}</h3>")
        elif s.startswith("### "):
            close()
            out.append(f"<h4>{inline(s[4:].strip())}</h4>")
        elif s.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(s[2:].strip())}</li>")
        elif re.match(r"^\d+\. ", s):
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline(re.sub(r'^\d+\. ', '', s))}</li>")
        elif s.startswith("> "):
            close()
            out.append(f"<blockquote>{inline(s[2:].strip())}</blockquote>")
        else:
            close()
            out.append(f"<p>{inline(s)}</p>")
        i += 1
    close()
    return "\n".join(out)


def finding_meta(txt: str) -> tuple[str, str]:
    m = re.search(r"Verdict:\s*([A-Za-z-]+)", txt)
    p = re.search(r"Product ID:\s*(\S+)", txt)
    return (m.group(1) if m else "", p.group(1) if p else "")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def strip_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            if f.name.startswith("T") and "_" in f.name and f.name.endswith(".jpg"):
                idx.setdefault(f.name.split("_", 1)[1][:-4], f)
    return idx


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def num(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v or default)
    except (TypeError, ValueError):
        return default


def top_leads(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r.get("verdict") != "CONFIRMED-LEAD":
            continue
        if num(r.get("contrast")) < 1.50:
            continue
        if r.get("near_edge") in ("True", "1"):
            continue
        area = int(num(r.get("area_px")))
        if area < 200 or area > 50000:
            continue
        out.append(r)
    out.sort(key=lambda r: num(r.get("score")), reverse=True)
    return out


def verdict_counts(rows: list[dict]) -> dict[str, int]:
    c: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict", "UNKNOWN")
        c[v] = c.get(v, 0) + 1
    return c


_ACQ = re.compile(r"^([A-Za-z]+_\d+_\d+)")


def acq_of(image: str) -> str:
    """Acquisition id, e.g. ESP_013236_1410 (strips band/variant suffixes)."""
    m = _ACQ.match(image or "")
    return m.group(1) if m else (image or "").split(".")[0]


def dedupe(rows: list[dict]) -> list[dict]:
    """Collapse the same physical feature that is reported once per band variant /
    enhancement of one acquisition. Key = (acquisition, x, y); keep the strongest
    (highest score) representative."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (acq_of(r.get("image", "")), int(round(num(r.get("x")))),
               int(round(num(r.get("y")))))
        cur = best.get(key)
        if cur is None or num(r.get("score")) > num(cur.get("score")):
            best[key] = r
    return sorted(best.values(), key=lambda r: num(r.get("score")), reverse=True)


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build_shared() -> None:
    a = SITE / "assets"
    a.mkdir(parents=True, exist_ok=True)
    (a / "style.css").write_text(CSS, encoding="utf-8")
    (a / "app.js").write_text(JS, encoding="utf-8")
    if (BRAND / "logo.svg").exists():
        shutil.copy2(BRAND / "logo.svg", a / "logo.svg")
    if (BRAND / "social-preview.png").exists():
        shutil.copy2(BRAND / "social-preview.png", a / "og-image.png")


def lead_json(rows, si, base="results/strips/") -> str:
    out = []
    for r in rows:
        img = r.get("image", "")
        strip = si.get(img)
        out.append({
            "image": img,
            "x": r.get("x"), "y": r.get("y"), "w": r.get("w"), "h": r.get("h"),
            "contrast": round(num(r.get("contrast")), 2),
            "score": round(num(r.get("score")), 1),
            "verdict": r.get("verdict", ""),
            "confidence": r.get("confidence", ""),
            "evidence_class": r.get("evidence_class", ""),
            "agrees": r.get("agrees", ""), "disagrees": r.get("disagrees", ""),
            "area_px": r.get("area_px", ""),
            "polarity": r.get("polarity", ""),
            "flags": r.get("flags", ""),
            "persistence": r.get("persistence", ""),
            "compactness": r.get("compactness", ""),
            "edge_sharpness": r.get("edge_sharpness", ""),
            "fdr_q": r.get("fdr_q", ""),
            "pixel_scale_m": r.get("pixel_scale_m", ""),
            "size_m": r.get("size_m", ""),
            "solar_elevation_deg": r.get("solar_elevation_deg", ""),
            "solar_azimuth_deg": r.get("solar_azimuth_deg", ""),
            "inferred_height_m": r.get("inferred_height_m", ""),
            "strip": (base + strip.name) if strip else "",
        })
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/")


def build_index(rows, leads, top, si, summary_md, meth_html, art_html) -> None:
    counts = verdict_counts(rows)
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))
    findings = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    fcards = ""
    for f in findings:
        txt = f.read_text(encoding="utf-8")
        v, p = finding_meta(txt)
        stamp = "<span class='f-stamp'>CONFIRMED LEAD</span>" if v.startswith("CONFIRMED") else ""
        sub = f"<div class='fc-sub'>PRODUCT {html.escape(p)} &middot; VERDICT {html.escape(v)}</div>"
        fcards += (
            f"<div class='finding-card'><div class='fc-head'><span class='fid'>{html.escape(f.name)}</span>{stamp}"
            f"<span class='ft'>+</span></div>{sub}<div class='fc-body prose'>{md_to_html(txt)}</div></div>"
        )
    chips = "".join(
        f"<span class='chip' data-v='{v}'>{v}</span>" for v in
        ["CONFIRMED-LEAD", "PROMISING", "TERRAIN", "EXPLAINED-ARTIFACT", "NOISE", "WEAK"]
    )
    body = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='description' content='Public NASA HiRISE anomaly investigation facility: acquire, catalog, enhance, detect, analyze, and adjudicate anomalies with statistical rigor.'>
<meta property='og:title' content='NASA HiRISE Anomaly Investigation — Public Facility'>
<meta property='og:description' content='Rigorous, reproducible anomaly investigation of public NASA HiRISE Mars & lunar imagery.'>
<meta property='og:image' content='{SITE_URL}/assets/og-image.png'>
<meta property='og:type' content='website'>
<link rel='icon' href='assets/logo.svg' type='image/svg+xml'>
<title>NASA HiRISE Anomaly Investigation — Public Facility</title>
<link rel='stylesheet' href='assets/style.css?v={CSS_VER}'></head><body>
<div class='toprule'></div>
<div class='ticker'><span>Classified // Anomaly Dossier &mdash; Public Facility</span><span class='eyes'>Eyes Only</span></div>
<div class='brackets'><span class='tl'></span><span class='tr'></span><span class='bl'></span><span class='br'></span></div>
<canvas id='stars'></canvas><div class='bg-glow'></div><div class='grid-ov'></div><div class='scan'></div>
<nav><div class='nav-in'>
  <a class='brand' href='#'><img src='assets/logo.svg' alt='logo'><span>NASA HiRISE<small>Anomaly Dossier</small></span></a>
  <div class='nav-links'>
    <a href='#overview'>Overview</a><a href='#explorer'>Explorer</a>
    <a href='#findings'>Findings</a><a href='#methodology'>Methodology</a>
    <a href='report/'>Report</a><a href='{BASE}'>Source</a>
  </div>
</div></nav>

<header class='hero'><div class='wrap'>
  <div class='tag'>Anomaly Dossier // Public Facility</div>
  <h1>NASA HiRISE <span class='grad'>Anomaly Investigation</span></h1>
  <p class='lead'>A rigorous, reproducible pipeline for analyzing public NASA HiRISE imagery of Mars &amp; the Moon &mdash;
  acquire, catalog, enhance, detect, analyze, and adjudicate anomalies with statistical rigor. Every step is documented,
  controlled, and built to <b>debunk</b> before anything is recorded as a finding.</p>
  <div class='stats'>
    <div class='stat'><b data-count='{len(rows)}'>0</b><span>Candidates</span></div>
    <div class='stat'><b data-count='{len(leads)}'>0</b><span>Leads</span></div>
    <div class='stat'><b data-count='{len(top)}'>0</b><span>Top leads</span></div>
    <div class='stat'><b data-count='{len(findings)}'>0</b><span>Findings</span></div>
  </div>
  <div style='display:flex;gap:.7rem;justify-content:center;flex-wrap:wrap'>
    <a class='btn primary' href='#explorer'>Explore the leads &rarr;</a>
    <a class='btn' href='report/'>Full Analysis Report</a>
    <a class='btn' href='{BASE}'>Source Repository</a>
  </div>
</div></header>

<section id='overview'><div class='wrap'>
  <div class='sec-head'><h2>Facility map</h2><span class='hint'>everything below is public &amp; verifiable</span></div>
  <div class='card-link'>
    <a class='tile' href='#explorer'><span class='badge'>Interactive</span><h3>Leads Explorer</h3><p>Search, filter and inspect every candidate with evidence strips.</p></a>
    <a class='tile' href='results/adjudicated.csv'><span class='badge'>Data</span><h3>Adjudicated Candidates</h3><p>Every candidate with its full verdict and metric columns (CSV).</p></a>
    <a class='tile' href='results/leads.csv'><span class='badge'>Data</span><h3>All Leads</h3><p>Complete metric set for every lead surfaced by the detector.</p></a>
    <a class='tile' href='#findings'><span class='badge'>Findings</span><h3>Finding Reports</h3><p>Per-lead dossiers (F-0001 &hellip;).</p></a>
    <a class='tile' href='#methodology'><span class='badge'>Docs</span><h3>Methodology</h3><p>The falsifiable, debunk-first investigation process.</p></a>
    <a class='tile' href='results/SUMMARY.md'><span class='badge'>Summary</span><h3>Adjudication Conclusion</h3><p>Funnel, verdict distribution, stress test, and bottom line.</p></a>
  </div>
</div></section>

<section id='explorer'><div class='wrap'>
  <div class='sec-head'><h2>Leads Explorer</h2><span class='hint'>all {len(rows)} adjudicated candidates</span></div>
  <div class='controls'>
    <input id='q' type='search' placeholder='Search image or flag&hellip;'>
    <label style='color:var(--muted);font-size:.85rem'>min contrast
      <input id='minC' type='range' min='0' max='4' step='0.05' value='0' style='vertical-align:middle'>
      <span id='minCval'>0</span></label>
    <select id='sort'>
      <option value='score'>sort: score</option>
      <option value='contrast'>sort: contrast</option>
      <option value='area_px'>sort: area</option>
      <option value='w'>sort: width</option>
    </select>
  </div>
  <div class='chips'>{chips}</div>
  <div id='leadNote' class='count-note'></div>
  <div id='leadsGrid' class='grid'></div>
</div></section>

<section id='findings'><div class='wrap'>
  <div class='sec-head'><h2>Finding Reports</h2><span class='hint'>{len(findings)} dossiers</span></div>
  <div class='findings'>{fcards}</div>
</div></section>

<section id='methodology'><div class='wrap'>
  <div class='sec-head'><h2>Methodology</h2><span class='hint'>from docs/</span></div>
  <div class='prose'>{meth_html}</div>
  <div class='sec-head' style='margin-top:2.5rem'><h2>Known Artifacts &mdash; the Checklist</h2></div>
  <div class='prose'>{art_html}</div>
</div></section>

<footer><div class='fwrap'>
  <span>Public facility &middot; Data: NASA/JPL HiRISE PDS (public domain) &middot; MIT License</span>
  <span class='src'>SOURCE &nbsp;{BASE}</span>
  <span class='view'>VIEW &nbsp; {SITE_URL}/report/</span>
  <a href='../'>Home</a>
</div></footer>

<div class='lb' id='lb'><span class='x'>&times;</span><div class='dossier' id='lbDossier'></div></div>
<script>{lead_json(rows, si)}</script>
<script src='assets/app.js?v={JS_VER}'></script>
</body></html>"""
    (SITE / "index.html").write_text(body, encoding="utf-8")


def build_report(rows, leads, si, summary_md) -> None:
    counts = verdict_counts(rows)
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))
    top = dedupe(top_leads(rows))
    # top-lead cards (server rendered, first 60)
    cards = []
    for i, r in enumerate(top[:60]):
        strip = si.get(r["image"])
        img = f"<img loading='lazy' src='../results/strips/{strip.name}' alt='{html.escape(r['image'])}'>" if strip else "<div class='ph'>no strip</div>"
        flags = (r["flags"].split(",") if r.get("flags") else [])
        fh = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
        cards.append(
            f"<div class='lead' onclick=\"openDossier('{html.escape(r['image'])}')\">"
            f"<div class='thumb'>{img}{('<div class=stamp>CONFIRMED LEAD</div>' if r['verdict'].startswith('CONFIRMED') else '')}"
            f"<div class='corner-ref'>x{r.get('x')} y{r.get('y')}</div></div><div class='body'>"
            f"<div class='name'>{i+1}. {html.escape(r['image'])}</div>"
            f"<div class='row'><span class='pill p-{r['verdict']}'>{r['verdict']}</span><span>{round(num(r['score']))}</span></div>"
            f"<div class='row'><span>contrast {round(num(r['contrast']),2)}</span><span>{r['w']}x{r['h']}</span></div>"
            f"<div class='row'><span>flags</span></div><ul style='margin:.1rem 0 0 1rem;color:var(--muted);font-size:.75rem'>{fh}</ul>"
            f"</div></div>"
        )
    # full sortable table
    trs = []
    for i, r in enumerate(top):
        trs.append(
            f"<tr><td>{i+1}</td><td>{html.escape(r['image'])}</td><td>{round(num(r['score']))}</td>"
            f"<td>{r['x']},{r['y']}</td><td>{html.escape(r.get('evidence_class',''))}</td>"
            f"<td class='p-{r['verdict']}' style='color:inherit'>{html.escape(r['verdict'])}</td>"
            f"<td>{round(num(r['contrast']),2)}</td><td>{r.get('agrees','')}/{r.get('disagrees','')}</td>"
            f"<td>{r.get('area_px','')}</td></tr>"
        )
    findings = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    fhtml = ""
    for f in findings:
        txt = f.read_text(encoding="utf-8")
        v, p = finding_meta(txt)
        stamp = "<span class='f-stamp'>CONFIRMED LEAD</span>" if v.startswith("CONFIRMED") else ""
        sub = f"<div class='fc-sub'>PRODUCT {html.escape(p)} &middot; VERDICT {html.escape(v)}</div>"
        fhtml += (
            f"<div class='finding-card'><div class='fc-head'><span class='fid'>{html.escape(f.name)}</span>{stamp}"
            f"<span class='ft'>+</span></div>{sub}<div class='fc-body prose'>{md_to_html(txt)}</div></div>"
        )
    body = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta property='og:title' content='NASA HiRISE Anomaly Analysis Report'>
<meta property='og:image' content='{SITE_URL}/assets/og-image.png'>
<link rel='icon' href='../assets/logo.svg' type='image/svg+xml'>
<title>NASA HiRISE — Anomaly Analysis Report</title>
<link rel='stylesheet' href='../assets/style.css?v={CSS_VER}'></head><body>
<div class='toprule'></div>
<div class='ticker'><span>Classified // Anomaly Dossier &mdash; Adjudication</span><span class='eyes'>Eyes Only</span></div>
<div class='brackets'><span class='tl'></span><span class='tr'></span><span class='bl'></span><span class='br'></span></div>
<div class='bg-glow'></div><div class='grid-ov'></div><div class='scan'></div>
<nav><div class='nav-in'>
  <a class='brand' href='../'><img src='../assets/logo.svg' alt='logo'><span>NASA HiRISE<small>Anomaly Dossier</small></span></a>
  <div class='nav-links'><a href='../#overview'>Home</a><a href='../#explorer'>Explorer</a><a href='../#findings'>Findings</a><a href='{BASE}'>Source</a></div>
</div></nav>
<header class='hero'><div class='wrap'>
  <div class='tag'>Adjudication // Dossier</div>
  <h1>Anomaly <span class='grad'>Analysis Report</span></h1>
  <p class='lead'>{len(rows)} candidates adjudicated &middot; {len(leads)} leads &middot; {len(findings)} finding reports.</p>
  <div class='stats'>
    <div class='stat'><b data-count='{len(rows)}'>0</b><span>Candidates</span></div>
    <div class='stat'><b data-count='{len(leads)}'>0</b><span>Leads</span></div>
    <div class='stat'><b data-count='{len(top)}'>0</b><span>Top leads</span></div>
    <div class='stat'><b data-count='{len(findings)}'>0</b><span>Findings</span></div>
  </div>
  <p style='color:var(--muted)'>Verdict distribution: {dist}</p>
</div></header>

<section><div class='wrap'>
  <div class='sec-head'><h2>Top leads preview</h2><span class='hint'>{min(60,len(top))} of {len(top)} with strips &mdash; click to enlarge</span></div>
  <div class='grid'>{''.join(cards)}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>All top leads ({len(top)})</h2><span class='hint'>click a column header to sort</span></div>
  <table class='sortable'><thead><tr>
    <th data-key='#'>#</th><th data-key='image'>image</th><th data-key='score'>score</th>
    <th data-key='xy'>xy</th><th data-key='class'>class</th><th data-key='verdict'>verdict</th>
    <th data-key='contrast'>contrast</th><th data-key='xb'>X-band</th><th data-key='area'>area</th></tr></thead>
    <tbody>{''.join(trs)}</tbody></table>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Adjudication summary</h2></div>
  <div class='prose'>{md_to_html(summary_md) if summary_md else ''}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Finding reports ({len(findings)})</h2></div>
  <div class='findings'>{fhtml}</div>
</div></section>

<footer>Public facility &middot; <a href='../'>Home</a> &middot; <a href='{BASE}'>Source</a> &middot; MIT License</footer>
<div class='lb' id='lb'><span class='x'>&times;</span><div class='dossier' id='lbDossier'></div></div>
<script>{lead_json(rows, si, '../results/strips/')}</script>
<script src='../assets/app.js?v={JS_VER}'></script>
</body></html>"""
    (SITE / "report" / "index.html").write_text(body, encoding="utf-8")


def build_results() -> None:
    res = SITE / "results"
    if res.exists():
        shutil.rmtree(res)
    res.mkdir(parents=True)
    for name in ("adjudicated.csv", "leads.csv", "SUMMARY.md"):
        src = CONC / name
        if src.exists():
            shutil.copy2(src, res / name)
    fdir = res / "findings"
    fdir.mkdir(parents=True, exist_ok=True)
    for f in sorted(LEADS_DIR.glob("F-*.md")):
        shutil.copy2(f, fdir / f.name)
    sdir = res / "strips"
    sdir.mkdir(parents=True, exist_ok=True)
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            if f.name.endswith(".jpg"):
                shutil.copy2(f, sdir / f.name)


def main() -> None:
    si = strip_index()
    rows = read_csv(CONC / "adjudicated.csv")
    leads = read_csv(CONC / "leads.csv")
    summary_md = (CONC / "SUMMARY.md").read_text(encoding="utf-8") if (CONC / "SUMMARY.md").exists() else ""
    meth = md_to_html((DOCS / "METHODOLOGY.md").read_text(encoding="utf-8")) if (DOCS / "METHODOLOGY.md").exists() else ""
    art = md_to_html((DOCS / "ARTIFACTS.md").read_text(encoding="utf-8")) if (DOCS / "ARTIFACTS.md").exists() else ""

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    (SITE / "report").mkdir(parents=True)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    build_shared()
    rows_d = dedupe(rows)
    leads_d = dedupe(leads)
    top = dedupe(top_leads(rows))
    build_index(rows_d, leads_d, top, si, summary_md, meth, art)
    build_report(rows_d, leads_d, si, summary_md)
    build_results()

    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"Built site/ ({size//1024} KB): landing+explorer + report + {len(rows_d)} candidates + "
          f"{len(top)} top leads + {len(list(LEADS_DIR.glob('F-*.md')))} findings + "
          f"{len(list((SITE/'results'/'strips').glob('*.jpg')))} strips")


if __name__ == "__main__":
    main()
