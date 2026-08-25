import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import download, fetch_json, log, safe_name

RAW_CATEGORIES = {"perseverance": "mars2020", "ingenuity": "ingenuity"}
GALLERY_CATEGORIES = {"curiosity": "msl", "opportunity": "mer", "spirit": "mer"}


def raw_feed(category, num, page, search, newest):
    order = "sol+desc" if newest else "sol+asc"
    search = urllib.parse.quote_plus(search)
    return (f"https://mars.nasa.gov/rss/api/?feed=raw_images&category={category}&feedtype=json"
            f"&ver=1.2&num={num}&page={page}&order={order}&search={search}&")


def gallery_feed(category, num):
    q = urllib.parse.urlencode({"feed": "images", "category": category, "feedtype": "json", "num": num})
    return "https://mars.nasa.gov/rss/api/?" + q


def main():
    p = argparse.ArgumentParser(description="Download NASA Mars rover imagery")
    p.add_argument("--rover", default="perseverance", choices=sorted(set(RAW_CATEGORIES) | set(GALLERY_CATEGORIES)))
    p.add_argument("--sol", type=int, default=None, help="filter to a specific sol (raw feed only)")
    p.add_argument("--num", type=int, default=25)
    p.add_argument("--camera", default="", help="camera search term, e.g. MCZ_LEFT, NAVCAM_LEFT, MAST")
    p.add_argument("--oldest", action="store_true", help="order oldest first instead of newest")
    p.add_argument("--out", default="data/raw/mars")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    logpath = os.path.join(a.out, "downloads.log")
    cam = a.camera.strip().upper()

    photos = []
    if a.rover in RAW_CATEGORIES:
        url = raw_feed(RAW_CATEGORIES[a.rover], a.num, 0, cam, not a.oldest)
        payload = fetch_json(url)
        for item in payload.get("images", []):
            files = item.get("image_files", {}) or {}
            cam_obj = item.get("camera", {}) or {}
            if a.sol is not None and int(item.get("sol", -1)) != a.sol:
                continue
            photos.append({"img_src": files.get("full_res") or files.get("large") or files.get("medium"),
                           "title": item.get("title", ""), "sol": item.get("sol", ""),
                           "camera": cam_obj.get("instrument", ""), "earth_date": item.get("date_taken_utc", "")})
    else:
        url = gallery_feed(GALLERY_CATEGORIES[a.rover], a.num)
        payload = fetch_json(url)
        for item in payload.get("imagegalleryitems", []):
            photos.append({"img_src": item.get("FULL") or item.get("MEDIUM") or item.get("BROWSE"),
                           "title": item.get("TITLE", ""), "sol": "", "camera": "",
                           "earth_date": item.get("DATE", "")})

    photos = [ph for ph in photos if ph.get("img_src")]
    if not photos:
        print("no photos found; try a different rover/sol/camera")
        return
    for ph in photos[:a.num]:
        src = ph["img_src"]
        name = ph.get("title") or os.path.basename(src).split("?")[0]
        ext = os.path.splitext(os.path.basename(src).split("?")[0])[1] or ".jpg"
        sol = ph.get("sol")
        soldir = (f"sol{int(sol):05d}") if sol not in ("", None) else "any"
        camdir = (ph.get("camera") or cam or "any")
        dest = os.path.join(a.out, a.rover, soldir, camdir, safe_name(name) + ext)
        try:
            msg = download(src, dest)
        except Exception as e:
            log(f"download error {src}: {e}", logpath)
            continue
        if msg == "downloaded":
            with open(os.path.splitext(dest)[0] + ".meta.json", "w", encoding="utf-8") as f:
                json.dump({"rover": a.rover, "sol": ph.get("sol", ""), "camera": ph.get("camera", ""),
                           "earth_date": ph.get("earth_date", ""), "src": src}, f, indent=2)
            log(f"saved {dest} <- {src}", logpath)
    print("done")


if __name__ == "__main__":
    main()
