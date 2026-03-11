.PHONY: run run-debug test lint

run:
	cd dashboard && gunicorn -w 1 --threads 4 -b 0.0.0.0:8051 app.main:server

run-debug:
	cd dashboard && python -m app.main

test:
	cd dashboard && python -m pytest tests/ -v --tb=short

lint:
	cd dashboard && python -m ruff check app/ tests/
