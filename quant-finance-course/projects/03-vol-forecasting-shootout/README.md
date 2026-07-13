# Project 3 — Volatility Forecasting Shootout: GARCH vs ML vs Implied

**Status: NOT STARTED** — gated on Modules 04 and 08. Charter below; no results until real runs.

<!-- RESULTS PLOTS GO HERE WHEN REAL: forecast-vs-realized panels, rolling QLIKE by model -->

## Research question

For 1-day and 21-day-ahead S&P 500 volatility, who wins out of: EWMA/RiskMetrics, GARCH(1,1)
(+ a GJR asymmetric variant), a gradient-boosted model on realized-vol features, and the
market's own forecast (VIX / VIX term structure) — **properly scored**?

## Planned methodology (pre-registered)

- **Target**: realized variance from daily (squared) returns over the horizon; definition fixed
  up front.
- **Scoring**: QLIKE primarily (robust for variance forecasts), MSE secondary; Diebold–Mariano
  tests for pairwise differences. No cherry-picking the metric after seeing results.
- **Splits**: models estimated on expanding windows; forecasts strictly out-of-sample,
  one-step-ahead re-estimated; IS/OOS dates stated here before the first OOS run.
- **ML leg**: purged/embargoed CV for any tuning; features documented; a deliberately boring
  linear baseline included — if GBM can't beat HAR-RV, that gets reported.
- **Implied leg**: VIX is a risk-neutral forecast — variance-risk-premium adjustment discussed,
  not ignored.

## Why this might not work / Limitations (drafted up front)

Vol forecasting is the *easiest* forecasting problem in finance — a win here says little about
alpha; free daily data limits realized-vol quality (no intraday RV); VIX horizon (30d) doesn't
match all targets; regime dependence (2017 vs 2020 will look like different planets).

## Reproduce

*(one command, filled in when the code exists)*
