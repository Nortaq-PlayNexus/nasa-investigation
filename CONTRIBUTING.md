# Contributing to NASA HiRISE Investigation

Thank you for your interest in contributing to this project. This document provides guidelines for contributing.

## How to Contribute

### Reporting Bugs

1. Check existing issues first
2. Open a new issue using the **Bug Report** template
3. Include: Python version, OS, steps to reproduce, expected vs actual behavior

### Suggesting Features

1. Open an issue using the **Feature Request** template
2. Describe the use case and why it fits the project's EXTRAS-only philosophy

### Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes following the coding standards below
4. Run tests: `python -m pytest tests/test_pipeline.py -v`
5. Run linter: `ruff check pipeline/ scripts/ app/ bot/`
6. Commit with clear messages
7. Open a Pull Request

## Coding Standards

### Python

- **Version:** >= 3.9
- **Line length:** 100 characters (enforced by ruff)
- **Formatter/Linter:** ruff (rules: E, F, W, I, UP, B)
- **Imports:** sorted by ruff (isort-compatible)

### Naming

- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Files: `snake_case.py`

### Testing

- All new features must include tests
- Tests go in `tests/test_pipeline.py` using `unittest.TestCase`
- Run the full suite before submitting:
  ```bash
  python -m pytest tests/test_pipeline.py -v
  ```

### Architecture Principles

- **Flat module layout:** `pipeline/` and `scripts/` have no `__init__.py` (enables PyInstaller single-file EXE)
- **No subprocess calls:** The orchestrator calls functions in-process
- **Graceful degradation:** Optional dependencies (scipy, opencv, discord.py) must not be required
- **EXTRAS-only:** All data acquisition must use sanctioned sources

## Pull Request Checklist

- [ ] Tests pass (`python -m pytest tests/test_pipeline.py`)
- [ ] Linter passes (`ruff check .`)
- [ ] No new hardcoded secrets
- [ ] Documentation updated if needed
- [ ] Commit messages are clear

## Code of Conduct

Be respectful, constructive, and focused on the science.

## Questions?

Open an issue with the **Question** label.
