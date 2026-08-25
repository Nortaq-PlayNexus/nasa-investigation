# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: the acquisition-to-adjudication pipeline CLI as one exe.

Build from the project root with either:

    python scripts/build_app.py            # shorthand (runs tests first)
    pyinstaller packaging/nasa-pipeline.spec --noconfirm

See packaging/README.md for full instructions.
"""

from pathlib import Path

# This spec lives in packaging/, so the project root is one directory up.
ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "scripts" / "run_pipeline.py")],
    pathex=[
        str(ROOT),                 # script-relative, "import common", etc.
        str(ROOT / "pipeline"),    # pipeline modules are flat top-level imports
        str(ROOT / "scripts"),     # download/build_catalog/verify are top-level too
    ],
    binaries=[],
    datas=[
        (str(ROOT / "config" / "pipeline.json"), "config"),
        (str(ROOT / "config" / "sources.yaml"), "config"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nasa-pipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="nasa-pipeline",
)
