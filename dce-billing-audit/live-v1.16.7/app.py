"""
DC&E Billing Audit — Web Application v3
Parallel report pulls, streaming progress, cancellable from the UI.
"""

import os
import json
import math
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta

from flask import Flask, request, render_template, jsonify, Response, stream_with_context, make_response
from dotenv import load_dotenv
load_dotenv()

from sql_client import (
    pull_invoice, pull_rates, pull_lost_revenue,
    pull_railcar, pull_packaging, pull_bulk_orders, pull_recurring_storage,
    pull_wh_names, pull_boxing_materials, pull_no_charges, pull_billing_horizon, _clean,
    rates_cache_status, rates_cache_force_refresh, rates_cache_startup,
)

# Kick the rates cache: load disk snapshot, schedule daily refresh, optionally
# pre-warm in the background. Idempotent — safe to call on every worker boot.
rates_cache_startup()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

APP_VERSION = "1.16.7"

_pull_results = {}  # in-memory store for completed results

# Per-pull cancel coordination.
# Maps pull_id -> threading.Event. The generator checks the event between
# yields and on each task completion. The frontend posts to /api/cancel/<id>
# to flip the event. We also auto-set the event on GeneratorExit so that an
# aborted browser fetch tears down running queries.
_cancel_events = {}
_cancel_lock = threading.Lock()


def _register_cancel(pull_id):
    ev = threading.Event()
    with _cancel_lock:
        _cancel_events[pull_id] = ev
        # Trim old events (keep last 20)
        if len(_cancel_events) > 20:
            for k in list(_cancel_events.keys())[:-20]:
                _cancel_events.pop(k, None)
    return ev


def _drop_cancel(pull_id):
    with _cancel_lock:
        _cancel_events.pop(pull_id, None)


def _get_cancel(pull_id):
    with _cancel_lock:
        return _cancel_events.get(pull_id)


# Tunables for parallel execution. Default 4 concurrent EDW connections is
# conservative for a B1 App Service Plan + Synapse DWU baseline. Override via
# env if Bryan tunes Synapse up or hits throttling.
_PARALLEL_MAX_WORKERS = int(os.getenv("PARALLEL_MAX_WORKERS", "4"))


# ── Single in-flight pull gate ──────────────────────────────────────────────────────────
# Why: a streaming /api/pull pins a request thread for the full audit duration
# (~3 minutes) plus an internal ThreadPoolExecutor with PARALLEL_MAX_WORKERS
# threads holding EDW connections. Two concurrent audit requests can therefore
# saturate the gthread pool and the SQL Server connection pool simultaneously,
# which wedged the live app on 2026-06-12 ~20:39 UTC. Solution: refuse a second
# concurrent pull on the same worker process with HTTP 429 so the caller knows
# to wait and retry instead of stacking dead connections.
#
# Per-process, not per-cluster: with --workers=2 we tolerate 2 concurrent pulls
# globally. Anything more should queue at the client.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_PULL_ID = None  # exactly one pull_id at a time, or None


def _try_claim_pull_slot(pull_id):
    """Atomically claim the single in-flight pull slot. Returns True on success."""
    global _INFLIGHT_PULL_ID
    with _INFLIGHT_LOCK:
        if _INFLIGHT_PULL_ID is not None:
            return False
        _INFLIGHT_PULL_ID = pull_id
        return True


def _release_pull_slot(pull_id):
    """Release the in-flight pull slot, but only if we own it (avoid races)."""
    global _INFLIGHT_PULL_ID
    with _INFLIGHT_LOCK:
        if _INFLIGHT_PULL_ID == pull_id:
            _INFLIGHT_PULL_ID = None


def _current_inflight():
    with _INFLIGHT_LOCK:
        return _INFLIGHT_PULL_ID


@app.route("/")
def index():
    # Inject APP_VERSION into the redirect URL as ?v=... so browser caches of
    # /static/billing_audit.html get invalidated on every deploy. Without this,
    # users have been seeing stale HTML (and stale JS) for hours because Azure
    # Easy Auth strips Cache-Control headers between Flask and the browser, so
    # browsers default to aggressive disk caching.
    resp = make_response(render_template("index.html", version=APP_VERSION))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.after_request
def _no_cache_dashboard(resp):
    # The 6.6MB dashboard is served by Flask's built-in /static/ handler, which
    # does NOT run through the index() route above and therefore gets default
    # static caching. Easy Auth also strips per-response Cache-Control, so the
    # ?v= querystring alone is not enough to defeat browser/CDN disk caching --
    # users kept seeing stale HTML after a deploy. Force no-store on the
    # dashboard file (and the redirect stub) on every response.
    p = (request.path or "")
    if p.endswith("billing_audit.html") or p == "/":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.route("/api/pull", methods=["POST"])
def api_pull():
    """
    Pull all report data from EDW in parallel with streaming progress.
    8 reports total — up to PARALLEL_MAX_WORKERS run concurrently (default 4).
    Cancellable via POST /api/cancel/<pull_id> or by aborting the fetch.
    """
    body = request.get_json(force=True)
    start_str = body.get("start")
    end_str   = body.get("end")

    if not start_str or not end_str:
        return jsonify({"error": "start and end dates are required"}), 400

    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end   = datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    # ── v1.16.7 FIX — Mechanism C (off-by-one on the end date) ──────────────
    # The UI date pickers are INCLUSIVE ("to 07-13" means through the 13th), but
    # every windowed pull's SQL upper bound is EXCLUSIVE (closed_date < ?,
    # actual_ship_date < ?, tran_start < ?). Passing the raw picker end therefore
    # silently dropped the ENTIRE final day — which for DC&E's batch billing is
    # routinely the batch-close day holding ~all of the week's charges
    # (07-06..07-13: 21 charges returned instead of ~11,751 because the 07-13
    # batch of 11,773 charges was cut off). Advance the exclusive bound one day.
    #
    # end_user (the user's inclusive end day) is kept for the pulls that must
    # NOT receive the advanced bound:
    #   - pull_billing_horizon: its SQL already advances internally
    #     (charge_date_time < DATEADD(day, 1, ?)) — advancing here would
    #     double-count a day and let the frontier scan past the window.
    #   - pull_railcar: dwell-as-of and its internal DATEADD bounds are keyed
    #     to the user's inclusive end day (see sql_client.pull_railcar v1.16.7).
    #   - data["end"] echoed to the frontend: the UI displays and reasons in
    #     inclusive user dates; leaking end+1 would shift banner text and the
    #     engine's audit-window label.
    end_user = end
    end = end + timedelta(days=1)

    # Recurring-storage anchor (v1.16.1). Blank -> today, so the backend resolver
    # snaps to the most recent MATERIAL Group-3 storage close. A user-supplied date
    # audits the month-close on/before that date. Never the shipping-audit window.
    billing_date_requested = None
    if body.get("billing_date"):
        try:
            billing_date_requested = datetime.strptime(body["billing_date"], "%Y-%m-%d").date()
        except ValueError:
            pass
    billing_date = billing_date_requested or date.today()

    warehouses = body.get("warehouses") or None
    clients    = body.get("clients") or None

    # Pre-allocate pull_id so it can be sent on the first line and the frontend
    # can call /api/cancel/<id> immediately. Register the cancel event up front.
    pull_id = str(uuid.uuid4())
    cancel_event = _register_cancel(pull_id)

    # Single in-flight gate: refuse a second concurrent pull on this worker.
    # With --workers=2, two pulls can run globally (Azure routes via ARRAffinity).
    # Anything beyond that gets 429 and the client should wait for the current
    # one to finish (or click Cancel on its tab).
    if not _try_claim_pull_slot(pull_id):
        _drop_cancel(pull_id)
        existing = _current_inflight()
        return jsonify({
            "error": "Another audit is already running on this worker.",
            "reason": "concurrent_pull_not_allowed",
            "in_flight_pull_id": existing,
            "retry_after_seconds": 30,
        }), 429

    def generate():
        data = {}
        total = 10

        wh_filter = warehouses if warehouses else None

        all_tasks = [
            ("Invoice",            "invoice",           lambda: pull_invoice(start, end, wh_filter)),
            ("Rates",              "rates",             lambda: pull_rates()),
            ("Railcar",            "railcar",           lambda: pull_railcar(start, end_user, wh_filter)),
            ("Packaging",          "packaging",         lambda: pull_packaging(start, end, wh_filter)),
            ("Bulk Orders",        "bulk_orders",       lambda: pull_bulk_orders(start, end, wh_filter)),
            ("Lost Revenue",       "lost_revenue",      lambda: pull_lost_revenue(start, end, wh_filter)),
            ("Recurring Storage",  "recurring_storage", lambda: pull_recurring_storage(billing_date, warehouses, clients)),
            ("Boxing Materials",   "boxing_materials",  lambda: pull_boxing_materials(start, end, wh_filter)),
            ("No Charges",         "no_charges",        lambda: pull_no_charges(start, end, wh_filter)),
            ("WH Names",           "wh_names",          lambda: pull_wh_names(wh_filter)),
        ]

        # ── Anti-buffering prelude ──────────────────────────────────────────
        # Two layers of buffering to defeat:
        # 1. Azure App Service front-end proxy: ~4 KB threshold (confirmed)
        # 2. Azure Easy Auth interception layer: much larger buffer, observed
        #    to swallow the entire 4 KB prelude PLUS all subsequent progress
        #    lines (Bryan saw no bytes for many seconds in browser even though
        #    server-side emission was sub-second).
        # Empirically 64 KB pushes through both layers. We send it once at the
        # top; subsequent progress lines flow normally after the initial flush.
        yield (" " * 65536) + "\n"

        # Emit pull_id first so the frontend can wire the Cancel button to it.
        yield json.dumps({"pull_id": pull_id}) + "\n"
        yield json.dumps({
            "progress": f"Starting EDW pull ({total} reports, up to {_PARALLEL_MAX_WORKERS} parallel)…",
            "step": 0, "total": total
        }) + "\n"
        yield (" " * 8192) + "\n"

        # ── Parallel execution ──────────────────────────────────────────────
        # All 8 pulls run concurrently up to _PARALLEL_MAX_WORKERS. Each pull
        # opens its own pyodbc connection; AAD token cache is thread-safe. Rates
        # returns from the in-memory snapshot at ~0 ms. The new wall-clock
        # bottleneck is the slowest single query (Lost Revenue or Packaging,
        # 20-50s) instead of the sum of all 8.
        executor = ThreadPoolExecutor(
            max_workers=_PARALLEL_MAX_WORKERS, thread_name_prefix="edw-pull"
        )
        future_meta = {}  # future -> (label, key)
        cancelled = False

        try:
            for label, key, fn in all_tasks:
                fut = executor.submit(fn)
                future_meta[fut] = (label, key)
                yield json.dumps({"progress": f"Queued {label}…", "step": 0, "total": total}) + "\n"
            yield (" " * 8192) + "\n"

            completed = 0
            t_start = time.time()
            # Bound the wait so we always emit a structured error before the
            # gunicorn --timeout=900 kills the worker.
            DEADLINE = 850
            # Heartbeat: emit a keepalive every HEARTBEAT_SEC even if no pull has
            # finished. Azure Front Door / App Service has a ~230s idle-stream
            # timeout; a slow single SQL query (cold Lost Revenue, e.g.) can
            # silence the stream for longer than that and the proxy drops the
            # connection. The heartbeat is a whitespace pad line that the
            # frontend NDJSON parser ignores via `if(!ln) continue`.
            HEARTBEAT_SEC = 25

            pending = set(future_meta.keys())
            iterator = as_completed(pending, timeout=None)
            while pending:
                if cancel_event.is_set():
                    cancelled = True
                    break
                if time.time() - t_start > DEADLINE:
                    yield json.dumps({"error": "Pull exceeded deadline; canceling remaining queries."}) + "\n"
                    cancelled = True
                    break

                # Try to claim a finished future within HEARTBEAT_SEC. If no
                # future is done in that window, emit a pad-line heartbeat and
                # loop. Reusing the same as_completed iterator across waits is
                # not safe with a per-call timeout, so build a fresh one each
                # iteration over the still-pending set.
                fut = None
                try:
                    fut = next(as_completed(pending, timeout=HEARTBEAT_SEC))
                except Exception:
                    # TimeoutError or StopIteration: no future finished in time.
                    elapsed = int(time.time() - t_start)
                    yield json.dumps({
                        "heartbeat": True,
                        "elapsed_seconds": elapsed,
                        "in_flight": [future_meta[p][0] for p in pending if not p.done()],
                    }) + "\n"
                    yield (" " * 8192) + "\n"
                    continue

                pending.discard(fut)
                label, key = future_meta[fut]
                try:
                    result = fut.result()
                    data[key] = result
                    completed += 1
                    count = len(result) if isinstance(result, list) else 0
                    yield json.dumps({
                        "progress": f"✓ {label}: {count:,} rows",
                        "step": completed, "total": total
                    }) + "\n"
                    yield (" " * 8192) + "\n"
                except Exception as e:
                    yield json.dumps({"error": f"{label} failed: {e}"}) + "\n"
                    cancelled = True
                    break

            if cancelled:
                # Cancel any not-yet-started futures. Already-running pyodbc
                # queries can't be killed from Python; they finish on their own
                # and their connections close. We just stop waiting on them.
                for f in future_meta.keys():
                    if not f.done():
                        f.cancel()
                if cancel_event.is_set():
                    yield json.dumps({"cancelled": True, "pull_id": pull_id}) + "\n"
                return
        finally:
            # Ensure the executor doesn't pin background threads past the response.
            # cancel_futures=True calls .cancel() on every not-yet-started future
            # so the pool's workers exit cleanly. Already-running SQL queries can't
            # be killed (pyodbc limitation) but the threads will exit when their
            # current statement returns and the executor's _shutdown flag is set.
            executor.shutdown(wait=False, cancel_futures=True)

        # ── Normalize recurring storage for engine() ────────────────────────
        # v1.15 FIX: the v1.13 sql_client rename (difference->variance, qty->
        # snapshot_qty, uom->per, client_code->customer_code, Client->customer)
        # was NOT reflected here, so every r.get() on an OLD name fell back to
        # its default -> variance became 0 for all rows -> the JS engine skipped
        # every row (absVar===0 return) -> ~378 Recurring Storage Variance action
        # items silently vanished from the dashboard. Read the NEW SQL names
        # first, fall back to the OLD names so this works against either schema.
        if "recurring_storage" in data:
            data["recurring_storage"] = [{
                "wh_id":           r.get("wh_id", ""),
                "customer":        r.get("customer") or r.get("Client") or r.get("Whse") or "",
                "customer_code":   r.get("customer_code") or r.get("client_code", ""),
                "chargeback_code": r.get("chargeback_code") or r.get("description", ""),
                "description":     r.get("description") if r.get("variance") is not None else r.get("display_item_number", ""),
                "per":             r.get("per") or r.get("uom", ""),
                "invoice_qty":     r.get("invoice_qty", 0),
                "snapshot_qty":    (r.get("snapshot_qty") if r.get("snapshot_qty") is not None
                                    else (r.get("qty", 0) if r.get("LP Count", 0) == 0 else r.get("LP Count", 0))),
                "variance":        (r.get("variance") if r.get("variance") is not None
                                    else r.get("difference", 0)),
                "invoice_number":  r.get("invoice_number", ""),
            } for r in data["recurring_storage"]]

        # ── Finalize ────────────────────────────────────────────────────────
        # ── Authoritative billing horizon (v1.16, 2026-07-07 fix) ─────────────
        # The engine previously inferred the horizon from max(Charge Date) over
        # closed-invoice rows, which lags mid-window and over-suppressed the back
        # half of the audit window. Supply the true material charge frontier in
        # t_bmm_charge (capped at end); the engine only raises the horizon to it.
        try:
            # end_user, NOT the advanced end: pull_billing_horizon's SQL already
            # does < DATEADD(day, 1, ?) internally (v1.16.7 — see Mechanism C fix).
            data["billing_horizon"] = pull_billing_horizon(start, end_user)
        except Exception as e:
            data["billing_horizon"] = {"horizon": None, "error": str(e)}

        # ── Recurring-storage billing date (v1.16.1) ───────────────────────
        # pull_recurring_storage() auto-snaps billing_date to the real Group-3
        # storage-invoice close date. Surface what it actually used so the UI can
        # show it (and flag when it differs from the requested date).
        import sql_client as _sc
        _rbd = _sc.LAST_RECURRING_BILLING_DATE
        data["recurring_billing_date"] = {
            "requested": (billing_date_requested.isoformat() if billing_date_requested else None),
            "resolved": (_rbd.isoformat() if _rbd else None),
            "autoresolved": bool(_sc.LAST_RECURRING_BILLING_AUTORESOLVED),
        }

        data["start"] = start.isoformat()
        data["end"]   = end_user.isoformat()  # user-facing inclusive end, not the advanced SQL bound
        data = _clean(data)

        yield json.dumps({"progress": "Building dashboard…", "step": total, "total": total}) + "\n"
        payload_json = json.dumps(data, default=str)
        _pull_results[pull_id] = payload_json
        if len(_pull_results) > 5:
            oldest = next(iter(_pull_results))
            del _pull_results[oldest]
        yield '{"done": true, "pull_id": "' + pull_id + '", "data": ' + payload_json + '}\n'

    def generate_and_cleanup():
        try:
            for chunk in generate():
                yield chunk
        except GeneratorExit:
            # Client disconnected mid-stream (browser closed tab, AbortController).
            # Flip the cancel event so running parallel pulls notice on next check.
            cancel_event.set()
            raise
        finally:
            _drop_cancel(pull_id)
            _release_pull_slot(pull_id)

    # Anti-buffering response headers. X-Accel-Buffering is honored by nginx
    # and ignored elsewhere; Cache-Control + no transform discourages any
    # proxy from holding chunks.
    resp = Response(stream_with_context(generate_and_cleanup()), mimetype="application/x-ndjson")
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Cache-Control"] = "no-cache, no-store, no-transform"
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route("/api/cancel/<pull_id>", methods=["POST"])
def api_cancel(pull_id):
    """Signal a running /api/pull stream to stop. Already-running pyodbc queries
    will finish on their own (pyodbc has no safe Python-side abort), but no
    more queries will start and the stream closes with a cancelled marker."""
    ev = _get_cancel(pull_id)
    if ev is None:
        return jsonify({"ok": False, "reason": "pull_id_not_found_or_already_completed"}), 404
    ev.set()
    return jsonify({"ok": True, "pull_id": pull_id})


@app.route("/api/result/<pull_id>")
def api_result(pull_id):
    """Fetch completed pull data. Pre-serialized — no re-encoding.
    Retained for backwards-compat; the inline `data` field on the `done` line
    is the preferred path."""
    data_json = _pull_results.pop(pull_id, None)
    if data_json is None:
        return jsonify({"error": "Pull result not found"}), 404
    return Response(data_json, mimetype="application/json")


@app.route("/api/status")
def api_status():
    # Include pid, in-flight pull, cancel-event count so we can diagnose
    # multi-process / multi-worker issues. /api/status MUST stay fast even
    # while a pull is running, so it only takes the inflight + cancel locks
    # for the briefest possible moment.
    inflight = _current_inflight()
    return jsonify({
        "version": APP_VERSION, "status": "ok",
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "inflight_pull_id": (inflight[:8] if inflight else None),
        "active_pulls": len(_cancel_events),
        "active_pull_ids": [k[:8] for k in list(_cancel_events.keys())],
        "parallel_max_workers": _PARALLEL_MAX_WORKERS,
    })


@app.route("/api/rates-status")
def api_rates_status():
    """Cache age + row count + stale flag. Frontend polls this on load to
    render the snapshot-age banner."""
    return jsonify(rates_cache_status())


@app.route("/api/refresh-rates", methods=["POST"])
def api_refresh_rates():
    """Manually refetch the Korber rate snapshot. Synchronous — returns when
    the refresh completes (typically 30-90s warm, 60-150s cold)."""
    result = rates_cache_force_refresh()
    status = rates_cache_status()
    return jsonify({"refresh": result, "status": status})


@app.route("/api/health")
def api_health():
    """Diagnostic endpoint — tests EDW connectivity and returns details."""
    import traceback, struct, urllib.request as ur, urllib.parse as up
    results = {}
    try:
        server = os.environ.get("EDW_DEV_SERVER", "MISSING")
        database = os.environ.get("EDW_DEV_DB", "MISSING")
        tenant = os.environ.get("EDW_SP_TENANT_ID", "MISSING")
        cid = os.environ.get("EDW_SP_CLIENT_ID", "MISSING")
        csec = os.environ.get("EDW_SP_CLIENT_SECRET", "")
        results["env"] = {
            "server": server, "database": database,
            "tenant": tenant[:12] + "...", "client_id": cid[:12] + "...",
            "secret_len": len(csec),
        }
        # Token
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/token"
        data = up.urlencode({"grant_type": "client_credentials", "client_id": cid,
                             "client_secret": csec, "resource": "https://database.windows.net/"}).encode()
        token = json.loads(ur.urlopen(url, data, timeout=10).read())["access_token"]
        results["token"] = {"ok": True, "len": len(token)}
    except Exception as e:
        results["token"] = {"ok": False, "error": str(e)}
        return jsonify(results)
    # SQL
    try:
        import pyodbc
        results["pyodbc"] = {"version": pyodbc.version, "drivers": pyodbc.drivers()}
        tb = token.encode("utf-16-le")
        ts = struct.pack(f"<I{len(tb)}s", len(tb), tb)
        conn = pyodbc.connect(
            f"Driver={{ODBC Driver 18 for SQL Server}};"
            f"Server=tcp:{server},1433;Database={database};"
            f"Encrypt=yes;TrustServerCertificate=yes;",
            attrs_before={1256: ts}, timeout=15)
        cur = conn.cursor()
        cur.execute("SELECT 1 AS health")
        results["sql"] = {"ok": True, "result": cur.fetchone()[0]}
        conn.close()
    except Exception as e:
        results["sql"] = {"ok": False, "error": str(e), "tb": traceback.format_exc()[-800:]}
    return jsonify(results)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    app.run(host="0.0.0.0", port=port, debug=False)
