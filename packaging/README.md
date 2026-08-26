# Building standalone executables

This folder contains everything needed to turn the Python pipeline and the
Discord bot into standalone Windows `.exe` programs. The build is driven by
`scripts/build_app.py`, which **runs the full unit-test suite first** and only
packages if every test passes — so a broken build fails loudly instead of
producing a junk binary.

## Prerequisites (once)

```bash
python -m venv .venv                 # optional but recommended
.venv/Scripts/activate               # Windows
pip install -e .[dev]                # numpy, Pillow, pytest, ruff
```

## Build the full-stack EXE (recommended)

```bash
pip install -e .[dev]               # core + dev tools
pip install fastapi uvicorn pyinstaller  # for fullstack build
python scripts/build_app.py --fullstack     # -> dist/nasa-fullstack/
python scripts/build_app.py --fullstack --onefile  # single-file  -> dist/nasa-fullstack.exe
```

Double-click `nasa-fullstack.exe` — it starts the server and opens `http://127.0.0.1:8000`:

- **Dashboard** at `/` (upload & instant analyze, live stats, pipeline controls)
- **Legacy showcase** at `/showcase/`
- **API docs** at `/docs` (FastAPI Swagger)
- Health at `/api/health`, stats at `/api/stats`, analyze at `POST /api/analyze`

```bash
dist/nasa-fullstack/nasa-fullstack.exe              # opens browser
dist/nasa-fullstack/nasa-fullstack.exe --port 3000 --no-browser
dist/nasa-fullstack/nasa-fullstack.exe --cli --from detect --to adjudicate  # CLI delegate
dist/nasa-fullstack/nasa-fullstack.exe --cli --selftest
```

Data lives next to the EXE in `data/` (portable). The showcase is rebuilt
automatically if `showcase/index.html` is missing.

## Build the pipeline CLI exe

```bash
python scripts/build_app.py                 # tests -> PyInstaller -> dist/nasa-pipeline/
python scripts/build_app.py --onefile       # single-file exe variant
python scripts/build_app.py --no-test       # skip the test gate (not recommended)
```

The result is written to `dist/nasa-pipeline/` (or `dist/nasa-pipeline.exe` with
`--onefile`). You can run it exactly like the sources:

```bash
dist/nasa-pipeline/nasa-pipeline.exe --from detect --to adjudicate
dist/nasa-pipeline/nasa-pipeline.exe --selftest
```

## Build the Discord bot exe

```bash
pip install -e .[dev]
pip install discord.py aiohttp
python scripts/build_app.py --bot
```

Run it with `DISCORD_TOKEN` set in the environment (the bot needs its token at
runtime, so it is never baked into the binary):

```bash
set DISCORD_TOKEN=your-token-here
dist/nasa-bot/nasa-bot.exe
```

## How it works

- `run_pipeline` now orchestrates every step **in-process** (no more `sys.executable`
  subprocess re-launches), which is exactly what makes a single frozen exe possible.
- `pipeline/` and `scripts/` are flat modules imported as top-level names (`import common`,
  `import detect`, …). The specs add `pipeline/` and `scripts/` to PyInstaller's `pathex`
  so those imports resolve during the freeze.
- `config/pipeline.json` and `config/sources.yaml` are bundled as data and resolved via
  `common.PROJECT_ROOT` (the bundle root at runtime).
- The Discord spec additionally does not run on import — pass it a token via env.

## Troubleshooting

- **`PyInstaller not installed`** — run `pip install -e .[dev]`.
- **Tests fail and the build aborts** — that is intended. Fix the failures first.
- **A feature needs an optional dependency at runtime** (scipy/opencv/imagecodecs) —
  install it in the active environment *before* building so PyInstaller bundles it.
