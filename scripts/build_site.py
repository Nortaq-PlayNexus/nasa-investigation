"""Assemble the public GitHub Pages site for the NASA HiRISE investigation.

Reads the local adjudication outputs (under data/anomalies/, which stay
gitignored) and emits a fully self-contained, committable ``site/`` tree:

    site/
      index.html              landing / facility display
      report/index.html      self-contained Anomaly Analysis Report
      results/
        adjudicated.csv       every candidate verdict
        leads.csv            full metric columns for every lead
        SUMMARY.md           adjudication conclusion
        findings/F-*.md       per-lead finding reports
        strips/T*.jpg        evidence strips (public)
      .nojekyll

Run:  python scripts/build_site.py
"""

from __future__ import annotations

import base64
import csv
import html
import mimetypes
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
STRIPS = CONC / "strips"
LEADS_DIR = CONC / "leads"
SITE = ROOT / "site"

REPO = "Nortaq-PlayNexus/nasa-investigation"
BASE = f"https://github.com/{REPO}"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def strip_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            name = f.name
            if name.startswith("T") and "_" in name and name.endswith(".jpg"):
                img = name.split("_", 1)[1][:-4]
                idx.setdefault(img, f)
    return idx


def b64(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


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


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def build_report(out: Path, rows, leads, si, summary_md) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict", "UNKNOWN")
        counts[v] = counts.get(v, 0) + 1
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))
    top = top_leads(rows)

    cards = []
    for i, r in enumerate(top[:30]):
        flags = r["flags"].split(",") if r.get("flags") else []
        flag_html = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
        img_tag = ""
        strip = si.get(r["image"])
        if strip is not None:
            img_tag = f"<p><img loading='lazy' src='{b64(strip)}' alt='strip for {html.escape(r['image'])}'></p>"
        cards.append(
            f"<div class='card'><h3>#{i + 1} {html.escape(r['image'])} "
            f"<span class='cls'>{html.escape(r['verdict'])}</span></h3>"
            f"<p><b>conf</b> {html.escape(r.get('confidence', ''))} &middot; "
            f"<b>score</b> {num(r['score']):.0f} &middot; <b>contrast</b> {num(r['contrast']):.2f}</p>"
            f"<table><tr><td>x,y</td><td>{r['x']}, {r['y']}</td></tr>"
            f"<tr><td>size</td><td>{r['w']} x {r['h']} px</td></tr>"
            f"<tr><td>evidence class</td><td>{r.get('evidence_class', '')}</td></tr>"
            f"<tr><td>cross-band</td><td>{r.get('agrees', '')} agree / {r.get('disagrees', '')} disagree</td></tr>"
            f"<tr><td>persistence</td><td>{r.get('persistence', '')}</td></tr>"
            f"<tr><td>compactness</td><td>{r.get('compactness', '')}</td></tr>"
            f"<tr><td>area</td><td>{r.get('area_px', '')} px</td></tr>"
            f"<tr><td>flags</td><td><ul>{flag_html}</ul></td></tr></table>"
            f"{img_tag}<p class='notes'>{html.escape(r.get('recommendation', ''))}</p></div>"
        )

    table_rows = []
    for i, r in enumerate(top):
        table_rows.append(
            f"<tr><td>{i + 1}</td><td>{html.escape(r['image'])}</td><td>{num(r['score']):.0f}</td>"
            f"<td>{r['x']},{r['y']}</td><td>{html.escape(r.get('evidence_class', ''))}</td>"
            f"<td>{html.escape(r.get('verdict', ''))}</td><td>{num(r['contrast']):.2f}</td>"
            f"<td>{r.get('agrees', '')}/{r.get('disagrees', '')}</td></tr>"
        )

    finding_files = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    finding_html = ""
    for f in finding_files:
        body = html.escape(f.read_text(encoding="utf-8")).replace("\n", "<br>")
        finding_html += f"<details class='finding'><summary>{html.escape(f.name)}</summary><div class='finding-body'>{body}</div></details>"

    body = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>NASA HiRISE — Anomaly Analysis Report</title><style>"
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0d1117;color:#d8dee6;margin:0;padding:0 1.5rem 3rem}"
        "h1,h2{border-bottom:1px solid #2a3138;padding-bottom:.3rem;margin-top:2rem}"
        "header{background:#151b23;border-bottom:1px solid #2a3138;padding:1.5rem;margin:0 -1.5rem 1rem}"
        "header p{margin:.3rem 0;color:#8b949e}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:1rem}"
        ".card{border:1px solid #2a3138;padding:.8rem;background:#151b23;border-radius:8px}"
        ".card img{max-width:100%;border:1px solid #333;border-radius:4px;margin-top:.4rem}"
        ".cls{color:#f0b429}table{border-collapse:collapse;margin:.6rem 0;width:100%}"
        "th,td{border:1px solid #2a3138;padding:.25rem .5rem;font-size:.8rem;text-align:left}th{background:#1a2030}"
        "ul{margin:.2rem 0 0 1rem;padding:0}a{color:#58a6ff}"
        ".stats{display:flex;flex-wrap:wrap;gap:.5rem;margin:.8rem 0}"
        ".stat{background:#1a2030;border:1px solid #2a3138;border-radius:6px;padding:.5rem .8rem}"
        ".stat b{font-size:1.3rem;display:block;color:#fff}.stat span{font-size:.75rem;color:#8b949e}"
        ".notes{color:#8b949e;font-size:.85rem}"
        ".finding{border:1px solid #2a3138;border-radius:6px;padding:.4rem .8rem;margin:.4rem 0;background:#151b23}"
        ".finding summary{cursor:pointer;font-weight:bold}.finding-body{margin-top:.6rem;font-size:.85rem;line-height:1.4}"
        ".summary{white-space:pre-wrap;background:#151b23;border:1px solid #2a3138;border-radius:6px;padding:1rem;font-size:.85rem;overflow:auto}"
        "</style></head><body>"
        "<header><h1>NASA HiRISE — Anomaly Analysis Report</h1>"
        f"<p>Generated from the public pipeline adjudication output. "
        f"{len(rows)} candidates adjudicated &middot; {len(leads)} leads &middot; {len(finding_files)} finding reports.</p>"
        f"<p>Verdict distribution: {dist}</p>"
        f"<p><a href='../index.html'>Facility home</a> &middot; "
        f"<a href='{BASE}/blob/main/docs/METHODOLOGY.md'>Methodology</a> &middot; "
        f"<a href='{BASE}/blob/main/docs/ARTIFACTS.md'>Artifact catalog</a> &middot; "
        f"<a href='#adjudication-summary'>Adjudication summary</a></p></header>"
    )

    body += "<div class='stats'>"
    for label, val in [
        ("Candidates", len(rows)),
        ("Leads", len(leads)),
        ("Top leads", len(top)),
        ("Findings", len(finding_files)),
        ("Strips", len(list(STRIPS.glob('T*.jpg'))) if STRIPS.is_dir() else 0),
    ]:
        body += f"<div class='stat'><b>{val}</b><span>{label}</span></div>"
    body += "</div>"

    body += (
        f"<h2>Top leads <span style='font-weight:normal;font-size:.9rem;color:#8b949e'>({min(30, len(top))} shown with strips, {len(top)} total)</span></h2>"
        "<p>Cross-band confirmed, contrast &ge; 1.50, off-border, 200&ndash;50000 px.</p>"
        "<div class='grid'>" + "".join(cards) + "</div>"
    )
    body += (
        f"<h2>All top leads ({len(top)})</h2>"
        "<table><tr><th>#</th><th>image</th><th>score</th><th>xy</th><th>class</th>"
        "<th>verdict</th><th>contrast</th><th>X-band</th></tr>"
        + "".join(table_rows) + "</table>"
    )
    if summary_md:
        body += "<h2 id='adjudication-summary'>Adjudication summary</h2><div class='summary'>" + html.escape(summary_md) + "</div>"
    if finding_html:
        body += f"<h2>Finding reports ({len(finding_files)})</h2>" + finding_html
    body += "</body></html>"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# landing
# --------------------------------------------------------------------------
def build_landing(out: Path, rows, leads, si, summary_md) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("verdict" if False else "verdict", "UNKNOWN")] = counts.get(r.get("verdict", "UNKNOWN"), 0) + 1
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))
    top = top_leads(rows)

    # a few inline top-lead strips for the landing hero grid
    preview = []
    for i, r in enumerate(top[:12]):
        strip = si.get(r["image"])
        img = f"<img loading='lazy' src='{b64(strip)}' alt='{html.escape(r['image'])}'>" if strip else ""
        preview.append(
            f"<a class='pcard' href='report/'><div class='pimg'>{img}</div>"
            f"<div class='pcap'>#{i + 1} {html.escape(r['image'])}<br>"
            f"<span>{html.escape(r.get('verdict',''))} &middot; score {num(r['score']):.0f} &middot; contrast {num(r['contrast']):.2f}</span></div></a>"
        )

    # pull the bottom line from SUMMARY.md
    bottom = ""
    if summary_md:
        for line in summary_md.splitlines():
            if line.strip().lower().startswith("## bottom line"):
                idx = summary_md.splitlines().index(line)
                chunk = "\n".join(summary_md.splitlines()[idx + 1: idx + 12])
                bottom = chunk.strip()
                break

    body = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='description' content='Public NASA HiRISE anomaly investigation facility: acquire, catalog, enhance, detect, analyze, adjudicate.'>
<title>NASA HiRISE Anomaly Investigation — Public Facility</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0a0c10;color:#d8dee6;margin:0;line-height:1.5}}
.hero{{background:radial-gradient(1200px 400px at 70% -10%,#16324a 0%,#0a0c10 60%);border-bottom:1px solid #1d2530;padding:3.5rem 1.5rem 2.5rem}}
.wrap{{max-width:1100px;margin:0 auto}}
.hero h1{{margin:0;font-size:2.4rem;letter-spacing:-.5px}}
.hero .tag{{color:#58a6ff;font-weight:600;letter-spacing:.18em;text-transform:uppercase;font-size:.8rem}}
.hero p{{max-width:760px;color:#9aa4b2;margin:.8rem 0 0}}
.stats{{display:flex;flex-wrap:wrap;gap:.7rem;margin:1.6rem 0}}
.stat{{background:#11161f;border:1px solid #1d2530;border-radius:10px;padding:.7rem 1rem;min-width:120px}}
.stat b{{display:block;font-size:1.6rem;color:#fff}}
.stat span{{font-size:.72rem;color:#8b949e;text-transform:uppercase;letter-spacing:.08em}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem;margin:1.5rem 0}}
.card{{display:block;background:#11161f;border:1px solid #1d2530;border-radius:12px;padding:1.1rem;text-decoration:none;color:inherit;transition:.15s}}
.card:hover{{border-color:#2f81f7;transform:translateY(-2px)}}
.card h3{{margin:.1rem 0 .4rem;font-size:1.05rem;color:#e6edf3}}
.card p{{margin:0;color:#8b949e;font-size:.85rem}}
.badge{{display:inline-block;font-size:.7rem;color:#7ee787;border:1px solid #2ea04355;background:#1a2e1f;border-radius:20px;padding:.1rem .6rem;margin-bottom:.5rem}}
section{{max-width:1100px;margin:0 auto;padding:1.5rem}}
h2{{border-bottom:1px solid #1d2530;padding-bottom:.4rem}}
.pgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.8rem;margin-top:1rem}}
.pcard{{display:block;background:#11161f;border:1px solid #1d2530;border-radius:10px;overflow:hidden;text-decoration:none;color:inherit}}
.pimg{{aspect-ratio:16/10;background:#05070a;display:flex;align-items:center;justify-content:center;overflow:hidden}}
.pimg img{{width:100%;height:100%;object-fit:cover}}
.pcap{{padding:.5rem .7rem;font-size:.8rem}}
.pcap span{{color:#8b949e}}
.callout{{background:#1a1626;border:1px solid #6e40c0;border-left:4px solid #8957e5;border-radius:10px;padding:1rem 1.2rem;margin:1.2rem 0;color:#d8dee6}}
.callout b{{color:#c8a8ff}}
footer{{border-top:1px solid #1d2530;color:#6e7681;font-size:.8rem;text-align:center;padding:1.5rem}}
a{{color:#58a6ff}}
</style></head><body>

<header class='hero'><div class='wrap'>
  <div class='tag'>Public Research Facility</div>
  <h1>NASA HiRISE Anomaly Investigation</h1>
  <p>A rigorous, reproducible pipeline for analyzing public NASA HiRISE imagery of Mars &amp; the Moon &mdash; acquire, catalog, enhance, detect, analyze, and adjudicate anomalies with statistical rigor. Every step is documented, controlled, and built to <b>debunk</b> before anything is recorded as a finding.</p>
  <div class='stats'>
    <div class='stat'><b>{len(rows)}</b><span>Candidates</span></div>
    <div class='stat'><b>{len(leads)}</b><span>Leads</span></div>
    <div class='stat'><b>{len(top)}</b><span>Top leads</span></div>
    <div class='stat'><b>{len(list(LEADS_DIR.glob('F-*.md')))}</b><span>Findings</span></div>
  </div>
</div></header>

<section>
  <h2>Explore the facility</h2>
  <div class='grid'>
    <a class='card' href='report/'><span class='badge'>Report</span><h3>Anomaly Analysis Report</h3><p>Full adjudication: verdict distribution, 296 top leads with evidence strips, all finding reports.</p></a>
    <a class='card' href='results/adjudicated.csv'><span class='badge'>Data</span><h3>Adjudicated Candidates (CSV)</h3><p>Every candidate with its full verdict and metric columns.</p></a>
    <a class='card' href='results/leads.csv'><span class='badge'>Data</span><h3>All Leads (CSV)</h3><p>Complete metric set for every lead surfaced by the detector.</p></a>
    <a class='card' href='results/findings/'><span class='badge'>Findings</span><h3>Finding Reports</h3><p>Per-lead dossiers (F-0001 &hellip;).</p></a>
    <a class='card' href='{BASE}/blob/main/docs/METHODOLOGY.md'><span class='badge'>Docs</span><h3>Methodology</h3><p>The falsifiable, debunk-first investigation process.</p></a>
    <a class='card' href='{BASE}/blob/main/docs/ARTIFACTS.md'><span class='badge'>Docs</span><h3>Artifact Catalog</h3><p>Known sensor, compression, and optics artifacts we screen against.</p></a>
    <a class='card' href='{BASE}'><span class='badge'>Source</span><h3>Source Repository</h3><p>Pipeline code, tests, CI, and documentation.</p></a>
    <a class='card' href='results/SUMMARY.md'><span class='badge'>Summary</span><h3>Adjudication Conclusion</h3><p>Funnel, verdict distribution, stress test, and bottom line.</p></a>
  </div>
</section>

<section>
  <h2>Top leads preview</h2>
  <p style='color:#8b949e'>Cross-band confirmed, contrast &ge; 1.50, off-border, 200&ndash;50000 px. Open the <a href='report/'>full report</a> for all {len(top)}.</p>
  <div class='pgrid'>{''.join(preview)}</div>
</section>

<section>
  <h2>Bottom line</h2>
  <div class='callout'><b>{html.escape(bottom) if bottom else 'After this pass, no candidate meets the bar for a finding. Cross-band agreement confirms a feature across band variants of one acquisition; confirming any top lead requires the EDR original plus an independent pass at different lighting.'}</b></div>
  <p style='color:#8b949e'>Verdict distribution: {dist}</p>
</section>

<footer>
  Public facility &middot; Data: NASA/JPL HiRISE PDS (public domain) &middot;
  <a href='{BASE}'>Source</a> &middot; MIT License
</footer>
</body></html>"""
    out.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
def main() -> None:
    si = strip_index()
    rows = read_csv(CONC / "adjudicated.csv")
    leads = read_csv(CONC / "leads.csv")
    summary_md = (CONC / "SUMMARY.md").read_text(encoding="utf-8") if (CONC / "SUMMARY.md").exists() else ""

    # clean previous build
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)

    # report
    build_report(SITE / "report" / "index.html", rows, leads, si, summary_md)

    # results data
    res = SITE / "results"
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

    # landing
    build_landing(SITE / "index.html", rows, leads, si, summary_md)

    # disable Jekyll
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"Built site/ ({size // 1024} KB): landing + report + {len(rows)} candidates + "
          f"{len(list(LEADS_DIR.glob('F-*.md')))} findings + {len(list(sdir.glob('*.jpg')))} strips")


if __name__ == "__main__":
    main()
