# Module 00 Quiz — Python for Data Work

**Rules:** closed-book, write answers below each question, then ask the tutor to
grade. Pass = 80% (12/15). Scores go in `progress.md`.

## Pandas & polars (6)

1. `df.loc[10]` and `df.iloc[10]` can return different rows. Explain when and why.
2. You group 10M rows by a string column and it's slow and memory-hungry. Name two
   concrete changes that would speed it up (and why they work).
3. What does `SettingWithCopyWarning` actually warn about, and what's the reliable
   pattern to avoid it?
4. In polars, what advantage does `scan_csv` + lazy execution have over `read_csv`?
   Name one specific optimization the query planner can make.
5. A left join between orders (1M rows) and customers (100k rows) returns 1.4M
   rows. What went wrong, and what one-line check would have caught it *before*
   the join?
6. Why is `df.apply(fn, axis=1)` usually the slowest way to compute a new column?
   What are the two idiomatic alternatives?

## NumPy (3)

7. Arrays shaped `(2000, 1, 2)` and `(1, 2000, 2)`: what shape results from
   subtracting them, and what rule makes that legal?
8. `rng = np.random.default_rng(42)` — why does seeding matter for your portfolio
   projects specifically? (One sentence, think "reviewer".)
9. What's the difference between a view and a copy of a numpy array, and give one
   operation that returns each.

## Testing & engineering (6)

10. Why should data-transform tests use tiny hand-built DataFrames instead of a
    sample of the real dataset? Give two reasons.
11. Write (on paper) a pytest test for: `add_resolution_hours(df)` must return NaN
    when `closed_date` is missing. Fixture + assert, sketch is fine.
12. What does `@pytest.mark.parametrize` buy you over copy-pasting three similar
    tests?
13. A teammate's PR hard-codes `/Users/alex/data/file.csv` inside a function.
    What's the actual problem, and what's the fix?
14. Why does a virtual environment + pinned requirements.txt matter for a *portfolio*
    repo in particular?
15. Your notebook runs fine, but only because cells were executed out of order.
    Why is this a bug for reproducibility, and what's the 10-second check?

---

## Scoring (tutor fills in)

- Score: __ / 15
- Weak areas → spaced repetition next session:
