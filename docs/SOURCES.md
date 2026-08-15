# Data sources registry

Every source below is public U.S. government or partner planetary-science data.
Always prefer **original/raw (EDR) products** over press-release JPEGs: EDRs keep
sensor bit-depth, radiometric fidelity and full metadata. JPEG/JP2 lossy
compression creates artifacts that look like "anomalies".

## Image & video library
| Source | URL | Access | Notes |
|---|---|---|---|
| NASA Images library | https://images.nasa.gov | `download_nasa_library.py` | search API, no key; supports image/video/audio |
| NASA Images API | https://images-api.nasa.gov | HTTP GET `/search?q=...` | JSON, paginated |
| NASA media collections | https://api.nasa.gov | optional free key | also hosts other APIs |

## Moon
| Source | URL | What | Access |
|---|---|---|---|
| LROC EDR (LRO) | https://pds-imaging.jpl.nasa.gov/data/lro/lroc/ | NAC 0.5–2 m/px, WAC ~100 m/px | `download_lroc.py` (PDS crawl) |
| LRO PDS Geosciences | https://pds-geosciences.wustl.edu/missions/lro/ | LOLA, Mini-RF, Diviner | manual / crawl |
| Moon Trek | https://trek.nasa.gov/moon/ | basemap & tools, geolocation | web |
| Apollo panoramas (LPI) | https://www.lpi.usra.edu/resources/apollopanoramas/ | surface 35mm panoramas | web |
| Apollo Image Archive (ASU) | https://apollo.sese.asu.edu/ | scans incl. orbital | web |
| Project Apollo Archive | https://www.flickr.com/photos/projectapolloarchive/ | original Hasselblad scans | web |
| JAXA Kaguya PDS | https://data.darts.isas.jaxa.jp/pub/pds3/ | SELENE TC/MI | web |
| USGS Astrogeology | https://astrogeology.usgs.gov/ | maps, mosaics, PDS | web |

## Mars
| Source | URL | What | Access |
|---|---|---|---|
| HiRISE catalog (MRO) | https://hirise-pds.lpl.arizona.edu/catalog/HiRISE_Catalog.json | 0.25–0.5 m/px | `download_hirise.py` |
| HiRISE PDS EDR | https://hirise-pds.lpl.arizona.edu/PDS/EDR/ | full-res RED/IR/BG products | `download_hirise.py --fetch <id>` |
| HiRISE public site | https://www.uahirise.org/ | browse by target, slideshows | web |
| Mars rover raw images | https://mars.nasa.gov/mars2020/multimedia/raw-images/ | Perseverance/Ingenuity raw | web + `download_rover.py` |
| Raw images RSS feed | https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json | JSON, no key; latest/full-res | `download_rover.py` |
| Featured gallery feed | https://mars.nasa.gov/rss/api/?feed=images&category=msl&feedtype=json | Curiosity/other (featured only) | `download_rover.py` (fallback) |
| Mars Photos API | https://api.nasa.gov/mars-photos/ | **ARCHIVED (404)** — do not use | n/a |
| Mars Trek | https://trek.nasa.gov/mars/ | basemap & geolocation | web |
| ESA Mars Express | https://psa.esa.int/ | HRSC stereo (10–20 m/px) | web |

## Hard-to-find archives (global / pre-2000 coverage)

These go well beyond the popular browse sites and cover the whole planet or
older eras — exactly what you need to (a) find a feature nobody else is looking
at, and (b) check the same spot decades apart. All are downloadable with
`scripts/download_archive.py --source <name> --mode browse|edr`.

| Source | What | Where | Verified |
|---|---|---|---|
| **CTX** (MRO) | global Mars coverage, 6 m/px, ~95k products | https://pds-imaging.jpl.nasa.gov/data/mro/mro-m-ctx-2-edr-l0-v1.0/ | yes |
| **MOC** (MGS, 1997–2006) | pre-HiRISE narrow-angle, 1.5–12 m/px | https://pds-imaging.jpl.nasa.gov/data/mgs/mgs-m-moc-2-edr-narrowangle-v1.0/ | yes |
| **Viking 1 & 2** orbiters (1976–80) | 1970s era Mars imagery | https://pds-imaging.jpl.nasa.gov/data/viking1/v1-visual-v02/ (+viking2) | yes |
| **Lunar Orbiter I–V** (1966–67) | digitized film, 60–90 m/px | https://pds-imaging.jpl.nasa.gov/data/lunar_orbiter_5/ | no — verify |
| **Clementine** (1994) | lunar UVVIS/NIR/HIRES | https://pds-geosciences.wustl.edu/missions/clementine/ | no — verify |
| **Moon Mineralogy Mapper** (Chandrayaan-1) | lunar hyperspectral cubes, 85 bands | https://pds-geosciences.wustl.edu/missions/chandrayaan-1/ | no — verify |
| **THEMIS** (Mars Odyssey) | Mars visible + thermal IR (~100 m/px) | https://pds-imaging.jpl.nasa.gov/data/odyssey/themis/ | no — verify |
| **HRSC** (Mars Express) | stereo imaging, 10–20 m/px | https://psa.esa.int/ (search UI) | n/a — manual |
| **Apollo orbital** (ASU) | metric/frame stereo 1968–72 | https://apollo.sese.asu.edu/ | n/a — web |

`--mode edr` downloads lossless originals — CTX/MOC EDRs are multiple GB, so set
`--max-size-mb` unless you really need the full product. `--mode browse` grabs
the small preview JPEGs, which is usually enough for detection (then fetch the
EDR only for confirmation). Entries marked "no — verify" are correct in spirit
but the exact current volume path should be confirmed once before a big run;
override with `--volume <url>`.

## Key guidance
- Log every source URL, product ID and hash — provenance is what makes a claim credible.
- Cross-check any candidate location against global coverage (Moon Trek / Mars Trek / HiRISE mosaic) to look for the same feature from other passes/angles.
- Timestamps matter: solar lighting changes between passes explains most apparent "differences."
