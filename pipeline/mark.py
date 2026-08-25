import argparse
import csv
import os

import common
from PIL import Image, ImageDraw

PALETTE = common.PALETTE


def main(argv=None):
    p = argparse.ArgumentParser(description="Draw anomaly boxes onto copies of the source images")
    p.add_argument("--candidates", required=True)
    p.add_argument("--out", default="data/anomalies/marked")
    p.add_argument("--fill-alpha", type=int, default=55, help="translucency of the box fill")
    p.add_argument("--max-size", type=int, default=40000000, help="skip images above this many pixels")
    a = p.parse_args(argv)

    with open(a.candidates, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_path = {}
    for r in rows:
        by_path.setdefault(r["path"], []).append(r)

    os.makedirs(a.out, exist_ok=True)
    marked = 0
    total_boxes = 0
    for path, boxes in sorted(by_path.items()):
        if not os.path.exists(path):
            continue
        try:
            base = Image.open(path).convert("RGBA")
        except Exception:
            continue
        if base.width * base.height > a.max_size:
            print(f"skip {os.path.basename(path)} ({base.width}x{base.height} px, too large)")
            continue
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for i, r in enumerate(boxes):
            x, y, w, h = (int(r[k]) for k in ("x", "y", "w", "h"))
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(base.width, x + w), min(base.height, y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            color = PALETTE[i % len(PALETTE)]
            lw = max(2, min(x1 - x0, y1 - y0) // 20)
            d.rectangle([x0, y0, x1, y1], outline=color + (255,), width=lw)
            d.rectangle([x0, y0, x1, y1], fill=color + (a.fill_alpha,))
            d.text((x0 + 3, max(0, y0 - 11)), "#{} score={}".format(i + 1, r["score"]),
                   fill=color + (255,))
        base = Image.alpha_composite(base, overlay).convert("RGB")
        dest = os.path.join(a.out, "marked_" + os.path.basename(path))
        base.save(dest, optimize=True)
        marked += 1
        total_boxes += len(boxes)
        print(f"marked {os.path.basename(path)} ({len(boxes)} boxes) -> {dest}")
    print(f"marked {marked} images, {total_boxes} boxes -> {a.out}")


if __name__ == "__main__":
    main()
