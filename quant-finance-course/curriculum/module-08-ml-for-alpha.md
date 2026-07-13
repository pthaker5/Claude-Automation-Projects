# Module 08 — ML for Alpha

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★ — in 2026 every QR loop probes ML fundamentals *and* expects skepticism.

## Learning objectives

- Apply gradient boosting (LightGBM/XGBoost) and simple neural nets to financial features, with
  a pipeline that cannot leak: purged & embargoed CV, no test-set peeking at any stage
  (including scaling and feature selection).
- Articulate **why most ML strategies fail**: tiny signal-to-noise, non-stationarity, effective
  sample size vs feature count, backtest overfitting, publication/survivor bias in "AI fund" claims.
- Evaluate feature importance with skepticism: MDI biases, permutation importance, SHAP caveats,
  importance under correlated features.
- Frame problems correctly: labels (fixed horizon vs triple-barrier), sample weights for
  overlapping labels, meta-labeling.

## Topics

1. The financial ML problem: low SNR, regime drift, why tabular beats deep here (mostly)
2. Labeling and sample construction; overlapping-label pathologies
3. Purged/embargoed cross-validation (builds on Module 06); hyperparameter honesty
4. Gradient boosting in practice; simple NNs (MLP) as a comparison, not a fetish
5. Feature importance: MDI vs permutation vs SHAP, and their failure modes
6. Case studies of ML strategy failure; what actually survives (slow signals, ensembles, ops discipline)

## Deliverables (planned)

- Exercise: take the Module 02 pipeline's features, train GBM with purged CV, compare against a
  linear baseline — and write up whether the complexity earned its keep.
- Feeds **Project 3** (ML leg of the vol shootout).
