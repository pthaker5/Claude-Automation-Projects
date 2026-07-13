# RAG Document Assistant with Eval Harness

> **Status: 📋 Proposed** — scaffolded, not started. See `../README.md` for the
> full proposal and module gate. This folder is self-contained (own README,
> requirements, tests) so it can be manually copied out as a standalone repo later.

## Results

*(Filled in first, before narrative, once out-of-sample evaluation exists —
headline table/plot goes here at the top.)*

## Problem statement

Public-sector documents (council minutes, agency PDFs) are effectively unsearchable for residents. Build a retrieval-augmented assistant over a real corpus with citations — and prove it works with a golden-set eval harness: retrieval recall@k, rubric-graded answer quality, and a prompt-regression suite that catches quality drops when the prompt or model changes. The eval harness IS the portfolio piece.

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
