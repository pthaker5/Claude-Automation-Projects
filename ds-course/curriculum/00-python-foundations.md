# Module 00 — Python for Data Work

**Estimated time:** ~25 hours (weeks 1–3) · **Working area:** `modules/00-python-foundations/`

## Why this module matters in 2026

Hiring screens assume fluent pandas and clean code as table stakes. What separates
candidates is (a) knowing *when* polars beats pandas, (b) writing data code that is
tested, and (c) not writing loops where vectorization works. Take-home assignments
are graded as much on code quality as on the answer.

## Learning objectives

By the end you can:
1. Load, filter, group, join, and reshape tabular data fluently in **pandas**, and
   translate the same operations to **polars** (lazy vs eager execution).
2. Use **numpy** vectorization instead of Python loops; explain broadcasting.
3. Structure a small data pipeline as functions in a `.py` module (not one giant
   notebook), with type hints and docstrings.
4. Write **pytest** tests for data code: fixtures, parametrize, testing transforms
   on tiny hand-built DataFrames.
5. Maintain a virtual environment and pinned `requirements.txt`.

## Curated free resources

- [pandas Getting Started tutorials](https://pandas.pydata.org/docs/getting_started/intro_tutorials/) — do all 8 short tutorials
- [Polars User Guide](https://docs.pola.rs/) — "Getting started" + "Concepts" (contexts & expressions)
- [NumPy: the absolute basics](https://numpy.org/doc/stable/user/absolute_beginners.html) + [Broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting.html)
- [pytest — Get Started](https://docs.pytest.org/en/stable/getting-started.html) and [How to parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html)
- [Effective Pandas talk (Matt Harrison, PyData)](https://www.youtube.com/watch?v=zgbUk90aQ6A) — method chaining style
- Optional deeper dive: [Python for Data Analysis, 3rd ed. (Wes McKinney, free online)](https://wesmckinney.com/book/)

## Exercises (in `modules/00-python-foundations/exercises/`)

1. **Pandas fluency drills** — 15 short tasks on a real open dataset (NYC 311 sample).
2. **Same job, twice** — rebuild exercise 1's core pipeline in polars; benchmark both.
3. **Loops to vectors** — refactor three slow loop implementations into numpy/pandas.
4. **Tested mini-pipeline** — a `pipeline.py` + `test_pipeline.py` that cleans and
   aggregates the dataset; ≥5 pytest tests, runs from a fresh clone.

## Quiz

`modules/00-python-foundations/quiz.md` — pass ≥ 80%, then Socratic check with tutor.

## Done when

- [ ] All 4 exercises complete and committed
- [ ] Quiz ≥ 80% logged in `progress.md`
- [ ] Tutor's Socratic check passed
