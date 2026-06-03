# DC&E Billing Audit — v3 Architecture Proposal

**Status:** Proposal only. No changes to existing app.  
**Validated:** Query runs clean against EDW_Dev — 24,993 rows, 12.7s, results below.

---

## The Problem with v2

The current `sql_client.py` runs 5 separate report functions, each doing its own
multi-table join against Korber source tables at query time:

| Function | Issue |
|---|---|
| `pull_lost_revenue` | 3 round-trip loops: orders → vessel batches → charge batches |
| `pull_bulk_orders` | Correlated subquery on 16.25M-row `t_bmm_event_log` per order row |
| `pull_recurring_storage` | Full 128M-row snapshot scan on every call; CAST() kills index |
| `pull_invoice` | Fine as-is |
| `pull_packaging` | Fine as-is, but `[Count Trans]` is always NULL |

**Bigger gap:** none of the current functions compare what was billed against
contracted rates. The audit is manual — a human compares the report output to
the rate sheet. v3 closes that gap in the database.

---

## The v3 Proposal

One pre-staged table: **`CORE.Stg_DCE_OpenInvoiceAudit`**

- **Scope:** all open (non-posted) invoices — `status NOT IN ('P')`
- **Grain:** one row per charge line
- **Pre-joined at load time:** invoice → charge → chargeback → contract → customer → order → order_detail → Core_Rates
- **Rate resolution at load time:** `CORE.Core_Rates` joined on `chargeback_id`, with `container_type` wildcard matching (`<ANY>`, `All`, or exact `source_vessel` match), precedence-ranked so the most specific rule wins
- **Computed at load:** `expected_amount`, `discrepancy`, `rate_variance`, `is_manual_charge`, `has_discrepancy`, `rate_match_found`
- **Refreshed nightly** by a single ADF stored-proc activity; also callable on-demand

App-side queries become simple `SELECT *` reads with optional filter parameters.
Single round trip. Sub-second response once the table is loaded.

---

## What the Audit Computes

| Column | Definition |
|---|---|
| `billed_rate` | `c.rate` — the rate Korber applied |
| `billed_qty` | `TRY_CAST(prompt_text_value AS FLOAT)` — NULL if blank |
| `contracted_rate` | `Core_Rates.rate` — best-matched contracted rate |
| `expected_amount` | `billed_qty × contracted_rate` — NULL if manual or no rate match |
| `discrepancy` | `charge_amount − expected_amount` — positive = overbilled |
| `rate_variance` | `billed_rate − contracted_rate` — shows if wrong rate was applied |
| `is_manual_charge` | 1 = blank `prompt_text_value` (flat-rate, can't auto-audit) |
| `has_discrepancy` | 1 = `ABS(discrepancy) > $0.01` |
| `rate_match_found` | 0 = no Core_Rates row matched (gap in rate table) |

---

## Validated Results (EDW_Dev, run 2026-06-01)

Using live Korber rate tables (`t_bmm_chargeback_rate` + manual prompt tables),
with NULL/empty vessel treated as wildcard for charges with no order context:

| Rate Source | Charges | Rate Matched | Discrepancies | Total Billed | Total Discrepancy |
|---|---|---|---|---|---|
| **WMS_Rates** | 24,403 | 24,403 (100%) | 19,566 | $5,309,180 | **$930,470** |
| **WMS_Manual** | 264 | 264 (100%) | 0 | $426,286 | $0.00 ✓ |
| **Renewal_Review** | 118 | 0 | — | $37,046 | n/a |
| **No rate row** | 208 | 0 | — | $168,705 | n/a |
| **TOTAL** | **24,993** | **24,667 (98.7%)** | | **$5,941,217** | |

**98.7% rate match.** WMS_Manual charges audit perfectly (expected — these are
manually entered flat rates). The **$930K discrepancy** across 19,566 WMS_Rates
charges is the real audit output — charges where `charge_amount ≠ billed_qty × contracted_rate`.

### Rate source breakdown

**WMS_Rates** — `t_bmm_chargeback_rate` (active rates, status='A')
Event-based charges. Container_type matched against order detail source_vessel;
NULL/empty vessel (no order context) treated as wildcard — picks lowest-precedence rate.

**WMS_Manual** — `t_bmm_param_manual_csr_prompt` / `t_bmm_param_manual_prompt`
Manual-Prompted and Manual-CSR-Prompted charges. No container_type restriction.

**Renewal_Review** (118 charges, $37K) — Renewal/Storage/Inbound types with no
matching rate row. Flagged for manual review; snapshot-based audit path applies
(same logic as existing `pull_recurring_storage`).

**No rate row** (208 charges, $168K) — `Manual - Adhoc` and unmatched `WMS Event`
charges. These represent genuine gaps in the rate tables — charges being applied
with no contracted rate on file.

---

## New Functions vs Old

| v2 Function | v3 Equivalent |
|---|---|
| `pull_invoice(start, end)` | `pull_open_audit()` scoped to invoice date range |
| `pull_lost_revenue(start, end)` | `pull_open_audit()` — order context already joined |
| `pull_bulk_orders(start, end)` | `pull_open_audit(chargeback_codes=[...])` or by order prefix |
| `pull_packaging(start, end)` | `pull_open_audit()` filtered on `display_order_number LIKE 'PW%'` |
| `pull_recurring_storage(date)` | `pull_open_audit()` + `is_manual_charge` flag covers storage charges |
| `pull_rates()` | Unchanged |
| _(new)_ | `pull_discrepancies()` — only rows with calculable variance |
| _(new)_ | `pull_manual_charges()` — flat-rate charges for human review |
| _(new)_ | `pull_unmatched_rates()` — charges with no rate match (gap report) |
| _(new)_ | `pull_audit_summary(group_by)` — rollup by customer/wh/chargeback/invoice |

---

## Deployment Steps (run with EDW admin credentials in Synapse Studio)

```
1. Run  sql/01_Stg_DCE_OpenInvoiceAudit_DDL.sql     → creates the staging table
2. Run  sql/02_usp_Refresh_DCE_OpenInvoiceAudit.sql  → creates the stored proc
3. Add ADF activity in prodadfquantixedw:
       Name: AT_Refresh_DCE_OpenInvoiceAudit
       Type: Stored Procedure
       SP:   CORE.usp_Refresh_DCE_OpenInvoiceAudit
       Trigger: add to existing nightly pipeline
4. Replace imports of sql_client.py → sql_client_v3.py in app.py
   (or rename after validation)
```

---

## Open Questions Before Go-Live

1. **$930K discrepancy — how much is real vs rate table artifact?**
   The largest driver is likely charges where `contracted_rate = 0` in
   `t_bmm_chargeback_rate` (intentional zero-rate) vs charges where Korber
   applied a non-zero rate. Need to segment: `WHERE contracted_rate = 0 AND billed_rate > 0`
   vs `WHERE contracted_rate > 0 AND billed_rate <> contracted_rate`.

2. **208 charges with no rate row ($168K):** These are `Manual - Adhoc` and
   unmatched `WMS Event` charges with no entry in `t_bmm_chargeback_rate`.
   Should these be reviewed manually or routed to a separate exception queue?

3. **Renewal_Review (118 charges, $37K):** These have no active rate row.
   Are they covered by a different rate table (e.g. `t_bmm_param_recurring`)?
   Or are these the snapshot-based recurring storage charges that belong to
   the `pull_recurring_storage` audit path?

4. **Refresh frequency:** Nightly ADF proposed. If invoices move between
   G/A/P during the business day, an on-demand refresh endpoint from the app
   UI may be needed.

5. **`wh_id = '13-160'` exclusion:** Present in v2's recurring storage query.
   Should it be excluded from the full audit table too?

---

## Files in this Proposal

```
v3_proposal/
├── PROPOSAL.md                              ← this file
├── sql_client_v3.py                         ← drop-in replacement for sql_client.py
└── sql/
    ├── 01_Stg_DCE_OpenInvoiceAudit_DDL.sql  ← CREATE TABLE (run in Synapse Studio)
    └── 02_usp_Refresh_DCE_OpenInvoiceAudit.sql  ← CREATE PROCEDURE (run in Synapse Studio)
```

Existing `sql_client.py` and app are untouched.
