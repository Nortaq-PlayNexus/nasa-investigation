import argparse
import os
import subprocess
import sys

STEPS = ["download", "catalog", "verify", "enhance", "detect", "mark",
         "analyze", "triage", "benchmark", "adjudicate"]

# Extra enhancement flags you can enable with --enhance-flags (e.g.
# "--native16 --destripe"). Deep CLAHE/bilateral processing needs opencv.
EXTRA_ENHANCE = "--native16"


def sh(args):
    print("+ " + " ".join(args), flush=True)
    return subprocess.call([sys.executable] + args)


def main():
    p = argparse.ArgumentParser(description="Run the full acquisition-to-triage pipeline")
    p.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0])
    p.add_argument("--to", dest="end", choices=STEPS, default=STEPS[-1])
    p.add_argument("--query", default="moon")
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--no-enhance-flags", action="store_true",
                   help="do not add the default native-16-bit enhancement flag")
    p.add_argument("--selftest", action="store_true",
                   help="run the unit test suite and exit (no pipeline steps)")
    a = p.parse_args()

    if a.selftest:
        code = subprocess.call([sys.executable, "tests/test_pipeline.py"])
        sys.exit(code)

    start_i, end_i = STEPS.index(a.start), STEPS.index(a.end)
    for s in STEPS[start_i:end_i + 1]:
        if s == "download":
            sh(["scripts/download_nasa_library.py", "--query", a.query, "--max", "20", "--out", a.raw])
        elif s == "catalog":
            # Records hashes + solar geometry, then freezes data/raw with an
            # ingest-time snapshot for later --check-immutable runs.
            sh(["scripts/build_catalog.py", "--root", a.raw, "--snapshot"])
        elif s == "verify":
            sh(["scripts/verify_downloads.py", "--root", a.raw])
            code = subprocess.call([sys.executable, "scripts/build_catalog.py",
                                    "--root", a.raw, "--check-immutable"])
            if code:
                print("FATAL: data/raw differs from the ingest snapshot; "
                      "investigate before continuing.", flush=True)
                sys.exit(code)
        elif s == "enhance":
            args = ["pipeline/enhance.py", "--dir", a.raw, "--out", "data/processed"]
            if not a.no_enhance_flags and EXTRA_ENHANCE:
                args += EXTRA_ENHANCE.split()
            sh(args)
        elif s == "detect":
            sh(["pipeline/detect.py", "--dir", "data/processed", "--out", "data/anomalies",
                "--scales", "4", "--z", "3.0", "--min-size", "12"])
        elif s == "mark":
            sh(["pipeline/mark.py", "--candidates", "data/anomalies/candidates.csv",
                "--out", "data/anomalies/marked"])
        elif s == "analyze":
            sh(["pipeline/analyze.py", "--candidates", "data/anomalies/candidates.csv",
                "--out", "data/anomalies/analysis"])
        elif s == "triage":
            sh(["pipeline/triage.py", "--candidates", "data/anomalies/candidates.csv",
                "--out", "data/anomalies/triage"])
        elif s == "benchmark":
            sh(["pipeline/benchmark.py", "--out", "data/anomalies/benchmark"])
        elif s == "adjudicate":
            # --metadata joins solar geometry/pixel scale from the catalog so
            # each candidate gets a physical size and shadow-alignment score.
            sh(["pipeline/adjudicate.py", "--candidates", "data/anomalies/candidates.csv",
                "--evaluated", "data/anomalies/analysis/evaluated.csv",
                "--metadata", "data/catalog/catalog.csv",
                "--out", "data/anomalies/conclusions"])

if __name__ == "__main__":
    main()
