# data/ layout

```
data/
  raw/moon/       downloaded lunar originals (read-only after ingest)
  raw/mars/       downloaded martian originals (read-only after ingest)
  processed/      enhanced/derived images (never your only copy)
  catalog/        catalog.csv, catalog.json, hirise_catalog.json, verify_report.txt
  anomalies/      candidates.csv, triage/ (HTML page with crops)
  downloads.log   acquisition audit trail (append-only)
```

Conventions:
- Every file under raw/ is recorded in the catalog with a sha256 hash.
- Never delete or edit files under raw/ after cataloging.
- `.meta.json` sidecar files hold source URL, sol, camera, dates.
- The catalog + hashes are the chain of custody for anything you later claim.
