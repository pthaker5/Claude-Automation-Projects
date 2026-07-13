# Bikeshare Demand Forecasting

> **Status: 📋 Proposed** — scaffolded, not started. See `../README.md` for the
> full proposal and module gate. This folder is self-contained (own README,
> requirements, tests) so it can be manually copied out as a standalone repo later.

## Results

*(Filled in first, before narrative, once out-of-sample evaluation exists —
headline table/plot goes here at the top.)*

## Problem statement

City bikeshare operators rebalance docks with trucks; bad demand forecasts mean empty or full stations at rush hour. Forecast station-level demand from open trip-history data joined with NOAA weather, evaluated with a walk-forward backtest (no random CV on time series). Deliverable is a forecast + an honest error analysis by station type and horizon.

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
