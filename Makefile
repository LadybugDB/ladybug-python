.DEFAULT_GOAL := help
# Explicit targets to avoid conflict with files of the same name.
.PHONY: \
	requirements \
	lint check format \
	build build-prebuilt bootstrap-prebuilt test \
	help

PYTHONPATH=
SHELL=/usr/bin/env bash
VENV=.venv

ifeq ($(OS),Windows_NT)
	VENV_BIN=$(VENV)/Scripts
else
	VENV_BIN=$(VENV)/bin
endif

.venv:  ## Set up a Python virtual environment and install dev packages
	uv venv $(VENV)

requirements: .venv ## Install/update Python dev packages
	@unset CONDA_PREFIX \
	&& uv pip install -e .[dev]

pytest: requirements
ifeq ($(OS),Windows_NT)
	set PYTHONPATH=./build
else
	export PYTHONPATH=./build
endif
	$(VENV_BIN)/python -m pytest -vv ./test

lint: requirements  ## Apply autoformatting and linting rules
	$(VENV_BIN)/ruff check src_py test
	$(VENV_BIN)/ruff format src_py test
	-$(VENV_BIN)/mypy src_py test

check: requirements
	$(VENV_BIN)/ruff check src_py test --verbose

format: requirements
	$(VENV_BIN)/ruff format src_py test

PREBUILT_ENV_FILE=.cache/lbug-prebuilt.env

build:  ## Compile ladybug (and install in 'build') for Python
	$(MAKE) -C ../../ python
	cp src_py/*.py build/ladybug/

bootstrap-prebuilt: ## Download latest precompiled core binary and emit cmake env file
	bash scripts/download_lbug.sh $(PREBUILT_ENV_FILE)

build-prebuilt: bootstrap-prebuilt ## Build Python bindings linked against downloaded precompiled core
	@set -a && source $(PREBUILT_ENV_FILE) && set +a && \
	$(MAKE) -C ../../ python EXTRA_CMAKE_FLAGS="$$EXTRA_CMAKE_FLAGS"
	cp src_py/*.py build/ladybug/

test: requirements  ## Run the Python unit tests
	cp src_py/*.py build/ladybug/ && cd build
	$(VENV_BIN)/pytest test

help:  ## Display this help information
	@echo -e "\033[1mAvailable commands:\033[0m"
	@grep -E '^[a-z.A-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' | sort
