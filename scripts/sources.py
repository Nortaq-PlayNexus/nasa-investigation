"""Curated registry of hard-to-find planetary imagery archives.

These are the archives beyond the obvious ones (images.nasa.gov, HiRISE,
LROC, rover feeds) — the global-coverage MRO CTX camera, the pre-HiRISE MGS
MOC archive, Viking Orbiter 1976-80, the digitized Lunar Orbiter 1966-67
scans, Clementine 1994, the Moon Mineralogy Mapper (Chandrayaan-1), Mars
Odyssey THEMIS thermal/visible, and ESA Mars Express HRSC stereo.

`verified` is True only for volume roots I am confident still serve today;
entries marked False are correct in spirit but the exact current volume path
should be confirmed once before a big run (PDS archives occasionally move).
Every script accepts `--volume` to override.

Keep pattern for `browse` = small preview JPEGs; `edr` = lossless originals
(some EDRs are multiple GB — mind the --max-size-mb flag).
"""

SOURCES = {
    "ctx": {
        "name": "MRO Context Camera (CTX) — global 6 m/px coverage",
        "target": "mars",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/mro/mro-m-ctx-2-edr-l0-v1.0/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 80,
        "verified": True,
        "notes": (
            "CTX covers the whole of Mars at 6 m/px; ~95k products. Browse "
            "JPEGs are small and fine for detection; the .IMG EDRs are "
            "multiple GB each — set --max-size-mb before fetching EDRs."
        ),
    },
    "moc": {
        "name": "Mars Global Surveyor MOC (narrow-angle, 1997-2006)",
        "target": "mars",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/mgs/mgs-m-moc-2-edr-narrowangle-v1.0/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 80,
        "verified": True,
        "notes": (
            "Pre-HiRISE narrow-angle archive, 1.5-12 m/px, ~144k products. "
            "Lets you check a site decades before MRO for change "
            "detection across eras."
        ),
    },
    "viking1": {
        "name": "Viking Orbiter 1 (1976-80) VIS",
        "target": "mars",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/viking1/v1-visual-v02/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 60,
        "verified": True,
        "notes": (
            "Legacy 1970s imaging, attached-label .IMG files. Coarse "
            "(>100 m/px) but a key independent-epoch dataset."
        ),
    },
    "viking2": {
        "name": "Viking Orbiter 2 (1976-80) VIS",
        "target": "mars",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/viking2/v2-visual-v02/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 60,
        "verified": True,
        "notes": "Companion to viking1.",
    },
    "lunar_orbiter": {
        "name": "Lunar Orbiter I-V (1966-67) digitized scans",
        "target": "moon",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/lunar_orbiter_5/",
        "browse_pattern": r"\.(jpg|jpeg|tif|tiff)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 60,
        "verified": False,
        "notes": (
            "Digitized film 1966-67, ~60-90 m/px. Volume path may have "
            "moved; verify once, or browse the USGS Astrogeology map "
            "search (https://astrogeology.usgs.gov/search) which serves "
            "georeferenced LO frames."
        ),
    },
    "clementine": {
        "name": "Clementine (1994) UVVIS/NIR/HIRES",
        "target": "moon",
        "volume": "https://pds-geosciences.wustl.edu/missions/clementine/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 60,
        "verified": False,
        "notes": (
            "1994 multi-spectral lunar mapping. Volume root at PDS "
            "Geosciences; verify the exact path before a big run."
        ),
    },
    "m3": {
        "name": "Moon Mineralogy Mapper (Chandrayaan-1, NASA instrument)",
        "target": "moon",
        "volume": "https://pds-geosciences.wustl.edu/missions/chandrayaan-1/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.(IMG|LBL)$",
        "depth": 3,
        "max_dirs": 60,
        "verified": False,
        "notes": (
            "Hyperspectral 85-band reflectance cubes (M3). Use "
            "pipeline/pds.read_band() to pull a single band without "
            "loading whole cubes. Volume path should be verified."
        ),
    },
    "themis": {
        "name": "Mars Odyssey THEMIS visible + thermal IR",
        "target": "mars",
        "volume": "https://pds-imaging.jpl.nasa.gov/data/odyssey/themis/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 3,
        "max_dirs": 60,
        "verified": False,
        "notes": (
            "Thermal IR (~100 m/px) exposes thermal-inertia differences "
            "invisible in visible light — a powerful cross-check on "
            "visible-band candidates. Volume path should be verified."
        ),
    },
    "mex_hrsc": {
        "name": "Mars Express HRSC stereo (ESA PSA archive)",
        "target": "mars",
        "volume": "https://psa.esa.int/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.IMG$",
        "depth": 2,
        "max_dirs": 20,
        "verified": False,
        "notes": (
            "10-20 m/px stereo-imaging products. PSA uses a search "
            "interface, not plain directory listings; fetch via their "
            "web UI / API and drop the products into data/raw manually."
        ),
    },
    "apollo_orbital": {
        "name": "Apollo orbital photography (AS10-AS17 metric/frame cameras)",
        "target": "moon",
        "volume": "https://apollo.sese.asu.edu/",
        "browse_pattern": r"\.(jpg|jpeg)$",
        "edr_pattern": r"\.(tif|tiff|IMG)$",
        "depth": 2,
        "max_dirs": 30,
        "verified": False,
        "notes": (
            "Orbital stereophotogrammetry 1968-72; metric-camera stereo "
            "pairs feed pipeline/stereo.py directly."
        ),
    },
}


def get_source(name):
    src = SOURCES.get(name)
    if not src:
        raise KeyError("unknown source %r; pick from %s" % (name, ", ".join(sorted(SOURCES))))
    return src


def list_sources():
    for name, src in sorted(SOURCES.items()):
        flag = "verified" if src["verified"] else "unverified"
        print("%-16s %-5s %s" % (name, flag, src["name"]))
