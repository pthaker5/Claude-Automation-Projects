# Module 05 — Portfolio Theory & Risk

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★

## Learning objectives

- Derive and implement mean–variance optimization, then explain why naive MVO fails in practice
  (estimation error, unstable covariance inverses) and what practitioners do instead.
- Work with factor models: CAPM, Fama–French 3/5, momentum; run factor regressions and interpret
  alpha/loadings; understand cross-sectional vs time-series views.
- Implement risk parity and compare allocation schemes honestly.
- Measure risk beyond volatility: VaR/CVaR (historical, parametric, Monte Carlo), drawdown
  statistics, and what each hides.

## Topics

1. Mean–variance: efficient frontier, tangency portfolio, constraints; estimation-error reality
2. Covariance estimation: sample vs shrinkage (Ledoit–Wolf), factor-based
3. Factor models: Fama–French, cross-sectional regressions, alpha vs exposure
4. Risk parity and volatility targeting
5. VaR and CVaR: computation, backtesting the risk model itself
6. Drawdown analysis: max drawdown distribution, time under water, Calmar

## Deliverables (planned)

- Exercises: factor-regress a chosen strategy/fund on Fama–French factors (data from Ken French
  library); shrinkage vs sample covariance in a small MVO, out-of-sample.
- Feeds **Project 2** (momentum strategy risk & factor analysis).
