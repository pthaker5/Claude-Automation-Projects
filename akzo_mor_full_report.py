"""
akzo_mor_full_report.py
=======================

Companion to akzo_mor_db_only.py.  Builds a slide-deck-style HTML report that
mirrors the Akzo MOR PowerPoint presentation.  Sections:

  1. Title + Today's Agenda
  2. Safety Moment            -- manual content (config YAML)
  3. On Time Carrier Performance    -- driven by akzo_mor_db_only.compute_super_adjusted
  4. Shipping Exceptions     -- driven by exclusion flags from compute_super_adjusted
  5. Operations Update       -- manual content (config YAML)
  6. Shipping Weight & Spend -- 712 data
  7. Carrier Tender Performance     -- 709 Tender Performance Detail hyper
  8. Claims & Complaints     -- Claims hyper
  9. Temperature Control     -- 712 filtered by Equipment / Service Type
 10. Expedite Tracking       -- 712 filtered by Service Type
 11. Conclusion + Appendix   -- manual content

Usage:
  python akzo_mor_full_report.py --report-month 2026-02 \
      --narrative narrative_2026-02.yaml \
      --tender-hyper tender_dashboard.hyper \
      --claims-hyper claims_dashboard.hyper

Anything the script can't auto-derive (RCAs, action plans, safety moment,
appendix market news) is loaded from the YAML so the user can write the
narrative once a month, drop it into the report folder, and re-run.
"""

from __future__ import annotations
import argparse
import base64
import io
import json
import os
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# =============================================================================
# 1. CONFIG / CONSTANTS
# =============================================================================
# Color palette extracted from the MOR deck
COLOR_NAVY = '#1B2541'       # dark slide-divider background
COLOR_NAVY_2 = '#23314F'     # secondary navy
COLOR_LIME = '#C5D52D'       # accent flag / underline
COLOR_LIME_DARK = '#9FB327'  # hover/border lime
COLOR_WHITE = '#FFFFFF'
COLOR_CREAM = '#F8F9FA'      # content area background
COLOR_TEXT = '#1F2A44'       # body text
COLOR_TEXT_LIGHT = '#5A6378'
COLOR_BORDER = '#D9DEE6'
COLOR_GOOD = '#27AE60'
COLOR_WARN = '#E67E22'
COLOR_BAD = '#C0392B'

# Chart palette -- matched to Tableau dashboard colors used in MOR deck
BU_COLORS = {
    'M & PC': '#7E4F8F',
    'MPY': '#A572B2',
    'MPC': '#7E4F8F',
    'Metal': '#F0A030',
    'METAL': '#F0A030',
    'POWDER': '#D9534F',
    'Powder': '#D9534F',
    'VR/Specialty': '#62B0A3',
    'VR/ Specialty': '#62B0A3',
    'VR / Specialty': '#62B0A3',
    'VR': '#62B0A3',
    'Vehicle Refinishes': '#62B0A3',
    'Wood': '#5DA571',
    'Wood Coatings': '#5DA571',
    'Marine and Protective Coatings': '#7E4F8F',
    'Metal Coatings': '#F0A030',
    'Powder Coatings': '#D9534F',
    # Non-canonical fallbacks so legend doesn't show duplicate teals
    'Not Provided': '#9AA5B8',         # neutral cool gray, distinct from VR teal
    'Unknown': '#9AA5B8',
    'Other': '#B8AEC9',
}
# Tableau-style softer status colors matching the MOR deck
STATUS_COLORS = {
    'Accepted': '#5DA571',           # muted green (matches deck + Tableau)
    'Declined': '#C0392B',           # deeper red (matches Tableau)
    'Expired': '#D08B9C',            # magenta/pink (matches Tableau's "Expired")
    'Rejected Carrier': '#E8C547',   # gold/yellow (matches Tableau's "Rejected by Carrier" -- the LARGE broadcast no-response segment)
    'Rejected Shipper': '#F47C3C',   # orange (matches Tableau's "Rejected by Shipper")
    'Shipper Cancelled': '#9C8159',  # brown (Tableau "Shipper Cancelled")
    'Withdrawn': '#5BB7A5',          # teal (Tableau labels this "In Progress" in some views)
    'In Progress': '#5BB7A5',        # alias
    'Late': '#E08885',               # softer red/pink (slide 6-9 OTP)
    'On Time': '#7AB8AC',            # soft teal-green (slide 6-9 OTP)
    'Justified': '#5A7AB5',
    'Unjustified': '#F0A030',
}

# On-time targets shown as a dashed reference line on the OTP/OTD performance
# slides (6-9).  Pickup slides use the OTP target, delivery slides the OTD one.
OTP_TARGET_PCT = 92.0
OTD_TARGET_PCT = 96.5
TARGET_LINE_COLOR = '#C00000'

# =============================================================================
# CARRIER EXCLUSIONS (Akzo request, 2026-06-22)
# Carriers that are local couriers or that Akzo works with directly are
# excluded from the Top Late Carriers dashboards/slides (10 & 11). The lists
# are mode-specific. Matching is case-insensitive and whitespace-normalized
# (handles SSRS/TMW name variants like 'Ryder' vs 'Ryder Integrated Logistics').
# Quikx applies to all modes per follow-up.
# =============================================================================
def _norm_carrier(name) -> str:
    """Normalize a carrier name for exclusion matching: lower, collapse spaces."""
    import re as _re
    return _re.sub(r'\s+', ' ', str(name).strip().lower())

CARRIER_EXCLUDE_ALL = {
    'quikx',
}
CARRIER_EXCLUDE_TL = {
    'gxo logistics supply chain',
    'chemlogix brokerage',
    'dominion warehousing & distribution',
    'ryder integrated logistics',
    'ryder',
    # Shuttle carriers -- excluded from the TL rejection-carrier ranking
    # (slide 25) per Poojan 2026-06-23. They run dedicated shuttle moves, not
    # routing-guide tenders, so their reject % is not comparable.
    'pioneer',
    'pioneer freight',
    'pioneer transport',
    'pioneer trucking',
    'pioneer logistics',
}
CARRIER_EXCLUDE_LTL = {
    'dominion warehousing & distribution',
    "atcheson's express",
    'fastrucking',
    'gladis transport llc',
    'gxo logistics supply chain',
    'h&m trucking ltd.',
    'h&m trucking ltd',
    'pioneer freight',
    'rolmar freight services',
    'wakely transportation',
}
# Pre-normalize so we don't recompute every call.
CARRIER_EXCLUDE_ALL = {_norm_carrier(c) for c in CARRIER_EXCLUDE_ALL}
CARRIER_EXCLUDE_TL = {_norm_carrier(c) for c in CARRIER_EXCLUDE_TL} | CARRIER_EXCLUDE_ALL
CARRIER_EXCLUDE_LTL = {_norm_carrier(c) for c in CARRIER_EXCLUDE_LTL} | CARRIER_EXCLUDE_ALL

def carrier_exclusions_for_mode(mode: str) -> set:
    """Return the normalized exclusion set for a given mode label."""
    m = str(mode).strip().lower()
    if m in ('ltl',):
        return CARRIER_EXCLUDE_LTL
    if m in ('truckload', 'tl'):
        return CARRIER_EXCLUDE_TL
    return CARRIER_EXCLUDE_ALL

# Market-average reference lines on slide 22 (Total Weight vs Average Weight).
# These are operational benchmarks Quantix uses, not data-derived.  Override at
# this module top if the underlying constants change.
MARKET_AVG_TL_LBS = 14500
MARKET_AVG_LTL_LBS = 3500

# Cost-per-KG conversion (slide 21).  The 712 'Normalized Weight' is in POUNDS
# and 'Normalized Ship't Actual Cost' is in USD, so the raw ratio is USD/lb.
# The Akzo KPI dashboard reports this as Cost per KG in EUR.  Conversion:
#     EUR/kg = (USD/lb) * LB_PER_KG * EUR_PER_USD
# Verified against the dashboard tooltip 2026-06-23: VR/Specialty May showed
# 0.1775 USD/lb -> 0.36 EUR/kg, which fixes EUR_PER_USD = 0.92.
LB_PER_KG = 2.20462
EUR_PER_USD = 0.92
USD_LB_TO_EUR_KG = LB_PER_KG * EUR_PER_USD  # multiply a USD/lb figure to get EUR/kg

# Canonical BU name normalization.  Applied to perf, 712, tender, AND claims so
# every chart/table sees the same set of BU labels and BU_COLORS hits cleanly.
# Without this, the tender BU table shows METAL + Metal as two rows, and the
# claims chart shows "Marine and Protective Coatings" with a different color
# than "M & PC" on slide 22.
BU_NORMALIZE = {
    'METAL': 'Metal', 'metal': 'Metal',
    'POWDER': 'Powder', 'powder': 'Powder', 'POWDER COATINGS': 'Powder',
    'MPY': 'M & PC', 'mpy': 'M & PC',
    'WOOD': 'Wood', 'wood': 'Wood', 'WOOD COATINGS': 'Wood',
    'VR': 'VR/Specialty', 'VR/SPECIALTY': 'VR/Specialty', 'VR/ Specialty': 'VR/Specialty',
    'VR / SPECIALTY': 'VR/Specialty', 'VEHICLE REFINISHES': 'VR/Specialty',
    # The claims SMU field has BOTH "Vehicle Refinishes" and "Specialty Coatings"
    # as separate values; the dashboard merges Specialty Coatings into the
    # VR/Specialty bucket (the legend shows 6 BUs, not 7).  Without this mapping
    # the report renders a spurious 7th "Specialty Coatings" series.
    'SPECIALTY COATINGS': 'VR/Specialty', 'SPECIALTY': 'VR/Specialty',
    'M&PC': 'M & PC', 'MPC': 'M & PC', 'M & PC': 'M & PC',
    'MARINE AND PROTECTIVE COATINGS': 'M & PC',
    'METAL COATINGS': 'Metal',
    'NOT PROVIDED': 'Not Provided',
    'NONE': 'Not Provided', 'NULL': 'Not Provided', '': 'Not Provided',
}
def normalize_bu(v):
    """Map any raw BU value (uppercase, SMU long-form, mis-spaced, NaN) to the
    canonical name used throughout the report."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 'Not Provided'
    s = str(v).strip()
    if not s:
        return 'Not Provided'
    return BU_NORMALIZE.get(s.upper(), BU_NORMALIZE.get(s, s))

# =============================================================================
# 2. IMPORT THE PERFORMANCE SCRIPT
# =============================================================================
def _import_perf_module() -> 'module':
    """Locate and import the akzo_mor_db_only.py module."""
    candidates = [
        Path(__file__).with_name('akzo_mor_db_only.py'),
        Path.cwd() / 'akzo_mor_db_only.py',
    ]
    for p in candidates:
        if p.exists():
            spec = importlib.util.spec_from_file_location('akzo_mor_db_only', str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(
        'akzo_mor_db_only.py not found.  Place it alongside akzo_mor_full_report.py.'
    )

# =============================================================================
# 3. DATA LOADERS FOR THE NEW SOURCES
# =============================================================================
def load_tender_data(hyper_path: str) -> pd.DataFrame:
    """Load CL709 Tender Performance Detail from a Tender Dashboard hyper extract.

    Returns DataFrame with: Tender Date, Carrier Name, Carrier SCAC, SID,
    Tender Type, Tender Status, Accepted, Declined, Expired, Withdrawn,
    Rejected Carrier (int flags), plus derived 'YYYY_MM' for grouping.
    """
    import pantab
    print(f'Loading Tender hyper: {hyper_path}', flush=True)
    frames = pantab.frames_from_hyper(hyper_path)
    df_tender = None
    for k, v in frames.items():
        name = k[1] if isinstance(k, tuple) else str(k)
        if 'CL709' in str(name) or 'Tender Performance' in str(name):
            df_tender = v.copy()
            break
    if df_tender is None:
        # fallback: take the largest table
        df_tender = max(frames.values(), key=len).copy()
    df_tender['Tender Date'] = pd.to_datetime(df_tender['Tender Date'], errors='coerce')
    df_tender['YYYY_MM'] = df_tender['Tender Date'].dt.strftime('%Y-%m')
    for c in ['Accepted', 'Declined', 'Expired', 'Withdrawn', 'Rejected Carrier']:
        if c in df_tender.columns:
            df_tender[c] = pd.to_numeric(df_tender[c], errors='coerce').fillna(0).astype(int)
    print(f'  Tender rows: {len(df_tender):,}', flush=True)
    return df_tender


def normalize_tender_sql(df_tender: pd.DataFrame) -> pd.DataFrame:
    """Normalize a CL709 SQL pull to match the shape that downstream chart helpers expect.

    Same output schema as load_tender_data(): Tender Date, Carrier Name, Carrier SCAC,
    SID, Tender Type, Tender Status, integer status flags (Accepted, Declined, ...),
    plus derived YYYY_MM.
    """
    df = df_tender.copy()
    df['Tender Date'] = pd.to_datetime(df['Tender Date'], errors='coerce')
    df['YYYY_MM'] = df['Tender Date'].dt.strftime('%Y-%m')
    for c in ['Accepted', 'Declined', 'Expired', 'Withdrawn',
              'Rejected Carrier', 'Rejected Shipper', 'Shipper Cancelled']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
    # SID is varchar-padded with leading zeros in CL709 (e.g. "0001045812")
    if 'SID' in df.columns:
        df['SID'] = df['SID'].astype(str).str.strip()
    # Strip trailing spaces from all string columns -- SQL varchar fields have
    # trailing spaces (e.g. 'Withdrawn ' not 'Withdrawn', 'Accepted ' not 'Accepted').
    for c in ['Tender Status', 'Tender Type', 'Carrier Name', 'Carrier SCAC']:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    return df


def load_claims_data(hyper_path: str) -> pd.DataFrame:
    """Load Claims & Complaints from a .hyper extract or .twbx packaged workbook.

    Accepts either a bare .hyper file or a .twbx (Tableau packaged workbook).
    For .twbx, the .hyper extract is unpacked from the ZIP into a temp file.

    Pre-computed Reported YY-MM Open column is used for monthly bucketing
    (the raw Reported Date column is stored as Excel serial -- the dashboard
    derives the YY-MM upstream).
    """
    import zipfile, tempfile, os, shutil, re

    lower = hyper_path.lower()
    # CSV / Excel export path: no Hyper engine needed.  This is the fallback
    # for machines where IT group policy blocks pantab's bundled hyperd.exe
    # ("This program is blocked by group policy") -- export the claims data
    # from the Tableau dashboard to CSV/XLSX and pass that file instead.
    if lower.endswith(('.csv', '.xlsx', '.xls')):
        print(f'Loading Claims export (no Hyper engine needed): {hyper_path}', flush=True)
        if lower.endswith('.csv'):
            try:
                df_claims = pd.read_csv(hyper_path)
                if df_claims.shape[1] <= 1:
                    # Tableau "Download Crosstab" CSVs are UTF-16 + tab-separated
                    df_claims = pd.read_csv(hyper_path, encoding='utf-16', sep='\t')
            except UnicodeDecodeError:
                df_claims = pd.read_csv(hyper_path, encoding='utf-16', sep='\t')
        else:
            df_claims = pd.read_excel(hyper_path)
    else:
        import pantab

        load_path = hyper_path
        tmp_dir = None

        if lower.endswith('.twbx'):
            print(f'Unpacking .twbx: {hyper_path}', flush=True)
            with zipfile.ZipFile(hyper_path) as z:
                hyper_names = [n for n in z.namelist() if n.endswith('.hyper')]
                if not hyper_names:
                    raise ValueError(f'No .hyper file found inside {hyper_path}')
                # Use the largest hyper if there are multiple
                hyper_name = max(hyper_names, key=lambda n: z.getinfo(n).file_size)
                tmp_dir = tempfile.mkdtemp()
                load_path = os.path.join(tmp_dir, 'extract.hyper')
                with z.open(hyper_name) as src, open(load_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                print(f'  Extracted: {hyper_name} ({os.path.getsize(load_path):,} bytes)', flush=True)

        print(f'Loading Claims hyper: {load_path}', flush=True)
        try:
            frames = pantab.frames_from_hyper(load_path)
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        df_claims = list(frames.values())[0].copy()
    print(f'  Claims columns: {list(df_claims.columns)[:25]}', flush=True)
    # Normalize the month value to 'YYYY-MM'.  The hyper extract has '2026-1',
    # but CSV/XLSX exports come in many shapes -- 'Jul-26', 'July 2026',
    # '26-Jul', '7/2026', real datetimes -- and an unrecognized format left
    # YYYY_MM unmatched, which rendered the claims slides completely empty.
    _MON = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

    def _norm_ymm(s):
        if pd.isna(s):
            return ''
        if isinstance(s, (pd.Timestamp, datetime)):
            return f'{s.year:04d}-{s.month:02d}'
        raw = str(s).strip()
        if not raw:
            return ''
        def _year(y):
            y = int(y)
            return y + 2000 if y < 100 else y
        parts = re.split(r'[-/\s]+', raw)
        if len(parts) == 2:
            a, b = parts
            if a.isdigit() and b.isdigit():
                ai, bi = int(a), int(b)
                if 1 <= bi <= 12:                    # '2026-7', '26-07'
                    return f'{_year(ai):04d}-{bi:02d}'
                if 1 <= ai <= 12:                    # '7/2026'
                    return f'{_year(bi):04d}-{ai:02d}'
            if a[:3].lower() in _MON and b.isdigit():    # 'Jul-26', 'July 2026'
                return f'{_year(int(b)):04d}-{_MON[a[:3].lower()]:02d}'
            if b[:3].lower() in _MON and a.isdigit():    # '26-Jul'
                return f'{_year(int(a)):04d}-{_MON[b[:3].lower()]:02d}'
        dt = pd.to_datetime(raw, errors='coerce')
        if pd.notna(dt):
            return f'{dt.year:04d}-{dt.month:02d}'
        return raw  # unparseable: pass through so it shows in the months-present print
    # Prefer the dashboard's precomputed month column, but fall back to deriving
    # it from any reported-date column if that exact name isn't present -- the
    # claims extract's column names vary, and a hard KeyError here would zero
    # out the entire claims section silently.
    ymm_col = next((c for c in [
        'Reported YY-MM Open', 'Reported YY-MM', 'YY-MM Open', 'Reported Month',
    ] if c in df_claims.columns), None)
    if ymm_col is not None:
        df_claims['YYYY_MM'] = df_claims[ymm_col].apply(_norm_ymm)
    else:
        date_col = next((c for c in df_claims.columns
                         if 'report' in c.lower() and 'date' in c.lower()), None)
        if date_col is None:
            date_col = next((c for c in df_claims.columns if 'date' in c.lower()), None)
        if date_col is not None:
            dt = pd.to_datetime(df_claims[date_col], errors='coerce', unit='D', origin='1899-12-30') \
                 if pd.api.types.is_numeric_dtype(df_claims[date_col]) \
                 else pd.to_datetime(df_claims[date_col], errors='coerce')
            df_claims['YYYY_MM'] = dt.dt.strftime('%Y-%m').fillna('')
            print(f'  (derived YYYY_MM from "{date_col}")', flush=True)
        else:
            df_claims['YYYY_MM'] = ''
            print('  WARN: no month/date column found in claims extract; '
                  'claims charts will be empty.', flush=True)
    # BU normalization: SMU column has full names, alias to short names
    BU_ALIAS = {
        'Marine and Protective Coatings': 'M & PC',
        'Vehicle Refinishes': 'VR/Specialty',
        'Wood Coatings': 'Wood',
        'Powder Coatings': 'Powder',
        'Metal Coatings': 'Metal',
    }
    if 'SMU' in df_claims.columns:
        df_claims['BU'] = df_claims['SMU'].map(BU_ALIAS).fillna(df_claims['SMU'])
    elif 'BU' not in df_claims.columns:
        df_claims['BU'] = 'Not Provided'
    # Numeric columns
    for c in ['Total Claim Value', 'Paid Amount', 'Check to Akzo Amount']:
        if c in df_claims.columns:
            df_claims[c] = pd.to_numeric(df_claims[c], errors='coerce').fillna(0)
    # Boolean flags (use object dtype to dodge pyarrow NA issues)
    if 'Justified?' in df_claims.columns:
        df_claims['Is_Justified'] = (df_claims['Justified?'].astype(str) == 'Justified').astype(int)
    else:
        df_claims['Is_Justified'] = 0
    if 'Formal Complaint? Y/N 1/0' in df_claims.columns:
        df_claims['Is_Complaint'] = pd.to_numeric(df_claims['Formal Complaint? Y/N 1/0'], errors='coerce').fillna(0).astype(int)
    else:
        df_claims['Is_Complaint'] = 0
    print(f'  Claims rows: {len(df_claims):,}', flush=True)
    _months = sorted(m for m in df_claims['YYYY_MM'].dropna().unique() if m)
    print(f'  Claims months present: {_months}', flush=True)
    print('  (If a report month is missing here, the claims extract has no rows '
          'for it -- the chart will be empty for that month.)', flush=True)
    return df_claims

# =============================================================================
# 4. CHART HELPERS (matplotlib -> base64 PNG embedded inline in HTML)
# =============================================================================
def _setup_matplotlib():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Calibri', 'DejaVu Sans', 'Arial']
    plt.rcParams['axes.edgecolor'] = COLOR_BORDER
    plt.rcParams['axes.labelcolor'] = COLOR_TEXT
    plt.rcParams['xtick.color'] = COLOR_TEXT_LIGHT
    plt.rcParams['ytick.color'] = COLOR_TEXT_LIGHT
    plt.rcParams['axes.titlecolor'] = COLOR_TEXT
    return plt


def fig_to_data_uri(fig, dpi: int = 110) -> str:
    """Convert a matplotlib Figure into a data: URI for inline HTML embedding."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight', facecolor='white')
    import matplotlib.pyplot as plt
    plt.close(fig)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def _otp_label_pct(df_perf: pd.DataFrame, ym_list: List[str], mode: str, side: str) -> Dict[str, float]:
    """The on-time % LABEL shown on BOTH the count and cost charts of the Akzo
    Performance dashboard.

    Verified from the .twbx: every OTP/OTD worksheet (PU, PU 2, Delivery count,
    Delivery cost) labels with the SAME measure --
        pcto( SUM( {FIXED [Key ShipperSID]: MAX([Normalized Ship't Actual Cost])} ) )
    partitioned by the on-time/late colour.  i.e. a COST-weighted on-time share,
    cost taken once per Key ShipperSID via MAX, split by Super Adj late.

    Because the label is identical on both charts, the left (count) and right
    (cost) charts MUST display the same percentage -- only the bar heights differ
    (shipment count vs cost dollars).  Returns {YYYY_MM: on_time_pct}.

    Filters mirror each side's worksheet: delivery applies Remove Insufficient TT
    for Del = 0; pickup applies none beyond BU+Mode (the OLT/past-due filters are
    redundant with Super Adjusted and live only on a cost variant we don't mirror).
    """
    late_col = 'SA_PU_Late' if side == 'PU' else 'SA_Del_Late'
    cost_col = "Normalized Ship't Actual Cost"
    sub = df_perf[(df_perf['Mode'] == mode) & (df_perf['YYYY_MM'].isin(ym_list))].copy()
    if side != 'PU' and 'Remove_Insuff_TT_Del' in sub.columns:
        v = pd.to_numeric(sub['Remove_Insuff_TT_Del'], errors='coerce')
        sub = sub[v.isna() | (v == 0)].copy()
    key_col = 'Key ShipperSID' if 'Key ShipperSID' in sub.columns else 'SID'
    out = {}
    if cost_col not in sub.columns:
        return out
    for ym in ym_list:
        d = sub[sub['YYYY_MM'] == ym]
        if len(d) == 0:
            continue
        per = d.groupby(key_col).agg(cost=(cost_col, 'max'), late=(late_col, 'max'))
        ot = per.loc[per['late'] == 0, 'cost'].sum()
        tot = per['cost'].sum()
        out[ym] = (ot / tot * 100) if tot > 0 else 0.0
    return out


def chart_late_vs_ontime(df_perf: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                         mode: str, side: str = 'PU') -> str:
    """Stacked-bar OnTime vs Late shipment count over three months, with % labels.

    `side` selects pickup ('PU') or delivery ('Del') flag columns.
    Mirrors the top-left chart on MOR slides 6/7 (PU) and 8/9 (Del).
    """
    plt = _setup_matplotlib()
    sub = df_perf[(df_perf['Mode'] == mode) & (df_perf['YYYY_MM'].isin(ym_list))].copy()
    # Match the dashboard COUNT worksheets exactly (PU 2 / Late vs On Time SID
    # Count - Delivery).  Pickup count: BU+Mode only, COUNTD(Key ShipperSID).
    # Delivery count: + Remove Insufficient TT for Del = 0, COUNTD(SID).
    def _keep_0_null(frame, col):
        if col not in frame.columns:
            return frame
        v = pd.to_numeric(frame[col], errors='coerce')
        return frame[v.isna() | (v == 0)]
    if side == 'PU':
        late_col = 'SA_PU_Late'
        count_key = 'Key ShipperSID' if 'Key ShipperSID' in sub.columns else 'SID'
        # NO OLT / past-due filters on the count chart (those are cost-only).
        title = 'Late vs On Time Shipment Count'
    else:
        late_col = 'SA_Del_Late'
        count_key = 'SID'
        sub = _keep_0_null(sub, 'Remove_Insuff_TT_Del')
        title = 'Late vs On Time Shipment Count'

    grp = sub.groupby('YYYY_MM').apply(
        lambda g: pd.Series({
            'on_time': g[g[late_col] == 0][count_key].nunique(),
            'late': g[g[late_col] == 1][count_key].nunique(),
        })
    ).reindex(ym_list).fillna(0)

    # The % LABEL is the dashboard's cost-weighted on-time share (identical on
    # the count and cost charts), NOT the count ratio.  Bars show counts; label
    # shows the cost-weighted %.  This is what makes the side-by-side charts agree.
    label_pct = _otp_label_pct(df_perf, ym_list, mode, side)

    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    ax.bar(x, grp['on_time'], bar_w, color=STATUS_COLORS['On Time'], label='On Time')
    ax.bar(x, grp['late'], bar_w, bottom=grp['on_time'], color=STATUS_COLORS['Late'], label='Late')
    totals = grp['on_time'] + grp['late']
    for i, ym in enumerate(ym_list):
        ot = grp['on_time'].iloc[i]
        if (ot + grp['late'].iloc[i]) > 0 and ym in label_pct:
            ax.text(i, ot / 2, f'{label_pct[ym]:.2f}%', ha='center', va='center',
                    color='white', fontsize=13, fontweight='bold')
    # Dashed per-bar target markers (OTP target on pickup, OTD on delivery).
    # Each month's marker sits at target% of THAT month's total bar height, so
    # the green on-time segment reaching the marker means the month is on
    # target.  (A single flat line on a hidden 0-100% axis floated above the
    # shorter bars and read as "under target" even when the labels beat it.)
    target = OTP_TARGET_PCT if side == 'PU' else OTD_TARGET_PCT
    half_w = bar_w / 2 * 1.35
    for i in range(len(ym_list)):
        tot = totals.iloc[i]
        if tot > 0:
            ax.plot([x[i] - half_w, x[i] + half_w], [tot * target / 100.0] * 2,
                    color=TARGET_LINE_COLOR, linestyle=(0, (4, 2)), linewidth=1.8,
                    zorder=5, solid_capstyle='butt')
    ax.set_xticks(x)
    ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.set_ylabel('Shipment Count', fontsize=11, color=COLOR_TEXT_LIGHT)
    ax.set_title(title, fontsize=13, color=COLOR_TEXT)
    handles, leg_labels = ax.get_legend_handles_labels()
    handles.append(plt.matplotlib.lines.Line2D([], [], color=TARGET_LINE_COLOR,
                                               linestyle=(0, (4, 2)), linewidth=1.8))
    leg_labels.append(f'Target {target:g}%')
    ax.legend(handles, leg_labels, loc='upper center', bbox_to_anchor=(0.5, -0.12),
              ncol=3, fontsize=11, frameon=False)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.tick_params(axis='y', labelsize=8)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_cost_late_overlay(df_perf: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                            mode: str, side: str = 'PU') -> str:
    """Cost (stacked: late-cost vs on-time-cost) + Load Count line.  4th cell of slides 6-9.

    Line represents total shipment count per month (Load Count) -- matches the deck's
    convention of showing volume trend alongside the cost split.
    """
    plt = _setup_matplotlib()
    sub = df_perf[(df_perf['Mode'] == mode) & (df_perf['YYYY_MM'].isin(ym_list))].copy()
    # Filter policy (verified against MAF data):
    #   Pickup: the OLT LTL/TL + Past Due filters are 100% redundant with Super
    #     Adjusted -- every row they remove is already SA_PU_Late=0 (on-time),
    #     so filtering them just double-handles on-time rows.  REMOVED.
    #   Delivery: Remove Insufficient TT for Del is NOT redundant -- it removes
    #     869 rows that are still SA_Del_Late=1 (impossible transit time, which
    #     SA does not convert because TT_Met=0).  KEPT.
    def _keep_0_null(frame, col):
        if col not in frame.columns:
            return frame
        v = pd.to_numeric(frame[col], errors='coerce')
        return frame[v.isna() | (v == 0)]
    if side != 'PU':
        sub = _keep_0_null(sub, 'Remove_Insuff_TT_Del')
    if "Normalized Ship't Actual Cost" not in sub.columns or len(sub) == 0:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.text(0.5, 0.5, '(no cost data)', ha='center', va='center', color=COLOR_TEXT_LIGHT)
        ax.axis('off')
        return fig_to_data_uri(fig)
    late_col = 'SA_PU_Late' if side == 'PU' else 'SA_Del_Late'
    # The bars show cost split on-time vs late.  The % LABEL matches the Akzo
    # dashboard's cost worksheet: a COST-WEIGHTED on-time share, i.e. on-time $
    # / total $, where each shipment's cost is taken once per Key ShipperSID via
    # MAX (FIXED [Key ShipperSID]: MAX([Normalized Ship't Actual Cost])).  This
    # is deliberately DIFFERENT from the left count chart's COUNTD(SID) % -- on
    # the dashboard the two charts show different numbers because one is
    # count-weighted and the other cost-weighted.
    cost_col = "Normalized Ship't Actual Cost"
    key_col = 'Key ShipperSID' if 'Key ShipperSID' in sub.columns else 'SID'

    def _cost_split(d):
        # One cost per Key ShipperSID (MAX), with that shipper's late status.
        per = d.groupby(key_col).agg(
            cost=(cost_col, 'max'),
            late=(late_col, 'max'),
        )
        ot_cost = per.loc[per['late'] == 0, 'cost'].sum()
        late_cost = per.loc[per['late'] == 1, 'cost'].sum()
        return pd.Series({
            'cost_ot': ot_cost,
            'cost_late': late_cost,
            'load_count': d[key_col].nunique(),
        })

    grp = sub.groupby('YYYY_MM').apply(_cost_split).reindex(ym_list).fillna(0)

    # Use the SHARED label helper so the cost chart's % is byte-identical to the
    # count chart's % (both are the dashboard's cost-weighted on-time share).
    label_pct = _otp_label_pct(df_perf, ym_list, mode, side)

    fig, ax1 = plt.subplots(figsize=(6.0, 3.6))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    ax1.bar(x, grp['cost_ot'], bar_w, color=STATUS_COLORS['On Time'], label='On Time $')
    ax1.bar(x, grp['cost_late'], bar_w, bottom=grp['cost_ot'], color=STATUS_COLORS['Late'], label='Late $')
    # COST-weighted percent label -- identical to the count chart's label.
    for i, ym in enumerate(ym_list):
        cot = grp['cost_ot'].iloc[i]
        if (cot + grp['cost_late'].iloc[i]) > 0 and ym in label_pct:
            ax1.text(i, cot / 2, f'{label_pct[ym]:.2f}%', ha='center', va='center',
                     color='white', fontsize=13, fontweight='bold')
    ax2 = ax1.twinx()
    ax2.plot(x, grp['load_count'], color=COLOR_TEXT, marker='o', linewidth=2,
             markersize=6, label='Load Count')
    # Annotate each point with its load count value
    for i, lc in enumerate(grp['load_count']):
        if lc > 0:
            ax2.annotate(f'{int(lc):,}', xy=(i, lc), xytext=(0, 8),
                         textcoords='offset points', ha='center', fontsize=11,
                         color=COLOR_TEXT, fontweight='bold')
    ax2.set_ylabel('Load Count', fontsize=11, color=COLOR_TEXT_LIGHT)
    # Widen avg axis so line doesn't smash into chart edges
    lc_max = grp['load_count'].max()
    if lc_max > 0:
        ax2.set_ylim(0, lc_max * 1.3)
    ax1.set_xticks(x)
    ax1.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax1.set_ylabel("Total Shipment Cost", fontsize=11, color=COLOR_TEXT_LIGHT)
    side_label = 'Pickup' if side == 'PU' else 'Delivery'
    ax1.set_title(f'Costs Late vs On Time {side_label}', fontsize=13, color=COLOR_TEXT)
    ax1.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(
        lambda v, _: f'${v/1e6:.1f}M' if v >= 1e6 else (f'${v/1e3:.0f}K' if v >= 1e3 else f'${v:.0f}')))
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc='upper center', bbox_to_anchor=(0.5, -0.12),
               ncol=3, fontsize=11, frameon=False)
    ax1.spines['top'].set_visible(False); ax2.spines['top'].set_visible(False)
    ax1.tick_params(axis='y', labelsize=8); ax2.tick_params(axis='y', labelsize=8)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def _render_bu_pie(grp: pd.Series, title: str, value_fmt) -> str:
    """Shared pie renderer for cost / weight by BU.

    - % shown INSIDE each slice (autopct), bold white text -- no overlap.
    - Full BU name + dollar/weight value shown in a side LEGEND (right of the
      pie) so labels never collide outside the slice.
    - Small slices (<3% of total) get their % label suppressed in-slice to
      avoid the cramped text problem; their value is still in the legend.
    """
    plt = _setup_matplotlib()
    colors = [BU_COLORS.get(b, '#7AAFB5') for b in grp.index]
    total = grp.sum()
    # 5.8x4.2 gives room for the side legend without forcing the pie circle small
    fig, ax = plt.subplots(figsize=(5.8, 4.2))
    # autopct returns '' for tiny slices to suppress crowded labels
    def _autopct(pct):
        return f'{pct:.1f}%' if pct >= 3.0 else ''
    wedges, texts, autotexts = ax.pie(
        grp.values, colors=colors, startangle=90,
        autopct=_autopct, pctdistance=0.72,
        textprops={'fontsize': 11, 'color': 'white', 'weight': 'bold'},
        wedgeprops={'edgecolor': 'white', 'linewidth': 1.2},
    )
    # autopct text -> white bold for readability on colored slices
    for t in autotexts:
        t.set_color('white')
        t.set_fontweight('bold')
        t.set_fontsize(11)

    # Build legend entries: "BU -- $123K (24.5%)"
    legend_labels = []
    for bu, val in zip(grp.index, grp.values):
        pct = val / total * 100 if total > 0 else 0
        legend_labels.append(f'{bu} - {value_fmt(val)} ({pct:.1f}%)')
    ax.legend(wedges, legend_labels, loc='center left',
              bbox_to_anchor=(1.0, 0.5), fontsize=10, frameon=False,
              borderaxespad=0.5)

    ax.set_title(title, fontsize=12, color=COLOR_TEXT, weight='bold', pad=8)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_cost_pie_by_bu(df_712: pd.DataFrame, ym: str, mode: Optional[str] = None) -> str:
    """Pie chart of total cost by BU for a given month.  Slide 6/7/8/9 bottom-left.

    `mode` filters to a single Mode (LTL / Truckload).  See _render_bu_pie for
    the labeling strategy (% inside slices, BU name + $ value in side legend).
    """
    plt = _setup_matplotlib()
    sub = df_712[(df_712.get('YYYY_MM') == ym) & (df_712.get('IB_OB') == 'OB')].copy()
    if mode is not None and 'Mode' in sub.columns:
        sub = sub[sub['Mode'] == mode]
    if 'BU' not in sub.columns or len(sub) == 0:
        fig, ax = plt.subplots(figsize=(5.8, 4.2))
        ax.text(0.5, 0.5, '(no data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    grp = sub.groupby('BU')["Normalized Ship't Actual Cost"].sum().sort_values(ascending=False)
    grp = grp[grp > 0]
    grp = grp[grp.index != 'Not Provided']
    if len(grp) == 0:
        fig, ax = plt.subplots(figsize=(5.8, 4.2))
        ax.text(0.5, 0.5, '(no data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    total = grp.sum()
    title_mode = f' - {mode}' if mode else ''
    title = f'Total Cost{title_mode} (${total/1e6:.2f}M)'
    return _render_bu_pie(grp, title, lambda v: f'${v/1000:,.0f}K')


def chart_weight_pie_by_bu(df_712: pd.DataFrame, ym: str, mode: Optional[str] = None) -> str:
    """Pie chart of total weight by BU for a given month.  Slide 6/7/8/9 bottom-right.

    `mode` filters to a single Mode (LTL / Truckload).
    """
    plt = _setup_matplotlib()
    sub = df_712[(df_712.get('YYYY_MM') == ym) & (df_712.get('IB_OB') == 'OB')].copy()
    if mode is not None and 'Mode' in sub.columns:
        sub = sub[sub['Mode'] == mode]
    if 'BU' not in sub.columns or len(sub) == 0:
        fig, ax = plt.subplots(figsize=(5.8, 4.2))
        ax.text(0.5, 0.5, '(no data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    grp = sub.groupby('BU')['Normalized Weight'].sum().sort_values(ascending=False)
    grp = grp[grp > 0]
    grp = grp[grp.index != 'Not Provided']
    if len(grp) == 0:
        fig, ax = plt.subplots(figsize=(5.8, 4.2))
        ax.text(0.5, 0.5, '(no data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    total = grp.sum()
    title_mode = f' - {mode}' if mode else ''
    weight_str = f'{total/1e6:.2f}M lb' if total >= 1e6 else f'{total/1e3:,.0f}K lb'
    title = f'Total Weight{title_mode} ({weight_str})'
    def _fmt_w(v):
        return f'{v/1e6:.2f}M lb' if v >= 1e6 else f'{v/1e3:,.0f}K lb'
    return _render_bu_pie(grp, title, _fmt_w)


def chart_cost_per_kg(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Cost-per-KG (EUR) line chart by BU across three months.  Slide 21 left chart.

    The 712 'Normalized Weight' is in POUNDS and 'Normalized Ship't Actual Cost'
    is in USD, so the raw ratio is USD/lb.  To match the Akzo KPI dashboard's
    'Cost per KG' view (reported in EUR) we convert:
        EUR/kg = (USD/lb) * LB_PER_KG * EUR_PER_USD
    (Poojan 2026-06-23: convert CPP -> Cost per KG to match Tableau.)
    """
    plt = _setup_matplotlib()
    # OUTBOUND ONLY.  The earlier "all movement types" reading of the dashboard's
    # empty Movement Type filter was WRONG -- it pulled in inbound/interplant rows
    # that distorted the per-BU cost/weight ratios (VR/Specialty crashed from
    # 0.25 to 0.16 instead of holding ~0.23 like the dashboard).  The working
    # version filtered IB_OB == 'OB' and matched the dashboard's "Rate per KG
    # Graph" shape (top line stays dominant), so we restore that.
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    for pc in ['Priority', 'Priority (group)', 'Weight brackets', 'Expedite']:
        if pc in sub.columns:
            sub = sub[~sub[pc].astype(str).str.upper().str.contains('EXPEDITE', na=False)]
            break
    if 'BU' in sub.columns:
        sub = sub[sub['BU'].notna() & (sub['BU'].astype(str).str.strip() != '')]
        # Per Akzo review (2026-07): leave Not Provided BU off this slide.
        # (normalize_bu maps blanks/nulls to the literal 'Not Provided'.)
        sub = sub[sub['BU'] != 'Not Provided']
    if 'BU' not in sub.columns or len(sub) == 0:
        # Never emit a broken <img>; show a labelled placeholder instead.
        fig, ax = plt.subplots(figsize=(6.0, 3.5))
        ax.text(0.5, 0.5, '(no cost-per-kg data)', ha='center', va='center', color=COLOR_TEXT_LIGHT)
        ax.axis('off')
        return fig_to_data_uri(fig)
    grp = sub.groupby(['YYYY_MM', 'BU']).agg(
        cost=("Normalized Ship't Actual Cost", 'sum'),
        weight=('Normalized Weight', 'sum'),
    ).reset_index()
    grp = grp[grp['weight'] > 0]
    # USD/lb -> EUR/kg to match the dashboard's Cost per KG view.
    grp['cpkg'] = (grp['cost'] / grp['weight']) * USD_LB_TO_EUR_KG
    fig, ax = plt.subplots(figsize=(6.0, 3.5))
    for bu, g in grp.groupby('BU'):
        g = g.set_index('YYYY_MM').reindex(ym_list)
        ax.plot(range(len(ym_list)), g['cpkg'], marker='o',
                color=BU_COLORS.get(bu, '#7AAFB5'), label=bu, linewidth=2)
    ax.set_xticks(range(len(ym_list)))
    ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.set_ylabel('Cost per KG (EUR)', fontsize=12)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(
        lambda v, _: f'\u20ac{v:.2f}'))
    ax.set_title('Cost per KG (EUR) by BU', fontsize=13, color=COLOR_TEXT)
    ax.legend(fontsize=11, loc='best', frameon=False)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    return fig_to_data_uri(fig)


def _prep_weight_frame(df: pd.DataFrame, ym_list: List[str]) -> pd.DataFrame:
    """Per-Key-ShipperSID weight, matching the KPI dashboard's
    'Total vs Avg Weight' worksheet (verified from Akzo KPI Dashboard.twbx):

        weight  = {FIXED [Key ShipperSID]: MAX([Normalized Weight])}
        split   = Transport Mode (== our 'Mode', which is mapped from it)
        moves   = ALL (Inbound + Interplant + Outbound)  -- NOT outbound-only
        exclude = expedite shipments (Priority/Weight-bracket = EXPEDITE)

    Returns one row per Key ShipperSID with columns [Key ShipperSID, YYYY_MM,
    Mode, weight].  Caller aggregates (SUM for totals, MEAN for average weight).
    """
    sub = df[df['YYYY_MM'].isin(ym_list)].copy()
    sub = sub[sub['Mode'].isin(['LTL', 'Truckload'])]
    # Exclude expedites if a priority/expedite flag is present.
    for pc in ['Priority', 'Priority (group)', 'Weight brackets', 'Expedite']:
        if pc in sub.columns:
            sub = sub[~sub[pc].astype(str).str.upper().str.contains('EXPEDITE', na=False)]
            break
    if len(sub) == 0:
        return pd.DataFrame(columns=['Key ShipperSID', 'YYYY_MM', 'Mode', 'weight'])
    key = 'Key ShipperSID' if 'Key ShipperSID' in sub.columns else 'SID'
    sub['Normalized Weight'] = pd.to_numeric(sub['Normalized Weight'], errors='coerce')
    # One weight per Key ShipperSID via MAX, carrying its month + mode.
    per = (sub.groupby([key, 'YYYY_MM', 'Mode'], as_index=False)['Normalized Weight']
           .max().rename(columns={'Normalized Weight': 'weight'}))
    return per


def chart_weight_by_mode(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Slide 21 right chart: Total Weight stacked by Mode (LTL/Truckload) across
    the 3-month window with per-segment percentage labels.  Simpler than slide 22's
    chart -- no secondary axis, no market-avg reference lines.  Pairs with the
    Cost per Pound (CPP) line chart on the left of slide 21.
    """
    plt = _setup_matplotlib()
    per = _prep_weight_frame(df_712, ym_list)
    if len(per) == 0:
        return ''
    grp = per.groupby(['YYYY_MM', 'Mode'])['weight'].sum().unstack(fill_value=0)
    grp = grp.reindex(ym_list).fillna(0)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    ltl_vals = grp.get('LTL', pd.Series([0]*len(ym_list), index=ym_list)).values
    tl_vals  = grp.get('Truckload', pd.Series([0]*len(ym_list), index=ym_list)).values
    ax.bar(x, ltl_vals, bar_w, color='#5DADE2', label='LTL')
    ax.bar(x, tl_vals, bar_w, bottom=ltl_vals, color='#F0A030', label='Truckload')
    # Percent labels
    totals = ltl_vals + tl_vals
    for i, tot in enumerate(totals):
        if tot <= 0: continue
        ltl_pct = ltl_vals[i] / tot * 100
        tl_pct  = tl_vals[i]  / tot * 100
        if ltl_vals[i] > 0:
            ax.text(i, ltl_vals[i] / 2, f'{ltl_pct:.1f}%',
                    ha='center', va='center', color='white', fontsize=12, fontweight='bold')
        if tl_vals[i] > 0:
            ax.text(i, ltl_vals[i] + tl_vals[i] / 2, f'{tl_pct:.1f}%',
                    ha='center', va='center', color='white', fontsize=12, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.tick_params(axis='y', labelsize=11)
    ax.set_ylabel('Total Weight (lbs)', fontsize=12)
    ax.set_title('Total Weight by Mode', fontsize=13, color=COLOR_TEXT, weight='bold')
    # Headroom so legend doesn't overlap the bars
    cur_top = (ltl_vals + tl_vals).max()
    if cur_top > 0:
        ax.set_ylim(0, cur_top * 1.18)
    ax.legend(fontsize=12, frameon=False, loc='upper right')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(
        lambda v, _: f'{v/1e6:.0f}M' if v >= 1e6 else f'{v/1e3:.0f}K'))
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_avg_weight_with_market(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Slide 22 right chart: Average weight per shipment by Mode with market avg
    reference lines.  This is the second of the slide-22 pair (Total Weight on
    left, Average Weight on right) -- previously combined into one chart with
    dual axes, which caused font/label overlap.
    """
    plt = _setup_matplotlib()
    per = _prep_weight_frame(df_712, ym_list)
    if len(per) == 0:
        return ''

    # Average weight per shipment = MEAN of the per-Key-ShipperSID weights.
    grp_avg = per.groupby(['YYYY_MM', 'Mode'])['weight'].mean().unstack(fill_value=0)
    grp_avg = grp_avg.reindex(ym_list).fillna(0)

    avg_ltl = grp_avg.get('LTL', pd.Series([0]*len(ym_list), index=ym_list)).values
    avg_tl  = grp_avg.get('Truckload', pd.Series([0]*len(ym_list), index=ym_list)).values

    tl_ref  = globals().get('MARKET_AVG_TL_LBS', 14500)
    ltl_ref = globals().get('MARKET_AVG_LTL_LBS', 3500)

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    x = np.arange(len(ym_list))

    # Truckload line + value labels above each marker
    ax.plot(x, avg_tl, color='#F0A030', marker='o', linewidth=2.4, markersize=8,
            label='Truckload Avg Wt')
    for i, v in enumerate(avg_tl):
        if v > 0:
            ax.annotate(f'{v:,.0f}', xy=(i, v), xytext=(0, 10),
                        textcoords='offset points', ha='center', fontsize=11,
                        color='#B07020', fontweight='bold')

    # LTL line + value labels below each marker
    ax.plot(x, avg_ltl, color='#5DADE2', marker='o', linewidth=2.4, markersize=8,
            label='LTL Avg Wt')
    for i, v in enumerate(avg_ltl):
        if v > 0:
            ax.annotate(f'{v:,.0f}', xy=(i, v), xytext=(0, -16),
                        textcoords='offset points', ha='center', fontsize=11,
                        color='#3380B2', fontweight='bold')

    # Market-avg horizontal references (dashed) -- labels on the LEFT side
    # to avoid overlapping the value annotations on the right side of the chart
    ax.axhline(tl_ref, color='#F0A030', linestyle='--', linewidth=1.4, alpha=0.7)
    ax.axhline(ltl_ref, color='#5DADE2', linestyle='--', linewidth=1.4, alpha=0.7)
    ax.text(-0.4, tl_ref, f'TL Market Avg ({tl_ref/1000:.1f}K)',
            color='#B07020', fontsize=10, va='center', ha='left',
            weight='bold', bbox=dict(boxstyle='round,pad=0.25', fc='white',
                                     ec='#F0A030', alpha=0.85))
    ax.text(-0.4, ltl_ref, f'LTL Market Avg ({ltl_ref/1000:.1f}K)',
            color='#3380B2', fontsize=10, va='center', ha='left',
            weight='bold', bbox=dict(boxstyle='round,pad=0.25', fc='white',
                                     ec='#5DADE2', alpha=0.85))

    ax.set_xticks(x)
    ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.tick_params(axis='y', labelsize=11)
    ax.set_ylabel('Average Weight per Shipment (lbs)', fontsize=12)
    ax.set_title('Average Weight by Mode', fontsize=13, color=COLOR_TEXT,
                 weight='bold', loc='left')
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(
        lambda v, _: f'{v/1e3:.0f}K' if v >= 1000 else f'{v:.0f}'))

    # Set y-range so the highest avg + both market refs fit cleanly, with
    # padding above and below for the value labels
    y_max = max(avg_tl.max(), avg_ltl.max(), tl_ref, ltl_ref) * 1.18
    ax.set_ylim(0, y_max)
    ax.legend(loc='upper right', fontsize=11, frameon=False)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_weight_vs_avg_for_slide22(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Deprecated alias: returns the new Average Weight chart only.

    Slide 22 was previously a single combined chart (Total Weight bars + Avg
    Weight lines + Market Avg refs on dual axes).  Per user request the
    metrics are now split into two separate charts on the slide:
        - Left: chart_weight_by_mode (Total Weight stacked LTL/TL)
        - Right: chart_avg_weight_with_market (Avg Weight lines + refs)
    This alias keeps any external references stable.
    """
    return chart_avg_weight_with_market(df_712, ym_list, labels)


def chart_tender_trend(df_tender: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """TL Tenders Over Time -- matches the Tableau 'Tenders over Time' worksheet.

    Stacks ALL 7 tender statuses (not just 3) so the chart visualization matches
    the live dashboard:

        Stack order from bottom to top (matches Tableau visual):
          Shipper Cancelled (brown, small)
          Rejected by Shipper (orange, small)
          Rejected by Carrier (gold/yellow, LARGE - broadcast no-responses)
          Withdrawn / In Progress (teal, small)
          Expired (pink, medium)
          Declined (red, medium-small)
          Accepted (green, top)

    Each major segment (>= 4% of bar) is labeled with its share of the FULL
    BAR (7-status total), matching Tableau's per-segment % labels.  The
    Accepted segment in particular shows the operational acceptance rate the
    same way Tableau reports it (e.g. 20.77% for Apr 2026).

    Secondary axis: Shipment Count line = unique SIDs where Accepted == 1
    per month.
    """
    plt = _setup_matplotlib()
    # Use last 16 months for a trend view
    all_ym = sorted(df_tender['YYYY_MM'].dropna().unique())
    last_ym = ym_list[-1] if ym_list else (all_ym[-1] if all_ym else '')
    if last_ym in all_ym:
        end_idx = all_ym.index(last_ym)
        window = all_ym[max(0, end_idx - 15):end_idx + 1]
    else:
        window = all_ym[-16:]
    sub = df_tender[df_tender['YYYY_MM'].isin(window)].copy()

    # STRICT TL-only filter -- drops the lenient "keep all modes if unknown"
    # fallback that inflated older history bars with LTL+TL+Parcel volume.
    if 'Mode' in sub.columns:
        sub = sub[sub['Mode'].astype(str).str.upper().isin(['TRUCKLOAD', 'TL'])].copy()

    # Drop Withdrawn -- Tableau's Tender Status filter explicitly excludes it
    # (filter-group 9: ALL EXCEPT [Withdrawn, null]).
    if 'Tender Status' in sub.columns:
        sub = sub[sub['Tender Status'].astype(str).str.strip() != 'Withdrawn'].copy()
    elif 'Withdrawn' in sub.columns:
        sub = sub[sub['Withdrawn'] != 1].copy()

    # Ensure all 7 tender-status columns exist (Withdrawn kept for completeness
    # but will be zero after the filter above)
    for c in ['Accepted', 'Declined', 'Expired', 'Rejected Carrier',
              'Rejected Shipper', 'Shipper Cancelled', 'Withdrawn']:
        if c not in sub.columns:
            sub[c] = 0

    grp = sub.groupby('YYYY_MM').agg(
        accepted=('Accepted', 'sum'),
        declined=('Declined', 'sum'),
        expired=('Expired', 'sum'),
        rej_carrier=('Rejected Carrier', 'sum'),
        rej_shipper=('Rejected Shipper', 'sum'),
        shipper_cancelled=('Shipper Cancelled', 'sum'),
        withdrawn=('Withdrawn', 'sum'),
    ).reindex(window).fillna(0)

    # Shipment count line = unique accepted SIDs per month (one Accepted per SID)
    accepted_sub = sub[sub['Accepted'] == 1]
    ship_count = accepted_sub.groupby('YYYY_MM')['SID'].nunique().reindex(window).fillna(0)
    grp['ship_count'] = ship_count

    # 7-status total = full bar height (denominator for all % labels)
    total = (grp['accepted'] + grp['declined'] + grp['expired'] + grp['rej_carrier']
             + grp['rej_shipper'] + grp['shipper_cancelled'] + grp['withdrawn'])

    fig, ax1 = plt.subplots(figsize=(11.0, 5.0))
    x = np.arange(len(window))
    bar_w = 0.7

    # Stack from bottom to top.  Each tuple = (col_name, label_for_legend, color)
    # Bottom of stack is the first entry (drawn first, then bottom is incremented).
    stack_spec = [
        ('shipper_cancelled', 'Shipper Cancelled', STATUS_COLORS['Shipper Cancelled']),
        ('rej_shipper',       'Rejected by Shipper', STATUS_COLORS['Rejected Shipper']),
        ('rej_carrier',       'Rejected by Carrier', STATUS_COLORS['Rejected Carrier']),
        ('withdrawn',         'Withdrawn',           STATUS_COLORS['Withdrawn']),
        ('expired',           'Expired',             STATUS_COLORS['Expired']),
        ('declined',          'Declined',            STATUS_COLORS['Declined']),
        ('accepted',          'Accepted',            STATUS_COLORS['Accepted']),
    ]
    bottom = np.zeros(len(window))
    for col, label, color in stack_spec:
        heights = grp[col].values
        ax1.bar(x, heights, bar_w, bottom=bottom, color=color, label=label,
                edgecolor='white', linewidth=0.3)
        # Label each segment with its % share of the FULL bar (7-status total)
        # Threshold 4% to avoid label-on-label crowding for tiny slices.
        for i, h in enumerate(heights):
            tot = total.iloc[i]
            if h <= 0 or tot <= 0:
                continue
            pct = h / tot * 100
            if pct < 4.0:
                continue
            y_center = bottom[i] + h / 2
            # Choose text color for contrast against the segment color
            if color in (STATUS_COLORS['Rejected Carrier'], STATUS_COLORS['Expired'],
                          STATUS_COLORS['Withdrawn']):
                txt_color = '#1F2A44'  # dark text on light segments
            else:
                txt_color = 'white'    # white text on dark/saturated segments
            ax1.text(i, y_center, f'{pct:.2f}%',
                     ha='center', va='center',
                     color=txt_color, fontsize=10, fontweight='bold')
        bottom += heights

    ax1.set_xticks(x)
    # Abbreviated month labels for the 16-month axis
    def _short_label(y):
        try:
            d = pd.Timestamp(y + '-01')
            return d.strftime('%b %y')
        except Exception:
            return labels.get(y, y[-5:])
    ax1.set_xticklabels([_short_label(y) for y in window], fontsize=12, rotation=45, ha='right')
    ax1.set_ylabel('Total Tender Count', fontsize=12, color=COLOR_TEXT)
    ax1.set_title('TL Tenders Over Time', fontsize=13, color=COLOR_TEXT, weight='bold', loc='left')
    ax1.tick_params(axis='y', labelsize=11)
    # Headroom for the legend
    max_top = max(total.max(), 1)
    ax1.set_ylim(0, max_top * 1.12)

    ax2 = ax1.twinx()
    ax2.plot(x, grp['ship_count'], color=COLOR_TEXT, marker='o', linewidth=2.2,
             markersize=6, label='Shipment Count')
    ax2.set_ylabel('Shipment Count', fontsize=12, color=COLOR_TEXT)
    ax2.tick_params(axis='y', labelsize=11)
    sc_max = grp['ship_count'].max() if len(grp) else 0
    if sc_max > 0:
        ax2.set_ylim(0, sc_max * 1.30)

    # Combined legend -- placed outside chart area to avoid overlapping bars
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc='upper left', bbox_to_anchor=(1.08, 1.0),
               fontsize=11, frameon=True, framealpha=0.95, edgecolor='#cccccc',
               borderaxespad=0)
    ax1.spines['top'].set_visible(False); ax2.spines['top'].set_visible(False)
    fig.subplots_adjust(right=0.78)  # make room for external legend
    return fig_to_data_uri(fig)


def chart_complaints_count(df_claims: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                            df_712: Optional[pd.DataFrame] = None) -> str:
    """Justified vs Unjustified complaint counts + % of total shipments overlay.
    Slide 27 left.  Per the deck, the chart shows complaints as stacked bars
    AND a line indicating complaint rate (complaints / monthly shipments).
    """
    plt = _setup_matplotlib()
    sub = df_claims[df_claims['YYYY_MM'].isin(ym_list)].copy()
    sub = sub[sub['Is_Complaint'] == 1] if 'Is_Complaint' in sub.columns and sub['Is_Complaint'].sum() > 0 else sub
    # The dashboard's Justified vs Unjustified worksheet EXCLUDES rows where
    # Justified? is null (and where the month is null).  Without this the totals
    # run a few high (e.g. Mar 47 vs dashboard 43).
    if 'Justified?' in sub.columns:
        _j = sub['Justified?'].astype(str).str.strip()
        sub = sub[sub['Justified?'].notna() & (_j != '') & (_j.str.lower() != 'nan') & (_j.str.lower() != 'none')]
    grp = sub.groupby(['YYYY_MM', 'Justified?']).size().unstack(fill_value=0)
    grp = grp.reindex(ym_list).fillna(0)

    # Monthly shipment denominator for the % line.  If df_712 is provided, use
    # OB shipment count per month; otherwise fall back to a simple total of
    # Justified+Unjustified (which gives a flat 100% line and is not useful).
    ship_counts = pd.Series(0.0, index=ym_list)
    if df_712 is not None and len(df_712) > 0:
        df712_ob = df_712[(df_712.get('IB_OB') == 'OB') & (df_712['YYYY_MM'].isin(ym_list))]
        ship_counts = df712_ob.groupby('YYYY_MM').size().reindex(ym_list).fillna(0)

    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    if 'Justified' in grp.columns:
        ax.bar(x, grp['Justified'], bar_w, color=STATUS_COLORS['Justified'], label='Justified')
        for i, v in enumerate(grp['Justified']):
            if v > 0: ax.text(i, v / 2, f'{int(v)}', ha='center', va='center',
                              color='white', fontsize=13, fontweight='bold')
    base = grp.get('Justified', pd.Series([0]*len(ym_list), index=ym_list))
    if 'Unjustified' in grp.columns:
        ax.bar(x, grp['Unjustified'], bar_w, bottom=base, color=STATUS_COLORS['Unjustified'], label='Unjustified')
        for i, v in enumerate(grp['Unjustified']):
            if v > 0: ax.text(i, base.iloc[i] + v / 2, f'{int(v)}', ha='center', va='center',
                              color='white', fontsize=13, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.tick_params(axis='y', labelsize=11)
    ax.set_ylabel('Claim / Complaint Count', fontsize=12)
    ax.set_title('Justified vs Unjustified', fontsize=13, color=COLOR_TEXT, weight='bold')

    # Headroom for the % line labels
    top = (grp.sum(axis=1)).max() if len(grp) else 0
    if top > 0:
        ax.set_ylim(0, top * 1.18)

    # % of total shipments line on secondary axis
    if (ship_counts > 0).any():
        total_complaints = grp.sum(axis=1).reindex(ym_list).fillna(0)
        complaint_pct = (total_complaints / ship_counts.replace(0, np.nan)) * 100
        ax2 = ax.twinx()
        ax2.plot(x, complaint_pct.values, color=COLOR_TEXT, marker='o',
                 linewidth=2.0, markersize=6, label='% of Shipments')
        for i, p in enumerate(complaint_pct.values):
            if p > 0 and not np.isnan(p):
                ax2.annotate(f'{p:.3f}%', xy=(i, p), xytext=(0, 8),
                             textcoords='offset points', ha='center',
                             fontsize=10, color=COLOR_TEXT, fontweight='bold')
        ax2.set_ylabel('% of Shipments', fontsize=12, color=COLOR_TEXT)
        ax2.tick_params(axis='y', labelsize=11)
        ax2.spines['top'].set_visible(False)
        max_pct = complaint_pct.max()
        if max_pct > 0 and not np.isnan(max_pct):
            ax2.set_ylim(0, max_pct * 1.6)
        # Combined legend
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc='upper right', fontsize=11, frameon=False)
    else:
        ax.legend(fontsize=11, frameon=False, loc='upper right')

    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_complaints_by_bu(df_claims: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Stacked complaints by BU, 3 months.  Slide 27 right."""
    plt = _setup_matplotlib()
    sub = df_claims[df_claims['YYYY_MM'].isin(ym_list)].copy()
    grp = sub.groupby(['YYYY_MM', 'BU']).size().unstack(fill_value=0)
    grp = grp.reindex(ym_list).fillna(0)
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    bottom = np.zeros(len(ym_list))
    for bu in grp.columns:
        color = BU_COLORS.get(bu, '#7AAFB5')
        ax.bar(x, grp[bu], bar_w, bottom=bottom, color=color, label=bu)
        # Label segments if big enough
        for i, v in enumerate(grp[bu]):
            if v >= max(grp.values.flatten()) * 0.05 and v > 0:
                ax.text(i, bottom[i] + v / 2, f'{int(v)}', ha='center', va='center',
                        color='white', fontsize=11, fontweight='bold')
        bottom += grp[bu].values
    ax.set_xticks(x); ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.set_ylabel('Count', fontsize=12)
    ax.set_title('Complaints by BU', fontsize=13, color=COLOR_TEXT)
    ax.legend(fontsize=11, frameon=False, loc='upper left', bbox_to_anchor=(1.0, 1.0))
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    return fig_to_data_uri(fig)


def _is_expedite_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask: True for expedite shipments.  MAF treats Priority starting
    with 'EXP' as the canonical expedite flag (~11k EXPEDITE + dozens of subtype
    breakdowns like EXP-CUSTOMER IMPACT)."""
    if 'Priority' not in df.columns:
        # Fallback to Service Type if Priority not present
        if 'Service Type' in df.columns:
            return df['Service Type'].astype(str).str.upper().str.contains('EXP|TEAM', na=False)
        return pd.Series(False, index=df.index)
    return df['Priority'].astype(str).str.upper().str.startswith('EXP')


def _expedite_ob_mask(df: pd.DataFrame) -> pd.Series:
    """Outbound mask for the expedite slides (33-35).

    Prefer the dashboard's own calculated [Type of Movement] classifier
    (available on the full 712 billing frame; default class is Outbound), and
    fall back to the raw-Movement-Type IB_OB for inputs that lack it.  The raw
    column defaults unknown rows to Interplant, which silently dropped
    expedites the Tableau dashboard counts as Outbound.
    """
    if 'Type of Movement (KPI)' in df.columns:
        return (df['Type of Movement (KPI)'].astype(str).str.strip().str.lower()
                == 'outbound')
    return df.get('IB_OB') == 'OB'


def _is_temp_control_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask: True for temperature-controlled shipments (temp van, refrig,
    insulated, or PFF LTL Priority)."""
    eq_mask = pd.Series(False, index=df.index)
    if 'Equipment Type' in df.columns:
        eq = df['Equipment Type'].astype(str).str.upper()
        eq_mask = eq.str.contains('TEMP|REFRIG|INSULATED', na=False)
    pri_mask = pd.Series(False, index=df.index)
    if 'Priority' in df.columns:
        pri = df['Priority'].astype(str).str.upper()
        pri_mask = pri.str.contains('PFF', na=False)
    return eq_mask | pri_mask


def chart_expedite_count_by_bu(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Stacked expedite count by BU, 3 months.  Slide 33 left."""
    plt = _setup_matplotlib()
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & _expedite_ob_mask(df_712)].copy()
    sub = sub[_is_expedite_mask(sub)]
    if 'BU' in sub.columns:
        # Per Akzo review (2026-07): leave Not Provided BU off this slide.
        sub = sub[sub['BU'] != 'Not Provided']
    if len(sub) == 0:
        return ''
    grp = sub.groupby(['YYYY_MM', 'BU']).size().unstack(fill_value=0)
    grp = grp.reindex(ym_list).fillna(0)
    fig, ax = plt.subplots(figsize=(6.0, 3.5))
    x = np.arange(len(ym_list))
    bar_w = 0.55
    bottom = np.zeros(len(ym_list))
    for bu in grp.columns:
        color = BU_COLORS.get(bu, '#7AAFB5')
        ax.bar(x, grp[bu], bar_w, bottom=bottom, color=color, label=bu)
        for i, v in enumerate(grp[bu]):
            tot = grp.iloc[i].sum()
            if v > 0 and tot > 0 and v / tot >= 0.05:
                ax.text(i, bottom[i] + v / 2, f'{v/tot*100:.2f}%',
                        ha='center', va='center', color='white', fontsize=11)
        bottom += grp[bu].values
    ax.set_xticks(x); ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.set_ylabel('Shipment Count', fontsize=12)
    ax.set_title('Expedite Counts by BU', fontsize=13, color=COLOR_TEXT)
    ax.legend(fontsize=11, frameon=False, loc='upper left', bbox_to_anchor=(1.0, 1.0))
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    return fig_to_data_uri(fig)

# =============================================================================
# 5. TABLE / TEXT HELPERS
# =============================================================================
def html_table_html(df: pd.DataFrame, caption: Optional[str] = None,
                    fmt: Optional[Dict[str, str]] = None) -> str:
    """Render a DataFrame as HTML with the MOR deck's table styling."""
    fmt = fmt or {}
    cap = f'<caption>{caption}</caption>' if caption else ''
    cols = ''.join(f'<th>{c}</th>' for c in df.columns)
    rows = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if c in fmt and pd.notna(v):
                try:
                    v = fmt[c].format(v)
                except Exception:
                    pass
            elif pd.isna(v):
                v = ''
            cells.append(f'<td>{v}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return (f'<table class="mor-table editable">{cap}<thead><tr>{cols}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def bullet_list(items: List[str]) -> str:
    """Render a list of plain-text items as an HTML <ul>."""
    if not items:
        return ''
    return '<ul>' + ''.join(f'<li>{it}</li>' for it in items) + '</ul>'


def narrative_block(title: str, items: List[str]) -> str:
    """Render the 'Historical Performance / Root Cause / Action Plan' blocks.

    Wrapped in `.editable` so the Ops team can edit the bullets in-browser.
    A small autosave-to-localStorage script (in build_full_html) handles
    persistence; data-edit-key is auto-assigned at DOMContentLoaded based
    on the parent <section id> + block index so keys are stable across
    monthly re-generations.
    """
    if not items:
        return ''
    return (f'<div class="narrative-block">'
            f'<h4>{title}</h4>'
            f'<div class="editable">{bullet_list(items)}</div>'
            f'</div>')


def editable_text(html: str) -> str:
    """Wrap arbitrary HTML (e.g. an auto-derived prose paragraph) as editable."""
    return f'<div class="editable">{html}</div>'

# =============================================================================
# 6. SECTION RENDERERS  (each returns an HTML string)
# =============================================================================
def slide_divider(title: str, slide_num: int = 0) -> str:
    """Navy section divider with a lime flag.  Mirrors MOR slides 3, 5, 12, 18, 20, 23, 26, 30, 32."""
    return f'''
<section class="mor-divider" id="divider-{slide_num}">
  <div class="divider-flag"></div>
  <h2 class="divider-title">{title}</h2>
</section>
'''


def slide_title(report_month_label: str) -> str:
    return f'''
<section class="mor-title">
  <div class="title-stripes">
    <div class="stripe lime"></div>
    <div class="stripe white"></div>
    <div class="stripe navy"></div>
  </div>
  <div class="title-content">
    <h1>AkzoNobel</h1>
    <h2 class="title-month">{report_month_label.upper()}<br>MOR</h2>
    <div class="title-brand">Quantix</div>
  </div>
</section>
'''


def slide_agenda(items: List[str]) -> str:
    items = items or [
        'On Time Carrier Performance Analysis', 'Shipping Exceptions Analysis',
        'Operations Update', 'Shipping Weight & Spend Analysis', 'Carrier Tender Performance Analysis',
        'Claims and Complaints Analysis', 'Temperature Control Analysis',
        'Expedite Tracking Analysis', 'Conclusion',
    ]
    # Safety Moment slide was removed from the report; drop it from the agenda
    # too even if a narrative YAML still lists it.
    items = [i for i in items if str(i).strip().lower() != 'safety moment']
    items_html = ''.join(f'<li>{i}</li>' for i in items)
    return f'''
<section class="mor-agenda">
  <h2 class="agenda-title">TODAY'S<br>AGENDA</h2>
  <ol class="agenda-list">{items_html}</ol>
</section>
'''


def slide_content(title: str, slide_num: int, body_html: str) -> str:
    """Standard content slide: lime flag + title + body."""
    return f'''
<section class="mor-content" id="slide-{slide_num}">
  <div class="content-flag"></div>
  <h2 class="content-title">{title}</h2>
  <div class="content-body">{body_html}</div>
  <div class="content-footer"><span class="brand">Quantix</span><span class="page-num">{slide_num}</span></div>
</section>
'''


def slide_otp_performance(perf_df: pd.DataFrame, df_712: pd.DataFrame,
                          ym_list: List[str], labels: Dict[str, str],
                          mode: str, slide_num: int, narrative: Dict,
                          side: str = 'PU') -> str:
    """Builds slides 6/7/8/9-style layout: text left, 2x2 charts right.

    `side` = 'PU' (slides 6/7) or 'Del' (slides 8/9).
    """
    report_ym = ym_list[-1]
    side_word = 'Pickup' if side == 'PU' else 'Delivery'
    late_col, ot_col = ('SA_PU_Late', 'SA_PU_OT') if side == 'PU' else ('SA_Del_Late', 'SA_Del_OT')

    # Build the top-3 sites table (%Late + Load Count by month).  Column order:
    # Origin City | %Late <all months> | LC <all months>  -- matches MAF deck.
    # Grain/filters MUST match the chart_late_vs_ontime worksheet so the table
    # and the bars agree: COUNTD(SID) split by SA-late; delivery side also
    # applies Remove Insufficient TT for Del = 0 (pickup uses no extra filter).
    sub = perf_df[(perf_df['Mode'] == mode) & (perf_df['YYYY_MM'].isin(ym_list))].copy()
    if side == 'Del' and 'Remove_Insuff_TT_Del' in sub.columns:
        _v = pd.to_numeric(sub['Remove_Insuff_TT_Del'], errors='coerce')
        sub = sub[_v.isna() | (_v == 0)].copy()
    if 'Origin City' in sub.columns:
        # Rank sites by the VOLUME of late shipments across the whole window,
        # not the report-month %.  A site like DORVAL (4 loads, 2 late = 50%)
        # is not a "top issue" vs PASADENA (200 loads, a few late); ranking by
        # % alone surfaces tiny-volume noise.  Require a minimum total volume so
        # only sites with a real shipment base qualify, then order by total late
        # SID count.
        site_vol = sub.groupby('Origin City')['SID'].nunique()
        min_site_vol = 20  # need a meaningful load base over the window
        eligible_sites = site_vol[site_vol >= min_site_vol].index
        sub_elig = sub[sub['Origin City'].isin(eligible_sites)]
        top_sites = (sub_elig[sub_elig[late_col] == 1].groupby('Origin City')['SID'].nunique()
                     .sort_values(ascending=False).head(3).index.tolist())
        # Fallback if the floor removed everyone (sparse data): drop the floor.
        if not top_sites:
            top_sites = (sub[sub[late_col] == 1].groupby('Origin City')['SID'].nunique()
                         .sort_values(ascending=False).head(3).index.tolist())
        tbl = []
        for site in top_sites:
            row = {'Origin City': site}
            for ym in ym_list:
                ss = sub[(sub['Origin City'] == site) & (sub['YYYY_MM'] == ym)]
                lc = ss['SID'].nunique()
                late = ss[ss[late_col] == 1]['SID'].nunique()
                row[f'%Late {labels.get(ym, ym)}'] = f'{(late / lc * 100) if lc else 0:.0f}%'
            for ym in ym_list:
                ss = sub[(sub['Origin City'] == site) & (sub['YYYY_MM'] == ym)]
                row[f'LC {labels.get(ym, ym)}'] = ss['SID'].nunique()
            tbl.append(row)
        site_table = html_table_html(pd.DataFrame(tbl)) if tbl else ''
    else:
        site_table = ''

    chart_late = chart_late_vs_ontime(perf_df, ym_list, labels, mode, side=side)
    chart_cost_late = chart_cost_late_overlay(perf_df, ym_list, labels, mode, side=side)
    # NOTE: cost/weight BU-mix pies stay OUTBOUND-ONLY (df_712 == OB perf_df) by
    # design -- the dashboard's cost/weight views are outbound, while the OTP/OTD
    # bars above are all-moves.  Do not switch these to all-moves.
    chart_cost = chart_cost_pie_by_bu(df_712, report_ym, mode=mode)
    chart_weight = chart_weight_pie_by_bu(df_712, report_ym, mode=mode)

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
    {narrative_block('Root Cause Analysis', narrative.get('rca', []))}
    {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
    {site_table}
  </div>
  <div class="col-charts grid-2x2">
    <div class="chart-cell"><img src="{chart_late}" alt="Late vs On Time count"></div>
    <div class="chart-cell"><img src="{chart_cost_late}" alt="Cost overlay"></div>
    <div class="chart-cell"><img src="{chart_cost}" alt="Total Cost pie"></div>
    <div class="chart-cell"><img src="{chart_weight}" alt="Total Weight pie"></div>
  </div>
</div>
'''
    return slide_content(f'On Time {side_word} Performance - {mode}', slide_num, body)


def slide_exceptions_count(perf_df: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                           slide_num: int, mode_form: str = 'count') -> str:
    """Slide 13: exceptions table by mode.  `mode_form` = 'count' or 'pct'.

    Slide 14 uses the same data divided by total tenders for each month.
    """
    show_pct = (mode_form == 'pct')

    def build_ex_table(mode):
        sub = perf_df[(perf_df['Mode'] == mode) & (perf_df['YYYY_MM'].isin(ym_list))]
        # OLT flag is mode-specific:
        #   LTL -> OLT_LTL_PU_Excl  (~Short Order Lead Time)
        #   TL  -> OLT_TL_PU_Excl
        # Using OLT_LTL_PU_Excl for both modes (the prior bug) caused the TL
        # Short Order Lead Time column to show 0 even though MAF shows ~100/mo
        # for TL Apr 2026 (Same Day TL TT exclusions are real and material).
        olt_flag = 'OLT_LTL_PU_Excl' if mode == 'LTL' else 'OLT_TL_PU_Excl'

        tot = sub.groupby('YYYY_MM').agg(
            tenders=('SID', 'count'),
            insuff_tt=('Remove_Insuff_TT_Del', 'sum') if 'Remove_Insuff_TT_Del' in sub.columns else ('SID', lambda s: 0),
            past_due=('Remove_Past_Due_PU', 'sum') if 'Remove_Past_Due_PU' in sub.columns else ('SID', lambda s: 0),
            short_olt=(olt_flag, 'sum') if olt_flag in sub.columns else ('SID', lambda s: 0),
            mat_na=('Remove_Mat_NA_PU', 'sum') if 'Remove_Mat_NA_PU' in sub.columns else ('SID', lambda s: 0),
            del_b4_pu=('Remove_Del_b4_PU', 'sum') if 'Remove_Del_b4_PU' in sub.columns else ('SID', lambda s: 0),
        ).reindex(ym_list).fillna(0).astype(int)
        # Unique SID Exclusion: count of unique SIDs where ANY exception flag fires.
        # Use the SAME flag list that contributes to the per-row exception counts.
        unique_excl_rows = {}
        flag_cols = [c for c in ['Remove_Insuff_TT_Del', 'Remove_Past_Due_PU',
                                  olt_flag, 'Remove_Mat_NA_PU',
                                  'Remove_Del_b4_PU'] if c in sub.columns]
        if flag_cols:
            any_excl = sub[flag_cols].sum(axis=1) >= 1
            unique_excl_rows = sub[any_excl].groupby('YYYY_MM')['SID'].nunique().reindex(ym_list).fillna(0).astype(int)
        else:
            unique_excl_rows = pd.Series(0, index=ym_list)

        rows = [
            ('Insufficient TT Exception', 'insuff_tt'),
            ('Past Due/Backorders', 'past_due'),
            ('Short Order Lead Time: Same Day PUs (past noon)', 'short_olt'),
            ("Remove Mat'l Not Avail PU Y/N 1/0", 'mat_na'),
            ('Reverse Order: Del before Pickup', 'del_b4_pu'),
        ]
        cols = ['Exception'] + [labels.get(y, y) for y in ym_list]
        data = []
        for label, col in rows:
            r = [label]
            for y in ym_list:
                v = tot.loc[y, col]
                if show_pct:
                    total = tot.loc[y, 'tenders']
                    r.append(f'{(v/total*100) if total else 0:.1f}%')
                else:
                    r.append(f'{v:,}')
            data.append(r)
        # Append Unique SID Exclusion row
        usid_row = ['Unique SID Exclusion']
        for y in ym_list:
            v = int(unique_excl_rows.get(y, 0))
            if show_pct:
                total = tot.loc[y, 'tenders']
                usid_row.append(f'{(v/total*100) if total else 0:.1f}%')
            else:
                usid_row.append(f'{v:,}')
        data.append(usid_row)
        df_view = pd.DataFrame(data, columns=cols)
        return df_view, tot

    ltl_df, ltl_tot = build_ex_table('LTL')
    tl_df, tl_tot = build_ex_table('Truckload')

    body = f'''
<div class="exceptions-grid">
  <div class="ex-block">
    <h4 class="ex-mode-header">LTL Exceptions</h4>
    {html_table_html(ltl_df)}
    <p class="totals-line"><strong>Total LTL Tenders:</strong>{''.join(f' &nbsp; {labels.get(y, y)}: {ltl_tot.loc[y, "tenders"]:,}' for y in ym_list)}</p>
  </div>
  <div class="ex-block">
    <h4 class="ex-mode-header">Truckload Exceptions</h4>
    {html_table_html(tl_df)}
    <p class="totals-line"><strong>Total TL Tenders:</strong>{''.join(f' &nbsp; {labels.get(y, y)}: {tl_tot.loc[y, "tenders"]:,}' for y in ym_list)}</p>
  </div>
  <div class="ex-legend">
    <p><strong>Insufficient Transit Time:</strong> Excludes orders whose planned transit time is less than expected transit time</p>
    <p><strong>Product Not Shipped:</strong> Excludes LTL orders when the carrier picked up other freight on the same day from the same location</p>
    <p><strong>Past Due/Brokerage:</strong> Excludes past due/backorders where planned pickup is in the past</p>
    <p><strong>Short Order Lead Time:</strong> Excludes orders created past noon (local time) for same day LTL pickups OR same day TL/Bulk Truck pickups</p>
    <p><strong>Reverse Order Deliver Before Pickup:</strong> Excludes orders planned to deliver before pickup</p>
    <p><strong>Unique SID Exceptions:</strong> Total of unique SIDs with exceptions</p>
  </div>
</div>
'''
    title = 'Exceptions by Mode - Percentage' if show_pct else 'Exceptions by Mode - Total Count'
    return slide_content(title, slide_num, body)


def slide_top_sites_exception(perf_df: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                              slide_num: int, title: str, flag_col: str,
                              mode_filter: Optional[str] = None,
                              extra_notes: Optional[List[str]] = None) -> str:
    """Slides 15-17: top 5 sites by an exception flag, with %Late and Load Count by month.

    `flag_col` is the 1/0 column name (e.g. 'Remove_Insuff_TT_Del').  If the
    sentinel value 'OLT_PER_MODE' is passed, the function automatically uses
    OLT_LTL_PU_Excl for LTL and OLT_TL_PU_Excl for TL -- needed for slide 16
    where the LTL OLT flag does not fire on TL rows and vice versa.
    `mode_filter` = 'LTL' to restrict (slide 17), or None for both modes.
    """
    def site_table(mode):
        # Pick the correct flag column for this mode
        if flag_col == 'OLT_PER_MODE':
            actual_flag = 'OLT_LTL_PU_Excl' if mode == 'LTL' else 'OLT_TL_PU_Excl'
        else:
            actual_flag = flag_col
        sub = perf_df[(perf_df['Mode'] == mode) & (perf_df['YYYY_MM'].isin(ym_list))].copy()
        if 'Origin City' not in sub.columns or actual_flag not in sub.columns:
            return ''
        # Pick top-5 sites by total flag count over the window
        top_sites = (sub.groupby('Origin City')[actual_flag]
                       .sum().sort_values(ascending=False).head(5).index.tolist())
        rows = []
        for site in top_sites:
            row = {'Origin City': site}
            # Per MAF deck: show exception COUNT (not %), grouped:
            # Origin City | Exception <Feb> | <Mar> | <Apr> | LC <Feb> | <Mar> | <Apr>
            for y in ym_list:
                ss = sub[(sub['Origin City'] == site) & (sub['YYYY_MM'] == y)]
                row[f'Excpt {labels.get(y, y)}'] = int(ss[actual_flag].sum())
            for y in ym_list:
                ss = sub[(sub['Origin City'] == site) & (sub['YYYY_MM'] == y)]
                row[f'LC {labels.get(y, y)}'] = len(ss)
            rows.append(row)
        if not rows:
            return ''
        df_view = pd.DataFrame(rows)
        return f'<h4>{mode} Mode</h4>' + html_table_html(df_view)

    table_html = ''
    if mode_filter:
        table_html = site_table(mode_filter)
    else:
        table_html = site_table('LTL') + site_table('Truckload')

    notes_html = bullet_list(extra_notes or [])
    body = f'''
<div class="two-col">
  <div class="col-narrative">
    {table_html}
  </div>
  <div class="col-narrative">
    {notes_html}
  </div>
</div>
'''
    return slide_content(title, slide_num, body)


def slide_top_late_carriers(perf_df: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                            slide_num: int, side: str, narrative: Dict) -> str:
    """Slides 10-11: Top 3 late carriers by mode (Pickup or Delivery)."""
    late_col = 'SA_PU_Late' if side == 'PU' else 'SA_Del_Late'
    side_word = 'Pickup' if side == 'PU' else 'Delivery'

    def carrier_table(mode):
        sub = perf_df[(perf_df['Mode'] == mode) & (perf_df['YYYY_MM'].isin(ym_list))].copy()
        # Match the OTP/OTD worksheet grain: COUNTD(SID), and on the delivery
        # side apply Remove Insufficient TT for Del = 0 (pickup: no extra filter).
        if side == 'Del' and 'Remove_Insuff_TT_Del' in sub.columns:
            _v = pd.to_numeric(sub['Remove_Insuff_TT_Del'], errors='coerce')
            sub = sub[_v.isna() | (_v == 0)].copy()
        scac_col = next((c for c in ['Carrier Name', 'Carrier SCAC', 'SCAC'] if c in sub.columns), None)
        if scac_col is None or late_col not in sub.columns:
            return ''
        # Exclude local couriers / Akzo-direct carriers from the dashboard
        # (Akzo request 2026-06-22). Mode-aware, case-insensitive match.
        _excl = carrier_exclusions_for_mode(mode)
        if _excl:
            sub = sub[~sub[scac_col].map(lambda v: _norm_carrier(v) in _excl)].copy()
        # Pick the top-3 carriers with the MOST late shipments across the whole
        # 3-month window -- carriers with sustained issues, not a single bad
        # month.  Rank by total distinct late SIDs over the window; require a
        # minimum total volume so a brand-new carrier with one high-volume late
        # month (e.g. 0/0/577 with no prior history) doesn't crowd out carriers
        # with a real track record of lateness.
        vol = sub.groupby(scac_col)['SID'].nunique()
        min_vol = 30  # need a meaningful shipment base over the window
        eligible = vol[vol >= min_vol].index
        sub_elig = sub[sub[scac_col].isin(eligible)]
        late_by_carrier = (sub_elig[sub_elig[late_col] == 1]
                           .groupby(scac_col)['SID'].nunique()
                           .sort_values(ascending=False))
        top_carriers = late_by_carrier.head(3).index.tolist()
        # Fallback: if the volume floor removed everyone (sparse data), drop it.
        if not top_carriers:
            top_carriers = (sub[sub[late_col] == 1].groupby(scac_col)['SID'].nunique()
                            .sort_values(ascending=False).head(3).index.tolist())
        rows = []
        for c in top_carriers:
            row = {'Carrier': c}
            for y in ym_list:
                ss = sub[(sub[scac_col] == c) & (sub['YYYY_MM'] == y)]
                lc = ss['SID'].nunique()
                late = ss[ss[late_col] == 1]['SID'].nunique()
                row[f'%Late {labels.get(y, y)}'] = f'{(late / lc * 100) if lc else 0:.0f}%'
            for y in ym_list:
                ss = sub[(sub[scac_col] == c) & (sub['YYYY_MM'] == y)]
                row[f'LC {labels.get(y, y)}'] = ss['SID'].nunique()
            rows.append(row)
        if not rows:
            return ''
        return f'<h4>{mode}</h4>' + html_table_html(pd.DataFrame(rows))

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    {carrier_table('LTL')}
    {carrier_table('Truckload')}
  </div>
  <div class="col-narrative">
    {narrative_block('Root Cause Analysis', narrative.get('rca', []))}
    {narrative_block('Top 2 Carriers - Highest % Failure', narrative.get('top_carriers', []))}
  </div>
</div>
'''
    return slide_content(f'Top 3 Late Carriers by Mode - {side_word}', slide_num, body)


def slide_cost_per_kg(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                      slide_num: int, narrative: Dict) -> str:
    """Slide 21: Cost per KG (EUR) Analysis.

    Two charts side-by-side on top + narrative split 2-col below:
      LEFT  chart: Cost per KG (EUR) by BU line chart (matches Tableau)
      RIGHT chart: Total Weight by Mode stacked bars (companion view -- shows
                   the denominator behind the cost/kg across the same window)
    """
    chart_cpp = chart_cost_per_kg(df_712, ym_list, labels)
    chart_wt = chart_weight_by_mode(df_712, ym_list, labels)

    # Auto-derived CPP MoM trend (overall + per-BU)
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    auto_paragraphs = []
    if len(sub) > 0 and 'Normalized Weight' in sub.columns:
        agg = sub.groupby('YYYY_MM').agg(
            cost=("Normalized Ship't Actual Cost", 'sum'),
            weight=('Normalized Weight', 'sum'),
        ).reindex(ym_list).fillna(0)
        # USD/lb -> EUR/kg to match the dashboard.
        agg['cpp'] = np.where(agg['weight'] > 0,
                              (agg['cost'] / agg['weight']) * USD_LB_TO_EUR_KG, 0)
        if len(agg) >= 2 and agg['cpp'].iloc[-2] > 0:
            cur, prev = agg['cpp'].iloc[-1], agg['cpp'].iloc[-2]
            pct = (cur - prev) / prev * 100
            verb = 'increased' if pct >= 0 else 'decreased'
            auto_paragraphs.append(
                f'Overall Cost per KG {verb} {abs(pct):.1f}% from '
                f'{labels.get(ym_list[-2], "prior")} (\u20ac{prev:.3f}/kg) to '
                f'{labels.get(ym_list[-1], "report")} (\u20ac{cur:.3f}/kg).'
            )

    auto_html = ''.join(f'<p>{p}</p>' for p in auto_paragraphs)
    auto_block = (f'<div class="narrative-block"><h4>Auto-derived</h4>'
                  f'<div class="editable">{auto_html}</div></div>'
                  if auto_html else '')

    body = f'''
<div class="two-col-charts-top">
  <div class="chart-row">
    <div class="chart-cell"><img src="{chart_cpp}" alt="Cost per KG (EUR) by BU"></div>
    <div class="chart-cell"><img src="{chart_wt}" alt="Total Weight by Mode"></div>
  </div>
  <div class="narrative-row">
    <div class="col-narrative">
      {auto_block}
      {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
      {narrative_block('Root Cause Analysis', narrative.get('rca', []))}
    </div>
    <div class="col-narrative">
      {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
    </div>
  </div>
</div>
'''
    return slide_content('Cost per KG (EUR) Analysis', slide_num, body)


def slide_tender(df_tender: pd.DataFrame, df_712: pd.DataFrame, ym_list: List[str],
                 labels: Dict[str, str], slide_num: int, narrative: Dict) -> str:
    """Slide 24: TL Tender Acceptance & Rejection.

    Tender Rejection % per the Tableau dashboard's '** Tender Rejection' calc:
        (Expired + Rejected Carrier + Rejected Shipper + Declined) /
        (Accepted + Declined + Expired + Rejected Carrier + Rejected Shipper
         + Shipper Cancelled + Withdrawn)
    """
    chart = chart_tender_trend(df_tender, ym_list, labels)

    report_ym = ym_list[-1]
    sub = df_tender[(df_tender['YYYY_MM'].isin(ym_list))].copy()

    # === Replicate the Tender KPI Dashboard "BU performance" worksheet exactly ===
    # (verified against Akzo_Tender_KPI_Dashboard.twbx; see tender_bu_table_SPEC.md)
    # Filter chain, in order:
    #   1. Tender Type group IN {Direct, Manual, Sequential}  -> exclude all Broadcast*
    #   2. Transport Mode = Truckload
    #   3. Tender Status NOT IN {Withdrawn, null}
    #   4. 712 Include filter == 'Include'
    #   5. Pick Up Date month IN ym_list
    #   6. BU not null
    # Shipment Count = COUNTD(billing SID) over the filtered set.
    # Tender Rejection = (Expired+RejCarrier+RejShipper+Declined) / Total Tenders
    #   where Total Tenders = all 7 statuses INCLUDING Withdrawn (per the calc).

    # 1. Exclude broadcast tender types (Broadcast for Capacity / Review / plain Broadcast)
    if 'Tender Type' in sub.columns:
        _tt = sub['Tender Type'].astype(str).str.upper()
        sub = sub[~_tt.str.startswith('BROADCAST')].copy()

    # 2. Truckload only
    if 'Mode' in sub.columns:
        sub = sub[sub['Mode'].astype(str).str.upper().isin(['TRUCKLOAD', 'TL'])].copy()

    # 3. Drop Withdrawn / null status (this is the STATUS filter, separate from the
    #    rejection denominator which still adds Withdrawn back per the Tableau calc;
    #    in practice Withdrawn rows are filtered here so the denom term is ~0).
    if 'Tender Status' in sub.columns:
        _ts = sub['Tender Status'].astype(str).str.strip()
        sub = sub[(_ts != 'Withdrawn') & (sub['Tender Status'].notna())].copy()
    elif 'Withdrawn' in sub.columns:
        sub = sub[sub['Withdrawn'] != 1].copy()

    # 4. 712 Include filter: the dashboard's BU performance worksheet uses a
    #    UNION filter that keeps ALL FIVE values (the 4 "Exclude - *" plus
    #    "Include") -- i.e. it does NOT actually drop the excluded rows.  An
    #    earlier version filtered to Include-only, which undercounted Shipment
    #    Count (especially for BUs with many created>=pickup or no-cost rows).
    #    So we deliberately do NOT filter on Include_712 here.
    #    (We still exclude rows whose movement classifier is null, matching the
    #    dashboard's 'except %null%' movement filter -- handled via BU not-null
    #    below, since null-movement rows also lack a usable BU.)

    # 6. BU: prefer upstream-attached BU, else map from df_712 by SID.
    if 'BU' not in sub.columns and 'SID' in sub.columns and 'BU' in df_712.columns:
        bu_map = df_712[['SID', 'BU']].drop_duplicates('SID').set_index('SID')['BU']
        sub['BU'] = sub['SID'].map(bu_map)

    if 'BU' in sub.columns:
        for c in ['Accepted', 'Declined', 'Expired', 'Rejected Carrier',
                  'Rejected Shipper', 'Shipper Cancelled', 'Withdrawn']:
            if c not in sub.columns:
                sub[c] = 0

        # BU set comes from normalize_bu'd df_tender (run at build_full_html top)
        # so no METAL+Metal duplicates.  Dual-key BU enrichment in main() means
        # M&PC surfaces for IB tender SIDs.
        # Per Akzo review (2026-07): leave Not Provided BU off this slide.
        bus_in_data = sorted(b for b in sub['BU'].dropna().unique()
                             if b != 'Not Provided')

        # Compute per-BU per-month metrics
        bu_rows = []
        for bu in bus_in_data:
            cells = []  # one (ships, rej_pct_str) tuple per month
            for ym in ym_list:
                s = sub[(sub['BU'] == bu) & (sub['YYYY_MM'] == ym)]
                # Shipment Count = COUNTD(SID) over the filtered set -- matches
                # the Tableau "Shipment Count" = COUNTD([SID 712 Billing]).  A SID
                # is counted once if it survives all filters, regardless of how
                # many tender attempts (accept/reject/expire) it generated.
                ships = int(s['SID'].nunique())
                # Numerator = 4 reject-type statuses
                rejected = (s['Expired'].sum() + s['Rejected Carrier'].sum()
                            + s['Rejected Shipper'].sum() + s['Declined'].sum())
                # Denominator = Total Tenders (all 7 statuses, incl. Withdrawn)
                total_tenders = (s['Accepted'].sum() + s['Declined'].sum()
                                 + s['Expired'].sum() + s['Rejected Carrier'].sum()
                                 + s['Rejected Shipper'].sum()
                                 + s['Shipper Cancelled'].sum()
                                 + s['Withdrawn'].sum())
                rej_pct = (rejected / total_tenders * 100) if total_tenders > 0 else 0
                cells.append((ships, f'{rej_pct:.2f}%'))
            bu_rows.append((bu, cells))

        # Build the grouped-header HTML table to match the deck's format:
        #   Row 1: **Business Unit | December 2025 (span 2) | January 2026 (span 2) | ...
        #   Row 2:                 | Shipment Count | Tender Rejection % | ... (repeated)
        #   Row 3+: BU name | counts and pcts paired by month
        month_headers = ''.join(
            f'<th colspan="2" class="tender-month-hdr">{labels.get(ym, ym)}</th>'
            for ym in ym_list
        )
        sub_headers = ''.join(
            '<th class="tender-sub-hdr">Shipment Count</th>'
            '<th class="tender-sub-hdr">Tender Rejection %</th>'
            for _ in ym_list
        )
        body_rows = ''
        for bu, cells in bu_rows:
            cell_html = ''.join(
                f'<td class="num">{ships:,}</td><td class="num">{pct}</td>'
                for ships, pct in cells
            )
            body_rows += f'<tr><td class="bu-name">{bu}</td>{cell_html}</tr>'
        bu_table = (
            '<table class="mor-table tender-bu-table editable">'
            f'<thead>'
            f'<tr><th rowspan="2" class="tender-bu-hdr">**Business Unit</th>{month_headers}</tr>'
            f'<tr>{sub_headers}</tr>'
            '</thead>'
            f'<tbody>{body_rows}</tbody>'
            '</table>'
        )
    else:
        bu_table = ''

    body = f'''
<div class="tender-layout">
  <div class="tender-main">
    <div class="chart-cell"><img src="{chart}" alt="Tenders over time"></div>
    {bu_table}
  </div>
  <div class="col-narrative">
    {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
    {narrative_block('Root Cause Analysis', narrative.get('rca', []))}
    {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
  </div>
</div>
'''
    return slide_content('TL Tender Acceptance & Rejection', slide_num, body)


def slide_top_rejecting_carriers(df_tender: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                                  slide_num: int, narrative: Dict,
                                  df_712_for_include: Optional[pd.DataFrame] = None) -> str:
    """Slide 25: Top rejecting TL carriers - last 3 months.

    Per the deck:
      - Top 5: highest rejection % carriers (with meaningful volume).
      - Bottom 5 (most accepting): top-volume carriers sorted by rejection %
        ascending.  These are the "preferred / primary" carriers shown for
        context -- they're not literally the 5 lowest rejection rates (which
        would be tiny one-off carriers at 0%).
    """
    all_ym = sorted(df_tender['YYYY_MM'].dropna().unique())
    # Always anchor to the last COMPLETE calendar month so a mid-month run
    # (e.g. running the June report on June 11) doesn't include partial data.
    last_complete_ym = (pd.Timestamp.today().normalize()
                        - pd.DateOffset(months=1)).strftime('%Y-%m')
    # Walk back from last_complete_ym to find the most recent month present in
    # the tender data (handles edge case where data hasn't arrived yet).
    anchor = next((ym for ym in reversed(all_ym) if ym <= last_complete_ym), None)
    if anchor is None:
        anchor = all_ym[-1] if all_ym else ''
    if anchor in all_ym:
        end_idx = all_ym.index(anchor)
        window = all_ym[max(0, end_idx - 2):end_idx + 1]
    else:
        window = all_ym[-3:]
    sub = df_tender[df_tender['YYYY_MM'].isin(window)].copy()

    # The dashboard "Carrier performance" worksheet uses the SAME filter chain as
    # the BU table (verified from the .twbx):
    #   Tender Type group IN {Direct, Manual, Sequential}  -> EXCLUDE broadcast
    #   Transport Mode = Truckload
    #   712 Include filter = Include
    #   Tender Status NOT IN {Withdrawn, null}
    # Earlier this table omitted the broadcast + Include filters, so it surfaced
    # "Broadcast for Capacity" carriers that the dashboard never shows.

    # Exclude broadcast tender types.
    if 'Tender Type' in sub.columns:
        _tt = sub['Tender Type'].astype(str).str.upper()
        sub = sub[~_tt.str.startswith('BROADCAST')].copy()

    # Strict TL filter.
    if 'Mode' in sub.columns:
        sub = sub[sub['Mode'].astype(str).str.upper().isin(['TRUCKLOAD', 'TL'])].copy()

    # Exclude shuttle / non-routing-guide carriers (Ryder, Pioneer, etc.) from
    # the rejection ranking -- their dedicated shuttle moves are not comparable
    # tenders and inflate the table (Poojan 2026-06-23).
    if 'Carrier Name' in sub.columns:
        _excl = carrier_exclusions_for_mode('TL')
        sub = sub[~sub['Carrier Name'].map(_norm_carrier).isin(_excl)].copy()

    # Drop Withdrawn / null status.
    if 'Tender Status' in sub.columns:
        sub = sub[(sub['Tender Status'].astype(str).str.strip() != 'Withdrawn')
                  & (sub['Tender Status'].notna())].copy()
    elif 'Withdrawn' in sub.columns:
        sub = sub[sub['Withdrawn'] != 1].copy()

    # 712 Include filter: like the BU table, the dashboard's Carrier performance
    # worksheet UNIONs all five values (4 Excludes + Include), so it does NOT
    # drop the excluded rows.  Do not filter on Include_712 -- doing so
    # undercounts each carrier's shipment count.

    for c in ['Accepted', 'Declined', 'Expired', 'Rejected Carrier',
              'Rejected Shipper', 'Shipper Cancelled', 'Withdrawn']:
        if c not in sub.columns:
            sub[c] = 0

    # ship_count = COUNTD(SID) over the filtered set -- matches the dashboard's
    # Shipment Count = COUNTD([SID 712 Billing]).  (Not accepted-only, which
    # undercounts carriers whose tenders were mostly rejected.)
    ship_count_per_carrier = (
        sub.groupby('Carrier Name')['SID'].nunique().rename('ship_count')
    )

    grp = sub.groupby('Carrier Name').agg(
        accepted=('Accepted', 'sum'),
        declined=('Declined', 'sum'),
        expired=('Expired', 'sum'),
        rej_carrier=('Rejected Carrier', 'sum'),
        rej_shipper=('Rejected Shipper', 'sum'),
        shipper_cancelled=('Shipper Cancelled', 'sum'),
        withdrawn=('Withdrawn', 'sum'),
    )
    grp = grp.join(ship_count_per_carrier, how='left').fillna({'ship_count': 0})
    grp['ship_count'] = grp['ship_count'].astype(int)
    # Per Tableau: numerator = Expired + Rejected Carrier + Rejected Shipper + Declined
    rejected = grp['expired'] + grp['rej_carrier'] + grp['rej_shipper'] + grp['declined']
    # Denominator = Total Tenders (6 statuses -- Withdrawn excluded per Tableau filter)
    total = (grp['accepted'] + grp['declined'] + grp['expired'] + grp['rej_carrier']
             + grp['rej_shipper'] + grp['shipper_cancelled'])
    grp['rej_pct'] = np.where(total > 0, rejected / total * 100, 0)

    # Contract type indicator -- derived from Tender Type in CL709.
    # In TMW/Gravity, "Automated" typically = routing guide (contracted),
    # "Manual" = spot/non-contracted.  Verify actual values in your data.
    if 'Tender Type' in sub.columns:
        def _contract_label(series):
            if len(series) == 0:
                return ''
            top = series.value_counts().index[0]
            top_u = str(top).strip().upper()
            if 'AUTO' in top_u:
                return 'Contracted'
            if 'MANUAL' in top_u or 'SPOT' in top_u:
                return 'Spot/Manual'
            return str(top).strip()
        tt = sub.groupby('Carrier Name')['Tender Type'].apply(_contract_label)
        grp['contract_type'] = tt
    else:
        grp['contract_type'] = ''

    # Top 5 rejecting: high rejection % with at least 50 shipments over the window.
    # Without a minimum threshold, tiny one-off carriers at 100% would dominate.
    top_rej = grp[grp['ship_count'] >= 50].sort_values('rej_pct', ascending=False).head(5).reset_index()

    # Bottom 5 (most accepting): TOP-VOLUME carriers, then sort by rejection % ascending.
    # The deck shows real high-volume carriers (Elberta, KCH, CAT, etc.), not random
    # zero-rejection one-offs.  Take the 10 highest-volume carriers, then sort by
    # rejection % ascending, then keep the top 5.
    top_volume = grp.sort_values('ship_count', ascending=False).head(10)
    bot_rej = top_volume.sort_values('rej_pct', ascending=True).head(5).reset_index()

    def render(rej_df, header):
        d = rej_df[['Carrier Name', 'contract_type', 'ship_count', 'rej_pct']].copy()
        d['rej_pct'] = d['rej_pct'].apply(lambda x: f'{x:.2f}%')
        d.columns = ['Carrier Name', 'Contract Type', 'Shipment Count', 'Tender Rejection %']
        return f'<h4>{header}</h4>' + html_table_html(d)

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    {render(top_rej, 'Top 5 Rejecting Carriers')}
    {render(bot_rej, 'Bottom Rejecting Carriers (top-volume)')}
  </div>
  <div class="col-narrative">
    {narrative_block('Top Rejecting Carriers Takeaways', narrative.get('top_takeaways', []))}
    {narrative_block('Top Accepting Carriers Takeaways', narrative.get('bottom_takeaways', []))}
  </div>
</div>
'''
    return slide_content('Top Rejecting TL Carriers - Last 3 Months', slide_num, body)


def slide_complaint_trends(df_claims: pd.DataFrame, df_712: pd.DataFrame,
                            ym_list: List[str], labels: Dict[str, str],
                            slide_num: int, narrative: Dict) -> str:
    """Slide 27 - Complaint Trends.  Layout: two charts side-by-side on top
    (Justified/Unjustified with % overlay LEFT, Complaints by BU RIGHT),
    narrative blocks in two columns below."""
    chart1 = chart_complaints_count(df_claims, ym_list, labels, df_712=df_712)
    chart2 = chart_complaints_by_bu(df_claims, ym_list, labels)
    body = f'''
<div class="complaints-layout">
  <div class="chart-row">
    <div class="chart-cell"><img src="{chart1}" alt="Justified vs Unjustified"></div>
    <div class="chart-cell"><img src="{chart2}" alt="Complaints by BU"></div>
  </div>
  <div class="narrative-row">
    <div class="col-narrative">
      {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
    </div>
    <div class="col-narrative">
      {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
    </div>
  </div>
</div>
'''
    return slide_content('Complaint Trends', slide_num, body)


def slide_claims_report(df_claims: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                        slide_num: int, narrative: Dict) -> str:
    """Slide 28: Claims report details (amounts + recoveries)."""
    report_ym = ym_list[-1]
    sub = df_claims[df_claims['YYYY_MM'].isin(ym_list)].copy() if not df_claims.empty else df_claims
    by_bu = sub.groupby('BU').agg(
        cases=('SID Number', 'count'),
        total_value=('Total Claim Value', 'sum'),
    ).round(2)
    by_bu = by_bu.reset_index()
    by_bu.columns = ['BU', 'Cases', 'Sum of Total Claim Value']
    by_bu['Sum of Total Claim Value'] = by_bu['Sum of Total Claim Value'].apply(lambda v: f'${v:,.2f}')

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    <h4>Claim Amounts</h4>
    {html_table_html(by_bu)}
    {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
  </div>
  <div class="col-narrative">
    {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
  </div>
</div>
'''
    return slide_content('Claims Report Details', slide_num, body)


def slide_expedite_trends(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                           slide_num: int, narrative: Dict) -> str:
    """Slide 33: Expedite spending & trends."""
    chart1 = chart_expedite_count_by_bu(df_712, ym_list, labels)

    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & _expedite_ob_mask(df_712)].copy()
    sub = sub[_is_expedite_mask(sub)]
    if 'BU' in sub.columns:
        # Per Akzo review (2026-07): leave Not Provided BU off graph AND table.
        sub = sub[sub['BU'] != 'Not Provided']
    if len(sub) > 0 and 'BU' in sub.columns:
        cost_tbl = sub.groupby(['BU', 'YYYY_MM'])["Normalized Ship't Actual Cost"].sum().unstack(fill_value=0)
        cost_tbl = cost_tbl.reindex(columns=ym_list, fill_value=0)
        cost_tbl['Grand Total'] = cost_tbl.sum(axis=1)
        # Add Grand Total row
        grand = cost_tbl.sum(axis=0)
        cost_tbl = cost_tbl.reset_index()
        cost_tbl.columns = ['Business Unit'] + [labels.get(y, y) for y in ym_list] + ['Grand Total']
        grand_row = pd.DataFrame([['Grand Total'] + [grand[ym] for ym in ym_list] + [grand['Grand Total']]],
                                  columns=cost_tbl.columns)
        cost_tbl = pd.concat([cost_tbl, grand_row], ignore_index=True)
        for c in cost_tbl.columns[1:]:
            cost_tbl[c] = cost_tbl[c].apply(lambda v: f'${v:,.0f}')
        cost_table_html = html_table_html(cost_tbl)
    else:
        cost_table_html = '<p>(No expedite data found for the window)</p>'

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    <div class="chart-cell"><img src="{chart1}" alt="Expedite counts by BU"></div>
    <h4>Expedite Costs by Business Unit</h4>
    {cost_table_html}
  </div>
  <div class="col-narrative">
    {narrative_block(f'{labels.get(ym_list[-2], "Prior")} Expedite BU & Spend Trends', narrative.get('prior_month', []))}
    {narrative_block(f'{labels.get(ym_list[-1], "Report")} Expedite BU & Spend Trends', narrative.get('report_month', []))}
  </div>
</div>
'''
    return slide_content('Expedite Spending & Trends by Business Unit', slide_num, body)


def chart_expedite_reasons(df_712: pd.DataFrame, ym: str, labels: Dict[str, str]) -> str:
    """Horizontal bar chart of expedite reason counts for a single month.
    Slide 34/35 top-left.  Sized bigger than the prior version (was getting
    squeezed in a half-column).
    """
    plt = _setup_matplotlib()
    sub = df_712[(df_712['YYYY_MM'] == ym) & _expedite_ob_mask(df_712)].copy()
    sub = sub[_is_expedite_mask(sub)]
    if 'Priority' not in sub.columns or len(sub) == 0:
        fig, ax = plt.subplots(figsize=(6.5, 4.0))
        ax.text(0.5, 0.5, '(no expedite data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    reasons = sub['Priority'].astype(str).str.upper().str.replace('^EXP[-\\s]+', '', regex=True)
    reasons = reasons.replace({'EXPEDITE': 'EXPEDITE (UNSPECIFIED)', 'EXPEDITE - NO FORM': 'NO FORM'})
    counts = reasons.value_counts().head(10)
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    bars = ax.barh(range(len(counts)), counts.values[::-1], color='#5DA571', height=0.7)
    ax.set_yticks(range(len(counts)))
    ax.set_yticklabels(counts.index[::-1], fontsize=11)
    ax.tick_params(axis='x', labelsize=11)
    ax.set_xlabel('Shipment Count', fontsize=12)
    ax.set_title(f'Expedite Reasons - {labels.get(ym, ym)}', fontsize=13,
                 color=COLOR_TEXT, weight='bold', loc='left')
    # Headroom on the right axis so labels fit
    xmax = counts.max()
    ax.set_xlim(0, xmax * 1.15)
    for i, v in enumerate(counts.values[::-1]):
        ax.text(v + xmax * 0.01, i, f'{int(v)}', va='center', fontsize=11, fontweight='bold')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def chart_expedite_carrier_pie(df_712: pd.DataFrame, ym: str, labels: Dict[str, str]) -> str:
    """Pie chart of expedite volume by carrier for a single month.  Slide 34/35
    top-right.  Uses the same legend-based labeling as the BU pies so carrier
    names never overlap each other outside the slice.
    """
    plt = _setup_matplotlib()
    sub = df_712[(df_712['YYYY_MM'] == ym) & _expedite_ob_mask(df_712)].copy()
    sub = sub[_is_expedite_mask(sub)]
    if 'Carrier Name' not in sub.columns or len(sub) == 0:
        fig, ax = plt.subplots(figsize=(5.8, 4.2))
        ax.text(0.5, 0.5, '(no expedite data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    counts = sub['Carrier Name'].astype(str).value_counts()
    top = counts.head(6).copy()
    if len(counts) > 6:
        top['Other'] = counts.iloc[6:].sum()
    total = top.sum()
    palette = ['#5DA571', '#F0A030', '#7E4F8F', '#5DADE2', '#D9534F', '#62B0A3', '#9AA5B8']
    fig, ax = plt.subplots(figsize=(6.0, 4.2))

    def _autopct(pct):
        return f'{pct:.1f}%' if pct >= 3.0 else ''
    wedges, texts, autotexts = ax.pie(
        top.values, colors=palette[:len(top)], startangle=90,
        autopct=_autopct, pctdistance=0.72,
        textprops={'fontsize': 11, 'color': 'white', 'weight': 'bold'},
        wedgeprops={'edgecolor': 'white', 'linewidth': 1.2},
    )
    for t in autotexts:
        t.set_color('white'); t.set_fontweight('bold'); t.set_fontsize(11)

    # Side legend with full carrier name + count + %
    def _short(name):
        return (name[:28] + '...') if len(name) > 29 else name
    legend_labels = [
        f'{_short(n)} - {int(v)} ({v/total*100:.1f}%)'
        for n, v in zip(top.index, top.values)
    ]
    ax.legend(wedges, legend_labels, loc='center left',
              bbox_to_anchor=(1.0, 0.5), fontsize=10, frameon=False,
              borderaxespad=0.5)
    ax.set_title(f'Carrier Share - {labels.get(ym, ym)} ({int(total)} shipments)',
                 fontsize=12, color=COLOR_TEXT, weight='bold', pad=8)
    plt.tight_layout()
    return fig_to_data_uri(fig)


def slide_expedite_reason(df_712: pd.DataFrame, ym: str, labels: Dict[str, str],
                          slide_num: int, narrative: Dict) -> str:
    """Slides 34 & 35: Expedite Reason & Carrier Trends for a single month.

    Two charts side-by-side on top, narrative 2-col below.  Matches the
    deck slide 34/35 deck layout.
    """
    chart1 = chart_expedite_reasons(df_712, ym, labels)
    chart2 = chart_expedite_carrier_pie(df_712, ym, labels)
    body = f'''
<div class="two-col-charts-top">
  <div class="chart-row">
    <div class="chart-cell"><img src="{chart1}" alt="Expedite reasons"></div>
    <div class="chart-cell"><img src="{chart2}" alt="Carrier share"></div>
  </div>
  <div class="narrative-row">
    <div class="col-narrative">
      {narrative_block(f'{labels.get(ym, ym)} Expedite Stats', narrative.get('items', []))}
    </div>
    <div class="col-narrative">
      {narrative_block('Expedite Form Compliance', narrative.get('compliance', []))}
    </div>
  </div>
</div>
'''
    return slide_content(f'Expedite Reason & Carrier Trends - {labels.get(ym, ym)}', slide_num, body)


def chart_temp_control_split(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Slide 31: Two stacked charts (TOP = STANDARD shipments, BOTTOM = TEMP CONTROL
    shipments) per the deck.  Each bar labeled with count + % of total OB shipments
    for that month.

    The deck shows STANDARD bars at 6000-7400 range (97%+ of total volume) and
    TEMP CONTROL bars at 170-240 range (~2-3% of total volume) on a much smaller
    y-axis, so the two groups need separate charts -- they can't share a y-axis
    without making TEMP CONTROL invisible.
    """
    plt = _setup_matplotlib()
    sub_all = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    if len(sub_all) == 0:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.text(0.5, 0.5, '(no OB data)', ha='center', va='center',
                color=COLOR_TEXT_LIGHT, fontsize=12)
        ax.axis('off')
        return fig_to_data_uri(fig)
    is_tc = _is_temp_control_mask(sub_all)
    std_sub = sub_all[~is_tc]
    tc_sub  = sub_all[is_tc]

    std_counts = std_sub.groupby('YYYY_MM').size().reindex(ym_list).fillna(0)
    tc_counts  = tc_sub.groupby('YYYY_MM').size().reindex(ym_list).fillna(0)
    total_counts = sub_all.groupby('YYYY_MM').size().reindex(ym_list).fillna(0)

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(8.0, 5.4),
                                          gridspec_kw={'height_ratios': [2.2, 1]})
    x = np.arange(len(ym_list))
    bar_w = 0.55

    # Top: STANDARD
    ax_top.bar(x, std_counts, bar_w, color='#4A6BA0', label='STANDARD')
    ax_top.set_title('Temp Control Chart', fontsize=13, color=COLOR_TEXT,
                     weight='bold', loc='left')
    ax_top.set_ylabel('Shipment Count', fontsize=11, color=COLOR_TEXT_LIGHT)
    ax_top.tick_params(axis='y', labelsize=10)
    ax_top.set_xticks(x); ax_top.set_xticklabels(['']*len(ym_list))  # hide x labels on top
    ax_top.spines['top'].set_visible(False); ax_top.spines['right'].set_visible(False)
    # Count + % labels above each bar
    for i, v in enumerate(std_counts):
        tot = total_counts.iloc[i]
        pct = (v / tot * 100) if tot > 0 else 0
        if v > 0:
            ax_top.text(i, v + std_counts.max() * 0.02,
                        f'{int(v):,}\n{pct:.2f}%',
                        ha='center', va='bottom', fontsize=11,
                        color=COLOR_TEXT, fontweight='bold')
    # Headroom for labels
    ax_top.set_ylim(0, std_counts.max() * 1.20 if std_counts.max() > 0 else 1)
    # Left annotation
    ax_top.text(-0.95, std_counts.max() / 2 if std_counts.max() > 0 else 0.5,
                'STANDARD', rotation=90, ha='center', va='center',
                fontsize=11, color=COLOR_TEXT, weight='bold')

    # Bottom: TEMP CONTROL
    ax_bot.bar(x, tc_counts, bar_w, color='#F0A030', label='TEMP CONTROL')
    ax_bot.set_ylabel('Shipment Count', fontsize=11, color=COLOR_TEXT_LIGHT)
    ax_bot.tick_params(axis='y', labelsize=10)
    ax_bot.set_xticks(x); ax_bot.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax_bot.spines['top'].set_visible(False); ax_bot.spines['right'].set_visible(False)
    for i, v in enumerate(tc_counts):
        tot = total_counts.iloc[i]
        pct = (v / tot * 100) if tot > 0 else 0
        if v > 0:
            ax_bot.text(i, v + (tc_counts.max() if tc_counts.max() > 0 else 1) * 0.04,
                        f'{int(v):,}\n{pct:.2f}%',
                        ha='center', va='bottom', fontsize=11,
                        color=COLOR_TEXT, fontweight='bold')
    ax_bot.set_ylim(0, (tc_counts.max() if tc_counts.max() > 0 else 1) * 1.32)
    ax_bot.text(-0.95, tc_counts.max() / 2 if tc_counts.max() > 0 else 0.5,
                'TEMP\nCONTROL', rotation=90, ha='center', va='center',
                fontsize=11, color=COLOR_TEXT, weight='bold')

    plt.tight_layout()
    return fig_to_data_uri(fig)


# Legacy alias so any external callers still work
def chart_temp_control_count(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Deprecated -- use chart_temp_control_split.  Kept as a thin wrapper."""
    return chart_temp_control_split(df_712, ym_list, labels)


def slide_temp_control(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                       slide_num: int, narrative: Dict) -> str:
    """Slide 31: Temperature Control Analysis by Mode.

    Per the deck:
      - Two stacked charts: STANDARD shipments (top) + TEMP CONTROL (bottom)
        with count + % of total monthly OB volume.
      - Load Count table below: rows = (BU, Equipment Type) where Equipment
        Type splits into STANDARD vs TEMP CONTROL, columns = the 3 report
        months, values = integer shipment counts.  (Previously this table
        showed Cost per Pound -- decimals like 0.090, 0.082 -- which didn't
        match the deck convention and confused presentation review.)
    """
    chart = chart_temp_control_split(df_712, ym_list, labels)

    # Build Load Count table: BU x Equipment Type (STANDARD / TEMP CONTROL)
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    count_table_html = ''
    if len(sub) > 0 and 'BU' in sub.columns:
        # Per Akzo review (2026-07): leave Not Provided BU off this slide.
        sub = sub[sub['BU'] != 'Not Provided'].copy()
        sub['EquipBand'] = np.where(_is_temp_control_mask(sub), 'TEMP CONTROL', 'STANDARD')
        # Shipment count per BU x EquipBand x month (each row = one shipment)
        counts = sub.groupby(['BU', 'EquipBand', 'YYYY_MM']).size().reset_index(name='n')

        # Wide pivot: (BU, EquipBand) rows x month columns of count
        wide = counts.pivot_table(index=['BU', 'EquipBand'], columns='YYYY_MM',
                                  values='n', fill_value=0)
        wide = wide.reindex(columns=ym_list, fill_value=0).astype(int)

        # Body rows grouped by BU, with the BU name shown only on the STANDARD
        # row and blank on the TEMP CONTROL row (matches deck Image 3 layout).
        bus_present = sorted({bu for (bu, eq) in wide.index})
        body_rows = ''
        for bu in bus_present:
            shown_bu = False
            for eq in ('STANDARD', 'TEMP CONTROL'):
                if (bu, eq) not in wide.index:
                    continue
                bu_cell = bu if not shown_bu else ''
                shown_bu = True
                cells = ''
                for ym in ym_list:
                    val = int(wide.loc[(bu, eq), ym])
                    cells += f'<td class="num">{val:,}</td>' if val > 0 else '<td class="num">-</td>'
                body_rows += (f'<tr><td class="bu-name">{bu_cell}</td>'
                              f'<td>{eq}</td>{cells}</tr>')
        header_cells = ''.join(f'<th>{labels.get(ym, ym)}</th>' for ym in ym_list)
        count_table_html = (
            '<table class="mor-table temp-cost-table editable">'
            '<caption>Load Count by BU and Equipment Type</caption>'
            f'<thead><tr><th>Business Unit</th><th>**Temp Control Equipment</th>'
            f'{header_cells}</tr></thead>'
            f'<tbody>{body_rows}</tbody>'
            '</table>'
        )

    body = f'''
<div class="two-col">
  <div class="col-narrative">
    <div class="chart-cell"><img src="{chart}" alt="Temperature control by mode"></div>
    {count_table_html}
  </div>
  <div class="col-narrative">
    {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
    {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
  </div>
</div>
'''
    return slide_content('Temperature Control Analysis by Mode', slide_num, body)


def slide_manual(title: str, slide_num: int, narrative: Dict) -> str:
    """Generic 'manual content' slide for things like Safety Moment, Operations Update."""
    items = narrative.get('items', [])
    extra = narrative.get('html', '')
    inner = bullet_list(items) + extra
    # Wrap the whole manual body in .editable so every bullet / text block on
    # slides like 'Monthly Achievements & Challenges' (19), 'Moving As One' (37),
    # 'Market News' (39) is editable in-browser and persists to localStorage.
    body = editable_text(inner) if inner.strip() else editable_text('<ul><li></li></ul>')
    return slide_content(title, slide_num, body)


# =============================================================================
# MARKET SLIDES -- extract from PPTX and embed in HTML
# =============================================================================

def _extract_pptx_slides(pptx_path: str) -> List[Dict]:
    """Extract slide content from a PPTX file (Quantix market-update deck structure).

    Returns a list of dicts:
      {
        'title': str,
        'elements': [           # canvas elements WITH original slide positions
            {'kind': 'image', 'src': data-URI,
             'left': emu, 'top': emu, 'w': emu, 'h': emu},
            {'kind': 'text',  'html': str, 'font_pt': float, 'boxed': bool,
             'left': emu, 'top': emu, 'w': emu, 'h': emu},
            {'kind': 'table', 'html': str,
             'left': emu, 'top': emu, 'w': emu, 'h': emu},
        ],
        'body_html': str,        # ph_idx=1 content placeholder, formatted HTML
        'slide_w': emu, 'slide_h': emu,
      }

    Positions are kept in raw EMU so the renderer can rescale them to the
    content region (the slide minus the title band and footer band, which the
    HTML shell renders separately).

    ph_idx=11 (brand footer) is always skipped.
    ph_idx=12 is skipped only when the text is a bare page number (single
    integer); on the cover slide ph_idx=12 holds the real title.
    """
    from pptx import Presentation
    from pptx.util import Emu
    import base64 as _b64
    import html as _html

    prs = Presentation(pptx_path)
    slide_w = prs.slide_width.emu
    slide_h = prs.slide_height.emu
    slides_data = []

    def _runs_to_html(text_frame, default_pt: float = 11.0) -> Tuple[str, float]:
        """Render a text frame to HTML preserving line breaks and bold runs.
        Returns (html, dominant_font_pt)."""
        para_parts = []
        sizes = []
        for para in text_frame.paragraphs:
            run_parts = []
            for run in para.runs:
                t = _html.escape(run.text)
                if not t:
                    continue
                if run.font.size is not None:
                    sizes.append(run.font.size.pt)
                if run.font.bold:
                    t = f'<b>{t}</b>'
                run_parts.append(t)
            para_parts.append(''.join(run_parts))
        html_out = '<br>'.join(para_parts).strip()
        # Trim leading/trailing empty lines
        while html_out.startswith('<br>'):
            html_out = html_out[4:]
        while html_out.endswith('<br>'):
            html_out = html_out[:-4]
        font_pt = (sorted(sizes)[len(sizes) // 2] if sizes else default_pt)
        return html_out, font_pt

    for slide in prs.slides:
        sd: Dict = {'title': '', 'elements': [], 'body_html': '',
                    'slide_w': slide_w, 'slide_h': slide_h}

        shapes = sorted(slide.shapes, key=lambda s: (getattr(s, 'top', 0) or 0,
                                                      getattr(s, 'left', 0) or 0))
        for shape in shapes:
            st = shape.shape_type
            left = getattr(shape, 'left', 0) or 0
            top = getattr(shape, 'top', 0) or 0
            w = getattr(shape, 'width', 0) or 0
            h = getattr(shape, 'height', 0) or 0

            # ---- PICTURE -- embed with positional data ----
            if st == 13:
                try:
                    blob = shape.image.blob
                    ext = shape.image.ext.lower()
                    mime = (
                        'image/png' if ext == 'png'
                        else 'image/jpeg' if ext in ('jpg', 'jpeg')
                        else f'image/{ext}'
                    )
                    b64 = _b64.b64encode(blob).decode()
                    sd['elements'].append({
                        'kind': 'image',
                        'src': f'data:{mime};base64,{b64}',
                        'left': left, 'top': top,
                        'w': w or slide_w, 'h': h or slide_h,
                    })
                except Exception:
                    pass
                continue

            # ---- TABLE ----
            if st == 19:
                try:
                    tbl = shape.table
                    rows_html = []
                    for r_idx, row in enumerate(tbl.rows):
                        cells = [c.text_frame.text.strip() for c in row.cells]
                        tag = 'th' if r_idx == 0 else 'td'
                        row_html = ''.join(f'<{tag}>{_html.escape(c)}</{tag}>' for c in cells)
                        rows_html.append(f'<tr>{row_html}</tr>')
                    sd['elements'].append({
                        'kind': 'table',
                        'html': ''.join(rows_html),
                        'left': left, 'top': top, 'w': w, 'h': h,
                    })
                except Exception:
                    pass
                continue

            # ---- PLACEHOLDER ----
            if getattr(shape, 'is_placeholder', False):
                try:
                    ph_idx = shape.placeholder_format.idx
                except Exception:
                    ph_idx = None

                try:
                    text = shape.text_frame.text.strip() if shape.has_text_frame else ''
                except Exception:
                    text = ''

                # Always skip brand footer
                if ph_idx == 11:
                    continue
                # Skip page-number placeholder (idx=12) only when its text IS a
                # bare integer (e.g. "3", "17").  On the cover slide idx=12 holds
                # the real title ("Market Update\nJune 2026") -- keep it.
                if ph_idx == 12:
                    if text.replace('\n', '').strip().isdigit():
                        continue
                    if not sd['title'] and text:
                        sd['title'] = text
                    continue

                if ph_idx == 0 and text:
                    sd['title'] = text
                elif ph_idx == 1 and text:
                    body_html, _pt = _runs_to_html(shape.text_frame)
                    sd['body_html'] = body_html
                continue

            # ---- TEXT BOX / AUTO SHAPE with text ----
            try:
                if shape.has_text_frame:
                    text = shape.text_frame.text.strip()
                    if text:
                        html_out, font_pt = _runs_to_html(shape.text_frame)
                        sd['elements'].append({
                            'kind': 'text',
                            'html': html_out,
                            'font_pt': font_pt,
                            'boxed': st == 1,   # AUTO_SHAPE -> render as callout box
                            'left': left, 'top': top, 'w': w, 'h': h,
                        })
            except Exception:
                pass

        slides_data.append(sd)

    return slides_data


def slide_market_slides_section(pptx_path: str, slide_start_num: int,
                                section_title: str = 'Market Update',
                                only: str = 'all') -> str:
    """Build HTML section(s) from a market-update PPTX file.

    `only` controls which slides are returned:
      'all'   -> every market slide (default, original behavior)
      'first' -> ONLY the first rendered market slide (the Monthly Safety
                 Share). Used to place it right after the agenda.
      'rest'  -> every market slide EXCEPT the first, used at the end of the
                 deck so the safety share is not duplicated.


    Each slide with chart content is rendered in a positioned canvas that
    reproduces the original layout: images, text labels (week-of headers,
    takeaway bullets, fuel callouts) and DAT rate tables are all placed at
    their original slide coordinates.  Two corrections versus the raw PPTX
    geometry:

      1. The canvas is cropped to the CONTENT region (the slide minus the
         title band at top and footer band at bottom), because the HTML shell
         renders the slide title and footer itself.  This removes the large
         blank bands the old renderer produced.
      2. Text is sized with container-query units (cqw) so labels scale with
         the canvas; 1% of slide width = 9.6pt at PPTX-native scale.

    Slides with no real content (cover, closing logo slide) are skipped.
    All content is base64-embedded for a self-contained HTML file.
    """
    try:
        slides_data = _extract_pptx_slides(pptx_path)
    except Exception as e:
        return slide_content(
            section_title, slide_start_num,
            f'<p class="placeholder">[Error loading market slides from {pptx_path}: {e}]</p>'
        )

    if not slides_data:
        return slide_content(
            section_title, slide_start_num,
            '<p class="placeholder">No slides found in PPTX.</p>'
        )

    import html as _html2

    out_parts = []
    slide_num = slide_start_num
    # Skip only the deck's filler slides (a bare "Moving As One" divider with no
    # real content).  Safety-share and market-news slides ARE kept -- they are
    # part of the market deck the user wants rendered.
    _SKIP_TITLE_SUBSTRINGS = ('moving as one',)

    for i, sd in enumerate(slides_data):
        title = sd['title'] or f'{section_title} - Slide {i + 1}'
        _tl = title.strip().lower()
        if any(sub in _tl for sub in _SKIP_TITLE_SUBSTRINGS):
            print(f'  Skipping market deck filler slide: {title!r}', flush=True)
            continue
        slide_w = sd['slide_w']
        slide_h = sd['slide_h']
        elements = sd['elements']

        imgs = [e for e in elements if e['kind'] == 'image']
        txts = [e for e in elements if e['kind'] == 'text']
        total_img_area_pct = sum(
            (e['w'] / slide_w) * (e['h'] / slide_h) for e in imgs
        )
        # Canvas mode when images cover a meaningful share of the slide.
        # (Original behavior -- the positioned canvas reproduces the deck layout
        # faithfully for both chart slides and text+image slides.)
        use_canvas = total_img_area_pct >= 0.10

        # Skip slides with no renderable content: covers and closing slides
        # (a lone logo < 10% of slide area, no body text, no table, no labels).
        has_table = any(e['kind'] == 'table' for e in elements)
        has_text = len(txts) > 0
        if not (use_canvas or sd['body_html'] or has_table or has_text):
            continue

        body_parts = []

        # Body text (content placeholder -- e.g. railroad news slide).
        if sd['body_html']:
            body_parts.append(
                f'<p class="editable" style="margin:0 0 10px;font-size:13.5px;line-height:1.55;">'
                f'{sd["body_html"]}</p>'
            )

        if use_canvas:
            # --- Content region: crop the title band (everything above the
            # topmost canvas element) and the footer band (below the lowest).
            pad_v = int(slide_h * 0.012)   # small breathing room
            content_top = max(0, min(e['top'] for e in elements) - pad_v)
            content_bottom = min(slide_h, max(e['top'] + e['h'] for e in elements) + pad_v)
            content_h = max(content_bottom - content_top, 1)

            # Canvas aspect matches the cropped region so nothing distorts.
            canvas_pad_pct = content_h / slide_w * 100
            canvas_css = (
                f'position:relative;width:100%;padding-top:{canvas_pad_pct:.3f}%;'
                'background:#fff;overflow:hidden;border:1px solid #e0e0e0;'
                'border-radius:4px;container-type:inline-size;'
            )

            def _pos_css(e) -> str:
                return (
                    f'left:{e["left"] / slide_w * 100:.3f}%;'
                    f'top:{(e["top"] - content_top) / content_h * 100:.3f}%;'
                    f'width:{e["w"] / slide_w * 100:.3f}%;'
                    f'height:{e["h"] / content_h * 100:.3f}%;'
                )

            el_tags = []
            for e in elements:
                if e['kind'] == 'image':
                    el_tags.append(
                        f'<img src="{e["src"]}" alt="" '
                        f'style="position:absolute;object-fit:contain;{_pos_css(e)}">'
                    )
                elif e['kind'] == 'text':
                    # 1cqw = 1% of canvas width = 9.6pt of original slide text.
                    fs = max(e.get('font_pt', 11.0), 8.0) / 9.6
                    boxed_css = (
                        'background:#F4F6F8;border:1px solid #D9DEE6;'
                        'border-radius:6px;padding:0.6cqw 0.9cqw;'
                        if e.get('boxed') else ''
                    )
                    el_tags.append(
                        f'<div class="editable" style="position:absolute;{_pos_css(e)}'
                        f'height:auto;font-size:{fs:.2f}cqw;line-height:1.35;'
                        f'color:#1F2A44;{boxed_css}">{e["html"]}</div>'
                    )
                elif e['kind'] == 'table':
                    el_tags.append(
                        f'<div style="position:absolute;{_pos_css(e)}height:auto;">'
                        f'<table class="editable" style="width:100%;border-collapse:collapse;'
                        f'font-size:1.1cqw;background:#fff;">{e["html"]}</table></div>'
                    )

            # Scoped styling for in-canvas tables (DAT rate tables).
            tbl_style = (
                '<style>'
                '.mkt-canvas table th{background:#1B2541;color:#fff;'
                'padding:0.4cqw 0.6cqw;border:1px solid #D9DEE6;text-align:center;}'
                '.mkt-canvas table td{padding:0.4cqw 0.6cqw;border:1px solid #D9DEE6;'
                'text-align:center;}'
                '</style>'
            )
            body_parts.append(
                f'{tbl_style}<div class="mkt-canvas" style="{canvas_css}">'
                f'{"".join(el_tags)}</div>'
            )
        else:
            # No-canvas slide (text/table only): flow content vertically in
            # original top-to-bottom order.
            for e in sorted(elements, key=lambda x: (x['top'], x['left'])):
                if e['kind'] == 'text':
                    body_parts.append(
                        f'<p class="editable" style="margin:6px 0;font-size:13px;line-height:1.5;">'
                        f'{e["html"]}</p>'
                    )
                elif e['kind'] == 'table':
                    body_parts.append(
                        '<table class="data-table editable" style="width:100%;'
                        'border-collapse:collapse;font-size:13px;margin:8px 0;">'
                        f'{e["html"]}</table>'
                    )
                elif e['kind'] == 'image':
                    w_pct = e['w'] / slide_w * 100
                    body_parts.append(
                        f'<div style="text-align:center;"><img src="{e["src"]}" alt="" '
                        f'style="max-width:{min(w_pct * 2, 60):.0f}%;max-height:200px;'
                        f'object-fit:contain;margin:8px auto;display:block;"></div>'
                    )

        out_parts.append(slide_content(title, slide_num, '\n'.join(body_parts)))
        slide_num += 1

    # Split out the first rendered slide (Monthly Safety Share) when requested
    # so it can be placed right after the agenda while the remaining market
    # slides stay at the end of the deck.
    if only == 'first':
        out_parts = out_parts[:1]
    elif only == 'rest':
        out_parts = out_parts[1:]
    return '\n'.join(out_parts)


def chart_weight_by_bu_stacked(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str]) -> str:
    """Stacked bar of total weight by BU across 3 months.  Slide 22."""
    plt = _setup_matplotlib()
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    if 'BU' not in sub.columns or len(sub) == 0:
        return ''
    grp = sub.groupby(['YYYY_MM', 'BU'])['Normalized Weight'].sum().unstack(fill_value=0)
    grp = grp.reindex(ym_list).fillna(0)
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    x = np.arange(len(ym_list))
    bar_w = 0.6
    bottom = np.zeros(len(ym_list))
    for bu in grp.columns:
        color = BU_COLORS.get(bu, '#7AAFB5')
        ax.bar(x, grp[bu], bar_w, bottom=bottom, color=color, label=bu)
        for i, v in enumerate(grp[bu]):
            tot = grp.iloc[i].sum()
            if v > 0 and tot > 0 and v / tot >= 0.05:
                ax.text(i, bottom[i] + v / 2, f'{v/tot*100:.1f}%',
                        ha='center', va='center', color='white', fontsize=11)
        bottom += grp[bu].values
    ax.set_xticks(x); ax.set_xticklabels([labels.get(y, y) for y in ym_list], fontsize=12)
    ax.set_ylabel('Total Weight', fontsize=12)
    ax.set_title('Total Weight by BU', fontsize=13, color=COLOR_TEXT)
    ax.legend(fontsize=11, frameon=False, loc='upper left', bbox_to_anchor=(1.0, 1.0))
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(
        lambda v, _: f'{v/1e6:.0f}M' if v >= 1e6 else f'{v/1e3:.0f}K'))
    return fig_to_data_uri(fig)


def slide_weight_analysis(df_712: pd.DataFrame, ym_list: List[str], labels: Dict[str, str],
                           slide_num: int, narrative: Dict) -> str:
    """Slide 22: Shipping Weight Analysis.

    Two charts side-by-side on top, narrative 2-col below:
      LEFT  chart: Total Weight stacked by Mode (LTL bottom, TL top), % labels
      RIGHT chart: Average Weight by Mode (lines) with TL/LTL market avg refs

    Splitting the metrics into two separate charts (vs the prior combined
    dual-axis chart) eliminates the label-overlap problems and matches the
    user-preferred 2-graph layout.
    """
    chart_total = chart_weight_by_mode(df_712, ym_list, labels)
    chart_avg = chart_avg_weight_with_market(df_712, ym_list, labels)

    # Auto-derived MoM bullets (kept from prior version)
    sub = df_712[(df_712['YYYY_MM'].isin(ym_list)) & (df_712.get('IB_OB') == 'OB')].copy()
    auto_paragraphs = []
    if len(sub) > 0:
        totals = sub.groupby('YYYY_MM')['Normalized Weight'].sum().reindex(ym_list).fillna(0)
        if len(totals) >= 2 and totals.iloc[-2] > 0:
            cur, prev = totals.iloc[-1], totals.iloc[-2]
            pct = (cur - prev) / prev * 100
            verb = 'increased' if pct >= 0 else 'decreased'
            auto_paragraphs.append(
                f'Total Weight Shipped {verb} {abs(pct):.1f}% from '
                f'{labels.get(ym_list[-2], "prior")} to {labels.get(ym_list[-1], "report")}.'
            )

        # Per-BU breakdown (report month vs prior month)
        if 'BU' in sub.columns and len(ym_list) >= 2:
            bu_grp = sub.groupby(['YYYY_MM', 'BU'])['Normalized Weight'].sum().unstack(fill_value=0)
            bu_grp = bu_grp.reindex(ym_list).fillna(0)
            bu_lines = []
            for bu in sorted(bu_grp.columns):
                prev_v = bu_grp.iloc[-2].get(bu, 0)
                cur_v  = bu_grp.iloc[-1].get(bu, 0)
                if prev_v <= 0: continue
                pct = (cur_v - prev_v) / prev_v * 100
                verb = 'increased' if pct >= 0 else 'decreased'
                bu_lines.append(f'{bu}: {verb} {abs(pct):.1f}% MoM')
            if bu_lines:
                auto_paragraphs.append('BU breakdown (report month vs prior): ' + '; '.join(bu_lines))

    auto_html = ''.join(f'<p>{p}</p>' for p in auto_paragraphs)
    auto_block = (f'<div class="narrative-block"><h4>Auto-derived</h4>'
                  f'<div class="editable">{auto_html}</div></div>'
                  if auto_html else '')

    body = f'''
<div class="two-col-charts-top">
  <div class="chart-row">
    <div class="chart-cell"><img src="{chart_total}" alt="Total Weight by Mode"></div>
    <div class="chart-cell"><img src="{chart_avg}" alt="Average Weight by Mode"></div>
  </div>
  <div class="narrative-row">
    <div class="col-narrative">
      {auto_block}
      {narrative_block('Historical Performance Analysis', narrative.get('history', []))}
      {narrative_block('Root Cause Analysis', narrative.get('rca', []))}
    </div>
    <div class="col-narrative">
      {narrative_block('Performance Improvement Action Plan', narrative.get('plan', []))}
    </div>
  </div>
</div>
'''
    return slide_content('Shipping Weight Analysis', slide_num, body)

# =============================================================================
# 7. CSS  (mirrors the deck's navy + lime + white aesthetic)
# =============================================================================
CSS = f'''
* {{ box-sizing: border-box; }}
body {{
    font-family: Calibri, 'Segoe UI', Arial, sans-serif;
    color: {COLOR_TEXT};
    background: {COLOR_CREAM};
    margin: 0;
    padding: 0;
    line-height: 1.45;
    font-size: 14px;
}}
section {{
    width: 95%;
    max-width: 1280px;
    margin: 24px auto;
    background: white;
    border: 1px solid {COLOR_BORDER};
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    border-radius: 4px;
    page-break-after: always;
    position: relative;
    min-height: 720px;
    padding: 36px 48px 48px;
}}

/* Title slide */
.mor-title {{
    background: {COLOR_NAVY};
    color: white;
    min-height: 560px;
    padding: 0;
    overflow: hidden;
    display: grid;
    grid-template-columns: 220px 1fr;
}}
.title-stripes {{ display: flex; flex-direction: column; height: 100%; }}
.title-stripes .stripe {{ flex: 1; }}
.title-stripes .lime {{ background: {COLOR_LIME}; }}
.title-stripes .white {{ background: white; }}
.title-stripes .navy {{ background: {COLOR_NAVY_2}; }}
.title-content {{
    padding: 60px 60px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.title-content h1 {{
    font-size: 60pt;
    color: #4A8FCF;
    margin: 0 0 24px;
    font-weight: 600;
    letter-spacing: -1px;
}}
.title-content .title-month {{
    font-size: 36pt;
    margin: 0;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
.title-brand {{
    margin-top: 60px;
    font-size: 20pt;
    color: {COLOR_LIME};
    font-weight: 700;
}}

/* Agenda */
.mor-agenda {{
    background: {COLOR_NAVY};
    color: white;
    min-height: 560px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 60px;
    padding: 80px 90px;
}}
.agenda-title {{
    font-size: 40pt;
    margin: 0;
    color: white;
    font-weight: 700;
}}
.agenda-list {{
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 15pt;
    line-height: 2.2;
    counter-reset: agenda;
}}
.agenda-list li {{ counter-increment: agenda; }}
.agenda-list li::before {{ content: counter(agenda) ". "; color: {COLOR_LIME}; font-weight: bold; }}

/* Section dividers */
.mor-divider {{
    background: {COLOR_NAVY};
    color: white;
    min-height: 360px;
    display: flex;
    align-items: center;
    padding: 40px 80px;
    border: none;
}}
.divider-flag {{
    width: 80px; height: 16px;
    background: {COLOR_LIME};
    clip-path: polygon(0 0, 100% 0, 85% 100%, 0 100%);
    margin-right: 28px;
}}
.divider-title {{
    font-size: 34pt;
    color: white;
    margin: 0;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}

/* Content slides */
.mor-content {{
    padding: 36px 48px 70px;
}}
.content-flag {{
    width: 56px; height: 6px;
    background: {COLOR_LIME};
    margin-bottom: 14px;
}}
.content-title {{
    font-size: 28pt;
    font-weight: 700;
    color: {COLOR_NAVY};
    margin: 0 0 28px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    line-height: 1.15;
}}
.content-body {{ font-size: 11pt; line-height: 1.5; }}
.content-body h4 {{
    color: {COLOR_NAVY};
    font-size: 12.5pt;
    margin: 18px 0 6px;
    font-weight: 700;
    letter-spacing: 0.2px;
}}
.content-body h4:first-child {{ margin-top: 4px; }}
.content-body ul {{ margin: 6px 0 12px 0; padding-left: 22px; }}
.content-body li {{ margin: 3px 0; line-height: 1.45; }}
.content-body p {{ margin: 6px 0; }}
.content-footer {{
    position: absolute;
    bottom: 16px; left: 48px; right: 48px;
    display: flex; justify-content: space-between;
    color: {COLOR_TEXT_LIGHT}; font-size: 10pt;
    border-top: 1px solid {COLOR_BORDER};
    padding-top: 8px;
}}
.content-footer .brand {{ color: {COLOR_NAVY_2}; font-weight: 700; font-size: 13pt; letter-spacing: 0.3px; }}

/* Layouts */
.two-col {{
    display: grid;
    grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.4fr);
    gap: 28px;
}}
.col-narrative {{ font-size: 11.5pt; }}
.col-charts.grid-2x2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 12px;
}}
.chart-cell img {{ width: 100%; height: auto; display: block; }}
.chart-cell {{ background: white; padding: 4px; border: 1px solid {COLOR_BORDER}; border-radius: 3px; }}

.two-col-charts-top {{ display: flex; flex-direction: column; gap: 18px; }}
.chart-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.narrative-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}

.exceptions-grid {{
    display: grid;
    grid-template-columns: 1.4fr 1.4fr 1fr;
    gap: 18px;
    font-size: 10pt;
}}
.ex-mode-header {{
    background: {COLOR_NAVY};
    color: white !important;
    padding: 6px 10px;
    margin: 0 0 6px !important;
    text-align: center;
    font-size: 11pt !important;
}}
.totals-line {{ font-size: 10pt; margin-top: 4px; color: {COLOR_TEXT}; }}
.ex-legend p {{ font-size: 9.5pt; margin: 4px 0; line-height: 1.35; }}

/* Slide 24 tender: chart + BU table on left (2/3 width), narrative right (1/3). */
.tender-layout {{
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 24px;
}}
.tender-main {{ display: flex; flex-direction: column; gap: 12px; }}

/* Slide 27 complaint trends: 2 charts side-by-side on top, narrative in 2-col
   underneath.  .chart-row enforces equal-width columns regardless of image
   aspect ratio so the two charts feel balanced. */
.complaints-layout {{ display: flex; flex-direction: column; gap: 18px; }}
.complaints-layout .chart-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
}}
.complaints-layout .chart-row .chart-cell img {{ width: 100%; height: auto; }}
.complaints-layout .narrative-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
}}

/* Tables */
.mor-table {{
    border-collapse: collapse;
    margin: 8px 0 12px;
    font-size: 10pt;
    width: 100%;
    background: white;
}}
.mor-table caption {{
    background: {COLOR_NAVY};
    color: white;
    padding: 6px 10px;
    text-align: center;
    font-weight: 600;
    font-size: 11pt;
    letter-spacing: 0.3px;
}}
.mor-table th {{
    background: #E6EAF1;
    color: {COLOR_NAVY};
    padding: 7px 10px;
    border: 1px solid {COLOR_BORDER};
    font-weight: 700;
    text-align: center;
    font-size: 9.5pt;
    line-height: 1.25;
}}
.mor-table td {{
    padding: 6px 10px;
    border: 1px solid {COLOR_BORDER};
    background: #F7F9FC;
    color: {COLOR_TEXT};
    text-align: center;
    line-height: 1.3;
}}
.mor-table td:first-child {{
    text-align: left;
    font-weight: 500;
}}
.mor-table tbody tr:nth-child(even) td {{ background: #FFFFFF; }}
.mor-table tbody tr:hover td {{ background: #EEF3FA; }}

/* Tender BU table with grouped month headers (matches deck slide 24 format):
   row 1 spans 2 cols per month, row 2 has Shipment Count + Tender Rejection %. */
.tender-bu-table {{ font-size: 10pt; }}
.tender-bu-table .tender-month-hdr {{
    background: {COLOR_NAVY};
    color: white;
    text-align: center;
    border-bottom: 1px solid {COLOR_NAVY};
    padding: 6px 10px;
    font-weight: 600;
}}
.tender-bu-table .tender-sub-hdr {{
    background: #EEF1F6;
    color: {COLOR_TEXT};
    text-align: center;
    font-weight: 600;
    font-size: 9.5pt;
    padding: 5px 6px;
    border-bottom: 1px solid {COLOR_BORDER};
}}
.tender-bu-table .tender-bu-hdr {{
    background: {COLOR_NAVY};
    color: white;
    vertical-align: middle;
    text-align: left;
    padding: 6px 10px;
    font-weight: 600;
}}
.tender-bu-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.tender-bu-table td.bu-name {{ text-align: left; font-weight: 500; }}

/* Slide 31 Cost per Pound table */
.temp-cost-table {{ font-size: 10pt; }}
.temp-cost-table caption {{
    caption-side: top;
    text-align: center;
    font-weight: 600;
    color: {COLOR_TEXT};
    padding: 4px 0;
    font-size: 11pt;
}}
.temp-cost-table th {{
    background: {COLOR_NAVY};
    color: white;
    text-align: center;
    padding: 5px 8px;
}}
.temp-cost-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.temp-cost-table td.bu-name {{ text-align: left; font-weight: 600; }}

/* ---- Editable narrative blocks (Ops team can edit inline) ---- */
.narrative-block {{ margin: 4px 0; }}
.narrative-block h4 {{ margin: 8px 0 4px; color: {COLOR_NAVY}; font-size: 11.5pt; }}
.editable {{
    border: 1px dashed transparent;
    padding: 6px 8px;
    border-radius: 3px;
    transition: border-color 0.15s, background 0.15s;
    cursor: text;
    min-height: 20px;
    margin: 0;
}}
.editable:hover {{ border-color: #C0DB3F; background: #FCFEF2; }}
.editable:focus {{ border-color: {COLOR_NAVY}; background: #FFFFFF; outline: none; }}
.editable[data-dirty="true"] {{ background: #FCF9EF; }}
.editable[data-dirty="true"]:hover {{ background: #FCFEF2; }}
/* Tables carrying .editable: cells are individually editable (set in JS). */
table.editable {{ padding: 0; }}
table.editable td[contenteditable="true"]:hover,
table.editable th[contenteditable="true"]:hover {{ outline: 1px dashed #C0DB3F; outline-offset: -1px; cursor: text; }}
table.editable td[contenteditable="true"]:focus,
table.editable th[contenteditable="true"]:focus {{ outline: 2px solid {COLOR_NAVY}; outline-offset: -2px; background: #FFFFFF; }}
table.editable td[data-dirty="true"],
table.editable th[data-dirty="true"] {{ background: #FCF9EF; }}
/* mor-table editable cells: subtle hover so the user knows cells are editable. */
.mor-table.editable td[contenteditable="true"]:hover,
.mor-table.editable th[contenteditable="true"]:hover {{ outline: 1px dashed #C0DB3F; outline-offset: -1px; cursor: text; }}
.mor-table.editable td[contenteditable="true"]:focus,
.mor-table.editable th[contenteditable="true"]:focus {{ outline: 2px solid {COLOR_NAVY}; outline-offset: -2px; }}
.mor-table.editable td[data-dirty="true"] {{ background: #FCF9EF !important; }}
/* Headings/titles/captions auto-tagged as .editable: use a non-intrusive
   outline affordance instead of the dashed-border+padding used for bullet
   blocks, so the deck layout (title bands, dividers, table captions) is not
   shifted.  Editing + localStorage persistence still apply. */
.content-title.editable, .divider-title.editable, .title-month.editable,
.agenda-title.editable, .agenda-list li.editable,
.narrative-block h4.editable, caption.editable,
.mor-content h3.editable, .mor-content h4.editable {{
    border: none;
    padding: 0;
    min-height: 0;
    border-radius: 2px;
}}
.content-title.editable:hover, .divider-title.editable:hover,
.title-month.editable:hover, .agenda-title.editable:hover,
.agenda-list li.editable:hover, .narrative-block h4.editable:hover,
caption.editable:hover, .mor-content h3.editable:hover,
.mor-content h4.editable:hover {{
    outline: 1px dashed #C0DB3F; outline-offset: 2px; background: transparent; cursor: text;
}}
.content-title.editable:focus, .divider-title.editable:focus,
.title-month.editable:focus, .agenda-title.editable:focus,
.agenda-list li.editable:focus, .narrative-block h4.editable:focus,
caption.editable:focus, .mor-content h3.editable:focus,
.mor-content h4.editable:focus {{
    outline: 2px solid {COLOR_NAVY}; outline-offset: 2px; background: transparent;
}}
/* Dark-background editables (agenda items + title month) sit on navy: the
   base dirty-state cream fill and a navy focus outline are wrong there -- the
   cream box kills legibility and a navy outline is invisible. Force transparent
   fill in ALL states and use a lime outline on dark. */
.agenda-list li.editable,
.agenda-list li.editable[data-dirty="true"],
.agenda-list li.editable:hover,
.agenda-list li.editable:focus,
.agenda-title.editable,
.agenda-title.editable[data-dirty="true"],
.title-month.editable,
.title-month.editable[data-dirty="true"] {{
    background: transparent !important;
    color: inherit !important;
}}
.agenda-list li.editable:hover,
.agenda-title.editable:hover,
.title-month.editable:hover {{
    outline: 1px dashed #C0DB3F !important; background: transparent !important;
}}
.agenda-list li.editable:focus,
.agenda-title.editable:focus,
.title-month.editable:focus {{
    outline: 2px solid #C0DB3F !important; background: transparent !important;
}}
/* Light-background heading editables: suppress the dirty-state cream box. */
.content-title.editable[data-dirty="true"],
.divider-title.editable[data-dirty="true"],
.narrative-block h4.editable[data-dirty="true"],
caption.editable[data-dirty="true"],
.mor-content h3.editable[data-dirty="true"],
.mor-content h4.editable[data-dirty="true"] {{
    background: transparent !important;
}}
/* In-canvas editable text: keep absolute positioning intact. */
.mkt-canvas .editable {{ padding: 0; }}
.mkt-canvas .editable:hover {{ background: rgba(192,219,63,0.12); }}
.edit-toolbar {{
    position: fixed; top: 12px; right: 12px;
    background: {COLOR_NAVY}; color: white;
    padding: 6px 10px; border-radius: 4px;
    font-size: 11px; z-index: 9999;
    display: flex; gap: 6px; align-items: center;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}}
.edit-toolbar button {{
    background: #C0DB3F; color: {COLOR_NAVY};
    border: none; padding: 3px 9px;
    border-radius: 3px; cursor: pointer;
    font-weight: 600; font-size: 11px;
}}
.edit-toolbar button:hover {{ background: #D5EE5A; }}
.edit-toolbar .edit-status {{ opacity: 0.85; min-width: 110px; }}

/* ---- Clickable charts: lightbox (click to enlarge, click again to close) ---- */
.chart-cell img {{
    cursor: zoom-in;
    transition: opacity 0.15s, box-shadow 0.15s;
}}
.chart-cell img:hover {{ opacity: 0.92; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
.lightbox-backdrop {{
    position: fixed; inset: 0;
    background: rgba(20, 32, 56, 0.88);
    z-index: 10000;
    display: none;
    align-items: center;
    justify-content: center;
    cursor: zoom-out;
    padding: 30px;
}}
.lightbox-backdrop.active {{ display: flex; }}
.lightbox-backdrop img {{
    max-width: 96vw;
    max-height: 92vh;
    width: auto;
    height: auto;
    object-fit: contain;
    box-shadow: 0 8px 40px rgba(0,0,0,0.6);
    border-radius: 4px;
    background: white;
    cursor: zoom-out;
}}
.lightbox-close {{
    position: absolute; top: 16px; right: 22px;
    color: white; background: rgba(0,0,0,0.4);
    border: none; padding: 6px 14px;
    font-size: 14px; font-weight: 600;
    border-radius: 4px; cursor: pointer;
}}
.lightbox-close:hover {{ background: rgba(0,0,0,0.6); }}
.lightbox-hint {{
    position: absolute; bottom: 18px; left: 50%;
    transform: translateX(-50%);
    color: rgba(255,255,255,0.7);
    font-size: 12px;
}}

@media print {{
    @page {{ size: 1290px 1040px; margin: 0; }}
    html, body {{ background: white; margin: 0 !important; padding: 0 !important; }}
    section {{
        box-shadow: none !important; border: none !important;
        margin: 0 auto !important; width: 1280px !important; max-width: 1280px !important;
        min-height: 1010px !important; height: auto !important; overflow: visible !important;
        page-break-after: always !important; break-after: page !important;
        page-break-inside: avoid !important; break-inside: avoid !important;
        box-sizing: border-box !important;
    }}
    section:last-of-type {{ page-break-after: auto !important; }}
    .edit-toolbar {{ display: none !important; }}
    .editable {{ border: none !important; background: transparent !important; padding: 0 !important; }}
    .editable[data-dirty="true"] {{ background: transparent !important; }}
    .lightbox-backdrop {{ display: none !important; }}
    .slide-hide-btn, .mor-hidden-label {{ display: none !important; }}
    section.mor-hidden {{ display: none !important; }}
    .chart-cell img {{ cursor: default; }}
}}
'''

# =============================================================================
# 8. ASSEMBLE FULL HTML
# =============================================================================
def build_full_html(perf_df: pd.DataFrame, df_712: pd.DataFrame,
                    df_tender: Optional[pd.DataFrame], df_claims: Optional[pd.DataFrame],
                    ym_list: List[str], labels: Dict[str, str], report_ym: str,
                    narrative: Dict,
                    market_pptx_path: Optional[str] = None,
                    perf_df_all_moves: Optional[pd.DataFrame] = None,
                    df_712_allmoves: Optional[pd.DataFrame] = None,
                    gen_info: str = '') -> str:
    """Assemble the full MOR-style HTML report."""
    # OTP/OTD slides count all movement types; fall back to perf_df if the
    # all-moves frame wasn't supplied (keeps older callers working).
    if perf_df_all_moves is None:
        perf_df_all_moves = perf_df
    # Weight + cost-per-lb slides compute on the full 712 billing population
    # (all movement types); fall back to the OB df_712 if not supplied.
    if df_712_allmoves is None:
        df_712_allmoves = df_712
    # Defensive: if the caller forgot to run compute_super_adjusted (or is using
    # an older version of the perf script), do it here so we don't crash with a
    # confusing KeyError deep inside a chart helper.
    required_sa_cols = ['SA_PU_OT', 'SA_PU_Late', 'SA_Del_OT', 'SA_Del_Late']
    missing = [c for c in required_sa_cols if c not in perf_df.columns]
    if missing:
        print(f'WARN: SA columns missing ({missing}); running compute_super_adjusted now.', flush=True)
        try:
            perf_mod = _import_perf_module()
            perf_df = perf_mod.compute_super_adjusted(perf_df)
            df_712 = perf_df  # same frame
        except Exception as e:
            print(f'ERROR: could not auto-compute SA columns: {e}', flush=True)
            for c in required_sa_cols:
                if c not in perf_df.columns:
                    perf_df[c] = 0

    # Normalize alternate column names so the chart helpers find what they expect.
    # The perf script calls the BU column 'Business Unit'; the chart helpers expect 'BU'.
    # Origin City is the actual physical-site city from 810 (e.g. 'GREENSBORO').
    # Origin Name is the legal entity name from 712 (e.g. 'Akzo Nobel Coatings') --
    # those are NOT the same thing.  If Origin City is missing, fall back to Origin
    # Loc Code rather than Origin Name to avoid the "Akzo Nobel Coatings" labels
    # in the top-3 sites table.
    rename_aliases = {
        'Business Unit': 'BU',
    }
    for src, dst in rename_aliases.items():
        if src in perf_df.columns and dst not in perf_df.columns:
            perf_df[dst] = perf_df[src]
        if src in df_712.columns and dst not in df_712.columns:
            df_712[dst] = df_712[src]
        # df_712_allmoves feeds the weight + cost-per-lb slides and the CPP chart
        # filters on BU -- without this rename its BU column is missing and the
        # chart renders the "(no cost-per-lb data)" placeholder.
        if (df_712_allmoves is not None and src in df_712_allmoves.columns
                and dst not in df_712_allmoves.columns):
            df_712_allmoves[dst] = df_712_allmoves[src]
    # Ensure Origin City column exists; fall back to Origin Loc Code if it doesn't
    if 'Origin City' not in perf_df.columns:
        if 'Origin Loc Code' in perf_df.columns:
            perf_df['Origin City'] = perf_df['Origin Loc Code'].astype(str).str.upper()
        else:
            perf_df['Origin City'] = ''
    else:
        # Uppercase + strip to match deck formatting
        perf_df['Origin City'] = perf_df['Origin City'].fillna('').astype(str).str.strip().str.upper()
    if 'Origin City' not in df_712.columns:
        df_712['Origin City'] = perf_df.get('Origin City', '')

    # Ensure IB_OB column exists.  prepare_dataset already filters to outbound,
    # but the chart helpers re-filter by IB_OB=='OB' as a safety check, so make
    # sure the column is present with the right value.
    if 'IB_OB' not in perf_df.columns:
        perf_df['IB_OB'] = 'OB'
    if 'IB_OB' not in df_712.columns:
        df_712['IB_OB'] = 'OB'
    if df_712_allmoves is not None and 'IB_OB' not in df_712_allmoves.columns:
        df_712_allmoves['IB_OB'] = 'OB'

    # Normalize BU values to canonical names across ALL data frames.  Live SQL
    # has mixed casing ("METAL", "Metal", "POWDER", "Powder") and some sources
    # use the long SMU names ("Marine and Protective Coatings", "Wood Coatings").
    # Without normalization:
    #   - Slide 24 tender BU table shows METAL + Metal as two rows.
    #   - Slide 27 Complaints by BU chart shows the same BU in two colors and
    #     the BU_COLORS dict doesn't hit cleanly so "Not Provided" / "Wood
    #     Coatings" fall through to a default teal that collides with the
    #     VR/Specialty teal in the legend.
    # The module-level normalize_bu() handles all the casing/spacing variants.
    if 'BU' in perf_df.columns:
        perf_df['BU'] = perf_df['BU'].apply(normalize_bu)
    if perf_df_all_moves is not None and 'BU' in perf_df_all_moves.columns:
        perf_df_all_moves['BU'] = perf_df_all_moves['BU'].apply(normalize_bu)
    if df_712_allmoves is not None and 'BU' in df_712_allmoves.columns:
        df_712_allmoves['BU'] = df_712_allmoves['BU'].apply(normalize_bu)
    if 'BU' in df_712.columns:
        df_712['BU'] = df_712['BU'].apply(normalize_bu)
    if df_tender is not None and 'BU' in df_tender.columns:
        df_tender['BU'] = df_tender['BU'].apply(normalize_bu)
    if df_claims is not None and 'BU' in df_claims.columns:
        df_claims['BU'] = df_claims['BU'].apply(normalize_bu)

    report_label = labels.get(report_ym, report_ym)
    sections = []

    # 1. Title
    sections.append(slide_title(report_label))
    # 2. Agenda
    sections.append(slide_agenda(narrative.get('agenda', {}).get('items', [])))

    # Resolve the market PPTX path once up front (handle ~$ Office lock files)
    # so the Monthly Safety Share (the FIRST market slide) can be placed right
    # after the agenda, while the remaining market slides go at the end.
    import os as _os
    if market_pptx_path:
        _bn = _os.path.basename(market_pptx_path)
        if _bn.startswith('~$'):
            _real = _os.path.join(_os.path.dirname(market_pptx_path), _bn[2:])
            if _os.path.exists(_real):
                print(f'Market path was an Office lock file; using real file: {_real}', flush=True)
                market_pptx_path = _real
            else:
                print(f'WARN: market path is a lock file ({_bn}) and no real file '
                      f'found alongside it; market slides skipped.', flush=True)
                market_pptx_path = None
        if market_pptx_path and not _os.path.exists(market_pptx_path):
            print(f'WARN: market-pptx path not found: {market_pptx_path}', flush=True)
            market_pptx_path = None

    # 3. Monthly Safety Share -- pulled from the FIRST slide of the market deck
    # and placed right after the agenda (per Akzo deck format).
    if market_pptx_path:
        try:
            safety_share = slide_market_slides_section(market_pptx_path, 3, only='first')
            if safety_share.strip():
                sections.append(safety_share)
                print('Monthly Safety Share placed after agenda (from market deck).', flush=True)
        except Exception as e:
            print(f'WARN: could not render safety-share slide ({e}); skipped.', flush=True)
    # 5. OTP section divider
    sections.append(slide_divider('On Time Carrier Performance Analysis', 5))
    # 6-7. PU LTL / PU TL  (all movement types -- dashboard does not filter OB)
    sections.append(slide_otp_performance(perf_df_all_moves, df_712, ym_list, labels, 'LTL', 6,
                                          narrative.get('pu_ltl', {}), side='PU'))
    sections.append(slide_otp_performance(perf_df_all_moves, df_712, ym_list, labels, 'Truckload', 7,
                                          narrative.get('pu_tl', {}), side='PU'))
    # 8-9. Delivery LTL / TL  (same layout, delivery flags)
    sections.append(slide_otp_performance(perf_df_all_moves, df_712, ym_list, labels, 'LTL', 8,
                                          narrative.get('del_ltl', {}), side='Del'))
    sections.append(slide_otp_performance(perf_df_all_moves, df_712, ym_list, labels, 'Truckload', 9,
                                          narrative.get('del_tl', {}), side='Del'))
    # 10-11. Top 3 late carriers by mode -- now auto from perf data
    sections.append(slide_top_late_carriers(perf_df_all_moves, ym_list, labels, 10, 'PU',
                                             narrative.get('top_carriers_pu', {})))
    sections.append(slide_top_late_carriers(perf_df_all_moves, ym_list, labels, 11, 'Del',
                                             narrative.get('top_carriers_del', {})))

    # 12. Exceptions section
    sections.append(slide_divider('Shipping Exceptions Analysis', 12))
    # 13. Exceptions count by mode
    sections.append(slide_exceptions_count(perf_df, ym_list, labels, 13, mode_form='count'))
    # 14. Exceptions percentage by mode  -- same data normalized
    sections.append(slide_exceptions_count(perf_df, ym_list, labels, 14, mode_form='pct'))
    # 15-17: top-5-site exception slides
    sections.append(slide_top_sites_exception(
        perf_df, ym_list, labels, 15,
        'Insufficient Transit Time - Top 5 Sites by Mode',
        'Remove_Insuff_TT_Del',
        extra_notes=narrative.get('insuff_tt', {}).get('items', []),
    ))
    sections.append(slide_top_sites_exception(
        perf_df, ym_list, labels, 16,
        'Short Order Lead Time - Top 5 Sites by Mode',
        'OLT_PER_MODE',
        extra_notes=narrative.get('short_olt', {}).get('items', []),
    ))
    sections.append(slide_top_sites_exception(
        perf_df, ym_list, labels, 17,
        'Material Not Ready at Pickup - Top 5 Sites (LTL Only)',
        'Remove_Mat_NA_PU',
        mode_filter='LTL',
        extra_notes=narrative.get('mat_na', {}).get('items', []),
    ))

    # 18-19. Ops update (manual)
    sections.append(slide_divider('Operations Update', 18))
    sections.append(slide_manual('Monthly Achievements & Challenges', 19,
                                  narrative.get('ops_update', {})))

    # 20-22. Weight & Spend
    sections.append(slide_divider('Shipping Weight & Spend Analysis', 20))
    # Cost-per-lb and weight charts compute on the FULL 712 billing population
    # (all movement types) per the KPI dashboard -- use df_712_allmoves, the
    # clean billing frame, NOT the 810-joined subset (which drops billing rows
    # lacking an 810 event and can return an empty/broken chart).
    sections.append(slide_cost_per_kg(df_712_allmoves, ym_list, labels, 21, narrative.get('cost_per_kg', {})))
    sections.append(slide_weight_analysis(df_712_allmoves, ym_list, labels, 22, narrative.get('weight_analysis', {})))

    # 23-25. Tender
    sections.append(slide_divider('Carrier Tender Performance Analysis', 23))
    if df_tender is not None:
        # df_tender already has Mode + BU attached upstream in main() using the
        # wide 18-month 712 SID lookup.  Just hand it straight to the slides.
        sections.append(slide_tender(df_tender, df_712, ym_list, labels, 24, narrative.get('tender', {})))
        sections.append(slide_top_rejecting_carriers(df_tender, ym_list, labels, 25,
                                                      narrative.get('top_rejecting', {}),
                                                      df_712_for_include=df_712))
    else:
        sections.append(slide_manual('TL Tender Acceptance & Rejection', 24,
                                      {'items': ['(Tender hyper not provided -- skip)']}))
        sections.append(slide_manual('Top Rejecting TL Carriers', 25, {}))

    # 26-29. Claims & Complaints
    sections.append(slide_divider('Claims and Complaints Analysis', 26))
    if df_claims is not None:
        sections.append(slide_complaint_trends(df_claims, df_712, ym_list, labels, 27,
                                                narrative.get('complaints', {})))
        sections.append(slide_claims_report(df_claims, ym_list, labels, 28,
                                             narrative.get('claims_report', {})))
    else:
        sections.append(slide_manual('Complaint Trends', 27, {}))
        sections.append(slide_manual('Claims Report Details', 28, {}))
    sections.append(slide_manual('Claims & Complaints - Akzo Case Management Compliance', 29,
                                  narrative.get('case_mgmt', {})))

    # 30-31. Temperature Control
    sections.append(slide_divider('Temperature Control Analysis', 30))
    sections.append(slide_temp_control(df_712, ym_list, labels, 31, narrative.get('temp_ctrl', {})))

    # 32-35. Expedite
    # Use the FULL 712 billing frame (df_712_allmoves), not the 810-joined
    # OB frame: the join drops expedites whose 810 event hasn't landed yet
    # (recent months lose the most), which made the HTML undercount May/June
    # vs the Tableau dashboard.  The OB cut happens inside the expedite
    # helpers via _expedite_ob_mask (the dashboard's own KPI classifier).
    df_712_exp = df_712_allmoves if df_712_allmoves is not None else df_712
    # Reconciliation aid: print the expedite population under each basis so a
    # residual mismatch vs the dashboard is diagnosable from the console.
    try:
        _e = df_712_exp[df_712_exp['YYYY_MM'].isin(ym_list)]
        _e = _e[_is_expedite_mask(_e)]
        _ej = df_712[df_712['YYYY_MM'].isin(ym_list)]
        _ej = _ej[_is_expedite_mask(_ej)]
        for _ym in ym_list:
            _m = _e[_e['YYYY_MM'] == _ym]
            _kpi = int(_expedite_ob_mask(_m).sum())
            _raw = int((_m['IB_OB'] == 'OB').sum()) if 'IB_OB' in _m.columns else -1
            _old = len(_ej[_ej['YYYY_MM'] == _ym])
            print(f'  Expedite {_ym}: all-moves={len(_m)}  KPI-OB={_kpi} (charts use this)  '
                  f'raw-OB={_raw}  old-810-joined-basis={_old}', flush=True)
    except Exception as _ex:
        print(f'  WARN: expedite diagnostic failed: {_ex}', flush=True)
    sections.append(slide_divider('Expedite Tracking Analysis', 32))
    sections.append(slide_expedite_trends(df_712_exp, ym_list, labels, 33, narrative.get('expedite_trends', {})))
    # Slides 34 & 35 are per-month expedite reason/carrier breakdowns
    sections.append(slide_expedite_reason(df_712_exp, ym_list[-2], labels, 34,
                                          narrative.get('expedite_prior', {})))
    sections.append(slide_expedite_reason(df_712_exp, ym_list[-1], labels, 35,
                                          narrative.get('expedite_report', {})))

    # 36-37. Conclusion / Moving As One
    sections.append(slide_divider('Conclusion', 36))
    sections.append(slide_manual('Moving As One', 37, narrative.get('moving_as_one', {})))

    # 38+. Appendix (manual)
    sections.append(slide_divider('Appendix', 38))
    sections.append(slide_manual('Market News', 39, narrative.get('market_news', {})))

    # Market update slides from PPTX (optional -- pass --market-pptx on CLI).
    # Path was already resolved up front; the FIRST market slide (safety share)
    # has already been placed after the agenda, so here we render only the REST.
    if market_pptx_path:
        try:
            market_section = slide_market_slides_section(market_pptx_path, 41, only='rest')
            if market_section.strip():
                sections.append(slide_divider('Market Rate Update', 40))
                sections.append(market_section)
                print(f'Market slides (rest) added from: {market_pptx_path}', flush=True)
        except Exception as e:
            # Do NOT append the divider on failure -- an empty "Market Rate
            # Update" section with an error placeholder is worse than nothing.
            print(f'WARN: market PPTX failed to render ({e}); market slides skipped.', flush=True)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Akzo MOR - {report_label}</title>
<style>{CSS}
/* ---- Navigation UI ---- */
.mor-nav {{
    position: fixed; bottom: 16px; right: 16px; z-index: 1000;
    background: rgba(20, 32, 56, 0.92);
    color: white;
    padding: 8px 14px;
    border-radius: 24px;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    display: flex; align-items: center; gap: 10px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    user-select: none;
    transition: opacity 0.25s ease;
}}
.mor-nav.dim {{ opacity: 0.25; }}
.mor-nav:hover {{ opacity: 1; }}
.mor-nav button {{
    background: rgba(255,255,255,0.15);
    color: white;
    border: none;
    width: 28px; height: 28px;
    border-radius: 50%;
    font-size: 16px;
    cursor: pointer;
    line-height: 1;
    transition: background 0.15s;
}}
.mor-nav button:hover {{ background: rgba(255,255,255,0.3); }}
.mor-nav button:disabled {{ opacity: 0.3; cursor: not-allowed; }}
.mor-nav .counter {{ min-width: 56px; text-align: center; font-variant-numeric: tabular-nums; }}
.mor-nav #navPresent {{
    width: auto; border-radius: 14px; padding: 0 12px; height: 28px;
    font-size: 12px; background: rgba(197,213,45,0.85); color: #1B2541; font-weight: 600;
}}
.mor-nav #navPresent:hover {{ background: #C5D52D; }}
.mor-nav .hint {{
    font-size: 11px; opacity: 0.7;
    border-left: 1px solid rgba(255,255,255,0.25);
    padding-left: 10px;
    margin-left: 2px;
}}
@media print {{ .mor-nav {{ display: none !important; }} }}

/* ---- Presentation mode ---- */
/* Full-screen dark stage; the active slide is centered at its NATURAL design
   size and scaled to fit.  We do NOT stretch the slide to 100vh -- doing that
   collapses the internal layout of title/divider/agenda slides (they were
   designed around a fixed min-height) and renders them blank. */
body.present-mode {{ overflow: hidden; background: #0B1220; }}
body.present-mode section.mor-title,
body.present-mode section.mor-agenda,
body.present-mode section.mor-divider,
body.present-mode section.mor-content {{
    display: none !important;
}}
/* The active slide is fixed-centered at its natural design size.  Position +
   sizing here; the DISPLAY type is restored per slide type below so the
   internal grid/flex layout stays intact. */
body.present-mode section.present-active {{
    position: fixed;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    margin: 0;
    width: min(96vw, 1280px);
    max-height: 96vh;
    overflow: auto;
    z-index: 5000;
    box-shadow: 0 10px 40px rgba(0,0,0,0.5);
    animation: presentFade 0.18s ease;
}}
/* Restore each slide type's stylesheet display (overrides the display:none). */
body.present-mode section.mor-title.present-active {{ display: grid !important; }}
body.present-mode section.mor-agenda.present-active {{ display: grid !important; }}
body.present-mode section.mor-divider.present-active {{ display: flex !important; }}
body.present-mode section.mor-content.present-active {{ display: block !important; }}
@keyframes presentFade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
/* Hide editing + hide-slide chrome while presenting */
body.present-mode .slide-hide-btn,
body.present-mode .mor-hidden-label,
body.present-mode .edit-toolbar,
body.present-mode .hidden-slides-bar {{ display: none !important; }}
body.present-mode .editable {{ border-color: transparent !important; background: transparent !important; }}
/* Presentation nav overlay */
.present-nav {{
    position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
    z-index: 6000; display: none; align-items: center; gap: 14px;
    background: rgba(11,18,32,0.82); color: #fff; padding: 8px 16px;
    border-radius: 24px; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px;
    opacity: 0; transition: opacity 0.25s; user-select: none;
}}
body.present-mode .present-nav {{ display: flex; }}
.present-nav.show {{ opacity: 1; }}
.present-nav button {{
    background: rgba(255,255,255,0.16); color: #fff; border: none;
    width: 34px; height: 34px; border-radius: 50%; font-size: 18px; cursor: pointer;
}}
.present-nav button:hover {{ background: rgba(255,255,255,0.32); }}
.present-nav .pcount {{ min-width: 60px; text-align: center; font-variant-numeric: tabular-nums; }}
.present-nav .pexit {{ font-size: 12px; width: auto; border-radius: 16px; padding: 0 12px; }}
@media print {{ .present-nav {{ display: none !important; }} }}
</style>
</head>
<body>
<!--GEN-INFO
{gen_info.replace('--', '~')}
GEN-INFO-->
{''.join(sections)}
<div class="mor-nav" id="morNav">
  <button id="navPrev" title="Previous (←)">&larr;</button>
  <span class="counter"><span id="navCur">1</span>/<span id="navTotal">1</span></span>
  <button id="navNext" title="Next (→ or click)">&rarr;</button>
  <button id="navPresent" title="Presentation mode (F or click)">&#9654; Present</button>
  <span class="hint">click slide or use &larr; &rarr;</span>
</div>
<div class="present-nav" id="presentNav">
  <button id="pPrev" title="Previous (←)">&larr;</button>
  <span class="pcount"><span id="pCur">1</span>/<span id="pTotal">1</span></span>
  <button id="pNext" title="Next (→)">&rarr;</button>
  <button class="pexit" id="pExit" title="Exit (Esc)">Exit</button>
</div>
<script>
(function() {{
    // Collect all top-level slide sections in DOM order.
    var slides = Array.prototype.slice.call(document.querySelectorAll(
        'section.mor-title, section.mor-agenda, section.mor-divider, section.mor-content'
    ));
    var total = slides.length;
    if (total === 0) return;

    var navEl = document.getElementById('morNav');
    var curEl = document.getElementById('navCur');
    var totalEl = document.getElementById('navTotal');
    var prevBtn = document.getElementById('navPrev');
    var nextBtn = document.getElementById('navNext');
    totalEl.textContent = total;

    function goTo(idx) {{
        if (idx < 0) idx = 0;
        if (idx >= total) idx = total - 1;
        slides[idx].scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        // Counter updates on scroll via IntersectionObserver, not here, so the
        // displayed number matches what the user actually sees.
    }}

    function indexOfCurrent() {{
        // Find the slide whose top is closest to (just above) the viewport top
        var y = window.scrollY + 60;  // small offset so we pick the slide we're "on"
        var best = 0;
        for (var i = 0; i < total; i++) {{
            if (slides[i].offsetTop <= y) best = i;
        }}
        return best;
    }}

    function next() {{ goTo(indexOfCurrent() + 1); }}
    function prev() {{ goTo(indexOfCurrent() - 1); }}

    // Click anywhere on a slide -> advance.  But don't trigger if the user is
    // clicking a link, an image (so they can right-click-save), or selecting text.
    slides.forEach(function(slide, i) {{
        slide.style.cursor = 'pointer';
        slide.addEventListener('click', function(ev) {{
            if (window.getSelection && window.getSelection().toString().length > 0) return;
            var tag = (ev.target.tagName || '').toLowerCase();
            if (tag === 'a' || tag === 'button' || tag === 'input' || tag === 'img') return;
            // Don't advance if user clicked inside an editable narrative block
            if (ev.target.closest && ev.target.closest('.editable')) return;
            // If clicked in left third of slide, go back; otherwise advance.
            var rect = slide.getBoundingClientRect();
            var relX = (ev.clientX - rect.left) / rect.width;
            if (relX < 0.15) prev(); else next();
        }});
    }});

    // Keyboard navigation
    document.addEventListener('keydown', function(ev) {{
        if (ev.target && /input|textarea|select/i.test(ev.target.tagName)) return;
        // Don't navigate slides while the user is editing a contenteditable narrative block
        if (ev.target && ev.target.isContentEditable) return;
        switch (ev.key) {{
            case 'ArrowRight':
            case 'PageDown':
            case ' ':           // space
                ev.preventDefault(); next(); break;
            case 'ArrowLeft':
            case 'PageUp':
                ev.preventDefault(); prev(); break;
            case 'Home':
                ev.preventDefault(); goTo(0); break;
            case 'End':
                ev.preventDefault(); goTo(total - 1); break;
        }}
    }});

    // Nav button clicks
    prevBtn.addEventListener('click', function(ev) {{ ev.stopPropagation(); prev(); }});
    nextBtn.addEventListener('click', function(ev) {{ ev.stopPropagation(); next(); }});

    // Update counter as user scrolls
    function refreshCounter() {{
        curEl.textContent = indexOfCurrent() + 1;
        prevBtn.disabled = (indexOfCurrent() === 0);
        nextBtn.disabled = (indexOfCurrent() === total - 1);
    }}
    var scrollTimer = null;
    window.addEventListener('scroll', function() {{
        if (scrollTimer) return;
        scrollTimer = setTimeout(function() {{ refreshCounter(); scrollTimer = null; }}, 80);
    }});
    refreshCounter();
    // The hide-slide script calls window.morRefreshNav() after a Hide/Show
    // toggle; before this was wired up the call was a silent no-op and the
    // slide counter went stale.
    window.morRefreshNav = refreshCounter;

    // Dim the nav bar when the mouse is idle (so it doesn't distract on screenshots)
    var dimTimer = null;
    function wake() {{
        navEl.classList.remove('dim');
        if (dimTimer) clearTimeout(dimTimer);
        dimTimer = setTimeout(function() {{ navEl.classList.add('dim'); }}, 2500);
    }}
    document.addEventListener('mousemove', wake);
    document.addEventListener('keydown', wake);
    wake();
}})();
</script>
<script>
(function() {{
    // ---- Presentation mode: one slide fills the screen, arrow/click to move ----
    function visibleSlides() {{
        // Skip slides hidden via the per-slide Hide button.
        return Array.prototype.slice.call(document.querySelectorAll(
            'section.mor-title, section.mor-agenda, section.mor-divider, section.mor-content'
        )).filter(function(s) {{ return !s.classList.contains('mor-hidden'); }});
    }}
    var pNav = document.getElementById('presentNav');
    var pCur = document.getElementById('pCur');
    var pTotal = document.getElementById('pTotal');
    var idx = 0, list = [], active = false, hideTimer = null;

    function render() {{
        list.forEach(function(s, i) {{
            s.classList.toggle('present-active', i === idx);
        }});
        if (list[idx]) list[idx].scrollTop = 0;
        pCur.textContent = idx + 1;
        pTotal.textContent = list.length;
    }}
    function go(n) {{
        idx = Math.max(0, Math.min(list.length - 1, n));
        render();
    }}
    function enter() {{
        list = visibleSlides();
        if (!list.length) return;
        // Start on the slide nearest the current scroll position.
        var y = window.scrollY + 60, best = 0;
        list.forEach(function(s, i) {{ if (s.offsetTop <= y) best = i; }});
        idx = best;
        active = true;
        document.body.classList.add('present-mode');
        render();
        if (document.documentElement.requestFullscreen) {{
            document.documentElement.requestFullscreen().catch(function() {{}});
        }}
        wakeNav();
    }}
    function exit() {{
        active = false;
        document.body.classList.remove('present-mode');
        list.forEach(function(s) {{ s.classList.remove('present-active'); }});
        if (document.fullscreenElement && document.exitFullscreen) {{
            document.exitFullscreen().catch(function() {{}});
        }}
        if (list[idx]) list[idx].scrollIntoView({{ block: 'start' }});
    }}
    function wakeNav() {{
        pNav.classList.add('show');
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(function() {{ pNav.classList.remove('show'); }}, 2200);
    }}

    var presentBtn = document.getElementById('navPresent');
    if (presentBtn) presentBtn.addEventListener('click', function(ev) {{ ev.stopPropagation(); enter(); }});
    document.getElementById('pPrev').addEventListener('click', function(ev) {{ ev.stopPropagation(); go(idx - 1); wakeNav(); }});
    document.getElementById('pNext').addEventListener('click', function(ev) {{ ev.stopPropagation(); go(idx + 1); wakeNav(); }});
    document.getElementById('pExit').addEventListener('click', function(ev) {{ ev.stopPropagation(); exit(); }});

    document.addEventListener('keydown', function(ev) {{
        if (!active) {{
            if (ev.key === 'f' || ev.key === 'F') {{
                if (ev.target && (ev.target.isContentEditable || /input|textarea|select/i.test(ev.target.tagName))) return;
                ev.preventDefault(); enter();
            }}
            return;
        }}
        switch (ev.key) {{
            case 'ArrowRight': case 'PageDown': case ' ':
                ev.preventDefault(); go(idx + 1); wakeNav(); break;
            case 'ArrowLeft': case 'PageUp':
                ev.preventDefault(); go(idx - 1); wakeNav(); break;
            case 'Home': ev.preventDefault(); go(0); wakeNav(); break;
            case 'End': ev.preventDefault(); go(list.length - 1); wakeNav(); break;
            case 'Escape': ev.preventDefault(); exit(); break;
        }}
    }});
    // Click on the active slide advances (left 15% goes back); ignore links/editables.
    document.addEventListener('click', function(ev) {{
        if (!active) return;
        var t = ev.target;
        var tag = (t.tagName || '').toLowerCase();
        if (tag === 'a' || tag === 'button' || tag === 'img') return;
        if (t.isContentEditable || (t.closest && t.closest('.editable'))) return;
        if (t.closest && t.closest('.present-nav')) return;
        var rel = ev.clientX / window.innerWidth;
        if (rel < 0.15) go(idx - 1); else go(idx + 1);
        wakeNav();
    }});
    document.addEventListener('mousemove', function() {{ if (active) wakeNav(); }});
    // If the user leaves fullscreen via Esc/browser UI, exit present mode too.
    document.addEventListener('fullscreenchange', function() {{
        if (!document.fullscreenElement && active) exit();
    }});
}})();
</script>
<div class="edit-toolbar">
    <span class="edit-status" id="edit-status">Edits save locally</span>
    <button onclick="saveCopy()">Save copy</button>
    <button onclick="saveAsPdf()">Save as PDF</button>
    <button onclick="exportEdits()">Export edits</button>
    <button onclick="resetEdits()">Reset</button>
</div>
<script>
(function() {{
    // Stable key per editable block: parent section id + block index within section.
    // This survives monthly re-generations as long as slide ordering doesn't change.
    const STORAGE_KEY = 'akzo_mor_edits_' + (document.title || 'report');

    function keyFor(el) {{
        const sect = el.closest('section');
        // Derive a STABLE section id.  Title/agenda sections have no id; using a
        // literal 'unknown' made every id-less section share the same key space
        // (unknown.block-0, unknown.block-1, ...), so edits on one bled onto
        // another (e.g. an agenda edit overwriting the title, and vice versa).
        // Fall back to a class-derived id so each section type is distinct.
        var sectId;
        if (!sect) {{
            sectId = 'global';
        }} else if (sect.id) {{
            sectId = sect.id;
        }} else {{
            var cls = (sect.className || '').split(' ').filter(function(c) {{ return c.indexOf('mor-') === 0; }})[0];
            sectId = cls || 'section';
        }}
        const all = sect ? sect.querySelectorAll('.editable') : [el];
        const idx = Array.prototype.indexOf.call(all, el);
        return sectId + '.block-' + idx;
    }}

    // For a TABLE.editable we do not make the <table> itself contenteditable
    // (unreliable across browsers).  Instead each cell becomes editable and is
    // keyed by table-key + r/c so edits persist per cell.
    // Auto-tag every remaining "text box" in the deck as editable so the Ops
    // team can edit ALL titles, headers, captions, agenda items and divider
    // titles in-browser -- not only the narrative bullet blocks.  Runs once,
    // before targets are collected.  Anything already carrying .editable (or
    // living inside an .editable table cell) is skipped to avoid double-keying.
    let _autoTagged = false;
    function autoTagText() {{
        if (_autoTagged) return;
        _autoTagged = true;
        const SEL = [
            '.content-title', '.divider-title', '.title-month', '.agenda-title',
            '.narrative-block h4', '.mor-table caption', '.data-table caption',
            '.agenda-list li', '.mor-content h3', '.mor-content h4'
        ].join(',');
        document.querySelectorAll(SEL).forEach(function(el) {{
            if (el.classList.contains('editable')) return;
            if (el.closest('[contenteditable="true"]')) return;
            // Skip captions/headers that sit inside an already-editable TABLE cell.
            const cell = el.closest('td,th');
            if (cell && cell.closest('table.editable')) return;
            el.classList.add('editable');
        }});
    }}

    function editableTargets() {{
        autoTagText();
        const out = [];
        document.querySelectorAll('.editable').forEach(function(el) {{
            if (el.tagName === 'TABLE') {{
                const cells = el.querySelectorAll('th,td');
                const tkey = keyFor(el);
                cells.forEach(function(cell, ci) {{
                    cell.setAttribute('data-edit-key', tkey + '.cell-' + ci);
                    out.push(cell);
                }});
            }} else {{
                el.setAttribute('data-edit-key', keyFor(el));
                out.push(el);
            }}
        }});
        return out;
    }}

    // Single-line text boxes that must NEVER hold block markup.  A stray paste
    // of a bullet list / table into one of these (e.g. a slide title) renders
    // at header font size and overlaps the body -- the "huge font box on top of
    // another" bug.  Defined before loadEdits so the self-heal can use them.
    // .title-month is intentionally excluded -- it legitimately uses a <br>
    // (e.g. "MAY 2026<br>MOR") and must keep its line break.
    const TITLE_LIKE = '.content-title, .divider-title, .agenda-title, .narrative-block h4, .mor-content h3, .mor-content h4, .mor-table caption, .data-table caption, .agenda-list li';
    function isTitleLike(el) {{ return el.matches && el.matches(TITLE_LIKE); }}
    function plainText(s) {{ return (s || '').replace(/[\\r\\n\\t]+/g, ' ').replace(/\\s{{2,}}/g, ' ').trim(); }}

    function loadEdits() {{
        let saved = {{}};
        try {{ saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch (e) {{}}
        editableTargets().forEach(function(el) {{
            const k = el.getAttribute('data-edit-key');
            el.setAttribute('contenteditable', 'true');
            el.setAttribute('spellcheck', 'true');
            if (saved[k] !== undefined && saved[k] !== el.innerHTML) {{
                // Self-heal: a previously-saved title that contains block markup
                // (bullet list / table pasted into a title) would render at
                // header size and overlap the body.  Flatten it to plain text
                // on load and rewrite the saved value so it stays fixed.
                let val = saved[k];
                if (isTitleLike(el) && /<(div|ul|ol|table|li|p)\\b/i.test(val)) {{
                    const tmp = document.createElement('div');
                    tmp.innerHTML = val;
                    val = plainText(tmp.textContent);
                    saved[k] = val;
                    try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(saved)); }} catch (e) {{}}
                    el.textContent = val;
                }} else {{
                    el.innerHTML = val;
                }}
                el.setAttribute('data-dirty', 'true');
            }}
        }});
    }}

    function saveEdit(el) {{
        let saved = {{}};
        try {{ saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch (e) {{}}
        const k = el.getAttribute('data-edit-key') || keyFor(el);
        saved[k] = el.innerHTML;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
        el.setAttribute('data-dirty', 'true');
        const s = document.getElementById('edit-status');
        if (s) s.textContent = 'Saved ' + new Date().toLocaleTimeString();
    }}

    window.exportEdits = function() {{
        const raw = localStorage.getItem(STORAGE_KEY) || '{{}}';
        const blob = new Blob([raw], {{type: 'application/json'}});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'mor_edits_' + new Date().toISOString().slice(0,10) + '.json';
        a.click();
        URL.revokeObjectURL(url);
    }};

    window.resetEdits = function() {{
        if (!confirm('Discard all local edits and revert to generated text?')) return;
        localStorage.removeItem(STORAGE_KEY);
        location.reload();
    }};

    document.addEventListener('DOMContentLoaded', function() {{
        loadEdits();
        editableTargets().forEach(function(el) {{
            let timer;
            el.addEventListener('input', function() {{
                clearTimeout(timer);
                timer = setTimeout(function() {{ saveEdit(el); }}, 400);
            }});
            el.addEventListener('blur', function() {{ saveEdit(el); }});
            if (isTitleLike(el)) {{
                // Plain-text-only paste: never inject HTML into a title.
                el.addEventListener('paste', function(e) {{
                    e.preventDefault();
                    const t = plainText((e.clipboardData || window.clipboardData).getData('text/plain'));
                    document.execCommand('insertText', false, t);
                }});
                // Enter must not create <div>/<br> block structure in a title.
                el.addEventListener('keydown', function(e) {{
                    if (e.key === 'Enter') e.preventDefault();
                }});
                // Drag-drop is another way block markup sneaks in; block it.
                el.addEventListener('drop', function(e) {{ e.preventDefault(); }});
                // On blur, sanitize: if any block markup slipped in, flatten to text.
                el.addEventListener('blur', function() {{
                    if (/[<]/.test(el.innerHTML) && el.querySelector('div,ul,ol,table,li,p')) {{
                        el.textContent = plainText(el.textContent);
                        saveEdit(el);
                    }}
                }});
            }}
        }});
    }});
}})();
</script>

<style>
.slide-hide-btn {{ position:absolute; top:10px; right:14px; z-index:30; opacity:0;
  transition:opacity .15s; background:#1B2541; color:#fff; border:none; border-radius:4px;
  padding:4px 10px; font-size:12px; cursor:pointer; }}
.slide-hide-btn:hover {{ background:#23314F; }}
section.mor-title > .slide-hide-btn, section.mor-agenda > .slide-hide-btn,
section.mor-divider > .slide-hide-btn {{ background:#C5D52D; color:#1B2541; }}
section:hover > .slide-hide-btn {{ opacity:0.85; }}
/* Touch screens have no hover -- keep the button faintly visible so it stays tappable. */
@media (hover: none) {{ .slide-hide-btn {{ opacity:0.55; }} }}
.mor-hidden-label {{ display:none; }}
section.mor-hidden {{ display:block !important; min-height:0 !important; height:auto !important;
  padding:8px 24px !important; background:#F2F4F7 !important; color:#5A6378 !important; }}
section.mor-hidden > *:not(.slide-hide-btn):not(.mor-hidden-label) {{ display:none !important; }}
section.mor-hidden > .slide-hide-btn {{ opacity:0.85; position:static; float:right;
  background:#1B2541; color:#fff; }}
section.mor-hidden > .mor-hidden-label {{ display:inline-block; font-size:13px;
  color:#5A6378; line-height:24px; }}
@media print {{ .slide-hide-btn, section.mor-hidden {{ display:none !important; }} }}
</style>
<script>
(function() {{
    var HIDE_KEY = 'akzo_mor_hidden_' + (document.title || 'report');

    function sections() {{
        return Array.prototype.slice.call(document.querySelectorAll(
            'section.mor-title, section.mor-agenda, section.mor-divider, section.mor-content'));
    }}
    function loadHidden() {{
        try {{ return JSON.parse(localStorage.getItem(HIDE_KEY) || '[]'); }} catch (e) {{ return []; }}
    }}
    function saveHidden(list) {{
        // localStorage can be unavailable (privacy mode, some embedded
        // viewers); a throw here used to kill the click handler and the
        // button looked dead.  Hiding still works for the session either way.
        try {{ localStorage.setItem(HIDE_KEY, JSON.stringify(list)); }} catch (e) {{}}
    }}

    function titleOf(sect) {{
        var h = sect.querySelector('h1,h2,h3');
        return h ? h.textContent.trim() : (sect.id || 'slide');
    }}

    function setHidden(sect, hidden) {{
        var btn = sect.querySelector(':scope > .slide-hide-btn');
        var label = sect.querySelector(':scope > .mor-hidden-label');
        if (hidden) {{
            sect.classList.add('mor-hidden');
            if (btn) btn.textContent = 'Show';
            if (label) label.textContent = 'Hidden: ' + titleOf(sect) + ' \u2014 excluded from Save copy';
        }} else {{
            sect.classList.remove('mor-hidden');
            if (btn) btn.textContent = 'Hide';
            if (label) label.textContent = '';
        }}
        var list = loadHidden();
        var i = list.indexOf(sect.id);
        if (hidden && i === -1) list.push(sect.id);
        if (!hidden && i !== -1) list.splice(i, 1);
        saveHidden(list);
        if (window.morRefreshNav) window.morRefreshNav();
    }}

    function initHide() {{
        var hidden = loadHidden();
        sections().forEach(function(sect, i) {{
            // Hidden state is persisted per section id.  The title/agenda
            // sections (and market slides in old copies) ship WITHOUT an id,
            // so they all shared the same empty-string key: hiding one hid
            // every id-less slide on the next open, and Show on one un-hid
            // the others -- the "hide buttons don't work" bug.  Give each
            // id-less section a stable index-based id before using the state.
            // (Assigned AFTER the edit script has keyed its editable blocks,
            // so existing saved edits keep their original keys.)
            if (!sect.id) sect.id = 'mor-auto-' + i;
            // Wire up the hide button.  The button + label are baked into the
            // section HTML by the generator; attach the handler to the
            // EXISTING button rather than skipping (the old code skipped
            // pre-wired sections, leaving the static buttons with no click
            // handler -- that is why clicking did nothing).  Only create the
            // elements if they are genuinely missing.
            var btn = sect.querySelector(':scope > .slide-hide-btn');
            var label = sect.querySelector(':scope > .mor-hidden-label');
            if (!label) {{
                label = document.createElement('span');
                label.className = 'mor-hidden-label';
                sect.appendChild(label);
            }}
            if (!btn) {{
                btn = document.createElement('button');
                btn.className = 'slide-hide-btn';
                btn.textContent = 'Hide';
                btn.title = 'Hide this slide (hidden slides are excluded when you Save copy)';
                sect.appendChild(btn);
            }}
            // Bind the click handler exactly once.
            if (!btn.dataset.hideWired) {{
                btn.dataset.hideWired = '1';
                btn.addEventListener('click', function(ev) {{
                    ev.stopPropagation();
                    setHidden(sect, !sect.classList.contains('mor-hidden'));
                }});
            }}
            if (getComputedStyle(sect).position === 'static') sect.style.position = 'relative';
            if (hidden.indexOf(sect.id) !== -1) setHidden(sect, true);
        }});
    }}
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initHide);
    }} else {{
        // Guard: this IIFE also defines saveCopy/saveAsPdf below.  If a
        // synchronous initHide() threw, those definitions never ran and the
        // whole toolbar (Save copy / Save as PDF) went dead.
        try {{ initHide(); }} catch (e) {{}}
    }}

    function buildCopyHtml() {{
        var clone = document.documentElement.cloneNode(true);
        // Delete hidden slides from the copy entirely
        Array.prototype.slice.call(clone.querySelectorAll('section.mor-hidden'))
            .forEach(function(s) {{ s.parentNode.removeChild(s); }});
        // Strip per-slide chrome; it is re-injected when the copy is opened
        Array.prototype.slice.call(clone.querySelectorAll('.slide-hide-btn, .mor-hidden-label'))
            .forEach(function(el) {{ el.parentNode.removeChild(el); }});
        // Reset transient UI state in the copy
        var lb = clone.querySelector('#lightbox');
        if (lb) lb.classList.remove('active');
        var bodyEl = clone.querySelector('body');
        if (bodyEl) bodyEl.style.overflow = '';
        return '<!DOCTYPE html>\\n' + clone.outerHTML;
    }}

    function setStatus(msg) {{
        var s = document.getElementById('edit-status');
        if (s) s.textContent = msg;
    }}

    window.saveCopy = async function() {{
        var htmlOut = buildCopyHtml();
        var base = (document.title || 'Akzo_MOR').replace(/[^a-zA-Z0-9_-]+/g, '_') + '_edited.html';

        // Preferred: real Save As dialog (Chrome/Edge) so the user picks the
        // folder.  Falls back to a normal download (browser Downloads folder).
        if (window.showSaveFilePicker) {{
            try {{
                var handle = await window.showSaveFilePicker({{
                    suggestedName: base,
                    types: [{{ description: 'HTML report',
                              accept: {{ 'text/html': ['.html'] }} }}]
                }});
                var writable = await handle.createWritable();
                await writable.write(htmlOut);
                await writable.close();
                setStatus('Saved ' + handle.name + ' ' + new Date().toLocaleTimeString());
                return;
            }} catch (e) {{
                if (e && e.name === 'AbortError') return;  // user cancelled
                // fall through to download on any other failure
            }}
        }}
        var blob = new Blob([htmlOut], {{ type: 'text/html' }});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = base;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        setStatus('Copy sent to Downloads folder ' + new Date().toLocaleTimeString());
    }};

    // Save the report as a PDF via the browser's print-to-PDF path.  The
    // @media print rules below lay the deck out one slide per page and hide all
    // UI chrome + slides hidden via the Hide button.  No external libraries.
    window.saveAsPdf = function() {{
        setStatus('Opening print dialog \u2014 choose "Save as PDF" as the destination.');
        // Defer so the status text paints before the (blocking) print dialog.
        setTimeout(function() {{
            try {{ window.print(); }}
            catch (e) {{ setStatus('Print blocked by browser \u2014 press Ctrl+P and choose "Save as PDF".'); }}
        }}, 60);
    }};
    // Put the toolbar status back once the print dialog closes.
    window.addEventListener('afterprint', function() {{ setStatus('Edits save locally'); }});
}})();
</script>

<!-- Lightbox: click any chart to zoom, click backdrop / hit ESC to close -->
<div class="lightbox-backdrop" id="lightbox" role="dialog" aria-hidden="true">
    <button class="lightbox-close" id="lightbox-close" aria-label="Close">Close ×</button>
    <img id="lightbox-img" src="" alt="Enlarged chart">
    <div class="lightbox-hint">Click anywhere or press ESC to close</div>
</div>
<script>
(function() {{
    const lb = document.getElementById('lightbox');
    const lbImg = document.getElementById('lightbox-img');
    const lbClose = document.getElementById('lightbox-close');
    if (!lb || !lbImg) return;

    function openLightbox(src, alt) {{
        lbImg.src = src;
        lbImg.alt = alt || 'Enlarged chart';
        lb.classList.add('active');
        lb.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }}
    function closeLightbox() {{
        lb.classList.remove('active');
        lb.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        // Clear src after transition to release memory
        setTimeout(function() {{ if (!lb.classList.contains('active')) lbImg.src = ''; }}, 150);
    }}

    // Bind every chart-cell img
    document.addEventListener('DOMContentLoaded', function() {{
        document.querySelectorAll('.chart-cell img').forEach(function(img) {{
            img.addEventListener('click', function(e) {{
                e.stopPropagation();  // don't trigger slide-nav click
                openLightbox(img.src, img.alt);
            }});
        }});
    }});

    // Close on backdrop click or close button
    lb.addEventListener('click', function() {{ closeLightbox(); }});
    lbClose.addEventListener('click', function(e) {{ e.stopPropagation(); closeLightbox(); }});
    // Clicking the image itself also closes (cursor: zoom-out)
    lbImg.addEventListener('click', function(e) {{ e.stopPropagation(); closeLightbox(); }});

    // ESC to close
    document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape' && lb.classList.contains('active')) {{
            closeLightbox();
        }}
    }});
}})();
</script>
</body>
</html>
'''

# =============================================================================
# 9. CLI
# =============================================================================
def _norm_sids(s: pd.Series) -> pd.Series:
    """Normalize SIDs for matching: trim, uppercase, drop a float-cast '.0'
    tail, strip leading zeros ('0001575520' == '1575520' == '1575520.0')."""
    out = s.astype(str).str.strip().str.upper()
    out = out.str.replace(r'\.0+$', '', regex=True)
    return out.str.lstrip('0')


def _otp_otd_snapshot(df: pd.DataFrame, ym_list: List[str]) -> Dict[str, tuple]:
    """Per-month/mode OTP & OTD (count-based, distinct IDs -- mirrors the
    Late-vs-OnTime count charts).  Used to print the before/after impact of
    manual adjustments so 'nothing changed' is visible at the console."""
    out = {}
    if df is None or len(df) == 0 or 'SID' not in df.columns:
        return out
    key_pu = 'Key ShipperSID' if 'Key ShipperSID' in df.columns else 'SID'
    for ym in ym_list:
        for mode in ['LTL', 'Truckload']:
            sub = df[(df.get('YYYY_MM') == ym) & (df.get('Mode') == mode)]
            if len(sub) == 0:
                continue

            def _share(late_col, key):
                if late_col not in sub.columns:
                    return None
                ot = sub[sub[late_col] == 0][key].nunique()
                late = sub[sub[late_col] == 1][key].nunique()
                return (ot / (ot + late) * 100) if (ot + late) else None

            out[f'{ym} {mode}'] = (_share('SA_PU_Late', key_pu), _share('SA_Del_Late', 'SID'))
    return out


def load_manual_adjustments(explicit_path: Optional[str], report_ym: str) -> Optional[pd.DataFrame]:
    """One-off, month-scoped SID adjustments -- NOT a permanent logic change.

    Used for exception SIDs that ops confirms with carriers after the data is
    cut (e.g. "these orders did pick up on time" / "exclude these disputed
    orders").  Reads --adjustments PATH if given, otherwise looks for
    manual_adjustments_<report-month>.csv (e.g. manual_adjustments_2026-07.csv)
    next to the script / in the working dir.  Because the filename carries the
    report month, it applies to that month's run only -- delete the file (or
    just don't create one next month) and the report is back to purely
    computed numbers.

    CSV columns: SID, Action[, Note]
        exclude -> drop the SID's rows from the performance frames entirely
        otp     -> force the SID's pickup On Time  (SA_PU_OT=1, SA_PU_Late=0)
        otd     -> force the SID's delivery On Time (SA_Del_OT=1, SA_Del_Late=0)
    SID matching ignores leading zeros ('0001575520' matches '1575520').
    """
    cands = []
    if explicit_path:
        cands.append(Path(explicit_path))
    fname = f'manual_adjustments_{report_ym}.csv'
    cands += [Path.cwd() / fname, Path(__file__).parent / fname]
    path = next((p for p in cands if p.exists()), None)
    if path is None:
        # ALWAYS say so -- a silently-skipped adjustments file looks exactly
        # like "the adjustments did nothing" and is undiagnosable from the deck.
        if explicit_path:
            print(f'WARN: adjustments file not found: {explicit_path}', flush=True)
        else:
            print(f'Manual adjustments: NONE -- no {fname} found in '
                  f'{Path.cwd()} or {Path(__file__).parent.resolve()}', flush=True)
        return None
    adj = pd.read_csv(path, dtype=str)
    cols = {c.lower().strip(): c for c in adj.columns}
    if 'sid' not in cols or 'action' not in cols:
        print(f'WARN: adjustments file {path} must have SID and Action columns; ignored.', flush=True)
        return None
    adj = adj.rename(columns={cols['sid']: 'SID', cols['action']: 'Action'})
    adj['SID_norm'] = _norm_sids(adj['SID'])
    adj['Action'] = adj['Action'].astype(str).str.strip().str.lower()
    bad = sorted(set(adj.loc[~adj['Action'].isin(['exclude', 'otp', 'otd']), 'Action']))
    if bad:
        print(f'WARN: unknown adjustment actions ignored: {bad}', flush=True)
        adj = adj[adj['Action'].isin(['exclude', 'otp', 'otd'])]
    print(f'Manual adjustments: {path} -- '
          f"{int((adj['Action'] == 'exclude').sum())} exclude, "
          f"{int((adj['Action'] == 'otp').sum())} force-OTP, "
          f"{int((adj['Action'] == 'otd').sum())} force-OTD SIDs", flush=True)
    return adj


def apply_manual_adjustments(df: pd.DataFrame, adj: pd.DataFrame, label: str) -> pd.DataFrame:
    """Apply load_manual_adjustments() output to one performance frame."""
    if df is None or len(df) == 0 or 'SID' not in df.columns:
        return df
    sid_norm = _norm_sids(df['SID'])
    excl = set(adj.loc[adj['Action'] == 'exclude', 'SID_norm'])
    otp = set(adj.loc[adj['Action'] == 'otp', 'SID_norm'])
    otd = set(adj.loc[adj['Action'] == 'otd', 'SID_norm'])
    n0 = len(df)
    keep = ~sid_norm.isin(excl)
    df = df[keep].copy()
    sid_norm = sid_norm[keep]
    m_otp = sid_norm.isin(otp)
    for col, val in (('SA_PU_Late', 0), ('SA_PU_OT', 1)):
        if col in df.columns:
            df.loc[m_otp, col] = val
    m_otd = sid_norm.isin(otd)
    for col, val in (('SA_Del_Late', 0), ('SA_Del_OT', 1)):
        if col in df.columns:
            df.loc[m_otd, col] = val
    print(f'  [{label}] excluded {n0 - len(df)} rows; '
          f'forced OTP on {int(m_otp.sum())} rows'
          + (f'; forced OTD on {int(m_otd.sum())} rows' if otd else ''), flush=True)
    return df


DEFAULT_NARRATIVE = {
    # Bare-minimum starter narrative so the deck doesn't have empty bullet sections
    # when no narrative.yaml is provided.  Replace by writing narrative_<month>.yaml
    # and passing --narrative.
    'agenda': {'items': [
        'On Time Carrier Performance Analysis',
        'Shipping Exceptions Analysis', 'Operations Update',
        'Shipping Weight & Spend Analysis', 'Carrier Tender Performance Analysis',
        'Claims and Complaints Analysis', 'Temperature Control Analysis',
        'Expedite Tracking Analysis', 'Conclusion',
    ]},
    'safety': {'title': 'Monthly Safety Share', 'items': [
        '[Edit narrative.yaml to customize this month\'s safety topic]',
    ]},
    'pu_ltl': {
        'history': ['[Auto-fill: see charts on the right for actual %late]'],
        'rca': ['[Edit narrative.yaml -> pu_ltl.rca for root cause bullets]'],
        'plan': ['[Edit narrative.yaml -> pu_ltl.plan for action plan bullets]'],
    },
    'pu_tl': {
        'history': ['[Edit narrative.yaml -> pu_tl.history]'],
        'rca': ['[Edit narrative.yaml -> pu_tl.rca]'],
        'plan': ['[Edit narrative.yaml -> pu_tl.plan]'],
    },
    'del_ltl': {
        'history': ['[Edit narrative.yaml -> del_ltl.history]'],
        'rca': ['[Edit narrative.yaml -> del_ltl.rca]'],
        'plan': ['[Edit narrative.yaml -> del_ltl.plan]'],
    },
    'del_tl': {
        'history': ['[Edit narrative.yaml -> del_tl.history]'],
        'rca': ['[Edit narrative.yaml -> del_tl.rca]'],
        'plan': ['[Edit narrative.yaml -> del_tl.plan]'],
    },
}


def load_narrative(path: Optional[str]) -> Dict:
    """Load narrative YAML/JSON.  Returns embedded default if no file found.

    If `path` is None, tries to auto-locate a narrative file in the script's
    own directory: first narrative_<month>.yaml, then narrative.yaml, then
    narrative_example.yaml.  Falls back to DEFAULT_NARRATIVE so slides always
    show at least placeholder text rather than empty space.
    """
    if not path:
        for candidate_name in ['narrative.yaml', 'narrative_example.yaml']:
            candidate = Path(__file__).with_name(candidate_name)
            if candidate.exists():
                path = str(candidate)
                print(f'  Using narrative file: {candidate}', flush=True)
                break
    if not path or not Path(path).exists():
        print('  No narrative file found -- using embedded defaults.', flush=True)
        print('  Tip: copy narrative_example.yaml to your script folder and edit it.', flush=True)
        return DEFAULT_NARRATIVE
    text = Path(path).read_text(encoding='utf-8')
    try:
        import yaml
        loaded = yaml.safe_load(text) or {}
        # Merge with default so any missing keys still produce placeholder content
        merged = dict(DEFAULT_NARRATIVE)
        merged.update(loaded)
        return merged
    except Exception:
        return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description='Build full MOR-style HTML report.')
    parser.add_argument('--report-month', required=True, help='YYYY-MM (e.g. 2026-02)')
    parser.add_argument('--narrative', help='YAML/JSON with manual narrative content')
    parser.add_argument('--tender-hyper', help='(LEGACY) Path to Tender Dashboard .hyper extract. NOT needed -- tender data is pulled directly from CL709 SQL.')
    parser.add_argument('--claims-hyper', help='Path to Claims Dashboard .hyper extract')
    parser.add_argument('--hyper-extract', help='Path to existing 810/712 Hyper extract (for performance script)')
    parser.add_argument('--output-dir', default='.', help='Output directory for the HTML')
    parser.add_argument('--market-pptx', help='Path to market update PPTX (slides appended at end of report)')
    parser.add_argument('--adjustments', help='CSV of one-off SID adjustments (SID, Action=exclude|otp|otd). '
                        'Auto-detected as manual_adjustments_<report-month>.csv when not passed.')
    args = parser.parse_args()

    print('=' * 60, flush=True)
    print('  Akzo MOR Full Report Generator  --  build 2026-08-21', flush=True)
    print('=' * 60, flush=True)

    perf_mod = _import_perf_module()
    sql_start, sql_end, labels, ym_list, report_ym = perf_mod.build_date_window(args.report_month)
    print(f'Reporting window: {labels} (report month: {report_ym})')

    # Use the perf script's data ingestion.  Returns 8-tuple including df_tender
    # (from CL709 SQL), df_712_wide (SID->Mode/Loc lookup for 12-month tender
    # history), and df_bu (the raw Akzo Origins BU lookup table -- needed for
    # tender-specific dual-key BU logic).
    perf_df, cost_df, labels, ym_list, report_ym, df_tender_sql, df_712_wide, df_bu, perf_df_all_moves, df_712_allmoves = perf_mod.prepare_dataset(
        args.report_month, use_hyper=bool(args.hyper_extract), hyper_path=args.hyper_extract or '')

    # Run Super Adjusted computation -- this is what attaches SA_PU_OT / SA_PU_Late /
    # SA_Del_OT / SA_Del_Late plus all the exception flags (Remove_Insuff_TT_Del,
    # OLT_LTL_PU_Excl, etc.) to the DataFrame.
    print('Computing Super Adjusted OTP/OTD...', flush=True)
    perf_df = perf_mod.compute_super_adjusted(perf_df)
    # OTP/OTD slides count ALL movement types (the Akzo Performance dashboard
    # does not filter to Outbound), so compute SA on the all-moves frame and use
    # it for the pickup/delivery performance slides.  The OB-only perf_df still
    # drives the outbound cost / weight / BU-mix slides.
    perf_df_all_moves = perf_mod.compute_super_adjusted(perf_df_all_moves)

    # One-off manual adjustments (confirmed-with-carrier corrections for THIS
    # report month only -- see load_manual_adjustments docstring).
    # gen_notes: generation fingerprint embedded in the HTML (as a comment) and
    # written to reports/adjustments_log_<month>.txt -- so a delivered report
    # carries its own diagnosis even when the console is gone.
    gen_notes = [f'generator build 2026-08-21 | report month {report_ym}']
    _adj = load_manual_adjustments(args.adjustments, report_ym)
    if _adj is None:
        gen_notes.append(f'adjustments: NONE loaded (no --adjustments arg and no '
                         f'manual_adjustments_{report_ym}.csv found in {Path.cwd()})')
    else:
        gen_notes.append(f"adjustments: {len(_adj)} SIDs loaded "
                         f"({int((_adj['Action'] == 'exclude').sum())} exclude, "
                         f"{int((_adj['Action'] == 'otp').sum())} otp, "
                         f"{int((_adj['Action'] == 'otd').sum())} otd)")
        _present = set(_norm_sids(perf_df_all_moves['SID'])) \
            if 'SID' in perf_df_all_moves.columns else set()
        _wanted = set(_adj['SID_norm'])
        _unmatched = sorted(_wanted - _present)
        if _unmatched:
            _note = (f'{len(_unmatched)} of {len(_wanted)} adjustment SIDs not in the '
                     f'dataset (already carrier-excluded, or absent): '
                     f'{", ".join(_unmatched[:12])}{" ..." if len(_unmatched) > 12 else ""}')
            print(f'  NOTE: {_note}', flush=True)
            gen_notes.append('adjustments: ' + _note)
            if _present and len(_unmatched) > 0.3 * len(_wanted):
                _sample = sorted(_present)[:8]
                _hint = (f'>30% of adjustment SIDs are missing.  If that looks wrong, '
                         f'compare SID formats -- dataset SIDs look like: {", ".join(_sample)}')
                print(f'  HINT: {_hint}', flush=True)
                gen_notes.append('adjustments: ' + _hint)
        _before = _otp_otd_snapshot(perf_df_all_moves, ym_list)
        perf_df = apply_manual_adjustments(perf_df, _adj, 'outbound frame')
        perf_df_all_moves = apply_manual_adjustments(perf_df_all_moves, _adj, 'all-moves frame')
        _after = _otp_otd_snapshot(perf_df_all_moves, ym_list)
        # Show the effect right in the console so "nothing changed" can't hide.
        print('  OTP/OTD impact of manual adjustments (count-based, all-moves):', flush=True)
        _fmt = lambda v: f'{v:6.2f}%' if v is not None else '   n/a'
        for k in _before:
            b, a = _before[k], _after.get(k, (None, None))
            marker = '' if (b == a) else '   <-- changed'
            _line = (f'{k:<20} OTP {_fmt(b[0])} -> {_fmt(a[0])}   '
                     f'OTD {_fmt(b[1])} -> {_fmt(a[1])}{marker}')
            print(f'    {_line}', flush=True)
            gen_notes.append('impact: ' + _line)

    # The perf_df has 810-side data with SA flags + Mode + YYYY_MM.  For the
    # 712-driven sections (weight, cost, expedite) we need 712 directly --
    # prepare_dataset returns the merged frame which already contains 712 cols.
    df_712 = perf_df  # joined frame -- has 712 fields

    # Tender data: prefer SQL pull (CL709) if available, fall back to legacy hyper
    if df_tender_sql is not None and len(df_tender_sql) > 0:
        df_tender = normalize_tender_sql(df_tender_sql)
        print(f'Tender data: {len(df_tender):,} rows from CL709 SQL')

        # ---- Tender-specific Mode + BU enrichment ----
        # Tender slides need Mode (to filter slide 24 chart to TL only) and BU
        # (for the BU breakdown table on slide 24).
        #
        # CRITICAL: use cost_df (the unfiltered 712 from prepare_dataset), NOT
        # perf_df / df_712, because prepare_dataset filters perf_df to Outbound
        # only.  Filtering away IB rows here would make the dual-key dest-loc
        # branch below dead code -- no inbound SIDs to look up.  cost_df has
        # all directions (OB, IB, IP) for the 3-month window.
        #
        # BU keying follows the Tender Dashboard's dual logic:
        #   Outbound  -> BU from Akzo Origins lookup keyed by Origin Loc Code
        #   Inbound   -> BU from same lookup keyed by Dest Loc Code
        # (Single source table, different keys per direction.  This surfaces
        # M&PC and other inbound-only BUs that origin-keying alone would miss.)
        sid_src = cost_df if (cost_df is not None and len(cost_df) > 0) else df_712
        if sid_src is not None and len(sid_src) > 0:
            # Build the BU lookup map (uppercased Loc Code -> BU)
            bu_map_dict = {}
            if df_bu is not None and len(df_bu) > 0:
                bu_key_col = next((c for c in ['Origin Loc Code', 'Origin Location Code', 'Origin Loc']
                                   if c in df_bu.columns), None)
                bu_val_col = next((c for c in ['Business Unit', 'Business Unit Name', 'BU']
                                   if c in df_bu.columns), None)
                if bu_key_col and bu_val_col:
                    bu_map_dict = dict(zip(
                        df_bu[bu_key_col].astype(str).str.strip().str.upper(),
                        df_bu[bu_val_col]
                    ))

            # Per-SID attributes from the unfiltered 712 (3-month window, all directions)
            # Include quality-gate columns for the Exclusions filter (mirrors Tableau's
            # **Exclusions calc: drop records where 712 data is invalid/phantom).
            cols_needed = ['SID']
            for c in ['Mode', 'Transport Mode', 'Movement Type', 'Origin Loc Code', 'Dest Loc Code',
                      'Normalized Weight', "Normalized Ship't Actual Cost",
                      'Created Date', 'Pick Up Date', 'Delivery Date']:
                if c in sid_src.columns:
                    cols_needed.append(c)
            per_sid = sid_src[cols_needed].drop_duplicates('SID').copy()

            # ---- 712 Include classification (NOT a filter) ----
            # IMPORTANT: the Tender Dashboard's "BU performance" worksheet applies
            # the 712 Include calc as a UNION filter that keeps ALL FIVE values
            # (the four "Exclude - *" categories PLUS "Include") -- i.e. it does
            # NOT drop the excluded rows.  An earlier version dropped every
            # excluded SID here, which removed ~3-4x of shipments and produced
            # badly low BU counts (M&PC 83 vs dashboard 371, Powder 60 vs 251)
            # and skewed the BU mix (Wood over-represented at 140 vs 29).
            # So we DO NOT drop excluded SIDs -- every tender SID with a 712
            # match is kept, regardless of the Include classification.

            # If 'Mode' isn't on cost_df, derive it from Transport Mode the same
            # way prepare_dataset does for perf_df
            if 'Mode' not in per_sid.columns and 'Transport Mode' in per_sid.columns:
                tmap = {'LTL': 'LTL', 'Truckload': 'Truckload', 'TL': 'Truckload',
                        'Parcel': 'Parcel', 'PARCEL': 'Parcel', 'Rail': 'Rail',
                        'Intermodal': 'Intermodal', 'Ocean': 'Ocean'}
                per_sid['Mode'] = per_sid['Transport Mode'].map(tmap).fillna(per_sid['Transport Mode'])

            # Compute tender-specific BU on the per-SID frame using dual keying
            if 'Movement Type' in per_sid.columns and bu_map_dict:
                mt = per_sid['Movement Type'].astype(str).str.strip().str.upper()
                is_inbound = mt.isin(['INBOUND', 'IB'])
                origin_loc = per_sid['Origin Loc Code'].astype(str).str.strip().str.upper() if 'Origin Loc Code' in per_sid.columns else pd.Series(['']*len(per_sid), index=per_sid.index)
                dest_loc = per_sid['Dest Loc Code'].astype(str).str.strip().str.upper() if 'Dest Loc Code' in per_sid.columns else pd.Series(['']*len(per_sid), index=per_sid.index)
                bu_from_origin = origin_loc.map(bu_map_dict)
                bu_from_dest = dest_loc.map(bu_map_dict)
                per_sid['BU'] = bu_from_origin.copy()
                per_sid.loc[is_inbound, 'BU'] = bu_from_dest[is_inbound]
            elif 'BU' in df_712.columns:
                # Fall back to df_712's existing BU column (origin-keyed only)
                per_sid = per_sid.merge(
                    df_712[['SID', 'BU']].drop_duplicates('SID'),
                    on='SID', how='left',
                )

            # ---- SID NORMALIZATION (critical) ----
            # CL709 stores SID as varchar zero-padded ("0001045812").
            # 712 stores SID as int -> astype(str) gives "1045812" (no padding).
            # A naive astype(str) on both sides DOES NOT MATCH because of the
            # leading zeros.  Normalize by coercing to int first when possible,
            # then back to string -- both sides end up as bare digits.
            def _norm_sid(s):
                """Strip whitespace, drop leading zeros, fall back to original
                stripped string if it's not numeric (e.g. AK-prefixed inbound SIDs)."""
                s = s.astype(str).str.strip()
                num = pd.to_numeric(s, errors='coerce')
                # numeric -> int -> str  (drops leading zeros)
                normalized = num.dropna().astype('int64').astype(str)
                # non-numeric -> keep original (uppercased to be safe)
                out = s.copy()
                out.loc[normalized.index] = normalized
                out.loc[num.isna()] = s.loc[num.isna()].str.upper()
                return out

            per_sid['SID_norm'] = _norm_sid(per_sid['SID'])
            per_sid_indexed = per_sid.drop_duplicates('SID_norm').set_index('SID_norm')

            tender_sids_norm = _norm_sid(df_tender['SID'])
            df_tender['Mode'] = tender_sids_norm.map(per_sid_indexed['Mode']) if 'Mode' in per_sid_indexed.columns else None
            if 'BU' in per_sid_indexed.columns:
                df_tender['BU'] = tender_sids_norm.map(per_sid_indexed['BU'])

            # NOTE: we intentionally do NOT drop tender rows by the 712 Include
            # classification -- the dashboard's BU performance worksheet unions
            # all five Include values (keeps everything).  Tender rows with no
            # 712 match at all simply get a null BU/Mode and fall out of the
            # BU-not-null table naturally, which matches the inner CL709->712
            # join the dashboard performs.

            # ---- WIDE Mode backfill from df_712_wide (12-month SID->Mode lookup) ----
            # The 3-month per_sid above only covers the report window.  For older
            # tender months (history bars on slide 24's trend chart), pull Mode
            # from df_712_wide which has 12 months of SID->Transport Mode pairs.
            #
            # CRITICAL: apply the SAME Type of Movement (KPI) filter to the wide
            # lookup that we apply to perf_df.  Otherwise the lookup leaks
            # Inbound (AK-prefix SIDs) and Interplant (Akzo->Akzo movements)
            # TL SIDs into the tender chart's TL filter, inflating bar height
            # ~40% and shipment count ~2.5x vs the Tableau dashboard's TL OB view.
            #
            # The KPI classifier (per the Tableau Tender KPI Dashboard):
            #   SID contains 'AK'                       -> Inbound  (drop)
            #   Origin and Destination both Akzo-y      -> Interplant (drop)
            #   otherwise                                -> Outbound (keep)
            if df_712_wide is not None and len(df_712_wide) > 0:
                # Apply KPI movement filter to the wide lookup
                if {'Movement Type', 'Origin Name', 'Destination Name'} <= set(df_712_wide.columns):
                    wide_sid = df_712_wide['SID'].astype(str).str.upper()
                    is_ak = wide_sid.str.contains('AK', regex=False, na=False)
                    on_lower = df_712_wide['Origin Name'].astype(str).str.lower().fillna('')
                    dn_lower = df_712_wide['Destination Name'].astype(str).str.lower().fillna('')
                    akzo_kw = ['akzo', 'international paint', 'international coatings',
                                'weber', 'santa fe springs dc']
                    on_is_akzo = pd.Series(False, index=df_712_wide.index)
                    dn_is_akzo = pd.Series(False, index=df_712_wide.index)
                    for kw in akzo_kw:
                        on_is_akzo |= on_lower.str.contains(kw, na=False, regex=False)
                        dn_is_akzo |= dn_lower.str.contains(kw, na=False, regex=False)
                    is_interplant = on_is_akzo & dn_is_akzo
                    is_ob_kpi = ~is_ak & ~is_interplant
                    df_712_wide_ob = df_712_wide[is_ob_kpi].copy()
                    print(f'  Wide lookup KPI-filtered: {len(df_712_wide_ob):,} of '
                          f'{len(df_712_wide):,} rows are OB ({len(df_712_wide) - len(df_712_wide_ob):,} '
                          'IB/IP dropped)')
                else:
                    df_712_wide_ob = df_712_wide

                tmap_wide = {'LTL': 'LTL', 'Truckload': 'Truckload', 'TL': 'Truckload',
                             'Parcel': 'Parcel', 'PARCEL': 'Parcel', 'Rail': 'Rail',
                             'Intermodal': 'Intermodal', 'Ocean': 'Ocean'}
                wide_norm_sid = _norm_sid(df_712_wide_ob['SID'])
                wide_mode = df_712_wide_ob['Transport Mode'].map(tmap_wide).fillna(df_712_wide_ob['Transport Mode'])
                wide_map = pd.Series(wide_mode.values, index=wide_norm_sid).groupby(level=0).first()
                # Backfill: where df_tender['Mode'] is still NaN, fill from wide_map
                missing_mask = df_tender['Mode'].isna()
                if missing_mask.any():
                    fill_vals = tender_sids_norm[missing_mask].map(wide_map)
                    df_tender.loc[missing_mask, 'Mode'] = fill_vals.values
                    n_backfilled = fill_vals.notna().sum()
                    print(f'  Tender Mode backfilled from wide 712: {n_backfilled:,} rows '
                          f'({len(df_712_wide_ob):,} OB-only SIDs in 12-month wide lookup)')

                # ALSO drop tender rows whose SID is in df_712_wide but NOT OB-classified.
                # Without this, tender SIDs that got Mode attached via the 3-month per_sid
                # branch (which has its own filter logic) but are IB/IP per the wide-lookup
                # classifier will still appear in the chart.
                wide_all_sids = set(_norm_sid(df_712_wide['SID']).tolist())
                wide_ob_sids = set(_norm_sid(df_712_wide_ob['SID']).tolist())
                wide_non_ob_sids = wide_all_sids - wide_ob_sids
                if wide_non_ob_sids:
                    non_ob_mask = tender_sids_norm.isin(wide_non_ob_sids)
                    n_dropped = non_ob_mask.sum()
                    if n_dropped > 0:
                        df_tender = df_tender.loc[~non_ob_mask].copy()
                        tender_sids_norm = tender_sids_norm.loc[~non_ob_mask]
                        print(f'  Tender rows dropped (SID is IB/IP per KPI): {n_dropped:,}')

            n_mode = df_tender['Mode'].notna().sum() if 'Mode' in df_tender.columns else 0
            n_bu = df_tender['BU'].notna().sum() if 'BU' in df_tender.columns else 0
            print(f'  Tender Mode attached: {n_mode:,}/{len(df_tender):,} rows total')
            print(f'  Tender BU attached:   {n_bu:,}/{len(df_tender):,} rows')
            if 'Movement Type' in per_sid_indexed.columns:
                ib_sids_norm = per_sid_indexed.index[
                    per_sid_indexed['Movement Type'].astype(str).str.strip().str.upper().isin(['INBOUND', 'IB'])
                ]
                n_ib_attached = tender_sids_norm.isin(ib_sids_norm).sum() if len(ib_sids_norm) > 0 else 0
                print(f'  Tender IB SIDs in 3-month window: {len(ib_sids_norm):,}; '
                      f'matched in tender: {n_ib_attached:,}')
    else:
        df_tender = load_tender_data(args.tender_hyper) if args.tender_hyper else None
        if df_tender is not None:
            print(f'Tender data: {len(df_tender):,} rows from hyper extract (legacy path)')

    df_claims = None
    if args.claims_hyper:
        try:
            df_claims = load_claims_data(args.claims_hyper)
        except Exception as e:
            # Do NOT kill the whole report over the (optional) claims input --
            # generate everything else and let slides 27-28 fall back to
            # manual placeholders.
            print('=' * 60, flush=True)
            print(f'WARN: claims data could not be loaded: {e}', flush=True)
            if 'group policy' in str(e).lower() or 'Hyper instance' in str(e):
                print('  Windows group policy blocked the Tableau Hyper engine '
                      '(hyperd.exe inside the pantab package).', flush=True)
                print('  Options:', flush=True)
                print('   1) Ask IT to whitelist hyperd.exe at the path shown above, or', flush=True)
                print('   2) Export the claims data from the Tableau dashboard to CSV/XLSX,', flush=True)
                print('      drop it in this folder (e.g. "Claims and Complaints.csv"),', flush=True)
                print('      and re-run -- no Hyper engine is needed for CSV/XLSX.', flush=True)
            print('  Continuing WITHOUT claims -- slides 27-28 will be manual placeholders.', flush=True)
            print('=' * 60, flush=True)
    if df_claims is None:
        # Auto-detect a claims extract in the working / output dir if not passed.
        import glob as _glob
        search_dirs = [Path(args.output_dir), Path.cwd(), Path(__file__).parent,
                       Path.home() / 'Downloads', Path('/mnt/user-data/uploads')]
        cand = []
        for d in search_dirs:
            for pat in ['*laim*.twbx', '*laim*.hyper', '*omplaint*.twbx', '*omplaint*.hyper',
                        '*laim*.csv', '*laim*.xlsx', '*omplaint*.csv', '*omplaint*.xlsx']:
                cand += _glob.glob(str(Path(d) / pat))
        cand = [p for p in cand if not os.path.basename(p).startswith('~$')]
        # Don't retry the exact path that already failed above.
        if args.claims_hyper:
            _failed = os.path.abspath(args.claims_hyper)
            cand = [p for p in cand if os.path.abspath(p) != _failed]
        cand = sorted(set(cand), key=lambda p: os.path.getmtime(p), reverse=True)
        if cand:
            # Try candidates newest-first until one loads (e.g. the twbx fails
            # because hyperd.exe is blocked, but a CSV export loads fine).
            for _c in cand:
                print(f'Auto-detected claims source: {_c}', flush=True)
                try:
                    df_claims = load_claims_data(_c)
                    break
                except Exception as e:
                    print(f'WARN: claims auto-load failed ({e}); trying next candidate.', flush=True)
            if df_claims is None:
                print('WARN: no claims candidate loaded; claims slides will be skipped.', flush=True)
        else:
            print('No claims extract passed or found; claims slides will be skipped. '
                  '(pass --claims-hyper to include them)', flush=True)
    # Loud sanity check: claims loaded but none in the reporting window means
    # empty claims slides -- surface it at generation time, not in review.
    if df_claims is not None and 'YYYY_MM' in df_claims.columns:
        _present = set(df_claims['YYYY_MM'].dropna())
        _missing = [m for m in ym_list if m not in _present]
        if _missing:
            print('!' * 60, flush=True)
            print(f'WARN: claims data has NO rows for report month(s): '
                  f'{", ".join(_missing)}', flush=True)
            _shown = sorted(str(x) for x in _present if str(x).strip())[-8:]
            print(f'      Month values present in the claims source: '
                  f'{", ".join(_shown) if _shown else "(none)"}', flush=True)
            print('      Claims slides will be EMPTY for the missing months -- check the', flush=True)
            print('      month column format in the claims export.', flush=True)
            print('!' * 60, flush=True)

    market_path = args.market_pptx
    if not market_path:
        import glob as _glob
        search_dirs = [Path(args.output_dir), Path.cwd(), Path(__file__).parent,
                       Path.home() / 'Downloads', Path('/mnt/user-data/uploads')]
        mcand = []
        for d in search_dirs:
            mcand += _glob.glob(str(Path(d) / '*arket*.pptx'))
        # Exclude Microsoft Office lock/temp files (~$prefix) -- these are not
        # real pptx packages and python-pptx cannot open them.  This was the
        # cause of "Package not found at ...~$Quantix...pptx".
        mcand = [p for p in mcand if not os.path.basename(p).startswith('~$')]
        mcand = sorted(set(mcand), key=lambda p: os.path.getmtime(p), reverse=True)
        if mcand:
            market_path = mcand[0]
            print(f'Auto-detected market PPTX: {market_path}', flush=True)
        else:
            print('No market PPTX passed or found; market slides will be skipped.', flush=True)
            print('  Searched these directories for *arket*.pptx:', flush=True)
            for d in search_dirs:
                print(f'    - {d}', flush=True)
            print('  Fix: put the market deck in one of the above, or pass '
                  '--market-pptx /full/path/to/deck.pptx', flush=True)

    narrative = load_narrative(args.narrative)

    if df_claims is not None and 'YYYY_MM' in df_claims.columns:
        _cm = sorted(str(m) for m in set(df_claims['YYYY_MM'].dropna()) if str(m).strip())
        gen_notes.append(f'claims: {len(df_claims)} rows, months {", ".join(_cm[-6:])}')
    else:
        gen_notes.append('claims: none loaded')

    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    # Sidecar diagnostics file -- same content as the HTML's GEN-INFO comment.
    _log_path = out_dir / f'adjustments_log_{report_ym}.txt'
    try:
        _log_path.write_text('\n'.join(gen_notes) + '\n', encoding='utf-8')
        print(f'Diagnostics written: {_log_path}', flush=True)
    except Exception as _e:
        print(f'WARN: could not write {_log_path}: {_e}', flush=True)

    html = build_full_html(perf_df, df_712, df_tender, df_claims,
                            ym_list, labels, report_ym, narrative,
                            market_pptx_path=market_path,
                            perf_df_all_moves=perf_df_all_moves,
                            df_712_allmoves=df_712_allmoves,
                            gen_info='\n'.join(gen_notes))
    out_file = out_dir / f'Akzo_MOR_Full_{report_ym}.html'
    out_file.write_text(html, encoding='utf-8')
    print(f'Report saved: {out_file}')
    # Inclusion summary -- makes it obvious which optional sections made it in.
    claims_n = 0 if df_claims is None else len(df_claims)
    print('--- Report section summary ---')
    print(f'  Performance/OTP-OTD slides: included')
    print(f'  Tender slides:              {"included" if (df_tender is not None and len(df_tender)) else "SKIPPED (no tender data)"}')
    print(f'  Claims/Complaints slides:   {"included (" + str(claims_n) + " claim rows)" if claims_n else "SKIPPED (no claims extract found)"}')
    print(f'  Market update slides:       {"included (" + str(market_path) + ")" if market_path else "SKIPPED (no market PPTX found)"}')


if __name__ == '__main__':
    main()
