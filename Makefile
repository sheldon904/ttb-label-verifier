.PHONY: install dev test eval eval-throughput lint fixtures docker

# The virtualenv lays its binaries out differently on Windows. Decided by the
# OS, not by what exists: before `make install` there is no .venv to look at.
# WSL reports Linux and gets the Linux layout, which is what it creates.
ifeq ($(OS),Windows_NT)
VENV_BIN := .venv/Scripts
PYTHON ?= python
else
VENV_BIN := .venv/bin
PYTHON ?= python3
endif
PY := $(VENV_BIN)/python

install:
	$(PYTHON) -m venv .venv && $(PY) -m pip install -r requirements-dev.txt

dev:
	$(PY) -m uvicorn app.main:app --reload --port 8000

test:
	$(PY) -m pytest -q

# Interactive latency: one label at a time, the way an agent experiences it.
eval:
	$(PY) -m eval.run --concurrency 1

# Throughput: the batch path, saturating the OCR thread pool. Written to its
# own file so it does not replace the latency report.
eval-throughput:
	$(PY) -m eval.run --concurrency 8 --out eval/out/report-throughput.md

lint:
	$(PY) -m ruff check app tests eval

fixtures:
	$(PY) fixtures/generate.py

docker:
	docker build -t ttb-label-verifier . && docker run --rm -p 8000:8000 ttb-label-verifier
