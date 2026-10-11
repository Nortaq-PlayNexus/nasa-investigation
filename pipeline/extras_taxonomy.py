"""
HiRISE EXTRAS product taxonomy — the single source of truth
===========================================================
Classifies every file that lives under
``https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/`` into a product family,
a variant role, a render scale, a geometry class and a human label, and
decides whether a file belongs in a browse-only acquisition.

Live tree shape (verified by directory probe, 2026-09)
------------------------------------------------------
::

    /PDS/EXTRAS/
      RDR/<INSTR>/<ORB shard>/<OBS>/          reduced-data-record browse sets
      DTM/<INSTR>/<ORB shard>/<PAIR>/         stereo DTM + orthorectified sets
      ANAGLYPH/<INSTR>/<ORB shard>/<PAIR>/    stereo anaglyphs (PNG)
      EDR/<INSTR>/<ORB shard>/<OBS>/          legacy per-filter EDR browses

    <INSTR> in {ESP, PSP, TRA, AEB};  <OBS> = <INSTR>_<orbit6>_<target4>
    <PAIR> = <OBS>_<OBS>  (stereo)
    <ORB shard> = ORB_<orbit6>_<orbit6>

Nominal file counts per footprint: RDR 27, DTM 16-19, ANAGLYPH 3, EDR 56.

Why this module exists
----------------------
``pipeline/extras_compare.py`` needs only a *narrow* role taxonomy
(``red``/``color``/``ortho_*``/``dtm``/``fom``) for alignment, and keeps it
inline. This module is the *broad* catalogue taxonomy: it also separates scale
(browse vs abrowse vs thumb vs full-res JP2), geometry (map-projected vs
detector NOMAP vs quicklook vs orthorectified), product family
(RDR/DTM/ANAGLYPH/EDR) and instrument, which the site catalogue and the
systematic acquisition pass need in order to decide what to fetch and how to
group siblings.

Both vocabularies agree on the roles they share; nothing here changes how
``extras_compare`` aligns variants.

Acquisition policy
------------------
The EXTRAS browse JPGs are the comparison unit (see ``docs/EXTRAS.md`` §3).
Full-resolution JP2s are 250-700 MB each and the whole site is ~100 TB, so
:func:`acquire_decision` fetches every ``*.browse.jpg``/``*.abrowse.jpg``/
``*.thumb.jpg``/``*.browse.png``/``*.thumb.png`` plus the small provenance
sidecars (``*.LBL``, ``README.TXT``, ``FOM_MAP_LEGEND.JPG``) and skips JP2s
unless an explicit budget is supplied.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTRAS_BASE = "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/"

#: Top-level EXTRAS collections and the product family they hold.
COLLECTIONS = ("RDR", "DTM", "ANAGLYPH", "EDR")

#: Instrument codes seen in the tree.
INSTRUMENTS = ("ESP", "PSP", "TRA", "AEB")

#: Collection -> instruments, exactly as published.
BRANCHES = (
    ("RDR/ESP", "RDR", "ESP"),
    ("RDR/PSP", "RDR", "PSP"),
    ("RDR/TRA", "RDR", "TRA"),
    ("RDR/AEB", "RDR", "AEB"),
    ("DTM/ESP", "DTM", "ESP"),
    ("DTM/PSP", "DTM", "PSP"),
    ("ANAGLYPH/ESP", "ANAGLYPH", "ESP"),
    ("ANAGLYPH/PSP", "ANAGLYPH", "PSP"),
    ("ANAGLYPH/TRA", "ANAGLYPH", "TRA"),
    ("EDR/ESP", "EDR", "ESP"),
    ("EDR/PSP", "EDR", "PSP"),
    ("EDR/TRA", "EDR", "TRA"),
    ("EDR/AEB", "EDR", "AEB"),
)

#: Scientific priority used to order the systematic pass. RDR/ESP first (it is
#: the canonical browse set and the only family with the full RED/IRB/MIRB/
#: MRGB/RGB/COLOR cross-rendering), DTM next (terrain truth), ANAGLYPH next,
#: legacy EDR last. ``docs/EXTRAS.md`` §2 marks EDR as "legacy (not used)".
BRANCH_PRIORITY = {
    "RDR/ESP": 0,
    "DTM/ESP": 1,
    "RDR/PSP": 2,
    "DTM/PSP": 3,
    "ANAGLYPH/ESP": 4,
    "RDR/TRA": 5,
    "RDR/AEB": 6,
    "ANAGLYPH/PSP": 7,
    "ANAGLYPH/TRA": 8,
    "EDR/ESP": 9,
    "EDR/PSP": 10,
    "EDR/TRA": 11,
    "EDR/AEB": 12,
}

#: Full-resolution extensions that the browse-only policy refuses by default.
FULLRES_EXTS = (".jp2",)

#: Render-scale sets the acquisition pass can be pointed at. ``browse`` is the
#: comparison unit (full-resolution rendering of a variant); ``thumb`` is the
#: cheap index/QA image; ``abrowse`` is the half-resolution duplicate that
#: costs nearly as much as the full browse while adding no new coverage.
DEFAULT_SCALES = ("browse", "thumb")
SCALE_SETS = {
    "thumb": ("thumb",),
    "browse": ("browse",),
    "core": ("browse", "thumb"),
    "full": ("browse", "abrowse", "thumb"),
}

#: Geometry classes a policy may accept.
#:
#: ``map`` keeps only products already resampled onto a common grid —
#: map-projected browses, orthorectified images and DTM derivatives — and drops
#: the raw detector-geometry (``nomap``) and quicklook renderings.
#:
#: This is the single biggest byte lever in the whole acquisition, and the
#: arithmetic is worth stating. Measured over ~7,600 real RDR footprints, an
#: ``*_RED.NOMAP.browse.jpg`` averages 5.6 MB against 2.3 MB for the
#: map-projected ``*_RED.browse.jpg``, because NOMAP preserves native detector
#: resolution while the projected product is resampled. Across a whole RDR
#: observation that is ~9.5 MB of the ~18 MB budget:
#:
#:     all geometries   ~18.0 MB/footprint   ->  RDR/ESP alone ~1489 GB
#:     map only          ~8.5 MB/footprint   ->  RDR/ESP alone  ~705 GB
#:
#: The science survives the cut: the documented debunk path is B&W RED ->
#: filtered colour -> orthorectified -> DTM-shaded, and every one of those is
#: map-projected. ``extras_compare`` already scores the NOMAP siblings as
#: STRONG DIVERGENCE (mean_abs_diff ~0.32) precisely because they are in a
#: different geometry, so they confirm coverage rather than morphology.
DEFAULT_GEOMETRIES = ("map", "ortho", "dtm", "anaglyph")
GEOMETRY_SETS = {
    "map": DEFAULT_GEOMETRIES,
    "all": ("map", "ortho", "dtm", "anaglyph", "nomap", "quicklook"),
}

#: Provenance sidecars — tiny, always fetched.
SIDECAR_NAMES = ("readme.txt", "fom_map_legend.jpg")

#: DTM derivative suffixes -> human label. Mirrors extras_compare.DTM_LABELS.
DTM_SUFFIX_LABELS = {
    "ab": "shaded relief, illumination A",
    "br": "browse B, illumination B",
    "ca": "colorized elevation A",
    "cb": "colorized elevation B",
    "ct": "contour / terrain model",
    "sa": "slope A",
    "sb": "slope B / aspect",
    "st": "stereo helper",
    "th": "thumbnail",
}

#: RDR band -> human label.
RDR_BAND_LABELS = {
    "RED": "B&W panchromatic (least processing) — comparison reference",
    "IRB": "enhanced color IR/RED/BG (filtered)",
    "MIRB": "map-projected IR color",
    "MRGB": "map-projected RGB color",
    "RGB": "RGB composite (detector geometry)",
    "COLOR": "COLOR quicklook composite",
}

#: RDR render scale -> resolution class.
SCALE_LABELS = {
    "browse": "full browse",
    "abrowse": "binned browse (half-res)",
    "thumb": "thumbnail",
    "fullres": "full-resolution source (JP2)",
    "quicklook": "quicklook full-resolution (JP2)",
}

GEOMETRY_LABELS = {
    "map": "map-projected to a common grid",
    "nomap": "NOT map-projected (detector geometry)",
    "quicklook": "quicklook rendering",
    "ortho": "orthorectified against the stereo DTM",
    "dtm": "DTM/terrain product",
    "anaglyph": "stereo anaglyph",
}

# ---------------------------------------------------------------------------
# Filename grammar
# ---------------------------------------------------------------------------

OBS = r"[A-Z]{3}_\d{6}_\d{4}"
OBS_RX = re.compile(rf"^{OBS}$")
PAIR_RX = re.compile(rf"^{OBS}_{OBS}$")
OBS_TOKEN_RX = re.compile(rf"{OBS}")
ORB_SHARD_RX = re.compile(r"^ORB_(\d{6})_(\d{6})$")

RDR_FILE_RX = re.compile(
    rf"^(?P<obs>{OBS})_(?P<band>RED|IRB|MIRB|MRGB|RGB|COLOR)"
    r"(?:\.(?P<geom>NOMAP|QLOOK))?"
    r"(?:\.(?P<scale>browse|abrowse|thumb)\.jpg|\.LBL|\.JP2)$"
)
EDR_FILE_RX = re.compile(
    rf"^(?P<obs>{OBS})_(?P<filter>RED\d+|IR\d+|BG\d+)_(?P<det>\d+)"
    r"\.(?P<scale>browse|thumb)\.jpg$"
)
DTEEC_BROWSE_RX = re.compile(
    r"^DTEEC_(?P<a>\d{6}_\d{4})_(?P<b>\d{6}_\d{4})_(?P<ver>[A-Z]\d{2})"
    r"\.(?P<sfx>ab|br|ca|cb|ct|sa|sb|st|th)\.jpg$"
)
DTEEC_FULL_RX = re.compile(r"^DTEEC_.+_A0?\d\.JP2$")
DTFEC_FULL_RX = re.compile(r"^DTFEC_.+\.JP2$")
ORTHO_BROWSE_RX = re.compile(
    rf"^(?P<obs>{OBS})_(?P<band>RED|IRB|MIRB|MRGB|RGB|COLOR)_C_\d+_ORTHO"
    r"(?:\.(?P<sfx>ab|br|ca|cb|ct|sa|sb|st|th))?\.jpg$"
)
ORTHO_FULL_RX = re.compile(
    rf"^(?P<obs>{OBS})_(?P<band>RED|IRB|MIRB|MRGB|RGB|COLOR)_C_\d+_ORTHO\.JP2$"
)
ANAGLYPH_BROWSE_RX = re.compile(
    rf"^(?P<pair>{OBS}_{OBS})_RED\.(?P<scale>browse|thumb)\.png$"
)
ANAGLYPH_FULL_RX = re.compile(rf"^(?P<pair>{OBS}_{OBS})_RED\.JP2$")

#: EDR filter -> what it actually is on the spacecraft.
EDR_FILTER_LABELS = {
    "RED": "detector 0-7 red band",
    "IR": "detector 8-9 infrared band",
    "BG": "detector 10-11 blue-green band",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def observations_in(name: str) -> list[str]:
    """Every ``<INSTR>_<orbit>_<target>`` token inside a directory or file name."""
    return OBS_TOKEN_RX.findall(name or "")


def instrument_of(obs_id: str) -> str:
    """``ESP_013948_1410`` -> ``ESP``."""
    return (obs_id or "").split("_", 1)[0].upper()


def orbit_of(obs_id: str) -> int | None:
    """``ESP_013948_1410`` -> ``13948``."""
    parts = (obs_id or "").split("_")
    if len(parts) == 3 and parts[1].isdigit():
        return int(parts[1])
    return None


def target_of(obs_id: str) -> int | None:
    """``ESP_013948_1410`` -> ``1410``."""
    parts = (obs_id or "").split("_")
    if len(parts) == 3 and parts[2].isdigit():
        return int(parts[2])
    return None


def classify_footprint(name: str) -> dict:
    """Classify a leaf directory name into a footprint record.

    Returns ``kind`` (``observation`` / ``stereo_pair``), the observation ids it
    covers, its instrument and the orbit it was acquired in.
    """
    name = (name or "").strip()
    if PAIR_RX.match(name):
        obs = observations_in(name)
        return {
            "kind": "stereo_pair",
            "observations": obs,
            "instrument": instrument_of(obs[0]) if obs else "",
            "orbit": orbit_of(obs[0]) if obs else None,
        }
    if OBS_RX.match(name):
        return {
            "kind": "observation",
            "observations": [name],
            "instrument": instrument_of(name),
            "orbit": orbit_of(name),
        }
    obs = observations_in(name)
    return {
        "kind": "unclassified",
        "observations": obs,
        "instrument": instrument_of(obs[0]) if obs else "",
        "orbit": orbit_of(obs[0]) if obs else None,
    }


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def _blank(branch_hint: str = "") -> dict:
    return {
        "product_family": branch_hint.split("/")[0] if "/" in branch_hint else "",
        "product_class": "unknown",
        "instrument": "",
        "observation": "",
        "band": "",
        "filter": "",
        "scale": "",
        "geometry": "",
        "role": "other",
        "taxonomy": "unclassified product",
        "ext": "",
        "is_label": False,
        "is_fullres": False,
        "is_sidecar": False,
    }


def classify_file(filename: str, branch_hint: str = "") -> dict:
    """Classify one EXTRAS filename.

    ``branch_hint`` is the collection/instrument branch (``"RDR/ESP"``); it is
    only used as a fallback when the filename alone is ambiguous.
    """
    name = (filename or "").strip()
    low = name.lower()
    info = _blank(branch_hint)
    info["ext"] = name[name.rfind("."):] if "." in name else ""
    info["is_label"] = low.endswith(".lbl")
    info["is_fullres"] = low.endswith(".jp2")
    info["is_sidecar"] = low in SIDECAR_NAMES

    # --- sidecars ---------------------------------------------------------
    if low == "readme.txt":
        info.update(
            product_class="readme",
            scale="",
            role="other",
            taxonomy="PDS README (compliance record, DTM RMS, valid elevation range)",
        )
        return info
    if low == "fom_map_legend.jpg":
        info.update(
            product_class="fom_legend",
            role="fom",
            scale="browse",
            geometry="dtm",
            taxonomy="Figure-of-Merit colour legend",
        )
        return info

    # --- RDR reduced data record browse sets -----------------------------
    m = RDR_FILE_RX.match(name)
    if m:
        band = m.group("band")
        geom_token = m.group("geom")
        is_jp2 = name.upper().endswith(".JP2")
        is_lbl = name.upper().endswith(".LBL")
        scale = m.group("scale") or ("fullres" if is_jp2 else "")
        if geom_token == "QLOOK":
            geometry = "quicklook"
        elif geom_token == "NOMAP":
            geometry = "nomap"
        else:
            geometry = "map"
        role = "red" if band == "RED" else "color"
        if is_lbl:
            product_class = "rdr_label"
            role = "other"
            taxonomy = f"PDS label for the {band} variant"
        else:
            product_class = "rdr_fullres" if is_jp2 else "rdr_browse"
            taxonomy = f"{RDR_BAND_LABELS.get(band, band)} — {SCALE_LABELS.get(scale, scale)}"
        info.update(
            product_family="RDR",
            product_class=product_class,
            instrument=instrument_of(m.group("obs")),
            observation=m.group("obs"),
            band=band,
            scale=scale,
            geometry=geometry,
            role=role,
            taxonomy=taxonomy,
        )
        info["ext"] = ".LBL" if is_lbl else (".JP2" if is_jp2 else ".jpg")
        return info

    # --- DTM stereo terrain models ----------------------------------------
    m = DTEEC_BROWSE_RX.match(name)
    if m:
        sfx = m.group("sfx")
        info.update(
            product_family="DTM",
            product_class="dtm_derivative",
            instrument=branch_hint.split("/")[-1] if "/" in branch_hint else "",
            observation=f"{m.group('a')}_{m.group('b')}",
            band="DTEEC",
            scale="thumbnail" if sfx == "th" else "browse",
            geometry="dtm",
            role="dtm",
            taxonomy=f"DTM {DTM_SUFFIX_LABELS.get(sfx, sfx)}",
            ext=".jpg",
        )
        return info
    if DTEEC_FULL_RX.match(name):
        info.update(
            product_family="DTM",
            product_class="dtm_elevation",
            instrument=branch_hint.split("/")[-1] if "/" in branch_hint else "",
            band="DTEEC",
            scale="fullres",
            geometry="dtm",
            role="dtm",
            taxonomy="DTM elevation, areoid, equirectangular (full-resolution)",
            ext=".JP2",
        )
        return info
    if DTFEC_FULL_RX.match(name):
        info.update(
            product_family="DTM",
            product_class="fom_map",
            instrument=branch_hint.split("/")[-1] if "/" in branch_hint else "",
            band="DTFEC",
            scale="fullres",
            geometry="dtm",
            role="fom",
            taxonomy="Figure-of-Merit map (stereo correlation quality)",
            ext=".JP2",
        )
        return info

    # --- orthorectified products ------------------------------------------
    m = ORTHO_BROWSE_RX.match(name)
    if m:
        band = m.group("band")
        role = "ortho_red" if band == "RED" else "ortho_color"
        base = "ortho B&W (RED)" if band == "RED" else f"ortho color ({band})"
        info.update(
            product_family="DTM",
            product_class="ortho_browse",
            instrument=instrument_of(m.group("obs")),
            observation=m.group("obs"),
            band=band,
            scale="thumbnail" if m.group("sfx") == "th" else "browse",
            geometry="ortho",
            role=role,
            taxonomy=f"{base} draped on the stereo DTM",
            ext=".jpg",
        )
        return info
    m = ORTHO_FULL_RX.match(name)
    if m:
        band = m.group("band")
        info.update(
            product_family="DTM",
            product_class="ortho_fullres",
            instrument=instrument_of(m.group("obs")),
            observation=m.group("obs"),
            band=band,
            scale="fullres",
            geometry="ortho",
            role="ortho_red" if band == "RED" else "ortho_color",
            taxonomy=f"orthorectified {band} (full-resolution)",
            ext=".JP2",
        )
        return info

    # --- ANAGLYPH ---------------------------------------------------------
    m = ANAGLYPH_BROWSE_RX.match(name)
    if m:
        info.update(
            product_family="ANAGLYPH",
            product_class="anaglyph_browse",
            instrument=instrument_of(m.group("pair")),
            observation=m.group("pair"),
            band="RED",
            scale=m.group("scale"),
            geometry="anaglyph",
            role="anaglyph",
            taxonomy=f"stereo anaglyph — {SCALE_LABELS.get(m.group('scale'), '')}".strip(),
            ext=".png",
        )
        return info
    m = ANAGLYPH_FULL_RX.match(name)
    if m:
        info.update(
            product_family="ANAGLYPH",
            product_class="anaglyph_fullres",
            instrument=instrument_of(m.group("pair")),
            observation=m.group("pair"),
            band="RED",
            scale="fullres",
            geometry="anaglyph",
            role="anaglyph",
            taxonomy="stereo anaglyph (full-resolution)",
            ext=".JP2",
        )
        return info

    # --- legacy EDR per-filter browses ------------------------------------
    m = EDR_FILE_RX.match(name)
    if m:
        filt = m.group("filter")
        stem = "".join(ch for ch in filt if not ch.isdigit())
        desc = EDR_FILTER_LABELS.get(stem, stem)
        info.update(
            product_family="EDR",
            product_class="edr_browse",
            instrument=instrument_of(m.group("obs")),
            observation=m.group("obs"),
            band=stem,
            filter=filt,
            scale=m.group("scale"),
            geometry="map",
            role="red" if stem == "RED" else "color",
            taxonomy=f"legacy EDR browse — {desc}, {SCALE_LABELS.get(m.group('scale'), '')}",
            ext=".jpg",
        )
        return info

    # --- anything else ----------------------------------------------------
    obs = observations_in(name)
    if obs:
        info["instrument"] = instrument_of(obs[0])
        info["observation"] = obs[0]
    info["taxonomy"] = f"unclassified EXTRAS product ({name})"
    return info


# ---------------------------------------------------------------------------
# Acquisition policy
# ---------------------------------------------------------------------------


def acquire_decision(
    info: dict,
    max_fullres_mb: float = 0.0,
    scales: tuple[str, ...] = DEFAULT_SCALES,
    geometries: tuple[str, ...] = DEFAULT_GEOMETRIES,
) -> tuple[bool, str]:
    """Should this classified file be fetched, under a browse-only budget?

    ``max_fullres_mb`` is a per-file cap for full-resolution JP2s; ``0``
    (the default) means "never fetch JP2s". ``scales`` selects which render
    scales count as the comparison unit (:data:`SCALE_SETS`) and
    ``geometries`` which geometry classes are in budget
    (:data:`GEOMETRY_SETS`).

    Returns ``(fetch, reason)``.
    """
    name_scale = info.get("scale") or ""
    ext = (info.get("ext") or "").lower()

    if info.get("is_label"):
        return True, "provenance sidecar (PDS label)"
    if info.get("is_sidecar"):
        return True, "provenance sidecar (README / FOM legend)"

    if ext in FULLRES_EXTS or info.get("is_fullres"):
        if max_fullres_mb <= 0:
            return False, "full-resolution JP2 excluded by browse-only policy"
        return True, f"full-resolution JP2 allowed by --max-fullres-mb {max_fullres_mb}"

    geom = info.get("geometry") or ""
    if geom and geom not in geometries:
        return False, (
            f"geometry {geom!r} outside the acquisition geometry set "
            f"(detector-geometry renderings are the largest files per footprint)"
        )
    if name_scale in scales:
        return True, f"{SCALE_LABELS.get(name_scale, name_scale)} — comparison unit"
    if name_scale and name_scale not in scales:
        return False, f"render scale {name_scale!r} not in the acquisition scale set"

    # Unknown scale/geometry: fetch it, the catalogue marks it for review.
    return True, "unclassified product; fetched for completeness"


def reference_choice(entries: list[dict]) -> str | None:
    """Pick the B&W RED browse that ``extras_compare`` should align against.

    ``entries`` are classified file records for one footprint. Mirrors the
    priority in ``extras_compare.compare_footprint``: a map-projected RED
    browse beats a NOMAP/quicklook one, full browse beats binned beats
    thumbnail.  Returns the file name, or ``None`` when the footprint has no
    B&W RED product at all (e.g. ANAGLYPH/EDR-only footprints).
    """
    red = [e for e in entries if e.get("role") == "red" and e.get("ext") == ".jpg"]
    if not red:
        red = [e for e in entries if e.get("role") == "ortho_red" and e.get("ext") == ".jpg"]
    if not red:
        return None
    geom_rank = {"map": 0, "ortho": 1, "nomap": 2, "quicklook": 3, "dtm": 4, "anaglyph": 5}
    scale_rank = {"browse": 0, "abrowse": 1, "thumb": 2}

    def key(e: dict) -> tuple:
        return (
            geom_rank.get(e.get("geometry", ""), 9),
            scale_rank.get(e.get("scale", ""), 9),
            -int(e.get("bytes") or 0),
            e.get("name", ""),
        )

    return min(red, key=key)["name"]
