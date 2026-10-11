#!/usr/bin/env python3
"""
Systematic EXTRAS pass — walk the catalogue, one image at a time
==============================================================
Reads the site catalogue produced by ``scripts/catalog_extras_site.py`` and
walks it in a fixed, reproducible order, taking every image through the whole
pipeline and recording a per-image JSON verdict. Designed to be launched in
the background and left alone: it checkpoints after every image, resumes
where it stopped, and stops cleanly on a disk or time budget.

For each footprint, in order:

  1. **acquire**  download the footprint's browse variant set
                  (``browse`` + ``thumb`` by default; JP2s refused unless
                  ``--max-fullres-mb``), verify SHA-256, append provenance to
                  ``data/raw/manifest.jsonl``, write ``_variant_manifest.json``.
  2. **compare**  ``extras_compare`` — align every sibling to the B&W RED
                  reference, difference the renderings, score cross-variant
                  persistence for the candidates found in step 4.
  3. **catalog**  ``build_catalog`` for the footprint so the adjudicator has
                  per-product solar geometry and pixel scale.
  4. **detect**   ``detect`` on the footprint's full-resolution browses —
                  the same terrain in every rendering, which is what makes
                  ``adjudicate``'s sibling/cross-band agreement meaningful.
  5. **mark / triage**  render the candidate overlays and review cards.
  6. **analyze**  per-candidate feature extraction + LLM verdict when
                  ``AI_LLM_KEY`` is set.
  7. **adjudicate** rank the candidates, apply the BH-FDR bar, write leads.
  8. **record**   write ``<out>/<footprint>/report.json`` and append one line
                  to ``<out>/index.jsonl``.

Order
-----
Branches in scientific priority (``extras_taxonomy.BRANCH_PRIORITY``:
RDR/ESP -> DTM/ESP -> RDR/PSP -> ... -> legacy EDR last), then orbit number,
then footprint name. The order is a pure function of the catalogue, so two
runs visit the same images in the same sequence.

Outputs
-------
::

    data/processed/extras_pass/
      index.jsonl            one JSON record per processed image (append-only)
      index.json             the same records as one array, for the dashboard
      state.json             progress + resume cursor
      <branch>/<footprint>/
        raw/                 downloaded variant set + _variant_manifest.json
        compare/             diffs, composite strip, compare_report.json
        detect/              candidates.csv
        analysis/            evaluated.csv, crops/, overviews/
        conclusions/         adjudicated.csv, leads.csv, report.html
        report.json          the consolidated per-image verdict

Usage
-----
::

    # see the plan without touching the network
    python scripts/extras_pass.py --plan

    # a bounded trial: 3 footprints, full pipeline each
    python scripts/extras_pass.py --limit 3

    # the whole site, in the background, resumeable
    python scripts/extras_pass.py --out data/processed/extras_pass

    # stop cleanly when the disk drops below 150 GB free
    python scripts/extras_pass.py --disk-floor-gb 150
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "pipeline"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adjudicate  # noqa: E402
import analyze as analyze_mod  # noqa: E402
import build_catalog  # noqa: E402
import common  # noqa: E402
import detect as detect_mod  # noqa: E402
import extras_compare  # noqa: E402
import extras_taxonomy as tax  # noqa: E402
import mark as mark_mod  # noqa: E402
import triage as triage_mod  # noqa: E402

USER_AGENT = {"User-Agent": "nasa-investigation/1.0 (HiRISE-EXTRAS-only pass)"}

STATE_SCHEMA = "extras-pass-state/1"


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _enforce_extras(url: str) -> None:
    if not url.startswith(tax.EXTRAS_BASE):
        raise ValueError(f"EXTRAS-only policy: refusing non-EXTRAS URL {url!r}")


def free_gb(path: str = ".") -> float:
    """Free space on the volume holding ``path``, in GB."""
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return float("inf")


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iter_queue(catalogue: dict, branches: list[str] | None = None) -> list[dict]:
    """Flatten the catalogue into the ordered work queue.

    One item per footprint::

        {"branch", "branch_priority", "family", "shard", "orbit", "name",
         "url", "kind", "reference", "acquire_bytes",
         "files": [{"name", "url", "bytes"}]}

    Sorted by (branch priority, orbit, footprint name) so the pass is
    reproducible and the Mars-orbiting sequence reads in time order.
    """
    want = set(branches) if branches else None
    items: list[dict] = []
    for br in catalogue.get("branches", []):
        if want and br["name"] not in want:
            continue
        for shard in br.get("shards", []):
            for fp in shard.get("footprints", []):
                files = [p for p in fp.get("products", []) if p.get("acquire")]
                if not files:
                    continue
                items.append(
                    {
                        "branch": br["name"],
                        "branch_priority": br.get("priority", 99),
                        "family": br.get("product_family", ""),
                        "instrument": br.get("instrument", ""),
                        "shard": shard.get("name", ""),
                        "orbit": fp.get("orbit") or 0,
                        "name": fp["name"],
                        "url": fp["url"],
                        "kind": fp.get("kind", ""),
                        "observations": fp.get("observations", []),
                        "reference": fp.get("reference"),
                        "product_count": fp.get("product_count", 0),
                        "acquire_count": len(files),
                        "acquire_bytes": sum(int(p.get("bytes") or 0) for p in files),
                        "files": files,
                    }
                )
    items.sort(key=lambda it: (it["branch_priority"], it["orbit"], it["shard"], it["name"]))
    return items


def item_key(item: dict) -> str:
    """Stable identity for a footprint in the pass index."""
    return f"{item['branch']}/{item['name']}"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_file(url: str, dest: str, attempts: int = 3, timeout: int = 300) -> tuple[str, str]:
    """Fetch one EXTRAS product. Returns ``(status, error)``.

    An existing non-empty file is kept as-is (``exists``) — the pass is
    resumable, so re-running must not re-download the archive.
    """
    _enforce_extras(url)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "exists", ""
    tmp = dest + ".part"
    last = ""
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, dest)
            return "downloaded", ""
        except Exception as e:  # noqa: BLE001
            last = str(e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            time.sleep(2.0 * (attempt + 1))
    return "error", last


def acquire_footprint(item: dict, raw_dir: str, workers: int, manifest: str) -> dict:
    """Download one footprint's variant set and write its provenance records."""
    os.makedirs(raw_dir, exist_ok=True)
    results: list[dict] = []
    tasks = [(p["url"], os.path.join(raw_dir, p["name"]), int(p.get("bytes") or 0)) for p in item["files"]]

    def work(task):
        url, dest, expected = task
        status, err = download_file(url, dest)
        if status == "exists" and expected and os.path.getsize(dest) != expected:
            status, err = "error", f"size {os.path.getsize(dest)} != catalogue {expected}"
        return url, dest, status, err

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, dest, status, err in ex.map(work, tasks):
            nbytes = os.path.getsize(dest) if os.path.exists(dest) else 0
            rec = {
                "url": url,
                "file": dest,
                "name": os.path.basename(dest),
                "bytes": nbytes,
                "status": status,
                "error": err,
                "sha256": common.sha256_file(dest) if nbytes else "",
            }
            results.append(rec)
            if nbytes and status != "error":
                # Append-only provenance, same schema as download_hirise_extras.py
                with open(manifest, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "url": url,
                                "file": os.path.abspath(dest),
                                "sha256": rec["sha256"],
                                "bytes": nbytes,
                                "source": "hirise_extras",
                                "branch": item["branch"],
                                "footprint": item["name"],
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )

    ok = [r for r in results if r["status"] != "error"]
    variant_manifest = {
        "footprint": item["name"],
        "branch": item["branch"],
        "source_url": item["url"],
        "reference": item["reference"],
        "retrieved": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": sorted(results, key=lambda r: r["name"]),
        "acquired": len(ok),
        "failed": len(results) - len(ok),
        "bytes": sum(r["bytes"] for r in results),
    }
    common.atomic_text_write(
        os.path.join(raw_dir, "_variant_manifest.json"), json.dumps(variant_manifest, indent=2)
    )
    return variant_manifest


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _run(label: str, fn, argv: list[str], errors: list[str], timing: dict | None = None) -> tuple[object, str]:
    """Call a pipeline stage's ``main(argv)`` in-process, capturing failures.

    Running the stages as function calls (rather than subprocesses) matters
    at this scale: the pass invokes them tens of thousands of times, and a
    fresh interpreter per stage would dominate the runtime.
    """
    t0 = time.time()
    try:
        out = fn(argv)
        err = ""
    except SystemExit as e:
        code = e.code or 0
        out = None
        if code:
            err = f"exit {code}"
            errors.append(f"{label}: exit {code}")
    except Exception as e:  # noqa: BLE001
        out = None
        err = f"{type(e).__name__}: {e}"
        errors.append(f"{label}: {err}")
        common.log("warn", f"{label}: {err}")
    if timing is not None:
        timing[label] = round(time.time() - t0, 1)
    return out, err


PARENT_GEOM_FIELDS = (
    "incidence_angle", "emission_angle", "phase_angle",
    "solar_azimuth", "solar_elevation", "observation_id", "start_time",
)


def apply_parent_geometry(catalog_csv: str, pgeom: dict) -> int:
    """Stamp a stereo pair's products with their source observation's lighting.

    Every product in a DTM footprint — the elevation derivatives and both
    orthorectified images — images the same ground during the same pair of
    acquisitions, so one lighting record applies to all of them.

    ``pixel_scale_m`` is intentionally not in the field list: these products
    live on the DTM's grid (1 m post for the exemplar), not on the parent's
    map-projected browse grid (0.5 m), and overwriting it would corrupt the
    ground-size and shadow-height calculations.
    """
    rows = _read_csv(catalog_csv)
    if not rows or not os.path.exists(catalog_csv):
        return 0
    with open(catalog_csv, newline="", encoding="utf-8") as f:
        fields = list(csv.DictReader(f).fieldnames or [])
    if not fields:
        return 0
    filled = 0
    for r in rows:
        for k in PARENT_GEOM_FIELDS:
            if k in fields and pgeom.get(k) and not r.get(k):
                r[k] = pgeom[k]
                filled += 1
    if filled:
        common.atomic_csv_write(catalog_csv, rows, fields)
    return filled


def parent_solar_geometry(out_root: str, obs_ids: list[str]) -> tuple[dict, list[str]]:
    """Solar geometry for a stereo pair, borrowed from its source observations.

    A DTM and its orthorectified image carry no solar geometry of their own —
    the pair's README documents the grid, the RMS and the elevation range, but
    not the lighting. The lighting belongs to the RDR observation the DTM was
    built from, and that observation lives in a *different* footprint
    directory (and a different branch) from the stereo pair.

    Branch priority puts RDR/ESP (0) ahead of DTM/ESP (1), so by the time the
    pass reaches a stereo pair its source observations have normally already
    been catalogued. This looks them up on disk rather than holding state.

    Returns ``(geometry, missing_observation_ids)``.
    """
    if not obs_ids:
        return {}, []
    root = os.path.abspath(out_root)
    found: dict = {}
    missing: list[str] = []
    for obs in obs_ids:
        instrument = tax.instrument_of(obs)
        candidates = [
            os.path.join(root, "RDR", instrument, obs, "catalog.csv"),
            os.path.join(root, "RDR", "ESP", obs, "catalog.csv"),
            os.path.join(root, "RDR", "PSP", obs, "catalog.csv"),
            os.path.join(root, "RDR", "TRA", obs, "catalog.csv"),
        ]
        rows: list[dict] = []
        for cand in candidates:
            if os.path.exists(cand):
                rows = _read_csv(cand)
                if rows:
                    break
        if not rows:
            missing.append(obs)
            continue
        for r in rows:
            if r.get("incidence_angle") and not found.get("incidence_angle"):
                for k in ("incidence_angle", "emission_angle", "phase_angle",
                          "solar_azimuth", "solar_elevation", "pixel_scale_m",
                          "observation_id", "target", "instrument", "start_time"):
                    if r.get(k):
                        found[k] = r[k]
                break
    if found:
        found["geometry_source"] = "parent RDR observation"
    return found, missing


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


#: Acquisition-level geometry: identical for every rendering of a footprint
#: because they all come from the same observation, taken in the same pass,
#: under the same lighting. Safe to copy from a labelled sibling onto a
#: product that ships no label of its own.
GEOM_FIELDS = (
    "observation_id", "target", "instrument", "start_time",
    "incidence_angle", "emission_angle", "phase_angle",
    "solar_azimuth", "solar_elevation", "spacecraft_altitude_km",
)

#: Fields that are a property of the *rendering*, not of the observation, so
#: they may only be copied between products that share a geometry class and a
#: render scale with the source.
SCALE_FIELDS = ("pixel_scale_m",)


def _rendering_profile(products: list[dict] | None) -> dict[str, tuple[str, str]]:
    """basename -> (geometry, scale) for one footprint, from the catalogue."""
    out: dict[str, tuple[str, str]] = {}
    for p in products or []:
        name = p.get("name")
        if name:
            out[name] = (p.get("geometry", ""), p.get("scale", ""))
    return out


def propagate_geometry(catalog_csv: str, footprint: str, products: list[dict] | None = None) -> int:
    """Copy observation-level geometry onto products that have no label of their own.

    The EXTRAS archive only ships PDS labels for *some* renderings of an
    observation (MIRB and MRGB), while the B&W RED browse — the reference the
    detector actually finds candidates in — has none. But every rendering of
    a footprint is the same observation acquired in the same pass, so they
    share one lighting geometry. Without this, every candidate found on the
    RED reference would reach the adjudicator with a blank incidence angle
    and solar azimuth, which are the two fields METHODOLOGY.md calls the
    primary explanation for apparent between-pass differences.

    Pixel scale is handled separately and much more carefully. Ground scale is
    a property of the *rendering*, not of the observation:

      * a ``*_NOMAP`` product keeps native detector resolution, so its scale
        differs from the map-projected browse;
      * a ``.thumb.jpg`` is a downsampled copy, so its scale differs again;
      * the map-projected ``*_RED.browse.jpg`` sits on exactly the same grid
        as the labelled map-projected ``*_MIRB.browse.jpg``.

    So scale is copied **only** to products whose (geometry, scale) class
    matches the source. Copying 0.5 m/px onto a thumbnail or a NOMAP product
    would make the adjudicator convert a shadow into a physical height using
    the wrong scale, which is worse than having no scale at all.

    Returns the number of fields filled in.
    """
    if not os.path.exists(catalog_csv):
        return 0
    with open(catalog_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        return 0

    # A single source of truth per observation, taken from the first row that
    # actually carries incidence + solar azimuth.
    fillable = [k for k in GEOM_FIELDS if k in fields and k != "observation_id"]

    def obs_key(r: dict) -> str:
        """Which observation does this row belong to?

        Rows that ship a PDS label carry ``observation_id``; the ones that do
        not — the B&W RED reference, the COLOR composites — have it blank, so
        matching on that field alone silently skips exactly the rows this
        function exists to repair. The observation id is recoverable from the
        EXTRAS product name, which always embeds it.
        """
        if r.get("observation_id"):
            return r["observation_id"]
        for key in ("name", "path"):
            toks = tax.observations_in(os.path.basename(r.get(key, "")))
            if toks:
                return toks[0]
        return ""

    truth: dict[str, dict] = {}
    for r in rows:
        obs = obs_key(r)
        if not obs or r.get("incidence_angle") in ("", None):
            continue
        truth.setdefault(obs, {k: r.get(k, "") for k in fillable})

    # Pixel scale needs a per-rendering decision, so track where each value
    # came from alongside its (geometry, scale) class.
    profile = _rendering_profile(products)
    scale_truth: dict[tuple[str, str, str], str] = {}
    for r in rows:
        prof = profile.get(r.get("name", ""))
        if not prof:
            continue
        val = r.get("pixel_scale_m") or ""
        if val:
            scale_truth.setdefault((obs_key(r), prof[0], prof[1]), val)

    filled = 0
    for r in rows:
        key = obs_key(r)
        src = truth.get(key)
        if src:
            for k, v in src.items():
                if v and not r.get(k):
                    r[k] = v
                    filled += 1
            if key and not r.get("observation_id"):
                r["observation_id"] = key
        # scale: only onto an identical rendering class
        if "pixel_scale_m" in fields and not r.get("pixel_scale_m"):
            prof = profile.get(r.get("name", ""))
            if prof:
                val = scale_truth.get((key, prof[0], prof[1]), "")
                if val:
                    r["pixel_scale_m"] = val
                    filled += 1

    # Correct the scale of downsampled renderings *before* writing, otherwise
    # the fix only ever lands in memory and the CSV keeps the wrong value.
    n_scale = correct_downsampled_scale(rows, fields, profile)
    if filled or n_scale:
        common.atomic_csv_write(catalog_csv, rows, fields)
    return filled + n_scale


def correct_downsampled_scale(rows: list[dict], fields: list[str],
                              profile: dict[str, tuple[str, str]]) -> int:
    """Fix the pixel scale of downsampled renderings, in place.

    ``metadata._find_label`` deliberately strips a render-scale token when
    looking for the sibling label, which is what makes provenance work for
    ``*_MIRB.browse.jpg`` -> ``*_MIRB.LBL``. The side effect is that a
    ``.thumb.jpg`` also resolves to that label and inherits its
    ``MAP_SCALE`` verbatim — reporting a thumbnail as 0.5 m/px when it is
    really several times coarser. A wrong scale is worse than no scale,
    because the adjudicator multiplies shadow length by it to infer a
    physical height.

    The downsample factor is taken from the actual pixel widths rather than
    guessed from the filename: scale_corrected = scale_map_projected x
    (full-res width / this image's width). Returns the number of rows fixed.
    """
    if "pixel_scale_m" not in fields or "width" not in fields:
        return 0
    # The finest map-projected browse is the full-resolution product the
    # label describes; everything wider than nothing but coarser than it.
    widths = {}
    for r in rows:
        try:
            wpx = int(r.get("width") or 0)
        except (TypeError, ValueError):
            continue
        prof = profile.get(r.get("name", ""))
        if wpx and prof and prof[0] in ("map", "ortho", "dtm"):
            widths.setdefault(r["name"], wpx)
    if not widths:
        return 0
    full_res = max(widths.values())

    fixed = 0
    for r in rows:
        try:
            wpx = int(r.get("width") or 0)
            base = float(r.get("pixel_scale_m") or 0)
        except (TypeError, ValueError):
            continue
        if not wpx or base <= 0 or wpx >= full_res:
            continue
        r["pixel_scale_m"] = round(base * full_res / float(wpx), 4)
        fixed += 1
    return fixed


def is_done(item: dict, out_root: str) -> bool:
    """Has this footprint already completed successfully?

    Derived from the per-image ``report.json`` on disk rather than from an
    in-memory done-map, so the state file stays a small fixed size no matter
    how many tens of thousands of images the pass walks. A footprint whose
    last run only *partially* succeeded is deliberately not "done" — the
    next run retries it.
    """
    path = os.path.join(out_root, *item_key(item).split("/"), "report.json")
    if not os.path.exists(path):
        return False
    try:
        return load_json(path).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def process_footprint(item: dict, args, out_root: str, manifest: str) -> dict:
    """Run the full pipeline over one footprint and return its record."""
    key = item_key(item)
    work = os.path.join(out_root, *key.split("/"))
    # Name the leaf directory after the footprint itself: extras_compare
    # derives its output subdirectory from footprint_dir.name, and a leaf
    # directory literally called "raw" would put every footprint's diff maps
    # under a directory named after nothing.
    raw = os.path.join(work, "raw", item["name"])
    compare_dir = os.path.join(work, "compare")
    detect_dir = os.path.join(work, "detect")
    analysis_dir = os.path.join(work, "analysis")
    concl_dir = os.path.join(work, "conclusions")
    catalog_csv = os.path.join(work, "catalog.csv")
    errors: list[str] = []
    timing: dict[str, float] = {}
    t0 = time.time()

    for d in (raw, compare_dir, detect_dir, analysis_dir, concl_dir):
        os.makedirs(d, exist_ok=True)

    # 1. acquire the complete browse variant set for this footprint
    t_dl = time.time()
    vm = acquire_footprint(item, raw, args.file_workers, manifest)
    timing["download"] = round(time.time() - t_dl, 1)
    acquired = [f for f in vm["files"] if f["status"] != "error"]
    if not acquired:
        return {
            "key": key, "schema": "extras-pass-record/1", "branch": item["branch"],
            "footprint": item["name"], "orbit": item["orbit"], "shard": item["shard"],
            "status": "download-failed", "errors": vm["files"],
            "elapsed_s": round(time.time() - t0, 1),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # 2. per-product hashes + solar geometry for the adjudicator
    _run("build_catalog", build_catalog.main, ["--root", raw, "--out", catalog_csv], errors, timing)
    n_geom = propagate_geometry(catalog_csv, item["name"], item.get("files"))

    # A stereo pair has no solar geometry of its own; borrow the lighting of
    # the RDR observations it was built from. Deliberately *not* pixel scale:
    # the DTM's 1 m post spacing is the truth for these products, and the
    # parent's 0.5 m map-projected browse scale is a different grid.
    parent_state = "n/a"
    if item.get("kind") == "stereo_pair":
        obs_ids = [o for o in item.get("observations", []) if o]
        pgeom, pmissing = parent_solar_geometry(out_root, obs_ids)
        n_parent = 0
        if pgeom:
            n_parent = apply_parent_geometry(catalog_csv, pgeom)
            parent_state = "joined:" + ",".join(obs_ids)
        elif obs_ids:
            parent_state = "unavailable:" + ",".join(pmissing)
        n_geom += n_parent

    # 3. detect on this footprint's full-resolution browses.
    #    DTM/ortho products are named `...ORTHO.br.jpg` / `DTEEC_....ab.jpg`,
    #    so the extension list has to cover those too or stereo-pair
    #    footprints would silently scan zero images.
    detect_argv = [
        "--dir", raw, "--out", detect_dir,
        "--exts", ".browse.jpg,.browse.png,.br.jpg,.ab.jpg",
        "--scales", args.detect_scales,
        "--z", str(args.detect_z),
        "--min-size", str(args.detect_min_size),
    ]
    if args.detect_scope == "reference" and item.get("reference"):
        # The B&W RED browse is the least-processed rendering, so it is the
        # honest place to look for candidates; cross-variant persistence is
        # then established in step 4 against every other rendering.
        detect_argv += ["--only", item["reference"]]
    _run("detect", detect_mod.main, detect_argv, errors, timing)
    cand_csv = os.path.join(detect_dir, "candidates.csv")
    candidates = _read_csv(cand_csv)

    # 4. cross-variant comparison, scored against the candidates just found:
    #    B&W RED vs filtered colour vs orthorectified vs DTM-shaded.
    compare_report = {}
    if acquired:
        try:
            compare_report = extras_compare.compare_footprint(
                Path(raw), candidates, Path(compare_dir),
                reference=item.get("reference"), diff_format=args.diff_format,
            ) or {}
        except Exception as e:  # noqa: BLE001
            errors.append(f"extras_compare: {type(e).__name__}: {e}")
            common.log("warn", errors[-1])
    cmp_json = os.path.join(compare_dir, item["name"], "compare_report.json")

    # 5. overlays + review cards
    if candidates:
        _run("mark", mark_mod.main, ["--candidates", cand_csv, "--out", os.path.join(work, "marked")], errors, timing)
        _run(
            "triage", triage_mod.main,
            ["--candidates", cand_csv, "--out", os.path.join(work, "cards"), "--thumb-size", "640"],
            errors, timing,
        )

    # 6. analyze
    _run(
        "analyze", analyze_mod.main,
        ["--candidates", cand_csv, "--out", analysis_dir] + (["--llm"] if args.llm else []),
        errors, timing,
    )
    evaluated = _read_csv(os.path.join(analysis_dir, "evaluated.csv"))

    # 7. adjudicate. The compare report is handed in so the adjudicator can
    #    reach a cross-rendering verdict: with reference-only detection there
    #    are no sibling *detections*, so `agrees` would otherwise always be 0
    #    and no candidate could ever be confirmed or refuted across variants.
    _run(
        "adjudicate", adjudicate.main,
        [
            "--candidates", cand_csv,
            "--evaluated", os.path.join(analysis_dir, "evaluated.csv"),
            "--out", concl_dir,
            "--metadata", catalog_csv,
            "--persistence", cmp_json if os.path.exists(cmp_json) else "",
            "--top", str(args.top),
        ],
        errors, timing,
    )
    leads = _read_csv(os.path.join(concl_dir, "leads.csv"))
    adjudicated = _read_csv(os.path.join(concl_dir, "adjudicated.csv"))
    band_dep = _read_csv(os.path.join(concl_dir, "band_dependent.csv"))

    # Verdict breakdown, so a per-image record says *why* it looks the way it
    # does rather than just how many candidates it produced.
    verdicts_tally: dict[str, int] = {}
    for r in adjudicated:
        v = r.get("verdict", "") or "(blank)"
        verdicts_tally[v] = verdicts_tally.get(v, 0) + 1

    # 8. record
    variants = compare_report.get("variants", []) if isinstance(compare_report, dict) else []
    verdicts: dict[str, int] = {}
    for v in variants:
        if isinstance(v, dict) and v.get("verdict"):
            verdicts[v["verdict"]] = verdicts.get(v["verdict"], 0) + 1

    record = {
        "key": key,
        "schema": "extras-pass-record/1",
        "branch": item["branch"],
        "family": item["family"],
        "instrument": item["instrument"],
        "shard": item["shard"],
        "orbit": item["orbit"],
        "footprint": item["name"],
        "kind": item["kind"],
        "url": item["url"],
        "reference": item["reference"],
        "status": "ok" if not errors else "partial",
        "products": {"catalogue": item["product_count"], "acquired": len(acquired), "failed": vm["failed"]},
        "bytes": vm["bytes"],
        "geometry_filled": n_geom,
        "parent_geometry": parent_state,
        "compare": {
            "compared": compare_report.get("summary", {}).get("compared", 0) if isinstance(compare_report, dict) else 0,
            "verdicts": verdicts,
            "report": os.path.relpath(cmp_json, out_root) if os.path.exists(cmp_json) else "",
        },
        "candidates": len(candidates),
        "evaluated": len(evaluated),
        "adjudicated": len(adjudicated),
        "verdicts": verdicts_tally,
        "band_dependent": len(band_dep),
        "leads": len(leads),
        "top_leads": [
            {k: v for k, v in lead.items() if k in ("image", "x", "y", "w", "h", "score", "verdict", "claim", "persistence", "notes")}
            for lead in leads[:5]
        ],
        "errors": errors,
        "stage_seconds": timing,
        "elapsed_s": round(time.time() - t0, 1),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    common.atomic_text_write(os.path.join(work, "report.json"), json.dumps(record, indent=2))
    return record


# ---------------------------------------------------------------------------
# Progress state
# ---------------------------------------------------------------------------


#: How many recent images the throughput estimate is based on. A lifetime
#: average is misleading here because a --force reprocess skips the download
#: stage entirely, so a run that re-adjudicates already-fetched images can
#: report >100 images/min while a fresh image genuinely takes ~40 s. A short
#: trailing window reflects the current mix of work instead.
RATE_WINDOW = 50


def load_state(path: str) -> dict:
    if os.path.exists(path):
        try:
            return load_json(path)
        except Exception:  # noqa: BLE001
            pass
    return {
        "schema": STATE_SCHEMA,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "processed": 0,
        "ok": 0,
        "partial": 0,
        "failed": 0,
        "candidates": 0,
        "evaluated": 0,
        "leads": 0,
        "bytes": 0,
        "elapsed_s": 0.0,
        "download_s": 0.0,
        "analysis_s": 0.0,
        "last_key": "",
        # trailing window of (total_s, download_s) for honest throughput
        "recent": [],
    }


def note_timing(state: dict, total_s: float, download_s: float) -> None:
    """Record one image's cost into the trailing throughput window."""
    win = state.setdefault("recent", [])
    win.append([round(float(total_s), 2), round(float(download_s), 2)])
    if len(win) > RATE_WINDOW:
        del win[: len(win) - RATE_WINDOW]


def save_state(path: str, state: dict, total: int, out_root: str) -> None:
    """Write a fixed-size progress file. Counters only — never a growing map."""
    done = state["processed"]
    state["total"] = total
    state["remaining"] = max(0, total - done)
    state["pct"] = round(100.0 * done / total, 2) if total else 0.0
    state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Trailing-window throughput: this is what the ETA must be based on.
    win = state.get("recent") or []
    n = len(win)
    if n:
        w_total = sum(w[0] for w in win)
        w_dl = sum(w[1] for w in win)
        rate = n / max(w_total, 1e-6)  # images per second
        state["window_images"] = n
        state["sec_per_image"] = round(w_total / n, 1)
        state["download_share_pct"] = round(100.0 * w_dl / max(w_total, 1e-6), 1)
        state["images_per_min"] = round(rate * 60.0, 2)
        state["eta_hours"] = round((total - done) / rate / 3600.0, 1) if rate > 0 else None
    # Lifetime figures, kept separate so a reprocess sweep cannot masquerade
    # as progress on the remaining queue.
    life = state["processed"] / max(state.get("elapsed_s", 0.0), 1e-6)
    state["lifetime_images_per_min"] = round(life * 60.0, 2)
    state["download_s"] = round(state.get("download_s", 0.0), 1)
    state["analysis_s"] = round(state.get("analysis_s", 0.0), 1)
    state["free_gb"] = round(free_gb(out_root), 1)
    # keep the persisted state small
    if len(state.get("recent") or []) > RATE_WINDOW:
        state["recent"] = state["recent"][-RATE_WINDOW:]
    common.atomic_text_write(path, json.dumps(state, indent=2))


def append_index(path: str, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def rewrite_index_jsonl(jsonl_path: str, json_path: str) -> int:
    """Collapse the append-only index into a single JSON array."""
    if not os.path.exists(jsonl_path):
        return 0
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    common.atomic_text_write(json_path, json.dumps(rows, indent=1))
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Systematic one-image-at-a-time pass over the HiRISE EXTRAS catalogue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--catalogue", default="data/catalog/extras_site.json", help="site catalogue JSON")
    p.add_argument("--out", default="data/processed/extras_pass", help="per-image output root")
    p.add_argument("--manifest", default="data/raw/manifest.jsonl", help="provenance JSONL (appended)")
    p.add_argument("--branches", default="", help="comma-separated branch filter")
    p.add_argument("--limit", type=int, default=0, help="stop after N footprints this run (0 = no limit)")
    p.add_argument("--max-hours", type=float, default=0.0, help="stop cleanly after this many hours")
    p.add_argument("--disk-floor-gb", type=float, default=100.0, help="stop cleanly below this much free disk")
    p.add_argument("--file-workers", type=int, default=4, help="parallel downloads within one footprint")
    p.add_argument(
        "--detect-scope",
        default="reference",
        choices=("reference", "all"),
        help=(
            "reference = detect only on the footprint's B&W RED browse, the "
            "least-processed rendering (default); all = also detect on every "
            "other rendering, which roughly multiplies detect time by the "
            "number of variants"
        ),
    )
    p.add_argument("--detect-scales", default="4", help="detect.py downsample factors")
    p.add_argument("--detect-z", type=float, default=3.0, help="detect.py z threshold")
    p.add_argument("--detect-min-size", type=int, default=12, help="detect.py min blob area")
    p.add_argument("--top", type=int, default=5, help="leads kept per image")
    p.add_argument(
        "--diff-format",
        default="jpeg",
        choices=("jpeg", "png", "none"),
        help=(
            "difference-map format per variant. jpeg (default) is ~25x "
            "smaller than png here and loses nothing for review; the "
            "quantitative scores are in compare_report.json either way"
        ),
    )
    p.add_argument(
        "--checkpoint-every",
        type=float,
        default=60.0,
        help="rebuild index.json at most every N seconds (0 = only at the end)",
    )
    p.add_argument("--llm", action="store_true", help="ask the vision LLM (needs AI_LLM_KEY)")
    p.add_argument("--plan", action="store_true", help="print the work plan and exit; no network")
    p.add_argument("--status", action="store_true", help="print progress from the state file and exit")
    p.add_argument("--force", action="store_true", help="reprocess footprints already marked done")
    p.add_argument("--refresh-index", action="store_true", help="rebuild index.json from index.jsonl and exit")
    args = p.parse_args(argv)

    out_root = os.path.abspath(args.out)
    os.makedirs(out_root, exist_ok=True)
    state_path = os.path.join(out_root, "state.json")
    index_jsonl = os.path.join(out_root, "index.jsonl")
    index_json = os.path.join(out_root, "index.json")

    if args.refresh_index:
        n = rewrite_index_jsonl(index_jsonl, index_json)
        common.log("info", f"rebuilt {index_json} from {n} records")
        return 0

    state = load_state(state_path)
    if args.status:
        total = state.get("total") or 0
        done = state.get("processed") or 0
        common.log("info", f"processed {done}/{total} ({state.get('pct', 0)}%)  "
                           f"ok={state.get('ok', 0)} partial={state.get('partial', 0)} failed={state.get('failed', 0)}")
        common.log("info", f"candidates={state.get('candidates', 0)} leads={state.get('leads', 0)} "
                           f"bytes={round((state.get('bytes') or 0)/1e9, 2)} GB free={state.get('free_gb')} GB")
        if state.get("window_images"):
            common.log(
                "info",
                f"recent {state['window_images']} images: {state.get('sec_per_image')} s/image "
                f"({state.get('download_share_pct')}% of it download), "
                f"{state.get('images_per_min')} img/min",
            )
            common.log(
                "info",
                f"eta={state.get('eta_hours')} h at the recent rate "
                f"(lifetime average {state.get('lifetime_images_per_min')} img/min, "
                f"not comparable after a --force reprocess)",
            )
        common.log("info", f"cumulative: download {round((state.get('download_s') or 0)/3600, 2)} h, "
                           f"analysis {round((state.get('analysis_s') or 0)/3600, 2)} h")
        return 0

    if not os.path.exists(args.catalogue):
        common.log("error", f"no catalogue at {args.catalogue} — run scripts/catalog_extras_site.py first")
        return 2

    catalogue = load_json(args.catalogue)
    branches = [b.strip() for b in args.branches.split(",") if b.strip()] or None
    queue = iter_queue(catalogue, branches)
    if not queue:
        common.log("error", "catalogue contains no footprints with fetchable products")
        return 2

    if args.plan:
        total_bytes = sum(it["acquire_bytes"] for it in queue)
        per_branch: dict[str, dict] = {}
        for it in queue:
            b = per_branch.setdefault(it["branch"], {"n": 0, "bytes": 0, "files": 0, "priority": it["branch_priority"]})
            b["n"] += 1
            b["bytes"] += it["acquire_bytes"]
            b["files"] += it["acquire_count"]
        common.log("info", f"catalogue: {len(catalogue.get('branches', []))} branches, {len(queue)} footprints queued")
        common.log("info", f"browse-only acquisition: {sum(it['acquire_count'] for it in queue)} files / "
                           f"{total_bytes/1e9:.1f} GB")
        common.log("info", "order:")
        for name, b in sorted(per_branch.items(), key=lambda kv: kv[1]["priority"]):
            common.log("info", f"  [{b['priority']:2d}] {name:14s} {b['n']:7d} images  "
                               f"{b['files']:8d} files  {b['bytes']/1e9:8.2f} GB")

        # A full-site acquisition does not fit on one volume: report how far
        # the priority order actually gets before the disk floor, rather than
        # discovering it hours later.
        avail = free_gb(out_root) - args.disk_floor_gb
        common.log("info", f"disk: {free_gb(out_root):.0f} GB free, floor {args.disk_floor_gb} GB "
                           f"-> {max(avail, 0):.0f} GB usable for downloads")
        if total_bytes / 1e9 > max(avail, 0):
            used = 0.0
            covered = 0
            cutoff = None
            for name, b in sorted(per_branch.items(), key=lambda kv: kv[1]["priority"]):
                if used + b["bytes"] / 1e9 > max(avail, 0):
                    cutoff = name
                    break
                used += b["bytes"] / 1e9
                covered += b["n"]
            common.log("info", f"!! the whole site ({total_bytes/1e9:.0f} GB) does NOT fit; "
                               f"the pass covers {covered}/{len(queue)} images "
                               f"({used:.0f} GB) and stops at branch {cutoff!r}")
            common.log("info", "   use --scales thumb at catalogue time for a cheap full-site index pass, "
                               "or raise --disk-floor-gb / add a volume")
        else:
            common.log("info", f"the whole site fits: {total_bytes/1e9:.0f} GB needed, "
                               f"{max(avail, 0):.0f} GB usable")
        common.log("info", f"first 10 images: {[it['name'] for it in queue[:10]]}")
        common.log("info", f"last 3 images:   {[it['name'] for it in queue[-3:]]}")
        return 0

    # Resume is derived from the per-image report.json on disk, not from an
    # in-memory done-map, so the state file stays small at any scale.
    if args.force:
        pending = list(queue)
    else:
        pending = [it for it in queue if not is_done(it, out_root)]
    already = len(queue) - len(pending)
    if already:
        common.log("info", f"resuming: {already} of {len(queue)} footprints already complete, {len(pending)} to go")

    os.makedirs(os.path.dirname(os.path.abspath(args.manifest)), exist_ok=True)
    common.set_audit(os.path.join(out_root, "audit.jsonl"))
    common.audit({"event": "extras_pass_start", "catalogue": args.catalogue, "pending": len(pending), "argv": sys.argv[1:]})

    t0 = time.time()
    state["elapsed_s"] = state.get("elapsed_s", 0.0)
    state["run_started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["run_images"] = 0
    processed_this_run = 0
    stop_reason = "queue-exhausted"
    last_save = time.time()

    for idx, item in enumerate(pending, 1):
        if args.limit and processed_this_run >= args.limit:
            stop_reason = f"--limit {args.limit}"
            break
        if args.max_hours and (time.time() - t0) / 3600.0 >= args.max_hours:
            stop_reason = f"--max-hours {args.max_hours}"
            break
        if free_gb(out_root) < args.disk_floor_gb:
            stop_reason = f"disk floor {args.disk_floor_gb} GB reached"
            common.log("warn", stop_reason + " — stopping cleanly, rerun to resume")
            break

        try:
            rec = process_footprint(item, args, out_root, args.manifest)
        except Exception as e:  # noqa: BLE001
            common.log("error", f"{item['name']}: {type(e).__name__}: {e}")
            common.log("debug", traceback.format_exc())
            rec = {
                "key": item_key(item), "schema": "extras-pass-record/1", "branch": item["branch"],
                "footprint": item["name"], "orbit": item["orbit"], "shard": item["shard"],
                "status": "error", "errors": [f"{type(e).__name__}: {e}"],
                "traceback": traceback.format_exc()[-2000:],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        append_index(index_jsonl, rec)
        state["processed"] = (state.get("processed") or 0) + 1
        state["last_key"] = rec["key"]
        status = rec.get("status", "error")
        bucket = status if status in ("ok", "partial") else "failed"
        state[bucket] = state.get(bucket, 0) + 1
        for f in ("candidates", "evaluated", "leads"):
            state[f] = (state.get(f) or 0) + (rec.get(f) or 0)
        state["bytes"] = (state.get("bytes") or 0) + (rec.get("bytes") or 0)
        spent = rec.get("elapsed_s", 0.0)
        dl = (rec.get("stage_seconds") or {}).get("download", 0.0)
        state["elapsed_s"] = round(state.get("elapsed_s", 0.0) + spent, 1)
        state["download_s"] = round(state.get("download_s", 0.0) + dl, 1)
        state["analysis_s"] = round(state.get("analysis_s", 0.0) + (spent - dl), 1)
        note_timing(state, spent, dl)
        processed_this_run += 1

        if idx % 1 == 0:
            save_state(state_path, state, len(queue), out_root)
            common.log(
                "info",
                f"[{state['processed']}/{len(queue)}] {rec['key']:44s} {status:12s} "
                f"files={rec.get('products', {}).get('acquired', 0):2d} "
                f"cand={rec.get('candidates', 0):3d} leads={rec.get('leads', 0):2d} "
                f"{rec.get('elapsed_s', 0):6.1f}s free={state['free_gb']}GB"
                + (f" verdicts={rec['verdicts']}" if rec.get("verdicts") else ""),
            )
            if args.checkpoint_every and time.time() - last_save > args.checkpoint_every:
                rewrite_index_jsonl(index_jsonl, index_json)
                last_save = time.time()

    state["stop_reason"] = stop_reason
    state["run_images"] = processed_this_run
    state["run_seconds"] = round(time.time() - t0, 1)
    state["elapsed_s"] = round(state.get("elapsed_s", 0.0), 1)
    save_state(state_path, state, len(queue), out_root)
    n_index = rewrite_index_jsonl(index_jsonl, index_json)
    common.log("info", f"stopped: {stop_reason}")
    common.log("info", f"this run: {processed_this_run} images, {state['processed']}/{len(queue)} total, "
                       f"ok={state['ok']} partial={state['partial']} failed={state['failed']}")
    common.log("info", f"index: {index_json} ({n_index} records), state: {state_path}")
    common.audit({"event": "extras_pass_stop", "stop_reason": stop_reason, "processed_this_run": processed_this_run})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
