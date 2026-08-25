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
CONFIRMED-LEAD: 1163 &middot; EXPLAINED-ARTIFACT: 1326 &middot; NOISE: 494 &middot; PROMISING: 674 &middot; TERRAIN: 1110 &middot; WEAK: 3059

## Multiple-comparison control
Approximate per-candidate p-values (contrast as a local-sigma z-score) corrected with Benjamini-Hochberg at q=0.05: 37/6500 non-artifact candidates survive. Cross-band-confirmed features have low contrast (median ~1.0), so almost none clear the corrected threshold.

## Stress test (robustness of the top-lead count)
| contrast bar | top leads |
|---|---|
| 1.00 | 563 |
| 1.25 | 408 |
| 1.50 | 296 |
| 1.75 | 170 |
| 2.00 | 98 |
| 2.50 | 45 |
| 3.00 | 23 |

## Top leads (296)
Cross-band confirmed, discrete, contrast >= 1.50, off-border, size 200-50000 px.

- **ESP_013236_1410_MIRB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.77, 2 band agrees
- **ESP_013236_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.86, 2 band agrees
- **ESP_013236_1410_MRGB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.77, 2 band agrees
- **ESP_013236_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.86, 2 band agrees
- **ESP_013236_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5296, score 100.0, contrast 3.88, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1276 y=2732, score 100.0, contrast 3.88, 2 band agrees
- **ESP_013948_1410_MIRB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=2084 y=9972, score 100.0, contrast 3.49, 2 band agrees
- **ESP_013948_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5516, score 100.0, contrast 3.97, 2 band agrees
- **ESP_013948_1410_MRGB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=2084 y=9972, score 100.0, contrast 3.64, 2 band agrees
- **ESP_013948_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5516, score 100.0, contrast 3.95, 2 band agrees
- **ESP_013948_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5516, score 100.0, contrast 3.94, 2 band agrees
- **ESP_013236_1410_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.6, contrast 3.5, 2 band agrees
- **ESP_013236_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.2, contrast 3.45, 2 band agrees
- **ESP_013236_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=752 y=5100, score 99.2, contrast 3.45, 2 band agrees
- **ESP_013948_1410_MIRB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5712, score 97.7, contrast 3.4, 2 band agrees
- **ESP_013948_1410_MRGB.abrowse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5712, score 97.7, contrast 3.4, 2 band agrees
- **ESP_013948_1410_RED.abrowse_enh.png** (CONFIRMED-LEAD): high, x=728 y=5712, score 96.9, contrast 3.31, 2 band agrees
- **ESP_013948_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=2084 y=9776, score 96.8, contrast 3.03, 2 band agrees
- **ESP_013948_1410_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1312 y=4128, score 96.0, contrast 3.05, 2 band agrees
- **ESP_013948_1410_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1312 y=4128, score 95.8, contrast 3.02, 2 band agrees

### Top leads by image
- ESP_013236_1410_IRB.NOMAP.browse_enh.png: 26 top leads
- ESP_013236_1410_MRGB.browse_enh.png: 24 top leads
- ESP_013236_1410_MIRB.browse_enh.png: 23 top leads
- ESP_013948_1410_MIRB.browse_enh.png: 23 top leads
- ESP_013948_1410_MRGB.browse_enh.png: 22 top leads
- ESP_013948_1410_RED.browse_enh.png: 22 top leads
- ESP_013236_1410_RED.browse_enh.png: 19 top leads
- ESP_013948_1410_IRB.NOMAP.browse_enh.png: 17 top leads
- ESP_013236_1410_RGB.NOMAP.browse_enh.png: 16 top leads
- ESP_013236_1410_RED.abrowse_enh.png: 15 top leads
- ESP_013948_1410_RED.abrowse_enh.png: 14 top leads
- ESP_013236_1410_MRGB.abrowse_enh.png: 12 top leads
- ESP_013948_1410_MRGB.abrowse_enh.png: 12 top leads
- ESP_013948_1410_RGB.NOMAP.browse_enh.png: 12 top leads
- ESP_013236_1410_MIRB.abrowse_enh.png: 11 top leads
- ESP_013948_1410_MIRB.abrowse_enh.png: 11 top leads
- ESP_013236_1410_RED.thumb_enh.png: 2 top leads
- ESP_013236_1410_RGB.NOMAP.thumb_enh.png: 2 top leads
- ESP_013948_1410_RGB.NOMAP.thumb_enh.png: 2 top leads
- ESP_013948_1410_RED_C_01_ORTHO.th_enh.png: 2 top leads
- ESP_013236_1410_MRGB.thumb_enh.png: 1 top leads
- ESP_013236_1410_MIRB.thumb_enh.png: 1 top leads
- ESP_013948_1410_RED.thumb_enh.png: 1 top leads
- ESP_013236_1410_RED_C_01_ORTHO.th_enh.png: 1 top leads
- ESP_013948_1410_RED_C_01_ORTHO.ab_enh.png: 1 top leads
- ESP_013236_1410_IRB.NOMAP.thumb_enh.png: 1 top leads
- ESP_013948_1410_IRB.NOMAP.thumb_enh.png: 1 top leads
- ESP_013236_1410_RED_C_01_ORTHO.ab_enh.png: 1 top leads
- ESP_013236_1410_IRB_C_01_ORTHO.ab_enh.png: 1 top leads

### Per-image baseline context
No benchmark baselines available for these images.

## Why the funnel matters
- 1326 candidates are explained by a known artifact mechanism (streak, hot pixel, compression grid, edge, saturation).
- 1110 are real surface features confirmed at the same pixels in several band variants of one acquisition, but their shape/scale is ordinary terrain.
- Only 296 discrete features survive the contrast bar, and none of them sits in genuinely smooth ground: on this data, everything discrete is embedded in cratered/ridged terrain, i.e. consistent with craters and rocks.

## Bottom line
After this pass, **no candidate meets the bar for a finding**. Cross-band agreement confirms a feature across band variants of ONE acquisition; it does not prove it is non-artifact, because the shared processing pipeline can imprint common artifacts. The top leads above are the only candidates worth a human + LLM second look; confirming any of them requires fetching the EDR original, checking a global mosaic/Trek, and finding the feature in an independent acquisition at a different lighting before writing a finding to `findings/`.
