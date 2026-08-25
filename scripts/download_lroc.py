import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from download_pds import crawl


def main():
    p = argparse.ArgumentParser(description="Download LROC (Lunar Reconnaissance Orbiter) images; thin wrapper over download_pds")
    p.add_argument("--volume", default="https://pds-imaging.jpl.nasa.gov/data/lro/XXDELETEME_lroc/edr/")
    p.add_argument("--pattern", default=r"NAC.*\.IMG$")
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--max-size-mb", type=float, default=12, help="skip files larger than this many MB")
    p.add_argument("--max-dirs", type=int, default=50, help="stop after visiting this many directories")
    p.add_argument("--out", default="data/raw/moon/lroc")
    a = p.parse_args()
    n = crawl(a.volume, a.pattern, a.depth, a.max, a.out, max_size=int(a.max_size_mb * 1024 * 1024) if a.max_size_mb else None, max_dirs=a.max_dirs)
    print(f"downloaded {n}")


if __name__ == "__main__":
    main()
