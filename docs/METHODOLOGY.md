# Investigation methodology

This project applies a disciplined, falsifiable process to searching public NASA
imagery for anything that stands out. The bar for claiming an anomaly is high on
purpose: nearly all "anomalies" in planetary imagery are known sensor, compression
or viewing artifacts. A rigorous process is what makes a genuine finding credible.

## Pipeline

1. **Acquire** — download only from official sources (see SOURCES.md), record URLs.
2. **Ingest & catalog** — `build_catalog.py` records path, mission, size, sha256, plus solar/geometry metadata parsed from the PDS label (`pipeline/pds.py`, `pipeline/metadata.py`).
3. **Verify** — `verify_downloads.py` confirms hashes, sizes, duplicates; `build_catalog.py --check-immutable` enforces that `data/raw` is byte-identical to the snapshot taken at ingest.
4. **Preprocess** — read native PDS/`.IMG` EDRs directly (`pipeline/pds.py` handles PDS3 labels, PDS4 XML, endianness, bit masks, BSQ/BIL/BIP), convert to 16-bit where possible, destripe/denoise, correct contrast.
5. **Enhance** — `enhance.py`: percentile stretch, denoise, unsharp, upscale, `--native16`.
6. **Stack** — `stack.py`: sigma-clipped median-stack repeated frames (`--clip`), column destriping (`--destripe`); residual maps highlight changes/transients.
7. **Detect** — `detect.py`: multi-scale local-contrast outlier flagging. `--method box` (classic) or `--method annulus` (each pixel vs. the annular ring around it — the "military-grade" background estimator that only flags things standing out against their immediate surroundings).
8. **Photometry & geometry** — `pipeline/photometry.py` normalizes for solar incidence (Lambert / Lommel-Seeliger), computes the sun-vector and shadow direction, and scores each candidate's **shadow alignment** with the sun. `pipeline/metadata.py` derives pixel scale, spacecraft altitude, solar elevation/azimuth from the product label so a shadow that disagrees with the sun marks a candidate *down*, and a physical object size can be estimated.
9. **Triage** — `triage.py`: HTML page of candidates with zoomed crops.
10. **Adjudicate** — for every candidate, work the artifact checklist (ARTIFACTS.md) before believing it; cross-band agreement, denoising persistence, compactness, terrain texture, solar-geometry shadow check, FDR correction (`pipeline/adjudicate.py`).
11. **3D check** — `scripts/check_stereo.py` runs block-matching stereo disparity on a candidate within a stereo pair: real topography shows parallax against the surrounding ground, a 2D albedo/shadow patch does not.
12. **Change detection** — `pipeline/changedet.py` phase-correlates two frames of one site, registers them, and maps only the residuals that remain after alignment (same-lighting, same-season passes).
13. **Confirm** — find independent confirmation before recording a finding.

## Controls (do these, they make the search meaningful)

- **Negative controls**: run `detect.py` on known-clean calibration frames and a random sample of "boring" terrain. Anything it flags there is a false-positive baseline; tune `--z` and `--min-size` until the baseline is near zero.
- **Synthetic positives (injection)**: draw a few simulated bright/shadowed blobs of known size into images, run the detector, and measure recall (what fraction you catch) and precision. This tells you what your pipeline can actually see at a given pixel scale.
- **Blind review**: have a second person triage candidates without knowing which images they came from. Only candidates both reviewers flag proceed.

## Confirmation standard

A candidate becomes a **finding** only when:
- It survives the full artifact checklist with documented reasoning, AND
- It is seen in at least one **independent image** (different pass, angle, or lighting), AND
- Its size and position are physically consistent across those images (checked via map projection / Trek overlays), AND
- It was flagged independently in blind review.

## Evidence grading

| Class | Meaning |
|---|---|
| 4 | Unexplained after all checks; consistent across independent images; strongest claim level |
| 3 | Candidate; survives artifact checks but only seen in one image / one angle |
| 2 | Weak candidate; plausible artifact not fully excluded |
| 1 | Explained artifact or geometry |
| 0 | Hoax / retouched / meme-source / misattributed |

## Rules

- Never claim without provenance (source URL + product ID + hash).
- Never "enhance" until the original is documented; always keep originals unmodified (data/raw is read-only after download).
- Never cite processed JPEGs from social media as primary evidence; go to the EDR.
- Record lighting geometry — the #1 cause of apparent "new objects" is different sun angle between passes.
- If a candidate disappears under a different lighting/pass, it is shadow or artifact, not object.
- A candidate whose shadow direction disagrees with the solar azimuth is self-invalidating.
- A candidate that shows no stereo parallax against its surroundings is 2D (albedo/shadow/artifact), not elevated — no matter how it looks.
- Thermal inertia differences (THEMIS IR) that do not show in visible light are geophysical, not structural, evidence.

## Change detection caveats

`changedet.py` aligns two frames by phase correlation and reports residuals.
These are *always* expected and almost always mundane:
- Different sun angle (even 1°) shifts shadow length and moves shadow/shine boundaries.
- Different season → different frost/thermal state and dust redistribution.
- Different resolution/phase → resampling ringing, not ground change.
Only a residual that survives (a) tight registration, (b) same-lighting
acquisition (compare solar elevation and azimuth in the labels first), and
(c) stereo/flatness checks, is worth investigating.
