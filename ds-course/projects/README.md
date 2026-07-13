# Showcase Projects — Proposals

Five proposals tailored to a **product-company data scientist** target (re-tailor
after you edit your career target in `CLAUDE.md`). Pick 4–5 with the tutor; the
recommended path is marked. Each project folder is **self-contained** — own README,
own `requirements.txt`, own tests — so any of them can be copied out into a separate
public repo manually later (per the local-only policy, publishing is always a manual
copy, never a push from here).

## Non-negotiable requirements (every project)

- Solves a plausible **business problem** on a **real public dataset** (nothing
  Kaggle-famous; source URL + download date documented)
- README with problem statement, approach, **results table/plot at the top**,
  an honest limitations section, and "what I'd do next"
- Reproducible: `requirements.txt`, seeded randomness, one `run.sh`/Makefile path
  from raw data to headline results
- At least a few **pytest** tests on the pipeline/core logic
- At least one project uses **LLMs with an eval harness**; at least one includes
  **deployment** (FastAPI + Dockerfile)

## The proposals

### 1. `churn-early-warning/` — ⭐ recommended first (modules 03–05)
Predict which telecom/subscription customers churn next cycle, with a cost-based
intervention threshold. Data: an open telco or subscription dataset NOT named
titanic/iris — e.g., IBM Telco churn alternatives from open data portals, or the
KKBox-style open subscription logs. Skills: EDA, boosting, calibration, SHAP,
business framing. *Interview story: "how I chose the threshold" beats "my AUC".*

### 2. `bikeshare-demand-forecast/` (modules 04–05)
Forecast daily/hourly dock-level demand for a city bikeshare (Capital Bikeshare /
Citi Bike open trip data — genuinely real, updated monthly). Proper time-based
validation, feature engineering (weather join from NOAA), honest backtest.
*Interview story: temporal leakage and why random CV lies on time series.*

### 3. `rag-doc-assistant/` — the LLM requirement (module 07)
RAG assistant over a real document corpus (e.g., a city's council meeting minutes,
or a federal agency's public PDFs) with a golden-set **eval harness**: retrieval
recall@k, rubric-graded answers, prompt-regression suite. *This is the 2026 hiring
delta project.*

### 4. `model-serving-api/` — the deployment requirement (module 08)
Take the churn model (or forecast model) to production shape: MLflow-tracked
training, FastAPI `/predict` with validated schemas, Dockerfile, drift-detection
script + monitoring runbook. Can be a standalone repo or the "productionization"
chapter of project 1 — decide with the tutor.

### 5. `ab-test-toolkit/` (module 02, revisited after 05)
A small, tested Python library + notebook walkthroughs: power analysis, sequential
peeking simulations, CUPED variance reduction demo on a public experiment dataset
(e.g., open marketing A/B data). *Interview story: you can talk experimentation
like someone who has run real tests.*

## Status

| Project | Status | Module gate |
|---|---|---|
| churn-early-warning | Proposed | Start after Module 03 |
| bikeshare-demand-forecast | Proposed | Start after Module 04 |
| rag-doc-assistant | Proposed | Start during Module 07 |
| model-serving-api | Proposed | Start during Module 08 |
| ab-test-toolkit | Proposed | Start after Module 02 (light), finish after 05 |
