"""Regenerate conclusions/report.html from current CSVs + strips."""
from __future__ import annotations

import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
STRIPS = CONC / "strips"


def strip_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            name = f.name
            if name.startswith("T") and "_" in name:
                img = name.split("_", 1)[1]
                idx.setdefault(img[:-4], name)
    return idx


def main():
    si = strip_index()

    with (CONC / "adjudicated.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with (CONC / "leads.csv").open(encoding="utf-8-sig", newline="") as fh:
        leads = list(csv.DictReader(fh))

    # top leads: CONFIRMED-LEAD, contrast >= 1.50, off-border, 200-50000 px
    top = []
    for r in rows:
        if r["verdict"] != "CONFIRMED-LEAD":
            continue
        if float(r.get("contrast", 0) or 0) < 1.50:
            continue
        if r.get("near_edge") in ("True", "1"):
            continue
        area = int(r.get("area_px", 0) or 0)
        if area < 200 or area > 50000:
            continue
        # attach strip (index keys are the full image filename incl. extension)
        img = r["image"]
        r["_strip"] = si.get(img, "")
        top.append(r)
    top.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)

    # verdict counts
    counts: dict[str, int] = {}
    for r in rows:
        v = r["verdict"]
        counts[v] = counts.get(v, 0) + 1
    dist = " &middot; ".join(f"{k}: {v}" for k, v in sorted(counts.items()))

    # build cards for top 60
    cards = []
    for r in top[:60]:
        flags = r["flags"].split(",") if r["flags"] else []
        flag_html = "".join(f"<li>{html.escape(f)}</li>" for f in flags) or "<li>none</li>"
        img_tag = ""
        if r.get("_strip"):
            img_tag = f"<p><img src='strips/{r['_strip']}' alt='strip'></p>"
        cards.append(
            f"<div class='card'><h3>{html.escape(r['image'])} "
            f"<span class='cls'>{html.escape(r['verdict'])}</span></h3>"
            f"<p><b>verdict</b> {html.escape(r['verdict'])} &middot; "
            f"<b>confidence</b> {html.escape(r.get('confidence',''))} &middot; "
            f"<b>score</b> {float(r['score']):.0f}</p>"
            f"<table><tr><td>x,y</td><td>{r['x']}, {r['y']}</td></tr>"
            f"<tr><td>size</td><td>{r['w']} x {r['h']} px</td></tr>"
            f"<tr><td>evidence class</td><td>{r['evidence_class']}</td></tr>"
            f"<tr><td>cross-band</td><td>{r['agrees']} agree / {r['disagrees']} disagree</td></tr>"
            f"<tr><td>persistence</td><td>{r['persistence']}</td></tr>"
            f"<tr><td>compactness</td><td>{r['compactness']}</td></tr>"
            f"<tr><td>contrast</td><td>{r['contrast']}</td></tr>"
            f"<tr><td>area</td><td>{r.get('area_px','')} px</td></tr>"
            f"<tr><td>polarity</td><td>{r.get('polarity','')}</td></tr>"
            f"<tr><td>flags</td><td><ul>{flag_html}</ul></td></tr></table>"
            f"{img_tag}"
            f"<p>{html.escape(r.get('recommendation',''))}</p></div>"
        )

    # finding summary
    leads_dir = CONC / "leads"
    finding_count = len(list(leads_dir.glob("F-*.md"))) if leads_dir.is_dir() else 0

    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Anomaly adjudication</title><style>"
        "body{font-family:sans-serif;background:#0d1117;color:#d8dee6;margin:1.5rem}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:1rem}"
        ".card{border:1px solid #2a3138;padding:.8rem;background:#151b23;border-radius:8px}"
        ".card img{max-width:100%;border:1px solid #333;border-radius:4px}"
        ".cls{color:#f0b429}"
        "table{border-collapse:collapse;margin:.4rem 0}"
        "th,td{border:1px solid #2a3138;padding:.2rem .5rem;font-size:.8rem}"
        "ul{margin:.2rem 0 0 1rem}"
        "a{color:#58a6ff}"
        "h2{margin-top:2rem;border-bottom:1px solid #2a3138;padding-bottom:.3rem}"
        ".stats{display:flex;flex-wrap:wrap;gap:.5rem;margin:.8rem 0}"
        ".stat{background:#1a2030;border:1px solid #2a3138;border-radius:6px;padding:.5rem .8rem}"
        ".stat b{font-size:1.3rem;display:block;color:#fff}"
        ".stat span{font-size:.75rem;color:#8b949e}"
        ".findings{margin:.5rem 0 1rem}"
        ".findings a{margin-right:1rem}"
        "</style></head><body>"
        "<h1>Anomaly adjudication</h1>"
        f"<p>{len(rows)} candidates adjudicated &middot; {len(leads)} leads &middot; {dist}</p>"
        "<p><a href='adjudicated.csv'>adjudicated.csv</a> &middot; "
        "<a href='leads.csv'>leads.csv</a> &middot; "
        "<a href='SUMMARY.md'>SUMMARY.md</a></p>"
    )

    # summary stats row
    body += "<div class='stats'>"
    for label, val in [
        ("Candidates", len(rows)),
        ("Leads", len(leads)),
        ("Findings", finding_count),
        ("Strips", len(list(STRIPS.glob("T*.jpg"))) if STRIPS.is_dir() else 0),
    ]:
        body += f"<div class='stat'><b>{val}</b><span>{label}</span></div>"
    body += "</div>"

    # links
    body += (
        "<p><a href='SUMMARY.md'>SUMMARY.md</a> &middot; "
        "<a href='../showcase/index.html'>Showcase catalogue</a> &middot; "
        "<a href='anomaly_map.html'>Anomaly map</a></p>"
    )

    # top leads section
    body += f"<h2>Top leads <span style='font-weight:normal;font-size:.9rem;color:#8b949e'>({min(60,len(top))} of {len(top)})</span></h2>"
    body += "<p>Cross-band confirmed, contrast &ge; 1.50, off-border, 200&ndash;50000 px.</p>"
    body += "<div class='grid'>" + "".join(cards) + "</div>"

    # findings list
    if finding_count > 0:
        body += f"<h2>Finding reports ({finding_count})</h2><div class='findings'>"
        for i in range(1, finding_count + 1):
            body += f"<a href='leads/F-{i:04d}.md'>F-{i:04d}</a> "
        body += "</div>"

    body += "</body></html>"

    out = CONC / "report.html"
    out.write_text(body, encoding="utf-8")
    print(f"Written {out}  ({len(rows)} candidates, {len(leads)} leads, {len(top)} top leads, {finding_count} findings)")


if __name__ == "__main__":
    main()
