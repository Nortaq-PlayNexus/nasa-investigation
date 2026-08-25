"""Reproducible build helper: run the tests, then package with PyInstaller.

Usage (from the project root):
    python scripts/build_app.py                 # build the pipeline CLI exe
    python scripts/build_app.py --bot           # build the Discord bot exe
    python scripts/build_app.py --fullstack     # build the full-stack EXE (API + dashboard + pipeline)
    python scripts/build_app.py --no-test       # skip the unit tests
    python scripts/build_app.py --onefile       # pass --onefile to PyInstaller

Requires the optional 'build' extras (see pyproject.toml):
    pip install -e .[dev]                       # pytest + ruff + pyinstaller
    pip install -e .[fullstack,dev]             # for --fullstack (fastapi+uvicorn)

The full-stack EXE is a single double-click app: it starts the FastAPI
server, serves app/static/index.html at / and showcase at /showcase,
exposes POST /api/analyze and pipeline controls, and opens the browser.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(ROOT, "packaging")
OUT_DIR = os.path.join(ROOT, "dist")


def confirm(prompt, default=False):
    """Repo-mode safety check so the script never silently rebuilds."""
    try:
        reply = input("%s [y/N] " % prompt).strip().lower()
    except EOFError:
        return default
    return reply in ("y", "yes")


def main():
    p = argparse.ArgumentParser(description="Run tests then package with PyInstaller")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--bot", action="store_true", help="build the Discord bot exe instead of the pipeline CLI")
    g.add_argument("--fullstack", action="store_true", help="build the full-stack EXE (API+dashboard+pipeline in one)")
    p.add_argument("--no-test", action="store_true", help="skip the unit test run")
    p.add_argument("--onefile", action="store_true", help="pass --onefile to PyInstaller")
    p.add_argument("--yes", action="store_true", help="do not prompt for confirmation")
    a = p.parse_args()

    if a.bot:
        spec = os.path.join(SPEC_DIR, "nasa-bot.spec")
        out_name = "nasa-bot"
    elif a.fullstack:
        if a.onefile:
            spec = os.path.join(SPEC_DIR, "nasa-fullstack-onefile.spec")
            out_name = "nasa-fullstack"
        else:
            spec = os.path.join(SPEC_DIR, "nasa-fullstack.spec")
            out_name = "nasa-fullstack"
    else:
        spec = os.path.join(SPEC_DIR, "nasa-pipeline.spec")
        out_name = "nasa-pipeline"

    if not os.path.exists(spec):
        sys.exit("spec not found: %s" % spec)

    # 1. Sanity-check dependencies so a broken build fails fast and clearly.
    missing = []
    for mod in ("numpy", "PIL"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        sys.exit("missing base dependency%s: %s\n"
                 "Run: pip install -r requirements.txt" %
                 ("s" if len(missing) > 1 else "", ", ".join(missing)))

    if a.fullstack:
        for mod in ("fastapi", "uvicorn"):
            try:
                __import__(mod)
            except ImportError:
                print(f"warning: {mod} not installed — install with: pip install -e .[fullstack]  (fallback stdlib server will be used)")
                break

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller not installed.\n"
                 "Run: pip install -e .[dev]   (or pip install pyinstaller)")

    # 2. Run the unit test suite unless the user opted out.
    if not a.no_test:
        print("== Running unit tests ==", flush=True)
        code = subprocess.call([sys.executable, "scripts/run_pipeline.py", "--selftest"],
                               cwd=ROOT)
        if code:
            sys.exit("tests failed (exit %d); not building.\n"
                     "Fix the failures or re-run with --no-test to force a build." % code)
    else:
        print("== Skipping unit tests (--no-test) ==", flush=True)

    # Ensure showcase is built so the EXE has content to serve
    if a.fullstack:
        showcase = os.path.join(ROOT, "showcase", "index.html")
        if not os.path.exists(showcase):
            print("== Showcase missing — building showcase/index.html ==", flush=True)
            try:
                subprocess.call([sys.executable, "scripts/build_showcase.py"], cwd=ROOT)
            except Exception as e:
                print(f"showcase build failed (ignoring): {e}")

    if not a.yes:
        if not confirm("About to run PyInstaller (builds %s). Continue?" % out_name):
            print("Aborted.")
            return

    # 3. Build into a fresh temp dir so the project's dist/ stays pristine
    #    until the build succeeds, then move just the result into dist/.
    with tempfile.TemporaryDirectory(prefix="nasa_build_") as tmp:
        os.makedirs(tmp, exist_ok=True)
        cmd = ["pyinstaller", "--noconfirm", "--distpath", tmp, "--workpath",
               os.path.join(ROOT, "build"), spec]
        print("== Building: %s ==" % " ".join(cmd), flush=True)
        code = subprocess.call(cmd, cwd=ROOT)
        if code:
            sys.exit("PyInstaller failed (exit %d)." % code)

        # The build output starts with our chosen name in tmp/.
        built = os.path.join(tmp, out_name)
        if a.onefile:
            built += ".exe"
            # onedir vs onefile: onefile produces file, not dir
            if not os.path.exists(built):
                # Windows may produce nasa-fullstack.exe without path prefix
                alt = os.path.join(tmp, out_name + ".exe")
                if os.path.exists(alt):
                    built = alt
        if not os.path.exists(built):
            sys.exit("expected build output not found: %s" % built)
        os.makedirs(OUT_DIR, exist_ok=True)
        target = os.path.join(OUT_DIR, os.path.basename(built))
        if os.path.exists(target):
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
        shutil.move(built, target)
        print("== Built -> %s ==" % target, flush=True)
        if os.path.isdir(target):
            print("   run: %s" % os.path.join(target, out_name + ".exe"))
        else:
            print("   run: %s --port 8000" % target)
            print("   or double-click in Explorer (opens http://127.0.0.1:8000)")


if __name__ == "__main__":
    main()
