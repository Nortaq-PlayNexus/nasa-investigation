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

import csv
import html
import json
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    from PIL import Image

    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
STRIPS = CONC / "strips"
LEADS_DIR = CONC / "leads"
DOCS = ROOT / "docs"
BRAND = ROOT / "assets" / "branding"
SITE = ROOT / "site"

# live 6h uplink window (set once by the agent; embedded as absolute epoch so rebuilds keep it)
_TIMER_PATH = Path(r"C:\Users\natha\AppData\Local\Temp\opencode\timer_end.txt")
TIMER_END = 0
try:
    TIMER_END = int(_TIMER_PATH.read_text().strip())
except Exception:
    TIMER_END = 0


def timer_html() -> str:
    if not TIMER_END:
        return ""
    return "<div id='uplink' class='uplink'>UPLINK WINDOW // <span id='uplinkClock'>--:--:--</span> REMAINING</div>"


def _git_rev() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT)
            .decode()
            .strip()
        )
    except Exception:
        return "n/a"


BUILD_TS = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
BUILD_REV = _git_rev()
BUILD_EPOCH = int(time.time())


def crop_box(path, x, y, w, h):
    """Return [lx,ty,fw,fh] fractions of `path` to frame the feature at (x,y,w,h)."""
    if not _HAVE_PIL or not path or not Path(path).exists():
        return None
    try:
        with Image.open(path) as im:
            W, H = im.size
    except Exception:
        return None
    try:
        x, y, w, h = (int(float(v)) for v in (x, y, w, h))
    except Exception:
        return None
    if W <= 0 or H <= 0 or w <= 0 or h <= 0:
        return None
    cx = x + w / 2.0
    cy = y + h / 2.0
    Z = max(w, h) * 7.0
    Z = max(Z, 40.0)
    Z = min(Z, min(W, H))
    if Z >= min(W, H):
        return [0.0, 0.0, 1.0, 1.0]
    left = max(0.0, min(W - Z, cx - Z / 2.0))
    top = max(0.0, min(H - Z, cy - Z / 2.0))
    return [left / W, top / H, Z / W, Z / H]


def crop_style(url, crop):
    """CSS background-crop string to frame a sub-rectangle of the image."""
    if not url or not crop:
        return None
    fw, fh = crop[2], crop[3]
    bx = 0.0 if fw >= 1 else crop[0] / (1 - fw) * 100.0
    by = 0.0 if fh >= 1 else crop[1] / (1 - fh) * 100.0
    return (
        "background-image:url(%s);background-repeat:no-repeat;"
        "background-size:%.2f%% %.2f%%;background-position:%.2f%% %.2f%%"
        % (url, 100.0 / fw, 100.0 / fh, bx, by)
    )


REPO = "Nortaq-PlayNexus/nasa-investigation"
BASE = f"https://github.com/{REPO}"
SITE_URL = "https://nortaq-playnexus.github.io/nasa-investigation"

# --------------------------------------------------------------------------
# design system
# --------------------------------------------------------------------------
CSS = r"""
:root{
  --bg:#05070a; --bg2:#0a0e1a; --panel:#0f1421; --panel2:#151b2e; --line:#1e2a44; --line2:rgba(255,196,48,.25);
  --text:#e6edf7; --muted:#8a9ab8; --faint:#5e6b86;
  --accent:#ffc430; --accent2:#ffd866; --red:#ff3b3b; --cyan:#3dd5ff; --green:#2ecc71; --purple:#a78bfa;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; --sans:Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  --r:16px; --r2:20px; --shadow:0 20px 60px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.04);
}
*{box-sizing:border-box} html{scroll-behavior:smooth}
body{margin:0;font-family:var(--sans);color:var(--text);line-height:1.6;background:var(--bg);overflow-x:hidden;-webkit-font-smoothing:antialiased}
a{color:var(--cyan);text-decoration:none} a:hover{text-decoration:underline}
.wrap{max-width:1240px;margin:0 auto;padding:0 20px}
/* chrome */
.toprule{height:14px;background:linear-gradient(90deg,var(--red) 0 50%,var(--accent) 50% 100%);position:relative}
.toprule:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.18),transparent);animation:shimmer 3s linear infinite}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.ticker{display:flex;justify-content:space-between;align-items:center;background:#080a10;color:var(--red);font-family:var(--mono);font-size:.70rem;letter-spacing:.18em;text-transform:uppercase;padding:.45rem 1.4rem;border-bottom:1px solid rgba(255,255,255,.06)}
.ticker .eyes{border:1px solid var(--accent);color:var(--accent);border-radius:999px;padding:.15rem .6rem;background:rgba(255,196,48,.08)}
.brackets span{position:fixed;width:48px;height:48px;border:2px solid var(--accent);z-index:5;pointer-events:none;opacity:.55}
.brackets .tl{top:14px;left:14px;border-right:none;border-bottom:none}
.brackets .tr{top:14px;right:14px;border-left:none;border-bottom:none}
.brackets .bl{bottom:14px;left:14px;border-right:none;border-top:none}
.brackets .br{bottom:14px;right:14px;border-left:none;border-top:none}
canvas#stars{position:fixed;inset:0;width:100%;height:100%;z-index:-3;opacity:.28}
.bg-glow{position:fixed;inset:0;z-index:-2;pointer-events:none;background:radial-gradient(900px 500px at 75% -10%,rgba(255,196,48,.10),transparent 60%),radial-gradient(700px 400px at 15% 10%,rgba(61,213,255,.08),transparent 55%),radial-gradient(600px 300px at 50% 90%,rgba(168,139,250,.06),transparent)}
.grid-ov{position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px);background-size:72px 72px}
.scan{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.35;background:repeating-linear-gradient(0deg,rgba(0,0,0,.04) 0 2px,transparent 2px 4px)}
/* nav - glass */
nav{position:sticky;top:0;z-index:40;backdrop-filter:blur(12px) saturate(1.2);background:rgba(8,12,22,.72);border-bottom:1px solid rgba(255,255,255,.06)}
.nav-in{max-width:1240px;margin:0 auto;padding:.75rem 20px;display:flex;align-items:center;gap:1rem}
.brand{display:flex;align-items:center;gap:.7rem;font-weight:800;letter-spacing:-.02em;color:var(--text)}
.brand img{width:32px;height:32px;border-radius:8px;background:#0b0f1f;border:1px solid var(--line2);padding:4px}
.brand small{display:block;font-family:var(--mono);font-size:.62rem;color:var(--accent);letter-spacing:.16em;font-weight:700}
.nav-links{margin-left:auto;display:flex;gap:1.2rem}
.nav-links a{color:var(--muted);font-size:.88rem;font-weight:600;letter-spacing:.02em}
.nav-links a:hover{color:var(--accent);text-decoration:none}
.nav-toggle{display:none;background:none;border:1px solid var(--line2);color:var(--accent);font-size:1.1rem;padding:.3rem .6rem;border-radius:8px;cursor:pointer}
/* hero redesign */
.hero{position:relative;padding:5rem 0 3.5rem;overflow:hidden}
.hero .reticle{position:absolute;left:50%;top:45%;width:520px;height:520px;transform:translate(-50%,-50%);border:1px solid rgba(255,196,48,.10);border-radius:50%;pointer-events:none}
.hero .reticle:before,.hero .reticle:after{content:"";position:absolute;background:rgba(255,196,48,.10)}
.hero .reticle:before{left:50%;top:-40px;bottom:-40px;width:1px} .hero .reticle:after{top:50%;left:-40px;right:-40px;height:1px}
.hero .reticle .ring2{position:absolute;inset:80px;border:1px dashed rgba(255,196,48,.08);border-radius:50%}
.hero .reticle .sweep{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,transparent 0 280deg,rgba(255,196,48,.18) 358deg,rgba(255,196,48,.06));animation:retspin 9s linear infinite;mix-blend-mode:screen}
@keyframes retspin{to{transform:rotate(360deg)}}
.hero .tag{color:var(--red);font-family:var(--mono);font-weight:700;letter-spacing:.22em;text-transform:uppercase;font-size:.76rem;display:inline-flex;align-items:center;gap:.5rem}
.hero .tag:before{content:"●";color:var(--red);animation:pulse 1.6s ease infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.hero h1{font-size:clamp(2.4rem,5.5vw,3.8rem);margin:.7rem 0 .5rem;letter-spacing:-.04em;line-height:.95;font-weight:900}
.hero h1 .grad{background:linear-gradient(135deg,#fff 30%,var(--accent) 60%,var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p.lead{max-width:820px;margin:.8rem auto 0;color:var(--muted);font-size:1.08rem;line-height:1.6}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:2.4rem 0}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{position:relative;background:linear-gradient(180deg,rgba(21,27,46,.9),rgba(15,20,33,.9));border:1px solid var(--line);border-radius:var(--r);padding:1.15rem 1rem;overflow:hidden;backdrop-filter:blur(6px);box-shadow:var(--shadow)}
.stat:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
.stat:nth-child(2):before{background:var(--red)} .stat:nth-child(3):before{background:var(--cyan)} .stat:nth-child(4):before{background:var(--purple)}
.stat b{display:block;font-size:2.1rem;line-height:1;font-weight:800;font-variant-numeric:tabular-nums}
.stat span{color:var(--accent);font-family:var(--mono);font-size:.68rem;letter-spacing:.08em;text-transform:uppercase}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;padding:.6rem 1.1rem;border-radius:10px;font-weight:700;font-size:.9rem;border:1px solid var(--line2);color:var(--text);background:rgba(21,27,46,.8);backdrop-filter:blur(4px);transition:.16s}
.btn:hover{text-decoration:none;border-color:var(--accent);transform:translateY(-1px);box-shadow:0 6px 20px rgba(255,196,48,.12)}
.btn.primary{background:linear-gradient(135deg,var(--accent),#e6a800);color:#1a1200;border-color:transparent;box-shadow:0 8px 24px rgba(255,196,48,.24)}
.btn.primary:hover{filter:brightness(1.05)}
/* sections */
section{padding:2.8rem 0;border-top:1px solid rgba(255,255,255,.04)}
.sec-head{display:flex;align-items:center;gap:.9rem;margin-bottom:1.2rem;flex-wrap:wrap}
.sec-head h2{margin:0;font-size:.95rem;letter-spacing:.16em;text-transform:uppercase;color:var(--text);display:flex;align-items:center;gap:.6rem}
.sec-head h2:before{content:"";width:10px;height:10px;background:var(--accent);transform:rotate(45deg);box-shadow:0 0 10px rgba(255,196,48,.5)}
.sec-head .hint{color:var(--faint);font-family:var(--mono);font-size:.76rem;margin-left:auto}
.card-link{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.tile{position:relative;display:block;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:1.25rem;overflow:hidden;transition:.18s;box-shadow:var(--shadow)}
.tile:before{content:"";position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,196,48,.06),transparent 60%);opacity:0;transition:.18s}
.tile:hover{transform:translateY(-4px);border-color:var(--line2);box-shadow:0 12px 32px rgba(0,0,0,.5)}
.tile:hover:before{opacity:1}
.tile .badge{font-family:var(--mono);font-size:.62rem;color:#111;background:var(--accent);border-radius:999px;padding:.2rem .6rem;font-weight:800;letter-spacing:.06em}
.tile h3{margin:.6rem 0 .3rem;font-size:1.04rem;font-weight:800;letter-spacing:-.01em}
.tile p{margin:0;color:var(--muted);font-size:.86rem;line-height:1.5}
/* explorer redesign */
.controls{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;background:rgba(15,20,33,.6);border:1px solid var(--line);border-radius:12px;padding:.6rem;backdrop-filter:blur(8px);margin-bottom:1rem}
.controls input,.controls select{background:#0a0e19;border:1px solid var(--line);color:var(--text);border-radius:10px;padding:.55rem .75rem;font-size:.88rem}
.controls input[type=search]{min-width:260px;flex:1}
.controls input:focus,.controls select:focus{outline:2px solid rgba(255,196,48,.3);border-color:var(--accent)}
.chips{display:flex;gap:.45rem;flex-wrap:wrap}
.chip{cursor:pointer;font-family:var(--mono);font-size:.70rem;padding:.32rem .75rem;border-radius:999px;border:1px solid var(--line2);color:var(--muted);background:rgba(15,20,33,.5);transition:.14s}
.chip.on{background:var(--accent);color:#111;border-color:transparent;font-weight:700;box-shadow:0 0 12px rgba(255,196,48,.3)}
.chip:hover{border-color:var(--accent);color:var(--text)}
.count-note{color:var(--faint);font-family:var(--mono);font-size:.78rem;margin:.4rem 0 1rem;padding:.5rem .8rem;background:rgba(15,20,33,.4);border:1px dashed var(--line);border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.lead{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;cursor:pointer;transition:.18s;display:flex;flex-direction:column;box-shadow:var(--shadow)}
.lead:hover{transform:translateY(-4px);border-color:var(--line2);box-shadow:0 16px 40px rgba(0,0,0,.5)}
.lead .thumb{aspect-ratio:16/9;background:#05070a;position:relative;overflow:hidden}
.lead .thumb .crop{position:absolute;inset:0;background-color:#05070a;background-size:cover;transition:transform .4s ease}
.lead:hover .thumb .crop{transform:scale(1.04)}
.lead .stamp{position:absolute;top:10px;left:10px;transform:rotate(-6deg);border:2px solid var(--red);color:var(--red);font-family:var(--mono);font-size:.58rem;font-weight:800;padding:.18rem .45rem;border-radius:6px;background:rgba(5,7,10,.55);backdrop-filter:blur(4px)}
.lead .corner-ref{position:absolute;right:8px;bottom:8px;font-family:var(--mono);font-size:.62rem;color:var(--accent);background:rgba(5,7,10,.6);border:1px solid rgba(255,196,48,.25);padding:.2rem .45rem;border-radius:6px}
.lead .body{padding:.8rem .9rem}
.lead .body .name{font-family:var(--mono);font-size:.74rem;color:var(--text);font-weight:700;word-break:break-all;display:flex;gap:.4rem;align-items:center}
.lead .body .row{display:flex;justify-content:space-between;align-items:center;margin-top:.35rem;font-size:.82rem;color:var(--muted)}
.pill{display:inline-flex;align-items:center;font-family:var(--mono);font-size:.64rem;font-weight:800;padding:.18rem .5rem;border-radius:999px;letter-spacing:.03em}
.p-CONFIRMED-LEAD{background:rgba(255,196,48,.14);color:var(--accent);border:1px solid rgba(255,196,48,.25)}
.p-PROMISING{background:rgba(61,213,255,.12);color:var(--cyan);border:1px solid rgba(61,213,255,.22)}
.p-TERRAIN{background:rgba(46,204,113,.12);color:var(--green);border:1px solid rgba(46,204,113,.2)}
.p-NOISE{background:rgba(255,59,59,.10);color:var(--red);border:1px solid rgba(255,59,59,.18)}
.p-EXPLAINED-ARTIFACT{background:rgba(167,139,250,.12);color:var(--purple);border:1px solid rgba(167,139,250,.2)}
.p-WEAK{background:rgba(255,255,255,.06);color:var(--faint);border:1px solid var(--line)}
.vcount{display:inline-flex;align-items:center;gap:.3rem;font-family:var(--mono);font-size:.64rem;font-weight:800;background:rgba(255,196,48,.14);border:1px solid var(--line2);color:var(--accent);border-radius:999px;padding:.18rem .5rem}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:.6rem;margin:.7rem 0}
.gallery figure{margin:0;background:#05070a;border:1px solid var(--line2);border-radius:10px;overflow:hidden;transition:.15s}
.gallery figure:hover{border-color:var(--accent);transform:translateY(-2px)}
.gallery figure img{width:100%;height:112px;object-fit:cover;display:block}
.gallery figcaption{font-family:var(--mono);font-size:.66rem;color:var(--muted);padding:.3rem .45rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* findings */
.findings{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
.finding-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;box-shadow:var(--shadow);transition:.16s}
.finding-card:hover{border-color:var(--line2)}
.fc-head{padding:.9rem 1rem;cursor:pointer;display:flex;align-items:center;gap:.6rem}
.fc-head .fid{font-family:var(--mono);font-size:.82rem;color:var(--accent);font-weight:800}
.fc-head .ft{margin-left:auto;color:var(--faint);transition:.2s;font-size:1.1rem}
.finding-card.open .ft{transform:rotate(45deg);color:var(--accent)}
.fc-body{max-height:0;overflow:hidden;transition:max-height .35s ease;padding:0 1rem}
.finding-card.open .fc-body{max-height:1400px;padding:0 1rem 1rem}
.fc-sub{font-family:var(--mono);font-size:.70rem;color:var(--muted);padding:.1rem 1rem .6rem}
.f-stamp{font-family:var(--mono);font-size:.58rem;font-weight:800;color:var(--red);border:2px solid var(--red);border-radius:6px;padding:.15rem .45rem;transform:rotate(-4deg);background:rgba(255,59,59,.08)}
/* dossier */
.lb{position:fixed;inset:0;background:rgba(3,5,10,.88);backdrop-filter:blur(8px);display:none;align-items:flex-start;justify-content:center;z-index:100;padding:2rem 1rem;overflow:auto}
.lb.open{display:flex;animation:lbIn .22s ease}
@keyframes lbIn{from{opacity:0}to{opacity:1}}
.lb .x{position:fixed;top:1rem;right:1.2rem;font-size:2rem;color:var(--muted);cursor:pointer;z-index:2;width:40px;height:40px;display:grid;place-items:center;background:rgba(15,20,33,.8);border:1px solid var(--line);border-radius:50%}
.lb .x:hover{color:var(--accent);border-color:var(--accent)}
.dossier{display:grid;grid-template-columns:1.1fr .95fr;gap:1.2rem;width:min(1100px,96vw);background:linear-gradient(180deg,#0f1421,#0a0e1a);border:1px solid var(--line2);border-radius:20px;padding:1.2rem;box-shadow:0 24px 80px rgba(0,0,0,.7)}
.dossier-board{display:flex;flex-direction:column;gap:.6rem}
.db-img{position:relative;background:#05070a;border:1px solid var(--line2);border-radius:12px;overflow:hidden;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center}
.db-img .crop{position:absolute;inset:0;background-size:cover}
.db-ctx{position:relative;margin-top:.6rem;border:1px solid var(--line2);border-radius:10px;overflow:hidden;aspect-ratio:16/9;background:#05070a}
.db-ctx img{width:100%;height:100%;object-fit:cover;display:block;opacity:.86}
.db-ctx .box{position:absolute;border:2px solid var(--red);box-shadow:0 0 0 1px rgba(0,0,0,.6),0 0 12px rgba(255,59,59,.5)}
.db-cap{font-family:var(--mono);font-size:.72rem;color:var(--accent);letter-spacing:.08em}
.dossier-info{font-family:var(--mono);font-size:.80rem;color:var(--text)}
.dossier-info h3{margin:.1rem 0 .6rem;font-size:1rem;letter-spacing:.06em;color:var(--accent);border-bottom:1px solid var(--line);padding-bottom:.45rem}
.df{display:flex;justify-content:space-between;gap:1rem;padding:.22rem 0;border-bottom:1px dashed rgba(255,255,255,.06)}
.df .k{color:var(--muted);letter-spacing:.02em;font-size:.76rem}
.df .v{color:var(--text);text-align:right;font-weight:700}
.dossier-info .sect{margin-top:.9rem;color:var(--accent);letter-spacing:.08em;font-size:.74rem;font-weight:800}
.verify{list-style:none;margin:.3rem 0 0;padding:0;color:var(--muted);font-size:.74rem;line-height:1.7}
.verify li:before{content:"› ";color:var(--accent);font-weight:800}
.src-chip{border:1px solid var(--line2);border-radius:8px;padding:.45rem .6rem;margin-top:.5rem;word-break:break-all;font-size:.70rem;background:rgba(255,196,48,.06)}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:.4rem 0 1.6rem}
.step{background:linear-gradient(180deg,rgba(21,27,46,.6),rgba(15,20,33,.6));border:1px solid var(--line);border-radius:12px;padding:.9rem 1rem;position:relative}
.step .n{font-family:var(--mono);font-size:1.3rem;color:var(--red);font-weight:800}
.step h4{margin:.2rem 0 .25rem;font-size:.92rem;letter-spacing:.08em;color:var(--accent)}
.step p{margin:0;color:var(--muted);font-size:.78rem}
@media(max-width:900px){.steps{grid-template-columns:repeat(2,1fr)} .dossier{grid-template-columns:1fr}}
.vbars{display:flex;flex-direction:column;gap:.55rem;max-width:760px}
.vrow{display:grid;grid-template-columns:170px 1fr 56px;gap:.7rem;align-items:center;font-family:var(--mono);font-size:.78rem}
.vl{color:var(--muted);text-align:right}
.vbar{background:rgba(255,255,255,.05);height:12px;border-radius:999px;overflow:hidden;border:1px solid rgba(255,255,255,.04)}
.vfill{display:block;height:100%;background:var(--accent)}
.vfill.v-conf{background:var(--red)}
.vc{color:var(--accent);text-align:left;font-weight:700}
.tchip{border:1px solid var(--line2);border-radius:999px;padding:.35rem .85rem;font-family:var(--mono);font-size:.78rem;color:var(--text);background:rgba(255,255,255,.03)}
.tchip b{color:var(--accent)}
footer{border-top:2px solid var(--red);background:#080a10;color:var(--muted);font-family:var(--mono);font-size:.78rem;padding:1.4rem;text-align:center}
html.reveal-on section{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease}
html.reveal-on section.in{opacity:1;transform:none}
.uplink{position:fixed;left:14px;bottom:14px;z-index:60;font-family:var(--mono);font-size:.70rem;letter-spacing:.1em;color:var(--accent);background:rgba(8,12,22,.9);border:1px solid var(--line2);border-left:3px solid var(--red);padding:.4rem .7rem;border-radius:8px}
.to-top{position:fixed;right:14px;bottom:14px;z-index:60;width:40px;height:40px;border-radius:50%;border:1px solid var(--line2);background:rgba(8,12,22,.9);color:var(--accent);cursor:pointer;display:none}
.to-top.show{display:grid;place-items:center}
.prose{max-width:900px} .prose h2{color:var(--accent)} .prose code{color:var(--accent2)}
"""

JS = r"""
(function(){
  var LEADS = [];
  var DIVERSE = [];
  var SB = window.STRIP_BASE || 'results/strips/';
  function stripUrl(n){return n ? SB + n : '';}
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
      var strip=cropDiv(r);
      var variants = r.variants || r.members || [];
      var vc = variants.length>1 ? '<span class="vcount">'+variants.length+' views</span>' : '';
      var bands = (r.bands||[]).map(function(b){return '<span class="pill p-'+r.verdict+'" style="background:#0d1a21;color:#7fd4e8;border:1px solid #16404d;font-size:.62rem">'+b+'</span>';}).join('');
      // show base as title, with count; still index by base so dossier groups open
      var title = escH(r.base||r.image);
      var scoreDisp = r.max_score!=null?r.max_score:r.score;
      var contrastDisp = r.max_contrast!=null?r.max_contrast:r.contrast;
      var verdictDisp = r.verdict|| (r.verdicts?r.verdicts[0]:'');
      return '<div class="lead" data-img="'+escH(r.base||r.image)+'" data-strip="'+escH(r.strip||'')+'">'
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
      var lm=document.getElementById('loadMore');
      if(lm){
        lm.style.display = rows.length ? 'inline-block' : 'none';
        // LOOP label: continuous — at end show wrap option
        if(state.limit>=rows.length) lm.textContent='↺ Loop to start — '+rows.length+' total (click to restart at top)';
        else lm.textContent='Load more — '+cap+' / '+rows.length+' (loops at end)';
      }
      Array.prototype.forEach.call(grid.querySelectorAll('.lead'),function(el){
        el.addEventListener('click',function(){openDossier(el.getAttribute('data-img'));});});}
    var q=document.getElementById('q'),mc=document.getElementById('minC'),sort=document.getElementById('sort');
    q.addEventListener('input',function(){state.q=q.value;render();});
    mc.addEventListener('input',function(){state.minC=+mc.value;document.getElementById('minCval').textContent=mc.value;render();});
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
  if(fs){fs.addEventListener('input',function(){
    var q=fs.value.toLowerCase().trim();
    document.querySelectorAll('#findings .finding-card').forEach(function(c){
      var hay=(c.getAttribute('data-search')||'').toLowerCase();
      c.style.display = (!q || hay.indexOf(q)>=0) ? '' : 'none';
    });});}

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
  if(nt&&nl){nt.addEventListener('click',function(){nl.classList.toggle('open');});
    nl.querySelectorAll('a').forEach(function(a){a.addEventListener('click',function(){nl.classList.remove('open');});});}

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
"""

import hashlib  # noqa: E402


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


def band_of(image: str) -> str:
    m = re.search(r"_(MIRB|MRGB|RED)\.", image or "")
    return m.group(1) if m else ""


def base_of(image: str) -> str:
    """Strip band + variant suffix to get the shared base (one physical frame)."""
    return (
        re.sub(r"_(MIRB|MRGB|RED)\.(browse|abrowse|thumb)_enh\.png$", "", image or "")
        or (image or "").split(".")[0]
    )


def group_features(rows: list[dict], si) -> list[dict]:
    """Group the same physical feature reported across band variants / nearby
    detections.  Returns one entry per distinct anomaly; each entry holds all
    band-variant members so the dossier can show every image of that anomaly.

    Mirrors showcase/build_showcase.py grouping: same base + within 6 px.
    This is what stops the explorer from looking like it is full of duplicates
    - one anomaly = one card, clicking it reveals every view of it.
    """
    # first split by base (same HiRISE frame regardless of band)
    bybase: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        bybase[base_of(r.get("image", ""))].append(r)

    def union_find(items, close):
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if close(items[i], items[j]):
                    union(i, j)
        groups: dict[int, list] = {}
        for i in range(len(items)):
            groups.setdefault(find(i), []).append(items[i])
        return list(groups.values())

    features: list[dict] = []
    for members in bybase.values():
        for grp in union_find(
            members,
            lambda a, b: abs(int(round(num(a.get("x")))) - int(round(num(b.get("x"))))) <= 8
            and abs(int(round(num(a.get("y")))) - int(round(num(b.get("y"))))) <= 8,
        ):
            grp.sort(key=lambda r: (-num(r.get("score")), r.get("image", "")))
            rep = grp[0]
            # collect all strips/crops for the dossier gallery
            variants = []
            bands_set = set()
            for m in grp:
                strip = si.get(m.get("image", ""))
                bands_set.add(band_of(m.get("image", "")))
                variants.append(
                    {
                        "image": m.get("image", ""),
                        "x": m.get("x"),
                        "y": m.get("y"),
                        "w": m.get("w"),
                        "h": m.get("h"),
                        "contrast": round(num(m.get("contrast")), 2),
                        "score": round(num(m.get("score")), 1),
                        "verdict": m.get("verdict", ""),
                        "polarity": m.get("polarity", ""),
                        "flags": m.get("flags", ""),
                        "band": band_of(m.get("image", "")),
                        "strip": strip.name if strip else "",
                        "crop": crop_box(strip, m.get("x"), m.get("y"), m.get("w"), m.get("h")),
                    }
                )
            # sort variants by score desc for gallery
            variants.sort(key=lambda v: -v["score"])
            bands = sorted(b for b in bands_set if b)
            # keep rep fields at top level for backwards-compat filtering/sorting
            features.append(
                {
                    "base": base_of(rep.get("image", "")),
                    "image": rep.get("image", ""),
                    "x": rep.get("x"),
                    "y": rep.get("y"),
                    "w": rep.get("w"),
                    "h": rep.get("h"),
                    "contrast": round(num(rep.get("contrast")), 2),
                    "score": round(num(rep.get("score")), 1),
                    "max_score": max(v["score"] for v in variants),
                    "max_contrast": max(v["contrast"] for v in variants),
                    "verdict": rep.get("verdict", ""),
                    "verdicts": sorted({m.get("verdict", "") for m in grp if m.get("verdict")}),
                    "confidence": rep.get("confidence", ""),
                    "evidence_class": rep.get("evidence_class", ""),
                    "polarity": rep.get("polarity", ""),
                    "flags": rep.get("flags", ""),
                    "area_px": rep.get("area_px", ""),
                    "agrees": rep.get("agrees", ""),
                    "disagrees": rep.get("disagrees", ""),
                    "persistence": rep.get("persistence", ""),
                    "compactness": rep.get("compactness", ""),
                    "edge_sharpness": rep.get("edge_sharpness", ""),
                    "fdr_q": rep.get("fdr_q", ""),
                    "pixel_scale_m": rep.get("pixel_scale_m", ""),
                    "size_m": rep.get("size_m", ""),
                    "solar_elevation_deg": rep.get("solar_elevation_deg", ""),
                    "solar_azimuth_deg": rep.get("solar_azimuth_deg", ""),
                    "inferred_height_m": rep.get("inferred_height_m", ""),
                    "bands": bands,
                    "members": variants,
                    "variants": variants,
                    "strip": variants[0]["strip"] if variants else "",
                    "crop": variants[0]["crop"] if variants else None,
                    "variant_count": len(variants),
                }
            )
    features.sort(key=lambda f: -f["max_score"])
    return features


def diverse_preview(top, n=60, max_per_image=2):
    """Spread preview cards across distinct source images for visual variety."""
    groups = defaultdict(list)
    for r in top:
        groups[r["image"]].append(r)
    for k in groups:
        groups[k].sort(key=lambda r: -num(r.get("score")))
    order = sorted(groups.values(), key=lambda g: -num(g[0].get("score")))
    out, counts, idxs = [], defaultdict(int), [0] * len(order)
    while len(out) < n:
        added = False
        for i, g in enumerate(order):
            if len(out) >= n:
                break
            img = g[0]["image"]
            if idxs[i] < len(g) and counts[img] < max_per_image:
                out.append(g[idxs[i]])
                idxs[i] += 1
                counts[img] += 1
                added = True
        if not added:
            break
    return out


def dedupe(rows: list[dict]) -> list[dict]:
    """Collapse the same physical feature that is reported once per band variant /
    enhancement of one acquisition. Key = (acquisition, x, y); keep the strongest
    (highest score) representative."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (acq_of(r.get("image", "")), int(round(num(r.get("x")))), int(round(num(r.get("y")))))
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


def build_leads_data(rows, si) -> str:
    payload = lead_json(rows, si)
    ver = _ver(payload)
    (SITE / "assets" / "leads.json").write_text(payload, encoding="utf-8")
    return ver


def lead_json(rows, si, max_per_image=8) -> str:
    """Build grouped leads JSON: one entry per distinct physical anomaly.

    The same crater/rock that is seen in RED/MIRB/MRGB (and as nearby
    detections within 8 px) is collapsed into a single ``feature`` with a
    ``members`` / ``variants`` array so the dossier can display *every* image
    of that anomaly.  This is the user-requested dedup: the grid no longer
    looks like it is full of copies - one anomaly = one card, click to see
    all angles/bands that captured it.
    """
    feats = group_features(rows, si)
    # Cap for visual variety: at most `max_per_image` distinct features per
    # *base* frame so the explorer does not show 200 cards from one swath.
    by_base: dict[str, list] = defaultdict(list)
    for f in feats:
        by_base[f["base"]].append(f)
    for lst in by_base.values():
        lst.sort(key=lambda f: -f["max_score"])
    out: list[dict] = []
    for base in sorted(by_base, key=lambda k: -by_base[k][0]["max_score"]):
        for f in by_base[base][:max_per_image]:
            out.append(f)
    # final global sort by score desc so grid is ranked
    out.sort(key=lambda f: -f["max_score"])
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/")


def build_index(rows, leads, top, si, summary_md, meth_html, art_html, leads_ver: str) -> None:
    counts = verdict_counts(rows)
    # Grouped display count: one card per distinct anomaly (band variants collapsed)
    # Matches lead_json() capping: at most 8 grouped features per base frame.
    # Use raw adjudicated.csv so all band variants are visible in the gallery,
    # while stats stay deduped (rows = rows_d).
    try:
        raw_for_group = read_csv(CONC / "adjudicated.csv")
    except Exception:
        raw_for_group = rows
    grouped_all = group_features(raw_for_group, si)
    by_base = defaultdict(list)
    for f in grouped_all:
        by_base[f["base"]].append(f)
    displayed = 0
    distinct_bases = len(by_base)
    for lst in by_base.values():
        lst.sort(key=lambda f: -f["max_score"])
        displayed += min(len(lst), 8)
    # keep legacy by_img_count for fallback but new hint uses grouped
    by_img_count = defaultdict(int)
    for r in rows:
        by_img_count[r.get("image", "")] += 1
    findings = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    fcards = ""
    for f in findings:
        txt = f.read_text(encoding="utf-8")
        v, p = finding_meta(txt)
        stamp = "<span class='f-stamp'>CONFIRMED LEAD</span>" if v.startswith("CONFIRMED") else ""
        sub = (
            f"<div class='fc-sub'>PRODUCT {html.escape(p)} &middot; VERDICT {html.escape(v)}</div>"
        )
        fcards += (
            f"<div class='finding-card' data-search='{html.escape(f.name)} {html.escape(v)} {html.escape(p)}'>"
            f"<div class='fc-head'><span class='fid'>{html.escape(f.name)}</span>{stamp}"
            f"<span class='ft'>+</span></div>{sub}<div class='fc-body prose'>{md_to_html(txt)}</div></div>"
        )
    chips = "".join(
        f"<span class='chip' data-v='{v}'>{v}</span>"
        for v in ["CONFIRMED-LEAD", "PROMISING", "TERRAIN", "EXPLAINED-ARTIFACT", "NOISE", "WEAK"]
    )
    legend_html = "".join(
        f"<span class='pill p-{v}' style='font-size:.68rem;padding:.1rem .5rem'>{v}</span>"
        for v in ["CONFIRMED-LEAD", "PROMISING", "TERRAIN", "EXPLAINED-ARTIFACT", "NOISE", "WEAK"]
    )
    ac = Counter(acq_of(r.get("image", "")) for r in rows)
    target_chips = "".join(
        f"<span class='tchip'>{html.escape(k)} <b>{v}</b></span>" for k, v in ac.most_common(14)
    )
    total = len(rows) or 1
    vbars = ""
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        pct = v / total * 100.0
        cls = "v-conf" if k.startswith("CONFIRMED") else "v-other"
        vbars += (
            f"<div class='vrow'><span class='vl'>{html.escape(k)}</span>"
            f"<span class='vbar'><span class='vfill {cls}' style='width:{pct:.1f}%'></span></span>"
            f"<span class='vc'>{v}</span></div>"
        )
    body = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='theme-color' content='#020617'>
<meta name='description' content='Public NASA HiRISE anomaly investigation facility: acquire, catalog, enhance, detect, analyze, and adjudicate anomalies with statistical rigor.'>
<meta property='og:title' content='NASA HiRISE Anomaly Investigation — Public Facility'>
<meta property='og:description' content='Rigorous, reproducible anomaly investigation of public NASA HiRISE Mars & lunar imagery.'>
<meta property='og:image' content='{SITE_URL}/assets/og-image.png'>
<meta property='og:type' content='website'>
<link rel='icon' href='assets/logo.svg' type='image/svg+xml'>
<title>NASA HiRISE Anomaly Investigation — Public Facility</title>
<link rel='stylesheet' href='assets/style.css?v={CSS_VER}'><script>document.documentElement.classList.add('reveal-on')</script></head><body>
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
  <button class='nav-toggle' aria-label='Menu'>&#9776;</button>
</div></nav>

<header class='hero'><div class='reticle'><div class='ring2'></div><div class='sweep'></div></div><div class='wrap'>
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
  <div class='steps'>
    <div class='step'><span class='n'>01</span><h4>Acquire</h4><p>EXTRAS-only HiRISE PDS imagery</p></div>
    <div class='step'><span class='n'>02</span><h4>Analyze</h4><p>local-contrast + cross-band confirmation</p></div>
    <div class='step'><span class='n'>03</span><h4>Adjudicate</h4><p>debunk-first, documented dossier</p></div>
    <div class='step'><span class='n'>04</span><h4>Publish</h4><p>verifiable GitHub Pages facility</p></div>
  </div>
  <div class='sec-head'><h2>Facility map</h2><span class='hint'>everything below is public &amp; verifiable</span></div>
  <div class='card-link'>
    <a class='tile' href='#explorer'><span class='badge'>Interactive</span><h3>Leads Explorer</h3><p>Search, filter and inspect every candidate with evidence strips.</p></a>
    <a class='tile' href='results/adjudicated.csv'><span class='badge'>Data</span><h3>Adjudicated Candidates</h3><p>Every candidate with its full verdict and metric columns (CSV).</p></a>
    <a class='tile' href='results/leads.csv'><span class='badge'>Data</span><h3>All Leads</h3><p>Complete metric set for every lead surfaced by the detector.</p></a>
    <a class='tile' href='#findings'><span class='badge'>Findings</span><h3>Finding Reports</h3><p>Per-lead dossiers (F-0001 &hellip;).</p></a>
    <a class='tile' href='#methodology'><span class='badge'>Docs</span><h3>Methodology</h3><p>The falsifiable, debunk-first investigation process.</p></a>
    <a class='tile' href='results/SUMMARY.md'><span class='badge'>Summary</span><h3>Adjudication Conclusion</h3><p>Funnel, verdict distribution, stress test, and bottom line.</p></a>
  </div>
  <div class='sec-head'><h2>Active targets</h2><span class='hint'>highest-volume acquisitions under investigation</span></div>
  <div class='chips'>{target_chips}</div>
  <div class='sec-head'><h2>Signal breakdown</h2><span class='hint'>{len(rows)} candidates adjudicated</span></div>
  <div class='vbars'>{vbars}</div>
</div></section>

<section id='explorer'><div class='wrap'>
  <div class='sec-head'><h2>Leads Explorer</h2><span class='hint'>{displayed} distinct anomalies (one card = all views) - {len(grouped_all)} distinct anomalies grouped from {len(raw_for_group)} raw band-variant rows - {distinct_bases} base frames - click any card to view every image</span></div>
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
<button id='reset' class='btn' style='padding:.4rem .8rem'>Reset</button>
<button id='export' class='btn' style='padding:.4rem .8rem'>Export CSV</button>
</div>
  <div class='chips'>{chips}</div>
  <div class='legend'>{legend_html}</div>
  <div id='leadNote' class='count-note'></div>
  <div id='leadsGrid' class='grid'></div>
  <div style='text-align:center;margin-top:1rem'><button id='loadMore' class='btn' style='display:none'>Load more</button></div>
</div></section>

<section id='findings'><div class='wrap'>
  <div class='sec-head'><h2>Finding Reports</h2><span class='hint'>{len(findings)} dossiers</span></div>
  <input id='fSearch' type='search' placeholder='Filter findings by id / verdict / product&hellip;' style='width:100%;max-width:420px;margin:.2rem 0 1rem;padding:.5rem .7rem;background:#0a0e16;border:1px solid var(--border2);border-radius:8px;color:var(--text);font-family:var(--mono)'>
  <div class='findings'>{fcards}</div>
</div></section>

<section id='methodology'><div class='wrap'>
  <div class='sec-head'><h2>Methodology</h2><span class='hint'>from docs/</span></div>
  <div class='panel-box'><div class='pb-head'>Investigation Methodology</div><div class='prose'>{meth_html}</div></div>
  <div class='sec-head' style='margin-top:2.5rem'><h2>Known Artifacts &mdash; the Checklist</h2></div>
  <div class='panel-box'><div class='pb-head'>Known Artifacts — the Checklist</div><div class='prose'>{art_html}</div></div>
</div></section>

<footer><div class='fwrap'>
  <span>Public facility &middot; Data: NASA/JPL HiRISE PDS (public domain) &middot; MIT License</span>
  <span class='src'>SOURCE &nbsp;{BASE}</span>
  <span class='view'>VIEW &nbsp; {SITE_URL}/report/</span>
  <span class='sync'>LAST SYNC &nbsp; {BUILD_TS} &middot; {BUILD_REV} &middot; <span id='ago'></span></span>
  <a href='../'>Home</a>
</div></footer>

<div class='lb' id='lb'><span class='x'>&times;</span><div class='dossier' id='lbDossier'></div></div>
<button id='toTop' class='to-top' aria-label='Back to top'>&#8593;</button>
{timer_html()}
<script>window.STRIP_BASE='results/strips/';window.LEADS_VER='{leads_ver}';window.UPLINK_END={TIMER_END};window.BUILD_EPOCH={BUILD_EPOCH};</script>
<script src='assets/app.js?v={JS_VER}'></script>
</body></html>"""
    (SITE / "index.html").write_text(body, encoding="utf-8")


def build_report(rows, leads, si, summary_md, leads_ver: str) -> None:
    counts = verdict_counts(rows)
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))
    top = dedupe(top_leads(rows))
    # verdict distribution bars
    total = len(rows) or 1
    vbars = ""
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        pct = v / total * 100.0
        cls = "v-conf" if k.startswith("CONFIRMED") else "v-other"
        vbars += (
            f"<div class='vrow'><span class='vl'>{html.escape(k)}</span>"
            f"<span class='vbar'><span class='vfill {cls}' style='width:{pct:.1f}%'></span></span>"
            f"<span class='vc'>{v}</span></div>"
        )
    # top-acquisition leaderboard
    total = len(rows) or 1
    acq = Counter(acq_of(r.get("image", "")) for r in rows)
    acq_bars = "".join(
        f"<div class='vrow'><span class='vl'>{html.escape(k)}</span>"
        f"<span class='vbar'><span class='vfill v-other' style='width:{v / total * 100:.1f}%'></span></span>"
        f"<span class='vc'>{v}</span></div>"
        for k, v in acq.most_common(12)
    )
    # top-lead cards (server rendered) — zoomed target-lock crop per feature, spread across source images
    cards = []
    for i, r in enumerate(diverse_preview([r for r in top if si.get(r["image"])], 60)):
        strip = si.get(r["image"])
        if strip:
            crop = crop_box(strip, r.get("x"), r.get("y"), r.get("w"), r.get("h"))
            cs = crop_style(f"../results/strips/{strip.name}", crop)
            img = (
                f"<div class='crop' style='{cs}'></div>" if cs else "<div class='ph'>no strip</div>"
            )
        else:
            img = "<div class='ph'>no strip</div>"
        flags = r["flags"].split(",") if r.get("flags") else []
        fh = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
        cards.append(
            f"<div class='lead' onclick=\"openDossier('{html.escape(r['image'])}')\">"
            f"<div class='thumb'>{img}{('<div class=stamp>CONFIRMED LEAD</div>' if r['verdict'].startswith('CONFIRMED') else '')}"
            f"<div class='corner-ref'>x{r.get('x')} y{r.get('y')}</div></div><div class='body'>"
            f"<div class='name'>{i + 1}. {html.escape(r['image'])}</div>"
            f"<div class='row'><span class='pill p-{r['verdict']}'>{r['verdict']}</span><span>{round(num(r['score']))}</span></div>"
            f"<div class='row'><span>contrast {round(num(r['contrast']), 2)}</span><span>{r['w']}x{r['h']}</span></div>"
            f"<div class='row'><span>flags</span></div><ul style='margin:.1rem 0 0 1rem;color:var(--muted);font-size:.75rem'>{fh}</ul>"
            f"</div></div>"
        )
    # full sortable table
    trs = []
    for i, r in enumerate(top):
        trs.append(
            f"<tr onclick=\"openDossier('{html.escape(r['image'])}')\" style='cursor:pointer'>"
            f"<td>{i + 1}</td><td>{html.escape(r['image'])}</td><td>{round(num(r['score']))}</td>"
            f"<td>{r['x']},{r['y']}</td><td>{html.escape(r.get('evidence_class', ''))}</td>"
            f"<td class='p-{r['verdict']}' style='color:inherit'>{html.escape(r['verdict'])}</td>"
            f"<td>{round(num(r['contrast']), 2)}</td><td>{r.get('agrees', '')}/{r.get('disagrees', '')}</td>"
            f"<td>{r.get('area_px', '')}</td></tr>"
        )
    findings = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    fhtml = ""
    for f in findings:
        txt = f.read_text(encoding="utf-8")
        v, p = finding_meta(txt)
        stamp = "<span class='f-stamp'>CONFIRMED LEAD</span>" if v.startswith("CONFIRMED") else ""
        sub = (
            f"<div class='fc-sub'>PRODUCT {html.escape(p)} &middot; VERDICT {html.escape(v)}</div>"
        )
        fhtml += (
            f"<div class='finding-card'><div class='fc-head'><span class='fid'>{html.escape(f.name)}</span>{stamp}"
            f"<span class='ft'>+</span></div>{sub}<div class='fc-body prose'>{md_to_html(txt)}</div></div>"
        )
    body = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='theme-color' content='#020617'>
<meta property='og:title' content='NASA HiRISE Anomaly Analysis Report'>
<meta property='og:image' content='{SITE_URL}/assets/og-image.png'>
<link rel='icon' href='../assets/logo.svg' type='image/svg+xml'>
<title>NASA HiRISE — Anomaly Analysis Report</title>
<link rel='stylesheet' href='../assets/style.css?v={CSS_VER}'><script>document.documentElement.classList.add('reveal-on')</script></head><body>
<div class='toprule'></div>
<div class='ticker'><span>Classified // Anomaly Dossier &mdash; Adjudication</span><span class='eyes'>Eyes Only</span></div>
<div class='brackets'><span class='tl'></span><span class='tr'></span><span class='bl'></span><span class='br'></span></div>
<div class='bg-glow'></div><div class='grid-ov'></div><div class='scan'></div>
<nav><div class='nav-in'>
  <a class='brand' href='../'><img src='../assets/logo.svg' alt='logo'><span>NASA HiRISE<small>Anomaly Dossier</small></span></a>
  <div class='nav-links'><a href='../#overview'>Home</a><a href='../#explorer'>Explorer</a><a href='../#findings'>Findings</a><a href='{BASE}'>Source</a></div>
  <button class='nav-toggle' aria-label='Menu'>&#9776;</button>
</div></nav>
<header class='hero'><div class='reticle'><div class='ring2'></div><div class='sweep'></div></div><div class='wrap'>
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
  <div class='sec-head'><h2>Signal breakdown</h2><span class='hint'>{len(rows)} candidates adjudicated</span></div>
  <div class='vbars'>{vbars}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Top leads preview</h2><span class='hint'>{min(60, len(top))} of {len(top)} with strips &mdash; click to enlarge</span></div>
  <div class='grid'>{"".join(cards)}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>All top leads ({len(top)})</h2><span class='hint'>click a column header to sort &middot; click a row to open its dossier</span></div>
  <table class='sortable'><thead><tr>
    <th data-key='#'>#</th><th data-key='image'>image</th><th data-key='score'>score</th>
    <th data-key='xy'>xy</th><th data-key='class'>class</th><th data-key='verdict'>verdict</th>
    <th data-key='contrast'>contrast</th><th data-key='xb'>X-band</th><th data-key='area'>area</th></tr></thead>
    <tbody>{"".join(trs)}</tbody></table>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Top acquisitions</h2><span class='hint'>most-investigated frames</span></div>
  <div class='vbars'>{acq_bars}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Adjudication summary</h2></div>
  <div class='prose'>{md_to_html(summary_md) if summary_md else ""}</div>
</div></section>

<section><div class='wrap'>
  <div class='sec-head'><h2>Finding reports ({len(findings)})</h2></div>
  <div class='findings'>{fhtml}</div>
</div></section>

<footer>Public facility &middot; <a href='../'>Home</a> &middot; <a href='{BASE}'>Source</a> &middot; MIT License &middot; <span class='sync'>LAST SYNC {BUILD_TS} &middot; {BUILD_REV} &middot; <span id='ago'></span></span></footer>
<div class='lb' id='lb'><span class='x'>&times;</span><div class='dossier' id='lbDossier'></div></div>
<button id='toTop' class='to-top' aria-label='Back to top'>&#8593;</button>
{timer_html()}
<script>window.STRIP_BASE='../results/strips/';window.LEADS_VER='{leads_ver}';window.UPLINK_END={TIMER_END};window.BUILD_EPOCH={BUILD_EPOCH};</script>
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
    summary_md = (
        (CONC / "SUMMARY.md").read_text(encoding="utf-8") if (CONC / "SUMMARY.md").exists() else ""
    )
    meth = (
        md_to_html((DOCS / "METHODOLOGY.md").read_text(encoding="utf-8"))
        if (DOCS / "METHODOLOGY.md").exists()
        else ""
    )
    art = (
        md_to_html((DOCS / "ARTIFACTS.md").read_text(encoding="utf-8"))
        if (DOCS / "ARTIFACTS.md").exists()
        else ""
    )

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    (SITE / "report").mkdir(parents=True)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    build_shared()
    rows_d = dedupe(rows)
    leads_d = dedupe(leads)
    top = dedupe(top_leads(rows))
    leads_ver = build_leads_data(rows, si)
    build_index(rows_d, leads_d, top, si, summary_md, meth, art, leads_ver)
    build_report(rows_d, leads_d, si, summary_md, leads_ver)
    build_results()

    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(
        f"Built site/ ({size // 1024} KB): landing+explorer + report + {len(rows_d)} candidates + "
        f"{len(top)} top leads + {len(list(LEADS_DIR.glob('F-*.md')))} findings + "
        f"{len(list((SITE / 'results' / 'strips').glob('*.jpg')))} strips"
    )


def selftest() -> int:
    """Lightweight offline checks for the dossier helpers (no HiRISE data needed)."""
    import tempfile
    from PIL import Image

    fails = 0

    def ok(cond, msg):
        nonlocal fails
        if not cond:
            fails += 1
            print("  FAIL:", msg)
        else:
            print("  ok:", msg)

    # crop_box: build a known synthetic strip and frame a feature
    im = Image.new("RGB", (200, 100), (10, 10, 10))
    for xx in range(90, 110):
        for yy in range(40, 60):
            im.putpixel((xx, yy), (240, 240, 240))
    tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    im.save(tf.name)
    cb = crop_box(Path(tf.name), 100, 50, 20, 20)
    ok(cb is not None, "crop_box returns a frame")
    ok(cb and all(0.0 <= v <= 1.0 for v in cb), "crop fractions within [0,1]")
    ok(cb and cb[2] > 0 and cb[3] > 0, "crop has positive size")
    ok(cb and abs((cb[0] + cb[2] / 2) - 0.5) < 0.05, "crop centers near feature x")
    # missing file -> None
    ok(crop_box(Path("nope.jpg"), 1, 1, 2, 2) is None, "crop_box handles missing file")

    # dedupe: same (acq,x,y) across bands collapses to one, highest score kept
    rows = [
        {
            "image": "ESP_013236_1410_MIRB.abrowse_enh.png",
            "verdict": "CONFIRMED-LEAD",
            "score": "80",
            "x": "5",
            "y": "5",
            "w": "10",
            "h": "10",
            "contrast": "2",
        },
        {
            "image": "ESP_013236_1410_RED.browse_enh.png",
            "verdict": "CONFIRMED-LEAD",
            "score": "100",
            "x": "5",
            "y": "5",
            "w": "10",
            "h": "10",
            "contrast": "2",
        },
        {
            "image": "ESP_013948_1410_RED.browse_enh.png",
            "verdict": "CONFIRMED-LEAD",
            "score": "90",
            "x": "9",
            "y": "9",
            "w": "10",
            "h": "10",
            "contrast": "2",
        },
    ]
    dd = dedupe(rows)
    ok(len(dd) == 2, "dedupe collapses same (acq,x,y) to one row")
    kept = [r for r in dd if r["image"].startswith("ESP_013236_1410")][0]
    ok(kept["score"] == "100", "dedupe keeps highest-score band")

    # diverse_preview: spreads across images, respects cap
    big = []
    for i in range(20):
        big.append(
            {
                "image": f"IMG_{i % 3}.png",
                "verdict": "CONFIRMED-LEAD",
                "score": str(i),
                "x": "1",
                "y": "1",
                "w": "4",
                "h": "4",
                "contrast": "2",
            }
        )
    prev = diverse_preview(big, 6, 2)
    from collections import Counter

    cnt = Counter(r["image"] for r in prev)
    ok(len(prev) == 6, "diverse_preview returns requested count")
    ok(all(v <= 2 for v in cnt.values()), "diverse_preview respects per-image cap")

    # verdict_counts / top_leads basic sanity
    tc = verdict_counts(rows)
    ok(tc.get("CONFIRMED-LEAD", 0) == 3, "verdict_counts tallies correctly")

    print(f"selftest: {'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return fails


if __name__ == "__main__":
    import argparse
    import sys

    _ap = argparse.ArgumentParser(description="Build the public HiRISE anomaly dossier site.")
    _ap.add_argument("--selftest", action="store_true", help="run offline helper checks and exit")
    _ap.add_argument("--version", action="store_true", help="print version and exit")
    _a = _ap.parse_args()
    if _a.version:
        print("build_site 1.4.0")
        sys.exit(0)
    if _a.selftest:
        raise SystemExit(selftest())
    main()
