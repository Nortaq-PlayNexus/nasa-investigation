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

import pds

DEG = math.pi / 180.0


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


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


def _find_label(path):
    """Resolve the label file for an image path (.IMG/.JP2 -> sibling .LBL)."""
    low = path.lower()
    if low.endswith(".lbl") or low.endswith(".xml") or ".lbl" in low:
        return path if os.path.exists(path) else None
    for ext in (".LBL", ".lbl", ".XML", ".xml"):
        cand = os.path.splitext(path)[0] + ext
        if os.path.exists(cand):
            return cand
    return None


def geometry_from_path(path):
    """Best-effort geometry dict for a downloaded product path.

    Reads the PDS label (detached sibling or attached header) when one exists
    and returns normalized keys; images without labels return an empty dict.
    """
    lbl = _find_label(path)
    if not lbl:
        return {}
    try:
        data = pds.parse_label(lbl)
    except Exception:
        return {}
    return geometry_from_label(data)


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

    m_per_px = _num(get("LINE_SAMPLING_FACTOR", "LINE_SAMPLING_RATE", "PIXEL_SCALE",
                        "SCALE_FACTOR", "RESOLUTION", "HORIZONTAL_PIXEL_SCALE"))
    if m_per_px is not None and m_per_px <= 1e-3:
        m_per_px = m_per_px * 1000.0  # some labels report km/px

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
