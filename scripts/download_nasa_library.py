import argparse
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import download, fetch_json, log, safe_name

BODIES = {
    "moon": ["moon", "lunar", "lro", "apollo", "crater", "regolith", "tranquility", "selene"],
    "mars": ["mars", "martian", "mro", "hirise", "perseverance", "curiosity", "opportunity", "spirit", "deimos", "phobos"],
}


def detect_body(text):
    t = text.lower()
    for body, keys in BODIES.items():
        if any(k in t for k in keys):
            return body
    return "other"


def pick_asset(links):
    cands = [x.get("href", "") for x in links if x.get("href", "").startswith("http")]
    if not cands:
        return ""
    chosen = ""
    for c in cands:
        if "~orig" in c:
            chosen = c
            break
    if not chosen:
        chosen = cands[-1]
    return urllib.parse.quote(chosen, safe=":/?&=%")


def main():
    p = argparse.ArgumentParser(description="Download NASA image/video library search results")
    p.add_argument("--query", required=True)
    p.add_argument("--media-type", default="image", choices=["image", "video", "audio"])
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--out", default="data/raw")
    p.add_argument("--page-size", type=int, default=100)
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    logpath = os.path.join(a.out, "downloads.log")
    page = 1
    seen = 0
    while seen < a.max:
        q = urllib.parse.urlencode({"q": a.query, "media_type": a.media_type, "page": page,
                                    "page_size": min(a.page_size, a.max - seen)})
        url = "https://images-api.nasa.gov/search?" + q
        try:
            data = fetch_json(url)
        except Exception as e:
            log("search error: {}".format(e), logpath)
            break
        items = data.get("collection", {}).get("items", [])
        if not items:
            break
        for item in items:
            if seen >= a.max:
                break
            meta = item.get("data", [{}])[0]
            href = pick_asset(item.get("links", []))
            if not href:
                continue
            ext = os.path.splitext(href.split("?")[0])[1] or (".mp4" if a.media_type == "video" else ".bin")
            body = detect_body((meta.get("title", "") or "") + " " + (meta.get("description", "") or ""))
            stem = safe_name((meta.get("nasa_id") or meta.get("title") or "item")) + ext
            dest = os.path.join(a.out, body, stem)
            try:
                msg = download(href, dest)
            except Exception as e:
                log("download error {}: {}".format(href, e), logpath)
                continue
            if msg == "downloaded":
                with open(os.path.splitext(dest)[0] + ".meta.json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                log("saved {} <- {}".format(dest, href), logpath)
            seen += 1
        page += 1
    print("done, {} items".format(seen))


if __name__ == "__main__":
    main()
