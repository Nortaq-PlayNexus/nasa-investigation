"""Build the anomaly showcase catalogue: showcase/index.html.

Reads leads.csv, adjudicated.csv, findings (F-*.md), strips, marked images and
the processed source image tree, and emits a single self-contained HTML file
(embedded JSON data + inline CSS/JS) with search / filter / sort / pagination.

Also writes downscaled JPEG previews under showcase/img/ so the page stays fast
while linking to the full-resolution originals.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
STRIPS = CONC / "strips"
LEADS_F = CONC / "leads"
MARKED = ROOT / "data" / "anomalies" / "marked"
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "showcase"
OUT_IMG = OUT / "img"
OUT_IMG_MARKED = OUT_IMG / "marked"
OUT_IMG_SRC = OUT_IMG / "src"

Image.MAX_IMAGE_PIXELS = None

STRIP_INDEX: dict[str, str] = {}


def thumb(src: Path, dst: Path, max_w: int = 1280, quality: int = 80) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w > max_w:
            im = im.resize((max_w, round(h * max_w / w)), Image.LANCZOS)
        im.save(dst, "JPEG", quality=quality, optimize=True)


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("**", "")
        .replace("`", "")
    )


def md_to_html(md: str) -> str:
    """Minimal, safe markdown->HTML for the finding reports."""
    out: list[str] = []
    in_list = False
    in_table = False
    for line in md.splitlines():
        line = line.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            continue
        if line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{line[2:].strip()}</h2>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{line[3:].strip()}</h3>")
        elif line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h4>{line[4:].strip()}</h4>")
        elif line.startswith("- ["):
            if not in_list:
                out.append("<ul>")
                in_list = True
            checked = "[x]" in line.lower()
            item = line.split("] ", 1)[-1]
            box = "&#9745;" if checked else "&#9744;"
            out.append(f'<li><span class="cb">{box}</span> {esc(item)}</li>')
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc(line[2:].strip())}</li>")
        elif line.startswith("|"):
            if not in_table:
                out.append("<table>")
                in_table = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if "-" not in cells[0] else "td"
            out.append("<tr>" + "".join(f"<{tag}>{esc(c)}</{tag}>" for c in cells) + "</tr>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{esc(line)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def band_of(image: str) -> str:
    m = re.search(r"_(MIRB|MRGB|RED)\.", image)
    if not m:
        return ""
    return m.group(1)


def base_of(image: str) -> str:
    return re.sub(r"_(MIRB|MRGB|RED)\.browse_enh\.png$", "", image) or image


def body_of(path: str, image: str) -> str:
    if "mars" in path:
        return "Mars"
    if "moon" in path:
        return "Moon"
    if "Perseverance" in image or "CAM" in image or "sol0" in path:
        return "Mars (rover)"
    return "Moon" if re.match(r"^[MP]\d", image) else ""


def obs_id_of(image: str) -> str | None:
    m = re.match(r"(ESP_\d+_\d+)", image)
    return m.group(1) if m else None


def parse_finding(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Finding ID: (F-\d+)", text)
    status = re.search(r"Status: (\S+)", text)
    ev = re.search(r"Evidence class: (\d)", text)
    src = re.search(r"File: `([^`]+\.png)`", text)
    image = ""
    src_path = ""
    if src:
        image = Path(src.group(1)).name
        src_path = src.group(1)
    return {
        "id": m.group(1) if m else path.stem,
        "status": status.group(1) if status else "",
        "evidence_class": int(ev.group(1)) if ev else None,
        "file": path.name,
        "image": image,
        "path": src_path.replace("\\", "/"),
        "strip": strip_of(image),
        "marked": marked_of(image),
        "html": md_to_html(text),
    }


def strip_of(image: str) -> str | None:
    if image in STRIP_INDEX:
        return f"data/anomalies/conclusions/strips/{STRIP_INDEX[image]}"
    return None


def marked_of(image: str) -> str:
    f = f"marked_{image[:-4]}.png" if image.endswith(".png") else ""
    return f if f in MARKED_SET else ""


def main() -> None:
    global STRIP_INDEX, MARKED_SET
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_IMG_MARKED.mkdir(parents=True, exist_ok=True)
    OUT_IMG_SRC.mkdir(parents=True, exist_ok=True)

    # ---- strips: T###_<image>.jpg, map by product image name ----
    STRIP_INDEX = {}
    if STRIPS.is_dir():
        for f in sorted(STRIPS.iterdir()):
            name = f.name
            if name.startswith("T") and "_" in name:
                img = name.split("_", 1)[1]
                STRIP_INDEX.setdefault(img[:-4], name)

    # ---- marked images: marked_<image>.png ----
    MARKED_SET = set()
    if MARKED.is_dir():
        for f in MARKED.iterdir():
            if f.name.startswith("marked_") and f.suffix.lower() == ".png":
                MARKED_SET.add(f.name)
                thumb(f, OUT_IMG_MARKED / (f.stem + ".jpg"), max_w=1400, quality=82)

    # ---- leads ----
    leads = []
    with (CONC / "leads.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            leads.append(dict(row))

    def _f(key, default=0.0):
        # graceful behind-exists helper for the new rigor metric columns
        def _get(row):
            try:
                v = row.get(key)
                return float(v) if v not in (None, "") else default
            except (TypeError, ValueError):
                return default

        return _get

    _grid = _f("grid_energy")
    _edge = _f("edge_sharpness")
    _stab = _f("contrast_stability")
    _size_m = _f("size_m")
    _shadow = _f("shadow_alignment")

    for r in leads:
        img = r["image"]
        r["_body"] = body_of(r.get("path", ""), img)
        r["_band"] = band_of(img)
        r["_strip"] = strip_of(img)
        r["_marked"] = marked_of(img)
        r["_obs"] = obs_id_of(img) or ""
        r["_contrast"] = float(r.get("contrast", 0) or 0)
        r["_score"] = float(r.get("score", 0) or 0)
        r["_area"] = int(r.get("area_px", 0) or 0)
        r["_grid"] = _grid(r)
        r["_edge"] = _edge(r)
        r["_stab"] = _stab(r)
        r["_size_m"] = _size_m(r)
        r["_shadow"] = _shadow(r)

    # ---- findings ----
    findings = []
    if LEADS_F.is_dir():
        for f in sorted(LEADS_F.glob("F-*.md")):
            findings.append(parse_finding(f))
    findings.sort(key=lambda d: d["id"])

    # ---- source image catalogue (processed tree) ----
    sources = []
    if PROCESSED.is_dir():
        for f in sorted(PROCESSED.rglob("*")):
            if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                rel = f.relative_to(ROOT).as_posix()
                rel_no_ext = f.relative_to(PROCESSED).with_suffix("").as_posix()
                thumb_f = OUT_IMG_SRC / (rel_no_ext.replace("/", "__").replace("\\", "__") + ".jpg")
                try:
                    with Image.open(f) as im:
                        w, h = im.size
                except Exception:
                    w = h = 0
                sources.append(
                    {
                        "file": rel,
                        "body": body_of(rel, f.name),
                        "w": w,
                        "h": h,
                        "thumb": "img/src/" + thumb_f.name,
                        "size": f.stat().st_size,
                    }
                )
                thumb(f, thumb_f, max_w=640, quality=78)

    # ---- group leads into distinct features (merge band variants) ----
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
        groups = {}
        for i in range(len(items)):
            groups.setdefault(find(i), []).append(items[i])
        return list(groups.values())

    bybase: dict[str, list] = {}
    for r in leads:
        bybase.setdefault(base_of(r["image"]), []).append(r)

    features = []
    for members in bybase.values():
        for grp in union_find(
            members,
            lambda a, b: abs(int(a["x"]) - int(b["x"])) <= 6
            and abs(int(a["y"]) - int(b["y"])) <= 6,
        ):
            grp.sort(key=lambda r: (-r["_score"], r["image"]))
            p = grp[0]
            bands = sorted({band_of(m["image"]) for m in grp if band_of(m["image"])})
            flags = sorted({f for m in grp for f in (m.get("flags") or "").split() if f})
            f = {
                "base": base_of(p["image"]),
                "members": grp,
                "bands": bands,
                "image": p["image"],
                "x": p["x"],
                "y": p["y"],
                "w": p["w"],
                "h": p["h"],
                "max_score": max(m["_score"] for m in grp),
                "max_contrast": max(m["_contrast"] for m in grp),
                "area": p["_area"],
                "aspect": p["aspect"],
                "polarity": p["polarity"],
                "evidence_class": max(int(m.get("evidence_class", 0) or 0) for m in grp),
                "confidence": p["confidence"],
                "interest": max(float(m.get("interest", 0) or 0) for m in grp),
                "fdr_q": min(float(m.get("fdr_q", 1) or 1) for m in grp),
                "grid_energy": max(m["_grid"] for m in grp),
                "edge_sharpness": max(m["_edge"] for m in grp),
                "contrast_stability": max(m["_stab"] for m in grp),
                "size_m": max(m["_size_m"] for m in grp),
                "shadow_alignment": max(m["_shadow"] for m in grp),
                "flags": flags,
                "recommendation": p["recommendation"],
                "_body": p["_body"],
                "_strip": next((m["_strip"] for m in grp if m["_strip"]), None),
                "_marked": next((m["_marked"] for m in grp if m["_marked"]), ""),
                "_obs": p["_obs"],
                "path": p["path"],
                "verdicts": sorted({m["verdict"] for m in grp}),
                "verdict": p["verdict"],
            }
            features.append(f)
    features.sort(key=lambda f: -f["max_score"])

    # ---- stats ----
    verdicts: dict[str, int] = {}
    bodies: dict[str, int] = {}
    bands: dict[str, int] = {}
    has_strip = 0
    for f in features:
        verdicts[f["verdict"]] = verdicts.get(f["verdict"], 0) + 1
        if f["_body"]:
            bodies[f["_body"]] = bodies.get(f["_body"], 0) + 1
        for b in f["bands"]:
            bands[b] = bands.get(b, 0) + 1
        if f["_strip"]:
            has_strip += 1

    band_variants = sum(len(f["members"]) for f in features) - len(features)
    stats = {
        "leads_total": len(leads),
        "features": len(features),
        "band_variants": band_variants,
        "top_leads": has_strip,
        "verdicts": verdicts,
        "bodies": bodies,
        "bands": bands,
        "findings": len(findings),
        "marked": len(MARKED_SET),
        "sources": len(sources),
    }

    # ---- audit / run history (data/anomalies/audit.jsonl) ----
    audit = []
    audit_path = ROOT / "data" / "anomalies" / "audit.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                audit.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    audit.sort(key=lambda r: r.get("ts") or "", reverse=True)

    payload = {
        "stats": stats,
        "features": features,
        "findings": findings,
        "sources": sources,
        "marked": sorted(MARKED_SET),
        "audit": audit,
    }
    json_blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    html = TEMPLATE.replace("__JSON__", json_blob)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"showcase/index.html  {os.path.getsize(OUT / 'index.html') / 1e6:.1f} MB")
    print(
        f"features={len(features)} (from {len(leads)} lead rows) findings={len(findings)} sources={len(sources)} marked={len(MARKED_SET)}"
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anomaly Catalogue &mdash; NASA Moon &amp; Mars Investigation</title>
<style>
:root{--bg:#0b0e14;--panel:#111623;--panel2:#151b2b;--line:#232b3f;--txt:#d7e0f0;--dim:#8ea0bf;--faint:#5b6b8a;
--green:#35c46b;--amber:#e0a83c;--red:#e05c5c;--blue:#4aa3ff;--purple:#a68bff;--mono:Consolas,"Cascadia Mono",monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:14px/1.55 system-ui,Segoe UI,Roboto,sans-serif;padding:28px 20px 80px}
.wrap{max-width:1280px;margin:0 auto}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:26px;letter-spacing:.3px}
h2{font-size:19px;margin:44px 0 4px;color:#fff;border-bottom:1px solid var(--line);padding-bottom:8px}
h2 .n{color:var(--faint);font-size:13px;font-weight:400;margin-left:8px}
.sub{color:var(--dim);margin:8px 0 18px;max-width:900px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:12.5px}
.chip b{color:#fff;font-size:15px;display:block}
.statrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:18px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat .k{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
.stat .v{font-size:22px;font-weight:600;margin-top:2px}
.vbar{display:flex;height:26px;border-radius:6px;overflow:hidden;margin:10px 0 14px;border:1px solid var(--line)}
.vbar div{display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;min-width:34px;white-space:nowrap}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--dim);margin-bottom:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.dots{color:var(--faint);font-size:11px;margin:6px 0 0}
table{width:100%;border-collapse:collapse;margin:8px 0}
th,td{border:1px solid var(--line);padding:5px 9px;font-size:12.5px;text-align:left}
th{background:var(--panel2);color:#fff}
/* findings */
.fcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:12px 0;overflow:hidden}
.fcard summary{cursor:pointer;list-style:none;padding:12px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.fcard summary::-webkit-details-marker{display:none}
.fcard summary:hover{background:var(--panel2)}
.fid{font-family:var(--mono);font-weight:700;color:#fff}
.fbody{padding:4px 18px 16px;border-top:1px solid var(--line)}
.fbody h2,.fbody h3,.fbody h4{font-size:14px;margin:16px 0 6px;color:#fff;border:none;padding:0}
.fbody ul{margin:4px 0 8px;padding-left:20px}
.fbody li{margin:2px 0}
.fbody p{margin:6px 0;color:var(--txt)}
.fbody table{font-size:12px}
.fbody .cb{color:var(--amber)}
/* badges */
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;letter-spacing:.4px;text-transform:uppercase}
.b-LEAD{background:#12301f;color:var(--green);border:1px solid #1d5a38}
.b-PROMISING{background:#31290f;color:var(--amber);border:1px solid #5c4a17}
.b-EXPLAINED{background:#241718;color:var(--red);border:1px solid #4d2729}
.b-OPEN{background:#12283a;color:var(--blue);border:1px solid #1d4668}
.b-body{background:#111827;color:var(--purple);border:1px solid #2a2547}
.b-band{background:#0d1a21;color:#7fd4e8;border:1px solid #16404d;font-family:var(--mono)}
.b-polarity{background:#1c1f2e;color:#c9b8ff;border:1px solid #2d2a45}
.b-conf{background:var(--panel2);color:var(--dim);border:1px solid var(--line);text-transform:none}
/* catalogue controls */
.controls{display:grid;grid-template-columns:1fr;gap:10px;margin:14px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.controls input[type=text],.controls select{background:#0d1220;border:1px solid var(--line);color:var(--txt);border-radius:7px;padding:8px 10px;font-size:13px;font-family:var(--mono);width:100%}
.controls input[type=text]:focus,.controls select:focus{outline:none;border-color:var(--blue)}
.frow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.frow label{font-size:12px;color:var(--dim);display:flex;align-items:center;gap:6px;white-space:nowrap}
.frow input[type=number]{width:74px;background:#0d1220;border:1px solid var(--line);color:var(--txt);border-radius:6px;padding:5px 7px;font-family:var(--mono)}
.frow input[type=checkbox]{accent-color:var(--blue)}
.count{font-size:12.5px;color:var(--dim);margin:6px 2px}
/* lead cards */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.card .imgbox{position:relative;background:#000;min-height:120px;display:flex;align-items:center;justify-content:center}
.card img{width:100%;height:auto;display:block}
.card .ph{padding:26px 10px;color:var(--faint);font-family:var(--mono);font-size:11.5px;text-align:center;word-break:break-all}
.card .ttl{padding:10px 12px 4px;font-family:var(--mono);font-size:12px;color:#fff;word-break:break-all}
.card .tbadges{padding:4px 12px 8px;display:flex;flex-wrap:wrap;gap:5px}
.card .meta{padding:0 12px 10px;font-size:12px;color:var(--dim);display:grid;grid-template-columns:1fr 1fr;gap:2px 10px}
.card .meta span:nth-child(odd){color:var(--faint)}
.card .links{padding:8px 12px 12px;display:flex;flex-wrap:wrap;gap:6px;margin-top:auto;border-top:1px solid var(--line);background:var(--panel2)}
.card .links a{font-size:11.5px;font-family:var(--mono);border:1px solid var(--line);padding:3px 8px;border-radius:6px;background:#0d1220}
details.extra{margin:6px 0 0}
details.extra summary{cursor:pointer;color:var(--dim);font-size:11.5px;font-family:var(--mono)}
details.extra .rec{font-size:12px;color:var(--txt);margin-top:6px;line-height:1.5}
/* source & marked galleries */
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.g{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.g img{width:100%;height:110px;object-fit:cover;display:block;background:#000}
.g .cap{padding:6px 8px;font-size:11px;color:var(--dim);word-break:break-all;font-family:var(--mono)}
.g .cap b{color:#fff;display:block;font-family:system-ui}
.foot{margin-top:50px;color:var(--faint);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
.more{display:block;margin:16px auto;background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:10px 22px;cursor:pointer;font-size:13px}
.more:hover{border-color:var(--blue);color:#fff}
.empty{color:var(--faint);padding:30px;text-align:center;font-family:var(--mono)}
/* analytics + search history + run timeline */
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:10px 0}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.chart h3{font-size:13px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.chart svg{width:100%;height:auto;display:block}
.chart .cap{font-size:11px;color:var(--faint);margin-top:4px}
.ax{stroke:var(--line)}
.gtxt{font:10.5px var(--mono);fill:var(--dim)}
/* search history */
.hist{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}
.hist .lbl{font-size:11.5px;color:var(--faint)}
.hchip{background:#0d1220;border:1px solid var(--line);color:var(--blue);border-radius:14px;padding:2px 10px;font:12px var(--mono);cursor:pointer}
.hchip:hover{border-color:var(--blue)}
.hchip .x{margin-left:6px;color:var(--faint)}
.hchip .x:hover{color:var(--red)}
.action{background:#0d1220;color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:6px 12px;cursor:pointer;font-size:12.5px}
.action:hover{border-color:var(--blue);color:#fff}
.qrow{display:flex;gap:8px}
.qbtn{background:var(--blue);border:none;color:#04121f;font-weight:700;border-radius:7px;padding:8px 16px;cursor:pointer;font-size:13px}
.qbtn:hover{filter:brightness(1.1)}
.sug{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.sug span{font-size:11px;color:var(--faint)}
.sugg{background:var(--panel2);border:1px solid var(--line);color:var(--dim);border-radius:12px;padding:2px 10px;font-size:11.5px;cursor:pointer}
.sugg:hover{color:var(--blue);border-color:var(--blue)}
/* run timeline */
.timeline{list-style:none;margin:8px 0;border-left:2px solid var(--line);padding-left:16px}
.timeline li{position:relative;margin:14px 0}
.timeline li::before{content:'';position:absolute;left:-21px;top:3px;width:9px;height:9px;border-radius:50%;background:var(--panel2);border:2px solid var(--blue)}
.timeline .ev{font-family:var(--mono);font-weight:600;color:#fff}
.timeline .ts{color:var(--faint);font:11px var(--mono)}
.timeline .det{color:var(--dim);font-size:12px;margin-top:2px;line-height:1.45}
.timeline .det b{color:var(--txt);font-weight:600}
.ev-badge{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 8px;font:11px var(--mono);margin-left:8px;color:var(--blue)}
@media(max-width:700px){h1{font-size:20px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Anomaly Catalogue &mdash; Moon &amp; Mars Remote-Sensing Investigation</h1>
  <div class="sub">Automated anomaly pipeline over verified PDS imagery &mdash; HiRISE browse (Mars), LROC NAC browse (Moon) and Perseverance rover cameras. Every candidate was enhanced, artifact-checked, cross-band confirmed and adjudicated. This page catalogues the results: the top leads with enhancement strips, all adjudicated leads with full metrics, the finding reports, and every source image.</div>
  <div class="chips" id="statsChips"></div>
  <div class="statrow" id="statRow"></div>
  <h2>Verdict distribution</h2>
  <div id="verdictBar"></div>
  <div class="legend" id="verdictLegend"></div>
</header>

<h2>Analytics <span class="n">multi-metric visual analysis of every adjudicated lead</span></h2>
<div class="sub">Rendered live from the full adjudication set. Hover any chart. The spatial plot shows where anomalies sit <i>within</i> each image (normalised x/y) &mdash; edge and corner clustering is the classic sensor-artifact signature, central diffuse scatter is consistent with real surface features.</div>
<div class="charts">
  <div class="chart"><h3>Score distribution</h3><div id="chScore"></div><div class="cap">adjudicated score histogram</div></div>
  <div class="chart"><h3>Contrast vs score</h3><div id="chScatter"></div><div class="cap">each dot = a distinct feature, sized by area, coloured by verdict</div></div>
  <div class="chart"><h3>Area distribution (log)</h3><div id="chArea"></div><div class="cap">feature pixel area, log scale</div></div>
  <div class="chart"><h3>Contrast histogram</h3><div id="chContrast"></div><div class="cap">peak local-sigma contrast</div></div>
  <div class="chart"><h3>Verdict composition</h3><div id="chDonut"></div><div class="cap">share of each verdict</div></div>
  <div class="chart"><h3>Polarity &amp; band</h3><div id="chPolar"></div><div class="cap">bright vs dark &middot; band variants present</div></div>
  <div class="chart"><h3>Spatial position within frame</h3><div id="chSpace"></div><div class="cap">normalised anomaly position (x, y) &mdash; clustering at edges/corners = artifact</div></div>
  <div class="chart"><h3>Rigor metrics</h3><div id="chRigor"></div><div class="cap">median grid-energy (spectral) &middot; edge sharpness &middot; contrast stability</div></div>
</div>

<h2>Bottom line <span class="n">from conclusions/SUMMARY.md</span></h2>
<p class="sub">After two passes (17 PIA press products, then 105 verified raw files), <b>no candidate meets the bar for a finding</b>: cross-band agreement confirms a feature across band variants of <i>one</i> acquisition, but does not prove it is non-artifact. 724 discrete features survive the contrast bar (cross-band confirmed, contrast &ge; 1.50, off-border, 200&ndash;50000 px); the chase found surface features that genuinely persist in the originals &mdash; but every one is ordinary geology (fresh craters / boulders / albedo patches) or a known CCD/compression artifact (LROC streaks, hot pixels, grids). Confirming any top lead requires the EDR original + an independent pass at different lighting. See the 25 chase findings below and <a href="../data/anomalies/conclusions/SUMMARY.md">SUMMARY.md</a>.</p>

<h2>Chase findings <span class="n">findings/leads reports, F-0001&hellip;</span></h2>
<div class="sub">Each finding report links the enhanced source, its enhancement strip and the boxed full-resolution image.</div>
<div id="findings"></div>

<h2>Anomaly catalogue <span class="n">distinct features, band variants merged</span></h2>
<div class="sub">Every adjudicated anomaly as a single card. The same feature confirmed in band variants (RED / MIRB / MRGB) of one observation is grouped into one card &mdash; band counts are shown as badges and compared in the per-band table. Enhancement strips exist for the top features by score. &ldquo;Source&rdquo; opens the full enhanced product, &ldquo;Boxed&rdquo; the same image with the anomaly region marked.</div>
<div class="controls">
  <div class="qrow">
    <input type="text" id="q" placeholder="Manual search: product id, observation, coordinates, flags, body, band&hellip;" onkeydown="if(event.key==='Enter'){render();saveSearch()}">
    <button class="qbtn" onclick="render();saveSearch()">Search</button>
    <button class="action" onclick="saveSearch()" title="Save the current search to history">&#43; Save search</button>
    <button class="action" onclick="clearFilters()" title="Reset all filters">Reset</button>
  </div>
  <div class="sug" id="suggRow"></div>
  <div class="hist" id="histRow" style="display:none"><span class="lbl">History:</span><button class="action" onclick="clearHistory()" title="Clear saved searches">clear</button></div>
  <div class="frow">
    <label>Verdict <select id="fVerdict" onchange="render()">
      <option value="">all</option><option>CONFIRMED-LEAD</option><option>PROMISING</option></select></label>
    <label>Body <select id="fBody" onchange="render()">
      <option value="">all</option></select></label>
    <label>Band <select id="fBand" onchange="render()">
      <option value="">all</option></select></label>
    <label>Polarity <select id="fPolarity" onchange="render()">
      <option value="">all</option><option>bright</option><option>dark</option></select></label>
    <label>Min score <input type="number" id="fScore" value="0" min="0" max="100" onchange="render()"></label>
    <label>Min contrast <input type="number" id="fContrast" value="0" step="0.1" onchange="render()"></label>
    <label><input type="checkbox" id="fStrip" onchange="render()"> has strip</label>
    <label>Sort <select id="fSort" onchange="render()">
      <option value="score">score desc</option><option value="contrast">contrast desc</option>
      <option value="area">area desc</option><option value="x">x asc</option><option value="id">product id</option></select></label>
  </div>
</div>
<div class="count" id="count"></div>
<div class="grid" id="cards"></div>
<button class="more" id="moreBtn" onclick="showMore()">Show more</button>

<h2>Source image catalogue <span class="n">data/processed &mdash; every enhanced product</span></h2>
<div class="sub">Full-resolution enhanced products. Click for the original file (these are the files the candidates and strips were measured from).</div>
<div class="gal" id="sources"></div>

<h2>Boxed full-resolution images <span class="n">data/anomalies/marked</span></h2>
<div class="sub">Every source image with the anomalous region boxed. Click for the full-resolution PNG.</div>
<div class="gal" id="marked"></div>

<h2>Analysis run history <span class="n">data/anomalies/audit.jsonl</span></h2>
<div class="sub">Every pipeline run (analyze / benchmark / adjudicate / chase) recorded by the audit trail &mdash; newest first &mdash; with its parameters, input/output hashes and duration. This is the provenance behind every claimed number on this page.</div>
<div id="timeline"></div>

<h2>Data &amp; methodology</h2>
<table>
<tr><th>Artifact</th><th>Path</th><th>Notes</th></tr>
<tr><td>Adjudication summary</td><td><a href="../data/anomalies/conclusions/SUMMARY.md">data/anomalies/conclusions/SUMMARY.md</a></td><td>Funnel, verdict distribution, stress test, bottom line</td></tr>
<tr><td>All leads (CSV)</td><td><a href="../data/anomalies/conclusions/leads.csv">data/anomalies/conclusions/leads.csv</a></td><td>Full metric columns for every lead</td></tr>
<tr><td>All adjudicated candidates</td><td><a href="../data/anomalies/conclusions/adjudicated.csv">data/anomalies/conclusions/adjudicated.csv</a></td><td>All verdicts incl. TERRAIN / NOISE / WEAK / EXPLAINED-ARTIFACT</td></tr>
<tr><td>Analysis report</td><td><a href="../data/anomalies/analysis/report.html">data/anomalies/analysis/report.html</a></td><td>Per-image enhancement report</td></tr>
<tr><td>Interactive anomaly map</td><td><a href="../data/anomalies/conclusions/anomaly_map.html">data/anomalies/conclusions/anomaly_map.html</a></td><td>Leads plotted on a Leaflet map</td></tr>
<tr><td>Conclusion report</td><td><a href="../data/anomalies/conclusions/report.html">data/anomalies/conclusions/report.html</a></td><td>Adjudication report</td></tr>
<tr><td>Finding reports (Markdown)</td><td><a href="../data/anomalies/conclusions/leads/">data/anomalies/conclusions/leads/</a></td><td>F-0001&hellip;F-0025</td></tr>
<tr><td>Source catalog</td><td><a href="../data/catalog/catalog.csv">data/catalog/catalog.csv</a></td><td>sha256 chain of custody + dimensions</td></tr>
<tr><td>Benchmark</td><td><a href="../data/anomalies/benchmark/benchmark_synthetic.md">data/anomalies/benchmark/</a></td><td>Synthetic sensitivity / false-positive calibration</td></tr>
</table>
<p class="dots">Detection: multi-scale blob at z&ge;3.0, min-size 12 &middot; Enhance: contrast stretch + residual + upscale &middot; Adjudicate: cross-band pixel agreement, denoise persistence, compactness, per-image negative controls, Benjamini&ndash;Hochberg FDR q=0.05 &middot; Chase: local-sigma z-score in the original (un-enhanced) product + CTX mosaic cross-check.</p>

<div class="foot">Generated by scripts/build_showcase.py from data/anomalies/conclusions/leads.csv, conclusions/leads/F-*.md, conclusions/strips/, data/anomalies/marked/ and data/processed/. Raw files under data/raw are the untouched chain-of-custody originals.</div>
</div>

<script>
const DATA = __JSON__;
const $=id=>document.getElementById(id);
const fmt=n=>Number(n).toLocaleString(undefined,{maximumFractionDigits:1});

function bd(txt,cls){return `<span class="badge ${cls}">${txt}</span>`}
function esc(s){return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function link(path,label){return `<a href="../${path}">${label}</a>`}

/* stats */
(function(){
  const s=DATA.stats, chips=$("statsChips"), row=$("statRow");
  const items=[
    ["features","Distinct anomalies",s.features],
    ["band_variants","Band variants",s.band_variants],
    ["leads_total","Lead rows",s.leads_total],
    ["top_leads","With enhancement strips",s.top_leads],
    ["findings","Chase findings",s.findings],
    ["marked","Boxed images",s.marked],
    ["sources","Source products",s.sources],
  ];
  chips.innerHTML=items.map(([k,t,v])=>`<div class="chip"><b>${v}</b>${t}</div>`).join("");
  row.innerHTML=Object.entries(s.bodies).map(([k,v])=>`<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")+
    Object.entries(s.bands).map(([k,v])=>`<div class="stat"><div class="k">band ${k}</div><div class="v">${v}</div></div>`).join("");
  const colors={"CONFIRMED-LEAD":"#35c46b","PROMISING":"#e0a83c"};
  const order=["CONFIRMED-LEAD","PROMISING"];
  const bar=$("verdictBar"), leg=$("verdictLegend");
  bar.innerHTML=order.map(k=>s.verdicts[k]?`<div style="flex:${s.verdicts[k]};background:${colors[k]}">${s.verdicts[k]}</div>`:"").join("");
  leg.innerHTML=order.map(k=>`<span><i style="background:${colors[k]}"></i>${k} &mdash; ${fmt(s.verdicts[k])}</span>`).join("")+
    `<span>distinct features ${fmt(s.features)}</span>`;
  // populate body/band filters
  const bodySel=$("fBody");Object.keys(s.bodies).sort().forEach(b=>{const o=document.createElement("option");o.textContent=b;bodySel.appendChild(o)});
  const bandSel=$("fBand");Object.keys(s.bands).sort().forEach(b=>{const o=document.createElement("option");o.textContent=b;bandSel.appendChild(o)});
})();

/* findings */
(function(){
  const fw=$("findings");
  fw.innerHTML=DATA.findings.map(f=>{
    const img=f.strip?`<div class="imgbox"><a href="../${f.strip}"><img loading="lazy" src="../${f.strip}"></a></div>`:"";
    const cls=f.status==="EXPLAINED"?"b-EXPLAINED":"b-OPEN";
    const links=[];
    if(f.path)links.push(link(f.path,"source"));
    if(f.strip)links.push(link(f.strip,"strip"));
    if(f.marked)links.push(link("data/anomalies/marked/"+f.marked,"boxed"));
    return `<details class="fcard"><summary><span class="fid">${f.id}</span>${bd(f.status,cls)}${bd("evidence "+f.evidence_class,"b-conf")}<span style="color:var(--dim);font-family:var(--mono);font-size:12px">${esc(f.file)}</span></summary>
      ${img}<div class="fbody">${f.html}<p style="margin-top:8px">${links.join(" &middot; ")}</p></div></details>`;
  }).join("");
})();

/* anomaly catalogue */
let N=0, show=48;
function filtered(){
  const q=($("q").value||"").trim().toLowerCase();
  const v=$("fVerdict").value, b=$("fBody").value, bn=$("fBand").value, p=$("fPolarity").value;
  const sc=+$("fScore").value||0, ct=+$("fContrast").value||0, strip=$("fStrip").checked;
  let L=DATA.features.filter(f=>{
    const members=f.members;
    if(v&&!f.verdicts.includes(v))return false;
    if(b&&f._body!==b)return false;
    if(bn&&!f.bands.includes(bn))return false;
    if(p&&members.some(m=>m.polarity!==p))return false;
    if(f.max_score<sc)return false;
    if(f.max_contrast<ct)return false;
    if(strip&&!f._strip)return false;
    if(q){
      const hay=members.map(m=>m.image+" "+m.x+","+m.y+" "+m.w+"x"+m.h+" "+m.flags+" "+m.verdict+" "+m.polarity+" "+m._grid+" "+m._edge+" "+m._stab).join(" ")+" "+f._obs+" "+f.base+" "+f._body+" "+f.bands.join(" ")+" "+(f._size_m||"")+"m";
      if(!hay.toLowerCase().includes(q))return false;
    }
    return true;
  });
  const srt=$("fSort").value;
  L.sort((a,b)=>{
    if(srt==="score")return b.max_score-a.max_score;
    if(srt==="contrast")return b.max_contrast-a.max_contrast;
    if(srt==="area")return b.area-a.area;
    if(srt==="x")return a.x-b.x;
    return a.base.localeCompare(b.base)});
  return L;
}
function render(){
  const L=filtered();
  N=L.length;
  $("count").textContent=`${fmt(N)} of ${DATA.features.length} distinct anomalies (${fmt(DATA.stats.leads_total)} band-variant rows)`+($("q").value?` for &ldquo;${esc($("q").value)}&rdquo;`:"");
  const el=$("cards");el.innerHTML="";show=48;
  el.innerHTML=L.slice(0,show).map(card).join("");
  $("moreBtn").style.display=N>show?"block":"none";
}
function showMore(){const L=filtered();const el=$("cards");show+=48;
  el.insertAdjacentHTML("beforeend",L.slice(show-48,show).map(card).join(""));
  $("moreBtn").style.display=N>show?"block":"none";
}
function card(f){
  const img=f._strip?`<div class="imgbox"><a href="../${f._strip}"><img loading="lazy" src="../${f._strip}" alt="${esc(f.base)}"></a></div>`
    :`<div class="imgbox"><div class="ph">${esc(f.base)}</div></div>`;
  const cls=f.verdict==="CONFIRMED-LEAD"?"b-LEAD":"b-PROMISING";
  const mixed=f.verdicts.length>1?""+bd("mixed","b-conf"):"";
  const bandBadges=f.bands.map(x=>bd(x,"b-band")).join("");
  const links=[link(f.path.replace(/\\/g,"/"),"source")];
  f.members.forEach(m=>{if(m.path!==f.path)links.push(link(m.path.replace(/\\/g,"/"),m.image.split(".")[0].split("_").pop()))});
  if(f._marked)links.push(link("data/anomalies/marked/"+f._marked,"boxed"));
  if(f._obs)links.push(`<a href="https://hirise.lpl.arizona.edu/${f._obs}" target="_blank" rel="noopener">${f._obs}</a>`);
  if(f._strip)links.push(link(f._strip,"strip"));
  const bandsRow=f.bands.map(b=>{
    const m=f.members.find(x=>x.image.includes("_"+b+"."));
    return m?`<tr><td>${b}</td><td>${m._score}</td><td>${m._contrast}</td><td>${m.x},${m.y}</td><td>${m.w}&times;${m.h}</td><td>${m.polarity}</td><td>${m.persistence}</td><td>${m.compactness}</td><td>${m.evidence_class}</td><td>${m.agrees}/${m.disagrees}</td><td>${m.fdr_q||"-"}</td></tr>`:"";
  }).join("");
  return `<div class="card">${img}
    <div class="ttl">${esc(f.base)}</div>
    <div class="tbadges">${bd(f.verdict,cls)}${mixed}${bd(f._body,"b-body")}${bandBadges}${bd(f.polarity,"b-polarity")}${bd(f.confidence,"b-conf")}${f.flags.length?bd(f.flags.join(","),"b-conf"):""}</div>
    <div class="meta">
      <span>score</span><b style="color:var(--txt)">${f.max_score}</b>
      <span>contrast</span><b style="color:var(--txt)">${f.max_contrast}</b>
      <span>area (px)</span><b style="color:var(--txt)">${f.area}</b>
      <span>aspect</span><b style="color:var(--txt)">${f.aspect}</b>
      <span>coords x,y</span><b style="color:var(--txt)">${f.x}, ${f.y}</b>
      <span>box w&times;h</span><b style="color:var(--txt)">${f.w}&times;${f.h}</b>
      <span>interest</span><b style="color:var(--txt)">${f.interest}</b>
      <span>fdr q</span><b style="color:var(--txt)">${f.fdr_q}</b>
      <span>grid-energy</span><b style="color:var(--txt)">${(f.grid_energy!==undefined)?f.grid_energy:"-"}</b>
      <span>edge sharpness</span><b style="color:var(--txt)">${(f.edge_sharpness!==undefined)?f.edge_sharpness:"-"}</b>
      <span>contrast stability</span><b style="color:var(--txt)">${(f.contrast_stability!==undefined)?f.contrast_stability:"-"}</b>
    </div>
    <details class="extra"><summary>metrics &amp; flags</summary>
      <div class="rec">${esc(f.recommendation)}</div>
      <table><thead><tr><th>band</th><th>score</th><th>contrast</th><th>x,y</th><th>box</th><th>pol.</th><th>persist</th><th>compact</th><th>e.c.</th><th>agr/dgr</th><th>fdr q</th></tr></thead><tbody>
      ${bandsRow}
      <tr><td colspan="11" style="color:var(--faint)">evidence class ${f.evidence_class} &middot; ${esc(f.flags.join(", ")||"-")} &middot; baseline fp ${esc(f.members[0].baseline_fp||"-")}</td></tr>
      </tbody></table>
    </details>
    <div class="links">${links.join("")}</div>
  </div>`;
}

/* source gallery */
(function(){
  $("sources").innerHTML=DATA.sources.map(s=>`<a class="g" href="../${s.file}"><img loading="lazy" src="${s.thumb}"><div class="cap"><b>${s.body}</b>${s.file.split("/").pop()}<br>${s.w}&times;${s.h} &middot; ${fmt(s.size/1048576)} MB</div></a>`).join("");
})();
/* marked gallery */
(function(){
  $("marked").innerHTML=DATA.marked.map(m=>`<a class="g" href="../data/anomalies/marked/${m}"><img loading="lazy" src="img/marked/${m.replace(".png",".jpg")}"><div class="cap"><b>boxed</b>${m}</div></a>`).join("");
})();

/* ---------- analytics chart renderers (pure SVG) ---------- */
const SVGNS="http://www.w3.org/2000/svg";
function svg(w,h){return `<svg xmlns="${SVGNS}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">`}
function histBins(values,bins){if(!values.length)return[];const lo=Math.min(...values),hi=Math.max(...values);const span=(hi-lo)||1;const out=Array(bins).fill(0);for(const v of values){let i=Math.floor((v-lo)/span*bins);i=Math.min(bins-1,Math.max(0,i));out[i]++}return{out,lo,hi}}
function renderHist(el,values,bins=24){const{out,lo,hi}=histBins(values,bins);const W=300,H=150,pad=26;const mx=Math.max(1,...out);let s=svg(W,H);s+=`<line x1="${pad}" y1="${H-pad}" x2="${W-4}" y2="${H-pad}" class="ax"/><line x1="${pad}" y1="4" x2="${pad}" y2="${H-pad}" class="ax"/>`;const bw=(W-pad-4)/out.length;out.forEach((c,i)=>{const h=c/mx*(H-pad-12);const x=pad+i*bw;s+=`<rect x="${x+1}" y="${H-pad-h}" width="${Math.max(1,bw-2)}" height="${h}" fill="#4aa3ff" opacity="0.9"><title>${lo+(hi-lo)*i/bins} &ndash; ${lo+(hi-lo)*(i+1)/bins}: ${c}</title></rect>`});if(out.length){const mid=lo+(hi-lo)/2;s+=`<text x="${pad}" y="${H-pad+12}" class="gtxt">${fmt(lo)}</text><text x="${W-4}" y="${H-pad+12}" text-anchor="end" class="gtxt">${fmt(hi)}</text><text x="${pad+6}" y="14" class="gtxt">n=${fmt(values.length)}</text>`}s+="</svg>";el.innerHTML=s}
function renderScatter(){const F=DATA.features;const pts=F.filter(f=>f.max_score>0||f.max_contrast>0);const X=pts.map(f=>f.max_contrast),Y=pts.map(f=>f.max_score);const xm=Math.max(0.1,...X),ym=Math.max(1,...Y);const W=300,H=220,pad=30;let s=svg(W,H);s+=`<line x1="${pad}" y1="${H-pad}" x2="${W-4}" y2="${H-pad}" class="ax"/><line x1="${pad}" y1="4" x2="${pad}" y2="${H-pad}" class="ax"/>`;const cols={"CONFIRMED-LEAD":"#35c46b","PROMISING":"#e0a83c","TERRAIN":"#7fd4e8","WEAK":"#a68bff","NOISE":"#5b6b8a","EXPLAINED-ARTIFACT":"#e05c5c"};for(const f of pts.sort((a,b)=>b.area-a.area)){const x=pad+(f.max_contrast/xm)*(W-pad-8),y=H-pad-(f.max_score/ym)*(H-pad-18);const r=Math.min(9,1.5+4*Math.sqrt(f.area/5000));s+=`<circle cx="${x}" cy="${y}" r="${r}" fill="${cols[f.verdict]||"#8ea0bf"}" opacity="0.75"><title>${esc(f.base)} | contrast ${f.max_contrast}, score ${f.max_score}, area ${f.area} px | ${f.verdict}</title></circle>`}s+=`<text x="${pad}" y="${H-pad+12}" class="gtxt">contrast &#8594;</text><text x="12" y="12" class="gtxt">score &#8594;</text>`;s+="</svg>";$("chScatter").innerHTML=s}
function renderDonut(){const F=DATA.features,cols={"CONFIRMED-LEAD":"#35c46b","PROMISING":"#e0a83c","TERRAIN":"#7fd4e8","WEAK":"#a68bff","NOISE":"#5b6b8a","EXPLAINED-ARTIFACT":"#e05c5c"};const order=["CONFIRMED-LEAD","PROMISING","TERRAIN","WEAK","NOISE","EXPLAINED-ARTIFACT"];const cnt={};F.forEach(f=>cnt[f.verdict]=(cnt[f.verdict]||0)+1);const tot=F.length||1;let acc=0;const cx=150,cy=150,R=9;let s=svg(320,200);const r=82;let prev=0;const labels=[];for(const k of order){const v=cnt[k]||0;if(!v)continue;const a0=prev,a1=prev+v/tot*Math.PI*2;prev=a1;if(a1<=a0)continue;const large=a1-a0>Math.PI?1:0;const x0=cx+r*Math.cos(a0-Math.PI/2),y0=cy+r*Math.sin(a0-Math.PI/2);const x1=cx+r*Math.cos(a1-Math.PI/2),y1=cy+r*Math.sin(a1-Math.PI/2);s+=`<path d="M${cx},${cy} L${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1} Z" fill="${cols[k]}" stroke="#0b0e14" stroke-width="1"><title>${k}: ${v} (${Math.round(v/tot*100)}%)</title></path>`}s+=`</svg><div class="cap-area" style="margin-top:4px;font-size:11px;color:var(--dim)">`+order.map(k=>cnt[k]?`<span style="margin-right:10px"><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${cols[k]};margin-right:4px"></i>${k}: ${cnt[k]}</span>`:"").join("")+`</div>`;$("chDonut").innerHTML=s}
function renderPolar(){const F=DATA.features;const pol={bright:0,dark:0};const bands={};F.forEach(f=>{pol[f.polarity]=(pol[f.polarity]||0)+1;f.bands.forEach(b=>bands[b]=(bands[b]||0)+1)});const W=300,H=170,pad=26;const items=Object.entries(pol),mx=Math.max(1,...items.map(i=>i[1]));let s=svg(W,H)+`<text x="${pad}" y="12" class="gtxt">polarity</text>`;items.forEach(([k,v],i)=>{const y=20+i*42;const bw=v/mx*(W-pad-40);s+=`<rect x="${pad}" y="${y}" width="${bw}" height="26" rx="3" fill="${k==="bright"?"#e8c66a":"#6a7fd8"}"><title>${k}: ${v}</title></rect><text x="${pad+4}" y="${y+17}" class="gtxt" style="fill:#0b0e14">${k} ${v}</text>`});if(Object.keys(bands).length){const items2=Object.entries(bands),mx2=Math.max(1,...items2.map(i=>i[1]));s+=(()=>{let t=`<text x="${pad}" y="${135}" class="gtxt">band variants</text>`;items2.forEach(([k,v],i)=>{const y=145+i*26,bw=v/mx2*(W-pad-40);t+=`<rect x="${pad}" y="${y}" width="${bw}" height="18" rx="3" fill="#7fd4e8" opacity="0.8"><title>${k}: ${v}</title></rect><text x="${pad+4}" y="${y+13}" class="gtxt">${k} ${v}</text>`});return t})()}s+="</svg>";$("chPolar").innerHTML=s}
function renderSpace(){const F=DATA.features,pts=F.filter(f=>f.w>0&&f.h>0);const W=300,H=240,pad=14;let s=svg(W,H);s+=`<rect x="${pad}" y="${pad}" width="${W-2*pad}" height="${H-2*pad}" fill="#0d1220" stroke="var(--line)"/>`;const cols={"CONFIRMED-LEAD":"#35c46b","PROMISING":"#e0a83c","TERRAIN":"#7fd4e8","WEAK":"#a68bff","NOISE":"#5b6b8a"};for(const f of pts){const nx=f.x/(f.w||1),ny=f.y/(f.h||1);if(nx<0||nx>1||ny<0||ny>1)continue;const px=pad+nx*(W-2*pad),py=pad+ny*(H-2*pad);s+=`<circle cx="${px}" cy="${py}" r="2.6" fill="${cols[f.verdict]||"#8ea0bf"}" opacity="0.6"><title>${esc(f.base)} at (${f.x},${f.y})</title></circle>`}s+=`<text x="${pad+4}" y="${H-pad+12}" class="gtxt">normalised x</text><text x="6" y="12" class="gtxt">y</text></svg>`;$("chSpace").innerHTML=s}
function renderRigor(){const F=DATA.features;const g=F.filter(f=>f.grid_energy!==undefined).map(f=>f.grid_energy);const e=F.filter(f=>f.edge_sharpness!==undefined).map(f=>f.edge_sharpness);const st=F.filter(f=>f.contrast_stability!==undefined).map(f=>f.contrast_stability);const rows=[["grid-energy",g],["edge sharpness",e],["contrast stability",st]];let s=`<table style="font-size:12px"><tr><th>metric</th><th>median</th><th>mean</th></tr>`;for(const[n,v]of rows){if(!v.length){s+=`<tr><td>${n}</td><td colspan="2" style="color:var(--faint)">re-run analyze.py to populate</td></tr>`;continue}const sorted=[...v].sort((a,b)=>a-b);const med=sorted[Math.floor(sorted.length/2)];const mean=v.reduce((a,b)=>a+b,0)/v.length;s+=`<tr><td>${n}</td><td>${fmt(med)}</td><td>${fmt(mean)}</td></tr>`}s+=`</table><div class="cap" style="margin-top:6px">${F.length} features &middot; high grid-energy = periodic sensor/compression structure</div>`;$("chRigor").innerHTML=s}
function renderAllCharts(){renderHist($("chScore"),DATA.features.map(f=>f.max_score));renderHist($("chContrast"),DATA.features.map(f=>f.max_contrast));renderHist($("chArea"),DATA.features.map(f=>Math.log10(1+f.area)),24);renderScatter();renderDonut();renderPolar();renderSpace();renderRigor()}

/* ---------- search history (localStorage) ---------- */
const LS_KEY="nasa_inves_history";
function getHist(){try{return JSON.parse(localStorage.getItem(LS_KEY)||"[]")}catch(e){return[]}}
function setHist(h){try{localStorage.setItem(LS_KEY,JSON.stringify(h.slice(0,24)))}catch(e){}}
function currentState(){return{q:$("q").value.trim(),verdict:$("fVerdict").value,body:$("fBody").value,band:$("fBand").value,polarity:$("fPolarity").value,score:$("fScore").value,contrast:$("fContrast").value,sort:$("fSort").value,strip:$("fStrip").checked}}
function saveSearch(){const st=currentState();if(!st.q&&!st.verdict&&!st.body&&!st.band&&!st.polarity&&!st.score&&!st.contrast)return;let h=getHist();h=h.filter(x=>JSON.stringify(x)!==JSON.stringify(st));h.unshift(st);setHist(h);renderHistRow();renderSugg()}
function applyState(st){$("q").value=st.q||"";$("fVerdict").value=st.verdict||"";$("fBody").value=st.body||"";$("fBand").value=st.band||"";$("fPolarity").value=st.polarity||"";$("fScore").value=st.score||0;$("fContrast").value=st.contrast||0;$("fSort").value=st.sort||"score";$("fStrip").checked=!!st.strip;render();window.scrollTo({top:$("cards").offsetTop-140,behavior:"smooth"})}
function renderHistRow(){const h=getHist(),el=$("histRow");if(!h.length){el.style.display="none";return}el.style.display="flex";const chips=h.map((st,i)=>`<span class="hchip" onclick="applyState(getHist()[${i}])">${esc(st.q||(st.verdict||st.body||st.band||"search"))}<span class="x" onclick="event.stopPropagation();removeHist(${i})" title="remove">&#10005;</span></span>`).join("");el.innerHTML=`<span class="lbl">History:</span>`+chips+`<button class="action" style="padding:2px 8px" onclick="clearHistory()">clear</button>`}
function removeHist(i){const h=getHist();h.splice(i,1);setHist(h);renderHistRow()}
function clearHistory(){setHist([]);renderHistRow()}
function clearFilters(){$("q").value="";$("fVerdict").value="";$("fBody").value="";$("fBand").value="";$("fPolarity").value="";$("fScore").value=0;$("fContrast").value=0;$("fSort").value="score";$("fStrip").checked=false;render()}
const SUGG=["CONFIRMED-LEAD","PROMISING","bright","dark","Mars","Moon","streak","hot_pixel","compression","ESP_","moon__NHQ"];
function renderSugg(){$("suggRow").innerHTML=`<span>Try:</span>`+SUGG.map(t=>`<span class="sugg" onclick="chipsugg('${t}')">${t}</span>`).join("")}
function chipsugg(t){const q=$("q").value?($("q").value+" "+t):t;$("q").value=q;render();saveSearch()}

/* ---------- run history timeline ---------- */
(function(){
  const evCols={"analyze":"#4aa3ff","benchmark":"#35c46b","adjudicate":"#e0a83c","chase_leads":"#a68bff"};
  const tl=$("timeline");
  if(!DATA.audit||!DATA.audit.length){tl.innerHTML=`<p class="empty">No audit records found (run the pipeline first).</p>`;return}
  const items=DATA.audit.map(r=>{
    const ev=r.event||"run";const det=[];
    for(const k of ["candidates","evaluated","adjudicated","top_leads","negative_control_fp","n_detections","recall","fdr_q"]){if(r[k]!==undefined&&r[k]!==null){det.push(`<b>${k}</b> ${Array.isArray(r[k])?r[k].join("/"):r[k]}`)}}
    if(r.seconds!==undefined)det.push(`<b>elapsed</b> ${r.seconds}s`);
    if(r.cmd)det.push(`<span style="color:var(--faint)">${esc(String(r.cmd).slice(0,140))}</span>`);
    return `<li><span class="ev">${esc(ev)}</span><span class="ev-badge" style="border-color:${evCols[ev]||'var(--line)'}">${esc(ev)}</span><br><span class="ts">${esc(r.ts||"—")} &middot; ${esc(r.out||"")}</span><div class="det">${det.join(" &middot; ")||"—"}</div></li>`;
  }).join("");
  tl.innerHTML=`<ul class="timeline">${items}</ul>`;
})();

renderAllCharts();
renderSugg();
renderHistRow();
render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
