"""Native Planetary Data System ingestion.

Reads PDS3 (.LBL + .IMG) and PDS4 (XML label + data) products directly, so the
pipeline can work with the lossless, full bit-depth EDR originals instead of
lossy browse JPEGs. This is what makes "enhance the artifact-free original"
possible for HiRISE, LROC NAC, CTX, MOC, Viking, Lunar Orbiter, Clementine,
Chandrayaan-1 M3 and Odyssey THEMIS data.

Supported:
  - PDS3 detached and attached labels, and inline object blocks (IMAGE, LUT)
  - 8/16/32-bit signed/unsigned samples, MSB/LSB byte order, bit masks
    (e.g. 12-bit values stored in 16-bit words), band-sequential /
    band-interleaved / line-interleaved 3-D cubes, line prefix/suffix bytes
  - PDS4 XML labels with Array_2D_Image / Array_3D_Image
  - optional LUT application (Viking-style lookup tables)

Importing this module is offline and touch-free.
"""

import os
import re
import xml.etree.ElementTree as ET

import numpy as np

__all__ = [
    "parse_label", "label_flat", "label_in", "read_image",
    "read_band", "read_cube", "image_geometry", "is_pds4_text",
]

# --------------------------------------------------------------------------
# PDS3 label parsing
# --------------------------------------------------------------------------

BINARY_NUMBER = re.compile(r"^([0-9]+|16|2)#([0-9A-Fa-f]+)#$")


def _unbalanced(text):
    """True if quotes or parens are not closed (value spans more lines)."""
    depth = 0
    in_str = False
    for ch in text:
        if ch == '"':
            in_str = not in_str
        elif ch == "(" and not in_str:
            depth += 1
        elif ch == ")" and not in_str:
            depth -= 1
    return in_str or depth > 0


def _parse_value(raw):
    """Interpret one PDS3 value token."""
    s = raw.strip()
    if not s:
        return ""
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1]
        parts = []
        cur, depth, in_str = "", 0, False
        for ch in inner:
            if ch == "," and depth == 0 and not in_str:
                parts.append(cur)
                cur = ""
                continue
            if ch == '"':
                in_str = not in_str
            if ch == "(" and not in_str:
                depth += 1
            if ch == ")" and not in_str:
                depth -= 1
            cur += ch
        if cur.strip():
            parts.append(cur)
        return tuple(_parse_value(p) for p in parts)
    if s.isdigit():
        return int(s)
    m = re.match(r"^([+-]?\d+\.\d+(?:[EeDd][+-]?\d+)?)$", s)
    if m:
        return float(s.replace("D", "E").replace("d", "e"))
    m = re.match(r"^([+-]?\d+[Ee][+-]?\d+)$", s)
    if m:
        return float(s.replace("D", "E"))
    m = BINARY_NUMBER.match(s)
    if m:
        base, digits = int(m.group(1)), m.group(2)
        if base == 2:
            return int(digits, 2)
        if base == 16:
            return int(digits, 16)
        return int(digits, base)
    return s


def _is_pds4_text(text):
    return text.lstrip().startswith("<?xml") or "<PDS4_Product" in text[:4096]


def is_pds4_text(text):
    return _is_pds4_text(text)


def _parse_pds3(text):
    """Return a dict of key -> value, object paths as 'OBJ > key'."""
    data = {}
    stack = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        i += 1
        if not s:
            continue
        if s.startswith("/*"):
            continue
        if s.startswith("OBJECT") or s.startswith("GROUP"):
            name = s.split("=", 1)[1].strip() if "=" in s else s.split(" ", 1)[-1].strip()
            stack.append(name)
            continue
        if s.startswith("END_OBJECT") or s.startswith("END_GROUP") or s.startswith("END"):
            if stack and (s.startswith("END_OBJECT") or s.startswith("END_GROUP")):
                stack.pop()
            continue
        if "=" not in s:
            continue
        key, _, rest = s.partition("=")
        key = key.strip()
        val = rest.strip()
        while _unbalanced(val):
            if i >= n:
                break
            val += " " + lines[i].strip()
            i += 1
        path = " > ".join(stack + [key]) if stack else key
        data[path] = _parse_value(val)
    return data


def _xml_text(elem):
    return (elem.text or "").strip()


def _xml_get(root, names):
    """First element whose local tag matches any name, walking all children."""
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in names:
            return el
    return None


def _xml_find(root, tag):
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag:
            return el
    return None


def _parse_pds4(text):
    """Return a flat dict from a PDS4 XML label (lightweight reader)."""
    data = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return data
    ns = None
    for child in root:
        if child.tag.startswith("{"):
            ns = child.tag.split("}")[0].strip("{}")
            break
    def local(el):
        return el.tag.rsplit("}", 1)[-1]
    for el in root.iter():
        tag = local(el)
        val = _xml_text(el)
        if val:
            data["%s_%s" % (tag, el.attrib.get("name", "value"))] = val
            data.setdefault(tag, val)
        for k, v in el.attrib.items():
            data.setdefault("%s_attr_%s" % (tag, k), v)
    return data


def parse_label(path_or_text):
    """Parse a PDS3 or PDS4 label file. Returns a dict.

    path_or_text: file path, bytes, or str.
    """
    if isinstance(path_or_text, (bytes, str)) and "\n" not in path_or_text and "\r" not in path_or_text and os.path.exists(str(path_or_text)):
        with open(path_or_text, encoding="utf-8", errors="replace") as f:
            text = f.read()
        is_attached = _label_attached(text)
    elif isinstance(path_or_text, bytes):
        text = path_or_text.decode("utf-8", "replace")
        is_attached = _label_attached(text)
    else:
        text = path_or_text
        is_attached = _label_attached(text)
    if is_pds4_text(text):
        return _parse_pds4(text)
    data = _parse_pds3(text)
    data.setdefault("__attached__", is_attached)
    return data


def _label_attached(text):
    """A PDS3 label is 'attached' when the data follows in the same file.

    Detached labels name a data file; attached labels sit in front of the
    binary data and end with a bare `END` line.
    """
    if is_pds4_text(text):
        return False
    m = re.search(r"^END\s*$", text, re.M)
    return bool(m)


def label_flat(data):
    """Leaf-key -> last value mapping (drops object path prefixes)."""
    flat = {}
    for k, v in data.items():
        if k.startswith("__"):
            continue
        flat[k.split(" > ")[-1]] = v
    return flat


def label_in(data, objname, key):
    """Value of `key` inside the first OBJECT block named `objname`."""
    prefix = objname + " > "
    matches = [v for k, v in data.items()
               if k.startswith(prefix) and k.split(" > ")[-1] == key]
    return matches[-1] if matches else None


def _leaf(data, keys, default=None):
    flat = label_flat(data)
    for k in keys:
        if k in flat:
            return flat[k]
    return default


def _to_int(v):
    try:
        if v is None:
            return None
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        if v is None:
            return None
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# dtype / layout resolution
# --------------------------------------------------------------------------

_SAMPLE_DTYPE = {
    "MSB_UNSIGNED_INTEGER": ">u",
    "LSB_UNSIGNED_INTEGER": "<u",
    "MSB_SIGNED_INTEGER": ">i",
    "LSB_SIGNED_INTEGER": "<i",
    "IEEE_REAL": ">f",
    "PC_REAL": "<f",
}

_PDS4_DTYPE = {
    "UnsignedByte": "u1",
    "SignedByte": "i1",
    "UnsignedMSB2": ">u2", "UnsignedLSB2": "<u2",
    "SignedMSB2": ">i2", "SignedLSB2": "<i2",
    "UnsignedMSB4": ">u4", "UnsignedLSB4": "<u4",
    "SignedMSB4": ">i4", "SignedLSB4": "<i4",
    "IEEE754MSBSingle": ">f4", "IEEE754LSBSingle": "<f4",
    "IEEE754MSBDouble": ">f8", "IEEE754LSBDouble": "<f8",
}


def _bit_mask_value(raw):
    """PDS3 SAMPLE_BIT_MASK like '2#1111111111111111#' -> int mask."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    m = BINARY_NUMBER.match(s)
    if m:
        base, digits = int(m.group(1)), m.group(2)
        if base == 2:
            return int(digits, 2)
        return int(digits, 16 if base == 16 else base)
    try:
        return int(s)
    except ValueError:
        return None


def _dtype_from_pds3(sample_type, bits):
    spec = _SAMPLE_DTYPE.get(str(sample_type).strip().upper())
    if spec is None:
        return None
    if spec.endswith("f"):
        return np.dtype(spec + str({32: "4", 64: "8"}.get(bits, "4")))
    size = {8: "1", 16: "2", 32: "4"}.get(bits)
    if size is None:
        return None
    return np.dtype(spec + size)


def _shift_for_mask(mask):
    """Low-bit shift needed after ANDing with a PDS bit mask."""
    if not mask:
        return 0
    shift = 0
    while mask and not (mask & 1):
        mask >>= 1
        shift += 1
    return shift


# --------------------------------------------------------------------------
# image data location
# --------------------------------------------------------------------------

def _data_file_and_offset(data, text_start_offset, label_path):
    """Resolve (data_path, byte_offset) from the ^IMAGE pointer + layout."""
    flat = label_flat(data)
    pointer = None
    for k, v in data.items():
        if k.endswith("^IMAGE") or k.endswith("^DATA"):
            pointer = v
            break
    record_bytes = _to_int(flat.get("RECORD_BYTES"))
    rec_type = str(flat.get("RECORD_TYPE", "")).strip()
    label_dir = os.path.dirname(os.path.abspath(label_path)) if label_path else "."

    if isinstance(pointer, tuple):
        fname = str(pointer[0]).strip('"')
        rec = _to_int(pointer[1]) if len(pointer) > 1 else None
        nbytes = _to_int(pointer[2]) if len(pointer) > 2 else None
        path = os.path.join(label_dir, fname)
        if rec is not None and record_bytes:
            offset = rec * record_bytes
        else:
            offset = 0
        return path, offset
    if isinstance(pointer, str):
        path = os.path.join(label_dir, pointer.strip('"'))
        return path, 0
    if isinstance(pointer, int):
        attached = bool(data.get("__attached__"))
        if attached:
            # Data begins after the label's END marker in the same file.
            if label_path and os.path.exists(label_path):
                with open(label_path, "rb") as f:
                    raw = f.read()
                idx = raw.find(b"\nEND\n")
                if idx == -1:
                    idx = raw.find(b"\nEND\r\n")
                if idx == -1:
                    idx = raw.find(b"\nEND")
                if idx != -1:
                    label_len = idx + 4
                else:
                    label_len = text_start_offset
            else:
                label_len = text_start_offset
            if rec_type.upper() == "FIXED_LENGTH" and record_bytes:
                # Record-structured attached label: data begins in the record
                # the pointer names; the label occupies whole preceding records.
                return label_path, pointer * record_bytes
            return label_path, label_len
        if rec_type.upper() == "FIXED_LENGTH" and record_bytes:
            return label_path, pointer * record_bytes
        return label_path, pointer
    # No pointer: attached label, data right after END.
    if label_path and os.path.exists(label_path):
        with open(label_path, "rb") as f:
            raw = f.read()
        idx = raw.find(b"\nEND\n")
        if idx != -1:
            return label_path, idx + 4
    return label_path, text_start_offset


def _image_block(data):
    """Extract the geometry describing the IMAGE object."""
    lines = _to_int(label_in(data, "IMAGE", "LINES")) or _to_int(_leaf(data, ("LINES",)))
    samples = _to_int(label_in(data, "IMAGE", "LINE_SAMPLES")) or _to_int(_leaf(data, ("LINE_SAMPLES",)))
    bands = _to_int(label_in(data, "IMAGE", "BANDS")) or _to_int(_leaf(data, ("BANDS",)))
    sample_type = label_in(data, "IMAGE", "SAMPLE_TYPE") or _leaf(data, ("SAMPLE_TYPE",))
    bits = _to_int(label_in(data, "IMAGE", "SAMPLE_BITS")) or _to_int(_leaf(data, ("SAMPLE_BITS",)))
    mask = _bit_mask_value(label_in(data, "IMAGE", "SAMPLE_BIT_MASK") or _leaf(data, ("SAMPLE_BIT_MASK",)))
    storage = (label_in(data, "IMAGE", "BAND_STORAGE_TYPE") or
               _leaf(data, ("BAND_STORAGE_TYPE",)) or "BAND_SEQUENTIAL")
    return {
        "lines": lines, "samples": samples, "bands": bands,
        "sample_type": sample_type, "bits": bits, "mask": mask,
        "storage": str(storage).strip().upper(),
    }


def read_image(label_path, band=None, dtype_float=True):
    """Read the image referenced by a PDS3/PDS4 label.

    Returns a numpy array: 2-D (lines, samples) for a single band, or 3-D
    (bands, lines, samples) / (lines, samples, bands) depending on storage
    type when no band is requested. When dtype_float is True the array is
    float32 with missing constants mapped to NaN.
    """
    with open(label_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if is_pds4_text(text):
        return _read_pds4(label_path, band, dtype_float)
    data = _parse_pds3(text)
    data["__attached__"] = _label_attached(text)
    geom = _image_block(data)
    path, offset = _data_file_and_offset(data, 0, label_path)

    if not geom["lines"] or not geom["samples"]:
        raise ValueError("label %s has no LINES/LINE_SAMPLES" % label_path)

    flat = label_flat(data)
    prefix = _to_int(label_in(data, "IMAGE", "LINE_PREFIX_BYTES")) or 0
    suffix = _to_int(label_in(data, "IMAGE", "LINE_SUFFIX_BYTES")) or 0
    dtype = _dtype_from_pds3(geom["sample_type"], geom["bits"])
    if dtype is None:
        raise ValueError("unsupported PDS3 sample %r / %r bits"
                         % (geom["sample_type"], geom["bits"]))
    itemsize = dtype.itemsize

    bands = geom["bands"] or 1
    lines, samples = geom["lines"], geom["samples"]
    expected = _cube_bytes(lines, samples, bands, prefix, suffix, itemsize,
                           geom["storage"])

    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(expected)
    if len(raw) < expected:
        raise ValueError("data truncated in %s: have %d bytes, label declares %d"
                         % (path, len(raw), expected))
    arr = _decode_cube(raw, dtype, lines, samples, bands, prefix, suffix,
                       geom["storage"])
    if bands == 1:
        # Single-band products keep the classic 2-D (lines, samples) shape
        # regardless of storage type.
        arr = arr.reshape(lines, samples)

    if geom["mask"]:
        amask = _bit_mask_value(geom["mask"])
        shift = _shift_for_mask(amask)
        arr = ((arr & amask) >> shift) if shift else (arr & amask)

    missing = _to_float(flat.get("MISSING_CONSTANT") or flat.get("MISSING_MULTIPLIER"))
    arr = arr.copy()  # frombuffer views are read-only; downstream may mutate
    if dtype_float:
        out = arr.astype(np.float32)
        if missing is not None:
            out[arr == missing] = np.nan
        elif flat.get("VALID_MINIMUM") is not None:
            vmin = _to_float(flat.get("VALID_MINIMUM"))
            vmax = _to_float(flat.get("VALID_MAXIMUM"))
            if vmin is not None:
                out[arr < vmin] = np.nan
            if vmax is not None:
                out[arr > vmax] = np.nan
        arr = out

    # LUT application (Viking-era)
    lut = _extract_lut(data)
    if lut is not None and not dtype_float:
        clipped = np.clip(arr, 0, len(lut) - 1)
        arr = np.asarray(lut, dtype=dtype)[clipped]

    if band is not None:
        if arr.ndim == 3 and arr.shape[0] == bands and geom["storage"] == "BAND_SEQUENTIAL":
            return arr[band]
        if arr.ndim == 3:
            if arr.shape[2] == bands:
                return arr[..., band]
            if arr.shape[1] == bands:
                return arr[:, band, :]
        raise ValueError("band requested but product is 2-D")
    return arr


def _cube_bytes(lines, samples, bands, prefix, suffix, itemsize, storage):
    """Total byte size of the image data for a given band layout.

    BAND_SEQUENTIAL stores whole planes one after another, so the line
    prefix/suffix pads every line of every band. In the interleaved layouts
    one physical record holds all bands of a line (or pixel), so the
    prefix/suffix applies once per record.
    """
    if storage == "SAMPLE_INTERLEAVED":
        row = samples * bands + prefix + suffix
        return row * itemsize * lines
    if storage == "LINE_INTERLEAVED":
        row = samples * bands + prefix + suffix
        return row * itemsize * lines
    # BAND_SEQUENTIAL (PDS default)
    row = samples + prefix + suffix
    return row * itemsize * lines * bands


def _decode_cube(raw, dtype, lines, samples, bands, prefix, suffix, storage):
    """Raw image bytes -> band-laid-out array with prefix/suffix stripped.

    Returns (bands, lines, samples) for BAND_SEQUENTIAL,
            (lines, bands, samples) for LINE_INTERLEAVED,
            (lines, samples, bands) for SAMPLE_INTERLEAVED.
    """
    buf = np.frombuffer(raw, dtype=dtype)
    if storage == "SAMPLE_INTERLEAVED":
        row = samples * bands + prefix + suffix
        grid = buf[:row * lines].reshape(lines, row)
        return grid[:, prefix:prefix + samples * bands].reshape(lines, samples, bands)
    if storage == "LINE_INTERLEAVED":
        row = samples * bands + prefix + suffix
        grid = buf[:row * lines].reshape(lines, row)
        return grid[:, prefix:prefix + samples * bands].reshape(lines, bands, samples)
    # BAND_SEQUENTIAL (PDS default)
    row = samples + prefix + suffix
    grid = buf[:row * lines * bands].reshape(lines * bands, row)
    return grid[:, prefix:prefix + samples].reshape(bands, lines, samples)


def read_band(label_path, band, dtype_float=True):
    """Read a single band without loading the whole cube (BSQ only).

    For interleaved layouts the full cube is decoded and the band sliced out.
    """
    with open(label_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    data = _parse_pds3(text)
    data["__attached__"] = _label_attached(text)
    geom = _image_block(data)
    if not geom["bands"] or geom["bands"] == 1:
        return read_image(label_path, dtype_float=dtype_float)
    if not 0 <= int(band) < geom["bands"]:
        raise ValueError("band %r out of range (product has %d bands)"
                         % (band, geom["bands"]))
    if geom["storage"] != "BAND_SEQUENTIAL":
        return read_image(label_path, band=band, dtype_float=dtype_float)
    flat = label_flat(data)
    path, offset = _data_file_and_offset(data, 0, label_path)
    dtype = _dtype_from_pds3(geom["sample_type"], geom["bits"])
    prefix = _to_int(label_in(data, "IMAGE", "LINE_PREFIX_BYTES")) or 0
    suffix = _to_int(label_in(data, "IMAGE", "LINE_SUFFIX_BYTES")) or 0
    itemsize = dtype.itemsize
    row = geom["samples"] + prefix + suffix
    plane = row * itemsize * geom["lines"]
    start = offset + band * plane
    with open(path, "rb") as f:
        f.seek(start)
        raw = f.read(plane)
    if len(raw) < plane:
        raise ValueError("data truncated in %s: have %d bytes, label declares %d"
                         % (path, len(raw), plane))
    arr = np.frombuffer(raw, dtype=dtype).reshape(geom["lines"], row)
    arr = arr[:, prefix:prefix + geom["samples"]]
    if geom["mask"]:
        amask = _bit_mask_value(geom["mask"])
        shift = _shift_for_mask(amask)
        arr = ((arr & amask) >> shift) if shift else (arr & amask)
    if dtype_float:
        arr = arr.astype(np.float32)
    return arr.copy()


def read_cube(label_path, dtype_float=True):
    return read_image(label_path, dtype_float=dtype_float)


def _extract_lut(data):
    """Inline PDS3 LUT -> numpy array, or None."""
    values = label_in(data, "LUT", "LUT_DATA") or label_in(data, "LUT", "LUT_VALUE")
    if isinstance(values, tuple):
        return np.asarray([int(v) for v in values])
    return None


# --------------------------------------------------------------------------
# PDS4 reader (lightweight)
# --------------------------------------------------------------------------

def _pds4_dtype(dtype_name, byte_size):
    spec = _PDS4_DTYPE.get(dtype_name)
    if spec:
        return np.dtype(spec)
    return np.dtype("u%d" % max(1, byte_size or 1))


def _read_pds4(label_path, band=None, dtype_float=True):
    tree = ET.parse(label_path)
    root = tree.getroot()
    local = lambda el: el.tag.rsplit("}", 1)[-1]

    # data file name
    fname = None
    for el in root.iter():
        if local(el) == "File_Name":
            fname = el.text.strip()
            break
    if not fname:
        raise ValueError("no File_Name in PDS4 label %s" % label_path)
    data_path = os.path.join(os.path.dirname(os.path.abspath(label_path)), fname)

    array = None
    for el in root.iter():
        if local(el) in ("Array_2D_Image", "Array_2D_Map", "Array_2D_Spectral_Image",
                         "Array_3D_Image", "Array_3D_Map", "Array_3D_Spectral_Image"):
            array = el
            break
    if array is None:
        raise ValueError("no Array_2D/3D in PDS4 label %s" % label_path)

    elem = None
    for el in array.iter():
        if local(el) == "Element_Array":
            elem = el
            break
    dtype = np.dtype("u1")
    if elem is not None:
        dt = ""
        bs = None
        for sub in elem.iter():
            if local(sub) == "Data_Type":
                dt = sub.text.strip()
            if local(sub) == "Byte_Size":
                bs = int(sub.text.strip())
        dtype = _pds4_dtype(dt, bs)

    axes = []  # (name, size, offset, length)
    for el in array.iter():
        if local(el) == "Axis_Array":
            name = size = off = length = None
            for sub in el.iter():
                t = local(sub)
                if t == "Axis_Name":
                    name = sub.text.strip()
                elif t == "Axis_Size":
                    size = int(sub.text.strip())
                elif t == "offset":
                    off = int(sub.text.strip())
                elif t == "object_length":
                    length = int(sub.text.strip())
            if size:
                axes.append((name, size, off, length))

    if not axes:
        raise ValueError("no Axis_Array in PDS4 label %s" % label_path)

    data_offset = 0
    for el in root.iter():
        if local(el) == "Byte_Stream":
            off = el.attrib.get("offset")
            if off is not None:
                data_offset = int(off)

    sizes = [a[1] for a in axes]
    nbytes = dtype.itemsize
    for s in sizes:
        nbytes *= s
    with open(data_path, "rb") as f:
        f.seek(data_offset)
        raw = f.read(nbytes)
    arr = np.frombuffer(raw, dtype=dtype)

    if len(sizes) == 2:
        arr = arr.reshape(sizes[0], sizes[1])
    elif len(sizes) == 3:
        arr = arr.reshape(sizes)
    else:
        arr = arr.reshape(sizes)

    if dtype_float and arr.dtype.kind in "ui":
        arr = arr.astype(np.float32)
    if band is not None:
        if arr.ndim == 3 and arr.shape[0] == sizes[0] and band < sizes[0]:
            return arr[band]
        if arr.ndim == 2:
            raise ValueError("band requested but product is 2-D")
        return arr[..., band] if arr.shape[-1] > band else arr[:, band, :]
    return arr


# --------------------------------------------------------------------------
# convenience
# --------------------------------------------------------------------------

def image_geometry(label_path):
    """Best-effort (lines, samples, bands) for a label, without reading data."""
    with open(label_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if is_pds4_text(text):
        tree = ET.fromstring(text)
        local = lambda el: el.tag.rsplit("}", 1)[-1]
        sizes = []
        for el in tree.iter():
            if local(el) == "Axis_Size":
                try:
                    sizes.append(int(el.text.strip()))
                except (TypeError, ValueError):
                    pass
        if not sizes:
            return None
        return sizes[0], sizes[1], (sizes[2] if len(sizes) > 2 else 1)
    data = _parse_pds3(text)
    g = _image_block(data)
    return g["lines"], g["samples"], g["bands"] or 1
