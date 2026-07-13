# Exercise 03 — Loops to Vectors

**Goal:** internalize vectorization and broadcasting; slow-loop code is an instant
red flag in DS take-homes. Estimated: 2 hours.

Work in `notebooks/ex03-vectorization.ipynb`. For each task: run the slow version,
write the vectorized version, assert identical results, and time both.

## Task 1 — Distance matrix

Given 2,000 random 2-D points (`rng = np.random.default_rng(42)`), a nested Python
loop computes all pairwise Euclidean distances. Rewrite with numpy broadcasting —
no loops, no `scipy.spatial`. Explain in one markdown sentence how the shapes
`(n,1,2)` and `(1,n,2)` broadcast.

## Task 2 — Conditional pricing

A DataFrame of 1M orders (`quantity`, `unit_price`, `customer_tier` in
{"gold","silver","bronze"}) is priced via `df.apply(row_fn, axis=1)` with if/else
tier discounts (gold 20%, silver 10%, bronze 0%, plus 5% extra when quantity > 100).
Rewrite with `np.select` (or a mapped Series + vector math). Generate the data
yourself with a seeded RNG.

## Task 3 — Rolling z-score with a twist

Given a noisy daily time series (generate 5 years, seeded), a loop computes each
day's z-score against the trailing 30-day window, then flags |z| > 2 as anomalies
— but only when the previous day was NOT flagged (no consecutive flags). Vectorize
the z-score with pandas rolling ops; then vectorize the no-consecutive-flags rule
(hint: this needs `.shift()`, think about it before asking).

## Wrap-up

Summary table: task | loop time | vectorized time | speedup. One paragraph: what
*kind* of operation resisted vectorization the most, and why?

## Deliverables

- [ ] Notebook with all three tasks, equality asserts passing, timings table
- [ ] Commit: `Module 00 / Ex 03: vectorization drills`
