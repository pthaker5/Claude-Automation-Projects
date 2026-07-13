# Module 08 — MLOps & Production

**Estimated time:** ~20 hours (weeks 22–23) · **Working area:** `modules/08-mlops-production/`

## Why this module matters in 2026

"Full-stack" data scientists who can ship a model behind an API are dramatically more
hireable than notebook-only candidates — especially at smaller companies where DS and
MLE blur. You don't need Kubernetes; you need the credible core: tracked experiments,
a packaged model, a served endpoint, a container, and a monitoring story.

## Learning objectives

1. **Experiment tracking** with MLflow: params, metrics, artifacts, model registry;
   never lose "which run produced this model" again.
2. **Model packaging**: pinned dependencies, model serialization pitfalls,
   inference-time preprocessing bundled with the model (no train/serve skew).
3. **Serving** with FastAPI: request/response schemas via Pydantic, input validation,
   health checks, simple load test.
4. **Docker basics**: write a Dockerfile for the API, build/run locally, layer
   caching, image size hygiene.
5. **Monitoring & drift**: logging predictions, input drift (PSI/KS tests),
   performance decay when labels arrive late, retraining triggers.

## Curated free resources

- [MLflow — Getting Started](https://mlflow.org/docs/latest/getting-started/)
- [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/) — first 10 sections + Pydantic models
- [Docker — Getting Started guide](https://docs.docker.com/get-started/)
- [Made With ML (Goku Mohandas)](https://madewithml.com/) — free MLOps lessons, testing & monitoring sections
- [Evidently AI blog — data drift concepts](https://www.evidentlyai.com/blog) (concept articles; the tool itself optional)

## Exercises (generated in depth when you reach this module)

1. Retrofit MLflow tracking onto Project 1's training pipeline; register the best model.
2. Serve Project 1's model with FastAPI: `/predict` + `/health`, validated inputs,
   pytest tests using the test client.
3. Containerize it; document the exact build/run commands in the README.
4. Drift drill: simulate input drift on held-back data, detect it with PSI, write
   the "what would trigger retraining" runbook paragraph.
5. **Deployment portfolio project** (`projects/model-serving-api/`) completes here.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] `docker build && docker run` → working `/predict` on a fresh machine
