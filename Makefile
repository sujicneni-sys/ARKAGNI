# Arkagni reproducible entry points.
#
# On Windows the virtualenv interpreter is at .venv/Scripts/python.exe:
#   make PYTHON=.venv/Scripts/python.exe test
# On Linux/macOS the default `python` (or a uv-managed environment) is used.

SHELL := /bin/sh
PYTHON ?= python
NPM ?= npm
UV ?= uv
COMPOSE ?= docker compose

.PHONY: help install frontend-install build test verify reproduce run-local dev dev-api docker-up docker-down docker-logs docker-batch clean

help:
	@echo "Arkagni targets"
	@echo "  install          sync the Python environment with uv"
	@echo "  frontend-install install dashboard dependencies (npm ci)"
	@echo "  build            type-check and build the dashboard"
	@echo "  test             run the full pytest suite"
	@echo "  verify           verify frozen artifact, config, and core parity hashes"
	@echo "  reproduce        regenerate L2-L5 outputs and verify the release"
	@echo "  run-local        build the dashboard and serve API + SPA on :8000"
	@echo "  dev              build the dashboard and serve Arkagni on :8000"
	@echo "  dev-api          run the API with reload on :8000"
	@echo "  docker-up        build and start the single Arkagni server (:8000)"
	@echo "  docker-batch     run the reproducible batch profile"
	@echo "  docker-down      stop the compose stack"
	@echo "  clean            remove caches and built frontend assets"

install:
	$(UV) sync

frontend-install:
	$(NPM) --prefix frontend ci

build: frontend-install
	$(NPM) --prefix frontend run build

test:
	$(PYTHON) -m pytest

verify:
	$(PYTHON) scripts/04_verify_release.py

reproduce:
	$(PYTHON) scripts/03_run_analysis.py --force
	$(PYTHON) scripts/04_verify_release.py
	$(PYTHON) -m pytest

run-local: build
	$(PYTHON) -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

dev:
	$(PYTHON) scripts/run_local.py

dev-api:
	$(PYTHON) -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

docker-up:
	$(COMPOSE) up --build -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=200

docker-batch:
	$(COMPOSE) --profile batch run --rm --build batch

clean:
	rm -rf frontend/dist frontend/node_modules .pytest_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
