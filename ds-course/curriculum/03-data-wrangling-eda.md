# Module 03 — Data Wrangling & EDA

**Estimated time:** ~18 hours (weeks 9–10) · **Working area:** `modules/03-data-wrangling-eda/`

## Why this module matters in 2026

Models are increasingly commoditized; insight communication is not. Take-homes are
graded on whether your EDA finds the real story and whether a non-technical reader
can follow it. This is also where "messy real data" skills (encodings, duplicates,
silent type coercion, missingness mechanisms) get tested.

**From this module on: no toy datasets.** Real, downloadable, open data only.

## Learning objectives

1. Profile an unfamiliar dataset systematically: grain, keys, ranges, duplicates,
   missingness patterns (MCAR/MAR/MNAR — and why the mechanism changes the fix).
2. Clean defensively: date parsing, category normalization, outlier triage
   (investigate before deleting), unit inconsistencies.
3. Choose the right chart and make it honest: axes from zero (when it matters),
   uncertainty shown, no dual axes, small multiples over spaghetti.
4. Build a narrative EDA notebook: question → evidence → so-what, with a summary
   any PM could read.
5. Use matplotlib fluently and plotly for interactivity; know when each fits.

## Curated free resources

- [pandas — Working with missing data](https://pandas.pydata.org/docs/user_guide/missing_data.html)
- [Fundamentals of Data Visualization (Claus Wilke, free online)](https://clauswilke.com/dataviz/) — chapters on amounts, distributions, uncertainty
- [From Data to Viz](https://www.data-to-viz.com/) — chart chooser with caveats
- [matplotlib tutorials](https://matplotlib.org/stable/tutorials/index.html) + [Plotly Python docs](https://plotly.com/python/)
- [Storytelling with Data blog](https://www.storytellingwithdata.com/blog) — before/after makeovers

## Exercises (generated in depth when you reach this module)

1. Messy-data gauntlet: a genuinely dirty open dataset (municipal/open-government
   data) to profile, clean, and document every decision.
2. Missingness lab: diagnose the mechanism, compare naive drop vs imputation impact.
3. Chart makeover: three bad charts to redesign, with written justification.
4. **Narrative EDA notebook** on a dataset from your target industry — portfolio piece
   and the seed of Project 1.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] EDA notebook readable start-to-finish by a non-technical reviewer
