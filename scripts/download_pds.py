import argparse
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import download, download_many, log, safe_name

HREF = re.compile(r'<a href="([^"]+)">.*?</a>(.*?)\n', re.I)
SIZE_CELL = re.compile(r'indexcolsize[^>]*>([^<]*)</td>', re.I)


def parse_size(text):
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    m = re.match(r"^(\d+(?:\.\d+)?)([KMG]?)$", text, re.I)
    if m:
        mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get(m.group(2).upper(), 1)
        try:
            return int(float(m.group(1)) * mult)
        except ValueError:
            return None
    return None


def list_dir(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nasa-investigation/1.0"}), timeout=60) as r:
                html = r.read().decode("utf-8", "ignore")
            base = url.rstrip("/")
            out = []
            sizes = SIZE_CELL.findall(html)
            for i, m in enumerate(HREF.finditer(html)):
                href = m.group(1)
                if href in ("./", "../", ""):
                    continue
                if href.startswith("http"):
                    full = href
                else:
                    full = base + "/" + href.lstrip("/")
                size = parse_size(sizes[i]) if i < len(sizes) else None
                out.append((full, size))
            return out
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def crawl(volume, pattern, depth, maxcount, out, suffix="", max_size=None,
          max_dirs=50, workers=4, manifest=None, source=""):
    """Crawl a PDS HTTP directory tree and download files matching a pattern.

    Directory discovery stays sequential (the listing HTML is light); the
    matching file downloads run in parallel with hash-verified provenance.
    """
    os.makedirs(out, exist_ok=True)
    logpath = os.path.join(out, "downloads.log")
    rx = re.compile(pattern, re.I)
    base = volume.rstrip("/")
    todo = [base]
    seen = set()
    tasks = []
    dirs_visited = 0
    while todo and len(tasks) < maxcount:
        url = todo.pop()
        if url in seen:
            continue
        seen.add(url)
        dirs_visited += 1
        if dirs_visited > max_dirs:
            log("stopped after {} directories".format(dirs_visited), logpath)
            break
        try:
            entries = list_dir(url)
        except Exception as e:
            log("list error {}: {}".format(url, e), logpath)
            continue
        for full, size in entries:
            if len(tasks) >= maxcount:
                break
            name = full.rsplit("/", 1)[-1]
            is_dir = full.endswith("/")
            if not is_dir and rx.search(name):
                if max_size is not None:
                    if size is None or size <= 0:
                        log("skip (unknown size) {}".format(full), logpath)
                        continue
                    if size > max_size:
                        log("skip ({} bytes) {}".format(size, full), logpath)
                        continue
                dest = os.path.join(out, safe_name(name) + suffix)
                tasks.append((full, dest, None))
                continue
            rel_depth = url.count("/") - base.count("/")
            if is_dir and rel_depth < depth:
                todo.append(full)
    if not tasks:
        log("no matching files found under {}".format(volume), logpath)
        return 0
    results = download_many(tasks[:maxcount], workers=workers,
                            manifest=manifest, source=source)
    count = 0
    for url, dest, status in results:
        if status == "downloaded":
            count += 1
        log("{} {}".format(status, dest), logpath)
    return count


def main():
    p = argparse.ArgumentParser(description="Crawl a PDS HTTP directory listing and download files matching a pattern")
    p.add_argument("--volume", required=True, help="root listing URL")
    p.add_argument("--pattern", required=True, help="regex matched against file names")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--max-size-mb", type=float, default=None, help="skip files larger than this many MB")
    p.add_argument("--max-dirs", type=int, default=50, help="stop after visiting this many directories")
    p.add_argument("--workers", type=int, default=4, help="parallel downloads")
    p.add_argument("--manifest", default="data/raw/manifest.jsonl", help="provenance JSONL")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    max_size = int(a.max_size_mb * 1024 * 1024) if a.max_size_mb else None
    n = crawl(a.volume, a.pattern, a.depth, a.max, a.out, max_size=max_size,
              max_dirs=a.max_dirs, workers=a.workers, manifest=a.manifest)
    print("downloaded {}".format(n))


if __name__ == "__main__":
    main()
