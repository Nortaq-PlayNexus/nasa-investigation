# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: the Discord bot as a standalone executable.

Requires the 'bot' extra (discord.py + aiohttp) to be installed:

    pip install -e .[bot,build]
    python scripts/build_app.py --bot

See packaging/README.md for full instructions.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "bot" / "discord_bot.py")],
    pathex=[
        str(ROOT),
        str(ROOT / "pipeline"),    # bot imports detect / analyze as top-level
        str(ROOT / "scripts"),
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
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nasa-bot",
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
    name="nasa-bot",
)
