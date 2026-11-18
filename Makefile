.DEFAULT_GOAL := help

PYTHON       ?= python3
VENV         ?= .venv
BIN          := $(VENV)/bin
PIP          := $(BIN)/pip
PYTEST       := $(BIN)/pytest
RUFF         := $(BIN)/ruff
PACKAGE      := hp_scanner
DIST         := dist
SCANNER_HOST ?= 192.168.4.195
DEV_STAMP    := $(VENV)/.dev-installed
VERSION      := $(shell cat VERSION)

.PHONY: help venv install uninstall dev lint format test coverage test-live status capabilities \
        build wheel sdist check verify-wheel install-wheel clean-build clean distclean all \
        version bump-patch bump-minor bump-major

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(VENV)/bin/activate ## Create the virtual environment

# Where `make install` puts the wheel: INSTALL_VENV=path > an activated venv > per-user site of $(PYTHON).
# UPDATE_PATH=1 also adds (install) / removes (uninstall) hpscan's folder in your shell startup file.
INSTALL_VENV ?=
UPDATE_PATH  ?=
INSTALL_ARGS  = $(if $(INSTALL_VENV),--venv $(INSTALL_VENV)) \
                $(if $(filter 1 yes true,$(UPDATE_PATH)),--update-path)

install: wheel ## Install for your user (pip --user), or INSTALL_VENV=path / active venv; UPDATE_PATH=1 adds to PATH
	$(PYTHON) scripts/install_wheel.py $(INSTALL_ARGS) $(DIST)/*.whl

uninstall: ## Uninstall from where `make install` would put it; UPDATE_PATH=1 also removes the PATH entry
	$(PYTHON) scripts/install_wheel.py --uninstall $(INSTALL_ARGS)

# Re-install when packaging metadata changes (version and dependencies are read at install time).
$(DEV_STAMP): pyproject.toml VERSION requirements.txt requirements-dev.txt | $(VENV)/bin/activate
	$(PIP) install -e ".[dev]"
	@touch $@

dev: $(DEV_STAMP) ## Install the package editable with dev/test dependencies

lint: dev ## Run ruff lint checks
	$(RUFF) check src tests scripts

format: dev ## Auto-format with ruff
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

test: dev ## Run the unit test suite (no scanner needed)
	$(PYTEST)

coverage: dev ## Run tests with a coverage report (fails under 80%)
	$(PYTEST) --cov=hp_scanner --cov-report=term-missing --cov-fail-under=80

test-live: dev ## Smoke-test against the real scanner at SCANNER_HOST
	$(BIN)/hpscan --host $(SCANNER_HOST) status
	$(BIN)/hpscan --host $(SCANNER_HOST) capabilities

status: dev ## Show scanner status
	$(BIN)/hpscan --host $(SCANNER_HOST) status

capabilities: dev ## Show scanner capabilities
	$(BIN)/hpscan --host $(SCANNER_HOST) capabilities

build: dev clean-build ## Build sdist and wheel into dist/
	$(BIN)/python -m build

wheel: dev clean-build ## Build only the wheel into dist/
	$(BIN)/python -m build --wheel

sdist: dev clean-build ## Build only the source distribution into dist/
	$(BIN)/python -m build --sdist

check: build ## Validate built distributions with twine and verify wheel metadata
	$(BIN)/twine check $(DIST)/*
	$(BIN)/python scripts/verify_wheel.py $(DIST)/*.whl

verify-wheel: ## Check dist/*.whl version + Requires-Dist against VERSION and requirements.txt
	$(BIN)/python scripts/verify_wheel.py $(DIST)/*.whl

version: ## Print the current version (from VERSION)
	@echo $(VERSION)

bump-patch: ## Bump VERSION patch (x.y.Z) - commit it yourself or use the Release workflow
	@$(PYTHON) scripts/bump_version.py patch

bump-minor: ## Bump VERSION minor (x.Y.0)
	@$(PYTHON) scripts/bump_version.py minor

bump-major: ## Bump VERSION major (X.0.0)
	@$(PYTHON) scripts/bump_version.py major

install-wheel: wheel ## Install the built wheel into .venv only (replaces the editable dev install)
	$(PIP) install --force-reinstall $(DIST)/*.whl
	@rm -f $(DEV_STAMP)  # so the next `make dev` restores the editable install
	@echo "Installed into $(VENV) only: run $(BIN)/hpscan, or 'make install' for your user"

clean-build:
	rm -rf $(DIST) build src/*.egg-info

clean: clean-build ## Remove build artifacts and caches
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

distclean: clean ## Remove everything including the virtual environment
	rm -rf $(VENV)

all: lint test build check ## Lint, test, build and check
