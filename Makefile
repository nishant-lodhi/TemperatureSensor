.PHONY: install install-backend install-dashboard \
       lint lint-dashboard test test-backend test-dashboard \
       run build validate \
       deploy-dev deploy-staging deploy-prod-a deploy-prod-b deploy-prod-c \
       deploy-govcloud-dev deploy-govcloud-prod \
       synth-on synth-off \
       add-client list-clients remove-client rotate-token \
       docker-build docker-run clean

# =============================================================================
#  Install
# =============================================================================

install: install-backend install-dashboard

install-backend:
	pip install -r src/requirements.txt

install-dashboard:
	pip install -r dashboard/requirements.txt

install-dev: install
	pip install -r requirements-dev.txt

# =============================================================================
#  Quality
# =============================================================================

lint: lint-dashboard

lint-dashboard:
	ruff check dashboard/app/ dashboard/tests/

test: test-backend test-dashboard

test-backend:
	python -m pytest tests/ -v --tb=short

test-dashboard:
	cd dashboard && python -m pytest tests/ -v --tb=short

# =============================================================================
#  Local Development
# =============================================================================

run:
	cd dashboard && python -m app.main

# =============================================================================
#  SAM Build & Deploy
# =============================================================================

validate:
	sam validate --template infra/template.yaml --lint

build:
	sam build --template infra/template.yaml

# Standard AWS environments
deploy-dev: build
	sam deploy --config-env dev --config-file infra/samconfig.toml --no-confirm-changeset --no-fail-on-empty-changeset

deploy-staging: build
	sam deploy --config-env staging --config-file infra/samconfig.toml --no-fail-on-empty-changeset

deploy-prod-a: build
	sam deploy --config-env prod-a --config-file infra/samconfig.toml --no-fail-on-empty-changeset

deploy-prod-b: build
	sam deploy --config-env prod-b --config-file infra/samconfig.toml --no-fail-on-empty-changeset

deploy-prod-c: build
	sam deploy --config-env prod-c --config-file infra/samconfig.toml --no-fail-on-empty-changeset

# GovCloud environments
deploy-govcloud-dev: build
	sam deploy --config-env govcloud-dev --config-file infra/samconfig.toml --no-confirm-changeset --no-fail-on-empty-changeset

deploy-govcloud-prod: build
	sam deploy --config-env govcloud-prod --config-file infra/samconfig.toml --no-fail-on-empty-changeset

# =============================================================================
#  Synthetic Mode Toggle (live stack update, no rebuild needed)
# =============================================================================
#  Usage: make synth-on  STACK=TempMonitor-dev
#         make synth-off STACK=TempMonitor-dev

synth-on:
ifndef STACK
	$(error STACK is required — e.g. make synth-on STACK=TempMonitor-dev)
endif
	aws cloudformation update-stack --stack-name $(STACK) --use-previous-template \
		--capabilities CAPABILITY_IAM \
		--parameters ParameterKey=SyntheticMode,ParameterValue=true \
		             ParameterKey=Environment,UsePreviousValue=true \
		             ParameterKey=DeploymentId,UsePreviousValue=true \
		             ParameterKey=ProjectPrefix,UsePreviousValue=true \
		             ParameterKey=EnableIoTRule,UsePreviousValue=true

synth-off:
ifndef STACK
	$(error STACK is required — e.g. make synth-off STACK=TempMonitor-dev)
endif
	aws cloudformation update-stack --stack-name $(STACK) --use-previous-template \
		--capabilities CAPABILITY_IAM \
		--parameters ParameterKey=SyntheticMode,ParameterValue=false \
		             ParameterKey=Environment,UsePreviousValue=true \
		             ParameterKey=DeploymentId,UsePreviousValue=true \
		             ParameterKey=ProjectPrefix,UsePreviousValue=true \
		             ParameterKey=EnableIoTRule,UsePreviousValue=true

# =============================================================================
#  Docker (Dashboard container option)
# =============================================================================

docker-build:
	docker build -f dashboard/infra/Dockerfile -t tempmonitor-dashboard dashboard/

docker-run: docker-build
	docker run -p 8050:8050 tempmonitor-dashboard

# =============================================================================
#  Client Management (multi-tenant)
# =============================================================================
#  Usage:
#    make add-client DEPLOYMENT_ID=dev00sim01 CLIENT_ID=acme CLIENT_NAME="Acme Facility"
#    make list-clients DEPLOYMENT_ID=dev00sim01
#    make remove-client DEPLOYMENT_ID=dev00sim01 CLIENT_ID=acme
#    make rotate-token DEPLOYMENT_ID=dev00sim01 CLIENT_ID=acme

add-client:
ifndef DEPLOYMENT_ID
	$(error DEPLOYMENT_ID is required)
endif
ifndef CLIENT_ID
	$(error CLIENT_ID is required)
endif
	python scripts/manage_client.py add --deployment-id $(DEPLOYMENT_ID) --client-id $(CLIENT_ID) --client-name "$(CLIENT_NAME)"

list-clients:
ifndef DEPLOYMENT_ID
	$(error DEPLOYMENT_ID is required)
endif
	python scripts/manage_client.py list --deployment-id $(DEPLOYMENT_ID)

remove-client:
ifndef DEPLOYMENT_ID
	$(error DEPLOYMENT_ID is required)
endif
ifndef CLIENT_ID
	$(error CLIENT_ID is required)
endif
	python scripts/manage_client.py remove --deployment-id $(DEPLOYMENT_ID) --client-id $(CLIENT_ID)

rotate-token:
ifndef DEPLOYMENT_ID
	$(error DEPLOYMENT_ID is required)
endif
ifndef CLIENT_ID
	$(error CLIENT_ID is required)
endif
	python scripts/manage_client.py rotate --deployment-id $(DEPLOYMENT_ID) --client-id $(CLIENT_ID)

# =============================================================================
#  Housekeeping
# =============================================================================

clean:
	rm -rf .aws-sam/ __pycache__ .pytest_cache .ruff_cache .mypy_cache
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
