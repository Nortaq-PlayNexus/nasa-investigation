# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.95] - 2026-08-25

### Added
- **Text overlay detection** module (`pipeline/overlay.py`) — detects baked-in annotations, legends, and text overlays in imagery using high-pass stroke isolation, connected-component analysis, and polarity-consistent scoring
- **Border exclusion** — `--border-frac` flag in detect.py drops candidates touching image edges (default 4% band)
- **Edge contrast floor** — `EDGE_CONTRAST_FLOOR=5.0` in analyze.py drops edge-touching candidates with low contrast
- **8 new unit tests** for overlay detection and border exclusion behavior
- **Pipeline orchestrator** with `--from X --to Y` step-level control

### Fixed
- **Bounding box scaling** in `make_strip()` — crop coordinates now correctly scale when tiles are resized to 256px height
- **Double audio** in RustVoiceBooster — native WASAPI stream is now the sole live path; WebAudio `setSinkId` is fallback-only
- **Version mismatch** — app package version aligned with pyproject.toml (1.0.95)

### Changed
- Detection pipeline now uses multi-pass scoring with overlay filtering before candidate ranking

## [1.0.0] - 2026-01-01

### Added
- Initial release
- HiRISE EXTRAS-only data acquisition
- Full pipeline: download → catalog → verify → enhance → detect → mark → analyze → triage → benchmark → adjudicate
- Native PDS3/PDS4 image reader
- Stereo disparity analysis
- Change detection via phase correlation
- Sigma-clipped stacking and destriping
- Full-stack dashboard (FastAPI + vanilla HTML/JS)
- Discord bot integration
- Standalone EXE packaging via PyInstaller
- Comprehensive test suite (69+ cases)
