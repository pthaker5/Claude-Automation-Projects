# DC&E Billing Audit Dashboard — v1.17.0
## Response to the DC&E team's feedback (Le'Shea, 2026-08-18)

Each issue from the email, what caused it, and what changed.

---

## Issue 4 first — "Missing Audit: the boxing material audit is no longer populating"

**Root cause (real bug, found in `sql_client.py:pull_boxing_materials`).**
SQL parameters are bound **positionally**. The query's placeholders appear in this
order: ① warehouse filter inside the `BoxingPwOrders` CTE, ② `closed_date >= ?`,
③ `closed_date < ?`, ④ warehouse filter in the charge stream. But the code passed
`[start, end, wh…, wh…]`. The moment auditors selected warehouse checkboxes —
which the DC&E teams always do — the **dates were bound into `wh_id IN (...)`**
and **warehouse IDs into the date bounds**. The pull returned nothing (or
errored) and the Boxing Material Audit silently disappeared. Pulls with *no*
warehouse selected have no warehouse placeholders at all, which is exactly why
the original validation ("2026-06-01..06-08: 919 rows") passed.

**Fix.** Parameters are now listed in true placeholder order
(`[start] + wh + [start, end] + wh` — the extra leading `start` feeds a new
180-day scan bound, see load-time section).

**Secondary cause fixed by Issue 2's change:** the boxing pull is windowed
entirely on **invoice close date**. When the team ran "Aug 10–16" to audit the
Aug 17 invoices, the Aug 17 batch was outside the window, so even an unfiltered
pull returned nothing. Invoice-Date mode (below) pulls exactly the batch day.

---

## Issue 2 — "Report results/date range: to audit invoices dated August 17 we may need to run August 10–16…"

**Root cause (design mismatch).** DC&E bills in weekly batches: work performed
Mon–Sun closes on the following invoicing day. The dashboard, however, windowed
*everything* on one user-supplied date range: invoice-driven pulls on
`closed_date`, operational pulls on ship/activity dates. There was **no window
that isolates one batch**:

- Include Aug 17 → the range also spans Aug 10, pulling in the **Aug 10 batch
  that was already reviewed**.
- Exclude Aug 17 → the **Aug 17 batch is invisible**: boxing audit empty,
  invoiced charges look "not invoiced", horizon logic flags the tail as pending.

**Fix (new default): "Invoice Date" audit mode.** Pick the invoicing
(batch-close) date — e.g. Monday Aug 17. The server then splits the windows:

| Data | Window |
|---|---|
| Invoice charges, Boxing materials | `closed_date` == the invoice date (exactly the audited batch) |
| Lost revenue, Packaging, Bulk orders, No charges, Railcar | work dates in `[invoice_date − lookback, invoice_date)` — the covered work week (lookback defaults to 7 days, adjustable) |
| Billing horizon | covered work week, with batch-day closes counted as billed |
| Recurring storage anchor | defaults to the invoice date's month-close |

Consequences, in the email's terms:

- Aug 10's already-reviewed invoices **cannot** appear: the invoice window is
  Aug 17 only. (Work performed Aug 10 *is* in scope — the Aug 10 batch covered
  work through Aug 9, so Aug 10–16 work is precisely the Aug 17 batch's
  population.)
- Nothing needed for the audit fails to populate: the batch day is always pulled.
- "Orders completed the day of invoicing that will be captured on the next
  invoicing cycle" are **excluded automatically** — the operational window ends
  the day *before* the invoice date.

The legacy Date Range mode is still available via a toggle for ad-hoc analysis.
(Its "Period End" hint also incorrectly said *Exclusive* while the backend
treats it as inclusive since v1.16.7 — corrected.)

---

## Issue 3 — "Previously reviewed items: no clear way to identify whether an item has already been reviewed"

**Root cause.** Done/Skip statuses and notes lived in in-page JavaScript
variables — wiped on every run, never visible to other auditors.

**Fix: shared, persistent review store.**

- New endpoints `GET/POST /api/reviews` persist status + note per item key
  (`order|category`) in a JSON store on the App Service shared `/home` volume
  (`REVIEWS_STORE_PATH`, default alongside the rates cache). Entries carry
  **who** (the Easy Auth signed-in user) and **when**; entries older than
  `REVIEWS_TTL_DAYS` (default 210) are pruned.
- Every audit run re-applies the store, so items anyone marked Done/Skipped —
  today or three weeks ago — come back with that status, the reviewer's name,
  and the date on the status pill.
- New **"Hide reviewed (N)"** toggle in the filter bar (default ON) keeps
  already-handled items out of the working list; the count shows what's hidden.
- Notes persist and sync the same way (debounced save on edit).

Marking an item Done in the Aug 17 audit also suppresses it if it ever
reappears in an overlapping run — the direct fix for "duplicating work that
someone else has already completed."

---

## Issue 5 — "Incorrect Audit Results: charges identified as not invoiced that were invoiced in Körber"

Two mechanisms, both fixed:

1. **Exact-match order join** (`pull_no_charges`): an order was only cleared
   when a charge existed under the *exact* event-log order number. Charges are
   routinely posted under dash-suffixed sub-orders (`PW2995516` in the event
   log vs `PW2995516-3` on the charge) or with stray whitespace — those orders
   kept surfacing as "No Charges" even though Körber showed them invoiced.
   The rewritten `NOT EXISTS` also matches the `<order>-<suffix>` form and
   trims whitespace on both sides.
2. **Batch closed outside the pulled window**: with a range ending before the
   batch-close day, every charge in that batch was invisible to the dashboard
   and flagged missing. Invoice-Date mode (Issue 2) eliminates this class.

---

## Issue 1 — "Load time"

| Change | Effect |
|---|---|
| Removed the 6.4 MB embedded rate-snapshot blob from `billing_audit.html`. The page is deliberately served `Cache-Control: no-store` (deploy-staleness protection), so every single visit re-downloaded 6.6 MB before anything rendered. | Page is now ~200 KB — **~97% smaller** on every load. EDW rates come from the server-side disk cache exactly as before; only the never-used upload-mode fallback lost its embedded snapshot (a rates file can still be uploaded). |
| `pull_bulk_orders`: the `InvoiceMatch` and `DetailRollup` CTEs aggregated the **entire** `t_bmm_charge` and `t_order_detail` tables on every pull before the window filter applied. Now scoped to the window's orders (semantically identical). | Removes two full-table `GROUP BY`s from every audit. |
| `pull_boxing_materials`: the PW-order classification scan was unbounded over all order history; now floored at 180 days before the window. | Cuts years of history from the scan while keeping any plausible late-billed order. |
| `pull_no_charges`: `NOT EXISTS` replaces the join-then-group over the full charge table. | Faster, and required for the Issue 5 fix anyway. |

Also note: Invoice-Date mode narrows the invoice/boxing pulls from 8 days of
closes to 1, which shrinks both query time and the payload streamed to the
browser.

---

## Deployment

`app.py`, `sql_client.py`, and `static/billing_audit.html` **all changed — deploy all three**
(same procedure as v1.15: deploying only the HTML will not fix the backend issues).

Optional env vars: `REVIEWS_STORE_PATH`, `REVIEWS_TTL_DAYS`, `REVIEWS_MAX_ENTRIES`.

## Suggested reply points for Le'Shea's team

- Use the new **Invoice Date** mode with the batch date you're auditing (e.g. Aug 17); leave lookback at 7.
- Mark items **Done/Skip** as you work — everyone now sees them, with your name and date, and they stay hidden on re-runs.
- Boxing Material Audit repopulates with warehouse filters applied (param-order bug fixed).
- If a "No Charges"/"not invoiced" flag still doesn't match Körber, capture the order number — with the suffix-matching fix these should now be true exceptions.
