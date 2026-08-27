"""Validate the adjudicated HiRISE conclusions for schema + sanity.

Run in CI / before publishing the dossier:

    python scripts/validate_conclusions.py            # checks adjudicated.csv + leads.csv
    python scripts/validate_conclusions.py --strict    # non-zero exit on any warning

Exits non-zero if any hard error is found.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"

REQUIRED = ["image", "verdict", "score", "x", "y", "w", "h", "contrast"]
NUMERIC = ["score", "x", "y", "w", "h", "contrast"]
ALLOWED = {
    "CONFIRMED-LEAD",
    "PROMISING",
    "TERRAIN",
    "EXPLAINED-ARTIFACT",
    "NOISE",
    "WEAK",
    "UNKNOWN",
}
_ACQ = re.compile(r"^([A-Za-z]+_\d+_\d+)")


def is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def check_file(path: Path, errors: list[str], warns: list[str]) -> int:
    if not path.exists():
        errors.append(f"missing file: {path.name}")
        return 0
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    cols = set(rows[0].keys()) if rows else set()
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        errors.append(f"{path.name}: missing columns {missing}")
    n = 0
    for i, r in enumerate(rows, 1):
        n += 1
        for c in REQUIRED:
            if c not in cols:
                continue
            if not (r.get(c) or "").strip():
                errors.append(f"{path.name} row {i}: empty '{c}'")
        for c in NUMERIC:
            if c in cols and not is_num(r.get(c)):
                errors.append(f"{path.name} row {i}: '{c}' not numeric ({r.get(c)!r})")
        v = (r.get("verdict") or "").strip()
        if v and v not in ALLOWED:
            warns.append(f"{path.name} row {i}: unknown verdict '{v}'")
        img = r.get("image", "")
        if img and not _ACQ.match(img) and "." not in img:
            warns.append(f"{path.name} row {i}: odd image name '{img}'")
    print(f"  {path.name}: {n} rows checked")
    return n


def main() -> int:
    errors: list[str] = []
    warns: list[str] = []
    na = check_file(CONC / "adjudicated.csv", errors, warns)
    nl = check_file(CONC / "leads.csv", errors, warns)
    print(f"validated {na + nl} rows; {len(errors)} errors, {len(warns)} warnings")
    for e in errors[:20]:
        print("  ERROR:", e)
    for w in warns[:10]:
        print("  warn:", w)
    if errors:
        return 1
    if "--strict" in sys.argv and warns:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
