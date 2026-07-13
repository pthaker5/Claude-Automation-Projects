# Data Science Portfolio — [YOUR NAME]

> **[EDIT THIS — one-sentence positioning, e.g., "Analyst transitioning to data science,
> building production-minded ML projects with honest evaluation."]**

This repository is a project-based data science course and working portfolio. Every
project solves a plausible business problem on real public data, is reproducible from
a clean clone, and includes tests. Results are stated with their limitations — no
cherry-picked metrics.

## Showcase projects

| Project | Result headline | Skills demonstrated |
|---|---|---|
| [Customer churn early-warning](projects/churn-early-warning/) | 🚧 In progress | Gradient boosting, calibration, SHAP, cost-based thresholds |
| [Demand forecasting for city bikeshare](projects/bikeshare-demand-forecast/) | 🚧 Proposed | Time series, feature engineering, backtest evaluation |
| [RAG document assistant + eval harness](projects/rag-doc-assistant/) | 🚧 Proposed | Embeddings, retrieval, LLM evals, agent basics |
| [ML model as a product: API + Docker](projects/model-serving-api/) | 🚧 Proposed | FastAPI, Docker, monitoring, MLOps |
| [A/B test analysis toolkit](projects/ab-test-toolkit/) | 🚧 Proposed | Experiment design, power analysis, sequential testing pitfalls |

*Result headlines are added only after out-of-sample evaluation — e.g., "Reduced churn
prediction error 23% vs. logistic baseline (holdout, 2024 cohort)."*

## Skills matrix

| Area | Level | Evidence |
|---|---|---|
| Python (pandas, polars, numpy) | 🟡 Learning | Module 00 |
| SQL & data modeling (DuckDB) | ⚪ Not started | Module 01 |
| Statistics & A/B testing | ⚪ Not started | Module 02 |
| EDA & data storytelling | ⚪ Not started | Module 03 |
| Classical ML (XGBoost/LightGBM, SHAP) | ⚪ Not started | Module 04 |
| ML evaluation & experimentation | ⚪ Not started | Module 05 |
| Deep learning (PyTorch) | ⚪ Not started | Module 06 |
| LLM & GenAI engineering (RAG, evals) | ⚪ Not started | Module 07 |
| MLOps (MLflow, FastAPI, Docker) | ⚪ Not started | Module 08 |

Legend: ⚪ not started · 🟡 learning · 🟢 working proficiency (project evidence linked)

## Repository layout

- `curriculum/` — syllabus per module: objectives, curated free resources, exercises
- `modules/` — my working area per module: notebooks, exercises, quizzes
- `projects/` — self-contained showcase projects (each can stand alone as its own repo)
- `progress.md` — completion log, quiz scores, and known weak spots
- `LEARNING_PLAN.md` — personalized weekly schedule
- `CLAUDE.md` — standing tutor instructions that govern every study session

## How this course works

The repo is driven by Claude Code in tutor mode: hints before solutions, Socratic
follow-ups after every exercise, and senior-DS code reviews that flag data leakage,
weak validation, and unreproducible steps. The commit history is the study log.
