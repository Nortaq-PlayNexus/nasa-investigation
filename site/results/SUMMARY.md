# Adjudication conclusion

## What was done
Every candidate from `detect.py` (scales 4, z 3.0, min-size 12) was enhanced, measured and artifact-checked by `analyze.py`, then adjudicated here with:
- pixel-level cross-band agreement across same-size sibling products,
- enhancement persistence (does it survive median denoising),
- shape compactness,
- per-image negative-control baselines, and
- Benjamini-Hochberg false-discovery-rate control.

## Sensitivity calibration (benchmark.py)
On a controlled synthetic scene: recall floor ~24 px, 0 false positives.

## Verdict distribution
CONFIRMED-LEAD: 621 &middot; EXPLAINED-ARTIFACT: 407 &middot; NOISE: 154 &middot; PROMISING: 341 &middot; TERRAIN: 559 &middot; WEAK: 884

## Multiple-comparison control
Approximate per-candidate p-values (contrast as a local-sigma z-score) corrected with Benjamini-Hochberg at q=0.05: 35/2559 non-artifact candidates survive. Cross-band-confirmed features have low contrast (median ~1.0), so almost none clear the corrected threshold.

## Stress test (robustness of the top-lead count)
| contrast bar | top leads |
|---|---|
| 1.00 | 295 |
| 1.25 | 219 |
| 1.50 | 153 |
| 1.75 | 91 |
| 2.00 | 51 |
| 2.50 | 18 |
| 3.00 | 11 |

## Top leads (153)
Cross-band confirmed, discrete, contrast >= 1.50, off-border, size 200-50000 px.

- **ESP_013236_1410_MIRB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.77, 2 band agrees
- **ESP_013236_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.86, 2 band agrees
- **ESP_013236_1410_MRGB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.77, 2 band agrees
- **ESP_013236_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.86, 2 band agrees
- **ESP_013236_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.88, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.88, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.6, contrast 3.5, 2 band agrees
- **ESP_013236_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.2, contrast 3.45, 2 band agrees
- **ESP_013236_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.2, contrast 3.45, 2 band agrees
- **ESP_013236_1410_RED.thumb_enh.png** (CONFIRMED-LEAD): high, x=708 y=2532, score 91.1, contrast 2.52, 2 band agrees
- **ESP_013236_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3672, score 90.6, contrast 2.32, 2 band agrees
- **ESP_013236_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3672, score 90.6, contrast 2.32, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3672, score 90.4, contrast 2.3, 2 band agrees
- **ESP_013236_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3868, score 89.8, contrast 2.23, 2 band agrees
- **ESP_013236_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=548 y=4696, score 89.5, contrast 2.21, 2 band agrees
- **ESP_013236_1410_MRGB.thumb_enh.png** (CONFIRMED-LEAD): high, x=708 y=2532, score 89.0, contrast 2.28, 2 band agrees
- **ESP_013236_1410_MIRB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3868, score 88.7, contrast 2.15, 2 band agrees
- **ESP_013236_1410_MRGB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=1352 y=3868, score 88.7, contrast 2.15, 2 band agrees
- **ESP_013236_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=1072 y=3648, score 88.7, contrast 2.11, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1708 y=8952, score 88.7, contrast 2.21, 2 band agrees

### Top leads by image
- ESP_013236_1410_IRB.NOMAP.browse_enh.png: 26 top leads
- ESP_013236_1410_MRGB.browse_enh.png: 24 top leads
- ESP_013236_1410_MIRB.browse_enh.png: 23 top leads
- ESP_013236_1410_RED.browse_enh.png: 19 top leads
- ESP_013236_1410_RGB.NOMAP.browse_enh.png: 16 top leads
- ESP_013236_1410_RED.abrowse_enh.png: 15 top leads
- ESP_013236_1410_MRGB.abrowse_enh.png: 12 top leads
- ESP_013236_1410_MIRB.abrowse_enh.png: 11 top leads
- ESP_013236_1410_RED.thumb_enh.png: 2 top leads
- ESP_013236_1410_RGB.NOMAP.thumb_enh.png: 2 top leads
- ESP_013236_1410_MRGB.thumb_enh.png: 1 top leads
- ESP_013236_1410_MIRB.thumb_enh.png: 1 top leads
- ESP_013236_1410_IRB.NOMAP.thumb_enh.png: 1 top leads

### Per-image baseline context
No benchmark baselines available for these images.

## Why the funnel matters
- 407 candidates are explained by a known artifact mechanism (streak, hot pixel, compression grid, edge, saturation).
- 559 are real surface features confirmed at the same pixels in several band variants of one acquisition, but their shape/scale is ordinary terrain.
- Only 153 discrete features survive the contrast bar, and none of them sits in genuinely smooth ground: on this data, everything discrete is embedded in cratered/ridged terrain, i.e. consistent with craters and rocks.

## Bottom line
After this pass, **no candidate meets the bar for a finding**. Cross-band agreement confirms a feature across band variants of ONE acquisition; it does not prove it is non-artifact, because the shared processing pipeline can imprint common artifacts. The top leads above are the only candidates worth a human + LLM second look; confirming any of them requires fetching the EDR original, checking a global mosaic/Trek, and finding the feature in an independent acquisition at a different lighting before writing a finding to `findings/`.
