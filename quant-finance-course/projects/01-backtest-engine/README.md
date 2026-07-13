# Project 1 — Event-Driven Backtesting Engine

**Status: NOT STARTED** — gated on Module 06. This README is the project charter; results
sections stay empty until real runs exist.

<!-- RESULTS PLOTS GO HERE WHEN REAL: equity curve of benchmark replication, cost sensitivity -->

## What this is

The `lib/quantlab` backtest engine, documented as a standalone project: market events → signal →
order → fill (with costs/slippage) → portfolio accounting. Building a small engine from scratch —
and validating it — is itself the showcase; most amateur portfolios *use* a backtester, few can
defend one they built.

## Planned scope

- Event loop: `DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler` with daily bars.
- Fill model: next-bar execution (signal on close t → fill at open t+1) — the timing convention
  that structurally prevents same-bar lookahead.
- Cost model: commissions + half-spread + optional square-root impact (from Module 03 work).
- Accounting: positions, cash, equity curve, turnover, per-trade log.

## Validation plan (the actual deliverable)

1. **Buy-and-hold replication**: SPY buy-and-hold through the engine matches the directly
   computed equity curve to numerical tolerance. Dates stated.
2. **Zero-cost/zero-signal invariants**: no trades → flat equity; costs strictly reduce returns.
3. **Deliberate-bug catches**: a test suite that injects a lookahead bug and asserts the
   engine's timing conventions make it impossible to express.
4. Property tests on accounting identities (cash + positions ≡ equity, always).

## In-sample / out-of-sample

Not applicable in the strategy sense (no parameters fitted); validation datasets and dates will
be stated here.

## Why this might not work / Limitations (to be completed honestly)

Known in advance: daily-bar fills ignore intraday paths; no partial fills or borrow constraints
initially; single currency. To be expanded with what's discovered during the build.

## Reproduce

*(one command, filled in when the code exists)*
