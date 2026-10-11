# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [UNRELEASED] — v2.0 Upgrade

### Added
- **AI Intelligence Layer** (`pipeline/intelligence.py`)
  - Natural language query engine — ask "bright features on Mars" or "high contrast craters" and get filtered results with criteria breakdown
  - Smart anomaly categorization (crater, boulder, albedo, linear, artifact, irregular) based on flags, aspect ratio, compactness
  - AI-generated plain-language summaries of anomaly datasets
  - Actionable insights engine (top leads, cross-band patterns, artifact rates, rare types)
  - Vision LLM integration for per-anomaly reasoning (uses existing OpenRouter config from pipeline.json)
  - Full query pipeline: parse → filter → categorize → summarize → insight
- **Enhanced Showcase Gallery v2** (`showcase/template.html`)
  - Masonry grid layout with responsive breakpoints
  - Interactive lightbox viewer with keyboard navigation (←/→/Esc) and info panel
  - AI Query Engine widget with real-time API integration
  - Smart insights cards with priority indicators
  - Category filter bar with live counts
  - Glassmorphism design with backdrop blur effects
  - Animated transitions, hover effects, gradient accents
  - Scroll-triggered visibility and smooth page transitions
  - Enhanced card metadata with category tags, band strip colors
  - Touch-friendly responsive design (3→2→1 column breakpoints)
- **New API Endpoints** in `app/server.py`:
  - `GET /api/intelligence/query?q=...` — natural language query → features + summary + insights
  - `GET /api/intelligence/summary` — AI-generated dataset summary
  - `GET /api/intelligence/insights` — smart actionable insights
  - `POST /api/intelligence/analyze` — vision LLM analysis per feature
  - `GET /api/intelligence/status` — AI feature availability check
- **Keyboard shortcuts**: `/` to focus search, `Esc` to close lightbox, `←/→` to navigate
- ARIA labels for accessibility
- `UPGRADE.md` — full upgrade plan and implementation roadmap

### Changed
- `scripts/build_showcase.py` — now loads template from `showcase/template.html` (external) with inline fallback
- Enhanced dark sci-fi theme across gallery with CSS variables, transitions, glow effects

### Fixed
- None

### Removed
- None

---

## [1.4.50] - 2026-08-26

### Fixed
- **32 ruff lint errors** across scripts/ and tests/ (E702, E731, E402, F811, F841)
- **Dead dependency cleanup** — removed unused `requests`, moved `playwright` to optional
- **Doc drift** — corrected Python version (3.9→3.10), test counts (69→88), removed nonexistent extras references
- **CI hardening** — removed `|| true` from ruff check, added Python 3.13 to matrix

## [1.0.95] - 2026-08-25

### Added
- **Text overlay detection** module (`pipeline/overlay.py`)
- **Border exclusion** — `--border-frac` flag in detect.py
- **Edge contrast floor** — `EDGE_CONTRAST_FLOOR=5.0` in analyze.py
- **8 new unit tests** for overlay detection and border exclusion
- **Pipeline orchestrator** with `--from X --to Y` step-level control

### Fixed
- **Bounding box scaling** in `make_strip()`
- **Version mismatch** — app package version aligned with pyproject.toml

### Changed
- Detection pipeline now uses multi-pass scoring with overlay filtering
