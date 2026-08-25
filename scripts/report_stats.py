"""Summarize the adjudicated HiRISE conclusions into a compact stats JSON.

Useful for the public dossier site and for quick facility reporting. Reads the
conclusions CSVs directly and never touches the raw imagery.

    python scripts/report_stats.py                 # print to stdout
    python scripts/report_stats.py --out stats.json # write file
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONC = ROOT / "data" / "anomalies" / "conclusions"
LEADS_DIR = CONC / "leads"

_ACQ = re.compile(r"^([A-Za-z]+_\d+_\d+)")


def acq_of(image: str) -> str:
    m = _ACQ.match(image or "")
    return m.group(1) if m else (image or "").split(".")[0]


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main() -> int:
    adj = CONC / "adjudicated.csv"
    leads = CONC / "leads.csv"
    if not adj.exists():
        print("report_stats: missing", adj, file=sys.stderr)
        return 2
    rows = list(csv.DictReader(adj.open(encoding="utf-8-sig")))
    lead_rows = list(csv.DictReader(leads.open(encoding="utf-8-sig"))) if leads.exists() else []

    verdicts = Counter(r.get("verdict", "UNKNOWN") for r in rows)
    acq = Counter(acq_of(r.get("image", "")) for r in rows)
    top_acq = [{"acq": k, "count": v} for k, v in acq.most_common(10)]

    conf = [r for r in rows if (r.get("verdict") or "").startswith("CONFIRMED")]
    avg_contrast = (sum(num(r.get("contrast")) for r in rows) / len(rows)) if rows else 0.0

    out = {
        "candidates": len(rows),
        "leads": len(lead_rows),
        "confirmed_leads": len(conf),
        "verdicts": dict(verdicts),
        "avg_contrast": round(avg_contrast, 3),
        "top_acquisitions": top_acq,
        "findings": len(list(LEADS_DIR.glob("F-*.md"))),
    }
    text = json.dumps(out, indent=2)
    if "--out" in sys.argv:
        i = sys.argv.index("--out") + 1
        Path(sys.argv[i]).write_text(text + "\n", encoding="utf-8")
        print("wrote", sys.argv[i])
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
