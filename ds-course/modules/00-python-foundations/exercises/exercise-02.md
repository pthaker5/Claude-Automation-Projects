# Exercise 02 — Same Job, Twice (pandas → polars)

**Goal:** learn polars by translation, and understand *why* it's fast (lazy
execution, expression engine) — a 2026 interview talking point. Estimated: 2–3 hours.

## Tasks

1. Reimplement your Exercise 01 Parts B+C pipeline in **polars** in
   `notebooks/ex02-polars-translation.ipynb`:
   - Once **eager** (`pl.read_csv` → method calls)
   - Once **lazy** (`pl.scan_csv` → ... → `.collect()`)
2. Look at the lazy version's `.explain()` query plan. In a markdown cell, identify
   one optimization the engine applied (e.g., projection pushdown) and explain it
   in one sentence.
3. Benchmark honestly: time pandas vs polars-eager vs polars-lazy on the same
   pipeline (use `%%timeit` or `time.perf_counter` with 3+ runs). Present a small
   results table.
4. Write 5 bullet points: "When I'd reach for polars over pandas, and when I
   wouldn't." Grounded in what you observed, not blog claims.

## Traps to notice (the tutor will ask about these)

- Polars has no index — what pandas habits break?
- `with_columns` vs `select` — when does each apply?
- Why can lazy mode be *slower* on tiny data?

## Deliverables

- [ ] Notebook runs top to bottom; benchmark table + written answers included
- [ ] Commit: `Module 00 / Ex 02: polars translation + benchmark`
