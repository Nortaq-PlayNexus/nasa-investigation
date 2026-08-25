# Roadmap

## Current Status: v1.0.95 — Production Ready

The core anomaly investigation pipeline is complete and functional. The system acquires, catalogs, enhances, detects, analyzes, and adjudicates anomalies in HiRISE EXTRAS imagery.

## v1.1.0 — Near Term

- [ ] **Overlay detection hardening** — tune polarity scoring to reliably catch all annotated/baked-in text images
- [ ] **Streaming pipeline** — process images as they download instead of batch-only
- [ ] **Confidence calibration** — calibrate detection thresholds against injected blob benchmarks
- [ ] **Report export** — CSV/JSON export from triage and adjudication results

## v1.2.0 — Medium Term

- [ ] **Multi-mission support** — extend beyond HiRISE to LROC NAC, Context Camera (CTX), and Mars Express HRSC
- [ ] **Stereo 3D confirmation** — automated stereo pair matching with height-from-disparity verification
- [ ] **AI second opinion** — optional vision LLM review step (currently experimental)
- [ ] **Performance optimization** — parallel tile processing, memory-mapped large images

## v2.0.0 — Long Term

- [ ] **Cross-platform builds** — Linux and macOS PyInstaller targets
- [ ] **Docker deployment** — containerized full-stack mode
- [ ] **Web dashboard redesign** — interactive map-based anomaly viewer
- [ ] **Community findings database** — shared anomaly catalog with peer review
- [ ] **Automated literature cross-reference** — match anomalies against published papers

## Design Principles

1. **EXTRAS-only** — all data acquisition uses sanctioned sources
2. **Falsifiable** — document and debunk before recording
3. **Reproducible** — deterministic pipeline, audit trail, versioned outputs
4. **Minimal dependencies** — core pipeline works with only numpy + Pillow
5. **Graceful degradation** — optional features work when dependencies are absent
