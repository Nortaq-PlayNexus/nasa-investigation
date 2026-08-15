"""AI-assisted anomaly analysis.

After `detect.py` flags candidates and `mark.py` draws them, this step:
  1. enhances each candidate crop several independent ways,
  2. measures physical/image features with numpy,
  3. evaluates it against the known-artifact checklist (docs/ARTIFACTS.md),
  4. checks for matching features in related frames of the same scene,
  5. ranks candidates and writes an HTML investigation report,
  optionally asking a vision LLM for a second opinion (env AI_LLM_KEY etc.).

Only the LLM path needs a network/API key; everything else is offline.
"""

import argparse
import base64
import csv
import html
import json
import os
import re
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

import common
import detect


def box_blur(arr, size):
    return detect.box_blur(arr, size)


def load_gray(path):
    return common.load_gray(path)


def enhance_variants(crop):
    """Independent enhancements of the crop array (float 0-255)."""
    out = {}
    lo, hi = np.percentile(crop, (0.5, 99.5))
    if hi - lo < 1:
        hi = lo + 1
    out["stretch"] = np.clip((crop - lo) * (255.0 / (hi - lo)), 0, 255)
    bg = box_blur(crop, max(5, min(65, int(min(crop.shape) / 2))))
    res = crop - bg
    lo2, hi2 = np.percentile(res, (2, 98))
    if hi2 - lo2 < 1:
        hi2 = lo2 + 1
    out["residual"] = np.clip((res - lo2) * (255.0 / (hi2 - lo2)), 0, 255)
    im = Image.fromarray(out["stretch"].astype(np.uint8))
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=1))
    out["upscale"] = np.asarray(im, dtype=np.float32)
    return out


def make_strip(variants, height=256):
    """Tile stretch|residual|upscale variants into one RGB strip image."""
    tiles = []
    for key in ("stretch", "residual", "upscale"):
        a = variants[key]
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB")
        s = height / float(im.height)
        im = im.resize((max(1, int(im.width * s)), height), Image.LANCZOS)
        tiles.append(im)
    w = sum(t.width for t in tiles)
    strip = Image.new("RGB", (w, height), (20, 20, 20))
    x = 0
    for t in tiles:
        strip.paste(t, (x, 0))
        x += t.width
    return strip


def measure(crop, fx, fy, fw, fh):
    fg = crop[fy:fy + fh, fx:fx + fw]
    mask = np.ones(crop.shape, dtype=bool)
    mask[fy:fy + fh, fx:fx + fw] = False
    bg = crop[mask]
    fg_mean, bg_mean = float(fg.mean()), float(bg.mean())
    bg_std = float(bg.std()) + 1e-6
    feats = {
        "polarity": "bright" if fg_mean >= bg_mean else "dark",
        "contrast": round(abs(fg_mean - bg_mean) / bg_std, 2),
        "fg_mean": round(fg_mean, 1),
        "bg_mean": round(bg_mean, 1),
        "bg_std": round(bg_std, 2),
        "sat_frac": round(float((fg >= 253).mean()), 3),
        "dark_frac": round(float((fg <= 2).mean()), 3),
        "texture": round(float(fg.std()), 1),
    }
    return feats


def analyze_candidate(row, arr, max_crop):
    H, W = arr.shape
    x, y, w, h = int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])
    margin = int(0.5 * max(w, h))
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
    crop = arr[y0:y1, x0:x1]
    scale = 1.0
    if crop.shape[0] > max_crop or crop.shape[1] > max_crop:
        scale = max_crop / float(max(crop.shape))
        crop = np.asarray(
            Image.fromarray(crop.astype(np.uint8)).resize(
                (max(8, int(crop.shape[1] * scale)), max(8, int(crop.shape[0] * scale))),
                Image.BILINEAR), dtype=np.float32)
    fx = int((x - x0) * scale)
    fy = int((y - y0) * scale)
    fw = max(1, int(w * scale))
    fh = max(1, int(h * scale))
    fx = min(fx, crop.shape[1] - 2)
    fy = min(fy, crop.shape[0] - 2)
    fw = min(fw, crop.shape[1] - fx)
    fh = min(fh, crop.shape[0] - fy)

    feats = measure(crop, fx, fy, fw, fh)
    feats.update({
        "area_px": int(w) * int(h),
        "aspect": round(max(w, h) / float(max(1, min(w, h))), 2),
        "fill": float(row["fill"]),
        "x": int(x), "y": int(y), "w": int(w), "h": int(h),
    })
    xdist = min(x % 8, 8 - (x % 8))
    ydist = min(y % 8, 8 - (y % 8))
    feats["on_grid8"] = xdist <= 2 and ydist <= 2
    feats["near_edge"] = bool(x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1)
    feats["dark_band"] = bool(feats["dark_frac"] >= 0.9 and (y <= 0.02 * H or y + h >= 0.98 * H))
    return crop, feats


def artifact_flags(feats):
    flags = {}
    aspect = feats["aspect"]
    if aspect >= 4 and (feats["w"] <= 12 or feats["h"] <= 12):
        flags["streak"] = "thin, elongated: likely bad column/row, seam, or cosmic-ray trail"
    if feats["area_px"] <= 800 and feats["sat_frac"] >= 0.3 and feats["contrast"] >= 3:
        flags["hot_pixel"] = "tiny, saturated, high contrast: likely hot pixel / cosmic ray hit"
    if feats["area_px"] < 1500 and aspect < 3:
        flags["small_blob"] = "small, isolated: too few pixels to distinguish surface feature from sensor noise"
    if (feats["on_grid8"] and feats["fill"] <= 0.3) or (feats["fill"] <= 0.12 and aspect < 3):
        flags["compression"] = "sparse/boxy, aligned to 8px grid: likely JPEG/JP2 compression artifact"
    if feats["sat_frac"] >= 0.5:
        flags["saturation"] = "more than half the region is blown out: highlight clipping, not structure"
    if feats["near_edge"]:
        flags["edge_artifact"] = "touches image border: possible calibration strip / edge effect"
    if feats["dark_band"]:
        flags["dark_band"] = "near-dark at top/bottom edge: HiRISE trailing-edge dark band artifact"
    if aspect >= 4 and feats["area_px"] >= 50000:
        flags["elongated_large"] = "large thin region: likely ridgeline/scan artifact rather than discrete object"
    return flags


def interest_score(feats, flags, matches):
    score = 35.0 * min(feats["contrast"] / 4.0, 1.0)
    score += 15.0 * min(feats["area_px"] / 30000.0, 1.0)
    score += 15.0 * (1.0 - min((feats["aspect"] - 1) / 9.0, 1.0))
    if not feats["near_edge"]:
        score += 10.0
    if feats["sat_frac"] < 0.3:
        score += 10.0
    score += 15.0 * min(matches / 3.0, 1.0)
    for flag in flags:
        score -= 30.0 if flag == "streak" else (15.0 if flag == "small_blob" else 20.0)
    return round(max(0.0, min(100.0, score)), 1)


def evidence_class(flags, matches):
    if set(flags) - {"small_blob"}:
        return 1
    if matches >= 2:
        return 3
    return 2


def verdict_text(flags, cls, matches):
    if flags:
        reasons = "; ".join(flags.values())
        return "Artifact: " + reasons
    base = "Candidate surface feature"
    if matches >= 1:
        base += " (corresponding feature found in %d related frame%s)" % (
            matches, "" if matches == 1 else "s")
    return base + " - evidence class %d (weak, single acquisition)" % cls


def sibling_stem(path):
    base = os.path.basename(path)
    m = re.match(r"^(ESP_\d+_\d+|PIA\d+)", base)
    return m.group(1) if m else os.path.splitext(base)[0]


def precompute(candidates):
    """Cache image sizes and absolute geometry for candidate matching."""
    size_cache = {}
    recs = {}
    for i, row in enumerate(candidates):
        path = row["path"]
        if path not in size_cache:
            try:
                size_cache[path] = load_size(path)
            except Exception:
                size_cache[path] = None
        size = size_cache[path]
        if not size:
            continue
        W, H = size
        recs[i] = {
            "stem": sibling_stem(path),
            "path": path,
            "W": W, "H": H,
            "x": int(row["x"]), "y": int(row["y"]),
            "w": int(row["w"]), "h": int(row["h"]),
        }
    return recs


def find_matches(recs, idx):
    """Count distinct same-size sibling images with a candidate at ~the same location.

    Only sibling products with identical dimensions (e.g. HiRISE MIRB/MRGB band
    variants of one footprint) are compared, using absolute pixel coordinates.
    This is an honest 'same feature in a related frame' signal.
    """
    a = recs[idx]
    seen = set()
    for j, b in recs.items():
        if j == idx or b["stem"] != a["stem"]:
            continue
        if b["path"] == a["path"] or b["W"] != a["W"] or b["H"] != a["H"]:
            continue
        tx = 0.02 * a["W"] + 4
        ty = 0.02 * a["H"] + 4
        if abs(a["x"] - b["x"]) <= tx and abs(a["y"] - b["y"]) <= ty:
            if abs(a["w"] / max(1e-6, b["w"])) < 3.0 and abs(a["h"] / max(1e-6, b["h"])) < 3.0:
                seen.add(b["path"])
    return len(seen)


def load_size(path):
    with Image.open(path) as im:
        return im.size


def llm_verdict(strip_path, feats, flags, cls):
    key = os.environ.get("AI_LLM_KEY")
    endpoint = os.environ.get("AI_LLM_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    model = os.environ.get("AI_LLM_MODEL", "meta-llama/llama-3.2-90b-vision-instruct")
    if not key:
        return ""
    b64 = base64.b64encode(open(strip_path, "rb").read()).decode()
    prompt = (
        "You are a rigorous NASA planetary imagery analyst. An anomaly detector "
        "flagged the boxed region in this enhancement strip (stretch | residual | upscale) "
        "from a Moon/Mars image. Features: %s. Heuristic artifact flags: %s. "
        "Answer in 2-3 sentences: is this a real surface feature or a known artifact "
        "(compression, cosmic ray, sensor defect, shadow, optics)? Give a confidence." %
        (json.dumps(feats), json.dumps(flags)))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return "LLM error: %s" % e


def main():
    p = argparse.ArgumentParser(description="Enhance, evaluate and investigate anomaly candidates")
    p.add_argument("--candidates", required=True)
    p.add_argument("--out", default="data/anomalies/analysis")
    p.add_argument("--max-crop", type=int, default=512, help="analysis crop cap per side")
    p.add_argument("--top", type=int, default=12, help="how many top candidates to ask the LLM about")
    p.add_argument("--llm", action="store_true", help="ask vision LLM for top candidates (requires env AI_LLM_KEY)")
    a = p.parse_args()
    common.set_audit(os.path.join(a.out, "..", "audit.jsonl"))
    start = common.time.time()

    with open(a.candidates, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    common.log("info", "analyze: %d candidates" % len(rows))

    crops_dir = os.path.join(a.out, "crops")
    os.makedirs(crops_dir, exist_ok=True)

    evaluated = []
    recs = precompute(rows)
    by_image = {}
    for i, row in enumerate(rows):
        by_image.setdefault(row["path"], []).append((i, row))
    done = 0
    skipped = 0
    for path, group in sorted(by_image.items()):
        if not os.path.exists(path):
            skipped += len(group)
            continue
        try:
            arr = load_gray(path)
        except Exception:
            skipped += len(group)
            continue
        H, W = arr.shape
        for i, row in group:
            if not common.validate_box(int(row["x"]), int(row["y"]),
                                       int(row["w"]), int(row["h"]), W, H):
                skipped += 1
                continue
            crop, feats = analyze_candidate(row, arr, a.max_crop)
            flags = artifact_flags(feats)
            matches = find_matches(recs, i)
            cls = evidence_class(flags, matches)
            feats["score"] = interest_score(feats, flags, matches)
            feats["evidence_class"] = cls
            feats["matches"] = matches
            feats["verdict"] = verdict_text(flags, cls, matches)
            feats["flags"] = ",".join(sorted(flags))

            strip = make_strip(enhance_variants(crop))
            strip_name = "c%04d_%s.jpg" % (i, re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(path))[:60])
            strip_path = os.path.join(crops_dir, strip_name)
            strip.save(strip_path, quality=92)
            feats["_strip"] = os.path.join("crops", strip_name)
            feats["image"] = row["image"]
            feats["path"] = path
            evaluated.append(feats)
            done += 1
            if done % 500 == 0:
                print("analyzed %d/%d" % (done, len(rows)), flush=True)

    evaluated.sort(key=lambda r: r["score"], reverse=True)
    fields = ["image", "x", "y", "w", "h", "contrast", "area_px", "aspect", "fill",
              "polarity", "sat_frac", "dark_frac", "on_grid8", "near_edge", "matches",
              "evidence_class", "score", "verdict", "flags"]
    common.atomic_csv_write(os.path.join(a.out, "evaluated.csv"), evaluated, fields)

    llm_notes = []
    if a.llm and os.environ.get("AI_LLM_KEY"):
        for r in evaluated[:a.top]:
            verdict = llm_verdict(os.path.join(a.out, r["_strip"]), r, r.get("flags", ""), r["evidence_class"])
            llm_notes.append((r, verdict))
    elif a.llm:
        print("LLM requested but AI_LLM_KEY not set; skipping LLM verdicts.")

    write_report(a.out, evaluated, llm_notes)
    common.log("info", "analyze: %d candidates -> %s" % (len(evaluated), a.out))
    common.audit({
        "event": "analyze",
        "cmd": " ".join(sys.argv),
        "candidates": len(rows), "evaluated": len(evaluated), "skipped": skipped,
        "out": os.path.abspath(a.out),
        "candidates_sha256": common.sha256_file(a.candidates),
        "evaluated_sha256": common.sha256_file(os.path.join(a.out, "evaluated.csv")),
        "seconds": round(common.time.time() - start, 1),
    })


def write_report(out, evaluated, llm_notes):
    by_img = {}
    for r in evaluated:
        by_img.setdefault(r["image"], []).append(r)

    cards = []
    for r in evaluated:
        flags = r["flags"].split(",") if r["flags"] else []
        flag_html = "".join("<li>{}</li>".format(html.escape(f)) for f in flags) or "<li>no artifact flags</li>"
        llm = "".join(
            "<div class='llm'><b>LLM:</b> {}</div>".format(html.escape(v))
            for rr, v in llm_notes if rr is r)
        cards.append(
            "<div class='card'>"
            "<img src='{strip}'>"
            "<p><b>{image}</b> bbox {x},{y} {w}x{h} "
            "<span class='cls'>class {cls}</span> "
            "<span class='sc'>interest {score}</span></p>"
            "<p>contrast {contrast} | {area_px}px&sup2; | aspect {aspect} | fill {fill} | "
            "polarity {polarity} | matches {matches}</p>"
            "<p class='verdict'>{verdict}</p>"
            "<ul class='flags'>{flags}</ul>{llm}</div>".format(
                strip=html.escape(r["_strip"]),
                image=html.escape(r["image"]), x=r["x"], y=r["y"], w=r["w"], h=r["h"],
                cls=r["evidence_class"], score=r["score"], contrast=r["contrast"],
                area_px=r["area_px"], aspect=r["aspect"], fill=r["fill"],
                polarity=r["polarity"], matches=r["matches"], verdict=html.escape(r["verdict"]),
                flags=flag_html, llm=llm))

    top = evaluated[:15]
    top_html = "".join(
        "<tr><td>{}</td><td>{}</td><td>{},{}</td><td>{}</td><td>{}</td></tr>".format(
            r["image"], r["score"], r["x"], r["y"], r["evidence_class"], html.escape(r["verdict"]))
        for r in top)

    img_summary = "".join(
        "<tr><td>{}</td><td>{}</td><td>{:.0%}</td></tr>".format(
            html.escape(img), len(lst), sum(r["evidence_class"] >= 3 for r in lst) / max(1, len(lst)))
        for img, lst in sorted(by_img.items()))

    style = ("body{font-family:sans-serif;background:#0d1117;color:#d8dee6;margin:1.5rem}"
             ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:1rem}"
             ".card{border:1px solid #2a3138;padding:.6rem;background:#151b23}"
             ".card img{max-width:100%;border:1px solid #333}"
             ".cls{color:#f0b429}.sc{color:#7ee787}table{border-collapse:collapse;width:100%;margin-bottom:1rem}"
             "th,td{border:1px solid #2a3138;padding:.3rem .5rem;font-size:.8rem;text-align:left}"
             ".verdict{font-weight:bold}.flags{margin:.3rem 0 0 1rem;font-size:.75rem;color:#ff9b9b}"
             ".llm{background:#1c2733;padding:.4rem;font-size:.8rem;margin-top:.3rem}")
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>Anomaly investigation</title>"
            "<style>{}</style></head><body>"
            "<h1>Anomaly investigation</h1>"
            "<p>{} candidates analyzed, top interest {:.1f}, {} with artifact flags, "
            "{} class-3+ candidates.</p>"
            "<h2>Top candidates</h2><table><tr><th>image</th><th>score</th><th>xy</th>"
            "<th>class</th><th>verdict</th></tr>{}</table>"
            "<h2>Per image</h2><table><tr><th>image</th><th>candidates</th><th>class3+</th></tr>"
            "{}</table>"
            "<h2>All candidates</h2><div class='grid'>{}</div></body></html>".format(
                style, len(evaluated), evaluated[0]["score"] if evaluated else 0,
                sum(1 for r in evaluated if r["flags"]),
                sum(1 for r in evaluated if r["evidence_class"] >= 3),
                top_html, img_summary, "".join(cards)))
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
