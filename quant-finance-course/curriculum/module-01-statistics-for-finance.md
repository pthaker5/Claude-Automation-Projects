# Module 01 — Statistics for Finance

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★

## Learning objectives

- Run and *distrust* hypothesis tests: p-values, power, and what a t-stat on a Sharpe ratio
  actually assumes.
- Use regression correctly and recognize its abuses: omitted variables, heteroskedasticity,
  autocorrelated errors, Newey–West, regressions on prices vs returns.
- Test for and reason about stationarity; understand why spurious regression happens.
- Internalize the multiple-testing problem — the statistical reason most published/backtested
  alphas are false — and the corrections (Bonferroni, FDR, deflated Sharpe preview).

## Topics

1. Estimators: bias, variance, consistency; standard errors you can defend
2. Hypothesis testing, confidence intervals, power; t-tests on strategy returns
3. Linear regression: assumptions, diagnostics, robust errors; and its classic abuses in finance
4. Stationarity, unit roots (ADF), spurious regression
5. Multiple testing: data snooping, backtest overfitting as a statistics problem
6. Bootstrap and permutation tests for strategy evaluation

## Deliverables (planned)

- Exercises: replicate a "significant" alpha then kill it with proper multiple-testing correction,
  on real data; Newey–West by hand vs library.
- Quiz with interview-style questions ("your backtest t-stat is 2.5 — is the strategy real?").
