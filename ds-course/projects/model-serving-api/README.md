# Model Serving API (FastAPI + Docker)

> **Status: 📋 Proposed** — scaffolded, not started. See `../README.md` for the
> full proposal and module gate. This folder is self-contained (own README,
> requirements, tests) so it can be manually copied out as a standalone repo later.

## Results

*(Filled in first, before narrative, once out-of-sample evaluation exists —
headline table/plot goes here at the top.)*

## Problem statement

A model in a notebook creates no value. Package the churn model into a production-shaped service: MLflow-tracked training, a FastAPI /predict endpoint with validated request/response schemas, a Dockerfile, and a drift-detection script with a written retraining runbook. Deliverable: docker build && docker run → working scored predictions on a fresh machine.

## Approach

*(To be written as the project develops: data source + download date, baseline,
method, validation scheme with explicit splits.)*

## Reproducing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# one-command path from raw data to headline results — added when built:
# ./run.sh
pytest
```

## Limitations (honest)

*(Required section — what this analysis cannot claim, and why.)*

## What I'd do next

*(Required section.)*

## Layout

- `src/` — pipeline & model code (tested)
- `notebooks/` — exploration; anything reused twice moves to `src/`
- `tests/` — pytest suite
- `results/` — figures & metrics tables referenced by this README
