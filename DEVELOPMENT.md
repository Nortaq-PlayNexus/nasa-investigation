# Development

## Setting Up

```bash
git clone https://github.com/Nortaq-PlayNexus/nasa-investigation.git
cd nasa-investigation
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -e .[dev]
```

## Running Tests

```bash
# Full suite
python -m pytest tests/test_pipeline.py -v

# Specific test class
python -m pytest tests/test_pipeline.py::TestDetect -v

# Via pipeline selftest
python scripts/run_pipeline.py --selftest
```

## Linting

```bash
ruff check scripts/ tests/ pipeline/ bot/ app/
```

## Project Structure

```
pipeline/           Core analysis modules (flat, no __init__.py)
scripts/            Pipeline orchestration and utilities
app/                Full-stack dashboard (FastAPI + HTML)
bot/                Discord bot integration
tests/              Unit tests (unittest + pytest)
config/             Pipeline configuration (JSON + YAML)
docs/               Documentation
data/               Working data (gitignored)
packaging/          PyInstaller build specs
assets/             Screenshots, branding, diagrams
```

## Code Style

- **Line length:** 100 characters
- **Formatter/Linter:** ruff
- **Naming:** snake_case (functions/variables), PascalCase (classes)
- **Imports:** sorted by ruff (isort-compatible)

## Architecture Principles

1. **Flat modules** — no `__init__.py` in `pipeline/` or `scripts/`
2. **In-process calls** — no subprocess in orchestrator (EXE-compatible)
3. **Graceful degradation** — optional deps work when absent
4. **Config-driven** — thresholds in `config/pipeline.json`
5. **Audit trail** — every operation recorded in `audit.jsonl`

## Adding a Pipeline Step

1. Create `pipeline/your_step.py`
2. Implement `def run(...)` function
3. Add CLI entry point with `argparse`
4. Wire into `scripts/run_pipeline.py`
5. Add tests in `tests/test_pipeline.py`
6. Update `config/pipeline.json` if needed

## Debugging

```bash
# Run with verbose output
python scripts/run_pipeline.py --query "crater" --verbose

# Run specific steps only
python scripts/run_pipeline.py --from detect --to adjudicate

# Check audit trail
cat data/anomalies/audit.jsonl | python -m json.tool
```
