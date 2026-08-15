# Mission & instrument reference

## Lunar

| Mission | Instrument | Spatial res | Notes |
|---|---|---|---|
| Lunar Reconnaissance Orbiter (LRO) | LROC NAC | 0.5–2 m/px | two push-broom cameras, EDR/RDR; highest-res lunar surface data |
| LRO | LROC WAC | ~100 m/px | global color + mono mosaics |
| LRO | LOLA (lidar) | 5 m spot | elevation, useful to check topography of finds |
| LRO | Mini-RF | 150 m | radar, subsurface signatures |
| Apollo 15/16/17 | Hasselblad 70mm | surface film | original film scans in ASU/Flickr archives |
| Apollo 15–17 | Panoramic camera | ~1–2 m/px | high-res orbital film scans |
| Clementine | UVVIS | 100–200 m/px | 1990s global color |
| Kaguya (SELENE) | Terrain Camera (TC) | 10 m/px | stereo, JAXA PDS |
| Clementine | NIR / HIRES | 100–200 m/px / up to 20 m/px | 1994 global + targeted |
| Chandrayaan-1 | Moon Mineralogy Mapper (M3) | ~140–280 m/px | NASA instrument; 85-band hyperspectral reflectance cubes (PDS) |
| Lunar Orbiter I–V | film framing camera | 1–60 m/px (digitized ~60–90 m/px) | 1966–67; ~99% of lunar surface |
| Apollo 15–17 | Metric camera | ~20 m/px | orbital stereo for elevation extraction |

## Mars

| Mission | Instrument | Spatial res | Notes |
|---|---|---|---|
| Mars Reconnaissance Orbiter (MRO) | HiRISE | 0.25–0.5 m/px | best Mars surface resolution; RED/IR/BG CCDs, JP2 products |
| MRO | CTX | ~6 m/px | context mosaics for geolocation |
| MRO | MARCI | global daily | weather/clouds |
| Mars Express | HRSC | 10–20 m/px | stereo, DTM |
| Perseverance (M2020) | Mastcam-Z, Navcam, SuperCam, EDL cams | cm–m | surface imagery, raw available by sol |
| Curiosity (MSL) | Mastcam, MAHLI, Navcam, Hazcam | cm–m | surface imagery by sol |
| Orbiters past | Viking, MOC (MGS) | 1.5–100 m | historical; useful for change detection |
| Mars Odyssey | THEMIS VIS / IR | ~18 m / ~100 m | IR = thermal inertia, geophysical differences invisible in visible light |

## Why resolution/geometry matter
- An "object" must be resolved beyond the pixel scale of the instrument to be real;
  a 0.5 m object in a 0.5 m/px image is borderline, in a 6 m/px CTX image it is sub-pixel.
- Foreshortening: features near the limb/edge are compressed and distorted.
- Parallax: compare stereo pairs — real 3D features shift relative to the surface, artifacts do not.
- Light direction: solar incidence angle controls shadow geometry; a shadowed object looks different between morning/evening passes.

## Camera model / metadata to always record
- Product ID, instrument, CCD (e.g., NAC_L/NAC_R, HiRISE RED0/1/2)
- Earth_date / sol / UTC time of acquisition
- Solar azimuth & incidence, emission angle, sub-spacecraft point
- Whether the product is EDR (raw) or RDR (map-projected/calibrated)
