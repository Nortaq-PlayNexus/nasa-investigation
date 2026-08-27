"""Catalog every downloaded product: hashes, dimensions, mission, and the
solar/geometry metadata parsed from its PDS label.

Also enforces the chain-of-custody rule: after a catalog snapshot is written
(--snapshot), data/raw must not change. --check-immutable compares every file
against the snapshot so a tampered or swapped original is caught before any
analysis is trusted.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline")
)

import common
import metadata


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def image_probe(path):
    try:
        w, h = common.image_dims(path)
        return w, h
    except Exception:
        return "", ""


def guess_mission(name, low):
    if re.search(r"^(psp|esp|mrb)_", low):
        return "hirise"
    if re.search(r"ctx", low):
        return "ctx"
    if re.search(r"moc|narrow.?angle", low):
        return "moc"
    if re.search(r"viking|vo1|vo2|^v1|^v2", low):
        return "viking"
    if re.search(r"lunar.?orbiter|lo[1-5]|^(lo)_", low):
        return "lunar-orbiter"
    if re.search(r"clementine|^cl_|uvvis|niris", low):
        return "clementine"
    if re.search(r"m3|chandrayaan|moon.?mineralogy", low):
        return "m3"
    if re.search(r"themis", low):
        return "themis"
    if re.search(r"nac|wac|narrow.?angle|wide.?angle", low):
        return "lroc"
    if re.search(r"mast|navcam|mcz|mahli|sherloc|mastcam|sol\d", low):
        return "marsrover"
    if re.search(r"apollo|as\d{2}-|a\d{2}-", low):
        return "apollo"
    if re.search(r"hrsc|mars.?express", low):
        return "mex"
    return "unknown"


FIELDS = [
    "path",
    "body",
    "mission",
    "name",
    "bytes",
    "sha256",
    "width",
    "height",
    "label_path",
    "observation_id",
    "target",
    "instrument",
    "band",
    "start_time",
    "incidence_angle",
    "emission_angle",
    "phase_angle",
    "solar_azimuth",
    "solar_elevation",
    "pixel_scale_m",
    "spacecraft_altitude_km",
]


def process_file(root, path):
    name = os.path.basename(path)
    if name.endswith(
        (".meta.json", ".log", ".part", ".LBL", ".lbl", ".XML", ".xml", ".J2I", ".LBL.json")
    ):
        return None
    rel = os.path.relpath(path, root)
    body = rel.split(os.sep)[0].lower()
    low = name.lower()
    w, h = image_probe(path)
    geo = metadata.geometry_from_path(path) if (w or h) else {}
    return {
        "path": rel,
        "body": body,
        "mission": guess_mission(name, low),
        "name": name,
        "bytes": os.path.getsize(path),
        "sha256": sha256(path),
        "width": w,
        "height": h,
        "label_path": metadata._find_label(path) or "",
        "observation_id": geo.get("observation_id") or "",
        "target": geo.get("target") or "",
        "instrument": geo.get("instrument") or "",
        "band": geo.get("band") or "",
        "start_time": geo.get("start_time") or "",
        "incidence_angle": geo.get("incidence_angle") or "",
        "emission_angle": geo.get("emission_angle") or "",
        "phase_angle": geo.get("phase_angle") or "",
        "solar_azimuth": geo.get("solar_azimuth") or "",
        "solar_elevation": geo.get("solar_elevation") or "",
        "pixel_scale_m": geo.get("pixel_scale_m") or "",
        "spacecraft_altitude_km": geo.get("spacecraft_altitude_km") or "",
    }


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Build a searchable catalog of downloaded imagery with hashes and metadata"
    )
    p.add_argument("--root", default="data/raw")
    p.add_argument("--out", default="data/catalog/catalog.csv")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="write data/catalog/immutable.json (sha256 of every file) after cataloging",
    )
    p.add_argument(
        "--check-immutable",
        action="store_true",
        help="fail if any file under --root differs from the snapshot",
    )
    a = p.parse_args(argv)

    if a.check_immutable:
        snap_path = os.path.join(os.path.dirname(a.out), "immutable.json")
        if not os.path.exists(snap_path):
            print("no snapshot at", snap_path)
            return 1
        with open(snap_path, encoding="utf-8") as f:
            snap = json.load(f)
        bad = 0
        for rel, h in snap.items():
            full = os.path.join(a.root, rel)
            if not os.path.exists(full):
                print("MISSING", rel)
                bad += 1
            elif sha256(full) != h:
                print("TAMPERED/CHANGED", rel)
                bad += 1
        print(f"immutability check: {bad} changed/missing of {len(snap)}")
        return 0 if bad == 0 else 1

    files = []
    for root, dirs, names in os.walk(a.root):
        for n in names:
            files.append(os.path.join(root, n))
    rows = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for row in ex.map(lambda p: process_file(a.root, p), sorted(files)):
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda r: r["path"])

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    common.atomic_csv_write(a.out, rows, FIELDS)
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    if a.snapshot:
        snap = {r["path"]: r["sha256"] for r in rows}
        snap_path = os.path.join(os.path.dirname(a.out), "immutable.json")
        common.atomic_text_write(snap_path, json.dumps(snap, indent=2))
        print("snapshot written ->", snap_path)

    geo = sum(1 for r in rows if r.get("solar_azimuth"))
    print(f"cataloged {len(rows)} files ({geo} with solar geometry) -> {a.out}")


if __name__ == "__main__":
    sys.exit(main())
