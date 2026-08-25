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

## 9. What is NOT allowed

- Fetching from `images-api.nasa.gov`, `mars.nasa.gov/rss`, `pds-imaging.jpl.nasa.gov`,
  ESA PSA, or any non-EXTRAS mirror. Those scripts remain in `scripts/` only as
  documentation of deprecated paths and are blocked by the enforcer.
- Cherry-picking a single `*_IRB.browse.jpg` without its `*_RED` sibling. The
  downloader groups siblings; the comparator assumes a B&W baseline exists.
- Trusting JP2 full-res without the browse set — browses are the comparison unit;
  JP2s are gated by `--max-size-mb` and are optional for the variant-set contract.

---

*Built like a flight system: one sanctioned source, complete variant sets,
hash-locked provenance, pixel-registered comparison, and an honest audit trail.
That is the level this investigation holds itself to.*
