# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: full-stack NASA Investigation EXE — military grade, everything in one.

Bundles into a single portable EXE directory (or single file with --onefile):
  - app/launcher.py  (entry, starts FastAPI server + opens browser)
  - app/server.py    (FastAPI + stdlib fallback, all API routes)
  - app/static/*     (new full-stack dashboard at /)
  - showcase/*       (full showcase + img thumbs — galleries in-exe)
  - pipeline/*, scripts/*  (all pipeline modules as top-level imports)
  - config/*, docs/*, findings/* (methodology, chain of custody)
  - data/catalog + data/anomalies (conclusions, strips, audit, triage, benchmark)
  — raw archives (data/raw, data/processed full-res, analysis/crops, marked full-res)
    are NOT bundled (multi-GB); gallery thumbs in showcase/img ARE bundled
    so the EXE is self-contained and galleries work offline. Full-res originals
    remain downloadable via the pipeline.

Military-grade hardening preserved frozen:
  - audit trail (audit.jsonl) with SHA-256, atomic writes, deterministic RNG,
    BH-FDR, validation, snapshot/immutable checks — all via pipeline/common.py
  - one-click launch, no installer, no external deps, runs offline.

Build:
  python scripts/build_app.py --fullstack          # -> dist/nasa-fullstack/
  python scripts/build_app.py --fullstack --onefile
  pyinstaller packaging/nasa-fullstack.spec --noconfirm

Run:
  dist/nasa-fullstack/nasa-fullstack.exe              # opens http://127.0.0.1:8000
  dist/nasa-fullstack/nasa-fullstack.exe --port 3000 --no-browser
  nasa-fullstack.exe --cli --from detect --to adjudicate
  nasa-fullstack.exe --cli --selftest
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

# ---------------------------------------------------------------------------
# datas: everything the EXE should serve without needing external files
# ---------------------------------------------------------------------------
datas = [
    (str(ROOT / "config" / "pipeline.json"), "config"),
    (str(ROOT / "config" / "sources.yaml"), "config"),
]

# Frontend: bundle the dossier site/ as app/static so the frozen exe serves it
# at / (the site uses root-relative assets/, results/, report/ which the server
# mounts). In dev, server.py prefers site/ directly; in the exe, app/static == site.
if (ROOT / "site").exists():
    datas.append((str(ROOT / "site"), "app/static"))

# showcase: full gallery (index.html + img thumbs + css/js is inline)
# 90 MB — the portable gallery. Full-res originals stay in data/processed
# and are fetched on demand, but thumbs make the gallery work offline.
if (ROOT / "showcase").exists():
    # Only bundle if showcase was built (build_app.py builds it if missing)
    # Use the whole folder so /showcase/img/* thumbs are in-exe
    datas.append((str(ROOT / "showcase"), "showcase"))

# docs + findings + templates (small, always useful for /data mounts)
for extra in ["docs", "findings"]:
    p = ROOT / extra
    if p.exists():
        datas.append((str(p), extra))

# Key data artifacts — conclusions, audit, catalog, triage, benchmark
# We include whole conclusions (strips 39MB + csvs) and small siblings;
# we EXCLUDE huge analysis/crops (1.48GB) and marked full-res (1.38GB)
# and data/processed full-res (2GB) — their downscaled thumbs live in showcase.
# For dirs, dest must be the full relative path (e.g. data/anomalies/conclusions)
# For files, dest is parent dir.
for rel in [
    "data/catalog/catalog.csv",
    "data/catalog/immutable.json",
    "data/anomalies/candidates.csv",
    "data/anomalies/audit.jsonl",
    "data/anomalies/analysis/evaluated.csv",
    "data/anomalies/analysis/report.html",
    "data/anomalies/conclusions",
    "data/anomalies/benchmark",
    "data/anomalies/triage",
]:
    src = ROOT / rel
    if not src.exists():
        continue
    if src.is_dir():
        # bundle dir contents into same relative path inside bundle
        datas.append((str(src), str(src.relative_to(ROOT))))
    else:
        if src.stat().st_size < 30 * 1024 * 1024:
            datas.append((str(src), str(src.parent.relative_to(ROOT))))

# Bundle test suite for --cli --selftest inside frozen exe
tests_file = ROOT / "tests" / "test_pipeline.py"
if tests_file.exists():
    datas.append((str(tests_file), "tests"))

# Ensure the mounted data tree has at least empty dirs for writes (audit, uploads)
for d in ["data/raw", "data/processed", "data/catalog", "data/anomalies"]:
    p = ROOT / d
    if p.exists() and not any((ROOT / r).exists() for r in [f"{d}/catalog.csv", f"{d}/conclusions"]):
        pass

a = Analysis(
    [str(ROOT / "app" / "launcher.py")],
    pathex=[
        str(ROOT),
        str(ROOT / "pipeline"),
        str(ROOT / "scripts"),
        str(ROOT / "app"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "fastapi.responses",
        "starlette",
        "starlette.responses",
        "starlette.staticfiles",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.routing",
        "anyio",
        "sniffio",
        "PIL",
        "PIL.Image",
        "PIL.ImageFilter",
        "numpy",
        "scipy",
        "scipy.ndimage",
        "multipart",
        "python_multipart",
        "common",
        "detect",
        "analyze",
        "adjudicate",
        "benchmark",
        "enhance",
        "mark",
        "triage",
        "pds",
        "metadata",
        "photometry",
        "stereo",
        "changedet",
        "stack",
        "build_catalog",
        "verify_downloads",
        "download_nasa_library",
        "download_rover",
        "download_hirise",
        "download_lroc",
        "download_pds",
        "download_archive",
        "sources",
        "check_stereo",
        "chase_leads",
        "rebuild_report",
        "build_showcase",
        "run_pipeline",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PySide2", "PySide6",
        "IPython", "jupyter", "notebook",
        # heavy libs not used by the frozen pipeline — keep bundle lean & analysis fast
        "torch", "torchvision", "torchaudio", "tensorflow", "pandas", "pyarrow",
        "sqlalchemy", "psutil", "cryptography", "fsspec", "numba", "llvmlite",
        "huggingface_hub", "transformers", "datasets", "accelerate",
        "numpy.distutils",
        "lxml", "openpyxl", "PIL.ImageQt",
        "agency_swarm", "aider_chat", "rich", "pygments", "pytest",
        "scipy.spatial", "scipy.linalg", "scipy.stats", "scipy.special",
        "cv2",  # opencv included via hidden but not via hook scan if excluded? we keep cv2 hook for optional
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nasa-fullstack",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="nasa-fullstack",
)
