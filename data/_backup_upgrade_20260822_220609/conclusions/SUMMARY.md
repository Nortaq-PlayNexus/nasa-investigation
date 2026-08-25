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
CONFIRMED-LEAD: 3148 &middot; EXPLAINED-ARTIFACT: 6451 &middot; NOISE: 3732 &middot; PROMISING: 5924 &middot; TERRAIN: 4923 &middot; WEAK: 14179

## Multiple-comparison control
Approximate per-candidate p-values (contrast as a local-sigma z-score) corrected with Benjamini-Hochberg at q=0.05: 1484/31906 non-artifact candidates survive. Cross-band-confirmed features have low contrast (median ~1.0), so almost none clear the corrected threshold.

## Stress test (robustness of the top-lead count)
| contrast bar | top leads |
|---|---|
| 1.00 | 1648 |
| 1.25 | 1156 |
| 1.50 | 724 |
| 1.75 | 448 |
| 2.00 | 249 |
| 2.50 | 82 |
| 3.00 | 29 |

## Top leads (724)
Cross-band confirmed, discrete, contrast >= 1.50, off-border, size 200-50000 px.

- **ESP_093491_1770_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=940 y=2392, score 100.0, contrast 4.32, 2 band agrees
- **ESP_093491_1770_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=940 y=2392, score 100.0, contrast 4.32, 2 band agrees
- **ESP_093491_1770_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=940 y=2392, score 100.0, contrast 4.64, 2 band agrees
- **ESP_093494_2015_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=2564 y=4044, score 99.5, contrast 3.61, 2 band agrees
- **ESP_093494_2015_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=2564 y=4044, score 99.5, contrast 3.61, 2 band agrees
- **ESP_093494_2015_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=2044 y=3732, score 98.3, contrast 3.35, 2 band agrees
- **ESP_093494_2015_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=2044 y=3732, score 98.3, contrast 3.35, 2 band agrees
- **ESP_093494_2015_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=2044 y=3732, score 98.3, contrast 3.35, 2 band agrees
- **ESP_093493_1390_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=2896 y=684, score 98.0, contrast 3.19, 2 band agrees
- **ESP_093493_1390_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=2896 y=684, score 98.0, contrast 3.19, 2 band agrees
- **ESP_093494_2015_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=2540 y=8944, score 97.1, contrast 3.13, 2 band agrees
- **ESP_093497_1560_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1204 y=2188, score 96.8, contrast 3.14, 2 band agrees
- **ESP_093497_1560_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1204 y=2188, score 96.8, contrast 3.14, 2 band agrees
- **ESP_093494_2015_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=2540 y=8944, score 96.6, contrast 3.07, 2 band agrees
- **ESP_093494_2015_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=2564 y=4044, score 96.4, contrast 3.71, 2 band agrees
- **ESP_093494_2015_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=1404 y=8976, score 95.9, contrast 2.94, 2 band agrees
- **ESP_093494_2015_MRGB.browse_enh.png** (CONFIRMED-LEAD): high, x=1404 y=8976, score 95.9, contrast 2.94, 2 band agrees
- **ESP_093494_2015_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1120 y=7160, score 95.5, contrast 3.15, 2 band agrees
- **ESP_093497_1560_RED.browse_enh.png** (CONFIRMED-LEAD): high, x=1208 y=2188, score 95.4, contrast 2.93, 2 band agrees
- **ESP_093487_1780_MIRB.browse_enh.png** (CONFIRMED-LEAD): high, x=2512 y=3948, score 95.2, contrast 3.37, 2 band agrees

### Top leads by image
- ESP_093494_2015_RED.browse_enh.png: 94 top leads
- ESP_093494_2015_MRGB.browse_enh.png: 92 top leads
- ESP_093494_2015_MIRB.browse_enh.png: 90 top leads
- ESP_093487_1780_RED.browse_enh.png: 36 top leads
- ESP_093487_1780_MIRB.browse_enh.png: 35 top leads
- ESP_093487_1780_MRGB.browse_enh.png: 32 top leads
- ESP_093493_1390_RED.browse_enh.png: 27 top leads
- ESP_093497_1560_RED.browse_enh.png: 24 top leads
- ESP_093493_1390_MIRB.browse_enh.png: 22 top leads
- ESP_093493_1390_MRGB.browse_enh.png: 22 top leads
- ESP_093497_1560_MIRB.browse_enh.png: 20 top leads
- ESP_093492_2070_MRGB.browse_enh.png: 20 top leads
- ESP_093497_1560_MRGB.browse_enh.png: 18 top leads
- ESP_093492_2070_RED.browse_enh.png: 18 top leads
- ESP_093492_2070_MIRB.browse_enh.png: 14 top leads
- ESP_093497_1980_RED.browse_enh.png: 13 top leads
- ESP_093497_1980_MIRB.browse_enh.png: 13 top leads
- ESP_093491_1770_RED.browse_enh.png: 12 top leads
- ESP_093497_1980_MRGB.browse_enh.png: 12 top leads
- ESP_093498_2095_MIRB.browse_enh.png: 10 top leads
- ESP_093491_1770_MRGB.browse_enh.png: 9 top leads
- ESP_093490_1440_RED.browse_enh.png: 9 top leads
- ESP_093498_2095_RED.browse_enh.png: 9 top leads
- ESP_093495_2105_MRGB.browse_enh.png: 8 top leads
- ESP_093495_2105_MIRB.browse_enh.png: 8 top leads
- ESP_093495_2105_RED.browse_enh.png: 7 top leads
- ESP_093498_2095_MRGB.browse_enh.png: 7 top leads
- ESP_093491_1770_MIRB.browse_enh.png: 6 top leads
- ESP_093490_1440_MIRB.browse_enh.png: 6 top leads
- ESP_093490_1440_MRGB.browse_enh.png: 6 top leads
- ESP_093496_1465_MIRB.browse_enh.png: 6 top leads
- ESP_093496_1465_RED.browse_enh.png: 6 top leads
- ESP_093496_1465_MRGB.browse_enh.png: 4 top leads
- ESP_093491_1055_MRGB.browse_enh.png: 2 top leads
- ESP_093489_2195_RED.browse_enh.png: 1 top leads
- ESP_093491_1055_MIRB.browse_enh.png: 1 top leads
- ESP_093492_1235_RED.browse_enh.png: 1 top leads
- ESP_093495_1450_MRGB.browse_enh.png: 1 top leads
- ESP_093491_1055_RED.browse_enh.png: 1 top leads
- ESP_093498_1385_RED.browse_enh.png: 1 top leads
- ESP_093495_1450_RED.browse_enh.png: 1 top leads

### Per-image baseline context
No benchmark baselines available for these images.

## Why the funnel matters
- 6451 candidates are explained by a known artifact mechanism (streak, hot pixel, compression grid, edge, saturation).
- 4923 are real surface features confirmed at the same pixels in several band variants of one acquisition, but their shape/scale is ordinary terrain.
- Only 724 discrete features survive the contrast bar, and none of them sits in genuinely smooth ground: on this data, everything discrete is embedded in cratered/ridged terrain, i.e. consistent with craters and rocks.

## Chase findings
85 chase finding reports (F-0001 through F-0085) are in `leads/`. Each links the enhanced source, its enhancement strip and the boxed full-resolution image. The chase found surface features that genuinely persist in the originals, but every one is ordinary geology (fresh craters, boulders, albedo patches) or a known CCD/compression artifact (LROC streaks, hot pixels, grids).

## Bottom line
After this pass, **no candidate meets the bar for a finding**. Cross-band agreement confirms a feature across band variants of ONE acquisition; it does not prove it is non-artifact, because the shared processing pipeline can imprint common artifacts. The top leads above are the only candidates worth a human + LLM second look; confirming any of them requires fetching the EDR original, checking a global mosaic/Trek, and finding the feature in an independent acquisition at a different lighting before writing a finding to `findings/`.
