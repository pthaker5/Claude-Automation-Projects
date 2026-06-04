"""
DC&E Billing Audit — SQL Client v2
Optimized: single-query Lost Revenue, pre-aggregated event log view,
thread-safe connection factory for parallel execution.
"""

import os
import struct
import json
import math
import urllib.request
import urllib.parse
from datetime import date, timedelta
from decimal import Decimal

import pyodbc

# ── Connection settings ───────────────────────────────────────────────────────
# Default to the on-prem EDW (Windows / Trusted auth) — the Azure endpoint
# (dev-quantix-useast-sql.database.windows.net) is blocked by VPN/firewall and
# fails with a TLS prelogin / 10054 "connection forcibly closed" error.
# EDW_SERVER/EDW_DB take precedence; legacy EDW_DEV_* names still work.
SERVER   = os.getenv("EDW_SERVER")  or os.getenv("EDW_DEV_SERVER", "az-bwprod.chemlogix.com")
DATABASE = os.getenv("EDW_DB")      or os.getenv("EDW_DEV_DB", "CLXDW")
PORT     = os.getenv("EDW_PORT", "1433")
TENANT   = os.getenv("EDW_SP_TENANT_ID", "")
CID      = os.getenv("EDW_SP_CLIENT_ID", "")
CSEC     = os.getenv("EDW_SP_CLIENT_SECRET", "")

# Auth: "trusted" = Windows integrated (on-prem); "sp" = Azure AD service principal.
# Blank = auto: use sp only when SP creds are set AND the server is Azure SQL.
EDW_AUTH    = os.getenv("EDW_AUTH", "").strip().lower()
ENCRYPT     = os.getenv("EDW_ENCRYPT", "yes")          # yes | no | optional
TRUST_CERT  = os.getenv("EDW_TRUST_CERT", "yes")       # yes | no
LOGIN_TIMEOUT = int(os.getenv("EDW_LOGIN_TIMEOUT", "60"))


def _auth_mode():
    if EDW_AUTH in ("trusted", "windows", "integrated"):
        return "trusted"
    if EDW_AUTH in ("sp", "serviceprincipal", "service_principal", "azuread", "aad"):
        return "sp"
    # auto-detect
    if TENANT and CID and CSEC and "database.windows.net" in SERVER.lower():
        return "sp"
    return "trusted"


def _base_conn_str():
    return (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{SERVER},{PORT};Database={DATABASE};"
        f"Encrypt={ENCRYPT};TrustServerCertificate={TRUST_CERT};"
    )


def get_connection():
    """Thread-safe: each call returns a fresh connection.

    Supports on-prem SQL Server (Windows/Trusted auth) and Azure SQL
    (Azure AD service-principal token), selected by EDW_AUTH (default: auto).
    """
    mode = _auth_mode()
    try:
        if mode == "sp":
            url  = f"https://login.microsoftonline.com/{TENANT}/oauth2/token"
            data = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": CID,
                "client_secret": CSEC,
                "resource": "https://database.windows.net/",
            }).encode()
            token = json.loads(urllib.request.urlopen(url, data).read())["access_token"]
            tb = token.encode("utf-16-le")
            ts = struct.pack(f"<I{len(tb)}s", len(tb), tb)
            conn = pyodbc.connect(_base_conn_str(), attrs_before={1256: ts},
                                  timeout=LOGIN_TIMEOUT)
        else:  # trusted (Windows integrated) — on-prem
            conn = pyodbc.connect(_base_conn_str() + "Trusted_Connection=yes;",
                                  timeout=LOGIN_TIMEOUT)
    except pyodbc.Error as e:
        raise RuntimeError(
            f"Could not connect to {SERVER}:{PORT}/{DATABASE} (auth={mode}). "
            f"Check EDW_SERVER/EDW_DB/EDW_AUTH in .env and that you're on the VPN. "
            f"If TLS prelogin fails on an old server, try EDW_ENCRYPT=optional. "
            f"Original error: {e}"
        ) from e
    conn.timeout = 600
    return conn


def _fix(rows, cols):
    """Convert DB rows to JSON-safe dicts.
    Nulls: numeric types → 0, strings → '', dates → None (JS handles null dates).
    Prevents JS engine() crashes on .toFixed()/.trim()/.toUpperCase() of undefined.
    """
    result = []
    for row in rows:
        d = {}
        for i, col in enumerate(cols):
            v = row[i]
            if v is None:
                d[col] = None  # will be post-processed below
            elif isinstance(v, Decimal):
                d[col] = float(v)
            elif hasattr(v, 'isoformat'):
                d[col] = v.isoformat()
            else:
                d[col] = v
        result.append(d)

    # Infer types from first non-null value per column, then coalesce nulls
    if result:
        col_defaults = {}
        for col in cols:
            for r in result:
                v = r.get(col)
                if v is not None:
                    if isinstance(v, (int, float)):
                        col_defaults[col] = 0
                    elif isinstance(v, str):
                        col_defaults[col] = ''
                    # dates stay None — JS null is fine for date fields
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


# ── Reports (each opens/closes its own connection for thread safety) ──────────

def pull_invoice(start, end):
    conn = get_connection()
    try:
        rows = _q(conn, """
SELECT cm.wh_id AS [WH ID], cust.customer_code AS [Customer Code],
       cust.customer_name AS [Customer Name], cb.chargeback_code AS [Chargeback Code],
       cb.description AS [Charge Description], c.rate AS [Rate],
       cr.per_text AS [Per], CAST(c.charge_amount AS FLOAT) AS [Charge Amount],
       c.charge_date_time AS [Charge Date], c.order_num_value AS [Order Number],
       inv.invoice_number AS [Invoice Number], inv.closed_date AS [Invoice Date],
       c.reason_text_value AS [Description 2], c.prompt_text_value AS [Qty]
FROM Korber.t_bmm_charge c
JOIN Korber.t_bmm_cont_inv_type_chargeback cb ON c.chargeback_id = cb.chargeback_id
JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
JOIN Korber.t_bmm_contract_invoice_type cit ON cb.contract_invoice_type_id = cit.contract_invoice_type_id
JOIN Korber.t_bmm_contract_master cm ON cit.contract_id = cm.contract_id
JOIN Korber.t_bmm_customer cust ON cm.customer_id = cust.customer_id
LEFT JOIN Korber.t_bmm_chargeback_rate cr ON c.chargeback_rate_id = cr.chargeback_rate_id
WHERE inv.closed_date >= ? AND inv.closed_date < ? AND c.charge_amount <> 0
""", [start, end])
        return rows
    finally:
        conn.close()


def pull_rates():
    """Pull WMS rates directly from Korber billing chain (two queries).
    Query 1: Chargeback rates — warehouse-specific with per_text, order_type, container_type.
    Query 2: Manual prompt rates — contract-level flat rates (no warehouse, no per_text).
    """
    conn = get_connection()
    try:
        # Query 1: WMS chargeback rates
        wms_rates = _q(conn, """
SELECT
    cust.customer_code,
    cm.wh_id              AS contract_wh_id,
    citch.chargeback_code,
    citch.description,
    cbr.rate,
    cbr.per_text,
    cbr.order_type,
    cbr.container_type,
    cbr.precedence
FROM Korber.t_bmm_chargeback_rate cbr
JOIN Korber.t_bmm_cont_inv_type_chargeback citch
    ON cbr.chargeback_id = citch.chargeback_id
JOIN Korber.t_bmm_contract_invoice_type cit
    ON citch.contract_invoice_type_id = cit.contract_invoice_type_id
JOIN Korber.t_bmm_contract_master cm
    ON cit.contract_id = cm.contract_id
JOIN Korber.t_bmm_customer cust
    ON cm.customer_id = cust.customer_id
WHERE cbr.rate <> 0
""")

        # Query 2: Manual prompt rates (flat / contract-level)
        manual_rates = _q(conn, """
SELECT
    cust.customer_code,
    NULL                  AS contract_wh_id,
    citch.chargeback_code,
    citch.description,
    pmp.rate,
    NULL                  AS per_text,
    'All'                 AS order_type,
    'All'                 AS container_type,
    NULL                  AS precedence
FROM Korber.t_bmm_param_manual_prompt pmp
JOIN Korber.t_bmm_cont_inv_type_chargeback citch
    ON pmp.chargeback_id = citch.chargeback_id
JOIN Korber.t_bmm_contract_invoice_type cit
    ON citch.contract_invoice_type_id = cit.contract_invoice_type_id
JOIN Korber.t_bmm_contract_master cm
    ON cit.contract_id = cm.contract_id
JOIN Korber.t_bmm_customer cust
    ON cm.customer_id = cust.customer_id
WHERE pmp.rate > 0
""")

        return wms_rates + manual_rates
    finally:
        conn.close()


def pull_lost_revenue(start, end):
    """
    Optimization #1: Single query with LEFT JOINs for vessel, charges, and
    pre-aggregated event log counts (DW_CORE.vw_event_log_counts).
    Replaces 4 sequential batched queries (~36 round trips) with 1.
    """
    conn = get_connection()
    try:
        # Step 1: orders + event log counts (fast — date-filtered, view is pre-aggregated)
        orders = _q(conn, """
SELECT o.wh_id AS [WH ID], o.display_order_number AS [Order Number],
       cl.name AS [Name], o.client_code AS [Client Code],
       o.actual_ship_date AS [Ship Date], o.bol_number AS [BOL Number],
       o.carrier AS [Carrier Name], o.order_id AS _oid,
       ISNULL(el.billing_link_count, 0) AS [Billing Link],
       ISNULL(el.our_supplies_count, 0) AS [Our Supplies]
FROM Korber.t_order o
LEFT JOIN Korber.t_client cl
    ON o.client_code = cl.client_code AND o.wh_id = cl.wh_id
LEFT JOIN DW_CORE.vw_event_log_counts el
    ON el.order_number = o.display_order_number AND el.wh_id = o.wh_id
WHERE o.actual_ship_date >= ? AND o.actual_ship_date < ?
  AND o.status IN ('SHIPPED','COMPLETE')
""", [start, end])
        if not orders:
            return orders

        oids  = list({int(r["_oid"]) for r in orders if r.get("_oid")})
        onums = list({r["Order Number"] for r in orders if r.get("Order Number")})
        BATCH = 500

        # Step 2: vessel info (batched by order_id — integer key, fast)
        vmap = {}
        for i in range(0, len(oids), BATCH):
            chunk = oids[i:i+BATCH]
            ph = ",".join("?" * len(chunk))
            for r in _q(conn, f"SELECT od.order_id AS id, MIN(od.source_vessel) AS sv, MIN(od.dest_vessel) AS dv FROM Korber.t_order_detail od WHERE od.order_id IN ({ph}) GROUP BY od.order_id", chunk):
                vmap[r["id"]] = (r["sv"], r["dv"])

        # Step 3: charges (batched by order number)
        ab = {}
        for i in range(0, len(onums), BATCH):
            chunk = onums[i:i+BATCH]
            ph = ",".join("?" * len(chunk))
            for r in _q(conn, f"SELECT order_num_value AS n, SUM(CAST(charge_amount AS FLOAT)) AS t FROM Korber.t_bmm_charge WHERE order_num_value IN ({ph}) GROUP BY order_num_value", chunk):
                ab[r["n"]] = r["t"]

        # Step 4: assemble
        rows = []
        for r in orders:
            o = r["Order Number"]
            oid = r.get("_oid")
            sv, dv = vmap.get(oid, ("", ""))
            rows.append({
                "WH ID": r["WH ID"], "Order Number": o, "Name": r["Name"],
                "Client Code": r["Client Code"],
                "Amount Billed": ab.get(o, 0),
                "Ship Date": r["Ship Date"], "BOL Number": r["BOL Number"],
                "Order Type": "", "Carrier Name": r["Carrier Name"],
                "Comment": "",
                "Source Vessel": sv, "Dest Vessel": dv,
                "Our Supplies": r["Our Supplies"], "Billing Link": r["Billing Link"],
                "Charge": "", "Corrected Amount": "", "Difference": "", "Reason": "",
            })
        return rows
    finally:
        conn.close()


def pull_railcar(start, end):
    conn = get_connection()
    try:
        return _q(conn, """
SELECT am.wh_id AS [WH ID], am.client_code AS [Client Code], cl.name AS [Client Name],
       ad.hu_id AS [Railcar], am.delivery_date AS [Arrived Date]
FROM Korber.t_asn_master am
JOIN Korber.t_asn_detail ad ON am.asn_number = ad.asn_number AND am.wh_id = ad.wh_id
LEFT JOIN Korber.t_client cl ON am.client_code = cl.client_code AND am.wh_id = cl.wh_id
WHERE am.delivery_date >= ? AND am.delivery_date < ? AND ad.vessel = 'RAILCAR'
""", [start, end])
    finally:
        conn.close()


def pull_packaging(start, end):
    conn = get_connection()
    try:
        return _q(conn, """
SELECT o.wh_id AS [Warehouse], o.display_order_number AS [Order Number],
       '' AS [Comments], o.store_order_number AS [Store Order Number],
       'Packaging Work Order' AS [Type], o.cust_po_number AS [Customer PO Number],
       o.carrier AS [Carrier], o.bol_number AS [BOL Number],
       od.item_description AS [Item Description], od.lot_number AS [Lot Number],
       o.created_by AS [Created By],
       ISNULL(CAST(o.bol_number AS NVARCHAR(200)),'') + ' '
         + ISNULL(CAST(od.item_number AS NVARCHAR(200)),'') + ' '
         + ISNULL(CAST(od.lot_number AS NVARCHAR(200)),'') AS [Text String],
       od.source_vessel AS [Source Vessel], od.dest_vessel AS [Destination Vessel],
       od.qty AS [Quantity], o.order_date AS [Order Date],
       o.actual_ship_date AS [Actual Ship Date], o.client_code AS [Client ID],
       inv.invoice_number AS [Invoice Number], inv.closed_date AS [Closed Date],
       cit.contract_invoice_type_code AS [Contract Invoice Type Code],
       cb.description AS [Description],
       CASE WHEN CHARINDEX('-', o.display_order_number) > 0
            THEN SUBSTRING(o.display_order_number, CHARINDEX('-', o.display_order_number)+1, LEN(o.display_order_number))
            ELSE o.display_order_number END AS [TRIM Order],
       NULL AS [Count Trans]
FROM Korber.t_order o
JOIN Korber.t_order_detail od ON od.order_id = o.order_id
LEFT JOIN Korber.t_bmm_charge c ON c.order_num_value = o.display_order_number
LEFT JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
LEFT JOIN Korber.t_bmm_cont_inv_type_chargeback cb ON c.chargeback_id = cb.chargeback_id
LEFT JOIN Korber.t_bmm_contract_invoice_type cit ON cb.contract_invoice_type_id = cit.contract_invoice_type_id
WHERE o.display_order_number LIKE 'PW%%' AND o.actual_ship_date >= ? AND o.actual_ship_date < ?
""", [start, end])
    finally:
        conn.close()


def pull_bulk_orders(start, end):
    conn = get_connection()
    try:
        return _q(conn, """
SELECT DISTINCT
    ord.wh_id AS [Warehouse], ord.display_order_number AS [Order Number],
    com.comment_text AS [Comments], ord.store_order_number AS [Store Order Number],
    'Bulk Shipping Order' AS [Type], ord.cust_po_number AS [Customer PO Number],
    ord.carrier AS [Carrier], ord.bol_number AS [BOL Number],
    det.item_description AS [Item Description], det.lot_number AS [Lot Number],
    det.created_by AS [Created By],
    CONCAT('BOL=', ord.bol_number, ' Item Number=', det.item_description,
           ' Lot Number=', det.lot_number) AS [Text String],
    det.source_vessel AS [Source Vessel], det.dest_vessel AS [Destination Vessel],
    det.qty AS [Quantity], ord.order_date AS [Order Date],
    ord.actual_ship_date AS [Actual Ship Date], ord.client_code AS [Client ID],
    sinv.invoice_number AS [Invoice Number], sinv.closed_date AS [Closed Date],
    sinv.contract_invoice_type_code AS [Contract Invoice Type Code],
    sinv.description AS [Description],
    ord.display_order_number AS [TRIM Order],
    (SELECT COUNT(el.tran_type) FROM Korber.t_bmm_event_log el
     WHERE el.tran_type='341' AND el.order_number=ord.display_order_number
       AND el.wh_id=ord.wh_id GROUP BY el.order_number) AS [Count Trans]
FROM Korber.t_order ord
LEFT JOIN Korber.t_order_comment com ON com.order_id = ord.order_id
LEFT JOIN (
    SELECT c2.order_num_value AS Order_Num, inv2.invoice_number, inv2.closed_date,
           cit2.contract_invoice_type_code, cb2.description
    FROM Korber.t_bmm_charge c2
    JOIN Korber.t_bmm_invoice inv2 ON c2.invoice_id = inv2.invoice_id
    JOIN Korber.t_bmm_cont_inv_type_chargeback cb2 ON c2.chargeback_id = cb2.chargeback_id
    JOIN Korber.t_bmm_contract_invoice_type cit2 ON cb2.contract_invoice_type_id = cit2.contract_invoice_type_id
) sinv ON sinv.Order_Num = ord.display_order_number
JOIN Korber.t_order_detail det ON det.order_id = ord.order_id
WHERE ord.actual_ship_date >= ? AND ord.actual_ship_date < ?
  AND ord.type_id = 668 AND ord.status = 'SHIPPED' AND ord.created_by <> 'AUTO'
""", [start, end])
    finally:
        conn.close()


def pull_no_charges(start, end):
    """No-Charges report (SSRS: HJ - Billable Activity with No Charges).

    Engine contract — return a list of dicts with THESE column names (exactly):
        [Order Number], [WH ID], [Vessel], [Name], [Description], [Date]
    The engine reads r['Order Number'], r['WH ID'], r['Vessel'], r['Name'],
    r['Description'], and r['Date'] (or r['Ship Date']). It only fires the
    Railcar-Switch / Weekend-Miss check on ASN orders with Vessel containing RAILCAR.

    >>> PASTE THE DATASET SQL FROM THE SSRS REPORT HERE <<<
    Get it from: SSRS > Billing/Audit Reports > "HJ - Billable Activity with No
    Charges" > open in Report Builder > Dataset > Query (or export the .rdl and
    read the <CommandText>). Alias the SELECT columns to the bracketed names above
    and bind ? to the date range, e.g.:

        SELECT o.display_order_number AS [Order Number], o.wh_id AS [WH ID],
               od.vessel AS [Vessel], cl.name AS [Name],
               <billable-activity-desc> AS [Description],
               o.actual_ship_date AS [Date]
        FROM ...
        WHERE o.actual_ship_date >= ? AND o.actual_ship_date < ?
          AND <order has billable activity but no matching t_bmm_charge row>

    Until the SQL is added this returns [] (EDW mode simply skips Weekend-Miss).
    """
    return []  # TODO: replace with _q(get_connection(), SQL, [start, end])


def pull_boxing_materials(start, end):
    """Boxing Materials report (SSRS: Qry-HJ-Boxing Materials).

    Engine contract — return a list of dicts with THESE snake_case keys (exactly),
    one row per material/charge line on a PW (packaging work) order:
        order_num, description, customer_name, customer_code, invoice_number,
        qty, charge_amount, wh_id, location, src_vessel, dest_vessel
    (desc2 and closed_date are optional.) order_num must keep the 'PW...' prefix;
    qty and charge_amount must be numeric. With this present the engine runs the
    precise Boxing-Material + Bag-Qty checks; when empty it falls back to a coarse
    invoice-only heuristic (more, noisier flags).

    >>> PASTE THE DATASET SQL FROM THE SSRS REPORT HERE <<<
    Get it from: SSRS > Billing/Audit Reports > "Qry-HJ-Boxing Materials" > open in
    Report Builder > Dataset > Query. Alias columns to the snake_case names above
    and bind ? to the date range. Starting point (mirrors pull_invoice, UNVERIFIED —
    confirm tables/filter against the real report before trusting it):

        SELECT c.order_num_value           AS order_num,
               cb.description              AS description,
               cust.customer_name          AS customer_name,
               cust.customer_code          AS customer_code,
               inv.invoice_number          AS invoice_number,
               CAST(c.prompt_text_value AS FLOAT) AS qty,
               CAST(c.charge_amount AS FLOAT)     AS charge_amount,
               cm.wh_id                    AS wh_id,
               ''                          AS location,
               c.source_vessel             AS src_vessel,
               c.dest_vessel               AS dest_vessel
        FROM Korber.t_bmm_charge c
        JOIN Korber.t_bmm_cont_inv_type_chargeback cb ON c.chargeback_id = cb.chargeback_id
        JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
        JOIN Korber.t_bmm_contract_invoice_type cit ON cb.contract_invoice_type_id = cit.contract_invoice_type_id
        JOIN Korber.t_bmm_contract_master cm ON cit.contract_id = cm.contract_id
        JOIN Korber.t_bmm_customer cust ON cm.customer_id = cust.customer_id
        WHERE inv.closed_date >= ? AND inv.closed_date < ?
          AND c.order_num_value LIKE 'PW%%'

    Until the SQL is added this returns [] (EDW mode uses the coarse fallback).
    """
    return []  # TODO: replace with _q(get_connection(), SQL, [start, end])


def pull_recurring_storage(billing_date, warehouses=None, clients=None):
    if billing_date is None:
        return []
    conn = get_connection()
    try:
        snap_date = billing_date - timedelta(days=1)
        wh_clause = "AND i.wh_id IN ({})".format(",".join("?" * len(warehouses))) if warehouses else ""
        cl_clause = "AND i.client_code IN ({})".format(",".join("?" * len(clients))) if clients else ""

        sql = f"""
WITH BillingBase AS (
    SELECT cust2.customer_code, cm2.wh_id, ch2.lot_number, ch2.item_number,
           CAST(ch2.prompt_text_value AS FLOAT) AS billed_qty,
           ISNULL(pus2.rate_basis,'') AS rate_basis
    FROM Korber.t_bmm_invoice inv2
    JOIN Korber.t_bmm_cont_inv_type_chargeback citch2 ON inv2.contract_invoice_type_id = citch2.contract_invoice_type_id
    JOIN Korber.t_bmm_contract_invoice_type cit2 ON cit2.contract_invoice_type_id = citch2.contract_invoice_type_id
    JOIN Korber.t_bmm_contract_master cm2 ON cm2.contract_id = cit2.contract_id
    JOIN Korber.t_bmm_customer cust2 ON cust2.customer_id = cm2.customer_id
    LEFT JOIN Korber.t_bmm_charge ch2 ON citch2.chargeback_id = ch2.chargeback_id AND ch2.invoice_id = inv2.invoice_id
    LEFT JOIN Korber.t_bmm_param_uom_storage pus2 ON citch2.chargeback_id = pus2.chargeback_id
    WHERE CAST(inv2.closed_date AS DATE) = ? AND cit2.contract_invoice_type_code = 'Group 3'
), BillingAgg AS (
    SELECT customer_code, wh_id, lot_number, item_number,
           SUM(billed_qty) AS invoice_qty, MAX(rate_basis) AS rate_basis
    FROM BillingBase GROUP BY customer_code, wh_id, lot_number, item_number
), SnapAgg AS (
    SELECT i.wh_id, i.client_code, i.lot_number, i.item_number,
           i.display_item_number, i.gen_attribute_value1, i.uom,
           CAST(i.record_create_date AS DATE) AS record_create_date,
           SUM(i.quantity) AS qty, COUNT(i.hu_id) AS lp_count
    FROM Korber.t_al_host_inventory_snapshot i
    WHERE i.gen_attribute_value1 NOT IN ('RAILCAR','ELIMINATOR','CONTAINER','DRYTAINER','TRAILER')
      AND i.location_id NOT IN ('SUPPLY') AND i.wh_id <> '13-160'
      AND CAST(i.record_create_date AS DATE) = ?
      AND NOT EXISTS (SELECT 1 FROM Korber.t_bmm_invoice_ref_information ref
                      WHERE ref.customer_code=i.client_code AND ref.wh_id=i.wh_id AND ISNULL(ref.minimum,'NO')='YES')
      {wh_clause} {cl_clause}
    GROUP BY i.wh_id, i.client_code, i.lot_number, i.item_number,
             i.display_item_number, i.gen_attribute_value1, i.uom, CAST(i.record_create_date AS DATE)
)
SELECT s.wh_id, w.name AS [Whse], c.name AS [Client], s.client_code,
       s.display_item_number, t.description, s.lot_number, s.gen_attribute_value1,
       s.qty, s.uom, s.lp_count AS [LP Count], s.record_create_date,
       ROUND(ISNULL(b.invoice_qty,0),3) AS [invoice_qty],
       ROUND(CASE WHEN ISNULL(b.rate_basis,'')='Rate per Handling Unit' THEN s.lp_count
                  WHEN ISNULL(b.rate_basis,'')='Rate per Unit of Measure' THEN s.qty
                  ELSE s.lp_count END - ISNULL(b.invoice_qty,0), 3) AS [difference]
FROM SnapAgg s
LEFT JOIN BillingAgg b ON b.customer_code=s.client_code AND b.wh_id=s.wh_id
    AND b.lot_number=s.lot_number AND b.item_number=s.item_number
LEFT JOIN Korber.t_client c ON c.client_code=s.client_code AND c.wh_id=s.wh_id
LEFT JOIN Korber.t_whse w ON w.wh_id=s.wh_id
LEFT JOIN Korber.t_item_master t ON t.item_number=s.item_number AND t.wh_id=s.wh_id
WHERE ABS(ROUND(CASE WHEN ISNULL(b.rate_basis,'')='Rate per Handling Unit' THEN s.lp_count
     WHEN ISNULL(b.rate_basis,'')='Rate per Unit of Measure' THEN s.qty
     ELSE s.lp_count END - ISNULL(b.invoice_qty,0), 0)) > 1
ORDER BY s.wh_id, s.client_code, s.lot_number
"""
        params = [billing_date, snap_date] + (list(warehouses) if warehouses else []) + (list(clients) if clients else [])
        return _q(conn, sql, params)
    finally:
        conn.close()
