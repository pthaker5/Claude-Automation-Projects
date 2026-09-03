"""
DC&E Billing Audit — SQL Client v2
Optimized: single-query Lost Revenue, pre-aggregated event log view,
thread-safe connection factory for parallel execution.
"""

import os
import struct
import json
import math
import threading
import time
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from decimal import Decimal

import pyodbc

SERVER   = os.getenv("EDW_DEV_SERVER", "dev-quantix-useast-sql.database.windows.net")
DATABASE = os.getenv("EDW_DEV_DB", "EDW_Dev")
TENANT   = os.getenv("EDW_SP_TENANT_ID", "")
CID      = os.getenv("EDW_SP_CLIENT_ID", "")
CSEC     = os.getenv("EDW_SP_CLIENT_SECRET", "")

# ── Recurring-storage billing-date resolution (v1.16.1) ───────────────────────
# pull_recurring_storage() snaps the requested billing_date to the actual
# Group-3 storage-invoice close date. These expose the resolved value so app.py
# can surface it in the dashboard banner.
LAST_RECURRING_BILLING_DATE = None
LAST_RECURRING_BILLING_AUTORESOLVED = False

# ── Token cache ───────────────────────────────────────────────────────────────
# AAD client_credentials tokens are valid for 1 hour. We cache and reuse across
# connections to skip the AAD round-trip on every pull (saves ~200-400ms per query).
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {"token": None, "expires_at": 0}
_TOKEN_TTL_SAFETY = 300  # refresh 5 min before actual expiry


def _get_aad_token(force_refresh=False):
    """Get a cached AAD token, refreshing if expired or near-expiry."""
    now = time.time()
    with _TOKEN_LOCK:
        if not force_refresh and _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] - _TOKEN_TTL_SAFETY > now:
            return _TOKEN_CACHE["token"]
        url  = f"https://login.microsoftonline.com/{TENANT}/oauth2/token"
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": CID,
            "client_secret": CSEC,
            "resource": "https://database.windows.net/",
        }).encode()
        resp = json.loads(urllib.request.urlopen(url, data, timeout=15).read())
        token = resp["access_token"]
        # expires_in is seconds-from-now
        expires_in = int(resp.get("expires_in", 3600))
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = now + expires_in
        return token


def get_connection(retries=3, backoff=2.0):
    """Thread-safe: each call returns a fresh connection.
    Uses cached AAD token. Retries on transient 08001 handshake failures.
    On 401-style failures, force a token refresh before retrying.
    """
    last_err = None
    force_refresh = False
    for attempt in range(retries):
        try:
            token = _get_aad_token(force_refresh=force_refresh)
            tb = token.encode("utf-16-le")
            ts = struct.pack(f"<I{len(tb)}s", len(tb), tb)
            conn = pyodbc.connect(
                f"Driver={{ODBC Driver 18 for SQL Server}};"
                f"Server=tcp:{SERVER},1433;Database={DATABASE};"
                f"Encrypt=yes;TrustServerCertificate=yes;",
                attrs_before={1256: ts}, timeout=60,
            )
            conn.timeout = 600
            # Read-only reporting connection; autocommit so SELECTs don't hold an open
            # transaction. NOTE: app blocks against hourly Korber/TMW ETL writes because
            # RCSI is OFF on EDW_Dev. Correct fix is DB-level:
            # ALTER DATABASE EDW_Dev SET READ_COMMITTED_SNAPSHOT ON; (raise with EDW owner).
            # READ UNCOMMITTED rejected: dirty reads unsafe for a billing audit (Forge 2026-06-30).
            conn.autocommit = True
            return conn
        except Exception as e:
            last_err = e
            # If auth-shaped error, refresh token next attempt
            msg = str(e).lower()
            if "login" in msg or "token" in msg or "18456" in msg or "401" in msg:
                force_refresh = True
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last_err


# ── Rates cache (disk-persisted, daily refresh) ────────────────────────────────────────
# pull_rates() scans the full Korber rate table chain with no filters and takes
# 70-150s on cold execution. Rates change infrequently (contract amendments and
# rate-card edits), so we keep a disk-persisted snapshot refreshed once per day.
# Strategy:
#   - On import: load snapshot from disk if present (survives app restarts)
#   - On app startup: kick off a background pre-warm so the file refreshes if stale
#   - Background scheduler thread: refresh once per day at REFRESH_HOUR_UTC
#   - Manual refresh: rates_cache_force_refresh() called by /api/refresh-rates
#   - pull_rates() always returns the cached snapshot (or fetches synchronously
#     if disk is empty AND no in-flight pre-warm has finished yet)
_RATES_LOCK = threading.Lock()
_RATES_CACHE = {"rows": None, "fetched_at": 0, "source": None}
# In-memory soft TTL still respected when no disk snapshot is configured.
_RATES_TTL = int(os.getenv("RATES_CACHE_TTL_SECONDS", "86400"))  # 24h default
# Disk path. Azure App Service Linux persists /home across restarts.
_RATES_DISK_PATH = os.getenv("RATES_CACHE_PATH", "/home/site/wwwroot/.cache/rates.json")
# Daily refresh time, UTC hour. 06:00 UTC = ~02:00 ET.
_RATES_REFRESH_HOUR_UTC = int(os.getenv("RATES_DAILY_REFRESH_HOUR_UTC", "6"))
# Stale-warning threshold for UI.
_RATES_STALE_SECONDS = int(os.getenv("RATES_STALE_AFTER_SECONDS", "86400"))  # 24h


def _rates_cache_get():
    with _RATES_LOCK:
        if _RATES_CACHE["rows"] is not None and (time.time() - _RATES_CACHE["fetched_at"]) < _RATES_TTL:
            return _RATES_CACHE["rows"]
    return None


def _rates_cache_set(rows, source="live"):
    with _RATES_LOCK:
        _RATES_CACHE["rows"] = rows
        _RATES_CACHE["fetched_at"] = time.time()
        _RATES_CACHE["source"] = source


def rates_cache_clear():
    """Public helper for a Refresh-Rates button. Clears in-memory only;
    next call to pull_rates() will refetch and re-persist to disk."""
    with _RATES_LOCK:
        _RATES_CACHE["rows"] = None
        _RATES_CACHE["fetched_at"] = 0
        _RATES_CACHE["source"] = None


def rates_cache_status():
    """Return age + source for the UI stale-warning banner."""
    with _RATES_LOCK:
        rows = _RATES_CACHE["rows"]
        fetched_at = _RATES_CACHE["fetched_at"]
        source = _RATES_CACHE["source"]
    if not rows or not fetched_at:
        return {"ready": False, "rows": 0, "fetched_at": None, "age_seconds": None, "stale": True, "source": source}
    age = time.time() - fetched_at
    return {
        "ready": True,
        "rows": len(rows),
        "fetched_at": fetched_at,
        "age_seconds": int(age),
        "stale": age > _RATES_STALE_SECONDS,
        "source": source,
    }


def _rates_disk_load():
    """Load snapshot from disk into the in-memory cache. Safe to call on import."""
    try:
        if not os.path.exists(_RATES_DISK_PATH):
            return False
        with open(_RATES_DISK_PATH, "r") as f:
            blob = json.load(f)
        rows = blob.get("rows") or []
        fetched_at = float(blob.get("fetched_at") or 0)
        if not rows or not fetched_at:
            return False
        with _RATES_LOCK:
            _RATES_CACHE["rows"] = rows
            _RATES_CACHE["fetched_at"] = fetched_at
            _RATES_CACHE["source"] = "disk"
        return True
    except Exception:
        # Disk corrupt or unreadable; fall through to live fetch.
        return False


def _rates_disk_save(rows):
    """Atomically write snapshot to disk so app restarts survive."""
    try:
        os.makedirs(os.path.dirname(_RATES_DISK_PATH), exist_ok=True)
        tmp = _RATES_DISK_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"rows": rows, "fetched_at": time.time()}, f)
        os.replace(tmp, _RATES_DISK_PATH)
        return True
    except Exception:
        return False


def _rates_fetch_live():
    """The actual two-query Korber pull. Called by pull_rates() and the scheduler.
    Returns the list of rate-row dicts."""
    conn = get_connection()
    try:
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


_REFRESH_INFLIGHT = threading.Lock()  # serialize refreshes; non-blocking


def rates_cache_force_refresh():
    """Synchronously refetch rates and update cache + disk. Returns status dict.
    Used by /api/refresh-rates and the daily scheduler."""
    if not _REFRESH_INFLIGHT.acquire(blocking=False):
        return {"ok": False, "reason": "refresh_already_in_progress"}
    try:
        t0 = time.time()
        rows = _rates_fetch_live()
        _rates_cache_set(rows, source="live")
        _rates_disk_save(rows)
        return {"ok": True, "rows": len(rows), "elapsed_seconds": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    finally:
        _REFRESH_INFLIGHT.release()


def _rates_daily_scheduler():
    """Background thread: sleep until next 06:00 UTC, refresh, repeat."""
    from datetime import datetime, timedelta, timezone
    while True:
        try:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=_RATES_REFRESH_HOUR_UTC, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            sleep_seconds = (target - now).total_seconds()
            time.sleep(sleep_seconds)
            rates_cache_force_refresh()
        except Exception:
            # Scheduler must never die; sleep an hour and retry.
            time.sleep(3600)


_STARTUP_DONE = False
_STARTUP_LOCK = threading.Lock()


def rates_cache_startup():
    """Idempotent. Called on first import.
    1. Try to load existing snapshot from disk (instant if file exists).
    2. Kick off a background pre-warm if cache is empty or stale.
    3. Start the daily-refresh scheduler thread.
    """
    global _STARTUP_DONE
    with _STARTUP_LOCK:
        if _STARTUP_DONE:
            return
        _STARTUP_DONE = True
    # Step 1: load from disk if available
    _rates_disk_load()
    # Step 2: if missing or stale, refresh in background (don't block startup)
    status = rates_cache_status()
    if not status["ready"] or status["stale"]:
        threading.Thread(target=rates_cache_force_refresh, daemon=True, name="rates-prewarm").start()
    # Step 3: daily refresh scheduler
    threading.Thread(target=_rates_daily_scheduler, daemon=True, name="rates-scheduler").start()


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

def pull_invoice(start, end, wh_filter=None):
    conn = get_connection()
    try:
        wh_clause = f"AND cm.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        params = [start, end] + (list(wh_filter) if wh_filter else [])
        rows = _q(conn, f"""
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
{wh_clause}
""", params)
        return rows
    finally:
        conn.close()


def pull_billing_horizon(start, end):
    """Authoritative billing horizon for the audit window (v1.16.6, 2026-07-13).

    v1.16.4/.5 BUG: detected billing frontier by volume-cliff — the last
    charge_date_time day whose ROW COUNT cleared an absolute floor of 100/day.
    Natural weekend taper (07-11=267, 07-12=233 charges) tripped the floor even
    though both days were 100% billed (closed_date NOT NULL for all charges),
    collapsing window 2026-07-06..07-13 from 11,794 charges to 21 and displaying
    a false 'Billing pending' banner with 541 rows suppressed.

    v1.16.6 FIX (Forge, 2026-07-13): replace volume-cliff with a closed_date
    COVERAGE test. A work-day is 'billed' when:
        billed_charges / total_charges >= COVERAGE_MIN  (default 0.95)
    This is evaluated regardless of absolute row count, so a light-but-fully-
    billed weekend correctly passes and a genuinely unbilled day fails.

    Days with tiny total (< TINY_DAY_MIN) are treated as billed if their own
    coverage clears COVERAGE_MIN, preventing a 3-charge correction day from
    distorting the frontier.

    material_frontier  = latest work-day in window where coverage >= COVERAGE_MIN.
    batch_complete     = True when no work-days after material_frontier are
                         unbilled (trailing_trickle_days == 0). If a trailing day
                         genuinely has many closed_date-NULL charges, coverage
                         fails, trailing_trickle_days > 0, and batch_complete=False
                         (real pending-batch protection preserved).

    The suppression of charge-completeness checks past the frontier is unchanged;
    only the detection method changed.

    v1.16.7: NOTE — this function must receive the USER'S INCLUSIVE end date,
    not app.py's +1-advanced exclusive bound: the SQL below already advances
    internally via DATEADD(day, 1, ...). Day analysis lives in
    _billing_frontier_analysis() (pure, unit-testable); two hardening guards
    were added there — see its docstring.

    Returns dict: {horizon, max_charge_date, material_frontier, batch_complete,
                   charge_rows, by_day, frontier_method, trailing_trickle_days,
                   frontier_gap_days, window_truncated, billed_after_end,
                   next_close_date}
    """
    COVERAGE_MIN = 0.95   # >= 95% of charges must have closed_date NOT NULL
    TINY_DAY_MIN = 20     # days below this can neither advance nor block the frontier

    conn = get_connection()
    try:
        # Inclusive on charge date: charges dated [start, end] — same window bound
        # as v1.16.4. Join to invoice for closed_date coverage test.
        #
        # v1.16.8: "billed" now means billed WITHIN THE PULLED WINDOW
        # (closed_date <= audit end), not "billed at all". pull_invoice only
        # returns invoices closed inside the window, so a charge closed AFTER the
        # end date is invisible to every completeness check — treating it as
        # "billed" declared batch_complete=True while the engine audited a week
        # of activity against an essentially empty invoice set (observed:
        # window 07-06..07-12 showed 'billing complete' + 21 charges + 844
        # action items, ~all false; the week's batch closed 07-13, one day past
        # the end). billed_late counts those out-of-window closes so the UI can
        # tell the user exactly what to do: extend the end date to next_close.
        rows = _q(conn, """
SELECT CAST(c.charge_date_time AS DATE) AS d,
       COUNT(*) AS total,
       SUM(CASE WHEN inv.closed_date IS NOT NULL
                 AND inv.closed_date < DATEADD(day, 1, CAST(? AS DATE))
            THEN 1 ELSE 0 END) AS billed,
       SUM(CASE WHEN inv.closed_date >= DATEADD(day, 1, CAST(? AS DATE))
            THEN 1 ELSE 0 END) AS billed_late
FROM Korber.t_bmm_charge c
LEFT JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
WHERE c.charge_date_time >= ? AND c.charge_date_time < DATEADD(day, 1, CAST(? AS DATE))
  AND c.charge_amount <> 0
GROUP BY CAST(c.charge_date_time AS DATE)
ORDER BY d
""", [end, end, start, end])

        # Next batch-close date for this window's late-billed work (None when
        # everything closed in-window). This is the date the user should extend
        # their End Date to in order to audit the window's billing.
        nc_rows = _q(conn, """
SELECT MIN(CAST(inv.closed_date AS DATE)) AS next_close
FROM Korber.t_bmm_charge c
JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
WHERE c.charge_date_time >= ? AND c.charge_date_time < DATEADD(day, 1, CAST(? AS DATE))
  AND c.charge_amount <> 0
  AND inv.closed_date >= DATEADD(day, 1, CAST(? AS DATE))
""", [start, end, end])

        def _as_date(x):
            # _fix() may stringify DATE columns; normalize to datetime.date.
            if x is None:
                return None
            if isinstance(x, datetime):
                return x.date()
            if isinstance(x, date):
                return x
            s = str(x)[:10]
            return datetime.strptime(s, "%Y-%m-%d").date()

        by_day_raw = [
            (_as_date(r.get("d")), int(r.get("total", 0) or 0), int(r.get("billed", 0) or 0))
            for r in rows if r.get("d")
        ]
        result = _billing_frontier_analysis(by_day_raw, _as_date(end),
                                            start_d=_as_date(start),
                                            coverage_min=COVERAGE_MIN,
                                            tiny_day_min=TINY_DAY_MIN)
        result["billed_after_end"] = sum(int(r.get("billed_late", 0) or 0) for r in rows)
        _nc = _as_date(nc_rows[0].get("next_close")) if nc_rows and nc_rows[0].get("next_close") else None
        result["next_close_date"] = (_nc.isoformat() if _nc else None)
        return result
    finally:
        conn.close()


def _billing_frontier_analysis(by_day_raw, end_d, start_d=None,
                               coverage_min=0.95, tiny_day_min=20,
                               complete_max_gap_days=1):
    """Pure frontier/batch-completeness analysis over per-day (date, total, billed)
    tuples. Factored out of pull_billing_horizon (v1.16.7) so the logic is unit-
    testable without EDW access — the incomplete-batch path could never be tested
    live because production data is always fully billed by the time we look.

    v1.16.7 HARDENING (two guards added to the v1.16.6 coverage detector):

    1. MATERIAL-DAYS-ONLY frontier advancement. v1.16.6 let ANY day that cleared
       coverage advance the frontier, including tiny ones. Failure mode: in a
       genuinely mid-batch window (e.g. 6/29-7/6 audited on 7/6), the pending
       days 7/2-7/6 carry only 2/3/18 stray charges — and strays from early-
       closing invoices are often BILLED. A tiny fully-billed stray day walked
       the frontier to the audit end, batch_complete flipped True, the JS snapped
       the cutoff to the audit end, and the entire pending window was audited as
       billed — re-creating the 3,713-false-positive storm the suppression exists
       to prevent. Now only days with total >= tiny_day_min can advance the
       frontier; tiny days neither advance nor block.

    2. FRONTIER-GAP guard on batch_complete. Pending days often have NO charge
       rows at all (charges are created at billing time), so a pending batch can
       be INVISIBLE to any per-day coverage test — there are no unbilled rows to
       see. trailing_trickle_days alone therefore cannot prove completeness. If
       the material frontier sits more than complete_max_gap_days before the
       audit end, the tail of the window has no material billed volume and we
       cannot distinguish 'quiet weekend' from 'batch not posted' → declare
       incomplete. Cost asymmetry makes this safe: wrongly-incomplete suppresses
       completeness checks on near-empty days (drops ~nothing); wrongly-complete
       fires hundreds of false 'missing charge' items.
       Verified reference window 07-06..07-13: frontier 07-12, gap 1 → complete.
       Regression window 6/29-7/6 audited mid-batch: frontier 07-01, gap 5 →
       incomplete, regardless of whether the stray rows happen to be billed.
    """
    total_rows = sum(t for _, t, _ in by_day_raw)
    max_cd = max((d for d, _, _ in by_day_raw), default=None)

    material_frontier = None
    frontier_method = "coverage_95pct_material"
    trailing_trickle_days = 0

    for d, total, billed in by_day_raw:
        if total < tiny_day_min:
            continue  # tiny days neither advance nor block the frontier
        if (billed / total) >= coverage_min:
            material_frontier = d

    if material_frontier is not None:
        # Material days with low coverage after the frontier = a visible unbilled
        # tail (charges exist on open invoices). Tiny stray/correction days are
        # ignored — they'd never have tripped the old 100-row floor either.
        trailing_trickle_days = sum(
            1 for d, total, billed in by_day_raw
            if d > material_frontier
            and total >= tiny_day_min
            and ((billed / total) if total > 0 else 0.0) < coverage_min
        )

    # v1.16.8: WINDOW-TRUNCATION detection. When material work-days exist but
    # NONE clears in-window coverage, the window's billing posted entirely
    # AFTER the end date (the caller's coverage counts only closes <= end).
    # Auditing such a window against its (near-empty) invoice pull would flood
    # false completeness items, so the horizon collapses to the day before
    # start — the JS cutoff then suppresses every completeness check in the
    # window — and window_truncated tells the UI to prompt the user to extend
    # the end date to next_close_date.
    has_material_day = any(t >= tiny_day_min for _, t, _ in by_day_raw)
    window_truncated = bool(has_material_day and material_frontier is None)

    # Horizon = billed frontier, capped at audit end. Truncated window → day
    # before start (suppress all). Fall back to max charge date only when the
    # window has no material day at all (holiday/empty week — old behavior).
    if window_truncated and start_d:
        horizon_d = start_d - timedelta(days=1)
    else:
        horizon_d = material_frontier or max_cd
    if horizon_d and end_d and horizon_d > end_d:
        horizon_d = end_d

    # Gap between the material frontier and the audit end (days). None when
    # there is no frontier.
    frontier_gap_days = ((end_d - material_frontier).days
                         if (material_frontier is not None and end_d) else None)

    # batch_complete: requires BOTH
    #   (a) no visible material unbilled tail (trailing_trickle_days == 0), and
    #   (b) the material frontier reaches to within complete_max_gap_days of the
    #       audit end (guard 2 above — an invisible pending batch shows up as a
    #       LARGE gap, not as unbilled rows).
    batch_complete = bool(
        material_frontier is not None
        and trailing_trickle_days == 0
        and frontier_gap_days is not None
        and frontier_gap_days <= complete_max_gap_days
    )

    # by_day emits (date, total) pairs — unchanged contract for downstream consumers.
    by_day = [(d.isoformat(), total) for d, total, _ in by_day_raw]

    return {"horizon": (horizon_d.isoformat() if horizon_d else None),
            "max_charge_date": (max_cd.isoformat() if max_cd else None),
            "material_frontier": (material_frontier.isoformat() if material_frontier else None),
            "charge_rows": total_rows, "batch_complete": batch_complete,
            "frontier_method": frontier_method,
            "trailing_trickle_days": trailing_trickle_days,
            "frontier_gap_days": frontier_gap_days,
            "window_truncated": window_truncated,
            "by_day": by_day}


def pull_rates(use_cache=True):
    """Return the cached rates snapshot. Refreshed once per day by the scheduler;
    initial load happens at app startup or on first call if startup hasn't run yet.

    use_cache=False is honored for legacy callers but is rarely needed —
    rates_cache_force_refresh() is the preferred manual-refresh path.
    """
    if use_cache:
        cached = _rates_cache_get()
        if cached is not None:
            return cached
    # No cached snapshot yet (cold startup, or use_cache=False): fetch live.
    rows = _rates_fetch_live()
    _rates_cache_set(rows, source="live")
    _rates_disk_save(rows)
    return rows


def pull_lost_revenue(start, end, wh_filter=None):
    """
    Pull Lost Revenue: shipped/complete orders with vessel info, charge totals,
    Billing Link, and Our Supplies counts.

    Billing Link and Our Supplies are derived from tran_type=344 events in
    t_bmm_event_log, joined to t_item_master on (item_number, wh_id) with
    client_code='0200' (Quantix-owned items only):
      - Our Supplies: inv_cat = 'SUPPLY'
      - Billing Link: inv_cat != 'SUPPLY' (BILLING / BILL-PICK / BILL-SHIP)
    Customer-coded items (e.g. 544D) are excluded from both counts.

    Validated 17/17 against SSRS Lost Revenue on May 11-18 billing week.
    """
    conn = get_connection()
    try:
        # Step 1: orders (date-filtered)
        wh_clause = f"AND o.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        order_params = [start, end] + (list(wh_filter) if wh_filter else [])
        orders = _q(conn, f"""
SELECT o.wh_id AS [WH ID], o.display_order_number AS [Order Number],
       cl.name AS [Name], o.client_code AS [Client Code],
       o.actual_ship_date AS [Ship Date], o.bol_number AS [BOL Number],
       o.carrier AS [Carrier Name], o.order_id AS _oid
FROM Korber.t_order o
LEFT JOIN Korber.t_client cl
    ON o.client_code = cl.client_code AND o.wh_id = cl.wh_id
WHERE o.actual_ship_date >= ? AND o.actual_ship_date < ?
  AND o.status IN ('SHIPPED','COMPLETE')
{wh_clause}
""", order_params)
        if not orders:
            return orders

        oids  = list({int(r["_oid"]) for r in orders if r.get("_oid")})
        onums = list({r["Order Number"] for r in orders if r.get("Order Number")})
        BATCH = 500

        # Step 2: vessel info (batched by order_id)
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

        # Step 4: Billing Link + Our Supplies from tran_type=344 event log
        # Join to t_item_master on (item_number, wh_id), filter client_code='0200'.
        # Our Supplies = Quantix-owned supply items (inv_cat='SUPPLY').
        # Billing Link = Quantix billing items (inv_cat != 'SUPPLY').
        # Customer-coded items excluded from both (they are not Quantix supplies or billing links).
        bl_os = {}  # order_number -> {"bl": int, "os": int}
        for i in range(0, len(onums), BATCH):
            chunk = onums[i:i+BATCH]
            ph = ",".join("?" * len(chunk))
            sql = f"""
SELECT el.order_number,
    COUNT(CASE WHEN im.inv_cat = 'SUPPLY' AND im.client_code = '0200' THEN 1 END) AS our_supplies,
    COUNT(CASE WHEN im.client_code = '0200' AND ISNULL(im.inv_cat,'BILLING') <> 'SUPPLY' THEN 1 END) AS billing_link
FROM Korber.t_bmm_event_log el
LEFT JOIN Korber.t_item_master im
    ON im.item_number = el.item_number AND im.wh_id = el.wh_id
WHERE el.order_number IN ({ph}) AND el.tran_type = '344'
GROUP BY el.order_number
"""
            for r in _q(conn, sql, chunk):
                bl_os[r["order_number"]] = {"bl": r["billing_link"], "os": r["our_supplies"]}

        # Step 5: assemble
        rows = []
        for r in orders:
            o = r["Order Number"]
            oid = r.get("_oid")
            sv, dv = vmap.get(oid, ("", ""))
            counts = bl_os.get(o, {"bl": 0, "os": 0})
            rows.append({
                "WH ID": r["WH ID"], "Order Number": o, "Name": r["Name"],
                "Client Code": r["Client Code"],
                "Amount Billed": ab.get(o, 0),
                "Ship Date": r["Ship Date"], "BOL Number": r["BOL Number"],
                "Order Type": "", "Carrier Name": r["Carrier Name"],
                "Comment": "",
                "Source Vessel": sv, "Dest Vessel": dv,
                "Our Supplies": counts["os"], "Billing Link": counts["bl"],
                "Charge": "", "Corrected Amount": "", "Difference": "", "Reason": "",
            })
        return rows
    finally:
        conn.close()


def pull_railcar(start, end, wh_filter=None):
    """Railcar Flow report — every RAILCAR/ELIMINATOR either still on site or
    departed during the audit window. Includes arrive_date AND depart_date so the
    engine() can compute dwell days for the Railcar Storage category instead of
    showing 'N/A — upload Railcar Flow Report'.

    Mirrors AAD.dbo.sp_RailCarDwell (Gail Westphal, 2015-12-04) which reads
    t_hu_history. Skipped: the @Client filter (audit always wants all clients),
    the Weight subquery (audit doesn't read weight), and the Location subquery
    (audit doesn't read location).

    Filter logic from the SP:
      container_type IN ('RAILCAR','ELIMINATOR')
      AND (depart_date IS NULL OR depart_date BETWEEN start AND end)

    Dwell:
      depart_date present  -> DATEDIFF(arrive, depart) + 1
      depart_date NULL     -> DATEDIFF(arrive, end_date) + 1  (cars still on site)

    Audit engine reads bracket-notation keys:
      r['WH ID']           our [WH ID]
      r['Client Code']     our [Client Code]
      r['Client Name']     our [Client Name]
      r['Railcar']         our [Railcar]
      r['Arrived Date']    our [Arrived Date]
      r['Released Date']   our [Released Date] (was missing in the old asn pull)

    Comparison to the OLD pull (t_asn_master + t_asn_detail):
      OLD: only NEW arrivals in the window; no depart_date -> dwell always N/A
      NEW: all railcars relevant to the window (arrived earlier and still here,
           or departed in the window); depart_date populated when applicable.
      Result: audit sees more cars (correctly — long-dwelling unbilled storage is
      a real audit target per Sarah's SOP) and can compute max dwell per
      (warehouse, customer) group.
    """
    conn = get_connection()
    try:
        wh_clause = f"AND h.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        # v1.16.7: `end` here is the USER'S INCLUSIVE end day (app.py passes
        # end_user, not the +1-advanced bound used by the end-exclusive pulls).
        # This function makes the end day inclusive ITSELF via DATEADD(day, 1, ...)
        # on the datetime bounds, because:
        #   - arrive_date/depart_date are DATETIMEs: the old `arrive_date < end`
        #     and `depart_date BETWEEN start AND end` cut the end day off at
        #     midnight — arrivals/departures ON the end day were silently dropped.
        #   - Dwell-as-of for still-on-site cars must stay the USER end day; an
        #     advanced date would inflate every open car's dwell by +1 day.
        # Params: dwell-as-of-end (user end), arrive < end+1, depart >= start,
        # depart < end+1, then optional warehouse list.
        params = [end, end, start, end] + (list(wh_filter) if wh_filter else [])
        return _q(conn, f"""
SELECT
    h.wh_id                AS [WH ID],
    h.hu_id                AS [Railcar],
    h.client_code          AS [Client Code],
    c.name                 AS [Client Name],
    h.arrive_date          AS [Arrived Date],
    h.depart_date          AS [Released Date],
    CASE WHEN h.depart_date IS NOT NULL
         THEN DATEDIFF(DAY, h.arrive_date, h.depart_date) + 1
         ELSE DATEDIFF(DAY, h.arrive_date, CAST(? AS DATE)) + 1
    END                    AS [Dwell],
    CASE WHEN h.depart_date IS NULL THEN 'N' ELSE 'Y' END AS [Released Y/N],
    h.container_type       AS [Container Type]
FROM Korber.t_hu_history h
LEFT JOIN Korber.t_client c
    ON c.wh_id = h.wh_id AND c.client_code = h.client_code
WHERE h.container_type IN ('RAILCAR','ELIMINATOR')
  AND h.arrive_date IS NOT NULL
  AND h.arrive_date < DATEADD(day, 1, CAST(? AS DATE))
  AND (h.depart_date IS NULL
       OR (h.depart_date >= ? AND h.depart_date < DATEADD(day, 1, CAST(? AS DATE))))
  {wh_clause}
""", params)
    finally:
        conn.close()


def pull_packaging(start, end, wh_filter=None):
    conn = get_connection()
    try:
        wh_clause = f"AND o.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        params = [start, end] + (list(wh_filter) if wh_filter else [])
        return _q(conn, f"""
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
       cl.name AS [Client Name],
       inv.invoice_number AS [Invoice Number], inv.closed_date AS [Closed Date],
       cit.contract_invoice_type_code AS [Contract Invoice Type Code],
       cb.description AS [Description],
       CASE WHEN CHARINDEX('-', o.display_order_number) > 0
            THEN SUBSTRING(o.display_order_number, CHARINDEX('-', o.display_order_number)+1, LEN(o.display_order_number))
            ELSE o.display_order_number END AS [TRIM Order],
       NULL AS [Count Trans]
FROM Korber.t_order o
JOIN Korber.t_order_detail od ON od.order_id = o.order_id
LEFT JOIN Korber.t_client cl ON o.client_code = cl.client_code AND o.wh_id = cl.wh_id
LEFT JOIN Korber.t_bmm_charge c ON c.order_num_value = o.display_order_number
LEFT JOIN Korber.t_bmm_invoice inv ON c.invoice_id = inv.invoice_id
LEFT JOIN Korber.t_bmm_cont_inv_type_chargeback cb ON c.chargeback_id = cb.chargeback_id
LEFT JOIN Korber.t_bmm_contract_invoice_type cit ON cb.contract_invoice_type_id = cit.contract_invoice_type_id
WHERE o.display_order_number LIKE 'PW%%' AND o.actual_ship_date >= ? AND o.actual_ship_date < ?
{wh_clause}
""", params)
    finally:
        conn.close()


def pull_bulk_orders(start, end, wh_filter=None):
    """Bulk shipping orders (type_id=668, status=SHIPPED) in the window.

    Returns one row per order with one invoice match (the first non-null invoice
    found via the order_num_value join). Audit logic (engine() in billing_audit.html)
    reads d.order_number, d.invoice_number, d.closed_date, d.customer,
    d.customer_code, d.wh_id, d.source_vessel, d.dest_vessel — so we emit
    snake_case lower-case keys directly. No order_type column (the WHERE clause
    already restricts to bulk).

    Customer resolution: t_order.customer_id is empirically always NULL for
    bulk orders, so we resolve via t_client on (client_code, wh_id). This gives
    a usable display name; the global t_bmm_customer.customer_code is not
    populated on these rows and we don't need it (no-invoice orders have no
    rate to match).

    De-duplication: t_order_detail produces one row per line item and t_bmm_charge
    produces one row per charge. We aggregate the invoice subquery to one row
    per order_num_value, and we collapse details to a single row by taking
    MIN(source_vessel) / MIN(dest_vessel) per order so the audit gets one row per
    bulk order instead of one row per (order, line, charge) cartesian.
    """
    conn = get_connection()
    try:
        wh_clause = f"AND ord.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        params = [start, end] + (list(wh_filter) if wh_filter else [])
        # v1.17.0 PERF: InvoiceMatch and DetailRollup previously aggregated the
        # ENTIRE t_bmm_charge and t_order_detail tables before the window filter
        # was applied. Scoping both CTEs to the window's orders is semantically
        # identical (LEFT JOINs only ever hit window orders) and removes two
        # full-table GROUP BYs from every audit pull.
        return _q(conn, f"""
WITH WindowOrders AS (
    SELECT ord.order_id, ord.display_order_number
    FROM Korber.t_order ord
    WHERE ord.actual_ship_date >= ? AND ord.actual_ship_date < ?
      AND ord.type_id = 668
      AND ord.status = 'SHIPPED'
      AND ord.created_by <> 'AUTO'
      {wh_clause}
),
InvoiceMatch AS (
    SELECT
        c2.order_num_value AS order_num,
        MIN(inv2.invoice_number) AS invoice_number,
        MIN(inv2.closed_date)    AS closed_date
    FROM Korber.t_bmm_charge c2
    JOIN Korber.t_bmm_invoice inv2 ON c2.invoice_id = inv2.invoice_id
    WHERE c2.order_num_value IN (SELECT display_order_number FROM WindowOrders)
    GROUP BY c2.order_num_value
),
DetailRollup AS (
    SELECT
        det.order_id,
        MIN(det.source_vessel) AS source_vessel,
        MIN(det.dest_vessel)   AS dest_vessel
    FROM Korber.t_order_detail det
    WHERE det.order_id IN (SELECT order_id FROM WindowOrders)
    GROUP BY det.order_id
)
SELECT
    ord.wh_id              AS wh_id,
    ord.display_order_number AS order_number,
    ord.client_code        AS client_code,
    ord.client_code        AS customer_code,
    COALESCE(cl.name, ord.client_code) AS customer,
    dr.source_vessel       AS source_vessel,
    dr.dest_vessel         AS dest_vessel,
    ord.actual_ship_date   AS ship_date,
    ord.bol_number         AS bol_number,
    ord.carrier            AS carrier,
    ord.cust_po_number     AS cust_po_number,
    ord.store_order_number AS store_order_number,
    im.invoice_number      AS invoice_number,
    im.closed_date         AS closed_date
FROM Korber.t_order ord
JOIN WindowOrders w              ON w.order_id = ord.order_id
LEFT JOIN DetailRollup dr        ON dr.order_id = ord.order_id
LEFT JOIN InvoiceMatch im        ON im.order_num = ord.display_order_number
LEFT JOIN Korber.t_client cl     ON cl.client_code = ord.client_code AND cl.wh_id = ord.wh_id
""", params)
    finally:
        conn.close()


def resolve_recurring_billing_date(as_of, conn=None):
    """Return the most recent Group-3 (recurring storage) invoice CLOSE date on or
    before `as_of`, or None if none found.

    WHY (v1.16.1, 2026-07-07): recurring storage is a MONTHLY charge. Group-3
    invoices close on a monthly cadence (observed: 6/1 -> 1200, 7/1 -> 1219, with
    essentially nothing in between). pull_recurring_storage() compares an inventory
    snapshot against invoices whose closed_date EQUALS billing_date. When the
    caller passes the audit-window end (e.g. 6/29) -- which the v1.15 billingDate
    auto-track does -- no Group-3 invoice closed that day, so BillingBase matches
    nothing, invoice_qty=0 for every row, and the variance is snapshot-vs-zero
    (garbage: it flagged 10-390 noise items for 6/22-6/29). Snapping billing_date
    to the actual month-close date (7/1 for June) makes the comparison real
    (102 rows, all with invoice_qty>0, 15 genuine variances).
    """
    # A real monthly storage batch is hundreds of invoices; stray correction/
    # adjustment closes (observed: 6/11 = 3 invoices) must NOT be selected or the
    # snapshot compares against a near-empty billed set (garbage variance). Require
    # a MATERIAL close date: >= RECURRING_MATERIAL_MIN invoices AND >= 20% of the
    # largest Group-3 batch in the trailing lookback.
    RECURRING_MATERIAL_MIN = 50
    RECURRING_MATERIAL_FRAC = 0.20
    own = conn is None
    if own:
        conn = get_connection()
    try:
        rows = _q(conn, """
SELECT CAST(inv.closed_date AS DATE) AS d, COUNT(*) AS n
FROM Korber.t_bmm_invoice inv
JOIN Korber.t_bmm_cont_inv_type_chargeback citch ON inv.contract_invoice_type_id = citch.contract_invoice_type_id
JOIN Korber.t_bmm_contract_invoice_type cit ON cit.contract_invoice_type_id = citch.contract_invoice_type_id
WHERE cit.contract_invoice_type_code = 'Group 3'
  AND CAST(inv.closed_date AS DATE) <= ?
  AND inv.closed_date >= DATEADD(day, -400, CAST(? AS DATE))
GROUP BY CAST(inv.closed_date AS DATE)
ORDER BY d
""", [as_of, as_of])

        def _as_date(x):
            if x is None:
                return None
            if isinstance(x, datetime):
                return x.date()
            if isinstance(x, date):
                return x
            return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()

        by_day = [(_as_date(r.get("d")), int(r.get("n", 0) or 0)) for r in rows if r.get("d")]
        if not by_day:
            return None
        max_batch = max(n for _, n in by_day)
        thresh = max(RECURRING_MATERIAL_MIN, max_batch * RECURRING_MATERIAL_FRAC)
        material = [d for d, n in by_day if n >= thresh]
        return max(material) if material else None
    finally:
        if own:
            conn.close()


def pull_recurring_storage(billing_date, warehouses=None, clients=None, auto=True):
    """Recurring storage variance audit.

    v1.16.1: when auto=True (default), billing_date is snapped to the most recent
    Group-3 invoice CLOSE date on or before the requested date. This aligns the
    snapshot-vs-billed comparison with the day storage was actually invoiced.
    Pass auto=False to force the exact billing_date (legacy behavior). The
    resolved date is returned to callers via the module-level
    LAST_RECURRING_BILLING_DATE for banner display.
    """
    global LAST_RECURRING_BILLING_DATE, LAST_RECURRING_BILLING_AUTORESOLVED
    if billing_date is None:
        return []
    conn = get_connection()
    try:
        requested = billing_date
        if auto:
            resolved = resolve_recurring_billing_date(billing_date, conn=conn)
            if resolved is not None:
                billing_date = resolved
        LAST_RECURRING_BILLING_DATE = billing_date
        LAST_RECURRING_BILLING_AUTORESOLVED = (billing_date != requested)
        snap_date = billing_date - timedelta(days=1)
        wh_clause = "AND i.wh_id IN ({})".format(",".join("?" * len(warehouses))) if warehouses else ""
        cl_clause = "AND i.client_code IN ({})".format(",".join("?" * len(clients))) if clients else ""

        sql = f"""
-- v1.13 FIX: Two bugs corrected in this query.
--
-- Bug A (duplicate rows): SnapAgg formerly grouped by
--   (wh_id, client_code, lot_number, item_number, display_item_number,
--    gen_attribute_value1, uom, record_create_date).
-- When the same (wh_id, client_code, lot_number, item_number) had multiple
-- snapshot rows differing in gen_attribute_value1 or display_item_number, each
-- joined to the SAME BillingAgg row, producing N identical output rows.
-- Fix: group SnapAgg by the 4-column billing key only; collapse the extra
-- dimensions with MAX() / SUM() / COUNT(DISTINCT).
--
-- Bug B (column-name mismatch): the JS engine() reads field names that match
-- the Excel-parser's normalized output.  Renamed aliases below to match:
--   customer        (was [Client])
--   customer_code   (was client_code without alias)
--   snapshot_qty    (was qty)
--   per             (was uom)
--   variance        (was [difference])
-- Also added chargeback_code and invoice_number from BillingBase.
WITH BillingBase AS (
    SELECT cust2.customer_code, cm2.wh_id, ch2.lot_number, ch2.item_number,
           CAST(ch2.prompt_text_value AS FLOAT) AS billed_qty,
           ISNULL(pus2.rate_basis,'')           AS rate_basis,
           citch2.chargeback_code,
           inv2.invoice_number
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
           SUM(billed_qty)          AS invoice_qty,
           MAX(rate_basis)          AS rate_basis,
           MAX(chargeback_code)     AS chargeback_code,
           MAX(invoice_number)      AS invoice_number
    FROM BillingBase GROUP BY customer_code, wh_id, lot_number, item_number
), SnapAgg AS (
    -- GROUP BY the 4-column billing key only; collapse extra snapshot dimensions
    -- with MAX/SUM/COUNT(DISTINCT) to produce exactly one row per billing line.
    SELECT i.wh_id, i.client_code, i.lot_number, i.item_number,
           MAX(i.display_item_number)              AS display_item_number,
           MAX(i.gen_attribute_value1)             AS gen_attribute_value1,
           MAX(i.uom)                              AS uom,
           MAX(CAST(i.record_create_date AS DATE)) AS record_create_date,
           SUM(i.quantity)                         AS qty,
           COUNT(DISTINCT i.hu_id)                 AS lp_count
    FROM Korber.t_al_host_inventory_snapshot i
    WHERE i.gen_attribute_value1 NOT IN ('RAILCAR','ELIMINATOR','CONTAINER','DRYTAINER','TRAILER')
      AND i.location_id NOT IN ('SUPPLY') AND i.wh_id <> '13-160'
      AND CAST(i.record_create_date AS DATE) = ?
      AND NOT EXISTS (SELECT 1 FROM Korber.t_bmm_invoice_ref_information ref
                      WHERE ref.customer_code=i.client_code AND ref.wh_id=i.wh_id AND ISNULL(ref.minimum,'NO')='YES')
      {wh_clause} {cl_clause}
    GROUP BY i.wh_id, i.client_code, i.lot_number, i.item_number
)
SELECT s.wh_id,
       c.name                 AS customer,
       s.client_code          AS customer_code,
       s.lot_number,
       s.item_number,
       s.display_item_number,
       t.description,
       ISNULL(b.chargeback_code, s.display_item_number) AS chargeback_code,
       b.invoice_number,
       s.gen_attribute_value1,
       s.qty                  AS snapshot_qty,
       s.uom                  AS per,
       s.lp_count,
       s.record_create_date,
       ROUND(ISNULL(b.invoice_qty,0),3) AS invoice_qty,
       ROUND(CASE WHEN ISNULL(b.rate_basis,'')='Rate per Handling Unit'
                      THEN s.lp_count
                  WHEN ISNULL(b.rate_basis,'')='Rate per Unit of Measure'
                      THEN s.qty
                  ELSE s.lp_count END
             - ISNULL(b.invoice_qty,0), 3) AS variance
FROM SnapAgg s
LEFT JOIN BillingAgg b ON b.customer_code=s.client_code AND b.wh_id=s.wh_id
    AND b.lot_number=s.lot_number AND b.item_number=s.item_number
LEFT JOIN Korber.t_client c ON c.client_code=s.client_code AND c.wh_id=s.wh_id
LEFT JOIN Korber.t_whse w ON w.wh_id=s.wh_id
LEFT JOIN Korber.t_item_master t ON t.item_number=s.item_number AND t.wh_id=s.wh_id
WHERE ABS(ROUND(CASE WHEN ISNULL(b.rate_basis,'')='Rate per Handling Unit'
                         THEN s.lp_count
                     WHEN ISNULL(b.rate_basis,'')='Rate per Unit of Measure'
                         THEN s.qty
                     ELSE s.lp_count END
                - ISNULL(b.invoice_qty,0), 0)) > 1
ORDER BY s.wh_id, s.client_code, s.lot_number
"""
        params = [billing_date, snap_date] + (list(warehouses) if warehouses else []) + (list(clients) if clients else [])
        return _q(conn, sql, params)
    finally:
        conn.close()


def pull_boxing_materials(start, end, wh_filter=None):
    """Charge-level pull for the Boxing Material Audit.

    Mirrors AAD.dbo.sp_sql_HJ_BoxingMaterials (Dale Story, 2021-11-04):
      - Source: v_bmm_summary_invoice JOIN t_order JOIN t_order_detail
      - Filter: closed_date > @CloseDate AND description NOT IN (Hourly Labor Rate,
        Labels, Switch Fee, Handling Out) AND Order_Num LIKE 'PW%'
        AND dest_vessel IN ('BOX','BAG','SUPERSACK')

    Differences from the stored proc:
      - Window is bounded on both sides via [start, end), not just > @CloseDate
      - v_bmm_summary_invoice doesn't exist in EDW Korber schema, so we inline
        the underlying invoice-charge-customer-contract join
      - De-cartesian: original SP joins t_order_detail directly, which multiplies
        rows by line items per order. We split into two CTEs and aggregate
        charges with GROUP BY (order_num, description) so the engine() audit
        sees one row per (order, charge-description) instead of (order, line,
        charge) products. Validated 2026-06-01..06-08: raw was 1,209 rows,
        de-cartesian gives 919 rows over the same 341 distinct PW orders.
      - Qty/Description_2 computations skipped (audit engine doesn't read them);
        we pass through raw prompt_text_value as qty and reason_text_value as desc2

    Audit engine (billing_audit.html `bxm.forEach`) reads:
      row.order_num, row.description, row.customer_code, row.customer_name,
      row.wh_id, row.location, row.invoice_number
    All emitted as snake_case lower-case keys.
    """
    conn = get_connection()
    try:
        wh_clause = f"AND cm.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        bpo_wh_clause = f"AND ord.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        # The wh filter applies both to the PW-orders CTE (via t_order.wh_id) and
        # to the charge stream (via t_bmm_contract_master.wh_id). Same param list,
        # passed twice.
        # v1.17.0 FIX — "Boxing material audit no longer populating". SQL Server
        # binds placeholders POSITIONALLY, and the placeholders in this statement
        # appear in the order: BoxingPwOrders wh filter, ChargeAgg start, end,
        # ChargeAgg wh filter. The previous params list was
        #   [start, end] + wh + wh
        # so whenever the auditors selected warehouse checkboxes, the DATES were
        # bound into "wh_id IN (...)" and WAREHOUSE IDs into the closed_date
        # bounds — the pull either errored or matched nothing, and the Boxing
        # Material Audit silently disappeared. (Unfiltered pulls had no wh
        # placeholders, which is why the bug escaped validation.) Params below
        # are listed in true placeholder order.
        #
        # v1.17.0 PERF: the BoxingPwOrders CTE also scanned ALL PW orders ever
        # (t_order x t_order_detail, unbounded) just to classify dest_vessel.
        # Orders invoiced in the audited window were created at most weeks ago;
        # a 180-day floor on order_date keeps every plausible late-billed order
        # while cutting years of history from the scan.
        wh_params = list(wh_filter) if wh_filter else []
        params = [start] + wh_params + [start, end] + wh_params
        return _q(conn, f"""
WITH BoxingPwOrders AS (
    SELECT DISTINCT ord.display_order_number AS order_num, ord.wh_id
    FROM Korber.t_order ord
    JOIN Korber.t_order_detail det ON det.order_id = ord.order_id
    WHERE ord.display_order_number LIKE 'PW%'
      AND ord.order_date >= DATEADD(day, -180, CAST(? AS DATE))
      AND det.dest_vessel IN ('BOX', 'BAG', 'SUPERSACK')
      {bpo_wh_clause}
),
ChargeAgg AS (
    SELECT
        ch.order_num_value                 AS order_num,
        citch.description                  AS description,
        MAX(inv.invoice_number)            AS invoice_number,
        MAX(inv.closed_date)               AS closed_date,
        MAX(cust.customer_code)            AS customer_code,
        MAX(cust.customer_name)            AS customer_name,
        MAX(cm.wh_id)                      AS wh_id,
        SUM(CAST(ch.charge_amount AS FLOAT)) AS charge_amount,
        MAX(ch.reason_text_value)          AS desc2,
        MAX(CAST(ch.prompt_text_value AS NVARCHAR(50))) AS qty
    FROM Korber.t_bmm_invoice inv
    JOIN Korber.t_bmm_cont_inv_type_chargeback citch
        ON inv.contract_invoice_type_id = citch.contract_invoice_type_id
    JOIN Korber.t_bmm_contract_invoice_type cit
        ON cit.contract_invoice_type_id = citch.contract_invoice_type_id
    JOIN Korber.t_bmm_contract_master cm
        ON cm.contract_id = cit.contract_id
    JOIN Korber.t_bmm_customer cust
        ON cust.customer_id = cm.customer_id
    JOIN Korber.t_bmm_charge ch
        ON citch.chargeback_id = ch.chargeback_id AND ch.invoice_id = inv.invoice_id
    WHERE inv.closed_date >= ? AND inv.closed_date < ?
      AND ch.order_num_value LIKE 'PW%'
      AND ABS(ch.charge_amount) > 0
      AND citch.description NOT IN ('Hourly Labor Rate', 'Labels', 'Switch Fee', 'Handling Out')
      {wh_clause}
    GROUP BY ch.order_num_value, citch.description
)
SELECT
    ca.customer_code,
    ca.customer_name,
    ca.invoice_number,
    ca.closed_date,
    ca.description,
    ca.order_num,
    ca.qty,
    ca.desc2,
    ca.charge_amount,
    ISNULL(whse.invoice_name, N'All') AS location,
    ca.wh_id
FROM ChargeAgg ca
JOIN BoxingPwOrders bpo ON bpo.order_num = ca.order_num
LEFT JOIN Korber.t_whse whse ON whse.wh_id = ca.wh_id
""", params)
    finally:
        conn.close()


_NC_TRAN_TYPE_DESC = {
    "161": "Receive",
    "521": "Transfer",
    "111": "Pick",
    "344": "Supply Issue",
    "151": "Move",
}


def pull_no_charges(start, end, wh_filter=None):
    """Billable activity with no charges — the 'No Charges' SSRS report.

    Powers two audit categories in engine():
      - "No Charges":     orders with event-log activity but no invoice posted
      - "Railcar Switch (Weekend Miss)": ASN railcar arrivals captured before
        Monday's invoice run, picked up via order_number LIKE 'ASN%' + vessel=RAILCAR

    SQL mirrors dce_audit/edw_pull.py:pull_no_charges from the historical Excel-
    export pipeline. Event-log transactions in (Receive, Transfer, Pick, Supply
    Issue, Move) where the order has no matching t_bmm_charge row. Excludes
    TRAILER/CONTAINER vessels and TO%-prefixed inter-warehouse transfers.

    Audit engine reads bracket-notation Excel-style keys (r['Order Number'],
    r['Date'], r['Vessel'], r['Name'], r['Description'], r['WH ID']) so we emit
    aliases in that exact shape.
    """
    conn = get_connection()
    try:
        wh_clause = f"AND bel.wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        params = [start, end] + (list(wh_filter) if wh_filter else [])
        # v1.17.0 FIX — false "not invoiced" flags: also treat charges posted
        # under dash-suffixed sub-orders (event log 'PW2995516' vs charge
        # 'PW2995516-3') as invoiced.
        #
        # v1.17.5 PERF FIX — the v1.17.0 shape put equality, LTRIM/RTRIM
        # equality, and the LIKE prefix in ONE NOT EXISTS joined by OR. The OR
        # plus functions on the charge column made every predicate
        # non-sargable: SQL Server scanned t_bmm_charge for EVERY event-log
        # row. Observed live: the No Charges pull ran 10+ minutes, starving
        # the response stream until the Azure proxy killed it ("network
        # error" at ~90%). Split into two AND-ed NOT EXISTS — plain equality
        # and a bare LIKE prefix — both index-seekable; the whitespace-trim
        # variant is dropped (dash-suffix was the real false-positive
        # source).
        rows = _q(conn, f"""
SELECT
    bel.wh_id                               AS [WH ID],
    w.name                                  AS [Location],
    bel.client_id                           AS [Client Code],
    c.name                                  AS [Name],
    CAST(bel.tran_start AS DATE)            AS [Date],
    bel.tran_type                           AS [Tran Type],
    bel.generic_attribute_1                 AS [Vessel],
    bel.order_number                        AS [Order Number]
FROM Korber.t_bmm_event_log bel
LEFT JOIN Korber.t_client c
    ON c.client_code = bel.client_id AND c.wh_id = bel.wh_id
LEFT JOIN Korber.t_whse w
    ON w.wh_id = bel.wh_id
WHERE bel.tran_type IN ('161','521','111','344','151')
  AND NOT EXISTS (
      SELECT 1 FROM Korber.t_bmm_charge ch
      WHERE ch.order_num_value = bel.order_number
  )
  AND NOT EXISTS (
      SELECT 1 FROM Korber.t_bmm_charge ch2
      WHERE ch2.order_num_value LIKE bel.order_number + '-%'
  )
  AND ISNULL(bel.generic_attribute_1, '') NOT IN ('TRAILER','CONTAINER')
  AND (bel.order_number IS NULL OR bel.order_number NOT LIKE 'TO%')
  AND CAST(bel.tran_start AS DATE) >= ?
  AND CAST(bel.tran_start AS DATE) <  ?
  {wh_clause}
GROUP BY
    bel.wh_id, w.name, bel.client_id, c.name,
    CAST(bel.tran_start AS DATE),
    bel.tran_type, bel.generic_attribute_1, bel.order_number
""", params)

        # Map tran_type code -> human-readable label expected by audit engine
        for r in rows:
            tt = r.pop("Tran Type", None)
            r["Description"] = _NC_TRAN_TYPE_DESC.get(str(tt) if tt is not None else "", str(tt) if tt is not None else "")
        return rows
    finally:
        conn.close()


def pull_wh_names(wh_filter=None):
    """Pull warehouse id → name mapping from t_whse."""
    conn = get_connection()
    try:
        wh_clause = f"WHERE wh_id IN ({','.join('?'*len(wh_filter))})" if wh_filter else ""
        params = list(wh_filter) if wh_filter else []
        return _q(conn, f"SELECT wh_id, name FROM Korber.t_whse {wh_clause}", params)
    finally:
        conn.close()
