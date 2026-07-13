# Project 2 — Cross-Sectional Momentum with Walk-Forward Evaluation

**Status: NOT STARTED** — gated on Modules 05–06. Charter below; no results until real runs.

<!-- RESULTS PLOTS GO HERE WHEN REAL: OOS equity curve (post-cost), rolling Sharpe, turnover -->

## Research question

Does classic 12-1 cross-sectional momentum survive, after realistic costs, on a liquid-ETF (or
liquid large-cap) universe in the 2015–2025 regime — evaluated strictly walk-forward?

## Planned methodology (pre-registered before first full run)

- **Universe**: fixed, liquid list chosen *by ex-ante rules* and documented; survivorship
  caveat of yfinance stated explicitly and its likely direction of bias assessed.
- **Signal**: trailing 12-month return skipping the most recent month; monthly rebalance;
  signal from data through month-end t, execution at first open of t+1.
- **Splits**: in-sample and out-of-sample date ranges stated here before any OOS run;
  walk-forward (rolling refit of any tuned choices) with parameter-stability report.
- **Costs**: documented cost model from Module 03 (spread + impact); turnover reported.
- **Evaluation**: post-cost Sharpe with deflated Sharpe given the *count of configurations
  actually tried* (logged in the repo as they happen), drawdown analysis, Fama-French factor
  regression — is this momentum or accidental beta?

## Why this might not work / Limitations (drafted up front)

Momentum crashes (2009-style reversals); crowding since publication (Jegadeesh–Titman 1993 is
the most-cited anomaly there is); small fixed universes → wide standard errors; monthly ETF
momentum may be spanned by a single factor ETF you could just buy.

## Reproduce

*(one command, filled in when the code exists)*
