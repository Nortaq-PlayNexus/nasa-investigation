import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import download, log
from download_pds import crawl

BROWSE_BASE = "https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/RDR/ESP/"


def pds_url(pid):
    prefix = pid.split("_")[0]
    return "{}/{}/{}/{}_{}.JP2".format(
        "https://hirise-pds.lpl.arizona.edu/PDS/EDR", prefix, pid, pid, "RED"
    )


def main():
    p = argparse.ArgumentParser(description="Download MRO HiRISE imagery from the PDS")
    p.add_argument(
        "--volume", default=BROWSE_BASE, help="PDS root to crawl (browse products by default)"
    )
    p.add_argument(
        "--pattern",
        default=r"_(RED|MIRB|MRGB)\.browse\.jpg$",
        help="regex matched against file names",
    )
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--max", type=int, default=20)
    p.add_argument(
        "--max-size-mb", type=float, default=15, help="skip files larger than this many MB"
    )
    p.add_argument(
        "--max-dirs", type=int, default=50, help="stop after visiting this many directories"
    )
    p.add_argument(
        "--fetch",
        default="",
        help="download a full-res RED JP2 by observation ID, e.g. ESP_011264_1090",
    )
    p.add_argument("--out", default="data/raw/mars/hirise")
    a = p.parse_args()

    if a.fetch:
        pid = a.fetch
        url = pds_url(pid)
        os.makedirs(a.out, exist_ok=True)
        dest = os.path.join(a.out, pid + "_RED.JP2")
        try:
            msg = download(url, dest)
        except Exception as e:
            log(f"download error {url}: {e}", os.path.join(a.out, "downloads.log"))
            return
        log(f"{msg} {dest}", os.path.join(a.out, "downloads.log"))
        return

    max_size = int(a.max_size_mb * 1024 * 1024) if a.max_size_mb else None
    n = crawl(a.volume, a.pattern, a.depth, a.max, a.out, max_size=max_size)
    print(f"downloaded {n}")


if __name__ == "__main__":
    main()
