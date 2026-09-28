# Makefile for the writing-habit Python package.
# Run `make` or `make help` to list targets.

PYTHON ?= python3
PIP    := $(PYTHON) -m pip
PKG    := writing_habit

# The package uses a src layout, so an uninstalled checkout still imports.
PYTHONPATH ?= src
export PYTHONPATH

# Qt needs no display for the test suite, and the offscreen platform plugin
# keeps `make test` usable over ssh and in continuous integration.
QT_QPA_PLATFORM ?= offscreen
export QT_QPA_PLATFORM

# Overridable inputs for the demo target.
DB    ?= habit.db
TABLE ?= examples/my-week.org
WEEK  ?= 2026-01-19
OUT   ?= out

.DEFAULT_GOAL := help

.PHONY: help install dev gui test coverage lint docs build check \
        publish publish-test demo clean distclean

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

install: ## Install the package
	$(PIP) install .

dev: ## Install editable with the developer extras and the graphical extra
	$(PIP) install -e ".[dev,gui]"

gui: ## Install editable with the graphical extra (PyQt5, GPL)
	$(PIP) install -e ".[gui,dev]"

test: ## Run the test suite headless
	$(PYTHON) -m pytest -q

coverage: ## Run the tests with a coverage report (needs pytest-cov)
	@$(PYTHON) -c "import pytest_cov" 2>/dev/null || $(PIP) install pytest-cov
	$(PYTHON) -m pytest --cov=$(PKG) --cov-report=term-missing

lint: ## Lint with ruff when it is installed
	@command -v ruff >/dev/null 2>&1 \
	  && ruff check src tests \
	  || echo "ruff not installed; skipping (pip install ruff)"

docs: ## Build the Sphinx site into docs/_build/html
	$(MAKE) -C docs html

build: ## Build the sdist and wheel into dist/
	@$(PYTHON) -c "import build" 2>/dev/null || $(PIP) install build
	$(PYTHON) -m build

check: build ## Validate the built distributions with twine
	@$(PYTHON) -c "import twine" 2>/dev/null || $(PIP) install twine
	$(PYTHON) -m twine check dist/*

publish-test: check ## Upload to TestPyPI
	$(PYTHON) -m twine upload --repository testpypi dist/*

publish: check ## Upload to PyPI
	$(PYTHON) -m twine upload dist/*

demo: ## Run the weekly loop on the example files into $(OUT)/
	mkdir -p $(OUT)
	$(PYTHON) -m writing_habit.cli initdb --db $(OUT)/$(DB)
	$(PYTHON) -m writing_habit.cli plan import $(TABLE) --week $(WEEK) --db $(OUT)/$(DB)
	$(PYTHON) -m writing_habit.cli track import examples/actuals.csv --db $(OUT)/$(DB)
	$(PYTHON) -m writing_habit.cli compare --week $(WEEK) --db $(OUT)/$(DB)
	$(PYTHON) -m writing_habit.cli dashboard --week $(WEEK) --out $(OUT)/week.html --db $(OUT)/$(DB)
	@echo "Wrote outputs to $(OUT)/"

clean: ## Remove caches, build artifacts, and demo output
	rm -rf build dist src/*.egg-info $(OUT)
	rm -rf .pytest_cache .coverage htmlcov .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete

distclean: clean ## Alias for clean
	@true
