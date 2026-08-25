.PHONY: test selftest build validate audit stats

test:
	python -m pytest tests/ -q -p no:cacheprovider

selftest:
	python scripts/build_site.py --selftest

build:
	python scripts/build_site.py

validate:
	python scripts/validate_conclusions.py --strict

audit:
	python scripts/audit_strips.py

stats:
	python scripts/report_stats.py
