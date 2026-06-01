# Akzo Nobel Month-Close Savings Engine — Full Build Handoff

## What This Is

A Python script (`akzo_month_close_engine.py`) that automates the Akzo Nobel monthly savings close process. Every month, Poojan's team reports TL bid savings, expedite reduction savings, lightweight TL-to-LTL conversion savings, and LTL RFP savings across all Akzo business units. Previously this required manual Excel pivots. The engine pulls data directly from SQL, computes all savings categories in Python, and writes the results into three output Excel files.

---

## What Already Exists

The script is fully built and verified against March 2026 close numbers. It runs end-to-end. File: `akzo_month_close_engine.py` (1,059 lines, attached below).

**What you are being asked to do:** Read, understand, and either extend, improve, or rebuild this script based on new requirements Poojan will give you. Everything below is the full context you need.

---

## How to Run It (Current)

1. Open the CONFIG block at the top of the script (6 lines) and update:
   - `CURRENT_MONTH_START` / `CURRENT_MONTH_END` — date range for the close month
   - `MONTH_LABEL` — short label written into Excel headers (e.g. `"May'26"`)
   - `MONTH_LONG` — used in output filenames (e.g. `"May_2026"`)
   - `MONTH_FOLDER` — subfolder name under the Closing folder (e.g. `"2026-05"`)
   - `PREV_MONTH_FOLDER` — full path to last month's output folder (template source)
2. Optionally set `TL_BID_FILE` to the routing guide path if new bid rates aren't in TMS yet. Set to `None` to use TMS base charges.
3. Run: `python akzo_month_close_engine.py`
4. Enter SQL credentials and EUR/USD rate when prompted.

---

## Database Connection

- **Server:** `az-bwprod.chemlogix.com`
- **Database:** `CLXDW`
- **Driver:** `ODBC Driver 18 for SQL Server`
- **Auth:** SQL login (username + password entered at runtime via `input()` / `getpass`)
- **Connection:** `TrustServerCertificate=yes; Encrypt=yes`
- **Note:** Server is only accessible from inside Quantix VPN. Script must run on Poojan's machine (on VPN) or a VPN-connected host.

**Primary query table:** `dbo.TMSCL712_3_FI_Billing_Extract_Akzo`
Filtered by `[Pick Up Date]` between `CURRENT_MONTH_START` and `CURRENT_MONTH_END`.

**Columns pulled:**
```
SID, Order Number, Origin Loc Code, Origin Name, Origin City, Or State, Origin Zip,
Dest Loc Code, Destination Name, Destination City, Dest State, Dest Zip,
Pick Up Date, Delivery Date, Movement Type, Carrier SCAC, Carrier Name,
Transport Mode, Equipment Type, Loaded Miles, Origin Country, Dest Country,
Key ShipperSID, Priority, Normalized Weight, Normalized Ship't Actual Cost,
Normalized Adj LineHaul, Normalized Fuel Charges, Normalized Base Charges,
Normalized All Accessorials
```

---

## BU Assignment and Normalization

After the SQL pull, every row needs a Business Unit. BU is NOT in the 712 table directly. It's assigned via a lookup file.

**Step 1 — Lookup:** Try Origin Loc Code first, fall back to Dest Loc Code.
Reference file: `Akzo Origins - BU (09.04.2025).xlsx` — two columns: Origin Location Code → BU.

**Step 2 — Normalize:** Raw BU values from the lookup are inconsistent. Apply this map:

| Raw Value | Normalized |
|---|---|
| MPY, M & PC, M&PC | MPY |
| VR/ SPECIALTY, VR/SPECIALTY, VR/ Specialty | VR/ Specialty |
| METAL, Metal | Metal |
| WOOD, Wood | Wood |
| POWDER, Powder | Powder |

Rows with no BU assignment after both tries are **dropped** — they don't contribute to any category.

**BU groupings used in outputs:**
- MPY → MPY
- VR/ Specialty → ASC (Procurement Tracker label)
- Metal + Wood → ICO (Procurement Tracker label — these two are always combined)
- Powder → Powder

---

## Reference Files (Static — Update Only at Bid Events)

These three files contain the baselines. They do NOT change monthly unless a new bid event occurs.

### 1. BU Lookup File
**File:** `Akzo Origins - BU (09.04.2025).xlsx`
**Purpose:** Maps Origin Location Code to BU.
Simple two-column table. Load with `pd.read_excel`, find the column containing "Origin" + "Code" and the column for "Business" or "BU".

---

### 2. Expedite Baseline File
**File:** `EXPEDITE REDUCTION Aug 2024 - Aug 2025 BASELINE.xlsx`
**Sheet:** `Baseline Table Expedite Count`

One row per lane (155 lanes). Columns used:

| Column | Description |
|---|---|
| BU | Business unit |
| Lane | `BU_OriginCity.OrState` — e.g. `MPY_Pasadena.TX` |
| Expedite Count | Total expedite shipments over the 12-month baseline period (Aug 2024 - Aug 2025) |
| Normal Cost | Average cost of a normal (non-expedite) shipment on that lane during baseline |
| Cost Increase | How much more an expedite costs vs a normal shipment (decimal — e.g. 0.40 = 40% premium) |

**Derived field computed at load time:**
`baseline_avg_per_month = CEILING(Expedite Count / 12)`
This is the monthly average used for comparison each month.

---

### 3. Reference 712 File
**File:** `Mar 712 For Month Close.xlsx`
**Contains two separate baselines on two sheets:**

#### Sheet: `LTL Baseline File`
One row per LTL bid lane. Two columns:
- `ltl_bid_id` — `BU_OriginZip.OriginCountry_DestZip.DestCountry` (e.g. `MPY_90670.USA_92113.USA`)
- `BASELINE CPP` — cost per pound locked in at the LTL RFP bid event

These keys are matched case-insensitively (uppercase both sides). "Grand Total" rows are excluded.

#### Sheet: `Light Weight TL to LTL Baseline`
One row per lane. Columns:
- Lane — `BU_OriginCity.OrState` (stored uppercase for matching)
- Greater than 15000 — count of GT-15k shipments during baseline period
- Less than 15000 — count of LT-15k shipments during baseline period
- Column 4 — baseline LT% (the % of shipments that were under 15k during the bid period)

"Grand Total" rows excluded.

#### Sheet: `IN Scope Lanes Light Weight`
36 lane values (one per row, column A). These are the only lanes analyzed for LW TL-LTL savings.
Stored uppercase. Any TL shipment not on one of these 36 lanes is ignored for LW purposes.

---

## Savings Category Logic

### Category 1: TL Bid Savings

**Source:** `TMSCL712_3_FI_Billing_Extract_Akzo` — TL rows only

**Pre-filters:**
- Transport Mode = TRUCKLOAD (case-insensitive)
- Updated Movement Type = OB (Outbound) or IP (Interplant) only — IB excluded
- Rows with zero or null `Normalized Base Charges` dropped
- Rows with zero or null `Normalized Adj LineHaul` dropped
- **All-inclusive filter:** drop rows where `(savings_raw > 0) AND (Normalized Fuel Charges == 0)` — these are all-in rates where fuel is embedded in linehaul; comparing to a base-only rate produces false savings

**Two modes — which one runs depends on `TL_BID_FILE`:**

**Mode A: TMS-base (no bid file set)**
```
savings_per_SID = Normalized Adj LineHaul - Normalized Base Charges
```
`Normalized Adj LineHaul` = what was actually paid. `Normalized Base Charges` = pre-bid baseline stored in TMS. Negative = paid less than baseline = savings.

**Mode B: Bid file override (routing guide provided)**
```
savings_per_SID = Normalized Adj LineHaul - bid_rate
```
`bid_rate` is looked up from the routing guide by key:
`(BU, Origin City, Origin State, Dest City, Dest State, Carrier Name)` — all uppercase.
Rows with no matching bid rate are excluded.
When multiple rates exist for the same key, the lower rate is used.
Same all-inclusive filter applies.

**Sign check (per BU x Direction independently):**
Sum all `savings_raw` values for a BU/direction combination.
- If net < 0 → record `abs(net)` as savings
- If net > 0 → record $0 (no negative savings ever flows through)

**ICO:** Metal savings + Wood savings are combined into a single ICO total for Procurement Tracker output.

**Output mapping:**
```
tl_savings[(BU, Direction)] — where Direction is "OB" or "IP"
tl_total = sum of all BU/direction values
```

---

### Category 2: Expedite Reduction

**Source:** `TMSCL712_3_FI_Billing_Extract_Akzo` — all modes

**Expedite flag:** `Priority` column starts with "EXP" (case-insensitive) = expedite shipment.

**Lane key:** `BU_OriginCity.OrState` — must match the baseline table format exactly.
BU prefix uses `LANE_BU_PREFIX` map (VR/ Specialty stays as-is, MPY stays as-is, etc.)

**Per-lane computation:**
1. Count expedite shipments this month on this lane
2. Count normal shipments (non-expedite, non-PARCEL transport mode) and compute their average cost
3. If no normal shipments this month: fall back to `baseline_avg_normal_cost` from the baseline file

**Formula:**
```
exp_delta = current_exp_count - baseline_avg_per_month
cost_change = cost_pct_increase * avg_normal_cost * exp_delta
```

**Zero-expedite rule:** If a lane had zero expedite shipments this month, `cost_change = 0` regardless of the delta. (Replicates Excel behavior where blank count = blank formula result.)

**Sign check at BU level:** Sum all lane-level `cost_change` values for a BU.
- Net < 0 (fewer expedites than baseline) → record `abs(net)` as savings
- Net > 0 → record $0

**Output keys:** `exp_savings[BU_normalized]` — keys are MPY, Metal, Wood, VR/ Specialty, Powder

---

### Category 3: Lightweight TL to LTL (LW)

**Source:** `TMSCL712_3_FI_Billing_Extract_Akzo` — TL only

**Concept:** Lightweight TL shipments (under 15,000 lbs) should move to LTL because LTL is cheaper for light freight. If more of these shipments are now moving LTL vs the baseline period, that's savings.

**Pre-filters:**
- Transport Mode = TRUCKLOAD
- Lane key must be in the 36 in-scope lanes (case-insensitive)

**Lane key:** `BU_OriginCity.OrState` — uppercase

**Per lane:**
1. Split shipments into `>15,000 lbs` and `<15,000 lbs` using `Normalized Weight`
2. Compute count and average cost for each band
3. `current_lt_pct = count(<15k) / total_count`
4. Compare to `baseline_lt_pct` from reference file

**Formula:**
```
pct_change = current_lt_pct - baseline_lt_pct
cost_delta = avg_cost(>15k TL) - avg_cost(<15k TL)
savings = pct_change * total_count * cost_delta
```

**Only recognized as savings if BOTH conditions hold:**
- `pct_change > 0` (more lightweight shipments this month than baseline)
- `cost_delta > 0` (the heavy band actually costs more than the light band)

If either is zero or negative, the lane contributes $0.

BU is extracted from the lane key prefix (text before the first underscore).

**Output keys:** `lw_savings[BU_normalized]`

---

### Category 4: LTL RFP Savings

**Source:** `TMSCL712_3_FI_Billing_Extract_Akzo` — LTL rows only

**Concept:** Post-bid LTL rates should be lower than pre-bid CPP. For every shipment on a bid lane, compare actual CPP to baseline CPP. If you paid less per pound, that's savings.

**Pre-filters:**
- Transport Mode contains "LTL" (case-insensitive)
- `Normalized Ship't Actual Cost` > 0 and not null
- `Normalized Weight` > 0 and not null
- LTL Bid ID must match a lane in the baseline file (unmatched = excluded)

**LTL Bid ID construction:**
```
BU_OriginZip.OriginCountry_DestZip.DestCountry
```
Country derivation:
- If Origin Country column = "USA", "US", "UNITED STATES" → "USA"
- If Origin Country column = "CAN", "CA", "CANADA" → "CAN"
- Fallback: if zip contains letters → "CAN", else "USA"
Keys are uppercased for matching against the baseline dict.

**Aggregation:** Group by `(BU_grp, Direction, ltl_bid_id, orig_country)` where Direction uses Updated Movement Type:
- Contains "interplant" → Interplant
- Contains "inbound" → Inbound
- Else → Outbound

**Formula per group:**
```
actual_cpp = sum(Normalized Ship't Actual Cost) / sum(Normalized Weight)
cpp_delta = baseline_cpp - actual_cpp
savings = cpp_delta * total_weight   (only if cpp_delta > 0)
```

If `cpp_delta <= 0` (you paid the same or more per pound), the lane contributes $0.

**Output keys:** `ltl_savings[(BU_grp, Direction, country)]`
BU_grp groupings for output: MPY=MPY, VR/ Specialty=ASC, Metal/Wood=ICO, Powder=Powder

---

## What Is NOT Automated (Manual Still)

- **STO savings** — entered manually into Closing Tracker
- **Payload savings** — entered manually into Closing Tracker

The script prints a reminder note at the end of every run.

---

## Output Files

The script copies last month's three files as templates, renames them for the new month, then writes into specific cells.

### Closing Tracker
File: `Month Closing Tracker - {Month} {Year}.xlsx`
Sheet: first sheet containing "Summary" in its name.
Month column is auto-inserted if it doesn't exist.

| Row | Value |
|---|---|
| 2 | TL Total |
| 3 | Expedite MPY |
| 4 | Expedite ASC (VR/ Specialty) |
| 5 | Expedite Metal |
| 6 | Expedite Wood |
| 7 | LW MPY |
| 8 | LW Metal |
| 9 | LW Wood |
| 10 | LW Powder |
| 11 | LW ASC |
| 12 | LTL Total |

---

### OPS Tracker v12
File: `Akzo ANT Project Summary thru {Month} v12 REPORT for OPS Update.xlsx`
Sheet: `Summary ANT Tracker 23`
Month column header is in row 2; auto-inserted if missing.

| Row | Value |
|---|---|
| 136 | Expedite MPY |
| 137 | Expedite ASC |
| 138 | Expedite Metal |
| 139 | Expedite Wood |
| 140 | LW MPY |
| 141 | LW Metal |
| 142 | LW Wood |
| 143 | LW Powder |
| 144 | LW ASC |

Also writes EUR equivalents to the `In Euros` tab at the same rows, using `value * EUR_rate`.

---

### Procurement Tracker v12
File: `Akzo ANT Project Summary thru {Month} v12 REPORT for PROCUREMENT Update.xlsx`
Sheet: `Summary ANT Tracker 24`
Month column header is in row 2.

**TL rows (130-141):**
| Row | Value |
|---|---|
| 130 | TL MPY OB |
| 131 | TL ICO OB |
| 132 | TL ASC OB |
| 133 | TL Powder OB |
| 134 | TL MPY IP |
| 135 | TL ICO IP |
| 136 | TL ASC IP |
| 137 | TL Powder IP |
| 138-141 | IB rows — always $0 |

**LTL rows (152-161):**
| Row | Value |
|---|---|
| 152 | LTL ASC Outbound USA |
| 153 | LTL ICO Outbound USA |
| 154 | LTL MPY Outbound USA |
| 155 | LTL Powder Outbound USA |
| 156 | LTL ASC Interplant USA |
| 157 | LTL ICO Interplant (USA + CAN combined) |
| 158 | LTL MPY Interplant (USA + CAN combined) |
| 159 | LTL Powder Interplant USA |
| 160 | LTL MPY Outbound CAN |
| 161 | LTL Powder Outbound CAN |

---

## File Paths (Current Config — Poojan's Machine)

```
BASE_PATH         = H:\Integrated Logistics Design\Akzo Performance Coatings\Poojan Transition
CLOSING_PATH      = {BASE_PATH}\Akzo Month End Closing
REFERENCE_712     = C:\Users\pthaker\OneDrive - Quantix\Desktop\Adhoc\Mar 712 For Month Close.xlsx
EXPEDITE_BASELINE = C:\Users\pthaker\OneDrive - Quantix\Desktop\Adhoc\EXPEDITE REDUCTION Aug 2024 - Aug 2025 BASELINE.xlsx
BU_LOOKUP_FILE    = H:\Integrated Logistics Design\Akzo Performance Coatings\Poojan Transition\Lookups for BU and Interplant\Akzo Origins - BU (09.04.2025).xlsx
TL_BID_FILE       = C:\Users\pthaker\OneDrive - Quantix\Desktop\Adhoc\Revised TL Routing Guide 042726.xlsx
```

---

## Known Issues / Notes

1. **`Updated Movement Type` fallback:** The 712 query does not always have this column populated. The script falls back to the raw `Movement Type` column if `Updated Movement Type` is missing from the result set.

2. **All-inclusive TL filter:** If `tl_savings_raw > 0` AND `Normalized Fuel Charges == 0`, the row is dropped. This is intentional — all-in rates would show artificial positive savings vs a base-only rate. Do not remove this filter.

3. **Expedite zero-expedite lanes:** If a lane in the baseline had zero expedite shipments this month, its `cost_change` must be forced to 0 (not computed from the delta). Excel blanks this out; the Python code replicates that behavior with an explicit `exp_count > 0` guard.

4. **LW: both conditions must be true.** `pct_change > 0` alone is not enough. If the cost delta is negative (the under-15k band costs more than over-15k, which can happen), there is no savings even if you shifted more shipments to LTL.

5. **LTL case-insensitive matching:** Both the DB-built Bid ID and the baseline file keys are uppercased before comparison. Column mismatches between the DB zip format and the baseline zip format are the most common reason for low match rates.

6. **TL bid file — PRIMARY awards only:** The routing guide may contain multiple carriers per lane. The script uses the lowest rate for a given key. Poojan should confirm whether only PRIMARY awards should be included when passing the bid file.

7. **EUR/USD rate:** Entered manually at runtime. OPS Tracker writes EUR equivalents; Procurement Tracker does not (only USD written there currently).

8. **STO and Payload savings:** Not in this script. They must be manually entered in the Closing Tracker after the script runs.

---

## Python Dependencies

```
pandas
openpyxl
pyodbc
```
Standard library: `os`, `sys`, `getpass`, `shutil`, `math`, `datetime`

---

## Verification Method

To verify output is correct, compare the script's printed summary against the prior month's manually-closed Closing Tracker. March 2026 close numbers were used as ground truth during initial build and verification. The key categories to spot-check are TL Bid total and LTL RFP total — those tend to have the largest dollar values and are most sensitive to filter changes.

---

## Full Source Code

See attached `akzo_month_close_engine.py`.
