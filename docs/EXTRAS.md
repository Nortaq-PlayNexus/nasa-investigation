# EXTRAS-Only Source Policy — HiRISE PDS Exclusive

> **Canon:** every image in this investigation comes from
> `https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/` and is consumed as a
> **complete variant set** (same terrain, many renderings). No mirrors,
> no reposts, no single-variant cherry-picks.

---

## 1. Why EXTRAS-only

| Property | EXTRAS | Other sources |
|---|---|---|
| Provenance URL + PDS label | ✅ per product | ❌ often stripped |
| Same terrain, multiple renderings | ✅ (RED, IRB, ortho, DTM siblings) | ❌ single browse |
| Audit trail (`manifest.jsonl` + `catalog.csv`) | ✅ hash-locked | ⚠️ partial |
| Debunk path | Compare B&W↔filtered↔DTM for persistence | Look at one JPEG and guess |

A feature that survives **B&W RED → filtered color → orthorectified → DTM-shaded**
is terrain (or a shared-pipeline artifact). A feature that collapses outside one
rendering is that rendering's artifact until an independent acquisition proves otherwise.

---

## 2. Archive layout

```
/PDS/EXTRAS/
  RDR/ESP/ORB_013900_013999/ESP_013948_1410/   ← per-observation RDR browse set
  DTM/ESP/ORB_013900_013999/ESP_013948_1410_ESP_013236_1410/  ← per-stereo-pair DTM set
  ANAGLYPH/                                   ← stereo anaglyphs (optional)
  EDR/                                        ← legacy (not used; EXTRAS/RDR is canonical)
```

Listing pages are plain Apache indexes (no API key, no auth).

---

## 3. Variant taxonomy (authoritative)

### 3a. RDR browse — per observation `ESP_XXXXXX_XXXX`

| File pattern | Meaning | Role | Processing |
|---|---|---|---|
| `ESP_*_RED.*.browse.jpg` | Panchromatic 550–850 nm, single band | **B&W baseline** | Minimal (radiometric only) |
| `ESP_*_IRB.*.browse.jpg` | Enhanced color IR+RED+BG | **filtered color** | Stretched / filtered |
| `ESP_*_MIRB.*.JP2/.jpg` | Map-projected IRB variant | filtered color | Map-projected |
| `ESP_*_MRGB.*` | Map-projected RGB variant | filtered color | Map-projected |
| `ESP_*_RGB.*` / `*_COLOR.*` | RGB / COLOR quicklook composites | filtered color | Composite |
| `*_NOMAP.JP2` | Non-map-projected (detector geometry) | geometry check | Unrectified |
| `.browse.jpg` / `.abrowse.jpg` / `.thumb.jpg` | Full / binned / thumbnail | *scale* | Same data, different downsample |

**B&W RED is the reference.** It has the fewest processing steps, so any
feature absent in RED but present in IRB/MIRB is a color-stretch artifact until
`extras_compare` proves persistence.

### 3b. DTM — per stereo pair `ESP_AAAA_AAAA_ESP_BBBB_BBBB`

Exemplar: `ESP_013948_1410_ESP_013236_1410` (Corozal crater region, 1 m post, 0.12 px RMS).

| File pattern | Meaning | Role |
|---|---|---|
| `DTEEC_*_A01.*.JP2` + derivatives | DTM elevation (areoid, equirect., 1 m) | **terrain truth** |
| `DTFEC_*_A01.JP2` | Figure-of-Merit map (stereo correlation quality) | **quality** |
| `ESP_013948_1410_RED_C_01_ORTHO.*` | Orthorectified B&W (RED draped on DTM) | ortho B&W |
| `ESP_013948_1410_IRB_C_01_ORTHO.*` | Orthorectified color (IRB draped on DTM) | ortho color |
| `DTEEC_*_A01.ab.jpg` | Shaded relief, illumination A | DTM visual |
| `DTEEC_*_A01.br.jpg` | Browse B | DTM visual |
| `DTEEC_*_A01.ca.jpg` / `.cb.jpg` | Colorized / curvature | DTM visual |
| `DTEEC_*_A01.ct.jpg` | Contour / terrain model | DTM visual |
| `DTEEC_*_A01.sa.jpg` / `.sb.jpg` | Slope / aspect | DTM visual |
| `DTEEC_*_A01.st.jpg` | Stereo helper | DTM visual |
| `DTEEC_*_A01.th.jpg` | Thumbnail | scale |
| `FOM_MAP_LEGEND.JPG` | FOM color table | legend |
| `README.TXT` | PDS compliance record, RMS, valid elevation range | provenance |

Post spacing, RMS (x/y/z), mean Δ MOLA, SOCET SET NGATE parameters all live in
`README.TXT` and are parsed by `pipeline/metadata.py` into `catalog.csv`.

---

## 4. The VariantSet contract

```
data/raw/mars/hirise_extras/
  ESP_013948_1410/
    ESP_013948_1410_RED.browse.jpg
    ESP_013948_1410_RED.abrowse.jpg
    ESP_013948_1410_IRB.NOMAP.browse.jpg
    ESP_013948_1410_MIRB.browse.jpg
    ...
    _variant_manifest.json          ← siblings + SHA-256 + taxonomy + provenance
  ESP_013948_1410_ESP_013236_1410/
    DTEEC_013948_1410_013236_1410_A01.ab.jpg
    DTEEC_013948_1410_013236_1410_A01.br.jpg
    ESP_013948_1410_RED_C_01_ORTHO.br.jpg
    ESP_013236_1410_RED_C_01_ORTHO.br.jpg
    ...
    _variant_manifest.json
data/raw/manifest.jsonl              ← global provenance (one JSON per file)
data/catalog/catalog.csv             ← hash + solar geometry + pixel scale
```

**Invariants enforced by `download_hirise_extras.py`:**
- Every URL starts with `https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/` or the fetch is rejected (`_enforce_extras`).
- Siblings sharing the same footprint are downloaded **together** into one directory; a footprint is not "ingested" until `_variant_manifest.json` exists.
- `manifest.jsonl` + `catalog.csv` + `_variant_manifest.json` triple-lock provenance: any claim can be traced to the exact PDS URL + SHA-256.
- `max-size-mb` gates only `*.JP2` (full-res, often >100 MB); browse JPGs (1–6 MB) are always fetched so comparison is never blocked.

---

## 5. Acquisition — `scripts/download_hirise_extras.py`

The **only** sanctioned downloader. All other `download_*.py` scripts are deprecated
and blocked when `extras_policy.enforced: true`.

```bash
# Exemplar first (recommended for review / CI) — DTM pair + both parent RDR sets
python scripts/download_hirise_extras.py --exemplar

# One observation (B&W + all filtered siblings together)
python scripts/download_hirise_extras.py --observation ESP_013948_1410 --max-size-mb 15

# One DTM pair (DTM + orthos + all shaded derivatives)
python scripts/download_hirise_extras.py --dtm ESP_013948_1410_ESP_013236_1410

# Bounded crawl (whole EXTRAS tree, but capped)
python scripts/download_hirise_extras.py --crawl --max-sets 20 --max-size-mb 15 --max-dirs 60
```

After any acquisition:
```bash
python scripts/build_catalog.py --root data/raw/mars/hirise_extras --snapshot
python pipeline/extras_compare.py --extras-root data/raw/mars/hirise_extras
```

---

## 6. Comparison — `pipeline/extras_compare.py`

For each footprint, aligns every variant to the **B&W RED browse** (the least-processed
reference) via phase-correlation translation, resamples to a common grid, and scores:

| Metric | Meaning |
|---|---|
| `mean_abs_diff` | Mean absolute photometric divergence vs B&W RED |
| `p95` | 95th-percentile divergence (tail) |
| `ssim_proxy` | `1 - mean_abs_diff` (quick structural similarity proxy) |
| `shift_dy/dx` | Translation applied (large shift ⇒ different coverage, comparison suppressed) |
| `candidate_median_persistence` | Median `contrast_in_variant / contrast_in_RED` across `candidates.csv` boxes |

**Verdicts:**

| Δ (mean) | Verdict | Interpretation |
|---|---|---|
| < 0.06 | PERSISTS | Near-identical to B&W — terrain or shared-pipeline artifact |
| 0.06–0.14 | COLOR DIVERGENCE | Expected B&W↔filtered difference; compare candidate contrast, not raw Δ |
| 0.14–0.28 | MODERATE DIVERGENCE | Ortho / DTM shading difference |
| > 0.28 | STRONG DIVERGENCE | Visualization or coverage difference — not morphology proof |

Per-footprint outputs:
```
data/processed/extras_compare/<footprint>/
  diff_<variant>_vs_<RED>.png
  composite_strip.jpg          # B&W | color | ortho | DTM thumbnailed
  compare_report.json          # machine-readable (ingested by adjudicate.py)
  compare_report.md            # human-readable
```

An `index.html` + `index.json` aggregates all footprints. The dashboard
(`app/static/index.html` → EXTRAS comparator) renders the strip with a
before/after slider and the per-variant table.

Integration with the main pipeline:
- `detect.py` / `analyze.py` run on `data/raw/mars/hirise_extras` as usual.
- `adjudicate.py` can ingest `extras_compare/**/compare_report.json` as an
  additional signal (a candidate whose persistence collapses outside the filtered
  variant is penalised; one that persists into DTM-shaded earns a bonus). This
  is *additive* — cross-variant persistence does not by itself promote a
  candidate to a finding (needs independent acquisition at different lighting).

---

## 7. Enforcement & audit

- **Config gate:** `config/sources.yaml:extras_policy.enforced` and
  `config/pipeline.json:source_policy` both say `hirise_extras_only`.
- **Code gate:** `download_hirise_extras._enforce_extras(url)` raises on any
  non-EXTRAS URL; `pipeline/common.validate_extras_path` rejects non-EXTRAS
  `path` fields in `candidates.csv` when the policy is active.
- **Audit trail:** every fetch appends to `data/raw/manifest.jsonl`; every
  `extras_compare` run appends to `data/processed/extras_compare/audit.jsonl`;
  every adjudication appends to `data/anomalies/audit.jsonl`. Any finding can
  be traced to the exact PDS URL + SHA-256 + pipeline parameters + elapsed time.

---

## 8. Exemplar — `ESP_013948_1410_ESP_013236_1410` (Corozal)

- **Location:** 159.3°E, 38.7°S (Corozal crater ejecta)
- **Source obs:** `ESP_013948_1410` + `ESP_013236_1410`
- **DTM:** 1 m post, equirectangular areoid, SOCET SET NGATE, total RMS 0.12 px
  (RMS x 2.07 m, y 0.02 m, z 0.87 m), valid elevation −208 to +877 m.
- **Browse the exemplar live:**
  `https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/DTM/ESP/ORB_013900_013999/ESP_013948_1410_ESP_013236_1410/`
- **Fetch it:** `python scripts/download_hirise_extras.py --exemplar`

---

## 9. Whole-site catalogue + systematic pass

The exemplar path above fetches one footprint. The site as a whole is far
larger, so acquisition runs in two stages.

### 9a. `scripts/catalog_extras_site.py` — index the whole tree

Walks every branch of the live Apache index and writes one organised JSON of
every footprint and every product. No image bytes are fetched.

```bash
python scripts/catalog_extras_site.py --workers 6 --scales core
```

Outputs `data/catalog/extras_site.json` (hierarchical),
`extras_site.csv` (one row per product) and `extras_summary.json`
(counts + byte budget). Listings are cached under `data/catalog/extras_listings/`
keyed by URL hash, so the crawl is **resumable** and a re-run costs zero
requests. Use `--branches`, `--shard-limit`, `--footprint-limit` for trials and
`--append` to add a branch to an existing catalogue.

**Host behaviour (measured).** The PDS host answers roughly one index request
per 10 s and starts returning `HTTP 503` beyond ~8 concurrent connections, so
raising `--workers` trades real throughput for errors. The crawler treats a
503 as "over the limit right now" and makes every worker back off, which keeps
the crawl inside the host's envelope instead of hammering it.

### 9b. `scripts/extras_pass.py` — one image at a time, full pipeline

Walks the catalogue in a fixed order and takes every footprint through
acquire → catalog → detect → mark/triage → analyze → adjudicate → record,
writing a per-image `report.json` and appending to `index.jsonl`.

```bash
python scripts/extras_pass.py --plan                 # the plan and the disk budget
python scripts/extras_pass.py --limit 3               # a bounded trial
python scripts/extras_pass.py                         # the whole site
python scripts/extras_pass.py --status                # progress, no network
```

Order is a pure function of the catalogue: branch scientific priority
(`extras_taxonomy.BRANCH_PRIORITY` — RDR/ESP, DTM/ESP, RDR/PSP … legacy EDR
last), then orbit, then footprint. Resume is derived from each image's
`report.json`, not from an in-memory map, so state stays a fixed size. The run
stops cleanly on `--limit`, `--max-hours` or `--disk-floor-gb` and picks up
where it left off.

### 9c. What the comparison reference must be

`extras_compare` aligns every sibling to the **map-projected B&W RED full
browse**. Ranking candidates by "is it a browse" and then by file size silently
picks `*_RED.NOMAP.browse.jpg`, which is the *largest* B&W product in a
typical RDR set and is in raw detector geometry — aligning to it drags a
registration error into every measurement. The acquisition pass pins the
reference explicitly so detection coordinates and comparison coordinates can
never disagree.

Cross-variant persistence, measured by `extras_compare` on the same terrain in
every band, is the adjudicator's *second* route to a verdict. It matters
because with reference-only detection there is exactly one detection image per
footprint, so `cross_band_agreement` has no sibling detections to compare and
`agrees` would otherwise always be 0 — every candidate parked at `PROMISING`,
with `CONFIRMED-LEAD` and `TERRAIN` unreachable.

The reading of that evidence is deliberately conservative:

| cross-rendering result | verdict | meaning |
|---|---|---|
| holds in another rendering, contrast ≥ bar, compact | `CONFIRMED-LEAD` | a real feature worth an independent check |
| holds in another rendering, below the bar | `TERRAIN` | real, and ordinary — persistence is the *null* result |
| vanishes in **every** other rendering | `BAND-DEPENDENT` | tracks the reference rendering, not the ground |
| on a product from a stereo DTM | `DTM-ARTIFACT-RISK` | the terrain model has declared defects; not usable as a surface feature |

Per §6, a feature surviving B&W → colour → ortho → DTM *is terrain*.
Persistence therefore demotes to `TERRAIN` by default and only promotes a
candidate when it is also compact, plausibly sized and above the contrast bar.
Neither outcome is a finding: that needs an independent acquisition at
different lighting.

### 9d. Provenance, and where the geometry comes from

Nothing in a candidate's record is invented; each field has one source, and the
source is recorded.

| field | RDR / ortho browse | DTM derivative |
|---|---|---|
| solar incidence, azimuth, elevation | the product's own `*.LBL` | borrowed from the source RDR observation, whose ids the pair README lists |
| pixel scale | `MAP_SCALE` (or `MAP_RESOLUTION` × local radius) | the README's "Post spacing in DTM is N m" |
| observation, target, instrument | label | README "PROJECT NAME" + "HIRISE SOURCE IMAGES" |
| stereo quality | — | README RMS x/y/z, total RMS px, MOLA difference |

Two traps in the EXTRAS naming, both of which produce confidently wrong numbers:

- **Grid spacing is not in the filename.** The letter in `..._A01` / `..._U01`
  is the producing *institution* (A = Arizona, U = USGS), not the grid
  spacing, as the README's own naming-convention section invites you to
  read. Post spacing appears only in prose.
- **A label describes the product, not every rendering of it.** Resolving a
  `.thumb.jpg` to the map-projected label makes it inherit that label's
  `MAP_SCALE` verbatim, reporting a thumbnail at full-browse resolution.
  Ground sample distance belongs to the rendering, so it is corrected from
  actual pixel widths and copied only between products sharing an identical
  geometry and scale class. A wrong scale is worse than a missing one: the
  adjudicator multiplies shadow length by it to infer a physical height.

Verification that the correction is right: every product in a footprint then
reports the same ground footprint, e.g. `2048 px × 0.5 m`, `1024 px × 1.0 m`
and `512 px × 2.0 m` all give 1024 m.

### 9e. Supervision — surviving the hours

Indexing the whole tree takes many hours at the host's ~1 req/s, and the jobs
had been killed by server restarts four times. Both are resumable — the listing
cache and per-image `report.json` files mean a restart costs nothing — but
something had to restart them:

```bash
python scripts/run_extras_pipeline.py --both      # supervise catalogue + pass
python scripts/run_extras_pipeline.py --status    # health, no side effects
```

It restarts a job on a non-zero exit with capped exponential backoff, kills and
relaunches one that makes no progress for `--catalogue-stall` / `--pass-stall`
seconds, and stops cleanly on SIGINT/SIGTERM or `--max-hours`. A clean exit is
treated as final: both jobs exit 0 when finished, or when a budget such as
`--disk-floor-gb` stops them, and relaunching on rc=0 would just spin.

The two jobs run together but the pass is throttled to `--pass-file-workers`
(default 2) so total in-flight requests stay near the host's 503 threshold.

### 9f. Reading progress honestly

`extras_pass.py --status` reports throughput from a **trailing window of 50
images**, not a lifetime average. A `--force` reprocess re-adjudicates
already-fetched images and skips the ~40 s download, so a lifetime average can
report >100 images/min while a fresh image genuinely takes that long. The
window reflects the current mix of work; the lifetime figure is still reported,
labelled as not comparable. Download and analysis seconds are accumulated
separately, since the pass is network-bound, not compute-bound.

### 9g. Scale, geometry, and what actually fits

Two orthogonal knobs, because they cut different costs:

`--scales` — which render scales count as the comparison unit:

| set | contents |
|---|---|
| `thumb` | `.thumb.jpg` only — a cheap full-site index pass |
| `browse` | `.browse.jpg` only |
| `core` (default) | `.browse.jpg` + `.thumb.jpg` |
| `full` | + the half-res `.abrowse.jpg` |

`--geometries` — which geometry classes are in budget:

| set | contents |
|---|---|
| `map` (default) | map-projected, orthorectified, DTM and anaglyph products |
| `all` | + raw detector geometry (`NOMAP`) and quicklooks |

Full-resolution JP2s are never fetched unless `--max-fullres-mb` is set.

**Why `map` is the default.** Measured over ~7,600 real RDR footprints, an
`*_RED.NOMAP.browse.jpg` averages 5.6 MB against 2.3 MB for the map-projected
`*_RED.browse.jpg` — NOMAP preserves native detector resolution while the
projected product is resampled onto a common grid. Across a whole observation
that is ~9.5 MB of the ~18 MB budget:

| policy | per footprint | RDR/ESP alone (~83k observations) |
|---|---|---|
| all geometries | ~18.0 MB | ~1489 GB |
| `map` only | ~8.5 MB | ~705 GB |
| `thumb` only | ~1.2 MB | ~102 GB |

The science survives the cut. The documented debunk path is B&W RED → filtered
colour → orthorectified → DTM-shaded, and every one of those is map-projected.
`extras_compare` already scores the NOMAP siblings as STRONG DIVERGENCE
(`mean_abs_diff` ~0.32) precisely because they are in a different geometry, so
they confirm coverage rather than morphology. A footprint still ships its
complete cross-rendering set: RED (the reference) + MIRB + MRGB + COLOR, each
at browse and thumbnail scale, plus the PDS labels.

**A whole-site `map` acquisition is the only policy that fits one volume.**
`--plan` reports the byte budget and where the disk floor will land; because
the order is priority-ordered, the archive fills with the most scientifically
useful data first, and legacy `EDR/` (which `docs/EXTRAS.md` §2 already marks
as "not used") is reached last.

---

## 10. What is NOT allowed

- Fetching from `images-api.nasa.gov`, `mars.nasa.gov/rss`, `pds-imaging.jpl.nasa.gov`,
  ESA PSA, or any non-EXTRAS mirror. Those scripts remain in `scripts/` only as
  documentation of deprecated paths and are blocked by the enforcer.
- Cherry-picking a single `*_IRB.browse.jpg` without its `*_RED` sibling. The
  downloader groups siblings; the comparator assumes a B&W baseline exists.
- Trusting JP2 full-res without the browse set — browses are the comparison unit;
  JP2s are gated by `--max-size-mb` and are optional for the variant-set contract.
- Treating a `NOMAP` product as the comparison reference, or propagating one
  product's pixel scale onto a rendering with a different ground scale
  (a thumbnail, or a detector-geometry product).

---

*Built like a flight system: one sanctioned source, complete variant sets,
hash-locked provenance, pixel-registered comparison, and an honest audit trail.
That is the level this investigation holds itself to.*
