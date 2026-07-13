# Curriculum Overview

Ten modules, 00–09. Each has a syllabus file here; the **in-depth material** (lesson notes,
exercises on real market data, quiz with interview-style questions) is generated in `modules/`
one module at a time, as you reach it. Module 00 is live.

## Module map

| # | Module | Syllabus | Deep material | Feeds projects |
|---|--------|----------|---------------|----------------|
| 00 | Math & probability foundations | [syllabus](module-00-math-probability.md) | [modules/module-00](../modules/module-00-math-probability/) ✅ | all |
| 01 | Statistics for finance | [syllabus](module-01-statistics-for-finance.md) | on demand | 2, 3, 5 |
| 02 | Python for quant work | [syllabus](module-02-python-for-quant.md) | on demand | 1, all |
| 03 | Financial markets & instruments | [syllabus](module-03-markets-and-instruments.md) | on demand | 2, 5 (cost models) |
| 04 | Time series analysis | [syllabus](module-04-time-series.md) | on demand | 3, 5 |
| 05 | Portfolio theory & risk | [syllabus](module-05-portfolio-and-risk.md) | on demand | 2 |
| 06 | Backtesting done right | [syllabus](module-06-backtesting.md) | on demand | 1, 2, 5 |
| 07 | Derivatives & stochastic calculus essentials | [syllabus](module-07-derivatives.md) | on demand | 4 |
| 08 | ML for alpha | [syllabus](module-08-ml-for-alpha.md) | on demand | 3, 8 |
| 09 | Capstone — research note | [syllabus](module-09-capstone.md) | on demand | capstone |

## Career-target weighting

Current target: **Quant Researcher (QR), buy-side**. If the target changes, update
`progress.md` and re-weight per this table (★ = light pass, ★★★ = full depth + extra drilling).

| Module | QR (current) | Quant Developer | Quant Trader |
|--------|:---:|:---:|:---:|
| 00 Math & probability | ★★★ | ★★ | ★★★ (+ mental-math speed) |
| 01 Statistics | ★★★ | ★★ | ★★ |
| 02 Python | ★★★ | ★★★ (+ C++/systems, data structures) | ★★ |
| 03 Markets & microstructure | ★★ | ★★ | ★★★ (+ order-book games) |
| 04 Time series | ★★★ | ★★ | ★★ |
| 05 Portfolio & risk | ★★★ | ★★ | ★★ |
| 06 Backtesting | ★★★ | ★★★ (engine internals) | ★★ |
| 07 Derivatives & stoch. calc | ★★ | ★★ | ★★★ if options desk, else ★★ |
| 08 ML for alpha | ★★★ | ★★ | ★★ |
| 09 Capstone | ★★★ | ★★★ (engineering-flavored) | ★★★ (execution-flavored) |

Interview reality check (2026): QR screens lean probability/statistics brainteasers, a research
project walkthrough where **methodology is attacked**, ML fundamentals with skepticism expected,
and live coding in Python (clean, vectorized, tested). This curriculum is ordered so that by
Module 06 you have one defensible project, and the capstone is interview ammunition.

## Module gates

A module is *closed* when:
1. Exercises are done and survive tutor code review (see CLAUDE.md §4 checklist);
2. The quiz is passed, including the oral portion administered by the tutor;
3. `progress.md` is updated with an honest strengths/weaknesses note.
