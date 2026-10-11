"""Solar/geometry metadata extracted from PDS labels.

Turns the raw label keywords (incidence, emission, phase angles, sub-solar /
sub-spacecraft positions, pixel scale, spacecraft altitude) into normalized
values the pipeline can reason about, plus the shadow physics used to convert
an apparent shadow in an image into a physical height bound.

The rule from METHODOLOGY.md: solar geometry is the #1 explanation for
apparent differences between passes, so every candidate should carry the
lighting it was seen under.
"""

import math
import os
import re

import pds

DEG = math.pi / 180.0


def _num(v):
    """Coerce a PDS label value to a float.

    PDS3 labels carry the unit inline (``57.508291 <DEG>``,
    ``0.5 <METERS/PIXEL>``, ``3394.83 <KM>``) and sometimes thousands
    separators. Strip the unit and separators before converting, or every
    geometry keyword silently parses as ``None``.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    lt = s.find("<")
    if lt != -1:
        s = s[:lt].strip()
    s = s.replace(",", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _unit(v):
    """The unit of a PDS value, upper-cased: ``57.5 <DEG>`` -> ``DEG``."""
    if v is None:
        return ""
    s = str(v)
    lt, gt = s.find("<"), s.find(">")
    if lt != -1 and gt > lt:
        return s[lt + 1:gt].strip().upper()
    return ""


def bearing(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing (degrees clockwise from north).

    Standard forward-azimuth formula; used to derive the sun azimuth from
    sub-spacecraft and sub-solar planetocentric coordinates when a label only
    gives positions.
    """
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def solar_elevation(incidence_deg):
    """Sun elevation above the local horizon, from the solar incidence angle."""
    if incidence_deg is None:
        return None
    return 90.0 - incidence_deg


#: Render-scale suffixes HiRISE EXTRAS puts between the product stem and the
#: image extension (``ESP_011261_1960_MIRB.browse.jpg``). The PDS label for
#: that product is ``ESP_011261_1960_MIRB.LBL`` — the scale token is *not*
#: part of the label name, so a plain splitext sibling lookup misses it and
#: the whole observation silently loses its solar geometry.
SCALE_TOKENS = (
    ".browse", ".abrowse", ".quicklook", ".thumb", ".nomap", ".qlook",
    ".ab", ".br", ".ca", ".cb", ".ct", ".sa", ".sb", ".st", ".th",
)


def _find_label(path):
    """Resolve the PDS label for an image path.

    Tries the exact sibling first (``X.IMG`` -> ``X.LBL``), then the same
    stem with any EXTRAS render-scale token removed
    (``X_MIRB.browse.jpg`` -> ``X_MIRB.LBL``), then the footprint-shared
    label. Labels are per-observation and every rendering of a footprint was
    acquired in the same pass, so one label describes all of them.
    """
    low = path.lower()
    if low.endswith(".lbl") or low.endswith(".xml") or ".lbl" in low:
        return path if os.path.exists(path) else None
    for ext in (".LBL", ".lbl", ".XML", ".xml"):
        cand = os.path.splitext(path)[0] + ext
        if os.path.exists(cand):
            return cand
    stem = os.path.splitext(path)[0]
    for token in SCALE_TOKENS:
        if stem.lower().endswith(token):
            base = stem[: -len(token)]
            for ext in (".LBL", ".lbl", ".XML", ".xml"):
                cand = base + ext
                if os.path.exists(cand):
                    return cand
            break
    return None


def _find_readme(path):
    """Locate a DTM ``README.TXT`` governing this product.

    DTM and orthorectified products ship no per-image PDS label. The stereo
    pair's directory carries a single ``README.TXT`` that holds the grid
    spacing, the valid elevation range, the stereo RMS and the source
    observations — i.e. all of the geometry that makes a DTM product usable.
    """
    d = os.path.dirname(os.path.abspath(path))
    for name in ("README.TXT", "readme.txt", "README.txt", "README.TXT"):
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return None


#: Known HiRISE DTM processing artifacts, described in every stereo pair's
#: README under "KNOWN ARTIFACTS". A candidate that lands on one of these is
#: a terrain-model defect, not a surface feature, so the value is surfaced
#: rather than left in prose nobody reads during adjudication.
DTM_ARTIFACTS = {
    "boxes": "square areas ~0.5-1 m off the surrounding elevation (SOCET SET tiling)",
    "ccd_seams": "long lines where the 10 CCD strips were stitched together",
    "faceted_areas": "bland or deeply shadowed areas with untrustworthy, faceted terrain",
}

#: Stereo-pair project names encode centre as ``<name>_<lon*10><E|W>_<lat*10><N|S>``
#: — e.g. ``Corozal_1593E_387S`` is 159.3 deg E, 38.7 deg S. Longitude comes
#: first, and the hemisphere letters are E/W then N/S.
_PROJECT_LATLON_RX = re.compile(
    r"_(?P<lon>\d{1,4})(?P<lonh>[EW])_(?P<lat>\d{1,4})(?P<lath>[NS])\s*$", re.I
)

#: A decimal that cannot swallow a sentence-ending period. ``([\d.]+)``
#: captures "6.486." from "...deviation 6.486." and ``float()`` rejects it.
_DEC = r"(\d+(?:\.\d+)?)"


def parse_dtm_readme(path):
    """Parse a stereo-pair ``README.TXT`` into normalised DTM geometry.

    The post spacing matters most: it is the ground sample distance of every
    DTM derivative and of the orthorectified image in the same directory, and
    it appears *nowhere else* — the letter in ``..._A01`` / ``..._U01`` is the
    producing institution (A = Arizona, U = USGS), not the grid spacing, as
    the README's own naming-convention section is easy to misread. Without
    this, DTM products reach the adjudicator with no scale at all.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return {}
    if not text:
        return {}

    g = {}

    def grab(pattern, cast=float, group=1):
        m = re.search(pattern, text, re.I | re.M)
        if not m:
            return None
        try:
            return cast(m.group(group))
        except (TypeError, ValueError):
            return None

    g["dtm_post_spacing_m"] = grab(r"[Pp]ost\s+spacing\s+in\s+DTM\s+is\s+" + _DEC + r"\s*m")
    g["dtm_valid_min_m"] = grab(r"VALID_MINIMUM\s*=\s*(-?" + _DEC + r")\s*m")
    g["dtm_valid_max_m"] = grab(r"VALID_MAXIMUM\s*=\s*(-?" + _DEC + r")\s*m")
    g["dtm_rms_total_px"] = grab(r"Total\s+RMS\s*==>\s*" + _DEC + r"\s*px")
    g["dtm_rms_x_m"] = grab(r"RMS\s+x\s*==>\s*" + _DEC + r"\s*m")
    g["dtm_rms_y_m"] = grab(r"RMS\s+y\s*==>\s*" + _DEC + r"\s*m")
    g["dtm_rms_z_m"] = grab(r"RMS\s+z\s*==>\s*" + _DEC + r"\s*m")
    g["dtm_mola_mean_diff_m"] = grab(r"Mean\s+difference\s+from\s+MOLA\s+" + _DEC + r"\s*m")
    # the mean is capture group 1 here, the standard deviation group 2
    g["dtm_mola_stdev_m"] = grab(
        r"from\s+MOLA\s+" + _DEC + r"\s*m,\s*standard\s+deviation\s+" + _DEC, group=2
    )
    m_sw = re.search(r"SOCET\s*SET\s*(?:(\S+)\s*)?was used", text, re.I)
    g["dtm_software"] = ("SOCET SET " + (m_sw.group(1) or "")).strip() if m_sw else ""

    m = re.search(r"PROJECT NAME\s*\n\s*(\S+)", text, re.I)
    g["dtm_project"] = m.group(1).strip() if m else ""
    lm = _PROJECT_LATLON_RX.search(g["dtm_project"])
    if lm:
        lon = float(lm.group("lon")) / 10.0
        lat = float(lm.group("lat")) / 10.0
        g["dtm_longitude"] = -lon if lm.group("lonh").upper() == "W" else lon
        g["dtm_latitude"] = -lat if lm.group("lath").upper() == "S" else lat

    src = re.search(r"HIRISE SOURCE IMAGES\s*\n((?:\s*\w+_\d+_\d+\s*\n)+)", text, re.I)
    g["dtm_source_images"] = [s.strip() for s in src.group(1).split()] if src else []
    g["dtm_known_artifacts"] = [k for k in DTM_ARTIFACTS if k.replace("_", " ") in text.lower()]
    return g


def _is_dtm_family(path):
    """True for products whose ground sample distance is the DTM post spacing.

    A stereo pair's directory also holds ``FOM_MAP_LEGEND.JPG``, a colour key
    for the Figure-of-Merit map. It is not a terrain product, so it must not
    inherit the DTM's metre-per-post.
    """
    name = os.path.basename(path).lower()
    if name.startswith("fom_map_legend"):
        return False
    return name.startswith("dteec_") or "ortho" in name


def geometry_from_path(path):
    """Best-effort geometry dict for a downloaded product path.

    Reads the PDS label (detached sibling or attached header) when one exists
    and the stereo pair's ``README.TXT`` when the product is a DTM or an
    orthorectified image; the README supplies the grid spacing those products
    otherwise lack entirely. Returns normalized keys; images with neither
    return an empty dict.
    """
    g = {}
    lbl = _find_label(path)
    if lbl:
        try:
            g = geometry_from_label(pds.parse_label(lbl))
        except Exception:
            g = {}
    readme = _find_readme(path)
    if readme and _is_dtm_family(path):
        r = parse_dtm_readme(readme)
        if r:
            # The README's post spacing is the ground sample distance of every
            # DTM derivative and of the orthorectified image beside it, and it
            # is the only place that value appears.
            if r.get("dtm_post_spacing_m"):
                g["pixel_scale_m"] = r["dtm_post_spacing_m"]
                g["pixel_scale_source"] = "DTM README post spacing"
            for k, v in r.items():
                if v not in ("", None, []):
                    g.setdefault(k, v)
    return g


def geometry_from_label(data):
    """Normalize PDS3/PDS4 label keywords into a geometry dict."""
    if isinstance(data, str):
        data = pds.parse_label(data)
    flat = pds.label_flat(data)

    def get(*names):
        for n in names:
            if n in flat:
                return flat[n]
        return None

    incidence = _num(get("INCIDENCE_ANGLE", "SOLAR_INCIDENCE_ANGLE", "INCIDENCE_ANGLE_SOLAR"))
    emission = _num(get("EMISSION_ANGLE", "EMISSION_ANGLE_OBSERVER"))
    phase = _num(get("PHASE_ANGLE"))
    azimuth = _num(get("SOLAR_AZIMUTH_ANGLE", "SUB_SOLAR_AZIMUTH", "SOLAR_AZIMUTH"))

    if azimuth is None:
        ss_lat = _num(get("SUB_SOLAR_LATITUDE", "SUN_LATITUDE"))
        ss_lon = _num(get("SUB_SOLAR_LONGITUDE", "SUN_LONGITUDE"))
        sc_lat = _num(get("SUB_SPACECRAFT_LATITUDE", "OBSERVER_LATITUDE"))
        sc_lon = _num(get("SUB_SPACECRAFT_LONGITUDE", "OBSERVER_LONGITUDE"))
        if None not in (ss_lat, ss_lon, sc_lat, sc_lon):
            azimuth = bearing(sc_lat, sc_lon, ss_lat, ss_lon)

    altitude = _num(get("SPACECRAFT_ALTITUDE", "SPACECRAFT_ALTITUDE_KM", "OBSERVER_ALTITUDE"))
    if altitude is not None and altitude > 1e5:
        altitude = altitude / 1000.0  # some labels report meters

    # Pixel scale. HiRISE map-projected RDR labels express it as MAP_SCALE
    # (metres per pixel) rather than LINE_SAMPLING_FACTOR, which is an
    # instrument rate for the native (non-projected) product. When only
    # MAP_RESOLUTION (pixels per degree) is given, convert it at the local
    # planetary radius carried in the same label.
    m_per_px = _num(get("LINE_SAMPLING_FACTOR", "LINE_SAMPLING_RATE", "PIXEL_SCALE",
                        "SCALE_FACTOR", "RESOLUTION", "HORIZONTAL_PIXEL_SCALE",
                        "MAP_SCALE"))
    scale_unit = _unit(get("LINE_SAMPLING_FACTOR", "LINE_SAMPLING_RATE", "PIXEL_SCALE",
                           "SCALE_FACTOR", "RESOLUTION", "HORIZONTAL_PIXEL_SCALE",
                           "MAP_SCALE"))
    if m_per_px is not None and (scale_unit.startswith("KM") or m_per_px <= 1e-3):
        m_per_px = m_per_px * 1000.0  # km/px -> m/px
    if m_per_px is None:
        pix_per_deg = _num(get("MAP_RESOLUTION"))
        radius_km = _num(get("A_AXIS_RADIUS", "B_AXIS_RADIUS", "C_AXIS_RADIUS",
                             "LOCAL_RADIUS", "RADII[1]"))
        if pix_per_deg and radius_km:
            m_per_px = (math.pi / 180.0) * (radius_km * 1000.0) / pix_per_deg

    elevation = solar_elevation(incidence)

    g = {
        "target": str(get("TARGET_NAME", "TARGET") or ""),
        "instrument": str(get("INSTRUMENT_ID", "INSTRUMENT_NAME", "INSTRUMENT") or ""),
        "observation_id": str(get("OBSERVATION_ID", "PRODUCT_ID", "IMAGE_ID",
                                  "IDENTIFICATION_NUMBER", "PRODUCT_VERSION_ID") or ""),
        "band": str(get("BAND", "FILTER_NUMBER", "FILTER_NAME") or ""),
        "start_time": str(get("START_TIME", "STOP_TIME", "START_DATE_TIME") or ""),
        "incidence_angle": incidence,
        "emission_angle": emission,
        "phase_angle": phase,
        "solar_azimuth": azimuth,
        "solar_elevation": elevation,
        "spacecraft_altitude_km": altitude,
        "pixel_scale_m": m_per_px,
    }
    for k, v in list(g.items()):
        if v == "":
            g[k] = None
    return g


def height_from_shadow_len(shadow_px, solar_elevation_deg, m_per_px):
    """Physical height (m) implied by a shadow of length shadow_px.

    Height = shadow_length * tan(sun_elevation). The object's own projected
    height equals shadow length only when the shadow falls on flat ground and
    the object is tall relative to its footprint; otherwise this is an upper
    bound. Recorded with the caveat, not as fact.
    """
    if None in (shadow_px, solar_elevation_deg, m_per_px) or m_per_px <= 0:
        return None
    if solar_elevation_deg <= 1 or solar_elevation_deg >= 89:
        return None
    return shadow_px * m_per_px * math.tan(solar_elevation_deg * DEG)


def shadow_len_for_height(height_m, solar_elevation_deg, m_per_px):
    """Expected shadow length in pixels for an object of the given height."""
    if None in (height_m, solar_elevation_deg, m_per_px) or m_per_px <= 0:
        return None
    if solar_elevation_deg <= 1 or solar_elevation_deg >= 89:
        return None
    return height_m / (m_per_px * math.tan(solar_elevation_deg * DEG))
