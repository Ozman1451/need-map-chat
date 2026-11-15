ifneq ($(CONDA_DEFAULT_ENV),ccc)
$(error Activate the conda env first: conda activate ccc (current: '$(CONDA_DEFAULT_ENV)'))
endif

SHELL := /bin/bash
DATASET ?= synthetic

.PHONY: setup seed scrape-dry scrape pipeline dev test verify

setup:
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
	DATASET=$(DATASET) uvicorn app.main:app --reload --port 8000 --app-dir backend & \
	(cd frontend && npm run dev -- --port 3000) & \
	wait

test:
	cd backend && python -m pytest -q
	cd frontend && npm run lint && npm run build

verify: test
	python pipeline/run_all.py --dataset sample
