"""Download from any of the curated hard-to-find archives in scripts/sources.py.

Examples:
  python scripts/download_archive.py --source ctx --mode browse --max 40 --out data/raw/mars/ctx
  python scripts/download_archive.py --source themis --mode edr --max-size-mb 250
  python scripts/download_archive.py --source moc --volume <override-url> --max 20
  python scripts/download_archive.py --list
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from download_pds import crawl
import sources


def main():
    p = argparse.ArgumentParser(description="Download from a curated obscure-source archive")
    p.add_argument("--source", help="archive name from scripts/sources.py")
    p.add_argument("--list", action="store_true", help="list known archives and exit")
    p.add_argument("--mode", choices=("browse", "edr"), default="browse",
                   help="browse = preview JPEGs; edr = lossless originals (can be huge)")
    p.add_argument("--volume", default=None, help="override the registry volume URL")
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--depth", type=int, default=None)
    p.add_argument("--max-size-mb", type=float, default=None,
                   help="skip files larger than this (strongly recommended for EDR mode)")
    p.add_argument("--max-dirs", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--manifest", default="data/raw/manifest.jsonl", help="provenance JSONL")
    p.add_argument("--out", default="data/raw/archive")
    a = p.parse_args()

    if a.list:
        sources.list_sources()
        return

    src = sources.get_source(a.source)
    print("==", src["name"])
    print("   target:", src["target"])
    print("   notes:", src["notes"])
    if not src["verified"]:
        print("   WARNING: volume path unverified; use --volume if it moved.")
    volume = a.volume or src["volume"]
    pattern = src["edr_pattern"] if a.mode == "edr" else src["browse_pattern"]
    depth = a.depth if a.depth is not None else src["depth"]
    max_dirs = a.max_dirs if a.max_dirs is not None else src["max_dirs"]
    max_size = int(a.max_size_mb * 1024 * 1024) if a.max_size_mb else None
    if max_size is None and a.mode == "edr" and src["target"] == "mars":
        print("   NOTE: EDR mode without --max-size-mb; CTX/MOC EDRs can be GBs.")
    out = os.path.join(a.out, src["target"], a.source)
    n = crawl(volume, pattern, depth, a.max, out, max_size=max_size,
              max_dirs=max_dirs, workers=a.workers, manifest=a.manifest,
              source=a.source)
    print("downloaded {} -> {}".format(n, out))


if __name__ == "__main__":
    main()
