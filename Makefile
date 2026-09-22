.PHONY: install dev test eval eval-throughput lint fixtures docker

# The virtualenv lays its binaries out differently on Windows. Pick whichever
# exists so the same targets work from Git Bash, WSL, macOS and Linux.
VENV_BIN := $(if $(wildcard .venv/Scripts),.venv/Scripts,.venv/bin)
PY := $(VENV_BIN)/python

install:
	python -m venv .venv && $(PY) -m pip install -r requirements-dev.txt

dev:
	$(PY) -m uvicorn app.main:app --reload --port 8000

test:
	$(PY) -m pytest -q

# Interactive latency: one label at a time, the way an agent experiences it.
eval:
	$(PY) -m eval.run --concurrency 1

# Throughput: the batch path, saturating the OCR thread pool.
eval-throughput:
	$(PY) -m eval.run --concurrency 8

lint:
	$(PY) -m ruff check app tests eval

fixtures:
	$(PY) fixtures/generate.py

docker:
	docker build -t ttb-label-verifier . && docker run --rm -p 8000:8000 ttb-label-verifier
