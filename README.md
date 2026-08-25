<div align="center">

# 🔬 NASA HiRISE Investigation

**Exclusive Anomaly Detection Pipeline for Mars & Lunar Imagery**

*Acquire → Catalog → Enhance → Detect → Analyze → Adjudicate*

[![CI](https://github.com/Nortaq-PlayNexus/nasa-investigation/actions/workflows/ci.yml/badge.svg)](https://github.com/Nortaq-PlayNexus/nasa-investigation/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-69%20passing-brightgreen)]()

</div>

---

## What Is This?

A rigorous, reproducible pipeline for analyzing **public NASA HiRISE PDS imagery** to surface candidate anomalies for structured human review. Built on the principle that nearly all "anomalies" in planetary imagery are known sensor/compression/viewing artifacts — the system is designed to **document, control, and debunk** before anything is ever recorded as a finding.

**Key design principle:** EXTRAS-only data acquisition from a single sanctioned source (`https://hirise-pds.lpl.arizona.edu/PDS/EXTRAS/`), comparing complete variant sets (B&W ↔ filtered ↔ ortho ↔ DTM) pixel-for-pixel to separate terrain from processing artifacts.

---

## Screenshots

<p align="center">
  <img src="assets/screenshots/report_top.png" width="80%" alt="Anomaly Analysis Report">
</p>

<p align="center">
  <em>Generated HTML report showing pipeline statistics, detection summary, and adjudicated leads</em>
</p>

---

## Features

- 🔍 **Multi-scale anomaly detection** — local-contrast flagging with box and annulus methods
- 🎯 **Cross-band confirmation** — pixel-level verification across B&W, filtered, and orthorectified variants
- 📊 **Statistical rigor** — Benjamini-Hochberg FDR control, negative-control baselines, stress testing
- 🛡️ **Artifact debunking** — systematic checklist against known sensor, compression, and optics artifacts
- 🗺️ **Native PDS ingestion** — reads `.IMG` EDRs directly with PDS3/PDS4 label parsing
- 📐 **3D stereo confirmation** — block-matching disparity maps with height estimation
- 🌗 **Solar geometry scoring** — shadow direction vs. solar azimuth alignment
- 🧪 **Benchmark calibration** — injected-blob sensitivity measurement with recall curves
- 📱 **Full-stack dashboard** — drag-drop analysis, live stats, searchable leads table
- 🤖 **Discord bot** — upload an image, get a pipeline verdict
- 📦 **Standalone EXE** — PyInstaller single-file builds, no installation required

---

## Technology Stack

```
Core Pipeline     Python 3.9+ / NumPy / Pillow
Image Analysis    SciPy (optional) / OpenCV (optional)
Web Dashboard     FastAPI + Uvicorn / Vanilla HTML/CSS/JS
Discord Bot       discord.py 2.x
Build System      PyInstaller / pip / pyproject.toml
Testing           unittest + pytest (69+ test cases)
Linting           ruff (100 char line length)
CI/CD             GitHub Actions (Linux + Windows, Python 3.9/3.11/3.12)
```

---

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│  Download    │───▶│   Catalog    │───▶│   Verify     │
│  (EXTRAS)    │    │  + Hash      │    │  Integrity   │
└─────────────┘    └──────────────┘    └──────────────┘
                                                │
┌─────────────┐    ┌──────────────┐    ┌────────▼──────┐
│   Detect    │◀───│   Enhance    │◀───│  Native PDS   │
│  Flagging   │    │  Stretch     │    │  Reader       │
└──────┬──────┘    └──────────────┘    └───────────────┘
       │
┌──────▼──────┐    ┌──────────────┐    ┌──────────────┐
│   Analyze   │───▶│  Adjudicate  │───▶│  Conclusions │
│  Measure    │    │  Cross-band  │    │  Leads       │
└─────────────┘    └──────────────┘    └──────────────┘
```

---

## Installation

### From Source

```bash
git clone https://github.com/Nortaq-PlayNexus/nasa-investigation.git
cd nasa-investigation
pip install -r requirements.txt
```

### Development

```bash
pip install -e .[dev]
python -m pytest tests/test_pipeline.py -v
```

### Standalone EXE

```bash
pip install -e .[dev]
python scripts/build_app.py              # Pipeline CLI
python scripts/build_app.py --fullstack  # Full dashboard + pipeline
```

---

## Quick Start

### Full Pipeline

```bash
python scripts/run_pipeline.py --query "moon" --max 50
```

### Individual Steps

```bash
# 1. Download EXTRAS imagery
python scripts/download_hirise_extras.py --query "crater" --max 30 --out data/raw

# 2. Build catalog with solar geometry
python scripts/build_catalog.py

# 3. Verify integrity
python scripts/verify_downloads.py

# 4. Enhance images
python pipeline/enhance.py --dir data/raw --out data/processed

# 5. Detect anomalies
python pipeline/detect.py --dir data/processed --out data/anomalies

# 6. Mark candidates
python pipeline/mark.py --candidates data/anomalies/candidates.csv --out data/anomalies/marked

# 7. Analyze candidates
python pipeline/analyze.py --candidates data/anomalies/candidates.csv --out data/anomalies/analysis

# 8. Adjudicate leads
python pipeline/adjudicate.py --candidates data/anomalies/candidates.csv \
    --evaluated data/anomalies/analysis/evaluated.csv \
    --out data/anomalies/conclusions
```

### Self-Test

```bash
python scripts/run_pipeline.py --selftest
```

---

## Configuration

| File | Purpose |
|------|---------|
| `config/pipeline.json` | Detector thresholds, adjudication gates, benchmark parameters |
| `config/sources.yaml` | EXTRAS-only source policy, variant taxonomy |
| `.env` | API tokens (Discord, LLM) — never commit |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | No | Discord bot token |
| `AI_LLM_KEY` | No | OpenRouter API key for vision LLM analysis |
| `AI_LLM_ENDPOINT` | No | LLM API endpoint (default: OpenRouter) |
| `AI_LLM_MODEL` | No | Vision model (default: llama-3.2-90b-vision) |

---

## Usage

### Full-Stack Dashboard

```bash
python scripts/build_app.py --fullstack
dist/nasa-fullstack/nasa-fullstack.exe
# Opens http://127.0.0.1:8000
```

Features: drag-drop instant analysis, live stats, searchable leads table, pipeline controls, showcase gallery.

### Discord Bot

```bash
pip install -r requirements-extras.txt
$env:DISCORD_TOKEN = "<your-token>"
python bot/discord_bot.py
```

Upload a Moon/Mars image → pipeline verdict with marked-up image and plain-language assessment.

### 3D Stereo Confirmation

```bash
python scripts/check_stereo.py --left pair_a.png --right pair_b.png \
    --candidates data/anomalies/candidates.csv --box 0 \
    --altitude-km 300 --baseline-km 1.2 --out data/anomalies/stereo
```

---

## Output Files

| File | Description |
|------|-------------|
| `data/catalog/catalog.csv` | Every file with mission, dimensions, SHA-256, solar geometry |
| `data/anomalies/candidates.csv` | Detected regions (x, y, w, h, fill, score) |
| `data/anomalies/marked/` | Images with anomaly boxes drawn |
| `data/anomalies/analysis/` | Enhanced crops, measurements, artifact verdicts, HTML report |
| `data/anomalies/conclusions/adjudicated.csv` | Cross-band confirmed leads with verdicts |
| `data/anomalies/audit.jsonl` | Machine-readable audit trail of every run |
| `findings/` | Only conclusions that survived the full methodology |

---

## Pipeline Modules

| Module | Purpose |
|--------|---------|
| `pipeline/common.py` | Hardened infrastructure: audit, hashing, atomic writes, stats |
| `pipeline/pds.py` | Native PDS3/PDS4 + `.IMG` EDR reader |
| `pipeline/overlay.py` | Text/annotation overlay detection |
| `pipeline/detect.py` | Multi-scale local-contrast anomaly flagging |
| `pipeline/analyze.py` | Enhance, measure, artifact-check, rank |
| `pipeline/adjudicate.py` | Cross-band confirmation, persistence, verdicts |
| `pipeline/stereo.py` | Block-matching disparity, height estimation |
| `pipeline/changedet.py` | Phase-correlation registration + change maps |
| `pipeline/benchmark.py` | Injected-blob calibration + negative controls |
| `pipeline/extras_compare.py` | B&W vs filtered vs ortho vs DTM comparator |

---

## Testing

```bash
# Run full test suite
python -m pytest tests/test_pipeline.py -v

# Run specific test class
python -m pytest tests/test_pipeline.py::TestDetect -v

# Run via pipeline selftest
python scripts/run_pipeline.py --selftest
```

**69+ test cases** covering: overlay detection, border exclusion, z-score p-values, Benjamini-Hochberg FDR, input validation, atomic writes, SHA-256 hashing, detector recall, blob injection, adjudication persistence/verdict/roundness, multi-band PDS cubes, stereo/change-detection, artifact flags, and rigor metrics.

---

## Security

- **No hardcoded secrets** — all tokens loaded from environment variables
- **Path traversal protection** — `common.contain_path()` validates all file paths
- **Atomic writes** — crash-safe file operations with fsync + rename
- **Audit trail** — every pipeline operation recorded in `audit.jsonl`
- **Localhost only** — server binds to `127.0.0.1:8000` by default

See [SECURITY.md](SECURITY.md) for the full security policy.

---

## Roadmap

- [ ] Overlay detection hardening
- [ ] Streaming pipeline (process during download)
- [ ] Confidence calibration against benchmarks
- [ ] Multi-mission support (LROC NAC, CTX, Mars Express HRSC)
- [ ] Automated stereo pair matching
- [ ] Cross-platform builds (Linux, macOS)
- [ ] Docker deployment
- [ ] Interactive map-based anomaly viewer

See [ROADMAP.md](ROADMAP.md) for the full roadmap.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Run tests: `python -m pytest tests/test_pipeline.py -v`
4. Run linter: `ruff check pipeline/ scripts/ app/ bot/`
5. Submit a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- **NASA/JPL** — HiRISE PDS data (public domain)
- **University of Arizona LPL** — HiRISE processing pipeline
- **Python community** — NumPy, Pillow, SciPy, FastAPI

---

<div align="center">

**Built for rigorous planetary anomaly investigation**

*Document → Control → Debunk → Confirm*

</div>
