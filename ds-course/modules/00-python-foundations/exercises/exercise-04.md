# Exercise 04 — Tested Mini-Pipeline (module capstone)

**Goal:** move from notebook code to a tested, reusable `.py` module — the single
biggest code-quality jump reviewers look for. Estimated: 4–5 hours.

## The job

Turn your NYC 311 work into a small package inside this module folder:

```
modules/00-python-foundations/
├── pipeline/
│   ├── __init__.py
│   ├── clean.py        # load + clean: dtypes, dates, dedup, resolution_hours
│   └── aggregate.py    # top-complaints table, borough per-capita, monthly counts
├── tests/
│   └── test_pipeline.py
└── run_pipeline.py     # CLI: python run_pipeline.py data/raw/nyc311.csv out/
```

## Requirements

1. **Pure functions**: each takes a DataFrame in, returns a DataFrame out. No
   global state, no hard-coded paths inside functions. Type hints + docstrings.
2. **Decisions become code**: your Ex-01 choices (negative durations, dedup rule)
   become explicit, named functions with the reasoning in the docstring.
3. **≥ 5 pytest tests** in `tests/test_pipeline.py`, each on a *tiny hand-built*
   DataFrame (5–10 rows) — never the real file. Must include:
   - a happy-path test per cleaning function
   - one edge case: all-missing `closed_date`
   - one edge case: negative durations handled per your documented rule
   - one aggregation correctness test with a hand-computed expected value
4. **Runnable end-to-end**: `run_pipeline.py` writes the three aggregate outputs
   as CSVs to an output dir. Document the exact command in a module README stub.
5. `pytest` passes from the module folder on a fresh environment.

## Quality bar (the tutor reviews this like a senior DS)

- Naming: no `df2`, `temp`, `process()`. Functions say what they do.
- No duplicated logic between `clean.py` and the notebook — the notebook may now
  *import* from `pipeline/`.
- requirements.txt at course root still accurate.

## Deliverables

- [ ] Package + tests + runner as above, `pytest` green
- [ ] Commit: `Module 00 / Ex 04: tested NYC 311 pipeline package`
- [ ] Request tutor code review, then take the module quiz (`../quiz.md`)
