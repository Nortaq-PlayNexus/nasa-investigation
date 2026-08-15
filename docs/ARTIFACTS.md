# Known artifacts — the checklist

Before recording anything, rule out these. Each is a well-documented cause of
false "anomalies" in planetary imagery. Note in the finding report which were
checked and why they don't apply.

## Sensor / camera
- **Cosmic ray hits**: bright single pixels / short streaks, random orientation; common in orbital CCDs. Verify by checking neighbors and the same spot in a second frame.
- **Hot pixels / bad columns**: reproducible, fixed position across frames — identical across multiple images of the same scene = sensor, not object.
- **Column/row defects and dead bands**: fixed stripes.
- **Calibration / zero-area strips**: detector edges, trailing-edge dark areas often wrongly read as "craters" or "objects".
- **Blooming / smear**: charge spill along a column from a bright source.
- **Dust or debris on optics**: out-of-focus donuts or smears that repeat in the same position of every frame regardless of target.

## Compression & processing
- **JPEG/JP2 lossy artifacts**: blocking, ringing, mosquito noise around edges. Use EDR (lossless) when available; never zoom into JPEG compression as "structure".
- **Decompression errors**: JP2 software differences produce grid or wavy artifacts.
- **Stitching seams**: panoramas/mosaics mismatch brightness across frame boundaries.
- **Map projection artifacts**: warping near poles/limb, oversampling, resampling ringing.
- **Bit-flip / telemetry corruption**: random noise bars, vertical striping, dropped rows.

## Optics & lighting
- **Lens flare / internal reflections**: arcs, glows, secondary ghosts; follow the Sun direction.
- **Vignetting**: dark corners mistaken for clouds/shadow.
- **Shadow geometry**: long shadows from terrain; an object's own shadow. Check solar azimuth and incidence angles.
- **Foreshortening** at limb/oblique angles: features look elongated/compressed.

## Hardware in frame
- Spacecraft booms, arms, wheels, mast, antenna, parachute, heat shield, backshell, sky crane, footpads, MOXIE, RTG etc. Rover/lander frames frequently contain their own hardware.
- Landing hardware in remote images: parachute + backshell + descent stage + heat shield are large and look anomalous to the untrained eye. NASA publishes their exact locations.

## Human & narrative artifacts
- **Copy/meme sources**: a "UFO in an Apollo photo" is often just a rescanned, recompressed copy of an original — compare pixel-for-pixel to the archive scan.
- **Highlights & blown-out regions**: film/sensor saturation flattens to pure white; white blobs inside blown highlights are not objects.
- **Film grain / scratches / dust on negatives** in old Apollo scans.
- **Misattribution**: images of Earth, launch vehicles, ISS, or Earth-circling debris mislabeled as "from the Moon."

## Geometry & photometry checks (automated, then manual)
- **Shadow direction vs. solar azimuth**: every real object's shadow points away from the sun at the label's solar azimuth. A "structure" whose shadow direction disagrees is shadow geometry, relief illusion, or processing, not an object. `photometry.shadow_alignment` scores this; `adjudicate.py` folds it into the verdict.
- **Sun elevation vs. shadow length**: an object's height can be estimated from its shadow length and solar elevation (`metadata.height_from_shadow_len`). An implied height wildly inconsistent with the feature's own size (or > terrain relief) argues against a discrete object.
- **Stereo parallax**: a real elevated feature shifts between the two frames of a stereo pair; a 2D albedo/shadow patch does not. No parallax → not elevated. (This is the single strongest debunker for "towers/pyramids".)
- **Photometric consistency**: normalized reflectance (Lambert/Lommel-Seeliger) should be roughly angle-independent across passes. A feature that only "appears" at grazing sun angles is relief illusion.
- **Thermal inertia**: THEMIS-IR-only brightness differences at a spot that looks ordinary in visible light indicate material/density differences (geophysical), not engineered structure.

## The default conclusion
For every candidate, the null hypothesis is: **known artifact, reproducible, explained by physics or instrument**. Extraordinary claims require you to defeat that null hypothesis in writing, in the finding report, with references to the specific images and metadata.
