ifneq ($(CONDA_DEFAULT_ENV),ccc)
$(error Activate the conda env first: conda activate ccc (current: '$(CONDA_DEFAULT_ENV)'))
endif

SHELL := /bin/bash
DATASET ?= synthetic
# `make dev` with no DATASET lets the backend pick: real when artifacts/real exists, else synthetic.
DEV_DATASET := $(if $(filter command line environment,$(origin DATASET)),$(DATASET),)

.PHONY: setup seed scrape-dry scrape pipeline dev test verify readme

setup:
	pip install torch --index-url https://download.pytorch.org/whl/cpu
	pip install -e "backend[dev]"
	cd frontend && npm install

seed:
	python pipeline/seed_synthetic.py --dataset synthetic

scrape-dry:
	python pipeline/scrape_apify.py --dataset real --dry-run

scrape:
	python pipeline/scrape_apify.py --dataset real

pipeline:
	python pipeline/run_all.py --dataset $(DATASET)

dev:
	trap 'kill 0' EXIT; \
	DATASET=$(DEV_DATASET) uvicorn app.main:app --reload --port 8000 --app-dir backend & \
	(cd frontend && npm run dev -- --port 3000) & \
	wait

test:
	cd backend && python -m pytest -q
	cd frontend && npm run lint && npm run build

verify: test
	MOCK_LLM=1 python pipeline/run_all.py --dataset sample

readme:
	python scripts/readme_tables.py
