# Shortcuts. Type `make` on its own to see them.
# The point of a Makefile on a small project is not automation, it is memory:
# six months from now you will not remember the coverage flags.

.DEFAULT_GOAL := help

.PHONY: help setup test cov lint fmt scan live clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the venv and install everything
	uv venv
	. .venv/bin/activate && uv pip install -e ".[dev]"

test:  ## Run the test suite
	pytest

cov:  ## Run tests with a coverage report
	pytest --cov=stocksignal --cov-report=term-missing

lint:  ## Check formatting and lint rules
	ruff check src tests
	ruff format --check src tests

fmt:  ## Fix what can be fixed automatically
	ruff check --fix src tests
	ruff format src tests

scan:  ## Offline scan of the default watchlist
	PYTHONPATH=src python -m stocksignal.cli scan --watchlist data/watchlist.txt

live:  ## Real market data, saved and logged
	PYTHONPATH=src python -m stocksignal.cli scan --live --watchlist data/watchlist.txt --save --log

clean:  ## Remove caches and build junk
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage dist build cache out
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
