"""Audit strip coverage for the adjudicated conclusions.

Reports how many candidates have a corresponding evidence strip on disk. This is
a data-integrity gate for the published dossier (every lead shown should have a
frame to inspect).

    python scripts/audit_strips.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as bs  # noqa: E402


def main() -> int:
    si = bs.strip_index()
    rows = bs.read_csv(bs.CONC / "adjudicated.csv")
    leads = bs.read_csv(bs.CONC / "leads.csv")
    miss_c = [r.get("image", "") for r in rows if not si.get(r.get("image", ""))]
    miss_l = [r.get("image", "") for r in leads if not si.get(r.get("image", ""))]
    print(f"strips on disk     : {len(si)}")
    print(f"candidates         : {len(rows)}  (without strip: {len(miss_c)})")
    print(f"leads              : {len(leads)}  (without strip: {len(miss_l)})")
    for m in miss_c[:10]:
        print("  candidate missing strip:", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
