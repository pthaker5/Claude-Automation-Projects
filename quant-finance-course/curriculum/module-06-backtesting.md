# Module 06 — Backtesting Done Right

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★ — this module is the portfolio differentiator.

## Learning objectives

- Build a simple **event-driven backtester** in `lib/quantlab` from scratch: market events →
  signals → orders → fills with costs and slippage → portfolio accounting. Understand why
  event-driven architecture prevents whole classes of lookahead bugs that vectorized backtests invite.
- Model transaction costs and slippage defensibly (from Module 03's cost model).
- Validate out of sample properly: walk-forward analysis, purged & embargoed cross-validation
  for overlapping labels (López de Prado), why ordinary k-fold lies on time series.
- Quantify overfitting: deflated Sharpe ratio, probability of backtest overfitting (PBO) via
  combinatorially symmetric cross-validation.

## Topics

1. Backtest architectures: vectorized vs event-driven; failure modes of each
2. The event loop: data handler, strategy, portfolio, execution handler; fill assumptions
3. Costs: commissions, spread, impact, borrow; turnover accounting
4. Walk-forward validation; anchored vs rolling; parameter stability reports
5. Overfitting metrics: deflated Sharpe, PBO, minimum backtest length
6. Common bugs catalog: lookahead, survivorship, restated data, signal-timing (t vs t+1 open)

## Deliverables (planned)

- **Project 1**: the engine itself, tested and documented — validated by reproducing a known
  benchmark result (e.g., buy-and-hold SPY equity curve matches direct computation to the cent).
- Every subsequent strategy project runs on this engine.
