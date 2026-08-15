import argparse
import os

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import common
import stack


def load_array(path):
    arr = common.load_image(path)
    if arr.dtype == np.float32 or arr.dtype == np.float64:
        return arr
    return np.asarray(arr)


def is_16bit(arr):
    return arr.dtype in (np.float32, np.float64, np.uint16, np.int16)


def stretch(arr, lo=1, hi=99):
    out = arr.astype(np.float32)
    was2d = out.ndim == 2
    if was2d:
        out = out[..., np.newaxis]
    for c in range(out.shape[2]):
        ch = out[..., c]
        a, b = np.percentile(ch, lo), np.percentile(ch, hi)
        if b - a < 1:
            continue
        out[..., c] = np.clip((ch - a) * (255.0 / (b - a)), 0, 255)
    return out[..., 0] if was2d else out


def clahe(arr, clip=2.0, grid=8):
    """Contrast-limited adaptive histogram equalization per channel (cv2)."""
    import cv2
    out = arr.copy()
    was2d = out.ndim == 2
    if was2d:
        out = out[..., np.newaxis]
    cl = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid))
    for c in range(out.shape[2]):
        out[..., c] = cl.apply(out[..., c].astype(np.uint8))
    return out[..., 0] if was2d else out


def to_uint16(arr):
    """Scaled 16-bit version of a float array (native bit-depth output)."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 3:
        a = a[..., 0] if a.shape[2] == 1 else np.mean(a, axis=2)
    lo, hi = np.percentile(a, (0.5, 99.5))
    span = max(1.0, float(hi - lo))
    return np.clip((a - lo) * (65535.0 / span), 0, 65535).astype(np.uint16)


def main():
    p = argparse.ArgumentParser(description="Enhance imagery: contrast stretch, denoise, sharpen, upscale")
    p.add_argument("--dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--scale", type=int, default=2)
    p.add_argument("--max-pixels", type=int, default=30000000, help="skip images larger than this many pixels")
    p.add_argument("--exts", default=".jpg,.jpeg,.png,.tif,.tiff,.jp2,.bmp,.gif,.img,.lbl")
    p.add_argument("--deep", action="store_true",
                   help="stronger enhancement: CLAHE, bilateral denoise, high-gain unsharp, sharper upscale")
    p.add_argument("--skip-existing", action="store_true", help="do not overwrite outputs that already exist")
    p.add_argument("--destripe", action="store_true",
                   help="column-median destripe before enhancement (HiRISE-style CCD striping)")
    p.add_argument("--native16", action="store_true",
                   help="also write a 16-bit PNG alongside the 8-bit preview")
    a = p.parse_args()

    exts = tuple(a.exts.split(","))
    os.makedirs(a.out, exist_ok=True)
    count = 0
    files = []
    for root, dirs, names in os.walk(a.dir):
        for n in names:
            if n.lower().endswith(exts):
                files.append(os.path.join(root, n))
    for path in sorted(files):
        base = os.path.basename(path)
        rel = os.path.dirname(os.path.relpath(path, a.dir))
        try:
            w0, h0 = common.image_dims(path)
        except Exception as e:
            print("skip {} ({})".format(base, e))
            continue
        if w0 * h0 > a.max_pixels:
            print("skip {} ({}x{} px, over {} pixel limit)".format(base, w0, h0, a.max_pixels))
            continue
        destdir = os.path.join(a.out, rel)
        os.makedirs(destdir, exist_ok=True)
        stem = os.path.splitext(base)[0]
        dest = os.path.join(destdir, stem + "_enh.png")
        if a.skip_existing and os.path.exists(dest):
            print("skip {} (already enhanced)".format(base))
            continue
        try:
            raw = load_array(path)
            if a.destripe and is_16bit(raw) and raw.ndim == 2:
                raw = stack.destripe(raw)
            arr = stretch(raw)
        except Exception as e:
            print("skip {} ({})".format(base, e))
            continue
        im = Image.fromarray(arr.astype(np.uint8))
        if a.deep:
            import cv2
            im = Image.fromarray(clahe(np.asarray(im), clip=2.5, grid=8))
            im = im.filter(ImageFilter.MedianFilter(3))
            arr_d = np.asarray(im)
            arr_d = cv2.bilateralFilter(arr_d, d=5, sigmaColor=60, sigmaSpace=60)
            im = Image.fromarray(arr_d)
            im = im.filter(ImageFilter.UnsharpMask(radius=3, percent=220, threshold=1))
        else:
            im = ImageOps.autocontrast(im)
            im = im.filter(ImageFilter.MedianFilter(3))
            im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))
        if a.scale > 1:
            w, h = im.size
            im = im.resize((w * a.scale, h * a.scale), Image.LANCZOS)
        im.save(dest)
        if a.native16 and is_16bit(raw):
            Image.fromarray(to_uint16(raw)).save(os.path.join(destdir, stem + "_enh16.png"))
        count += 1
    print("enhanced {} files -> {}".format(count, a.out))


if __name__ == "__main__":
    main()
