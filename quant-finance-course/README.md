# Quantitative Finance — Project-Based Course & Portfolio

A self-directed, project-based quantitative finance curriculum targeting what quant hiring
(trading firms, hedge funds, quant research/dev roles) actually screens for in 2026.
Built and graded with an AI tutor operating under strict rigor rules (see [CLAUDE.md](CLAUDE.md)).

**Career target:** Quant Researcher (buy-side) — curriculum weighting reflects this; see
[curriculum/overview.md](curriculum/overview.md) for how weighting shifts for quant dev / quant trader tracks.

---

## Methodology commitments

Every result reported in this repository obeys these rules. A number that violates any of them
does not get reported.

1. **Explicit in-sample / out-of-sample splits**, with dates stated where the result is reported.
   Nothing tuned on data it is later scored on.
2. **Transaction costs and slippage always included** in headline numbers. Frictionless results
   may appear only alongside post-cost results, clearly labelled.
3. **No survivorship bias by construction where feasible**; where a free data source forces it
   (e.g., current-constituent universes from yfinance), the bias is named and its likely direction stated.
4. **Multiple-testing honesty**: number of configurations tried is reported; Sharpe ratios are
   deflated (Bailey & López de Prado) when a search was involved.
5. **Every project ships a "Why this might not work / Limitations" section.** An honest failure
   analysis is worth more than an inflated Sharpe.
6. **Reproducibility**: pinned dependencies, seeded randomness, one-command runs, pytest suites.

## Showcase projects

Result headlines follow the format *"Strategy X: Sharpe Y out-of-sample, DATES, after transaction
costs."* All are **TBD until the project is actually run** — no placeholder numbers, ever.

| # | Project | Status | Headline result (post-cost, out-of-sample) |
|---|---------|--------|--------------------------------------------|
| 1 | [Event-driven backtesting engine](projects/01-backtest-engine/) (`lib/quantlab`) | Not started | *TBD — engine correctness demonstrated via test suite & benchmark replication* |
| 2 | [Cross-sectional momentum with walk-forward evaluation](projects/02-cross-sectional-momentum/) | Not started | *TBD* |
| 3 | [Volatility forecasting shootout: GARCH vs ML vs implied](projects/03-vol-forecasting-shootout/) | Not started | *TBD — scored by QLIKE / MSE on out-of-sample windows* |
| 4 | [Options pricing & Greeks visualizer (MC vs closed-form)](projects/04-options-pricing-greeks/) | Optional | *TBD — MC estimates validated against Black-Scholes closed form* |
| 5 | [Statistical arbitrage pairs study](projects/05-stat-arb-pairs/) | Not started | *TBD — honest post-cost result, even if the answer is "it doesn't survive costs"* |

Each project directory is fully self-contained (own README, code, tests, data recipe) so it can be
copied out and published independently later.

## Skills matrix

| Skill area | Where it's built | Where it's demonstrated | Status |
|---|---|---|---|
| Probability & brainteasers | Module 00 | Quiz transcripts, warm-up log in `progress.md` | 🔄 In progress |
| Statistics / inference for finance | Module 01 | Multiple-testing analysis in Projects 2, 5 | ⬜ |
| Python performance (numpy/pandas/polars) | Module 02 | `lib/quantlab` code quality, vectorized pipelines | 🔄 Seeded |
| Market structure & microstructure | Module 03 | Cost/slippage models in Projects 2, 5 | ⬜ |
| Time series (ARIMA/GARCH/cointegration) | Module 04 | Project 3 (vol shootout), Project 5 (pairs) | ⬜ |
| Portfolio theory & risk | Module 05 | Factor exposure & drawdown analysis in Project 2 | ⬜ |
| Backtesting methodology | Module 06 | Project 1 (engine), walk-forward evals everywhere | ⬜ |
| Derivatives & stochastic calculus | Module 07 | Project 4 | ⬜ |
| ML for alpha (with skepticism) | Module 08 | Project 3 ML leg; purged CV in Project 2 | ⬜ |
| Research communication | Module 09 (capstone) | Capstone research note | ⬜ |
| Software engineering (tests, packaging, git) | Throughout | `lib/` test suite, commit history | 🔄 Seeded |

## Repository layout

```
quant-finance-course/
├── README.md            ← you are here
├── CLAUDE.md            ← tutor-mode operating rules
├── progress.md          ← session log, current assignment, calibration
├── weekly-plan.md       ← the study plan
├── curriculum/          ← one syllabus file per module (00–09) + overview
├── modules/             ← in-depth lessons/exercises/quizzes, generated one module at a time
├── projects/            ← self-contained showcase projects
├── lib/                 ← quantlab: shared, tested package (data loaders → backtest engine)
└── data/                ← local cache of downloaded market data (gitignored)
```

## Quick start

```bash
cd quant-finance-course
pip install -r requirements.txt
pip install -e lib/            # install quantlab in editable mode
python -m pytest lib/tests -q  # verify the toolkit
```

Then open [progress.md](progress.md) for the current assignment, and start a tutor session —
the tutor reads `progress.md`, serves a probability warm-up, and picks up where you left off.

## Curriculum at a glance

| Module | Topic | Depth for QR target |
|---|---|---|
| 00 | Math & probability foundations | ★★★ core — interview-critical |
| 01 | Statistics for finance | ★★★ core |
| 02 | Python for quant work | ★★★ core |
| 03 | Financial markets & instruments | ★★ context |
| 04 | Time series analysis | ★★★ core |
| 05 | Portfolio theory & risk | ★★★ core |
| 06 | Backtesting done right | ★★★ core — the differentiator |
| 07 | Derivatives & stochastic calculus | ★★ essentials (heavier if sell-side/options) |
| 08 | ML for alpha | ★★★ core in 2026 |
| 09 | Capstone research note | ★★★ core |

Details: [curriculum/overview.md](curriculum/overview.md)
