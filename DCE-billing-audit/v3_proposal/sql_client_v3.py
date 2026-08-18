"""
DC&E Billing Audit — SQL Client v3 (PROPOSAL)
----------------------------------------------
Architecture change: replaces the existing per-report query functions with a
single pre-staged EDW table (CORE.Stg_DCE_OpenInvoiceAudit).

Current v2 approach:
  - 5 separate report functions, each doing its own multi-table join
  - pull_lost_revenue: 3 round-trip loops (orders, vessel batches, charge batches)
  - pull_bulk_orders: correlated subquery on 16M-row event log (N × scan)
  - pull_recurring_storage: 128M-row snapshot scan on every call
  - No rate comparison — charges returned as-is with no contract validation

v3 approach:
  - One staging table: CORE.Stg_DCE_OpenInvoiceAudit
  - Refreshed nightly by ADF (or on-demand); audit logic runs at refresh, not at query time
  - Scope: all open (non-posted) invoices only — status NOT IN ('P')
  - Rate resolution at load time: joined to CORE.Core_Rates by chargeback_id,
    container_type wildcard matching, precedence-ranked per charge
  - Computed at load: expected_amount, discrepancy, rate_variance, flags
  - App reads are simple SELECTs with optional filters — single round trip, <1s

See PROPOSAL.md for full context, tradeoffs, and open questions.
Deploy: run sql/01_DDL and sql/02_proc in Synapse Studio with EDW admin creds,
        then add ADF activity to call CORE.usp_Refresh_DCE_OpenInvoiceAudit nightly.
"""

import os
import struct
import json
import math
import time
import urllib.request
import urllib.parse
from decimal import Decimal

import pyodbc

SERVER   = os.getenv("EDW_DEV_SERVER", "dev-quantix-useast-sql.database.windows.net")
DATABASE = os.getenv("EDW_DEV_DB", "EDW_Dev")
TENANT   = os.getenv("EDW_SP_TENANT_ID", "")
CID      = os.getenv("EDW_SP_CLIENT_ID", "")
CSEC     = os.getenv("EDW_SP_CLIENT_SECRET", "")

# ── Token cache — one AAD fetch per hour regardless of how many reports run ───
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    url  = f"https://login.microsoftonline.com/{TENANT}/oauth2/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CID,
        "client_secret": CSEC,
        "resource": "https://database.windows.net/",
    }).encode()
    resp = json.loads(urllib.request.urlopen(url, data).read())
    _token_cache["token"] = resp["access_token"]
    _token_cache["expires_at"] = time.time() + int(resp.get("expires_in", 3600))
    return _token_cache["token"]


def get_connection():
    """Thread-safe: fresh connection per call, shared token."""
    token = _get_token()
    tb = token.encode("utf-16-le")
    ts = struct.pack(f"<I{len(tb)}s", len(tb), tb)
    conn = pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server=tcp:{SERVER},1433;Database={DATABASE};"
        f"Encrypt=yes;TrustServerCertificate=yes;",
        attrs_before={1256: ts}, timeout=60,
    )
    conn.timeout = 600
    return conn


def _fix(rows, cols):
    """Convert DB rows to JSON-safe dicts."""
    result = []
    for row in rows:
        d = {}
        for i, col in enumerate(cols):
            v = row[i]
            if v is None:
                d[col] = None
            elif isinstance(v, Decimal):
                d[col] = float(v)
            elif hasattr(v, "isoformat"):
                d[col] = v.isoformat()
            else:
                d[col] = v
        result.append(d)
    if result:
        col_defaults = {}
        for col in cols:
            for r in result:
                v = r.get(col)
                if v is not None:
                    if isinstance(v, (int, float)):
                        col_defaults[col] = 0
                    elif isinstance(v, str):
                        col_defaults[col] = ""
                    break
        for r in result:
            for col in cols:
                if r.get(col) is None and col in col_defaults:
                    r[col] = col_defaults[col]
    return result


def _q(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return _fix(cur.fetchall(), cols)


def _clean(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


# ── Staging table refresh ─────────────────────────────────────────────────────

def refresh_audit_table():
    """
    Trigger a full refresh of CORE.Stg_DCE_OpenInvoiceAudit.
    Normally called by ADF nightly. Use for on-demand refresh.
    Typical runtime: 30–90s depending on open invoice volume.
    """
    conn = get_connection()
    try:
        conn.timeout = 300
        cur = conn.cursor()
        cur.execute("EXEC CORE.usp_Refresh_DCE_OpenInvoiceAudit")
        conn.commit()
    finally:
        conn.close()


# ── Report reads ──────────────────────────────────────────────────────────────
# All hit CORE.Stg_DCE_OpenInvoiceAudit — single round trip, no joins at query time.

def pull_open_audit(
    wh_ids=None,
    customer_codes=None,
    chargeback_codes=None,
    discrepancies_only=False,
    manual_charges=True,
):
    """
    Full open-invoice audit. One row per charge line on any non-posted invoice.

    Optional filters (all combinable):
      wh_ids            list[str]   warehouse IDs
      customer_codes    list[str]   customer codes
      chargeback_codes  list[str]   chargeback codes
      discrepancies_only bool       only rows where ABS(discrepancy) > $0.01
      manual_charges    bool        include NULL-expected_amount rows (default True)

    Key audit columns returned:
      charge_amount     — what was billed
      expected_amount   — billed_qty × contracted_rate (NULL = manual or no rate match)
      discrepancy       — charge_amount - expected_amount (+ = overbilled, - = underbilled)
      rate_variance     — billed_rate - contracted_rate
      is_manual_charge  — 1 if prompt_text_value was blank (flat-rate charge)
      has_discrepancy   — 1 if ABS(discrepancy) > $0.01
      rate_match_found  — 0 if no Core_Rates row matched this chargeback/container combo
    """
    conn = get_connection()
    try:
        clauses, params = [], []

        if wh_ids:
            clauses.append(f"wh_id IN ({','.join('?'*len(wh_ids))})")
            params.extend(wh_ids)
        if customer_codes:
            clauses.append(f"customer_code IN ({','.join('?'*len(customer_codes))})")
            params.extend(customer_codes)
        if chargeback_codes:
            clauses.append(f"chargeback_code IN ({','.join('?'*len(chargeback_codes))})")
            params.extend(chargeback_codes)
        if discrepancies_only:
            clauses.append("has_discrepancy = 1")
        if not manual_charges:
            clauses.append("is_manual_charge = 0")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        return _q(conn, f"""
            SELECT *
            FROM CORE.Stg_DCE_OpenInvoiceAudit
            {where}
            ORDER BY customer_code, wh_id, invoice_number, charge_id
        """, params)
    finally:
        conn.close()


def pull_discrepancies(wh_ids=None, customer_codes=None):
    """Shortcut: calculable discrepancies only (has_discrepancy=1, not manual)."""
    return pull_open_audit(
        wh_ids=wh_ids,
        customer_codes=customer_codes,
        discrepancies_only=True,
        manual_charges=False,
    )


def pull_manual_charges(wh_ids=None, customer_codes=None):
    """
    Flat-rate / manual charges (blank prompt_text_value).
    expected_amount is NULL — these need human review, not automated audit.
    """
    conn = get_connection()
    try:
        clauses = ["is_manual_charge = 1"]
        params  = []
        if wh_ids:
            clauses.append(f"wh_id IN ({','.join('?'*len(wh_ids))})")
            params.extend(wh_ids)
        if customer_codes:
            clauses.append(f"customer_code IN ({','.join('?'*len(customer_codes))})")
            params.extend(customer_codes)

        return _q(conn, f"""
            SELECT invoice_number, invoice_status, customer_code, customer_name,
                   wh_id, chargeback_code, chargeback_description, order_num_value,
                   display_order_number, billed_rate, charge_amount, billed_per_text,
                   actual_ship_date, source_vessel, dest_vessel,
                   gl_code_description, contract_invoice_type_code
            FROM CORE.Stg_DCE_OpenInvoiceAudit
            WHERE {' AND '.join(clauses)}
            ORDER BY customer_code, wh_id, invoice_number
        """, params)
    finally:
        conn.close()


def pull_unmatched_rates(wh_ids=None):
    """
    Charges where no contracted rate row was found (rate_match_found=0, not manual).
    Use to identify gaps in CORE.Core_Rates — missing rates or new charge types.
    """
    conn = get_connection()
    try:
        clauses = ["rate_match_found = 0", "is_manual_charge = 0"]
        params  = []
        if wh_ids:
            clauses.append(f"wh_id IN ({','.join('?'*len(wh_ids))})")
            params.extend(wh_ids)

        return _q(conn, f"""
            SELECT customer_code, customer_name, wh_id,
                   chargeback_code, chargeback_description,
                   COUNT(charge_id)      AS charge_count,
                   SUM(charge_amount)    AS total_billed,
                   MIN(actual_ship_date) AS earliest_date,
                   MAX(actual_ship_date) AS latest_date
            FROM CORE.Stg_DCE_OpenInvoiceAudit
            WHERE {' AND '.join(clauses)}
            GROUP BY customer_code, customer_name, wh_id,
                     chargeback_code, chargeback_description
            ORDER BY total_billed DESC
        """, params)
    finally:
        conn.close()


def pull_audit_summary(group_by="customer"):
    """
    Rollup for dashboard / reporting.
    group_by: 'customer' | 'wh' | 'chargeback' | 'invoice'
    """
    dim = {
        "customer":   "customer_code, customer_name",
        "wh":         "wh_id",
        "chargeback": "chargeback_code, chargeback_description",
        "invoice":    "invoice_number, invoice_status, customer_code, wh_id",
    }
    if group_by not in dim:
        raise ValueError(f"group_by must be one of {set(dim)}")

    conn = get_connection()
    try:
        return _q(conn, f"""
            SELECT
                {dim[group_by]},
                COUNT(charge_id)                                        AS total_charges,
                SUM(charge_amount)                                      AS total_billed,
                SUM(ISNULL(expected_amount, 0))                         AS total_expected,
                SUM(ISNULL(discrepancy, 0))                             AS total_discrepancy,
                SUM(CASE WHEN has_discrepancy  = 1 THEN 1 ELSE 0 END)  AS discrepancy_count,
                SUM(CASE WHEN is_manual_charge = 1 THEN 1 ELSE 0 END)  AS manual_count,
                SUM(CASE WHEN rate_match_found = 0
                          AND is_manual_charge = 0 THEN 1 ELSE 0 END)  AS unmatched_rate_count
            FROM CORE.Stg_DCE_OpenInvoiceAudit
            GROUP BY {dim[group_by]}
            ORDER BY total_discrepancy DESC
        """)
    finally:
        conn.close()


# ── Rates reference (unchanged from v2) ───────────────────────────────────────

def pull_rates():
    conn = get_connection()
    try:
        return _q(conn, """
            SELECT customer_code, contract_wh_id, chargeback_code, description,
                   rate, per_text, order_type, container_type, precedence
            FROM CORE.Core_Rates
            WHERE source_table IN ('WMS_Rates', 'WMS_Manual')
        """)
    finally:
        conn.close()
