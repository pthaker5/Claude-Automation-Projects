"""
DC&E Billing Audit — Web Application v2
Optimized: parallel report pulls, streaming progress, single-query Lost Revenue.
"""

import os
import json
import math
import uuid
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, render_template, jsonify, Response, stream_with_context
from dotenv import load_dotenv
load_dotenv()

from sql_client import (
    pull_invoice, pull_rates, pull_lost_revenue,
    pull_railcar, pull_packaging, pull_bulk_orders, pull_recurring_storage,
    _clean,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

APP_VERSION = "1.2.0"

_pull_results = {}  # in-memory store for completed results


@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION)


@app.route("/api/pull", methods=["POST"])
def api_pull():
    """
    Pull all report data from EDW with parallel execution and streaming progress.
    Phase 1: 5 independent reports in parallel (Invoice, Rates, Railcar, Packaging, Bulk)
    Phase 2: 2 sequential reports (Lost Revenue, Recurring Storage — heavier queries)
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

    billing_date = None
    if body.get("billing_date"):
        try:
            billing_date = datetime.strptime(body["billing_date"], "%Y-%m-%d").date()
        except ValueError:
            pass

    warehouses = body.get("warehouses") or None
    clients    = body.get("clients") or None

    def generate():
        import queue, threading

        data = {}
        total = 7

        # ── Phase 1: parallel independent reports ────────────────────────────
        parallel_tasks = [
            ("Invoice",     "invoice",      lambda: pull_invoice(start, end)),
            ("Rates",       "rates",        lambda: pull_rates()),
            ("Railcar",     "railcar",      lambda: pull_railcar(start, end)),
            ("Packaging",   "packaging",    lambda: pull_packaging(start, end)),
            ("Bulk Orders", "bulk_orders",  lambda: pull_bulk_orders(start, end)),
        ]

        yield json.dumps({"progress": "Starting parallel pull (5 reports)…", "step": 0, "total": total}) + "\n"

        completed = 0
        errors = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {}
            for label, key, fn in parallel_tasks:
                fut = pool.submit(fn)
                futures[fut] = (label, key)

            for fut in as_completed(futures):
                label, key = futures[fut]
                try:
                    result = fut.result()
                    data[key] = result
                    completed += 1
                    count = len(result) if isinstance(result, list) else 0
                    yield json.dumps({
                        "progress": f"✓ {label}: {count:,} rows",
                        "step": completed, "total": total
                    }) + "\n"
                except Exception as e:
                    errors.append(f"{label}: {e}")
                    completed += 1
                    yield json.dumps({
                        "progress": f"✗ {label}: {e}",
                        "step": completed, "total": total
                    }) + "\n"

        if errors:
            yield json.dumps({"error": "Parallel pull errors: " + "; ".join(errors)}) + "\n"
            return

        # ── Phase 2: sequential heavy queries ────────────────────────────────
        sequential_tasks = [
            ("Lost Revenue",      "lost_revenue",      lambda: pull_lost_revenue(start, end)),
            ("Recurring Storage", "recurring_storage", lambda: pull_recurring_storage(billing_date, warehouses, clients)),
        ]

        for label, key, fn in sequential_tasks:
            yield json.dumps({"progress": f"Pulling {label}…", "step": completed, "total": total}) + "\n"
            try:
                result = fn()
                data[key] = result
                completed += 1
                count = len(result) if isinstance(result, list) else 0
                yield json.dumps({
                    "progress": f"✓ {label}: {count:,} rows",
                    "step": completed, "total": total
                }) + "\n"
            except Exception as e:
                yield json.dumps({"error": f"{label} failed: {e}"}) + "\n"
                return

        # ── Normalize recurring storage for engine() ─────────────────────────
        if "recurring_storage" in data:
            data["recurring_storage"] = [{
                "wh_id":           r.get("wh_id", ""),
                "customer":        r.get("Client") or r.get("Whse") or "",
                "customer_code":   r.get("client_code", ""),
                "chargeback_code": r.get("description", ""),
                "description":     r.get("display_item_number", ""),
                "per":             r.get("uom", ""),
                "invoice_qty":     r.get("invoice_qty", 0),
                "snapshot_qty":    r.get("qty", 0) if r.get("LP Count", 0) == 0 else r.get("LP Count", 0),
                "variance":        r.get("difference", 0),
                "invoice_number": "",
            } for r in data["recurring_storage"]]

        # ── Finalize ─────────────────────────────────────────────────────────
        data["start"] = start.isoformat()
        data["end"]   = end.isoformat()
        data = _clean(data)

        yield json.dumps({"progress": "Building dashboard…", "step": total, "total": total}) + "\n"
        # Pre-serialize once (28MB) — store as string, serve directly
        pull_id = str(uuid.uuid4())
        _pull_results[pull_id] = json.dumps(data, default=str)
        if len(_pull_results) > 5:
            oldest = next(iter(_pull_results))
            del _pull_results[oldest]
        yield json.dumps({"done": True, "pull_id": pull_id}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@app.route("/api/result/<pull_id>")
def api_result(pull_id):
    """Fetch completed pull data. Pre-serialized — no re-encoding."""
    data_json = _pull_results.pop(pull_id, None)
    if data_json is None:
        return jsonify({"error": "Pull result not found"}), 404
    return Response(data_json, mimetype="application/json")


@app.route("/api/status")
def api_status():
    return jsonify({"version": APP_VERSION, "status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100, debug=True)
