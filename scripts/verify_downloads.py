import argparse
import csv
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor


def sha256(path, chunk=1 << 16):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def check_file(args):
    root, r = args
    full = os.path.join(root, r["path"])
    if not os.path.exists(full):
        return ("MISSING", full, r)
    if os.path.getsize(full) != int(r["bytes"]):
        return ("SIZE MISMATCH", full, r)
    h = sha256(full)
    if h != r["sha256"]:
        return ("HASH MISMATCH", full, r)
    return ("OK", full, r)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Verify integrity of downloaded files against the catalog"
    )
    p.add_argument("--root", default="data/raw")
    p.add_argument("--catalog", default="data/catalog/catalog.csv")
    p.add_argument("--out", default="data/catalog/verify_report.txt")
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args(argv)

    report = []
    ok = bad = missing = 0
    byhash = {}
    if os.path.exists(a.catalog):
        with open(a.catalog, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for status, full, r in ex.map(check_file, [(a.root, r) for r in rows]):
                if status == "OK":
                    ok += 1
                    byhash.setdefault(r["sha256"], []).append(full)
                elif status == "MISSING":
                    missing += 1
                    report.append(f"MISSING {full}")
                else:
                    bad += 1
                    report.append(f"{status} {full}")
        for h, files in byhash.items():
            if len(files) > 1:
                report.append("DUPLICATE {}: {}".format(h, ", ".join(files)))
    else:
        report.append(f"no catalog found at {a.catalog}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    dup_groups = sum(1 for v in byhash.values() if len(v) > 1)
    print(f"ok={ok} bad={bad} missing={missing} duplicate_groups={dup_groups}")
    print("report ->", a.out)
    # Nonzero exit so pipeline/CI steps can fail loudly on integrity problems.
    return 0 if (bad == 0 and missing == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
