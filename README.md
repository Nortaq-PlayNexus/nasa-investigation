# NASA Moon & Mars anomaly investigation

An organized, reproducible pipeline for acquiring, cataloging, enhancing and
analyzing **public NASA imagery** of the Moon and Mars to surface candidate
anomalies for structured human review.

All data is public-domain U.S. government planetary science. The process is
deliberately rigorous: almost every "anomaly" in planetary imagery turns out to
be a sensor, compression, or lighting artifact, so the pipeline is built to
document, control, and debunk before anything is ever recorded as a finding.
See `docs/METHODOLOGY.md` for the full protocol.

## Layout

```
nasa-investigation/
  config/
    sources.yaml            source registry (URLs, auth, notes)
    pipeline.json           central thresholds (detector, adjudication, FDR, benchmark)
  docs/
    SOURCES.md               all data sources & access methods
    MISSIONS.md              mission/instrument + resolution reference
    METHODOLOGY.md           the investigation protocol
    ARTIFACTS.md             known false-anomaly catalog (must-check list)
  scripts/
    download_nasa_library.py  images.nasa.gov search (image/video/audio)
    download_rover.py         Perseverance/Curiosity/others raw imagery
    download_hirise.py        MRO HiRISE catalog + full-res fetch
    download_lroc.py          LRO LROC NAC/WAC via PDS crawl
    download_pds.py           generic parallel PDS HTTP crawler (+ provenance manifest)
    download_archive.py       curated hard-to-find archives (CTX/MOC/Viking/LO/Clementine/M3/THEMIS)
    sources.py                registry behind download_archive.py
    build_catalog.py          index everything with hashes + solar geometry + immutable snapshot
    verify_downloads.py       integrity + duplicate check
    check_stereo.py           stereo-parallax check of a candidate (3D or flat?)
    run_pipeline.py           orchestrate the whole flow (+ --selftest)
  pipeline/
    common.py                 hardened infra: audit, hashing, atomic writes, config, stats
    pds.py                    native PDS3/PDS4 + .IMG EDR reader (endianness, bit masks, BIL/BIP)
    metadata.py               solar/geometry metadata from product labels (px scale, sun vector)
    photometry.py             Lambert/Lommel-Seeliger normalization, shadow-direction scoring
    stereo.py                 block-matching disparity, relief, anaglyphs
    changedet.py              phase-correlation registration + change/residual maps
    enhance.py                stretch, denoise, sharpen, upscale, --native16
    stack.py                  sigma-clipped stacking + column destriping
    detect.py                 multi-scale local-contrast anomaly flagging (box or annulus)
    mark.py                   draw anomaly boxes onto copies of the images
    analyze.py                AI analysis: enhance, measure, artifact-check, rank, investigate
    triage.py                 HTML review page with zoomed, boxed thumbnails
    benchmark.py              injected-blob sensitivity calibration + negative controls
    adjudicate.py             cross-band confirmation, persistence, shape, sun-shadow, verdicts, leads
  bot/
    discord_bot.py            Discord bot: upload an image -> pipeline verdict (optional)
  tests/
    test_pipeline.py          stdlib unit tests (common, detect, benchmark, adjudicate, pds, ...)
  data/                       raw/, processed/, catalog/, anomalies/
    anomalies/marked/         images with anomaly boxes drawn on them
    anomalies/analysis/       per-candidate enhancement strips + evaluation report
    anomalies/benchmark/      sensitivity calibration report
    anomalies/conclusions/    adjudicated verdicts, top leads, per-lead reports
    anomalies/audit.jsonl     machine-readable audit trail of every run
  findings/                   structured reports (only after methodology satisfied)
```

## Quickstart

From the project root:

```
pip install -r requirements.txt

python scripts/download_nasa_library.py --query "apollo" --max 100 --out data/raw
python scripts/build_catalog.py
python scripts/verify_downloads.py

python pipeline/enhance.py  --dir data/raw --out data/processed
python pipeline/detect.py   --dir data/processed --out data/anomalies
python pipeline/mark.py     --candidates data/anomalies/candidates.csv --out data/anomalies/marked
python pipeline/analyze.py  --candidates data/anomalies/candidates.csv --out data/anomalies/analysis
python pipeline/triage.py   --candidates data/anomalies/candidates.csv --out data/anomalies/triage
python pipeline/benchmark.py --out data/anomalies/benchmark
python pipeline/adjudicate.py --candidates data/anomalies/candidates.csv --evaluated data/anomalies/analysis/evaluated.csv --out data/anomalies/conclusions
```

or run it all at once:

```
python scripts/run_pipeline.py --query "moon"
```

More specific acquisition:

```
python scripts/download_rover.py  --rover perseverance --sol 1000 --num 50
python scripts/download_hirise.py --update-catalog
python scripts/download_hirise.py --list --search "crater" --catalog data/catalog/hirise_catalog.json
python scripts/download_hirise.py --fetch PSP_005800_2210
python scripts/download_lroc.py   --max 30
python scripts/download_pds.py --volume https://pds-imaging.jpl.nasa.gov/data/lro/lroc/edr/ --pattern "NAC.*\\.IMG$" --max 10 --out data/raw/moon/lroc

# hard-to-find archives
python scripts/download_archive.py --list
python scripts/download_archive.py --source ctx   --mode browse --max 40 --out data/raw/mars/ctx
python scripts/download_archive.py --source themis --mode edr --max-size-mb 250
```

After any acquisition: `build_catalog.py` (record hashes + solar geometry) then
`build_catalog.py --snapshot` to freeze `data/raw`. Before trusting old data,
run `build_catalog.py --check-immutable`.

## Discord bot

Upload a Moon/Mars image to the bot and it runs the pipeline on it and replies
with a marked-up image and a plain-language verdict for the top candidates.
Preliminary, single-image findings only — never a confirmation.

```
pip install -r requirements-extras.txt     # brings discord.py
$env:DISCORD_TOKEN = "<bot token from Discord Developer Portal>"
python bot/discord_bot.py
```

Standalone test without Discord:

```
python bot/discord_bot.py --analyze data/processed/some_image.png
```

Guards: only raster attachments, ~25 MB cap, downscaled to 4 Mpix, one analysis
at a time, pipeline runs off the event loop, honest disclaimer on every reply.

## 3D confirmation of a candidate

```
python scripts/check_stereo.py --left pair_a.png --right pair_b.png \
    --candidates data/anomalies/candidates.csv --box 0 \
    --altitude-km 300 --baseline-km 1.2 --out data/anomalies/stereo
```

Block-matching disparity across a stereo pair: real topography shifts against
the surrounding ground (implied height reported in meters); a 2D albedo/shadow
patch is flat in disparity. Outputs `disparity.png` + `anaglyph.png`.

## Native PDS ingestion

`pipeline/pds.py` reads `.IMG` EDRs directly — no pre-conversion needed. It
handles PDS3 labels and PDS4 XML, MSB/LSB signed/unsigned ints and IEEE real,
sample bit masks (e.g. 12-bit data packed in 16-bit), BSQ/BIL/BIP band layouts,
line prefix/suffix, LUTs, and attached/detached labels. Missing values become
NaN. `pipeline/metadata.py` then extracts solar elevation/azimuth, pixel scale,
spacecraft altitude, incidence/emission/phase angles from the label, which
drives the photometric shadow check and physical-size estimates.

## Reading the outputs

- `data/catalog/catalog.csv` — every file with mission, dimensions, sha256, and solar/geometry metadata parsed from the label; `data/catalog/immutable.json` is the ingest-time hash snapshot for `--check-immutable`.
- `data/raw/manifest.jsonl` — provenance record (URL, sha256, bytes, timestamp, source) for every verified download.
- `data/anomalies/candidates.csv` — regions flagged by `detect.py` (x, y, w, h, fill, score). Coordinates are in the pixels of the enhanced image.
- `data/anomalies/marked/` — `marked_*.png` copies of every image with the candidate boxes drawn on them.
- `data/anomalies/analysis/` — AI analysis of every candidate: enhanced crop strips (stretch/residual/upscale), measured features, artifact-checklist verdict, evidence class and interest score, cross-frame confirmation, and an HTML investigation report (`analysis/report.html`).
- `data/anomalies/triage/index.html` — open in a browser: thumbnail per image with boxes overlaid.
- `data/anomalies/benchmark/benchmark_synthetic.md` — injected-blob sensitivity calibration (recall per blob size) plus the negative-control FP count on the clean scene; `benchmark_*.csv` per scene.
- `data/anomalies/conclusions/adjudicated.csv` — every candidate with its adjudication: cross-band agreement, denoising persistence, shape compactness, local terrain texture, adjudicated score and verdict (`EXPLAINED-ARTIFACT` / `TERRAIN` / `CONFIRMED-LEAD` / `PROMISING` / `WEAK` / `NOISE`).
- `data/anomalies/conclusions/leads/` — per-lead `F-*.md` reports following the finding template, each with enhancement-strip evidence.
- `data/anomalies/conclusions/SUMMARY.md` — the bottom-line conclusion funnel.
- `findings/` — only conclusions that survived the protocol.

## AI analysis step

`analyze.py` runs entirely offline with numpy/PIL:

- **Enhance by any means** — every candidate crop is independently enhanced three ways (percentile stretch, local residual vs. blurred background, unsharpened upscale) and tiled into a review strip.
- **Evaluate** — physical/image features are measured (contrast vs. local background, polarity, size, aspect, fill, saturation, 8px-grid alignment, edge proximity) and checked against the known-artifact checklist in `docs/ARTIFACTS.md`. Each candidate gets a verdict, an evidence class (1=artifact, 2=weak, 3=seen in related frames) and a 0-100 interest score.
- **Investigate** — candidates in same-size sibling products of one footprint (e.g. HiRISE band variants) are cross-checked at matching coordinates; features confirmed in 2+ frames are marked class 3.
- **Optional vision LLM second opinion** — `python pipeline/analyze.py --llm` sends the top-N strips to a vision model. Configure via env: `AI_LLM_KEY`, `AI_LLM_ENDPOINT` (OpenAI-compatible), `AI_LLM_MODEL`.

Remember: none of this is a finding. A candidate becomes a finding only after the full methodology below is satisfied.

## Calibration (`benchmark.py`)

Before trusting any candidate, calibrate what the detector can actually see:

- Injects Gaussian bright/dark blobs of known size into a controlled synthetic textured scene and into a real image, runs the real detector, and reports recall per blob size.
- The negative-control run counts false positives on the clean scene; that number is the baseline every candidate must beat.
- Result on the current data: ~24 px recall floor with 0 FPs on the synthetic scene, but ~279 detections on a clean HiRISE image — i.e. on textured terrain the detector is background-limited and small candidates are unreliable.

## Adjudication (`adjudicate.py`)

Brings the candidate list toward a conclusion using the confirmation methods the methodology demands:

- **Pixel-level cross-band agreement** — for same-size sibling products of one footprint (e.g. HiRISE MIRB/MRGB/RED), verifies the feature actually exists at the same pixels in each sibling with the same polarity and comparable contrast. Confirms "real surface feature" (shared across bands) without overclaiming: shared processing can still imprint common artifacts.
- **Enhancement persistence** — re-measures contrast after median denoising; hot pixels/compression speckle vanish, extended features survive.
- **Shape compactness** — separates round/donut-like features from ridges and detector scratches.
- **Local terrain texture** — a discrete feature in otherwise smooth ground is far more interesting than one inside a crater field.
- **Solar-geometry shadow check** — with metadata from the product label, each candidate's shadow direction is scored against the solar azimuth, its physical size estimated from pixel scale, and its height implied from shadow length. A shadow that disagrees with the sun marks the candidate down; a physically absurd implied size does too.
- Outputs a verdict funnel and per-lead reports; `SUMMARY.md` states the honest bottom line. Top leads get enhancement strips in `conclusions/strips/`.

No adjudication is a finding: cross-band agreement is one acquisition, one processing chain. Confirmation still requires the EDR original, a mosaic/Trek cross-check, and an independent pass at different lighting.

## Control your detector first

Tune `detect.py` (`--z`, `--min-size`, `--scales`) on known-clean images until the
false-positive rate is near zero, and test it on images with injected synthetic
blobs to measure sensitivity. Lower `--z` and `--min-size` to surface more
candidates (and more false positives); add finer scales with `--scales 4,2,1`.
Details in `docs/METHODOLOGY.md`.

## Hardening & statistical controls

The pipeline is hardened so a result can be audited and reproduced:

- **Config-driven** — thresholds live in `config/pipeline.json` (detector z/min-size/scales, adjudication contrast bar, area range, FDR q, benchmark sizes/seed). CLI flags override the file.
- **Audit trail** — every `benchmark` / `analyze` / `adjudicate` run appends a JSONL record to `data/anomalies/audit.jsonl` with the exact command, parameters, SHA-256 of every input/output CSV, verdict counts and run time. Any claimed result can be traced to the exact data it was computed from.
- **Crash-safe writes** — CSVs/reports are written to a temp file, fsynced, then atomically renamed (`common.atomic_*_write`); a crash never leaves a half-written table.
- **Deterministic** — a single `common.set_seed` seeds all RNGs; the synthetic benchmark scene is reproducible.
- **Defensive validation** — `common.validate_box` rejects out-of-bounds/malformed candidate coordinates before analysis; `common.contain_path` guards path traversal.
- **Multiple-comparison control** — `adjudicate.py` converts each candidate's contrast into a one-sided z-score p-value (`common.z_pvalue`) and corrects the whole tested set with Benjamini-Hochberg (`common.benjamini_hochberg`). At q=0.05, 42/2102 non-artifact candidates survive — the top lead itself is q≈0.16, i.e. it does **not** survive.
- **Negative-control baselines per image** — benchmark FP counts are attached to every candidate; e.g. ESP_093498_2095_MRGB's 279 candidates exactly match its 279 clean-scene false positives, i.e. that image is at the pipeline's own noise floor.
- **Stress test** — the top-lead count is reported as the contrast bar tightens (160 → 41 → 6 → 0 across 1.0/1.5/2.0/2.5): the conclusion must not live or die on a single threshold.
- **Self-test** — `python scripts/run_pipeline.py --selftest` runs the 29-case stdlib test suite in `tests/test_pipeline.py` (z-pvalue, BH-FDR, validation, hashing, atomic writes, detector recall, blob injection, adjudication persistence/verdict/roundness).

## Chain of custody

`data/raw/` is read-only after download. Every file is hashed into the catalog,
so any claim can be traced back to an official source URL. Never work from
social-media reposts — always go to the EDR/PDS original.
