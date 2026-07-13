# Module 01 — SQL + Data Modeling

**Estimated time:** ~18 hours (weeks 4–5) · **Working area:** `modules/01-sql-data-modeling/`

## Why this module matters in 2026

SQL screens remain the single most common DS interview filter, and they've gotten
harder: window functions, CTE decomposition, and "explain why this query is slow"
questions are standard. DuckDB lets you practice warehouse-grade SQL locally on
real files with zero setup.

## Learning objectives

1. Write multi-CTE analytical queries confidently; know when a CTE helps vs hurts.
2. Use **window functions** fluently: `ROW_NUMBER`, `RANK`, `LAG/LEAD`, rolling
   aggregates, partitioned running totals.
3. Reason about **query plans**: predicate pushdown, join order, why `SELECT *` on
   a wide Parquet file is slow (columnar storage).
4. Model data: star schema basics, grain, fact vs dimension tables, slowly changing
   dimensions (conceptually), and normalization trade-offs for analytics.
5. Mix SQL and DataFrames: query Parquet/CSV directly with DuckDB from Python.

## Curated free resources

- [DuckDB SQL introduction](https://duckdb.org/docs/stable/sql/introduction) and [Window functions docs](https://duckdb.org/docs/stable/sql/functions/window_functions)
- [Mode SQL tutorial — Advanced](https://mode.com/sql-tutorial/) (window functions, subqueries, performance)
- [SQLBolt](https://sqlbolt.com/) — quick refresher if rusty
- [Kimball dimensional modeling techniques (official summary PDF)](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/)
- Practice: [DataLemur SQL questions](https://datalemur.com/questions) — free tier, real interview questions

## Exercises (generated in depth when you reach this module)

1. Analytics question set on a real events dataset in DuckDB (window functions heavy).
2. "Slow query clinic" — three bad queries to diagnose and fix, with EXPLAIN.
3. Design a star schema for a subscription business; load it and answer exec questions.
4. Python + DuckDB pipeline: query Parquet directly, hand off to pandas for the last mile.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
