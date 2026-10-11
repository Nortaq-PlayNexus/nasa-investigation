#!/usr/bin/env python3
"""
Build the full, organised HiRISE EXTRAS site catalogue (JSON)
=============================================================
Walks the *live* PDS index tree and writes one hierarchical JSON document
describing every footprint and every product in it, plus a flat CSV and a
machine-readable summary. No image bytes are fetched here — this is the
index pass that precedes acquisition.

    https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/
      RDR/<INSTR>/<ORB shard>/<OBS>/       RDR       browse sets (27 files)
      DTM/<INSTR>/<ORB shard>/<PAIR>/      DTM       DTM + ortho (16-19)
      ANAGLYPH/<INSTR>/<ORB shard>/<PAIR>/ ANAGLYPH  stereo anaglyph (3)
      EDR/<INSTR>/<ORB shard>/<OBS>/       EDR       legacy per-filter (56)

Tree shape verified by live probe: RDR/ESP 771 orbit shards, DTM/ESP 495,
ANAGLYPH/ESP 751, plus PSP/TRA/AEB branches and a legacy EDR tree. That is
~25k leaf directories, so the crawler is:

  * **resumable** — every directory listing is cached on disk under
    ``--cache`` keyed by a hash of its URL, so a re-run costs zero requests
    and an interrupted run continues where it stopped;
  * **bounded** — ``--branches`` / ``--shard-limit`` / ``--footprint-limit``
    keep a trial run cheap;
  * **ordered** — branches, then orbit shards, then footprints, all sorted,
    so the systematic acquisition pass has a stable total order to walk;
  * **EXTRAS-only** — every URL is checked against ``extras_taxonomy.EXTRAS_BASE``
    before it is requested.

Outputs
-------
``data/catalog/extras_site.json``       hierarchical catalogue (see SCHEMA below)
``data/catalog/extras_site.csv``        one row per product file
``data/catalog/extras_summary.json``    counts + byte budgets per branch

SCHEMA (``extras_site.json``)
-----------------------------
::

    {
      "schema": "hirise-extras-site/1",
      "generated": "2026-09-29T..Z",
      "base": "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/",
      "policy": {"max_fullres_mb": 0.0, "browse_only": true},
      "branches": [
        {"name": "RDR/ESP", "product_family": "RDR", "instrument": "ESP",
         "priority": 0, "url": "...", "shards": [
           {"name": "ORB_011200_011299", "url": "...", "orbit_from": 11200,
            "orbit_to": 11299, "footprints": [
              {"name": "ESP_011261_1960", "url": "...", "kind": "observation",
               "instrument": "ESP", "orbit": 11261, "target": 1960,
               "observations": ["ESP_011261_1960"],
               "reference": "ESP_011261_1960_RED.browse.jpg",
               "product_count": 27, "acquire_count": 18, "acquire_bytes": 12345678,
               "products": [
                 {"name": "...", "url": "...", "bytes": 260910907,
                  "modified": "15-Sep-2009 09:37", "product_class": "rdr_fullres",
                  "role": "color", "band": "COLOR", "scale": "fullres",
                  "geometry": "quicklook", "taxonomy": "...",
                  "acquire": false, "reason": "full-resolution JP2 excluded ..."}
               ]}
            ]}
         ]}
      ]
    }

Usage
-----
::

    # whole site (resumable; safe to re-run)
    python scripts/catalog_extras_site.py

    # one branch, one orbit shard — a fast trial
    python scripts/catalog_extras_site.py --branches RDR/ESP --shard-limit 1

    # what would a browse-only acquisition of a branch cost?
    python scripts/catalog_extras_site.py --branches RDR/ESP --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "pipeline"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common  # noqa: E402
import extras_taxonomy as tax  # noqa: E402

USER_AGENT = {"User-Agent": "nasa-investigation/1.0 (HiRISE-EXTRAS-only catalogue)"}

# Apache index row: <a href="NAME">NAME</a>   DD-Mon-YYYY HH:MM   <bytes>
ROW_RX = re.compile(
    r'<a href="(?P<name>[^"]+)">(?P<label>[^<]*)</a>\s+'
    r"(?P<mod>\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})"
    r"(?:\s+(?P<size>\d+))?"
)

SCHEMA = "hirise-extras-site/1"


# ---------------------------------------------------------------------------
# Adaptive throttle
# ---------------------------------------------------------------------------
#
# Measured behaviour of the PDS host (benchmark, 40 cold index requests):
#
#   1 worker   0.09 req/s   latency 10.7 s
#   8 workers  0.44 req/s   latency 18.0 s      <- still clean
#   24 workers 1.82 req/s   latency  0.7 s      <- 28/40 responses were HTTP 503
#   48 workers 2.00 req/s   latency  0.7 s      <- 30/40 responses were HTTP 503
#
# So the host serves one index request roughly every 10 s and starts refusing
# (503) beyond ~8 concurrent connections. Pushing concurrency buys apparent
# throughput made almost entirely of errors. The throttle below therefore
# treats a 503 as "we are over the limit right now" and makes every worker
# wait, which keeps the crawl inside the host's envelope instead of hammering
# it and burning the retry budget.

_THROTTLE_LOCK = threading.Lock()
_THROTTLE = {"delay": 0.0, "clean": 0, "throttled": 0, "errors": 0}
MIN_DELAY = 0.0
MAX_DELAY = 30.0


def _penalise() -> float:
    with _THROTTLE_LOCK:
        _THROTTLE["throttled"] += 1
        _THROTTLE["clean"] = 0
        _THROTTLE["delay"] = min(MAX_DELAY, (_THROTTLE["delay"] or 0.4) * 2.0)
        return _THROTTLE["delay"]


def _reward() -> None:
    with _THROTTLE_LOCK:
        _THROTTLE["clean"] += 1
        if _THROTTLE["clean"] >= 25 and _THROTTLE["delay"] > MIN_DELAY:
            _THROTTLE["delay"] = max(MIN_DELAY, _THROTTLE["delay"] / 2.0)
            _THROTTLE["clean"] = 0


def _sleep_turn() -> None:
    with _THROTTLE_LOCK:
        d = _THROTTLE["delay"]
    if d > 0:
        time.sleep(d + random.random() * d * 0.25)


def throttle_stats() -> dict:
    with _THROTTLE_LOCK:
        return {
            "delay_s": round(_THROTTLE["delay"], 2),
            "throttled_503": _THROTTLE["throttled"],
            "errors": _THROTTLE["errors"],
        }



# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------


def _enforce_extras(url: str) -> None:
    if not url.startswith(tax.EXTRAS_BASE):
        raise ValueError(f"EXTRAS-only policy: refusing non-EXTRAS URL {url!r}")


def _cache_path(cache_dir: str, url: str) -> str:
    return os.path.join(cache_dir, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")


def list_dir(url: str, cache_dir: str, refresh: bool = False, timeout: int = 120, attempts: int = 8) -> list[dict]:
    """Return the entries of an Apache index, cached on disk by URL hash.

    Each entry is ``{"name", "is_dir", "bytes", "modified"}``. A cached
    listing is reused unless ``refresh`` is set, which is what makes the
    crawl resumable and re-runnable for free.

    Retries are 503-aware: the host rate-limits with ``503 Service
    Temporarily Unavailable`` and each retry waits behind the shared
    :func:`_penalise` throttle, so a throttled crawl slows itself down
    instead of storming the archive.
    """
    _enforce_extras(url)
    cpath = _cache_path(cache_dir, url)
    if not refresh and os.path.exists(cpath):
        try:
            with open(cpath, encoding="utf-8") as f:
                return json.load(f)["entries"]
        except Exception:  # corrupt cache entry -> refetch
            pass

    last = ""
    for attempt in range(attempts):
        _sleep_turn()
        try:
            req = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", "ignore")
            _reward()
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                wait = _penalise()
            elif 400 <= e.code < 500:
                # 404 etc: retrying will not help
                with _THROTTLE_LOCK:
                    _THROTTLE["errors"] += 1
                raise RuntimeError(f"index fetch failed {url}: {last}") from e
            else:
                wait = _penalise()
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            wait = _penalise()
        time.sleep(min(60.0, wait * (1 + attempt)))
    else:
        with _THROTTLE_LOCK:
            _THROTTLE["errors"] += 1
        raise RuntimeError(f"index fetch failed {url} after {attempts} attempts: {last}")

    entries: list[dict] = []
    for m in ROW_RX.finditer(html):
        name = m.group("name")
        if name in ("../", "./", "/") or name.startswith("?"):
            continue
        size = m.group("size")
        entries.append(
            {
                "name": name,
                "is_dir": name.endswith("/"),
                "bytes": int(size) if size else 0,
                "modified": m.group("mod").strip(),
            }
        )
    common.atomic_text_write(
        cpath, json.dumps({"url": url, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "entries": entries})
    )
    return entries


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------


def crawl_branch(
    branch: str,
    family: str,
    instrument: str,
    cache_dir: str,
    workers: int,
    refresh: bool,
    shard_limit: int,
    footprint_limit: int,
    max_fullres_mb: float,
    scales: tuple[str, ...] = tax.DEFAULT_SCALES,
    geometries: tuple[str, ...] = tax.DEFAULT_GEOMETRIES,
    log_every: int = 25,
    on_progress=None,
) -> dict:
    """Crawl one ``<COLLECTION>/<INSTRUMENT>`` branch into a catalogue node."""
    branch_url = tax.EXTRAS_BASE + branch + "/"
    out = {
        "name": branch,
        "product_family": family,
        "instrument": instrument,
        "priority": tax.BRANCH_PRIORITY.get(branch, 99),
        "url": branch_url,
        "shard_count": 0,
        "footprint_count": 0,
        "product_count": 0,
        "acquire_count": 0,
        "acquire_bytes": 0,
        "errors": [],
        "shards": [],
    }

    try:
        shard_entries = list_dir(branch_url, cache_dir, refresh)
    except Exception as e:  # noqa: BLE001
        common.log("warn", f"{branch}: index failed ({e})")
        out["errors"].append({"url": branch_url, "error": str(e)})
        return out

    shards = sorted(
        e["name"].rstrip("/")
        for e in shard_entries
        if e["is_dir"] and tax.ORB_SHARD_RX.match(e["name"].rstrip("/"))
    )
    if shard_limit:
        shards = shards[:shard_limit]

    def _footprints(shard: str) -> list[dict]:
        shard_url = branch_url + shard + "/"
        try:
            kids = list_dir(shard_url, cache_dir, refresh)
        except Exception as e:  # noqa: BLE001
            common.log("warn", f"{branch}/{shard}: index failed ({e})")
            return []
        names = sorted(k["name"].rstrip("/") for k in kids if k["is_dir"])
        if footprint_limit:
            names = names[:footprint_limit]
        recs = []
        for name in names:
            try:
                files = list_dir(shard_url + name + "/", cache_dir, refresh)
            except Exception as e:  # noqa: BLE001
                common.log("warn", f"{branch}/{shard}/{name}: index failed ({e})")
                continue
            recs.append(build_footprint(name, shard_url + name + "/", files, branch, max_fullres_mb, scales, geometries))
        return recs

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for shard_name, recs in zip(shards, ex.map(_footprints, shards)):
            om = tax.ORB_SHARD_RX.match(shard_name)
            shard = {
                "name": shard_name,
                "url": branch_url + shard_name + "/",
                "orbit_from": int(om.group(1)) if om else None,
                "orbit_to": int(om.group(2)) if om else None,
                "footprints": recs,
            }
            out["shards"].append(shard)
            out["shard_count"] += 1
            out["footprint_count"] += len(recs)
            for fp in recs:
                out["product_count"] += fp["product_count"]
                out["acquire_count"] += fp["acquire_count"]
                out["acquire_bytes"] += fp["acquire_bytes"]
            done += 1
            if done % log_every == 0:
                common.log(
                    "info",
                    f"{branch}: {done}/{len(shards)} shards, "
                    f"{out['footprint_count']} footprints, "
                    f"{out['acquire_count']} files / {out['acquire_bytes']/1e6:.1f} MB to fetch",
                )
            # A full branch is thousands of listings over many hours, so hand
            # the partial node back for checkpointing: the catalogue on disk is
            # then always usable, never a single all-or-nothing write at the end.
            if on_progress is not None:
                on_progress(out)
    out["shards"].sort(key=lambda s: s["orbit_from"] if s["orbit_from"] is not None else 0)
    return out


def build_footprint(
    name: str,
    url: str,
    files: list[dict],
    branch: str,
    max_fullres_mb: float,
    scales: tuple[str, ...] = tax.DEFAULT_SCALES,
    geometries: tuple[str, ...] = tax.DEFAULT_GEOMETRIES,
) -> dict:
    """Turn one directory listing into a footprint catalogue record."""
    fp = tax.classify_footprint(name)
    primary = fp["observations"][0] if fp["observations"] else ""
    products = []
    for f in files:
        if f["is_dir"]:
            continue
        info = tax.classify_file(f["name"], branch)
        fetch, reason = tax.acquire_decision(info, max_fullres_mb, scales, geometries)
        products.append(
            {
                "name": f["name"],
                "url": url + f["name"],
                "bytes": int(f.get("bytes") or 0),
                "modified": f.get("modified", ""),
                "ext": info["ext"],
                "product_class": info["product_class"],
                "role": info["role"],
                "band": info["band"],
                "filter": info.get("filter", ""),
                "scale": info["scale"],
                "geometry": info["geometry"],
                "taxonomy": info["taxonomy"],
                "acquire": bool(fetch),
                "reason": reason,
            }
        )
    products.sort(key=lambda p: p["name"])
    acq = [p for p in products if p["acquire"]]
    rec = {
        "name": name,
        "url": url,
        "kind": fp["kind"],
        "instrument": fp["instrument"],
        "orbit": fp["orbit"],
        "target": tax.target_of(primary) if primary else None,
        "observations": fp["observations"],
        "product_count": len(products),
        "acquire_count": len(acq),
        "acquire_bytes": sum(p["bytes"] for p in acq),
        "products": products,
    }
    entries = [dict(p, name=p["name"], bytes=p["bytes"]) for p in products]
    rec["reference"] = tax.reference_choice(entries)
    return rec


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def write_csv(path: str, catalogue: dict) -> int:
    """Flat one-row-per-product CSV for filtering/spreadsheets."""
    fields = [
        "branch", "product_family", "instrument", "shard", "footprint",
        "footprint_kind", "orbit", "target", "file", "bytes", "modified",
        "product_class", "role", "band", "filter", "scale", "geometry",
        "acquire", "reason", "url",
    ]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    n = 0
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for br in catalogue["branches"]:
            for sh in br["shards"]:
                for fp in sh["footprints"]:
                    for p in fp["products"]:
                        w.writerow(
                            {
                                "branch": br["name"], "product_family": br["product_family"],
                                "instrument": br["instrument"], "shard": sh["name"],
                                "footprint": fp["name"], "footprint_kind": fp["kind"],
                                "orbit": fp["orbit"], "target": fp["target"],
                                "file": p["name"], "bytes": p["bytes"],
                                "modified": p["modified"], "product_class": p["product_class"],
                                "role": p["role"], "band": p["band"], "filter": p.get("filter", ""),
                                "scale": p["scale"], "geometry": p["geometry"],
                                "acquire": p["acquire"], "reason": p["reason"], "url": p["url"],
                            }
                        )
                        n += 1
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return n


def summarise(catalogue: dict) -> dict:
    per_branch = {}
    totals = {
        "branches": 0, "shards": 0, "footprints": 0, "products": 0,
        "acquire_files": 0, "acquire_bytes": 0, "all_bytes": 0, "errors": 0,
    }
    for br in catalogue["branches"]:
        b = {
            "priority": br["priority"],
            "shards": br["shard_count"],
            "footprints": br["footprint_count"],
            "products": br["product_count"],
            "acquire_files": br["acquire_count"],
            "acquire_bytes": br["acquire_bytes"],
            "acquire_gb": round(br["acquire_bytes"] / 1e9, 2),
            "errors": len(br["errors"]),
        }
        per_branch[br["name"]] = b
        totals["branches"] += 1
        totals["shards"] += br["shard_count"]
        totals["footprints"] += br["footprint_count"]
        totals["products"] += br["product_count"]
        totals["acquire_files"] += br["acquire_count"]
        totals["acquire_bytes"] += br["acquire_bytes"]
        totals["errors"] += len(br["errors"])
    for br in catalogue["branches"]:
        for sh in br["shards"]:
            for fp in sh["footprints"]:
                totals["all_bytes"] += sum(p["bytes"] for p in fp["products"])
    totals["acquire_gb"] = round(totals["acquire_bytes"] / 1e9, 2)
    totals["all_gb"] = round(totals["all_bytes"] / 1e9, 2)
    totals["per_branch"] = per_branch
    return totals


def merge_branch(previous: dict | None, current: dict) -> dict:
    """Union a branch's shards across runs, newest product data winning.

    A checkpoint publishes the branch as it stands *in this run*. Because the
    listing cache makes earlier shards free to re-walk, a fresh run re-touches
    them in order, so a checkpoint taken minutes in would otherwise drop every
    shard it had not yet reached and the on-disk catalogue would shrink — the
    opposite of "always usable". Shards already known from a previous run are
    carried forward, and a shard seen again contributes its newer footprints.
    """
    if not previous:
        return current
    merged = dict(current)
    have = {s.get("name") for s in current.get("shards", [])}
    for shard in previous.get("shards", []):
        if shard.get("name") not in have:
            merged.setdefault("shards", []).append(shard)
    merged["shards"].sort(key=lambda s: (s.get("orbit_from") if s.get("orbit_from") is not None else 0, s.get("name", "")))
    merged["shard_count"] = len(merged["shards"])
    merged["footprint_count"] = sum(len(s.get("footprints", [])) for s in merged["shards"])
    merged["product_count"] = sum(
        fp.get("product_count", 0) for s in merged["shards"] for fp in s.get("footprints", [])
    )
    merged["acquire_count"] = sum(
        fp.get("acquire_count", 0) for s in merged["shards"] for fp in s.get("footprints", [])
    )
    merged["acquire_bytes"] = sum(
        fp.get("acquire_bytes", 0) for s in merged["shards"] for fp in s.get("footprints", [])
    )
    return merged


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Crawl the HiRISE PDS EXTRAS index and build the full organised site catalogue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--out", default="data/catalog/extras_site.json", help="hierarchical catalogue JSON")
    p.add_argument("--csv", default="data/catalog/extras_site.csv", help="flat per-product CSV")
    p.add_argument("--summary", default="data/catalog/extras_summary.json", help="counts + byte budget JSON")
    p.add_argument("--cache", default="data/catalog/extras_listings", help="on-disk index-listing cache dir")
    p.add_argument(
        "--workers",
        type=int,
        default=6,
        help=(
            "parallel index fetches. The host serves ~1 index per 10 s and "
            "answers HTTP 503 beyond ~8 concurrent connections, so raising "
            "this trades real throughput for errors. Default 6."
        ),
    )
    p.add_argument("--branches", default="", help="comma-separated branch filter, e.g. RDR/ESP,DTM/ESP")
    p.add_argument("--shard-limit", type=int, default=0, help="max orbit shards per branch (0 = all)")
    p.add_argument("--footprint-limit", type=int, default=0, help="max footprints per shard (0 = all)")
    p.add_argument(
        "--max-fullres-mb",
        type=float,
        default=0.0,
        help="per-file cap for full-resolution JP2s; 0 = browse-only (default)",
    )
    p.add_argument(
        "--scales",
        default="core",
        choices=sorted(tax.SCALE_SETS),
        help=(
            "which render scales count as the comparison unit: "
            "core = full browse + thumbnail (default); "
            "full = also the half-res abrowse; thumb = thumbnails only"
        ),
    )
    p.add_argument(
        "--geometries",
        default="map",
        choices=sorted(tax.GEOMETRY_SETS),
        help=(
            "which geometry classes are in budget: map = map-projected, "
            "orthorectified and DTM products only (default; the detector-geometry "
            "NOMAP renderings are ~53%% of the total bytes and add coverage "
            "rather than morphology); all = also fetch raw detector geometry "
            "and quicklooks"
        ),
    )
    p.add_argument("--refresh", action="store_true", help="ignore the listing cache and re-fetch every index")
    p.add_argument("--dry-run", action="store_true", help="crawl and report, but do not write outputs")
    p.add_argument("--append", action="store_true", help="merge into an existing catalogue file instead of replacing it")
    p.add_argument(
        "--checkpoint-every",
        type=int,
        default=1,
        help="write the catalogue every N branches (0 disables in-branch checkpoints)",
    )
    p.add_argument(
        "--checkpoint-seconds",
        type=float,
        default=300.0,
        help="minimum seconds between in-branch catalogue writes (0 = every shard)",
    )
    args = p.parse_args(argv)

    wanted = [b.strip() for b in args.branches.split(",") if b.strip()]
    branches = [b for b in tax.BRANCHES if not wanted or b[0] in wanted]
    if wanted:
        unknown = set(wanted) - {b[0] for b in tax.BRANCHES}
        if unknown:
            common.log("warn", f"ignoring unknown branches: {sorted(unknown)}")
    if not branches:
        common.log("error", "no branches selected")
        return 2

    os.makedirs(args.cache, exist_ok=True)
    scales = tax.SCALE_SETS[args.scales]
    geometries = tax.GEOMETRY_SETS[args.geometries]
    common.set_audit(os.path.join(os.path.dirname(os.path.abspath(args.out)), "audit.jsonl"))
    common.audit({"event": "catalog_extras_site_start", "branches": [b[0] for b in branches], "argv": sys.argv[1:]})

    catalogue = {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base": tax.EXTRAS_BASE,
        "policy": {
            "max_fullres_mb": args.max_fullres_mb,
            "browse_only": args.max_fullres_mb <= 0,
            "scales": list(scales),
            "scale_set": args.scales,
            "geometries": list(geometries),
            "geometry_set": args.geometries,
            "shard_limit": args.shard_limit,
            "footprint_limit": args.footprint_limit,
        },
        "branches": [],
    }

    # Branches being re-crawled are dropped from the in-memory catalogue while
    # the crawl runs (so counters are not double-counted), but they are kept
    # here so every checkpoint can merge the new work onto the old instead of
    # replacing it. This is what makes the on-disk catalogue grow monotonically
    # across restarts rather than shrinking to whatever the current run has
    # re-touched so far.
    prior_branches: dict[str, dict] = {}
    if args.append and os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                old = json.load(f)
            # `branches` here is the CLI selection, a list of (name, family, instrument)
            # tuples; the catalogue entries are dicts keyed by "name".
            selected = {name for name, _family, _instr in branches}
            prior_branches = {b["name"]: b for b in old.get("branches", []) if b.get("name")}
            catalogue["branches"] = [
                b for b in old.get("branches", []) if b.get("name") not in selected
            ]
            common.log("info", f"--append: keeping {len(catalogue['branches'])} existing branch record(s), "
                               f"merging {len(selected)} re-crawled")
        except Exception as e:  # noqa: BLE001
            common.log("warn", f"--append could not read {args.out} ({e}); starting fresh")

    t0 = time.time()

    def flush() -> None:
        """Write the catalogue so far, so a long crawl never loses a branch."""
        if args.dry_run:
            return
        catalogue["branches"].sort(key=lambda b: (b["priority"], b["name"]))
        s = summarise(catalogue)
        s["generated"] = catalogue["generated"]
        s["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        s["elapsed_s"] = round(time.time() - t0, 1)
        s["throttle"] = throttle_stats()
        s["partial"] = True
        common.atomic_text_write(args.out, json.dumps(catalogue, indent=1))
        common.atomic_text_write(args.summary, json.dumps(s, indent=2))
        write_csv(args.csv, catalogue)

    for i, (name, family, instr) in enumerate(branches, 1):
        common.log("info", f"[{i}/{len(branches)}] crawling {name} ...")
        last_flush = [0.0]

        def _checkpoint(node, _name=name, _last=last_flush):
            """Publish the in-progress branch so the catalogue on disk is usable.

            Time-throttled: a full RDR/ESP branch is tens of thousands of
            footprints, so rewriting the whole JSON + CSV on every one of 771
            shards would cost hundreds of GB of pointless disk writes. Merged
            rather than replaced, so the catalogue only ever grows.
            """
            now = time.time()
            if now - _last[0] < args.checkpoint_seconds:
                return
            _last[0] = now
            prior = prior_branches.get(_name) or next(
                (b for b in catalogue["branches"] if b.get("name") == _name), None
            )
            merged = merge_branch(prior, node)
            catalogue["branches"] = [
                b for b in catalogue["branches"] if b.get("name") != _name
            ] + [merged]
            flush()

        node = crawl_branch(
            name, family, instr, args.cache, args.workers, args.refresh,
            args.shard_limit, args.footprint_limit, args.max_fullres_mb, scales,
            geometries, on_progress=_checkpoint if args.checkpoint_every else None,
        )
        prior = prior_branches.get(name) or next(
            (b for b in catalogue["branches"] if b.get("name") == name), None
        )
        catalogue["branches"] = [
            b for b in catalogue["branches"] if b.get("name") != name
        ] + [merge_branch(prior, node)]
        th = throttle_stats()
        common.log(
            "info",
            f"    {name}: {node['shard_count']} shards, {node['footprint_count']} footprints, "
            f"{node['product_count']} products, {node['acquire_count']} to fetch "
            f"({node['acquire_bytes']/1e9:.2f} GB), {len(node['errors'])} errors",
        )
        common.log("info", f"    throttle: delay={th['delay_s']}s  503s={th['throttled_503']}  errors={th['errors']}")
        flush()
    catalogue["branches"].sort(key=lambda b: (b["priority"], b["name"]))

    summary = summarise(catalogue)
    summary["generated"] = catalogue["generated"]
    summary["elapsed_s"] = round(time.time() - t0, 1)

    common.log("info", "=" * 68)
    common.log("info", f"branches {summary['branches']}  shards {summary['shards']}  "
                       f"footprints {summary['footprints']}  products {summary['products']}")
    common.log("info", f"browse-only acquisition: {summary['acquire_files']} files / "
                       f"{summary['acquire_gb']} GB  (all products incl. JP2: {summary['all_gb']} GB)")
    for name, b in sorted(summary["per_branch"].items(), key=lambda kv: kv[1]["priority"]):
        common.log("info", f"  [{b['priority']:2d}] {name:14s} {b['footprints']:7d} footprints  "
                           f"{b['acquire_gb']:9.2f} GB  errors={b['errors']}")
    th = throttle_stats()
    common.log("info", f"throttle: {th['delay_s']}s delay, {th['throttled_503']} HTTP 503s, {th['errors']} hard errors")
    common.log("info", f"elapsed {summary['elapsed_s']}s")
    common.log("info", "=" * 68)

    if args.dry_run:
        common.log("info", "--dry-run: nothing written")
    else:
        summary["partial"] = False
        summary["throttle"] = th
        common.atomic_text_write(args.out, json.dumps(catalogue, indent=1))
        common.atomic_text_write(args.summary, json.dumps(summary, indent=2))
        n = write_csv(args.csv, catalogue)
        common.log("info", f"wrote {args.out}, {args.summary}, {args.csv} ({n} product rows)")

    common.audit({"event": "catalog_extras_site_done", "summary": {k: v for k, v in summary.items() if k != "per_branch"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
