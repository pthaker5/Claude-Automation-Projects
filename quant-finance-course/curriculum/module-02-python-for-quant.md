# Module 02 — Python for Quant Work

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★ (live-coding screens are universal)

## Learning objectives

- Write numpy/pandas that a reviewer would call fast and clean: vectorization, broadcasting,
  avoiding copies, groupby without apply, when to drop to numpy, when polars wins.
- Build a **tested** market-data pipeline on free sources (yfinance, FRED / stooq fallback):
  download, validate, cache, adjust, and serve clean price panels.
- Profile before optimizing; know the memory model well enough to explain *why* something is slow.
- Practice the software hygiene quant teams expect: pytest, type hints, small pure functions,
  reproducible environments.

## Topics

1. numpy internals: dtypes, strides, broadcasting, vectorization patterns
2. pandas done right: indexes, alignment, groupby, resampling, common performance traps
3. polars and when it matters; a fair benchmark
4. Market data plumbing: corporate actions, adjusted vs unadjusted prices, calendars, timezones,
   missing data policies (explicit, never silent `dropna`)
5. Testing numerical code: tolerances, property-based tests, fixtures with synthetic data
6. Profiling: `%timeit`, cProfile, line_profiler; memory profiling

## Deliverables (planned)

- Grow `lib/quantlab` data layer into a validated, cached pipeline with a test suite — this code
  is portfolio material and gets reviewed ruthlessly.
- Vectorization kata set: rewrite 10 slow snippets, with measured speedups.
