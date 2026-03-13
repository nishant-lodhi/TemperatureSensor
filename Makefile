.PHONY: run run-debug test lint sam-validate sam-build validate install install-dev docker-check

# ── Run ───────────────────────────────────────────────────────────────────────
run:
	cd dashboard && gunicorn -w 1 --threads 4 -b 0.0.0.0:8051 app.main:server

run-debug:
	cd dashboard && python -m app.main

# ── Quality checks (individual) ──────────────────────────────────────────────
lint:
	cd dashboard && python -m ruff check app/ tests/

test:
	cd dashboard && python -m pytest tests/ -v --tb=short

sam-validate:
	sam validate --template-file infra/template.yaml --lint

docker-check:
	@docker info > /dev/null 2>&1 || (echo "ERROR: Docker is not running. Start Docker first (needed for --use-container)." && exit 1)
	@echo "Docker OK"

sam-build: docker-check
	sam build --template-file infra/template.yaml --use-container

# ── All checks in one shot (run before every push) ───────────────────────────
validate: lint test sam-validate sam-build
	@echo ""
	@echo "✅ All checks passed — safe to push."

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	cd dashboard && pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt
