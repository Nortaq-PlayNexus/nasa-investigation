import argparse
import csv
import html
import os

import common
from PIL import Image, ImageDraw

PALETTE = common.PALETTE


def fit(im, thumb_size):
    scale = thumb_size / float(max(im.width, im.height))
    return im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)


def draw_boxes(im, boxes, thumb_size):
    thumb = fit(im, thumb_size)
    scale = thumb.width / float(im.width)
    d = ImageDraw.Draw(thumb)
    for i, (x, y, w, h) in enumerate(boxes):
        x0, y0 = x * scale, y * scale
        x1, y1 = (x + w) * scale, (y + h) * scale
        color = PALETTE[i % len(PALETTE)]
        lw = max(2, int(min(x1 - x0, y1 - y0) / 20))
        d.rectangle([x0, y0, x1, y1], outline=color, width=lw)
        d.text((x0 + 3, max(0, y0 - 11)), f"#{i + 1}", fill=color)
    return thumb


def main(argv=None):
    p = argparse.ArgumentParser(description="Build an HTML triage page from candidates.csv")
    p.add_argument("--candidates", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--thumb-size", type=int, default=640)
    p.add_argument("--no-mark", action="store_true", help="do not draw boxes on thumbnails")
    a = p.parse_args(argv)

    with open(a.candidates, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_path = {}
    for r in rows:
        by_path.setdefault(r["path"], []).append(r)

    os.makedirs(a.out, exist_ok=True)
    cards = []
    i = 0
    total_regions = 0
    for path, group in sorted(by_path.items()):
        if not os.path.exists(path):
            continue
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue
        # Number boxes by descending score so #1 is always the best candidate.
        group = sorted(group, key=lambda r: float(r["score"]), reverse=True)
        boxes = [(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])) for r in group]
        thumb_path = os.path.join(a.out, f"thumb_{i:03d}.jpg")
        if a.no_mark:
            thumb = fit(im, a.thumb_size)
        else:
            thumb = draw_boxes(im, boxes, a.thumb_size)
        thumb.save(thumb_path, quality=85)
        shown = os.path.basename(thumb_path)
        best = group[0]
        top_txt = ", ".join("#{} (score {})".format(j + 1, t["score"])
                            for j, t in enumerate(group[:5]))
        cards.append(
            "<div class='card'><a href='{}'><img src='{}'></a>"
            "<p><b>{}</b><br>{} regions, best: {}<br>fill={} score={}</p></div>".format(
                shown, shown, html.escape(best["image"]),
                len(group), html.escape(top_txt), best["fill"], best["score"]))
        total_regions += len(group)
        i += 1

    style = ("body{font-family:sans-serif;background:#101418;color:#d8dee6;margin:2rem}"
             ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}"
             ".card{border:1px solid #2a3138;padding:.5rem;background:#171c22}"
             "img{max-width:100%}p{font-size:.75rem;word-break:break-all}")
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>Candidate triage</title>"
            "<style>%s</style></head>"
            "<body><h1>Candidate triage</h1>"
            "<p>%d images &middot; %d candidate regions &middot; boxes numbered by score</p>"
            "<div class='grid'>%s</div></body></html>"
            % (style, len(cards), total_regions, "".join(cards)))
    common.atomic_text_write(os.path.join(a.out, "index.html"), page)
    print(f"triage page with {len(cards)} cards -> {a.out}")


if __name__ == "__main__":
    main()
