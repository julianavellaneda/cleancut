# Shorthand for the commands in README.md and CONTRIBUTING.md. Thin wrappers
# only: tool flags live in backend/pyproject.toml and CI's thresholds live in
# .github/workflows/ci.yml. If a target here starts deciding something - a
# floor, a flag, a path - it has become a second definition of CI, and the
# first one of the two to change leaves the other lying. CONTRIBUTING.md keeps
# the explicit commands alongside, because that file mirrors CI literally.
#
# Written for GNU make 3.81, the one macOS ships: no .ONESHELL, so every recipe
# line is its own shell and changes directory for itself.

# The backend's tools, relative to backend/. Override to use an environment
# that is already active: `make test BIN=`.
BIN ?= .venv/bin/

# The uv CI pins. A different uv formats the lock header differently and fails
# the drift check on an otherwise correct commit; backend/tests/test_makefile.py
# fails if this and ci.yml disagree.
UV_VERSION := 0.12.10

SUITE ?= claims-and-scrub
DEMO := ../tests/fixtures/demo

.DEFAULT_GOAL := help
.PHONY: help install dev test lint eval eval-live lock docker

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

install: ## Backend venv from the dev lock, and npm ci
	cd backend && test -d .venv || python3 -m venv .venv
	cd backend && $(BIN)pip install --require-hashes -r requirements-dev.txt
	cd frontend && npm ci

dev: ## Backend and frontend together (start.sh)
	./start.sh

test: ## pytest and vitest
	cd backend && $(BIN)pytest
	cd frontend && npm test

lint: ## Format check, lint and types, backend then frontend
	cd backend && $(BIN)ruff format --check app tests conftest.py
	cd backend && $(BIN)ruff check app tests conftest.py
	cd backend && $(BIN)mypy
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit

eval: ## The two free evals: recorded run, then the detectors (scorecards, no floors)
	cd backend && $(BIN)python -m app.eval.run $(DEMO)/seed_job.json
	cd backend && $(BIN)python -m app.eval.run --detectors $(DEMO)/demo_seminar.mp3 --suite scrub

eval-live: ## The whole pipeline on the demo clip - transcribes and calls CLEANCUT_MODEL
	cd backend && $(BIN)python -m app.eval.run --live $(DEMO)/demo_seminar.mp3 --suite $(SUITE)

lock: ## Re-compile both dependency locks with the uv CI pins
	cd backend && uvx --from uv==$(UV_VERSION) uv pip compile requirements.in --universal --python-version 3.10 --generate-hashes --output-file requirements.txt --quiet
	cd backend && uvx --from uv==$(UV_VERSION) uv pip compile requirements-dev.in --universal --python-version 3.10 --generate-hashes --output-file requirements-dev.txt --quiet

docker: ## docker compose up --build
	docker compose up --build
