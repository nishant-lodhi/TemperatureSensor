.PHONY: run run-debug lint test sam-validate sam-build validate install install-dev

SAM := $(shell command -v sam 2>/dev/null)

run:
	cd dashboard && gunicorn -w 1 --threads 4 -b 0.0.0.0:8051 app.main:server

run-debug:
	cd dashboard && python -m app.main

lint:
	cd dashboard && python -m ruff check app/ tests/

test:
	cd dashboard && python -m pytest tests/ -v --tb=short

sam-validate:
ifndef SAM
	$(error sam CLI not found — install via https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
endif
	$(SAM) validate --template-file infra/template.yaml --region us-east-1

sam-build:
ifndef SAM
	$(error sam CLI not found — install via https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
endif
	@docker info > /dev/null 2>&1 || (echo "Error: Docker daemon is not running — required for container image build" && exit 1)
	$(SAM) build --template-file infra/template.yaml

validate: lint test sam-validate sam-build
	@echo "\n✅ All checks passed — safe to push."

install:
	cd dashboard && pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt
