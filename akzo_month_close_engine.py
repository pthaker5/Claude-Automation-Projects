"""
Akzo Nobel Month Close Savings Automation Engine
=================================================
FULLY AUTOMATED - no manual Excel steps required.

What you do each month:
    1. Update the CONFIG section (6 lines: dates, month label, folder)
    2. Run: python3 akzo_month_close_engine.py
    3. Enter SQL credentials and EUR/USD rate when prompted

What the engine does:
    - Pulls all current month billing data directly from az-bwprod/CLXDW
    - Loads static baselines from reference Excel files (update only at bid events)
    - Computes all savings categories in Python (no Excel pivots needed)
    - Writes output to Closing Tracker, OPS Tracker, Procurement Tracker

=== REFERENCE FILES (update only when bid event occurs) ===
    REFERENCE_712     : One-time reference 712 containing LTL Baseline File,
                        LW Baseline, In-scope lanes tabs
    EXPEDITE_BASELINE : EXPEDITE REDUCTION baseline file (Baseline Table tab)
    BU_LOOKUP_FILE    : Akzo Origins - BU lookup

=== DATA SOURCES (verified against correct March 2026 close numbers) ===

TL Bid Savings
    DB columns: Normalized Adj LineHaul, Normalized Base Charges, Normalized Fuel Charges,
                Carrier Name, Origin City, Or State, Destination City, Dest State, BU,
                Updated Movement Type
    Logic: Adj LineHaul - Base Charges per SID. Filter: no zero base/linehaul, remove
           all-inclusive (positive savings + zero fuel). OB and IP only. Each BU x Direction
           sign-checked independently. ICO = Metal savings + Wood savings.
    Fallback: if bid_file provided, use bid rates as base instead of Normalized Base Charges.

Expedite Reduction
    DB columns: Priority (EXP* = expedite), BU, Origin City, Or State,
                Normalized Ship't Actual Cost
    Logic: Build lane key (BU_OriginCity.OrState). Group by lane: count expedite vs normal,
           avg normal cost. Join against Baseline Table (155 lanes). Compute per lane:
           cost_change = cost_pct_increase x avg_normal_cost x (current_exp - baseline_avg).
           Negative = savings. Sum by BU.

Lightweight TL to LTL
    DB columns: Transport Mode, Normalized Weight, Normalized Ship't Actual Cost,
                BU, Origin City, Or State
    Logic: TL only. Build lane key. Filter to in-scope lanes (36 lanes). Group by lane +
           weight band (>15k vs <15k). Compare current LT% to baseline LT%.
           savings = pct_change x total_count x cost_delta (GT avg - LT avg), if positive.

LTL RFP Savings
    DB columns: Transport Mode, Origin Zip, Origin Country, Dest Zip, Dest Country, BU,
                Updated Movement Type, Normalized Ship't Actual Cost, Normalized Weight
    Logic: Build LTL Bid ID (BU_OriginZip.OriginCountry_DestZip.DestCountry). Join against
           LTL Baseline File (bid-event CPP per lane). Aggregate by BU + Movement + Bid ID +
           Country. savings = (baseline_cpp - actual_cpp) x weight, only if positive.
"""

import os
import sys
import getpass
import shutil
import math
import pandas as pd
import openpyxl
from datetime import datetime

# pyodbc is imported lazily inside get_connection() so the savings/calculation
# functions can be imported and unit-tested on machines without an ODBC driver.


# ===========================================================================
# CONFIG - UPDATE EACH MONTH
# ===========================================================================

CURRENT_MONTH_START = "2026-04-01"
CURRENT_MONTH_END   = "2026-04-30"
MONTH_LABEL         = "Apr'26"
MONTH_LONG          = "Apr_2026"
MONTH_FOLDER        = "2026-04"

BASE_PATH         = r"H:\Integrated Logistics Design\Akzo Performance Coatings\Poojan Transition"
CLOSING_PATH      = os.path.join(BASE_PATH, "Akzo Month End Closing")
PREV_MONTH_FOLDER = os.path.join(CLOSING_PATH, "2026-03")
NEW_MONTH_FOLDER  = os.path.join(CLOSING_PATH, MONTH_FOLDER)

# Previous month template files (copied as base for new month)
SRC_OPS     = os.path.join(PREV_MONTH_FOLDER, "Akzo ANT Project Summary thru Mar  2026 v12 REPORT for OPS Update.xlsx")
SRC_PROC    = os.path.join(PREV_MONTH_FOLDER, "Akzo ANT Project Summary thru Mar  2026 v12 REPORT for PROCUREMENT Update.xlsx")
SRC_TRACKER = os.path.join(PREV_MONTH_FOLDER, "Month Closing Tracker - Mar 2026.xlsx")

# === REFERENCE FILES - update only at bid events ===
REF_BASE_PATH   = BASE_PATH  # update path if reference files live elsewhere
REFERENCE_712     = r"C:\Users\pthaker\OneDrive - Quantix\Desktop\Adhoc\Mar 712 For Month Close.xlsx"
EXPEDITE_BASELINE = r"C:\Users\pthaker\OneDrive - Quantix\Desktop\Adhoc\EXPEDITE REDUCTION Aug 2024 - Aug 2025 BASELINE.xlsx"

# Interplant location lookup (the manual's external 'Interplant Loc' reference).
# Used to derive Updated Movement Type exactly like the close (see derive logic in
# main): col B = origin interplant location NAMES, col H = destination interplant
# location NAMES. A move is Interplant when Origin Name is in col B AND Destination
# Name is in col H.
#
# You normally do NOT need to set a path: the engine auto-locates the file by name
# (handles trailing-space / minor filename variations) in the folders where your
# other lookups live. Set INTERPLANT_LOOKUP_FILE only to force a specific file.
INTERPLANT_LOOKUP_FILE = None          # explicit override; None = auto-locate
INTERPLANT_LOOKUP_PATTERN = "Akzo Interplant Locations*.xlsx"
INTERPLANT_SHEET       = "Sheet1"

# In-scope LTL bid lanes = baseline lanes with MORE THAN 25 baseline shipments
# (BASELINE SID > 25). Per business decision: thin lanes (<=25 baseline shipments)
# are excluded -- their CPP is statistically unreliable and inflates savings.
# (The manual close used a spend-sorted row cutoff, $A$2:$D$1104, which is a close
# but not identical proxy for this rule; >25 shipments is the intended rule.)
# Set to None to use every lane in the sheet.
LTL_BASELINE_MIN_SHIPMENTS = 25
BU_LOOKUP_FILE    = "H:\\Integrated Logistics Design\\Akzo Performance Coatings\\Poojan Transition\\Lookups for BU and Interplant\\Akzo Origins \u2013 BU (09.04.2025).xlsx"

# Optional: TL bid routing guide (use ONLY when a new bid is not yet loaded in TMS).
# The new bid rates are now in TMS, so this stays None and TL savings come from
# Normalized Adj LineHaul - Normalized Base Charges directly. If a future bid is
# ever run before TMS is updated, point this at that routing guide temporarily.
TL_BID_FILE = None

# Output file names
OUT_OPS_NAME     = f"Akzo ANT Project Summary thru {MONTH_LONG.replace('_', '  ')} v12 REPORT for OPS Update.xlsx"
OUT_PROC_NAME    = f"Akzo ANT Project Summary thru {MONTH_LONG.replace('_', '  ')} v12 REPORT for PROCUREMENT Update.xlsx"
_tracker_month   = MONTH_LABEL.replace("'", " 20")
OUT_TRACKER_NAME = f"Month Closing Tracker - {_tracker_month}.xlsx"


# ===========================================================================
# DB CONNECTION
# ===========================================================================

SERVER   = "az-bwprod.chemlogix.com"
DATABASE = "CLXDW"
DRIVER   = "ODBC Driver 18 for SQL Server"

def get_connection(uid, pwd):
    import pyodbc
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={uid};"
        f"PWD={pwd};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )
    return pyodbc.connect(conn_str)

QUERY_712 = """
SELECT
    SID,
    [Order Number],
    [Origin Loc Code],
    [Origin Name],
    [Origin City],
    [Or State],
    [Origin Zip],
    [Dest Loc Code],
    [Destination Name],
    [Destination City],
    [Dest State],
    [Dest Zip],
    [Pick Up Date],
    [Delivery Date],
    [Movement Type],
    [Carrier SCAC],
    [Carrier Name],
    [Transport Mode],
    [Equipment Type],
    [Loaded Miles],
    [Origin Country],
    [Dest Country],
    [Key ShipperSID],
    [Priority],
    [Normalized Weight],
    [Normalized Ship't Actual Cost],
    [Normalized Adj LineHaul],
    [Normalized Fuel Charges],
    [Normalized Base Charges],
    [Normalized All Accessorials]
FROM dbo.TMSCL712_3_FI_Billing_Extract_Akzo
WHERE [Pick Up Date] >= '{start}' AND [Pick Up Date] <= '{end}'
""".strip()


# ===========================================================================
# BU NORMALIZATION
# ===========================================================================

BU_NORMALIZE = {
    "MPY": "MPY", "M & PC": "MPY", "M&PC": "MPY",
    "VR/ SPECIALTY": "VR/ Specialty", "VR/SPECIALTY": "VR/ Specialty",
    "VR/ Specialty": "VR/ Specialty",
    "METAL": "Metal", "Metal": "Metal",
    "WOOD": "Wood", "Wood": "Wood",
    "POWDER": "Powder", "Powder": "Powder",
}

# BU prefix used in lane keys (matches baseline file format)
LANE_BU_PREFIX = {
    "MPY": "MPY",
    "VR/ Specialty": "VR/ Specialty",
    "Metal": "Metal",
    "Wood": "Wood",
    "Powder": "Powder",
}

# BU grouping for Procurement tracker
BU_TO_GROUP = {
    "MPY": "MPY", "M & PC": "MPY",
    "VR/ Specialty": "ASC",
    "Metal": "ICO", "Wood": "ICO",
    "Powder": "Powder",
}

def normalize_bu(raw_bu):
    if raw_bu is None:
        return None
    return BU_NORMALIZE.get(str(raw_bu).strip(), str(raw_bu).strip())


# ===========================================================================
# REFERENCE DATA LOADERS (static - loaded once per session)
# ===========================================================================

def resolve_interplant_file():
    """Locate the interplant-locations workbook. Uses INTERPLANT_LOOKUP_FILE if it
    exists; otherwise searches (by INTERPLANT_LOOKUP_PATTERN, so trailing-space /
    minor filename variants still match) the folders where the other lookups live,
    plus the script dir, cwd, Downloads and the Adhoc desktop folder.
    Returns a path or None.
    """
    import glob
    if INTERPLANT_LOOKUP_FILE and os.path.exists(INTERPLANT_LOOKUP_FILE):
        return INTERPLANT_LOOKUP_FILE
    dirs = []
    for ref in (BU_LOOKUP_FILE, REFERENCE_712, EXPEDITE_BASELINE):
        try:
            dirs.append(os.path.dirname(ref))
        except Exception:
            pass
    try:
        dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    dirs.append(os.getcwd())
    home = os.path.expanduser("~")
    dirs.append(os.path.join(home, "Downloads"))
    dirs.append(os.path.join(home, "OneDrive - Quantix", "Desktop", "Adhoc"))
    seen = set()
    for d in dirs:
        if not d or d in seen:
            continue
        seen.add(d)
        try:
            hits = sorted(glob.glob(os.path.join(d, INTERPLANT_LOOKUP_PATTERN)))
        except Exception:
            hits = []
        if hits:
            return hits[0]
    return None


def load_interplant_locs(filepath=None, sheet=INTERPLANT_SHEET):
    """Load the Interplant Loc lookup the manual close uses to flag interplant.

    Mirrors the workbook formulas:
        Interplant Origin      = VLOOKUP(Origin Name,      'Interplant Loc'!$B:$B)
        Interplant Destination = VLOOKUP(Destination Name, 'Interplant Loc'!$H:$H)
    Returns (origin_names, dest_names) as UPPER-CASE name sets, or (None, None)
    when the lookup file cannot be located. When filepath is None it is
    auto-resolved via resolve_interplant_file().
    """
    if filepath is None:
        filepath = resolve_interplant_file()
    if not filepath or not os.path.exists(filepath):
        return None, None
    df = pd.read_excel(filepath, sheet_name=sheet, header=None, engine="openpyxl")
    def colset(idx):
        if df.shape[1] <= idx:
            return set()
        return {str(v).strip().upper() for v in df.iloc[:, idx].dropna() if str(v).strip()}
    return colset(1), colset(7)  # column B (origins), column H (destinations)


def load_bu_lookup(filepath):
    """Maps Origin Location Code -> Business Unit."""
    df = pd.read_excel(filepath, engine="openpyxl")
    df.columns = df.columns.str.strip()
    # Handle both column name variants
    loc_col = next((c for c in df.columns if "Origin" in c and "Code" in c), None)
    bu_col  = next((c for c in df.columns if "Business" in c or c == "BU"), None)
    if not loc_col or not bu_col:
        raise ValueError(f"Could not find Location/BU columns in {filepath}. Found: {list(df.columns)}")
    df = df[[loc_col, bu_col]].dropna(subset=[loc_col])
    df[loc_col] = df[loc_col].astype(str).str.strip()
    return dict(zip(df[loc_col], df[bu_col]))


# Divisor turning the baseline window's total expedite count into a per-month
# rate. Set to 12 to match the established methodology (per business decision).
# build_baselines.py writes a precomputed "baseline_avg_per_month" using the same
# divisor; this constant is the fallback when an older baseline file lacks it.
EXPEDITE_MONTHS_IN_WINDOW = 12

def load_expedite_baseline(filepath, months_in_window=EXPEDITE_MONTHS_IN_WINDOW):
    """
    Baseline Table Expedite Count: per-lane baseline counts and cost % increase.
    Returns DataFrame: BU, Lane, baseline_exp_count, baseline_avg_per_month,
                       baseline_avg_normal_cost, cost_pct_increase
    Lane format: BU_OriginCity.OrState (e.g. MPY_Pasadena.TX)

    baseline_avg_per_month is taken from the file if build_baselines.py wrote it
    (so the window-normalization lives in one place); otherwise it is computed
    as CEILING(expedite count / months_in_window).
    """
    df = pd.read_excel(filepath, sheet_name="Baseline Table Expedite Count", engine="openpyxl")
    df.columns = df.columns.str.strip()
    has_precomputed = "baseline_avg_per_month" in df.columns
    df = df.rename(columns={
        "BU": "BU",
        "Lane": "Lane",
        "Expedite Count": "baseline_exp_count",
        "Normal Cost": "baseline_avg_normal_cost",
        "Cost Increase": "cost_pct_increase",
    })
    keep = ["BU", "Lane", "baseline_exp_count", "baseline_avg_normal_cost", "cost_pct_increase"]
    if has_precomputed:
        keep.append("baseline_avg_per_month")
    df = df[keep].dropna(subset=["Lane"])
    df["BU"] = df["BU"].apply(normalize_bu)
    if has_precomputed:
        df["baseline_avg_per_month"] = pd.to_numeric(df["baseline_avg_per_month"], errors="coerce").fillna(0).astype(int)
    else:
        df["baseline_avg_per_month"] = df["baseline_exp_count"].apply(
            lambda x: math.ceil(x / months_in_window) if pd.notna(x) else 0
        )
    return df


def load_ltl_baseline(filepath_ref_712):
    """
    LTL Baseline File: bid-event CPP per lane.
    Returns DataFrame: ltl_bid_id, baseline_cpp
    ltl_bid_id format: BU_OriginZip.OriginCountry_DestZip.DestCountry
    """
    df = pd.read_excel(filepath_ref_712, sheet_name="LTL Baseline File", engine="openpyxl")
    df.columns = df.columns.str.strip()
    df = df.rename(columns={df.columns[0]: "ltl_bid_id", "BASELINE CPP": "baseline_cpp"})
    df["baseline_cpp"] = pd.to_numeric(df["baseline_cpp"], errors="coerce")
    df = df[["ltl_bid_id", "baseline_cpp"]].dropna(subset=["ltl_bid_id"])
    df = df[df["ltl_bid_id"] != "Grand Total"]
    df = df[df["baseline_cpp"].notna()]
    return df


def load_lw_baseline(filepath_ref_712):
    """
    LW TL to LTL Baseline: per-lane baseline LT% from bid event.
    Returns DataFrame: Lane (uppercase), lt_pct_base
    Lane format: BU_OriginCity.OrState — normalized to uppercase for case-insensitive matching.
    """
    df = pd.read_excel(filepath_ref_712, sheet_name="Light Weight TL to LTL Baseline", engine="openpyxl")
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        df.columns[0]: "Lane",
        "Greater than 15000": "gt_count_base",
        "Less than 15000": "lt_count_base",
        df.columns[4]: "lt_pct_base",
    })
    df["lt_pct_base"] = pd.to_numeric(df["lt_pct_base"], errors="coerce")
    df = df[["Lane", "lt_pct_base"]].dropna(subset=["Lane"])
    df = df[df["Lane"] != "Grand Total"]
    df["Lane"] = df["Lane"].astype(str).str.strip().str.upper()
    return df


def load_ltl_lane_baselines(filepath_ref_712, min_shipments=LTL_BASELINE_MIN_SHIPMENTS):
    """
    Load LTL Baseline CPP from the LTL Baseline File sheet (pivot output).
    Key format: BU_OriginZip.Country_DestZip.Country (e.g. MPY_90670.USA_92113.USA)
    Returns dict: uppercase_key -> baseline_cpp
    Normalized to uppercase so DB-built keys can match case-insensitively.

    Only in-scope lanes are kept: those with BASELINE SID > min_shipments. Thin
    lanes have unreliable CPP and inflate savings, so they are excluded (per
    business rule). Pass None to use every lane.
    """
    df = pd.read_excel(filepath_ref_712, sheet_name="LTL Baseline File", engine="openpyxl")
    df.columns = df.columns.str.strip()
    df = df.rename(columns={df.columns[0]: "ltl_bid_id", "BASELINE CPP": "baseline_cpp",
                            "BASELINE SID": "baseline_sid"})
    df["baseline_cpp"] = pd.to_numeric(df["baseline_cpp"], errors="coerce")
    df["baseline_sid"] = pd.to_numeric(df.get("baseline_sid"), errors="coerce")
    df = df.dropna(subset=["ltl_bid_id", "baseline_cpp"])
    df = df[df["ltl_bid_id"].astype(str).str.strip() != "Grand Total"]
    total = len(df)
    if min_shipments is not None:
        df = df[df["baseline_sid"] > min_shipments]
    result = {}
    for _, row in df.iterrows():
        key = str(row["ltl_bid_id"]).strip().upper()
        result[key] = float(row["baseline_cpp"])
    scope = (f"BASELINE SID > {min_shipments}" if min_shipments is not None else "all lanes")
    print(f"  LTL lane baselines: {len(result)} of {total} lanes loaded ({scope})")
    return result


def load_lw_in_scope_lanes(filepath_ref_712):
    """36 in-scope lanes for LW TL to LTL analysis. Stored uppercase for case-insensitive matching."""
    wb = openpyxl.load_workbook(filepath_ref_712, read_only=True, data_only=True)
    ws = wb["IN Scope Lanes Light Weight"]
    lanes = set()
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0]:
            lanes.add(str(row[0]).strip().upper())
    wb.close()
    return lanes


# ===========================================================================
# SAVINGS CALCULATIONS (all from DB data)
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. TL BID SAVINGS
# ---------------------------------------------------------------------------

def load_tl_bid_rates(filepath):
    """Load bid routing guide. Includes all rows with a rate (PRIMARY and NON PRIMARY).
    For each lane-carrier combination, uses the rate from the file regardless of award status.
    Key: (BU, origin city, origin state, dest city, dest state, carrier).
    If a lane-carrier appears more than once, takes the lower rate.
    """
    if filepath is None or not os.path.exists(filepath):
        return {}
    df = pd.read_excel(filepath, sheet_name=0, engine="openpyxl")
    df.columns = df.columns.str.strip()
    df["Revised linehaul rates"] = pd.to_numeric(df["Revised linehaul rates"], errors="coerce")
    df = df[df["Revised linehaul rates"].notna()]
    total_rows = len(df)
    bid_map = {}
    for _, row in df.iterrows():
        key = (
            str(row.get("BUSINESS UNIT", "") or "").upper().strip(),
            str(row.get("ORIGIN CITY", "") or "").upper().strip(),
            str(row.get("ORIGIN STATE", "") or "").upper().strip(),
            str(row.get("DESTINATION CITY", "") or "").upper().strip(),
            str(row.get("DESTINATION STATE", "") or "").upper().strip(),
            str(row.get("BIDDER", "") or "").upper().strip(),
        )
        rate = float(row["Revised linehaul rates"])
        if key not in bid_map or rate < bid_map[key]:
            bid_map[key] = rate
    print(f"  Bid file: {total_rows} rows with rates -> {len(bid_map)} unique lane-carrier combinations")
    return bid_map


def calc_tl_bid_savings(df_712, bid_rate_map=None):
    """
    Source: DB columns Normalized Adj LineHaul, Normalized Base Charges.
    Filters: TL only, OB and IP only. Each BU x Direction sign-checked independently.
    ICO = Metal savings + Wood savings.
    """
    df = df_712.copy()
    if "Transport Mode" in df.columns:
        df = df[df["Transport Mode"].str.upper() == "TRUCKLOAD"]

    df["Normalized Base Charges"] = pd.to_numeric(df["Normalized Base Charges"], errors="coerce")
    df["Normalized Adj LineHaul"] = pd.to_numeric(df["Normalized Adj LineHaul"], errors="coerce")
    df["Normalized Fuel Charges"] = pd.to_numeric(df["Normalized Fuel Charges"], errors="coerce")

    def map_direction(mt):
        mt = str(mt).strip().lower()
        if "interplant" in mt: return "IP"
        elif "inbound" in mt: return "IB"
        else: return "OB"

    df["direction"] = df["Updated Movement Type"].apply(map_direction)
    df = df[df["direction"].isin(["OB", "IP"])]

    if bid_rate_map:
        def lookup_bid_rate(row):
            key = (
                str(row.get("BU", "") or "").upper().strip(),
                str(row.get("Origin City", "") or "").upper().strip(),
                str(row.get("Or State", "") or "").upper().strip(),
                str(row.get("Destination City", "") or "").upper().strip(),
                str(row.get("Dest State", "") or "").upper().strip(),
                str(row.get("Carrier Name", "") or "").upper().strip(),
            )
            return bid_rate_map.get(key)

        df["bid_base"] = df.apply(lookup_bid_rate, axis=1)
        df = df[df["bid_base"].notna() & df["Normalized Adj LineHaul"].notna() &
                (df["Normalized Adj LineHaul"] != 0)]
        df["tl_savings_raw"] = df["Normalized Adj LineHaul"] - df["bid_base"]
        df = df[~((df["tl_savings_raw"] > 0) & (df["Normalized Fuel Charges"].fillna(0) == 0))]
    else:
        df = df[df["Normalized Base Charges"].notna() & (df["Normalized Base Charges"] != 0)]
        df = df[df["Normalized Adj LineHaul"].notna() & (df["Normalized Adj LineHaul"] != 0)]
        df["tl_savings_raw"] = df["Normalized Adj LineHaul"] - df["Normalized Base Charges"]
        df = df[~((df["tl_savings_raw"] > 0) & (df["Normalized Fuel Charges"].fillna(0) == 0))]

    def map_bu(bu):
        bu = normalize_bu(str(bu))
        if bu == "MPY":             return "MPY"
        elif bu == "Metal":         return "Metal"
        elif bu == "Wood":          return "Wood"
        elif bu == "VR/ Specialty": return "ASC"
        elif bu == "Powder":        return "Powder"
        return None

    df["bu_mapped"] = df["BU"].apply(map_bu)
    df = df.dropna(subset=["bu_mapped"])

    results = {}
    for direction in ["OB", "IP"]:
        d = df[df["direction"] == direction]
        metal_sav = 0.0
        wood_sav  = 0.0
        for bu in ["MPY", "ASC", "Powder", "Metal", "Wood"]:
            raw = d[d["bu_mapped"] == bu]["tl_savings_raw"].sum()
            sav = abs(raw) if raw < 0 else 0.0
            if bu == "Metal":
                metal_sav = sav
            elif bu == "Wood":
                wood_sav = sav
            else:
                results[(bu, direction)] = sav
        results[("ICO", direction)] = metal_sav + wood_sav
    return results


def dump_tl_detail(df_712, csv_path, bid_rate_map=None):
    """Write a small per-shipment TL diagnostic CSV mirroring calc_tl_bid_savings.

    One row per TRUCKLOAD shipment, with the per-row savings and a 'status'
    showing whether it was kept or why it was excluded (so a TL gap can be
    pinpointed by diffing against the manual TL RFP tab). Also prints the
    per-BU x direction summary the savings are built from.
    """
    df = df_712.copy()
    if "Transport Mode" in df.columns:
        df = df[df["Transport Mode"].astype(str).str.upper() == "TRUCKLOAD"].copy()
    if df.empty:
        print("  TL detail: no truckload rows")
        return

    df["lh"]   = pd.to_numeric(df["Normalized Adj LineHaul"], errors="coerce")
    df["base"] = pd.to_numeric(df["Normalized Base Charges"], errors="coerce")
    df["fuel"] = pd.to_numeric(df["Normalized Fuel Charges"], errors="coerce")

    def map_direction(mt):
        mt = str(mt).strip().lower()
        if "interplant" in mt: return "IP"
        elif "inbound" in mt:  return "IB"
        else:                  return "OB"

    def map_bu(bu):
        bu = normalize_bu(str(bu))
        return {"MPY": "MPY", "Metal": "Metal", "Wood": "Wood",
                "VR/ Specialty": "ASC", "Powder": "Powder"}.get(bu)

    df["direction"] = df["Updated Movement Type"].apply(map_direction)
    df["bu_mapped"] = df["BU"].apply(map_bu)

    if bid_rate_map:
        def lookup(row):
            key = (str(row.get("BU","") or "").upper().strip(),
                   str(row.get("Origin City","") or "").upper().strip(),
                   str(row.get("Or State","") or "").upper().strip(),
                   str(row.get("Destination City","") or "").upper().strip(),
                   str(row.get("Dest State","") or "").upper().strip(),
                   str(row.get("Carrier Name","") or "").upper().strip())
            return bid_rate_map.get(key)
        df["base_used"] = df.apply(lookup, axis=1)
    else:
        df["base_used"] = df["base"]
    df["tl_savings_raw"] = df["lh"] - df["base_used"]

    def status(r):
        if r["direction"] == "IB":                              return "excluded_inbound"
        if r["bu_mapped"] is None:                              return "excluded_bu_unmapped"
        if pd.isna(r["base_used"]) or r["base_used"] == 0:      return "excluded_zero_base"
        if pd.isna(r["lh"]) or r["lh"] == 0:                    return "excluded_zero_linehaul"
        if r["tl_savings_raw"] > 0 and (r["fuel"] or 0) == 0:   return "excluded_all_inclusive"
        return "kept"
    df["status"] = df.apply(status, axis=1)

    cols = ["SID", "BU", "bu_mapped", "direction", "Origin City", "Or State",
            "Destination City", "Dest State", "Carrier Name", "lh", "base_used",
            "fuel", "tl_savings_raw", "status"]
    cols = [c for c in cols if c in df.columns]
    df[cols].to_csv(csv_path, index=False)

    kept = df[df["status"] == "kept"]
    print(f"  [OK] TL detail CSV: {os.path.basename(csv_path)} "
          f"({len(df):,} TL rows, {len(kept):,} kept)")
    print(f"  TL kept summary (sum of savings_raw; negative = savings):")
    print(f"    {'BU':<8}{'dir':<5}{'count':>7}{'sum_raw':>14}{'savings':>14}")
    for direction in ["OB", "IP"]:
        for bu in ["MPY", "ASC", "Powder", "Metal", "Wood"]:
            g = kept[(kept["direction"] == direction) & (kept["bu_mapped"] == bu)]
            if len(g) == 0:
                continue
            s = g["tl_savings_raw"].sum()
            print(f"    {bu:<8}{direction:<5}{len(g):>7}{s:>14,.2f}{(abs(s) if s<0 else 0):>14,.2f}")


# ---------------------------------------------------------------------------
# 2. EXPEDITE REDUCTION
# ---------------------------------------------------------------------------

def calc_expedite_savings(df_712, df_exp_baseline):
    """
    Source: DB columns Priority (EXP* = expedite), BU, Origin City, Or State,
            Normalized Ship't Actual Cost.

    Logic:
        Build lane key: BU_OriginCity.OrState (matching baseline table format)
        Group by lane: count expedite (Priority starts with EXP) vs normal,
                       avg cost for normal shipments
        Join against Baseline Table on Lane key
        Cost Change = cost_pct_increase x current_avg_normal_cost x (current_exp - baseline_avg_per_month)
        Negative = savings (fewer expedites). Positive = $0.
        Sum by BU.
    """
    df = df_712.copy()
    cost_col = "Normalized Ship't Actual Cost"
    df["cost"] = pd.to_numeric(df.get(cost_col), errors="coerce")
    df["BU_norm"] = df["BU"].apply(normalize_bu)

    # Build lane key: BU_OriginCity.OrState
    # Use the BU prefix format from the baseline table
    def bu_prefix(bu):
        return LANE_BU_PREFIX.get(bu, bu) if bu else bu

    df["lane_key"] = (
        df["BU_norm"].apply(bu_prefix) + "_" +
        df["Origin City"].astype(str).str.strip() + "." +
        df["Or State"].astype(str).str.strip()
    )

    # Flag expedite vs normal
    df["is_expedite"] = df["Priority"].astype(str).str.upper().str.startswith("EXP")

    # Aggregate per lane
    # Exclude PARCEL from normal avg cost - pivot uses Truckload + LTL only
    df_non_exp = df[~df["is_expedite"] & ~df["Transport Mode"].astype(str).str.upper().str.contains("PARCEL", na=False)]
    exp = df[df["is_expedite"]].groupby("lane_key")["SID"].count().rename("exp_count")
    norm = df_non_exp.groupby("lane_key").agg(
        normal_count = ("SID", "count"),
        normal_avg_cost = ("cost", "mean")
    )
    lane_data = pd.concat([exp, norm], axis=1).reset_index()
    lane_data.columns.name = None
    lane_data = lane_data.rename(columns={"lane_key": "Lane"})
    lane_data["exp_count"] = lane_data["exp_count"].fillna(0)
    lane_data["normal_count"] = lane_data["normal_count"].fillna(0)
    lane_data["normal_avg_cost"] = pd.to_numeric(lane_data["normal_avg_cost"], errors="coerce").fillna(0)

    # Join against baseline using uppercase lane keys
    df_base = df_exp_baseline.copy()
    df_base["lane_upper"] = df_base["Lane"].astype(str).str.upper()
    lane_data = lane_data.rename(columns={"Lane": "lane_upper"})

    merged = pd.merge(df_base, lane_data, on="lane_upper", how="left")
    merged["exp_count"] = merged["exp_count"].fillna(0)
    merged["normal_avg_cost"] = pd.to_numeric(merged["normal_avg_cost"], errors="coerce")

    # Use baseline normal cost if no current month normal shipments
    merged["avg_cost"] = merged.apply(
        lambda r: r["normal_avg_cost"] if pd.notna(r["normal_avg_cost"]) and r["normal_avg_cost"] > 0
                  else r["baseline_avg_normal_cost"],
        axis=1
    )

    merged["exp_delta"] = merged["exp_count"] - merged["baseline_avg_per_month"]
    # KEY: if lane had ZERO expedites this month, Excel DC=blank -> DG=blank -> 0
    # Only compute cost_change for lanes with at least 1 expedite shipment
    merged["cost_change"] = merged.apply(
        lambda r: r["cost_pct_increase"] * r["avg_cost"] * r["exp_delta"]
        if pd.notna(r["cost_pct_increase"]) and pd.notna(r["avg_cost"])
           and pd.notna(r["exp_count"]) and r["exp_count"] > 0
        else 0.0,
        axis=1
    )

    # Sum per BU (positive + negative together), then sign check at BU level
    merged["BU_norm"] = merged["BU"].apply(normalize_bu)
    bu_net = merged.groupby("BU_norm")["cost_change"].sum()
    return {bu: abs(val) if pd.notna(val) and val < 0 else 0.0
            for bu, val in bu_net.items()}


# ---------------------------------------------------------------------------
# 3. LIGHTWEIGHT TL TO LTL
# ---------------------------------------------------------------------------

def calc_lw_savings(df_712, df_lw_baseline, in_scope_lanes):
    """
    Source: DB columns Transport Mode, Normalized Weight, Normalized Ship't Actual Cost,
            BU, Origin City, Or State.

    Logic:
        TL only. Build lane key: BU_OriginCity.OrState.
        Filter to in-scope lanes (36 lanes from reference 712).
        Group by lane + weight band (>15k vs <15k based on Normalized Weight).
        pct_change = current_lt_pct - baseline_lt_pct
        cost_delta = avg_cost_gt15k - avg_cost_lt15k
        savings = pct_change x total_count x cost_delta (only if both > 0)
        Sum by BU.
    """
    df = df_712.copy()
    if "Transport Mode" in df.columns:
        df = df[df["Transport Mode"].str.upper() == "TRUCKLOAD"]

    df["cost"] = pd.to_numeric(df.get("Normalized Ship't Actual Cost"), errors="coerce")
    df["weight"] = pd.to_numeric(df.get("Normalized Weight"), errors="coerce")
    df["BU_norm"] = df["BU"].apply(normalize_bu)

    def bu_prefix(bu):
        return LANE_BU_PREFIX.get(bu, bu) if bu else bu

    df["lane_key"] = (
        df["BU_norm"].apply(bu_prefix) + "_" +
        df["Origin City"].astype(str).str.strip() + "." +
        df["Or State"].astype(str).str.strip()
    ).str.upper()
    df["weight_band"] = df["weight"].apply(
        lambda w: ">15000lbs" if pd.notna(w) and w > 15000 else "<15000lbs"
    )

    # Filter to in-scope lanes (both sets already uppercase)
    df = df[df["lane_key"].isin(in_scope_lanes)]
    if df.empty:
        return {}

    # Pivot: lane x weight_band -> avg cost and count
    pivot = df.groupby(["lane_key", "weight_band"]).agg(
        avg_cost = ("cost", "mean"),
        count    = ("SID", "count")
    ).reset_index()

    wide = pivot.pivot(index="lane_key", columns="weight_band", values=["avg_cost", "count"])
    wide.columns = [f"{col[0]}_{col[1]}" for col in wide.columns]
    wide = wide.reset_index().rename(columns={"lane_key": "Lane"})

    # Standardize column names
    gt_avg   = "avg_cost_>15000lbs"
    lt_avg   = "avg_cost_<15000lbs"
    gt_count = "count_>15000lbs"
    lt_count = "count_<15000lbs"

    for col in [gt_avg, lt_avg, gt_count, lt_count]:
        if col not in wide.columns:
            wide[col] = 0.0

    wide[gt_count] = pd.to_numeric(wide[gt_count], errors="coerce").fillna(0)
    wide[lt_count] = pd.to_numeric(wide[lt_count], errors="coerce").fillna(0)
    wide[gt_avg]   = pd.to_numeric(wide[gt_avg],   errors="coerce").fillna(0)
    wide[lt_avg]   = pd.to_numeric(wide[lt_avg],   errors="coerce").fillna(0)
    wide["total_count"] = wide[gt_count] + wide[lt_count]
    wide["lt_pct"] = wide.apply(
        lambda r: r[lt_count] / r["total_count"] if r["total_count"] > 0 else 0, axis=1
    )

    # Join with baseline
    merged = pd.merge(wide, df_lw_baseline, on="Lane", how="inner")

    def calc_lane_savings(row):
        pct_change = row["lt_pct"] - row["lt_pct_base"]
        cost_delta = row[gt_avg] - row[lt_avg]
        if pct_change > 0 and cost_delta > 0:
            return pct_change * row["total_count"] * cost_delta
        return 0.0

    merged["savings"] = merged.apply(calc_lane_savings, axis=1)

    # Extract BU from lane key (prefix before first underscore; lane key is uppercase)
    BU_NORM_UPPER = {
        "MPY": "MPY", "M&PC": "MPY",
        "METAL": "Metal",
        "WOOD": "Wood",
        "POWDER": "Powder",
        "VR/ SPECIALTY": "VR/ Specialty",
    }
    merged["BU"] = merged["Lane"].apply(
        lambda x: BU_NORM_UPPER.get(str(x).split("_")[0].strip().upper(), str(x).split("_")[0].strip())
    )

    return merged.groupby("BU")["savings"].sum().to_dict()


# ---------------------------------------------------------------------------
# 4. LTL RFP SAVINGS
# ---------------------------------------------------------------------------

def calc_ltl_rfp_savings(df_712, ltl_lane_baselines):
    """
    Source: DB columns Transport Mode, BU, Updated Movement Type, Origin Zip,
            Origin Country, Dest Zip, Dest Country, Normalized Ship't Actual Cost,
            Normalized Weight.
    Reference: ltl_lane_baselines dict (from LTL Baseline File sheet), keyed by
               uppercase BU_OriginZip.Country_DestZip.Country.

    Logic:
        Build LTL Bid ID from DB columns: BU_OriginZip.OriginCountry_DestZip.DestCountry
        Match uppercase Bid ID against baseline dict.
        Only shipments on bid lanes (matched) are included.
        Aggregate by BU_grp + Direction + ltl_bid_id + Origin Country.
        actual_cpp = sum(cost) / sum(weight)
        savings = (baseline_cpp - actual_cpp) * weight (only if positive)
        Returns flat dict keyed by (BU_grp, direction, country).
    """
    df = df_712.copy()
    if "Transport Mode" in df.columns:
        df = df[df["Transport Mode"].str.upper().str.contains("LTL", na=False)]

    df["cost"]    = pd.to_numeric(df.get("Normalized Ship't Actual Cost"), errors="coerce")
    df["weight"]  = pd.to_numeric(df.get("Normalized Weight"), errors="coerce")
    df["BU_norm"] = df["BU"].apply(normalize_bu)

    # Country codes: use 3-char ISO from DB if available, else derive from zip format
    def country_code(country_raw, zip_val):
        c = str(country_raw).strip().upper()
        if c in ("USA", "US", "UNITED STATES"): return "USA"
        if c in ("CAN", "CA", "CANADA"):         return "CAN"
        # fallback: Canadian zips contain letters
        if zip_val and any(ch.isalpha() for ch in str(zip_val)):
            return "CAN"
        return "USA"

    df["orig_country"] = df.apply(
        lambda r: country_code(r.get("Origin Country", ""), r.get("Origin Zip", "")), axis=1
    )
    df["dest_country"] = df.apply(
        lambda r: country_code(r.get("Dest Country", ""), r.get("Dest Zip", "")), axis=1
    )

    # Build LTL Bid ID: BU_OriginZip.OriginCountry_DestZip.DestCountry
    def build_bid_id(row):
        bu = str(row["BU_norm"] or "").strip()
        oz = str(row.get("Origin Zip", "") or "").strip()
        dz = str(row.get("Dest Zip", "") or "").strip()
        oc = row["orig_country"]
        dc = row["dest_country"]
        return f"{bu}_{oz}.{oc}_{dz}.{dc}".upper()

    df["ltl_bid_id"] = df.apply(build_bid_id, axis=1)
    df["baseline_cpp"] = df["ltl_bid_id"].map(ltl_lane_baselines)

    # Only bid lanes with valid cost/weight
    df = df[df["baseline_cpp"].notna() &
            df["cost"].notna() & (df["cost"] > 0) &
            df["weight"].notna() & (df["weight"] > 0)].copy()

    if df.empty:
        print("  LTL RFP: 0 matched shipments - check Zip/Country columns vs baseline lane keys")
        return {}

    print(f"  LTL RFP: {len(df):,} shipments matched to baseline lanes")

    def map_dir(mt):
        mt = str(mt).strip().lower()
        if "interplant" in mt: return "Interplant"
        elif "inbound" in mt:  return "Inbound"
        else:                  return "Outbound"

    df["dir"]    = df["Updated Movement Type"].apply(map_dir)
    df["BU_grp"] = df["BU_norm"].map(lambda x: BU_TO_GROUP.get(x, x))

    agg = df.groupby(["BU_grp", "dir", "ltl_bid_id", "orig_country"]).agg(
        total_cost   = ("cost",   "sum"),
        total_weight = ("weight", "sum"),
        baseline_cpp = ("baseline_cpp", "first"),
    ).reset_index()

    agg = agg[agg["total_weight"] > 0]
    agg["actual_cpp"] = agg["total_cost"] / agg["total_weight"]
    agg["cpp_delta"]  = agg["baseline_cpp"] - agg["actual_cpp"]
    agg["savings"]    = agg.apply(
        lambda row: row["cpp_delta"] * row["total_weight"] if row["cpp_delta"] > 0 else 0.0,
        axis=1
    )

    result = {}
    for _, row in agg.iterrows():
        key = (row["BU_grp"], row["dir"], row["orig_country"])
        result[key] = result.get(key, 0.0) + row["savings"]
    return result


# ===========================================================================
# OUTPUT FILE WRITING
# ===========================================================================

def unique_path(path):
    """Return a path that does not collide with an existing file. If `path` is
    free it is returned unchanged; otherwise a timestamp (and counter if needed)
    is inserted before the extension so existing files are never overwritten.
    """
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base} ({stamp}){ext}"
    n = 2
    while os.path.exists(candidate):
        candidate = f"{base} ({stamp}_{n}){ext}"
        n += 1
    return candidate


def find_or_insert_month_col(ws, month_label, header_row=2):
    for c in range(1, ws.max_column + 1):
        val = ws.cell(row=header_row, column=c).value
        if val and str(val).strip() == month_label.strip():
            return c
    last_col = 6
    for c in range(1, ws.max_column + 1):
        if ws.cell(row=header_row, column=c).value is not None:
            last_col = c
    new_col = last_col + 1
    ws.cell(row=header_row, column=new_col).value = month_label
    return new_col


def write_closing_tracker(filepath, savings_dict, month_label):
    wb = openpyxl.load_workbook(filepath)
    sheet_name = next((s for s in wb.sheetnames if "Summary" in s), wb.sheetnames[0])
    ws = wb[sheet_name]

    month_col = None
    for c in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=c).value == month_label:
            month_col = c
            break
    if month_col is None:
        last = max((c for c in range(1, ws.max_column + 1)
                    if ws.cell(row=1, column=c).value is not None), default=3)
        month_col = last + 1
        ws.cell(row=1, column=month_col).value = month_label

    row_map = {
        2:  savings_dict.get("TL_TOTAL", 0),
        3:  savings_dict.get("EXP_MPY", 0),
        4:  savings_dict.get("EXP_ASC", 0),
        5:  savings_dict.get("EXP_Metal", 0),
        6:  savings_dict.get("EXP_Wood", 0),
        7:  savings_dict.get("LW_MPY", 0),
        8:  savings_dict.get("LW_Metal", 0),
        9:  savings_dict.get("LW_Wood", 0),
        10: savings_dict.get("LW_Powder", 0),
        11: savings_dict.get("LW_ASC", 0),
        12: savings_dict.get("LTL_TOTAL", 0),
    }
    for row, val in row_map.items():
        ws.cell(row=row, column=month_col).value = val

    wb.save(filepath)
    wb.close()
    print(f"  [OK] Closing Tracker: {os.path.basename(filepath)}")


def write_ops_tracker(filepath, savings_dict, month_label, eur_rate):
    wb = openpyxl.load_workbook(filepath)
    ws = wb["Summary ANT Tracker 23"]
    col = find_or_insert_month_col(ws, month_label)

    ops_row_map = {
        136: savings_dict.get("EXP_MPY", 0),
        137: savings_dict.get("EXP_ASC", 0),
        138: savings_dict.get("EXP_Metal", 0),
        139: savings_dict.get("EXP_Wood", 0),
        140: savings_dict.get("LW_MPY", 0),
        141: savings_dict.get("LW_Metal", 0),
        142: savings_dict.get("LW_Wood", 0),
        143: savings_dict.get("LW_Powder", 0),
        144: savings_dict.get("LW_ASC", 0),
    }
    for row, val in ops_row_map.items():
        ws.cell(row=row, column=col).value = val

    # EUR equivalent in In Euros tab
    if "In Euros" in wb.sheetnames:
        ws_eur = wb["In Euros"]
        for row, val in ops_row_map.items():
            ws_eur.cell(row=row, column=col).value = round(val * eur_rate, 2)

    wb.save(filepath)
    wb.close()
    print(f"  [OK] OPS Tracker: col {col} ({month_label})")


def write_procurement_tracker(filepath, tl_savings, ltl_savings, month_label, eur_rate):
    wb = openpyxl.load_workbook(filepath)
    ws = wb["Summary ANT Tracker 24"]
    col = find_or_insert_month_col(ws, month_label)

    tl_row_map = {
        130: tl_savings.get(("MPY",  "OB"), 0),
        131: tl_savings.get(("ICO",  "OB"), 0),
        132: tl_savings.get(("ASC",  "OB"), 0),
        133: tl_savings.get(("Powder","OB"), 0),
        134: tl_savings.get(("MPY",  "IP"), 0),
        135: tl_savings.get(("ICO",  "IP"), 0),
        136: tl_savings.get(("ASC",  "IP"), 0),
        137: tl_savings.get(("Powder","IP"), 0),
        138: 0, 139: 0, 140: 0, 141: 0,  # IB excluded
    }
    for row, val in tl_row_map.items():
        ws.cell(row=row, column=col).value = val

    def ltl(bu, dir_, country="USA"):
        return ltl_savings.get((bu, dir_, country), 0.0)

    ltl_row_map = {
        152: ltl("ASC",    "Outbound",   "USA"),
        153: ltl("ICO",    "Outbound",   "USA"),
        154: ltl("MPY",    "Outbound",   "USA"),
        155: ltl("Powder", "Outbound",   "USA"),
        156: ltl("ASC",    "Interplant", "USA"),
        157: ltl("ICO",    "Interplant", "USA") + ltl("ICO", "Interplant", "CAN"),
        158: ltl("MPY",    "Interplant", "USA") + ltl("MPY", "Interplant", "CAN"),
        159: ltl("Powder", "Interplant", "USA"),
        160: ltl("MPY",    "Outbound",   "CAN"),
        161: ltl("Powder", "Outbound",   "CAN"),
    }
    for row, val in ltl_row_map.items():
        ws.cell(row=row, column=col).value = val

    wb.save(filepath)
    wb.close()
    print(f"  [OK] Procurement Tracker: col {col} ({month_label})")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("=" * 65)
    print("Akzo Nobel Month Close Engine - FULLY AUTOMATED")
    print(f"Month: {MONTH_LABEL}  |  {CURRENT_MONTH_START} to {CURRENT_MONTH_END}")
    print("=" * 65)

    # -----------------------------------------------------------------------
    # PRE-RUN VALIDATION
    # -----------------------------------------------------------------------
    print("\n[0/6] Pre-run validation...")
    errors = []

    required = [
        ("Previous OPS Tracker",         SRC_OPS),
        ("Previous Procurement Tracker", SRC_PROC),
        ("Previous Closing Tracker",     SRC_TRACKER),
        ("Expedite Baseline",            EXPEDITE_BASELINE),
        ("Reference 712",                REFERENCE_712),
        ("BU Lookup",                    BU_LOOKUP_FILE),
    ]
    for label, path in required:
        if not os.path.exists(path):
            errors.append(f"  MISSING: {label}\n    -> {path}")

    if errors:
        print("Pre-run validation FAILED:\n")
        for e in errors:
            print(e)
        sys.exit(1)
    print("  All checks passed.")

    uid = input("\nSQL Username: ").strip()
    pwd = getpass.getpass("SQL Password: ")
    eur_rate = float(input("EUR/USD rate (e.g. 0.86): ").strip())

    # -----------------------------------------------------------------------
    # STEP 1: Setup output folder
    # -----------------------------------------------------------------------
    print("\n[1/6] Setting up output folder...")
    os.makedirs(NEW_MONTH_FOLDER, exist_ok=True)
    # Never overwrite/replace an existing file in the folder: if a same-named
    # output already exists, write to a new timestamped name instead.
    out_ops     = unique_path(os.path.join(NEW_MONTH_FOLDER, OUT_OPS_NAME))
    out_proc    = unique_path(os.path.join(NEW_MONTH_FOLDER, OUT_PROC_NAME))
    out_tracker = unique_path(os.path.join(NEW_MONTH_FOLDER, OUT_TRACKER_NAME))

    for src, dst in [(SRC_OPS, out_ops), (SRC_PROC, out_proc), (SRC_TRACKER, out_tracker)]:
        shutil.copy2(src, dst)
        print(f"  Created: {os.path.basename(dst)}")

    # -----------------------------------------------------------------------
    # STEP 2: Pull current month data from DB
    # -----------------------------------------------------------------------
    print(f"\n[2/6] Pulling {CURRENT_MONTH_START} to {CURRENT_MONTH_END} from DB...")
    conn = get_connection(uid, pwd)
    query = QUERY_712.format(start=CURRENT_MONTH_START, end=CURRENT_MONTH_END)
    df_712 = pd.read_sql(query, conn)
    conn.close()
    print(f"  {len(df_712):,} rows loaded")

    # --- Collapse to one row per SID (match the manual one-per-SID extract) ---
    # The TMSCL712 billing table can return multiple charge/leg rows per SID
    # (common for LTL); each row repeats the SID-level Normalized values, so
    # summing them multiplies a shipment's cost/weight by its line count. This is
    # why LTL came in ~2.8x high while Lightweight (single-line TL) reconciled to
    # the penny. The safety check below warns if duplicate rows of a SID ever
    # carry DIFFERING normalized cost (which would mean we must sum, not keep one).
    if "SID" in df_712.columns and df_712["SID"].duplicated().any():
        n_rows, n_sids = len(df_712), df_712["SID"].nunique()
        cost_col = "Normalized Ship't Actual Cost"
        varying = int((df_712.groupby("SID")[cost_col].nunique() > 1).sum()) if cost_col in df_712.columns else 0
        warn = f"  WARNING: {varying} SIDs have differing {cost_col} across rows (keep-first may undercount)" if varying else ""
        print(f"  Duplicate SID rows: {n_rows:,} rows -> {n_sids:,} unique SIDs{warn}")
        df_712 = df_712.drop_duplicates(subset=["SID"], keep="first").reset_index(drop=True)
        print(f"  Collapsed to one row per SID: {len(df_712):,} rows")

    # Assign BU using lookup: try Origin Loc Code first, fall back to Dest Loc Code
    bu_map = load_bu_lookup(BU_LOOKUP_FILE)
    def assign_bu(row):
        origin_bu = bu_map.get(str(row.get("Origin Loc Code", "") or "").strip())
        if origin_bu:
            return origin_bu
        return bu_map.get(str(row.get("Dest Loc Code", "") or "").strip())

    df_712["BU"] = df_712.apply(assign_bu, axis=1)
    resolved = df_712["BU"].notna().sum()
    print(f"  BU resolved: {resolved:,} of {len(df_712):,} rows")
    df_712["BU"] = df_712["BU"].apply(normalize_bu)

    # Remove rows with no BU assignment - these are excluded from all calculations
    before = len(df_712)
    df_712 = df_712[df_712["BU"].notna()].copy()
    dropped = before - len(df_712)
    if dropped:
        print(f"  Removed {dropped} rows with no BU assignment")

    # --- Direction (Updated Movement Type) ---
    # Replicate the manual close's formula exactly:
    #   Interplant  if Origin Name is an interplant location (Interplant Loc col B)
    #               AND Destination Name is one (Interplant Loc col H)
    #   Inbound     elif SID starts with "AK0"
    #   Outbound    otherwise
    # Raw [Movement Type] mis-splits interplant vs outbound, so we derive it.
    interplant_path = resolve_interplant_file()
    io_locs, id_locs = load_interplant_locs(interplant_path)
    if io_locs is not None:
        print(f"  Interplant lookup: {interplant_path}")
        def derive_mt(row):
            oi = str(row.get("Origin Name", "") or "").strip().upper() in io_locs
            di = str(row.get("Destination Name", "") or "").strip().upper() in id_locs
            if oi and di:
                return "Interplant"
            if str(row.get("SID", "") or "").strip().upper().startswith("AK0"):
                return "Inbound"
            return "Outbound"
        df_712["Updated Movement Type"] = df_712.apply(derive_mt, axis=1)
        print(f"  Direction (Interplant Loc lookup: {len(io_locs)} origin / {len(id_locs)} dest names): "
              f"{df_712['Updated Movement Type'].value_counts().to_dict()}")
    else:
        if "Updated Movement Type" not in df_712.columns:
            df_712["Updated Movement Type"] = df_712.get("Movement Type", "Outbound")
        print(f"  *** WARNING: could not locate '{INTERPLANT_LOOKUP_PATTERN}' in the lookup/Adhoc/\n"
              f"      Downloads folders -> falling back to raw Movement Type; TL OB/IP split will be WRONG.\n"
              f"      Put 'Akzo Interplant Locations.xlsx' next to this script (or set INTERPLANT_LOOKUP_FILE).")

    # -----------------------------------------------------------------------
    # STEP 3: Load static reference baselines
    # -----------------------------------------------------------------------
    print("\n[3/6] Loading reference baselines...")

    df_exp_baseline = load_expedite_baseline(EXPEDITE_BASELINE)
    print(f"  Expedite baseline: {len(df_exp_baseline)} lanes")

    ltl_lane_baselines = load_ltl_lane_baselines(REFERENCE_712)

    df_lw_baseline = load_lw_baseline(REFERENCE_712)
    in_scope_lw = load_lw_in_scope_lanes(REFERENCE_712)
    print(f"  LW baseline: {len(df_lw_baseline)} lanes, {len(in_scope_lw)} in-scope")

    # TL bid rates (optional)
    bid_rate_map = load_tl_bid_rates(TL_BID_FILE) if TL_BID_FILE else {}
    if not bid_rate_map:
        print("  TL bid: using Normalized Base Charges from TMS")

    # -----------------------------------------------------------------------
    # STEP 4: Compute all savings from DB data
    # -----------------------------------------------------------------------
    print("\n[4/6] Computing savings...")

    # Always compute TMS base version
    tl_savings_tms = calc_tl_bid_savings(df_712, None)
    tl_total_tms = sum(tl_savings_tms.values())
    print(f"  TL Bid (TMS base):     ${tl_total_tms:,.0f}")

    # Compute bid file version if available
    if bid_rate_map:
        tl_savings_bid = calc_tl_bid_savings(df_712, bid_rate_map)
        tl_total_bid = sum(tl_savings_bid.values())
        print(f"  TL Bid (bid file):     ${tl_total_bid:,.0f}")
        # Use bid file version as primary output
        tl_savings = tl_savings_bid
        tl_total = tl_total_bid
    else:
        tl_savings = tl_savings_tms
        tl_total = tl_total_tms

    # Diagnostic: per-shipment TL detail CSV (small) to reconcile TL vs the manual close
    try:
        dump_tl_detail(df_712, unique_path(os.path.join(NEW_MONTH_FOLDER, f"TL_detail_{MONTH_FOLDER}.csv")), bid_rate_map)
    except Exception as e:
        print(f"  (TL detail dump skipped: {e})")

    exp_savings = calc_expedite_savings(df_712, df_exp_baseline)
    print(f"  Expedite: MPY=${exp_savings.get('MPY',0):,.0f}  "
          f"Metal=${exp_savings.get('Metal',0):,.0f}  "
          f"ASC=${exp_savings.get('VR/ Specialty',0):,.0f}  "
          f"Wood=${exp_savings.get('Wood',0):,.0f}")

    lw_savings = calc_lw_savings(df_712, df_lw_baseline, in_scope_lw)
    print(f"  LW: MPY=${lw_savings.get('MPY',0):,.0f}  "
          f"Metal=${lw_savings.get('Metal',0):,.0f}  "
          f"Wood=${lw_savings.get('Wood',0):,.0f}  "
          f"Powder=${lw_savings.get('Powder',0):,.0f}  "
          f"ASC=${lw_savings.get('VR/ Specialty',0):,.0f}")

    ltl_savings = calc_ltl_rfp_savings(df_712, ltl_lane_baselines)
    ltl_total = sum(ltl_savings.values())
    print(f"  LTL RFP: ${ltl_total:,.0f}")

    # -----------------------------------------------------------------------
    # STEP 5: Assemble output dict
    # -----------------------------------------------------------------------
    savings_dict = {
        "TL_TOTAL":  tl_total,
        "EXP_MPY":   exp_savings.get("MPY", 0),
        "EXP_ASC":   exp_savings.get("VR/ Specialty", 0),
        "EXP_Metal": exp_savings.get("Metal", 0),
        "EXP_Wood":  exp_savings.get("Wood", 0),
        "LW_MPY":    lw_savings.get("MPY", 0),
        "LW_Metal":  lw_savings.get("Metal", 0),
        "LW_Wood":   lw_savings.get("Wood", 0),
        "LW_Powder": lw_savings.get("Powder", 0),
        "LW_ASC":    lw_savings.get("VR/ Specialty", 0),
        "LTL_TOTAL": ltl_total,
    }
    grand = sum(savings_dict.values())

    # -----------------------------------------------------------------------
    # STEP 6: Write outputs
    # -----------------------------------------------------------------------
    print("\n[5/6] Writing output files...")
    write_closing_tracker(out_tracker, savings_dict, MONTH_LABEL)
    write_ops_tracker(out_ops, savings_dict, MONTH_LABEL, eur_rate)
    write_procurement_tracker(out_proc, tl_savings, ltl_savings, MONTH_LABEL, eur_rate)

    # -----------------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------------
    print("\n[6/6] Summary")

    # TL comparison table (always shown when bid file loaded)
    if bid_rate_map:
        BU_DIRS = [
            ("MPY",    "OB"), ("MPY",    "IP"),
            ("ASC",    "OB"), ("ASC",    "IP"),
            ("ICO",    "OB"), ("ICO",    "IP"),
            ("Powder", "OB"), ("Powder", "IP"),
        ]
        print("\n  TL Bid Savings Comparison:")
        print(f"  {'BU/Direction':<18} {'TMS Base':>12} {'Bid File':>12} {'Diff':>12}")
        print("  " + "-" * 56)
        for bu, d in BU_DIRS:
            tms_val = tl_savings_tms.get((bu, d), 0)
            bid_val = tl_savings_bid.get((bu, d), 0)
            diff    = bid_val - tms_val
            if tms_val == 0 and bid_val == 0:
                continue
            print(f"  {bu+' '+d:<18} ${tms_val:>10,.0f}  ${bid_val:>10,.0f}  ${diff:>+10,.0f}")
        print("  " + "-" * 56)
        print(f"  {'TOTAL TL':<18} ${tl_total_tms:>10,.0f}  ${tl_total_bid:>10,.0f}  ${tl_total_bid-tl_total_tms:>+10,.0f}")
        print(f"\n  Output files use BID FILE version (PRIMARY awards only).\n")

    print("-" * 65)
    print(f"{'Category':<35} {'USD':>12} {'EUR':>12}")
    print("-" * 65)
    rows = [
        ("TL Bid Savings",    savings_dict["TL_TOTAL"]),
        ("Expedite MPY",      savings_dict["EXP_MPY"]),
        ("Expedite ASC",      savings_dict["EXP_ASC"]),
        ("Expedite Metal",    savings_dict["EXP_Metal"]),
        ("Expedite Wood",     savings_dict["EXP_Wood"]),
        ("LW TL-LTL MPY",    savings_dict["LW_MPY"]),
        ("LW TL-LTL Metal",  savings_dict["LW_Metal"]),
        ("LW TL-LTL Wood",   savings_dict["LW_Wood"]),
        ("LW TL-LTL Powder", savings_dict["LW_Powder"]),
        ("LW TL-LTL ASC",    savings_dict["LW_ASC"]),
        ("LTL RFP Savings",  savings_dict["LTL_TOTAL"]),
    ]
    for label, val in rows:
        print(f"  {label:<33} ${val:>10,.0f}  {val*eur_rate:>10,.0f}")
    print("-" * 65)
    print(f"  {'TOTAL':<33} ${grand:>10,.0f}  {grand*eur_rate:>10,.0f}")
    print("-" * 65)
    print("\nNOTE: STO and Payload savings - enter manually in closing tracker.")
    print(f"\nOutput: {NEW_MONTH_FOLDER}")
    print("Done.")


if __name__ == "__main__":
    main()
