# Exercise 01 — Pandas Fluency Drills (NYC 311 Service Requests)

**Goal:** fluent loading, filtering, grouping, joining, reshaping on real data.
**Rules:** no toy data, no copy-pasting solutions. Stuck → ask the tutor for a
*concept hint* first. Estimated time: 3–4 hours.

## Setup

1. Create and activate your virtual environment; `pip install -r requirements.txt`
   (course root).
2. Download a sample of NYC 311 service requests (open data, no login):
   - Source: https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2010-to-Present/erm2-nwe9
   - Grab a manageable slice via the export/API — e.g., 250k recent rows as CSV:
     `https://data.cityofnewyork.us/resource/erm2-nwe9.csv?$limit=250000&$order=created_date DESC`
   - Save it to `data/raw/nyc311.csv` inside this module folder (`data/raw/` is
     gitignored — never commit raw data).
3. Work in `notebooks/ex01-pandas-drills.ipynb`. Put the dataset URL and download
   date in the first cell.

## Part A — Load & inspect (warm-up)

1. Load the CSV with an explicit `dtype`/`parse_dates` strategy — no naive
   `pd.read_csv(path)` and hoping. Parse `created_date` and `closed_date`.
2. Report: shape, memory usage, and the 10 columns you judge most analytically
   useful (drop the rest for this exercise — justify briefly in markdown).
3. How many exact duplicate rows exist? Are `unique_key` values actually unique?

## Part B — Filtering & transformation

4. Keep complaints created in the last full 12 months of the data. How many rows?
5. Create `resolution_hours` = closed − created, in hours. What fraction is
   missing? What fraction is *negative*, and what do you do about those rows?
   (Write your decision and reasoning in a markdown cell — this is graded.)
6. Normalize `complaint_type` to lowercase/stripped; how many distinct types
   before vs after?

## Part C — Grouping & aggregation

7. Top 10 complaint types by volume — as a well-formatted table.
8. For those top 10: median and 90th-percentile `resolution_hours`, in one
   grouped aggregation (no loops).
9. Complaints per borough **per 100k residents** — you'll need to join a small
   borough-population table; type it in by hand from any current census source
   and cite it. Which borough complains most, adjusted for population?

## Part D — Reshaping & time series

10. Build a month × borough pivot table of complaint counts.
11. Plot total monthly complaints as a line chart (matplotlib, labeled axes,
    title). Any seasonality? One-sentence interpretation in markdown.
12. For the single top complaint type: monthly share of total complaints over
    time. Rising or falling trend?

## Part E — Method-chaining refactor

13. Take your Part B–C pipeline and rewrite it as ONE method chain
    (`.pipe`, `.assign`, `.query`, `.groupby`), readable, no intermediate
    `df2`/`df3` variables. This style shows up in code review constantly.

## Deliverables

- [ ] `notebooks/ex01-pandas-drills.ipynb` — runs top to bottom on a fresh kernel
- [ ] Written answers to 5, 9, 11 in markdown cells
- [ ] Local git commit: `Module 00 / Ex 01: pandas drills on NYC 311`

Then tell the tutor you're done — expect 2–3 Socratic questions before it counts.
