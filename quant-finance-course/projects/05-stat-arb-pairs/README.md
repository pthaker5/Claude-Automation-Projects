# Project 5 — Statistical Arbitrage Pairs Study

**Status: NOT STARTED** — gated on Modules 04 and 06. Charter below; no results until real runs.

<!-- RESULTS PLOTS GO HERE WHEN REAL: spread + z-score sample pair, post-cost OOS equity curve -->

## Research question

Can a cointegration-based pairs strategy on liquid US ETFs/large caps clear realistic
transaction costs out of sample — or is the honest answer "no, post-2010 it's arbitraged away"?
**Either answer, rigorously shown, is a successful project.**

## Planned methodology (pre-registered)

- **Pair selection**: candidate pairs from an ex-ante economic shortlist (same sector/asset
  class), *then* Engle–Granger + Johansen tests **on the in-sample window only**. Selection is
  part of the strategy — selecting pairs on the full sample is lookahead, and the write-up will
  show the damage that mistake causes as a case study.
- **Trading rule**: spread z-score entry/exit with half-life-based lookback; parameters chosen
  in-sample, frozen, then walk-forward.
- **Splits**: IS/OOS dates stated here before the first OOS run; multiple-testing accounting
  for the number of pairs tested (this is a many-trials study by construction — deflated Sharpe
  mandatory).
- **Costs**: both legs' spread + impact; borrow cost for shorts acknowledged; turnover reported.

## Why this might not work / Limitations (drafted up front)

Cointegration estimated in-sample routinely breaks OOS (regime changes, corporate events);
pairs trading is capacity-constrained and heavily mined — post-cost decay since the 1990s is
documented in the literature; daily bars understate execution slippage on mean-reversion
signals; two-legged costs double the hurdle.

## Reproduce

*(one command, filled in when the code exists)*
