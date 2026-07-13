# Module 04 — Classical ML

**Estimated time:** ~35 hours (weeks 11–14) · **Working area:** `modules/04-classical-ml/`

## Why this module matters in 2026

On tabular business data, gradient boosting still wins most of the time, and
interviewers know it. What they screen for: proper validation (the #1 take-home
failure), feature engineering judgment, and the ability to explain a model to
stakeholders (SHAP). "Why not deep learning here?" is a common trap question.

## Learning objectives

1. Linear/logistic regression as baselines: assumptions, regularization (L1/L2),
   coefficients as (careful) explanations. Always build the baseline first.
2. Trees → random forests → gradient boosting (XGBoost/LightGBM): how boosting
   works, key hyperparameters, early stopping, handling categoricals.
3. **Validation done right**: train/valid/test discipline, k-fold vs stratified vs
   time-based splits, leakage taxonomy (target, temporal, preprocessing), pipelines
   so preprocessing is fit inside CV folds only.
4. Feature engineering: encodings (one-hot vs target with CV), interactions,
   aggregations over relational data, datetime features.
5. Interpretation: permutation importance vs impurity importance (and why the
   latter misleads), SHAP values, partial dependence — plus their caveats.

## Curated free resources

- [scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html) — linear models, cross-validation, pipelines
- [StatQuest — Gradient Boost series](https://www.youtube.com/watch?v=3CC4N4z3GJc) (4 parts)
- [LightGBM docs](https://lightgbm.readthedocs.io/) and [XGBoost tutorials](https://xgboost.readthedocs.io/en/stable/tutorials/index.html)
- [Interpretable Machine Learning (Christoph Molnar, free online)](https://christophm.github.io/interpretable-ml-book/) — SHAP + PDP chapters
- [Kaggle Learn — Feature Engineering](https://www.kaggle.com/learn/feature-engineering) (short, practical)

## Exercises (generated in depth when you reach this module)

1. Baseline discipline: logistic regression with a proper sklearn Pipeline; beat it
   or explain why you can't.
2. Boosting lab: LightGBM with early stopping + hyperparameter search inside CV.
3. **Leakage hunt**: a provided notebook with 5 hidden leaks — find and fix them all.
4. SHAP story: turn model explanations into three stakeholder-ready sentences.
5. **Project 1 modeling phase** (churn early-warning) starts here.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] Project 1 has a validated model beating a documented baseline
