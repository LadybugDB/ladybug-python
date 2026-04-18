.DEFAULT_GOAL := help
# Explicit targets to avoid conflict with files of the same name.
.PHONY: \
	requirements \
	lint check format \
	build bootstrap-capi build-pybind-subdir test test-pybind-subdir \
	help

PYTHONPATH=
SHELL=/usr/bin/env bash
VENV=.venv
LBUG_SOURCE_DIR?=ladybug

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

CAPI_ENV_FILE=.cache/lbug-capi.env

build: bootstrap-capi ## Prepare C-API backend package in ./build
	mkdir -p build/ladybug
	cp src_py/*.py build/ladybug/

build-pybind-subdir: requirements ## Build pybind via ./ladybug checkout (inverted layout)
	bash scripts/build_pybind_from_subdir.sh "$(LBUG_SOURCE_DIR)"

test-pybind-subdir: build-pybind-subdir ## Run tests against pybind build produced from ./ladybug
	export PYTHONPATH=./build
	$(VENV_BIN)/pytest -q

bootstrap-capi: ## Download latest shared C-API binary and emit runtime env file
	LBUG_LIB_KIND=shared bash scripts/download_lbug.sh $(CAPI_ENV_FILE)

test: requirements build ## Run the Python unit tests
	cd build && $(VENV_BIN)/pytest test

help:  ## Display this help information
	@echo -e "\033[1mAvailable commands:\033[0m"
	@grep -E '^[a-z.A-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' | sort
