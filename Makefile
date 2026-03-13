.PHONY: run run-debug test lint sam-validate sam-build validate install install-dev docker-check sam-check

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

sam-check:
	@python3 -c "import sys; v=sys.version_info; exit(1 if v>=(3,13) else 0)" 2>/dev/null \
		&& echo "WARNING: SAM CLI is incompatible with Python 3.13+. Use Python 3.12: python3.12 -m pip install aws-sam-cli" \
		|| true

sam-validate: sam-check
	sam validate --template-file infra/template.yaml --lint

docker-check:
	@docker info > /dev/null 2>&1 || (echo "ERROR: Docker is not running. Start Docker first (needed for --use-container)." && exit 1)
	@echo "Docker OK"

sam-build: sam-check docker-check
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
