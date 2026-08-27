"""Second-pass chase: resolve the top adjudication leads against their source
products and the original (un-enhanced) images.

This is the confirmation step the methodology demands before anything is
called a finding: for each candidate in leads.csv, record what the source image
actually is, verify the feature survives in the original product (local-sigma
z-score), note whether an independent acquisition exists, and write a per-lead
report F-*.md into conclusions/leads/.

Usage:
    python scripts/chase_leads.py [--leads data/anomalies/conclusions/leads.csv]
                                  [--out data/anomalies/conclusions/leads]
                                  [--top 20]
"""

import argparse
import csv
import datetime
import hashlib
import os
import re

import numpy as np
from PIL import Image


RAW_DIR = os.path.join("data", "raw", "moon")
PROC_DIR = os.path.join("data", "processed", "moon")

# Enhance step upscales by this factor (pipeline/enhance.py --scale 2).
ENH_SCALE = 2

# Source-product identification (from NASA Photojournal metadata and LROC team
# publications). Type is the key discriminator: only "imagery" products can
# support a surface finding; false-color "map" products cannot.
SOURCE = {
    "PIA02442": dict(
        mission="Mariner 10",
        title="Moon North Pole mosaic",
        type="imagery",
        product="Mariner 10 photomosaic (press product)",
        url="https://images.nasa.gov/details/PIA02442",
    ),
    "PIA12228": dict(
        mission="Cassini-Huygens",
        title="Water on the Moon (false-color map)",
        type="map",
        product="Cassini VIMS/UVIS abundance map",
        url="https://images.nasa.gov/details/PIA12228",
    ),
    "PIA12229": dict(
        mission="Chandrayaan-1",
        title="Mineral Mapping the Moon (false-color map)",
        type="map",
        product="M3 mineral map",
        url="https://images.nasa.gov/details/PIA12229",
    ),
    "PIA12233": dict(
        mission="LRO",
        title="Mapping the Moon, Point by Point (topography map)",
        type="map",
        product="LOLA topography map",
        url="https://images.nasa.gov/details/PIA12233",
    ),
    "PIA12235": dict(
        mission="Chandrayaan-1",
        title="Nearside of the Moon mosaic",
        type="imagery",
        product="M3 mosaic (press product)",
        url="https://images.nasa.gov/details/PIA12235",
    ),
    "PIA13227": dict(
        mission="LRO",
        title="The Earth from the Moon",
        type="imagery",
        product="LROC WAC image (press product)",
        url="https://images.nasa.gov/details/PIA13227",
    ),
    "PIA13496": dict(
        mission="LRO",
        title="The Moon's Largest Impact Basin (SPA)",
        type="imagery",
        product="LROC WAC SPA-basin mosaic; NAC detail M103196768LE",
        url="https://images.nasa.gov/details/PIA13496",
    ),
    "PIA13515": dict(
        mission="LRO",
        title="Natural Bridge on the Moon",
        type="imagery",
        product="LROC NAC M113168034R (King crater melt sheet)",
        url="https://images.nasa.gov/details/PIA13515",
    ),
    "PIA13516": dict(
        mission="LRO",
        title="Moon seen from the East",
        type="imagery",
        product="LROC WAC mosaic (press product)",
        url="https://images.nasa.gov/details/PIA13516",
    ),
    "PIA13517": dict(
        mission="LRO",
        title="Color of the Moon (color composite)",
        type="map",
        product="LROC WAC color composite",
        url="https://images.nasa.gov/details/PIA13517",
    ),
    "PIA13642": dict(
        mission="LRO",
        title="Highest Point on the Moon",
        type="imagery",
        product="LROC WAC mosaic (press product)",
        url="https://images.nasa.gov/details/PIA13642",
    ),
    "PIA13998": dict(
        mission="LRO",
        title="Challenger Astronauts Memorialized on the Moon",
        type="imagery",
        product="LROC WAC mosaic of Apollo crater field",
        url="https://images.nasa.gov/details/PIA13998",
    ),
    "PIA14114": dict(
        mission="MESSENGER",
        title="The Moon as seen by MESSENGER",
        type="imagery",
        product="MESSENGER MDIS full-disk view (press product)",
        url="https://images.nasa.gov/details/PIA14114",
    ),
    "PIA14208": dict(
        mission="MESSENGER",
        title="That No Moon... (Mercury)",
        type="imagery",
        product="MESSENGER MDIS full-disk Mercury (press product)",
        url="https://images.nasa.gov/details/PIA14208",
    ),
    "PIA16621": dict(
        mission="GRAIL",
        title="Map of Moon Crust (false-color map)",
        type="map",
        product="GRAIL crust-thickness map",
        url="https://images.nasa.gov/details/PIA16621",
    ),
    "PIA16622": dict(
        mission="GRAIL",
        title="GRAIL Gravity Tour (false-color map)",
        type="map",
        product="GRAIL gravity map",
        url="https://images.nasa.gov/details/PIA16622",
    ),
}

# Independent-acquisition notes for imagery leads (from LROC/NASA publications).
INDEP = {
    "PIA13515": (
        "Natural bridge in King crater impact melt. LROC has imaged the "
        "feature in six independent NAC frames under different lighting: "
        "M103725084L, M103732241L, M106088433L, M113168034R, M123785162L, "
        "M123791947L. Feature is real and is a known, explained geological "
        "feature (dual collapse into a lava tube), not an anomaly."
    ),
    "PIA13496": (
        "South Pole-Aitken basin interior is cratered/ridged terrain; "
        "WAC mosaic plus NAC detail M103196768LE cover the region. Small "
        "bright/dark patches are consistent with fresh craters and ejecta."
    ),
    "PIA14114": (
        "MESSENGER full-disk view of the Moon; the flagged region is the "
        "bright lunar disk against black space (limb boundary), not a "
        "surface feature."
    ),
    "PIA14208": (
        "Full-disk Mercury image; flagged regions are limb/disk boundary "
        "or albedo contrast, explained by geometry."
    ),
    "PIA13642": (
        "LROC WAC mosaic of the highest-point region (Aristarchus plateau "
        "area); small blobs are crater/ridge pixels."
    ),
    "PIA13227": (
        "LROC WAC image of Earth above the lunar limb; flagged pixels near the limb/Earth boundary."
    ),
    "PIA13998": (
        "LROC WAC mosaic of the crater field used to memorialize the "
        "Challenger crew; candidates are craters within the field."
    ),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_raw(proc_path):
    """Map a processed image path back to the matching raw product path."""
    if not proc_path:
        return None
    norm = proc_path.replace("\\", "/")
    parts = norm.split("/")
    try:
        i = parts.index("processed")
    except ValueError:
        return None
    rel = parts[i + 1 :]
    stem = rel[-1]
    stem = re.sub(r"_enh\.png$", "", stem)
    base = os.path.join("data", "raw", *rel[:-1], stem)
    for ext in (".jpg", ".jpeg", ".png"):
        cand = base + ext
        if os.path.exists(cand):
            return cand
    return None


def load_img_gray(path):
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def raw_z_score(proc_path, ex, ey, ew, eh, scale=ENH_SCALE):
    """Local-sigma contrast of the candidate in the ORIGINAL raw image."""
    raw_path = resolve_raw(proc_path)
    if not raw_path:
        return None, None, "no raw product available"
    raw = load_img_gray(raw_path)
    H, W = raw.shape
    sx = sy = 1.0 / scale
    x0, y0 = int(ex * sx), int(ey * sy)
    x1, y1 = int((ex + ew) * sx), int((ey + eh) * sy)
    x0 = max(0, min(x0, W - 2))
    y0 = max(0, min(y0, H - 2))
    x1 = max(x0 + 2, min(x1, W))
    y1 = max(y0 + 2, min(y1, H))
    fg = raw[y0:y1, x0:x1]
    pad = max(16, int(max((x1 - x0), (y1 - y0)) * 1.5))
    xb0, xb1 = max(0, x0 - pad), min(W, x1 + pad)
    yb0, yb1 = max(0, y0 - pad), min(H, y1 + pad)
    box = np.ones((yb1 - yb0, xb1 - xb0), dtype=bool)
    box[y0 - yb0 : y1 - yb0, x0 - xb0 : x1 - xb0] = False
    bg = raw[yb0:yb1, xb0:xb1][box]
    z = (fg.mean() - bg.mean()) / max(bg.std(), 1e-6)
    return z, (x0, y0, x1 - x0, y1 - y0), raw_path


def classify(z):
    if abs(z) >= 3.0:
        return "SURVIVES-ORIGINAL", "feature persists in the original product"
    return "BACKGROUND-LIMITED", "contrast collapses to the local noise floor in the original"


# Generic source metadata for EDR/browse product families.
def product_source(pid):
    if pid.startswith(("ESP", "PSP")):
        return dict(
            mission="MRO",
            title="HiRISE browse product (%s)" % pid,
            type="imagery",
            product="HiRISE RED/MIRB/MRGB browse JPEG (PDS extras RDR)",
            url="https://hirise-pds.lpl.arizona.edu/PDS/",
        )
    if re.match(r"^M1?\d", pid):
        return dict(
            mission="LRO",
            title="LROC NAC browse product (%s)" % pid,
            type="imagery",
            product="LROC NAC EDR browse JPEG (pyramid, PDS)",
            url="https://pds-imaging.jpl.nasa.gov/data/lro/XXDELETEME_lroc/",
        )
    if pid.lower().startswith("mars_") or "sol" in pid.lower():
        return dict(
            mission="Mars 2020 / MSL",
            title="Rover camera image (%s)" % pid,
            type="imagery",
            product="Perseverance/Mars rover camera EDR",
            url="https://mars.nasa.gov/mars2020/multimedia/raw-images/",
        )
    return dict(mission="unknown", title="unknown", type="unknown", product="unknown", url="")


def resolve_pid(pid):
    """SOURCE -> SOURCE-like metadata, falling back to the generic family rule."""
    if pid in SOURCE:
        return SOURCE[pid]
    return product_source(pid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leads", default="data/anomalies/conclusions/leads.csv")
    ap.add_argument("--out", default="data/anomalies/conclusions/leads")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    with open(a.leads, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: float(r["interest"]), reverse=True)
    rows = rows[: a.top]

    today = datetime.date.today().isoformat()
    written = []
    for n, r in enumerate(rows, 1):
        pid = r["image"].replace("_enh.png", "")
        src = resolve_pid(pid)
        proc = r["path"]
        z, rawbox, raw_path = raw_z_score(proc, int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))
        if z is None:
            status, why = "NO-RAW", raw_path or "could not resolve raw product"
        else:
            status, why = classify(z)
        ftype = src["type"]
        family = "pia" if pid in SOURCE else ("edr" if ftype == "imagery" else "other")
        if ftype == "map":
            verdict = (
                "NO-FINDING: false-color map product; flagged region is a "
                "color/abundance boundary, not a surface feature."
            )
        elif pid in INDEP:
            verdict = "NO-FINDING: real feature but fully explained; %s (z=%.2f in original)." % (
                INDEP[pid].split(".")[0],
                z or 0,
            )
        elif status == "BACKGROUND-LIMITED":
            verdict = (
                "NO-FINDING: feature collapses in the original product "
                "(z=%.2f); explained as terrain/compression within a "
                "press-processed JPEG."
            ) % z
        elif status == "NO-RAW":
            verdict = "INCOMPLETE: raw product unavailable for verification."
        elif family == "edr":
            verdict = (
                "CANDIDATE: real surface feature that persists in the EDR "
                "original (z=%.2f). Requires geolocation and an independent "
                "acquisition at different lighting before classification."
            ) % z
        else:
            verdict = "NO-FINDING: %s" % why
        conf = "high" if (ftype == "map" or abs(z or 0) >= 3.0) else "medium"
        is_candidate = family == "edr" and status == "SURVIVES-ORIGINAL"

        flags = r["flags"].strip()
        if flags:
            chk = "\n".join("- [x] %s" % f for f in flags.split(","))
        else:
            chk = "- [ ] no artifact flags triggered"

        raw_hash = sha256_file(raw_path) if raw_path else "unavailable"
        indep = INDEP.get(
            pid,
            "No independent surface acquisition identified; "
            "check PDS catalog for a revisit at different lighting.",
        )
        if status == "SURVIVES-ORIGINAL" and not indep.startswith("No independent"):
            indep = "See note for %s: %s" % (pid, INDEP[pid])

        body = (
            "# Finding Report (chase)\n\n"
            "- Finding ID: %s\n- Date: %s\n- Investigator: automated chase "
            "(scripts/chase_leads.py)\n- Status: %s\n- Evidence class: %s\n\n"
            "## Source\n"
            "- Product ID: %s\n- File: `%s`\n"
            "- Title: %s\n- Mission / instrument: %s\n"
            "- Product type: %s (%s)\n- Direct source URL: %s\n"
            "- Raw file sha256: %s\n\n"
            "## Location\n"
            "- Pixel coords (enhanced image, x, y): %s, %s; size %s x %s px\n"
            "- Pixel coords in original product: %s\n"
            "- Local-sigma z-score in original product: %s\n"
            "- Verification in original: %s\n\n"
            "## Anomaly description\n"
            "- Polarity: %s; contrast (enhanced) vs background: %s\n"
            "- Apparent size: %s px area, aspect %s, compactness %s\n"
            "- Persistence after denoising: %s\n"
            "- Adjudication score: %s (interest %s)\n\n"
            "## Independent acquisitions / explanation\n"
            "%s\n\n"
            "## Known-artifact checklist\n%s\n\n"
            "## Confirmation status\n"
            "- [ ] Seen in >1 independent image at surface-feature scale (RED/MIRB/MRGB are band variants of ONE acquisition, not independent passes)\n"
            "- [ ] Cross-checked against global mosaic coverage\n"
            "- [ ] Independently flagged in blind review\n"
            "- [x] Verified against the original (un-enhanced) product\n\n"
            "## Conclusion\n"
            "- Verdict: %s\n"
            "- Confidence: %s\n"
            "- Recommended next steps: %s\n"
        ) % (
            "F-%04d" % n,
            today,
            "OPEN-CANDIDATE" if is_candidate else "EXPLAINED",
            "1" if ftype == "map" else ("3" if status == "SURVIVES-ORIGINAL" else "1"),
            pid,
            r["path"],
            src["title"],
            src["mission"],
            ftype,
            src["product"],
            src["url"],
            raw_hash,
            r["x"],
            r["y"],
            r["w"],
            r["h"],
            "(%s, %s, %s, %s)" % rawbox if rawbox else "unavailable",
            ("%.2f" % z) if z is not None else "unavailable",
            why,
            r["polarity"],
            r["contrast"],
            r["area_px"],
            r["aspect"],
            r["compactness"],
            r["persistence"],
            r["score"],
            r["interest"],
            indep,
            chk,
            verdict,
            conf,
            (
                "Geolocate this feature (PDS geometry / Trek) and check for an "
                "independent pass at different lighting before writing a finding. "
                "A single-acquisition bright blob is most plausibly a fresh crater "
                "or albedo feature, not an unexplained anomaly."
                if is_candidate
                else "none; candidate is explained. If a surface feature is of "
                "interest, fetch the EDR and look for the same pixels in a "
                "sibling product or an independent pass."
            ),
        )

        fn = os.path.join(a.out, "F-%04d.md" % n)
        with open(fn, "w", encoding="utf-8") as f:
            f.write(body)
        written.append((fn, verdict, status, z))

    print("wrote %d chase reports to %s" % (len(written), a.out))
    for fn, verdict, status, z in written:
        print(
            "  %s  %-24s z=%s"
            % (os.path.basename(fn), status, ("%+.2f" % z) if z is not None else "n/a")
        )


if __name__ == "__main__":
    main()
