"""Build a self-contained, publicly-committable Anomaly Analysis Report.

The pipeline's own report lives under ``data/anomalies/`` which is gitignored,
so it never reaches GitHub. This script reads the local adjudication data and
emits a single self-contained ``report/index.html`` (images inlined as base64)
that can be committed and viewed by anyone on the repository.

    python scripts/build_public_report.py
    python scripts/build_public_report.py --out report/index.html
"""

from __future__ import annotations

import base64
import csv
import html
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
ANALYSIS = ROOT / "data" / "anomalies" / "analysis"
STRIPS = CONC / "strips"
LEADS_DIR = CONC / "leads"


def strip_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            name = f.name
            if name.startswith("T") and "_" in name and name.endswith(".jpg"):
                img = name.split("_", 1)[1][:-4]  # drop T000_ prefix and .jpg
                idx.setdefault(img, f)
    return idx


def b64(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = path.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


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


def build(out_path: Path) -> None:
    si = strip_index()
    rows = read_csv(CONC / "adjudicated.csv")
    leads = read_csv(CONC / "leads.csv")
    summary_md = (CONC / "SUMMARY.md").read_text(encoding="utf-8") if (CONC / "SUMMARY.md").exists() else ""

    # verdict distribution
    counts: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict", "UNKNOWN")
        counts[v] = counts.get(v, 0) + 1
    dist = " &middot; ".join(f"{html.escape(k)}: {v}" for k, v in sorted(counts.items()))

    top = top_leads(rows)

    # top leads cards (inline strips for first 30)
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
            f"<b>score</b> {num(r['score']):.0f} &middot; "
            f"<b>contrast</b> {num(r['contrast']):.2f}</p>"
            f"<table><tr><td>x,y</td><td>{r['x']}, {r['y']}</td></tr>"
            f"<tr><td>size</td><td>{r['w']} x {r['h']} px</td></tr>"
            f"<tr><td>evidence class</td><td>{r.get('evidence_class', '')}</td></tr>"
            f"<tr><td>cross-band</td><td>{r.get('agrees', '')} agree / {r.get('disagrees', '')} disagree</td></tr>"
            f"<tr><td>persistence</td><td>{r.get('persistence', '')}</td></tr>"
            f"<tr><td>compactness</td><td>{r.get('compactness', '')}</td></tr>"
            f"<tr><td>area</td><td>{r.get('area_px', '')} px</td></tr>"
            f"<tr><td>flags</td><td><ul>{flag_html}</ul></td></tr></table>"
            f"{img_tag}"
            f"<p class='notes'>{html.escape(r.get('recommendation', ''))}</p></div>"
        )

    # full top-leads table (text only)
    table_rows = []
    for i, r in enumerate(top):
        table_rows.append(
            f"<tr><td>{i + 1}</td><td>{html.escape(r['image'])}</td>"
            f"<td>{num(r['score']):.0f}</td><td>{r['x']},{r['y']}</td>"
            f"<td>{html.escape(r.get('evidence_class', ''))}</td>"
            f"<td>{html.escape(r.get('verdict', ''))}</td>"
            f"<td>{num(r['contrast']):.2f}</td>"
            f"<td>{r.get('agrees', '')}/{r.get('disagrees', '')}</td></tr>"
        )

    # findings
    finding_files = sorted(LEADS_DIR.glob("F-*.md")) if LEADS_DIR.is_dir() else []
    finding_html = ""
    for f in finding_files:
        text = f.read_text(encoding="utf-8")
        body = html.escape(text)
        body = body.replace("\n", "<br>")
        finding_html += f"<details class='finding'><summary>{html.escape(f.name)}</summary><div class='finding-body'>{body}</div></details>"

    finding_count = len(finding_files)

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
        ".cls{color:#f0b429}"
        "table{border-collapse:collapse;margin:.6rem 0;width:100%}"
        "th,td{border:1px solid #2a3138;padding:.25rem .5rem;font-size:.8rem;text-align:left}"
        "th{background:#1a2030}"
        "ul{margin:.2rem 0 0 1rem;padding:0}"
        "a{color:#58a6ff}"
        ".stats{display:flex;flex-wrap:wrap;gap:.5rem;margin:.8rem 0}"
        ".stat{background:#1a2030;border:1px solid #2a3138;border-radius:6px;padding:.5rem .8rem}"
        ".stat b{font-size:1.3rem;display:block;color:#fff}"
        ".stat span{font-size:.75rem;color:#8b949e}"
        ".notes{color:#8b949e;font-size:.85rem}"
        ".finding{border:1px solid #2a3138;border-radius:6px;padding:.4rem .8rem;margin:.4rem 0;background:#151b23}"
        ".finding summary{cursor:pointer;font-weight:bold}"
        ".finding-body{margin-top:.6rem;font-size:.85rem;line-height:1.4}"
        ".summary{white-space:pre-wrap;background:#151b23;border:1px solid #2a3138;border-radius:6px;padding:1rem;font-size:.85rem;overflow:auto}"
        "</style></head><body>"
        "<header><h1>NASA HiRISE — Anomaly Analysis Report</h1>"
        f"<p>Generated from the public pipeline adjudication output. "
        f"{len(rows)} candidates adjudicated &middot; {len(leads)} leads &middot; {finding_count} finding reports.</p>"
        f"<p>Verdict distribution: {dist}</p>"
        f"<p><a href='https://github.com/Nortaq-PlayNexus/nasa-investigation'>Repository</a> &middot; "
        f"<a href='docs/METHODOLOGY.md'>Methodology</a> &middot; "
        f"<a href='docs/ARTIFACTS.md'>Artifact catalog</a> &middot; "
        f"<a href='#adjudication-summary'>Adjudication summary</a></p></header>"
    )

    body += "<div class='stats'>"
    for label, val in [
        ("Candidates", len(rows)),
        ("Leads", len(leads)),
        ("Top leads", len(top)),
        ("Findings", finding_count),
        ("Strips", len(list(STRIPS.glob('T*.jpg'))) if STRIPS.is_dir() else 0),
    ]:
        body += f"<div class='stat'><b>{val}</b><span>{label}</span></div>"
    body += "</div>"

    body += (
        "<h2>Top leads <span style='font-weight:normal;font-size:.9rem;color:#8b949e'>"
        f"({min(30, len(top))} shown with strips, {len(top)} total)</span></h2>"
        "<p>Cross-band confirmed, contrast &ge; 1.50, off-border, 200&ndash;50000 px.</p>"
        "<div class='grid'>" + "".join(cards) + "</div>"
    )

    body += (
        f"<h2>All top leads ({len(top)})</h2>"
        "<table><tr><th>#</th><th>image</th><th>score</th><th>xy</th>"
        "<th>class</th><th>verdict</th><th>contrast</th><th>X-band</th></tr>"
        + "".join(table_rows)
        + "</table>"
    )

    if summary_md:
        body += "<h2>Adjudication summary</h2><div class='summary'>" + html.escape(summary_md) + "</div>"

    if finding_html:
        body += f"<h2>Finding reports ({finding_count})</h2>" + finding_html

    body += "</body></html>"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024
    print(f"Wrote {out_path} ({len(rows)} candidates, {len(top)} top leads, {finding_count} findings, {size_kb} KB)")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "report" / "index.html"))
    args = ap.parse_args()
    build(Path(args.out).resolve())
