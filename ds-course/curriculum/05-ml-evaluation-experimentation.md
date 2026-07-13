# Module 05 — ML Evaluation & Experimentation

**Estimated time:** ~18 hours (weeks 15–16) · **Working area:** `modules/05-ml-evaluation-experimentation/`

## Why this module matters in 2026

"Your model has 94% accuracy — is it good?" is the classic screen, and the expected
answer involves base rates, cost asymmetry, calibration, and what happens online.
Evaluation maturity is what distinguishes a data scientist from someone who can call
`.fit()`. This module upgrades Project 1 from "trained a model" to "evaluated like
a professional."

## Learning objectives

1. Metrics beyond accuracy: precision/recall trade-offs, PR vs ROC curves (and when
   ROC misleads under class imbalance), F-beta, business-cost-weighted metrics.
2. **Calibration**: reliability curves, Brier score, Platt/isotonic; why calibrated
   probabilities matter for thresholding and decision-making.
3. Error analysis: slice-based evaluation (find segments where the model fails),
   confusion analysis, residual analysis for regression.
4. Uncertainty in evaluation: bootstrap CIs on metrics; is model A actually better
   than model B, or is it noise?
5. Offline vs online: why offline gains shrink online, proxy metrics, shadow
   deployment, and how model evaluation connects back to A/B testing (module 02).

## Curated free resources

- [scikit-learn — Model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html) and [Calibration](https://scikit-learn.org/stable/modules/calibration.html)
- [Google ML Crash Course — Classification metrics](https://developers.google.com/machine-learning/crash-course/classification)
- [Recognizing and Avoiding Common ML Evaluation Pitfalls (paper-adjacent blog reading; tutor will supply current links)]
- Chip Huyen, [Designing Machine Learning Systems notes](https://huyenchip.com/machine-learning-systems-design/toc.html) — evaluation & deployment chapters

## Exercises (generated in depth when you reach this module)

1. Metric duel: same model, five metrics, three different "best" thresholds — write
   the memo recommending one, with costs stated.
2. Calibration lab on Project 1's model: reliability curve before/after isotonic.
3. Slice hunter: find the two worst-performing segments and hypothesize why.
4. Bootstrap the headline metric: report the CI, not the point estimate.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] Project 1 README's results section includes CIs, calibration, and slice analysis
