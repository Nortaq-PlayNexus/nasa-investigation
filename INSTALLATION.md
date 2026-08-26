# Installation

## Requirements

- **Python:** 3.10 or higher
- **OS:** Windows, Linux, or macOS
- **Disk:** ~100 MB for code, variable for data

## From Source

```bash
git clone https://github.com/Nortaq-PlayNexus/nasa-investigation.git
cd nasa-investigation
pip install -r requirements.txt
```

## Development Install

```bash
pip install -e .[dev]
```

This installs:
- Core dependencies (numpy, Pillow)
- Dev tools (pytest, ruff)

## Optional Dependencies

### Deep Analysis (SciPy, OpenCV)

```bash
pip install -r requirements-extras.txt
```

Provides:
- Advanced photometry (scipy)
- Feature matching / registration (opencv)
- JPEG2000 browse product support (imagecodecs)

### Full-Stack Dashboard

```bash
pip install fastapi uvicorn
```

Provides:
- FastAPI web server
- Dashboard UI

### Discord Bot

```bash
pip install discord.py aiohttp
```

## Standalone EXE

No Python installation required:

```bash
pip install -e .[dev]
python scripts/build_app.py --fullstack
# Output: dist/nasa-fullstack/nasa-fullstack.exe
```

See [packaging/README.md](../packaging/README.md) for build details.

## Verify Installation

```bash
python scripts/run_pipeline.py --selftest
```

This runs the full test suite (88 cases) to verify everything works.
