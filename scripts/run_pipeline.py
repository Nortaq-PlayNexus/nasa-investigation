"""Orchestrate the whole acquisition-to-adjudication pipeline in-process.

Every step is invoked as a plain function call (passing its own argv list)
rather than as a subprocess that re-launches `sys.executable`. That makes the
pipeline runnable from a single frozen executable and avoids the overhead and
process-spawn fragility of nested interpreters.

Try it:

    python scripts/run_pipeline.py --query moon          # full flow
    python scripts/run_pipeline.py --from enhance --to adjudicate
    python scripts/run_pipeline.py --selftest           # run the unit tests
"""

import argparse
import os
import subprocess
import sys

# Make every module addressable; handle PyInstaller frozen (sys._MEIPASS)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _bundle = os.path.abspath(sys._MEIPASS)
    # Prefer exe_dir if it has project markers, else bundle
    if os.path.exists(os.path.join(_exe_dir, "config", "pipeline.json")) or os.path.exists(
        os.path.join(_exe_dir, "data")
    ):
        ROOT = _exe_dir
    else:
        ROOT = _bundle
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "pipeline"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

# pipeline/ and scripts/ are flat (no __init__.py), so each is imported as a
# top-level module after its directory is put on sys.path above.
import adjudicate  # noqa: E402
import analyze as analyze_mod  # noqa: E402
import benchmark  # noqa: E402
import build_catalog  # noqa: E402
import detect  # noqa: E402
import download_nasa_library  # noqa: E402
import enhance  # noqa: E402
import mark  # noqa: E402
import triage  # noqa: E402
import verify_downloads  # noqa: E402

STEPS = [
    "download",
    "catalog",
    "verify",
    "enhance",
    "detect",
    "mark",
    "analyze",
    "triage",
    "benchmark",
    "adjudicate",
]

# Extra enhancement flags you can enable with --enhance-flags (e.g.
# "--native16 --destripe"). Deep CLAHE/bilateral processing needs opencv.
EXTRA_ENHANCE = "--native16"


def run(fn, argv):
    """Call a step's main(argv) in-process, printing the invocation."""
    print("+ %s" % " ".join(["orchestrate"] + argv), flush=True)
    return fn(argv) or 0


def step_args(step, a):
    """Build the argv list for one pipeline step from the top-level args."""
    if step == "download":
        return ["--query", a.query, "--max", "20", "--out", a.raw]
    if step == "catalog":
        # Records hashes + solar geometry, then freezes data/raw with an
        # ingest-time snapshot for later --check-immutable runs.
        return ["--root", a.raw, "--snapshot"]
    if step == "verify":
        return ["--root", a.raw]
    if step == "enhance":
        args = ["--dir", a.raw, "--out", "data/processed"]
        if EXTRA_ENHANCE and not a.no_enhance_flags:
            args += EXTRA_ENHANCE.split()
        return args
    if step == "detect":
        return [
            "--dir",
            "data/processed",
            "--out",
            "data/anomalies",
            "--scales",
            "4",
            "--z",
            "3.0",
            "--min-size",
            "12",
        ]
    if step == "mark":
        return ["--candidates", "data/anomalies/candidates.csv", "--out", "data/anomalies/marked"]
    if step == "analyze":
        return ["--candidates", "data/anomalies/candidates.csv", "--out", "data/anomalies/analysis"]
    if step == "triage":
        return ["--candidates", "data/anomalies/candidates.csv", "--out", "data/anomalies/triage"]
    if step == "benchmark":
        return ["--out", "data/anomalies/benchmark"]
    # adjudicate -- --metadata joins solar geometry/pixel scale from the
    # catalog so each candidate gets a physical size and shadow-alignment score.
    return [
        "--candidates",
        "data/anomalies/candidates.csv",
        "--evaluated",
        "data/anomalies/analysis/evaluated.csv",
        "--metadata",
        "data/catalog/catalog.csv",
        "--out",
        "data/anomalies/conclusions",
    ]


MODULES = {
    "download": download_nasa_library,
    "catalog": build_catalog,
    "verify": verify_downloads,
    "enhance": enhance,
    "detect": detect,
    "mark": mark,
    "analyze": analyze_mod,
    "triage": triage,
    "benchmark": benchmark,
    "adjudicate": adjudicate,
}


def main():
    p = argparse.ArgumentParser(description="Run the full acquisition-to-triage pipeline")
    p.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0])
    p.add_argument("--to", dest="end", choices=STEPS, default=STEPS[-1])
    p.add_argument("--query", default="moon")
    p.add_argument("--raw", default="data/raw")
    p.add_argument(
        "--no-enhance-flags",
        action="store_true",
        help="do not add the default native-16-bit enhancement flag",
    )
    p.add_argument(
        "--selftest",
        action="store_true",
        help="run the unit test suite and exit (no pipeline steps)",
    )
    a = p.parse_args()

    if a.selftest:
        # frozen exe: sys.executable is the bundle, not python — run tests in-process
        if getattr(sys, "frozen", False):
            import importlib.util
            import unittest

            test_path = os.path.join(ROOT, "tests", "test_pipeline.py")
            # fallback: try bundled test file, else discover
            if os.path.exists(test_path):
                spec = importlib.util.spec_from_file_location("test_pipeline", test_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
            else:
                # no test file bundled (excluded) — run minimal smoke test
                print("selftest: no tests/test_pipeline.py bundled; running import smoke test")
                import detect  # noqa: F401

                print("smoke: common + detect imports ok")
                sys.exit(0)
            runner = unittest.TextTestRunner(verbosity=2)
            res = runner.run(suite)
            sys.exit(0 if res.wasSuccessful() else 1)
        code = subprocess.call([sys.executable, "tests/test_pipeline.py"])
        sys.exit(code)

    start_i, end_i = STEPS.index(a.start), STEPS.index(a.end)
    for s in STEPS[start_i : end_i + 1]:
        if s == "verify":
            # verify integrity, then make sure data/raw still matches the
            # ingest-time snapshot before analysis is trusted.
            if run(verify_downloads.main, step_args("verify", a)):
                print("FATAL: verification failed; investigate before continuing.", flush=True)
                sys.exit(1)
            code = build_catalog.main(["--root", a.raw, "--check-immutable"])
            if code:
                print(
                    "FATAL: data/raw differs from the ingest snapshot; "
                    "investigate before continuing.",
                    flush=True,
                )
                sys.exit(code)
        else:
            rc = run(MODULES[s].main, step_args(s, a))
            if rc:
                sys.exit(rc)


if __name__ == "__main__":
    main()
