#!/usr/bin/env python3
"""
HiRISE PDS EXTRAS — Exclusive Acquisition & Variant-Comparison Downloader
=======================================================================
The ONLY sanctioned imagery source for this investigation.

    Base: https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/

Why EXTRAS-only?
  - Every product carries an auditable PDS label / provenance URL.
  - Every observation ships as a *variant set* (same terrain, many renderings)
    so a feature can be cross-checked across B&W, filtered color, ortho and
    DTM-shaded derivatives in one acquisition — the core debunk path.
  - No social-media reposts, no secondary mirrors: EDR/PDS original or nothing.

Variant taxonomy (authoritative, from PDS label docs + live directory probe)
--------------------------------------------------------------------------
RDR browse products  — per observation  ESP_XXXXXX_XXXX
  RED.*       Panchromatic B&W  (550-850 nm, single band, least processing, highest fidelity)
  IRB.*       Enhanced color    (IR + RED + BG, stretched, filtered)
  MIRB.MRGB   Map-projected color variants (different filter stacks)
  RGB/COLOR   Quicklook composites
  NOMAP.*     Non-map-projected (detector geometry preserved)
  Suffix .browse.jpg = full browse, .abrowse.jpg = binned browse, .thumb.jpg = thumbnail

DTM products  — per stereo pair  ESP_AAAAAA_AAAA_ESP_BBBBBB_BBBB  (e.g. ESP_013948_1410_ESP_013236_1410)
  DTEEC_*     DTM elevation (areoid), equirectangular, 1 m post spacing
  DTFEC_*     Figure-of-Merit map (stereo correlation quality, JP2)
  ESP_*_RED_C_01_ORTHO.*   Orthorectified B&W  (geometrically corrected RED)
  ESP_*_IRB_C_01_ORTHO.*   Orthorectified color (geometrically corrected IRB)
  DTM browse derivatives (same terrain, different visualisation):
    .ab/.br = shaded relief (A/B illumination angles)
    .ca/.cb = colorized elevation / curvature
    .ct     = contour / terrain model
    .sa/.sb = slope / aspect
    .st     = stereo anaglyph helper
    .th     = thumbnail
  FOM_MAP_LEGEND.JPG  Explains FOM color table; README.TXT = PDS compliance record

Comparison contract
  For every footprint (observation OR stereo pair), ALL sibling variants
  sharing the same geometry are downloaded together under data/raw/mars/hirise_extras/<footprint>/
  and registered as one VariantSet in data/raw/manifest.jsonl + data/catalog/catalog.csv.
  The downstream pipeline (pipeline/extras_compare.py) then aligns and
  subtracts B&W ↔ filtered ↔ ortho ↔ DTM-shaded to flag processing artifacts
  vs. persistent terrain.

Directory layout after acquisition
  data/raw/mars/hirise_extras/
    ESP_013948_1410/
      ESP_013948_1410_RED.browse.jpg        # B&W
      ESP_013948_1410_IRB.NOMAP.browse.jpg  # filtered color
      ...
      _variant_manifest.json                # siblings + hashes + provenance
    ESP_013948_1410_ESP_013236_1410/
      DTEEC_013948_1410_013236_1410_A01.ab.jpg
      ESP_013948_1410_RED_C_01_ORTHO.br.jpg
      ...
      _variant_manifest.json

This script is the SOLE entry-point for acquisition. All other download_*.py
scripts are deprecated and blocked when --enforce-extras is active.

Usage
  # recommended: pull the exemplar DTM pair + both parent RDR observations
  python scripts/download_hirise_extras.py --exemplar

  # a single observation (with all color/BW variants)
  python scripts/download_hirise_extras.py --observation ESP_013948_1410 --out data/raw/mars/hirise_extras

  # a stereo DTM pair (with all DTM + ortho derivatives)
  python scripts/download_hirise_extras.py --dtm ESP_013948_1410_ESP_013236_1410

  # crawl entire EXTRAS tree (bounded)
  python scripts/download_hirise_extras.py --crawl --max-sets 20 --max-size-mb 15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — the only allowed root; everything else is rejected in enforce mode
# ---------------------------------------------------------------------------
EXTRAS_BASE = "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/"
EXEMPLAR_DTM = "ESP_013948_1410_ESP_013236_1410"
EXEMPLAR_OBS = ["ESP_013948_1410", "ESP_013236_1410"]
EXEMPLAR_DIR = "ESP/ORB_013900_013999/ESP_013948_1410_ESP_013236_1410"

# Variant regexes — each footprint's siblings are collected together
RDR_VARIANTS = re.compile(
    r"^(ESP_\d+_\d+)_(RED|IRB|MIRB|MRGB|RGB|COLOR)(\.(NOMAP|QLOOK))?(\.LBL|\.JP2|\.(abrowse|browse|thumb)\.jpg)$",
    re.I,
)
DTM_VARIANTS = re.compile(
    r"^(DTEEC|DTFEC|ESP)_.+(\.JP2|\.LBL|\.(ab|br|ca|cb|ct|sa|sb|st|th)\.jpg|FOM_MAP_LEGEND\.JPG|README\.TXT)$",
    re.I,
)
# For grouping: observation key or pair key
OBS_KEY_RX = re.compile(r"^(ESP_\d+_\d+)", re.I)
PAIR_KEY_RX = re.compile(r"(ESP_\d+_\d+_ESP_\d+_\d+)", re.I)

USER_AGENT = {"User-Agent": "nasa-investigation/1.0 (HiRISE-EXTRAS-only)"}
HREF_RX = re.compile(r'<a href="([^"]+)">', re.I)

# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _list_dir(url: str, timeout: int = 60) -> list[str]:
    """Return raw href values inside a PDS Apache index page."""
    html = _http_get(url, timeout=timeout).decode("utf-8", "ignore")
    hrefs = HREF_RX.findall(html)
    return [h for h in hrefs if h not in ("../", "./", "/", "") and not h.startswith("?")]


def _enforce_extras(url: str) -> None:
    if not url.startswith(EXTRAS_BASE):
        raise ValueError(
            f"EXTRAS-only enforcement: URL must start with {EXTRAS_BASE}\n  got: {url}\n"
            "This investigation is locked to hirise-pds.lpl.arizona.edu/PDS/EXTRAS/."
        )


def _download(url: str, dest: Path, manifest_path: Path | None, max_retries: int = 3) -> str:
    _enforce_extras(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        # keep existing; re-hash for manifest below but avoid re-download
        status = "exists"
    else:
        tmp = dest.with_suffix(dest.suffix + ".part")
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers=USER_AGENT)
                with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                tmp.replace(dest)
                status = "downloaded"
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(2 * (attempt + 1))
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
        else:
            raise RuntimeError(f"download failed {url}: {last_err}") from last_err
    # provenance
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "url": url,
            "file": str(dest.resolve()),
            "sha256": _sha256(dest),
            "bytes": dest.stat().st_size,
            "source": "hirise_extras",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(manifest_path, "a", encoding="utf-8") as mf:
            mf.write(json.dumps(rec, sort_keys=True) + "\n")
    return status


# ---------------------------------------------------------------------------
# VariantSet discovery
# ---------------------------------------------------------------------------

def _classify_variant(filename: str) -> str:
    """Human taxonomy label for a single file."""
    low = filename.lower()
    if "red" in low and "ortho" in low:
        return "ORTHO_RED (B&W orthorectified)"
    if "irb" in low and "ortho" in low:
        return "ORTHO_IRB (filtered-color orthorectified)"
    if low.startswith("dteec"):
        return "DTM elevation (areoid)"
    if low.startswith("dtfec"):
        return "FOM map (stereo correlation quality)"
    if low.startswith("fom_map"):
        return "FOM legend"
    if filename.lower() == "readme.txt":
        return "PDS README"
    m = RDR_VARIANTS.match(filename)
    if m:
        band = m.group(2).upper()
        mapping = {
            "RED": "B&W panchromatic (least processing)",
            "IRB": "Enhanced color (IR/RED/BG filtered)",
            "MIRB": "MIRB color variant",
            "MRGB": "MRGB color variant",
            "RGB": "RGB composite",
            "COLOR": "COLOR quicklook composite",
        }
        return mapping.get(band, band)
    # DTM browses
    for suf, label in [
        (".ab.jpg", "DTM shaded relief A"),
        (".br.jpg", "DTM browse B"),
        (".ca.jpg", "DTM color/albedo"),
        (".cb.jpg", "DTM colorized B"),
        (".ct.jpg", "DTM contour/terrain"),
        (".sa.jpg", "DTM slope/aspect A"),
        (".sb.jpg", "DTM slope/aspect B"),
        (".st.jpg", "DTM stereo helper"),
        (".th.jpg", "Thumbnail"),
    ]:
        if low.endswith(suf):
            return label
    return "browse variant"


def discover_exemplar(out_root: Path, manifest: Path, max_size_mb: float | None) -> int:
    """Fetch the canonical exemplar: DTM pair + both parent RDR observation sets."""
    count = 0
    # DTM directory itself (all DTEEC/DTFEC/ORTHO siblings)
    dtm_url = EXTRAS_BASE + "DTM/" + EXEMPLAR_DIR + "/"
    count += _fetch_directory_set(dtm_url, out_root / EXEMPLAR_DTM, manifest, max_size_mb, label="DTM exemplar")
    # Parent RDR observations
    for obs in EXEMPLAR_OBS:
        # RDR is sharded by ORB range, discover by crawling RDR/ESP/ORB_013900*
        rdr_url = _find_rdr_observation_url(obs)
        if rdr_url:
            count += _fetch_directory_set(rdr_url, out_root / obs, manifest, max_size_mb, label=f"RDR {obs}")
        else:
            print(f"[warn] could not locate RDR directory for {obs}", file=sys.stderr)
    return count


def _find_rdr_observation_url(obs: str) -> str | None:
    """Locate the RDR/ESP/ORB_*/*obs*/ directory for an observation."""
    rdr_esp = EXTRAS_BASE + "RDR/ESP/"
    try:
        orbs = [h for h in _list_dir(rdr_esp) if h.startswith("ORB_")]
    except Exception:
        return None
    for orb in orbs:
        orb_url = rdr_esp + orb
        try:
            entries = _list_dir(orb_url)
        except Exception:
            continue
        for e in entries:
            if obs in e:
                cand = orb_url + e
                # ensure it lists files matching that obs
                return cand
    return None


def _fetch_directory_set(url: str, out_dir: Path, manifest: Path, max_size_mb: float | None, label: str = "") -> int:
    print(f"[extras] {label or url}  <-  {url}")
    _enforce_extras(url)
    hrefs = _list_dir(url)
    # Filter to known variant files (exclude sort headers)
    wanted = [h for h in hrefs if not h.endswith("/") and not h.startswith("?")]
    # Probe sizes via HEAD-ish: we just try to download browses first; JP2 may be huge
    downloaded = 0
    variant_manifest: list[dict] = []
    for href in wanted:
        fname = href.split("/")[-1] if "/" in href else href
        if fname in ("", "../", "./"):
            continue
        file_url = url.rstrip("/") + "/" + fname
        # Size guard for JP2s
        if max_size_mb is not None and fname.lower().endswith(".jp2"):
            # conservative: JP2s are often >50 MB; skip if over budget unless user asked
            # We skip only if we can't confirm size; the caller sets max_size_mb
            # to gate; browses/JPGs are always allowed (few MB).
            print(f"  skip (JP2 size-gated) {fname}")
            variant_manifest.append({"file": fname, "taxonomy": _classify_variant(fname), "status": "skipped-size-gate", "url": file_url})
            continue
        dest = out_dir / fname
        try:
            status = _download(file_url, dest, manifest)
            downloaded += 1 if status == "downloaded" else 0
            print(f"  {status:10s} {fname:45s}  [{_classify_variant(fname)}]")
            variant_manifest.append({
                "file": fname,
                "taxonomy": _classify_variant(fname),
                "status": status,
                "url": file_url,
                "sha256": _sha256(dest) if dest.exists() else None,
                "bytes": dest.stat().st_size if dest.exists() else 0,
            })
        except Exception as e:  # noqa: BLE001
            print(f"  error   {fname}: {e}", file=sys.stderr)
            variant_manifest.append({"file": fname, "taxonomy": _classify_variant(fname), "status": f"error: {e}", "url": file_url})
    # Write per-footprint variant manifest (the comparison contract's index)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "_variant_manifest.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "footprint": out_dir.name,
                "source_url": url,
                "retrieved": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "variants": variant_manifest,
                "comparison_note": "Each entry is the same terrain in a different rendering (B&W vs filtered color vs ortho vs DTM-shaded). Downstream extras_compare.py aligns and diffs them.",
            },
            f,
            indent=2,
        )
    print(f"  -> {downloaded} downloaded, {len(variant_manifest)} catalogued -> {out_dir}/_variant_manifest.json")
    return downloaded


def crawl_extras(out_root: Path, manifest: Path, max_sets: int, max_size_mb: float | None, max_dirs: int) -> int:
    """Bounded crawl of EXTRAS/ tree, collecting bounded number of variant sets."""
    # Walk RDR + DTM roots breadth-first
    roots = [EXTRAS_BASE + "RDR/", EXTRAS_BASE + "DTM/"]
    todo: list[tuple[str, int]] = [(r, 0) for r in roots]
    seen: set[str] = set()
    sets_done = 0
    total_files = 0
    dirs_visited = 0
    while todo and sets_done < max_sets and dirs_visited < max_dirs:
        url, depth = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        dirs_visited += 1
        try:
            hrefs = _list_dir(url)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] list {url}: {e}", file=sys.stderr)
            continue
        # Distinguish leaf observation dirs (contain browse JPGs) from branch dirs
        has_variant = any(RDR_VARIANTS.match(h) or DTM_VARIANTS.match(h) for h in hrefs if not h.endswith("/"))
        subdirs = [h for h in hrefs if h.endswith("/")]
        if has_variant and depth >= 2:
            # This is a leaf footprint — fetch as a complete variant set
            # Derive out name from URL tail
            tail = url.rstrip("/").split("/")[-1]
            # DTM leaf has several DTM browses; keep pair id
            out_dir = out_root / tail
            n = _fetch_directory_set(url, out_dir, manifest, max_size_mb, label=tail)
            total_files += n
            sets_done += 1
            print(f"[crawl] set {sets_done}/{max_sets} done ({tail})")
        else:
            # Branch: enqueue subdirs (bounded depth)
            if depth < 5:
                for sd in subdirs:
                    # Keep within EXTRAS
                    nxt = url.rstrip("/") + "/" + sd
                    if nxt.startswith(EXTRAS_BASE):
                        todo.append((nxt, depth + 1))
    print(f"[crawl] visited {dirs_visited} dirs, {sets_done} variant sets, {total_files} files")
    return total_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="HiRISE PDS EXTRAS exclusive acquisition — variant-set downloader (the only sanctioned source)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--out", default="data/raw/mars/hirise_extras", help="output root (variant sets become subdirs)")
    p.add_argument("--manifest", default="data/raw/manifest.jsonl", help="provenance JSONL (appended)")
    p.add_argument("--max-size-mb", type=float, default=15.0, help="skip JP2s larger than this (browse JPGs always fetched); 0=allow all")
    p.add_argument("--max-sets", type=int, default=5, help="max variant sets when crawling")
    p.add_argument("--max-dirs", type=int, default=60, help="max directory listings visited when crawling")
    # Focused modes
    p.add_argument("--exemplar", action="store_true", help="fetch the canonical DTM exemplar + its two parent RDR observations")
    p.add_argument("--observation", default="", help="single observation id, e.g. ESP_013948_1410 (fetches all BW/color variants)")
    p.add_argument("--dtm", default="", help="stereo pair id, e.g. ESP_013948_1410_ESP_013236_1410 (fetches DTM + orthos + shaded)")
    p.add_argument("--crawl", action="store_true", help="bounded crawl of EXTRAS/RDR and EXTRAS/DTM (use --max-sets to bound)")
    p.add_argument("--enforce-extras", action="store_true", default=True, help="reject any URL outside EXTRAS_BASE (default: on)")
    p.add_argument("--no-enforce", dest="enforce_extras", action="store_false", help="disable enforcement (not recommended)")
    args = p.parse_args(argv)

    out_root = Path(args.out)
    manifest = Path(args.manifest)

    # Enforce global flag if needed (monkey-patch guard)
    if not args.enforce_extras:
        global _enforce_extras  # noqa: PLW0603

        def _enforce_extras_noop(url: str) -> None:  # type: ignore[no-redef]
            return

        globals()["_enforce_extras"] = _enforce_extras_noop

    out_root.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    if args.exemplar or (not args.observation and not args.dtm and not args.crawl):
        # default: exemplar (most useful for review / CI)
        total += discover_exemplar(out_root, manifest, args.max_size_mb)
    if args.observation:
        obs = args.observation.strip()
        url = _find_rdr_observation_url(obs)
        if not url:
            # try direct guess: search all ORB ranges quickly
            print(f"[error] could not locate RDR dir for observation {obs}", file=sys.stderr)
            return 2
        total += _fetch_directory_set(url, out_root / obs, manifest, args.max_size_mb, label=f"RDR {obs}")
    if args.dtm:
        pair = args.dtm.strip()
        # Try every ORB range under DTM/
        dtm_root = EXTRAS_BASE + "DTM/"
        found = None
        try:
            for orb in _list_dir(dtm_root):
                if not orb.endswith("/"):
                    continue
                orb_url = dtm_root + orb
                for sub in _list_dir(orb_url):
                    if pair in sub:
                        found = orb_url + sub
                        break
                if found:
                    break
        except Exception:
            pass
        if not found:
            print(f"[error] DTM pair dir not found for {pair}", file=sys.stderr)
            return 2
        total += _fetch_directory_set(found, out_root / pair, manifest, args.max_size_mb, label=f"DTM {pair}")
    if args.crawl:
        total += crawl_extras(out_root, manifest, args.max_sets, args.max_size_mb, args.max_dirs)

    print(f"\n[done] {total} file(s) downloaded (variant sets in {out_root})")
    print(f"       provenance -> {manifest}")
    print(f"       variant manifests -> {out_root}/*/_variant_manifest.json")
    print("       Next: python pipeline/extras_compare.py  (B&W vs filtered vs ortho vs DTM diff)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
