# Akzo Nobel Month-Close Automation

Automates the Akzo Nobel monthly savings close: pulls billing data from TMS,
computes TL-bid / expedite / lightweight-TL→LTL / LTL-RFP savings, and writes
the OPS, Procurement, and Closing tracker workbooks.

## Components

| File | Purpose |
|---|---|
| `akzo_month_close_engine.py` | Monthly run. Pulls the close month from SQL, computes savings, writes the three tracker workbooks. |
| `build_baselines.py` | **Refresh the reference baselines from raw data with one command.** Replaces the old hand-built Excel pivots. |
| `AKZO_MONTH_CLOSE_HANDOFF.md` | Full functional spec / handoff for the engine. |

## Why `build_baselines.py` exists (the numbers-not-matching fix)

The baselines used to be built by hand with Excel pivots. Raw TMS data spells the
same physical lane in **mixed case** — e.g. `Wood_Greensboro.NC` and
`Wood_GREENSBORO.NC`. Hand pivots merged these inconsistently, and any code that
grouped case-sensitively split one lane into two baseline rows. Those duplicate
rows then double-counted (or mis-matched) against the engine's upper-cased
current-month keys — the root cause of the drift.

**27 of 298 lanes** had such case collisions. `build_baselines.py` normalizes
**every** grouping key to UPPER-CASE, so a lane is always one lane.

Validation: rebuilt from the same raw query, the expedite baseline reproduces the
hand-built `Baseline Table Expedite Count` table **exactly** — 155/155 lanes, every
count and cost to the penny (`--validate` reports `cell-mismatches=0`).

## What gets rebuilt

| Baseline | Output sheet | Source |
|---|---|---|
| Expedite | `Baseline Table Expedite Count` | Raw query, PARCEL excluded, grouped by upper-case lane, split on Expedite Binary / Priority `EXP*` |
| LTL RFP | `LTL Baseline File` | LTL rows, baseline CPP = Σcost / Σweight per `BU_OZip.Ctry_DZip.Ctry` |
| Lightweight TL→LTL | `Light Weight TL to LTL Baseline` | Truckload rows, >15k vs ≤15k counts + baseline LT% per lane |
| In-scope lanes | `IN Scope Lanes Light Weight` | **Curated project scope — carried over, not regenerated** |

### Curated scopes carry over
The expedite baseline tracks a **fixed set of in-scope lanes** (155 in the
original table: 29 with expedites + 126 held at zero), and the LW analysis tracks
**36 in-scope lanes**. These are project-scope decisions made at the bid event, not
something to auto-expand. The builder reads them from the existing reference
workbooks and keeps them, so a refresh never silently changes scope.

### Bid-event windows
The **expedite** baseline is derived from the locked Aug'24–Aug'25 window and
reproduces exactly. The **LTL** and **LW** baselines are *bid-event* baselines — set
the corresponding `*_BASELINE_START/END` in the CONFIG block to the bid-analysis
window and point the run at that raw query.

## Usage

```bash
pip install -r requirements.txt

# Refresh baselines (production — pulls from SQL, must be on Quantix VPN):
python build_baselines.py

# Refresh from a raw Excel export instead of SQL:
python build_baselines.py --source excel

# Rebuild + compare to the current reference sheets (no surprises before writing):
python build_baselines.py --source excel --validate

# Build + report only, write nothing:
python build_baselines.py --no-write
```

Then run the monthly close (update its 6-line CONFIG first):

```bash
python akzo_month_close_engine.py
```

## Data layout (kept out of git — see `.gitignore`)

The large/sensitive workbooks live on OneDrive / the `H:` drive, not in the repo.
For local runs the code expects:

```
reference_baselines/
    EXPEDITE REDUCTION Aug 2024 - Aug 2025 BASELINE.xlsx   # built by build_baselines.py
    712 For Month Close.xlsx                               # built by build_baselines.py
sample_data/
    EXPEDITE REDUCTION Aug 2024 - Aug 2025 BASELINE_sample.xlsx   # raw query for offline validation
    712 For Month Close_sample.xlsx
```

Adjust the paths in the CONFIG block of each script for your machine.

## Expedite per-month normalization (fixed)

The expedite baseline window (Aug 1 2024 – Aug 30 2025) spans **13 calendar
months**, but the old logic divided the annual expedite count by **12**, which
inflated the per-month baseline. This is now corrected:

- `build_baselines.py` **auto-detects** the number of distinct year-months in the
  data (13 for this window) and writes the per-month figure into the baseline.
- `akzo_month_close_engine.py` uses that precomputed value; if it's missing it
  falls back to `EXPEDITE_MONTHS_IN_WINDOW = 13`.

To force a fixed divisor (e.g. lock the window to exactly 12 months), set
`EXPEDITE_MONTHS_IN_WINDOW` in `build_baselines.py`.

## Validation

There is no built-in validator. To check a month: run the engine via SQL, then
send the three output workbooks. They are cross-checked against the manually
closed numbers in the trackers — for April the authoritative targets are the
Closing `April 2026 Summary` and Procurement `Summary ANT Tracker 24` column
**`April'26` (col 70)**, which reconcile to Procurement **159,614.36** / Ops
**134,200.54**. (Note: the separate `Apr'26` col 75 in Procurement is an earlier
output that did *not* reconcile — ignore it.)

## LTL in-scope lane rule

LTL savings are credited only on in-scope lanes: **baseline lanes with more than
25 baseline shipments** (`BASELINE SID > 25`), set by `LTL_BASELINE_MIN_SHIPMENTS
= 25`. Thin lanes (≤25 baseline shipments) have statistically unreliable CPP that
inflates savings, so they are excluded. Reading the full 8,677-lane sheet without
this filter over-counts LTL ~2.8× (it credits the long tail of small, high-CPP
lanes).

Note: the manual close used a spend-sorted row cutoff
(`'LTL Baseline File'!$A$2:$D$1104`, the top 1,103 lanes by spend) as a proxy;
`>25 shipments` is the intended business rule and is what the engine applies, so
the engine's LTL total may differ slightly from a given month's manual figure
where the two rules disagree on borderline lanes.

## Open items to confirm with the business

- **LTL / LW baseline windows.** Confirm the exact bid-analysis date range so those
  two baselines are rebuilt from the right period (these are bid-event baselines and
  can use a different window than expedite — set the `*_BASELINE_START/END` in
  `build_baselines.py`).
- **STO and Payload savings** remain manual entries in the Closing Tracker.
