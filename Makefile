# =============================================================================
# DCOps Copilot — single entry point for common tasks
# =============================================================================
# Usage:
#   make            # show this help
#   make dev        # bring up the dev profile (1 site + data + dashboard)
#   make demo       # bring up the demo profile (all 3 sites)
#   make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
# =============================================================================

# Pick docker compose binary — both `docker compose` (v2) and `docker-compose` (v1)
# are supported. Prefer v2.
COMPOSE := docker compose

# Default profile if none specified.
PROFILE ?= dev

# Default site for inject / per-site commands.
SITE ?= frankfurt

# Default scenario for inject.
SCENARIO ?= gpu_ecc_failure

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@echo "DCOps Copilot — make targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""
	@echo "Vars (override on command line):"
	@echo "  PROFILE   default: dev      one of: data, dev, demo, site-1, site-2, site-3, tools"
	@echo "  SITE      default: frankfurt"
	@echo "  SCENARIO  default: gpu_ecc_failure"

# -----------------------------------------------------------------------------
# Compose lifecycle
# -----------------------------------------------------------------------------
.PHONY: up
up: ## Bring up the data profile only (just the stores)
	$(COMPOSE) --profile data up -d
	@echo "Data services started. Check health: make ps"

.PHONY: dev
dev: ## Bring up the dev profile (data + 1 site + dashboard)
	$(COMPOSE) --profile dev up -d
	@echo ""
	@echo "Dev stack is starting. Once healthy:"
	@echo "  Dashboard:  http://localhost:3000"
	@echo "  API docs:   http://localhost:8080/docs"
	@echo "  Grafana:    http://localhost:3001 (admin/admin)"
	@echo "  Neo4j:      http://localhost:7474"

.PHONY: demo
demo: ## Bring up the demo profile (all 3 sites)
	$(COMPOSE) --profile demo up -d
	@echo ""
	@echo "Demo stack is starting (~8 GB combined). Once healthy:"
	@echo "  Dashboard:  http://localhost:3000"
	@echo "  Inject:     make inject SCENARIO=gpu_ecc_failure SITE=frankfurt"

.PHONY: down
down: ## Stop and remove all containers (keeps volumes)
	$(COMPOSE) --profile demo down

.PHONY: nuke
nuke: ## DESTRUCTIVE: stop everything AND delete all volumes (DB data, MinIO, Chroma)
	@echo "This will delete ALL persistent data. Ctrl-C to abort."
	@sleep 3
	$(COMPOSE) --profile demo down -v

.PHONY: ps
ps: ## Show container status + health
	$(COMPOSE) --profile demo ps

.PHONY: logs
logs: ## Tail logs for all services in the active profile
	$(COMPOSE) --profile $(PROFILE) logs -f --tail=200

.PHONY: logs-agent
logs-agent: ## Tail logs for a single agent (use AGENT=sentinel SITE=frankfurt)
	$(COMPOSE) logs -f $(AGENT)-$(SITE)

.PHONY: restart
restart: ## Restart all containers in the active profile
	$(COMPOSE) --profile $(PROFILE) restart

# -----------------------------------------------------------------------------
# Seed + reset
# -----------------------------------------------------------------------------
.PHONY: seed
seed: ## Seed Neo4j topology + initial telemetry + Chroma past-incidents + Chroma runbooks
	$(COMPOSE) --profile dev run --rm api python scripts/seed_graph.py
	$(COMPOSE) --profile dev run --rm api python scripts/seed_telemetry_sample.py
	$(COMPOSE) --profile dev run --rm api python scripts/seed_incidents.py
	$(COMPOSE) --profile dev run --rm api python scripts/seed_runbooks.py

.PHONY: reset-db
reset-db: ## Reset all databases (DESTRUCTIVE on data)
	bash scripts/reset_db.sh

.PHONY: download-backblaze
download-backblaze: ## Download Backblaze SMART dataset for Sentinel training
	bash scripts/download_backblaze.sh

# -----------------------------------------------------------------------------
# Failure injection (live demo)
# -----------------------------------------------------------------------------
.PHONY: inject
inject: ## Inject a failure scenario: make inject SCENARIO=gpu_ecc_failure SITE=frankfurt
	$(COMPOSE) --profile dev run --rm api \
		python scripts/inject_failure.py --scenario $(SCENARIO) --site $(SITE)

.PHONY: list-scenarios
list-scenarios: ## List available failure scenarios
	@ls -1 benchmarks/scenarios/*.yml | xargs -n1 basename | sed 's/\.yml$$//'

# -----------------------------------------------------------------------------
# Tests + benchmarks
# -----------------------------------------------------------------------------
.PHONY: test
test: ## Run pytest (unit tests only by default)
	uv run pytest -m "not slow and not integration"

.PHONY: test-integration
test-integration: ## Run integration tests (requires dev profile up)
	uv run pytest -m "integration"

.PHONY: test-all
test-all: ## Run all tests including slow ones
	uv run pytest

.PHONY: bench
bench: ## Run the full 200-scenario benchmark suite
	uv run python -m benchmarks.runner --output case_study/benchmark_results.json
	uv run python -m benchmarks.report --input case_study/benchmark_results.json \
		--output case_study/benchmark_report.html

# -----------------------------------------------------------------------------
# Lint / format
# -----------------------------------------------------------------------------
.PHONY: lint
lint: ## Run ruff + mypy on Python; eslint on TS
	uv run ruff check apps tests scripts benchmarks
	uv run mypy apps
	cd apps/dashboard && npm run lint

.PHONY: format
format: ## Auto-format Python (ruff + black) and TS (prettier)
	uv run ruff check --fix apps tests scripts benchmarks
	uv run black apps tests scripts benchmarks
	cd apps/dashboard && npm run format

# -----------------------------------------------------------------------------
# Install / setup
# -----------------------------------------------------------------------------
.PHONY: install
install: ## Install Python deps via uv + frontend deps via npm
	uv sync --dev
	cd apps/dashboard && npm install
	uv run pre-commit install

.PHONY: clean
clean: ## Remove caches, build artifacts (keeps containers & data)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	rm -rf .coverage_html .coverage
	rm -rf apps/dashboard/.next apps/dashboard/out

# -----------------------------------------------------------------------------
# Convenience
# -----------------------------------------------------------------------------
.PHONY: shell-api
shell-api: ## Open a shell in the API container
	$(COMPOSE) exec api bash

.PHONY: shell-redis
shell-redis: ## Open redis-cli
	$(COMPOSE) exec redis redis-cli

.PHONY: shell-neo4j
shell-neo4j: ## Open Neo4j cypher-shell
	$(COMPOSE) exec neo4j cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-changeme_neo4j}

.PHONY: shell-timescale
shell-timescale: ## Open psql against TimescaleDB
	$(COMPOSE) exec timescaledb psql -U $${TIMESCALE_USER:-dcops} -d $${TIMESCALE_DB:-dcops}
