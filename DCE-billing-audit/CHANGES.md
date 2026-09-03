# v1.17.1 (2026-09-01) — Setup-screen polish

- Fix: audit-mode radio buttons rendered as full-width pills (global .cfg-row
  input style bled onto them); scoped input[type=radio] override added.
- UX: Work-Week Lookback and Storage Billing Month moved into a collapsible
  "Advanced options" section — the default flow is now just "pick Invoice
  Date, Run Audit".
- Fix (v1.17.0 regression): Storage Billing Month was unreachable in Date
  Range mode (it lived inside the invoice-mode row); the Advanced section is
  visible in both modes.
- Files: static/billing_audit.html (UI), app.py (version), deploy.yml (probe).


---

# v1.17.0 (2026-08-18) — Response to DC&E team feedback (Le'Shea, 8/18)

Five issues reported; each maps to a fix below. Full detail in FIXES_v1.17.0.md.

## 1. Missing Audit — Boxing Material Audit no longer populating (BUG FIX)
pull_boxing_materials bound its SQL parameters in the wrong order whenever
warehouse checkboxes were selected: placeholders appear as (CTE wh filter,
start, end, charge wh filter) but params were passed [start, end, wh…, wh…].
Dates were bound into wh_id IN (...) and warehouse IDs into the closed_date
bounds — the pull matched nothing/errored and the audit vanished. Unfiltered
pulls have no wh placeholders, which is why validation passed. Params now
follow true placeholder order.

## 2. Report results / date range — new Invoice-Date audit mode (FEATURE)
The teams audit one invoicing batch ("invoices dated August 17"), not an
arbitrary range. New default mode: pick the Invoice Date; the server pulls
  - invoice-driven data (invoice, boxing materials) for closed_date == that day
  - operational data (lost revenue, packaging, bulk, no charges, railcar) for
    the covered work week [invoice_date − lookback, invoice_date)
so prior, already-reviewed batches stay out, the audited batch is never
missing, and orders completed ON the invoicing day (which bill next cycle)
are excluded automatically. Date Range mode retained for ad-hoc analysis.

## 3. Previously reviewed items — shared, persistent review store (FEATURE)
Done/Skip statuses and notes now persist server-side (/api/reviews, JSON store
on the App Service shared /home volume) keyed by order|category, tagged with
the Easy Auth signed-in user and timestamp. Every run re-applies the store, the
status pill shows who reviewed the item and when, and a "Hide reviewed (N)"
toggle (default ON) keeps completed items out of the working list.

## 4. Incorrect results — charges flagged not-invoiced that WERE invoiced (BUG FIX)
pull_no_charges only cleared an order when a charge existed under the EXACT
event-log order number. Charges posted under dash-suffixed sub-orders
(PW2995516 vs PW2995516-3) or with stray whitespace kept surfacing as "No
Charges". The NOT EXISTS rewrite also matches the '<order>-suffix' form and
trims both sides. Invoice-Date mode removes the other false-positive source
(batch closed outside the pulled window).

## 5. Load time (PERF)
  - Removed the 6.4 MB embedded rate-snapshot blob from billing_audit.html.
    The page is served no-store, so every visit re-downloaded 6.6 MB; it is now
    ~200 KB (~97% smaller). EDW rates come from the server cache as before.
  - pull_bulk_orders: InvoiceMatch/DetailRollup CTEs aggregated the ENTIRE
    charge and order-detail tables every pull; now scoped to window orders.
  - pull_boxing_materials: PW-order classification scan bounded to 180 days.
  - pull_no_charges: NOT EXISTS replaces join-then-group over all charges.

## Files
  static/billing_audit.html — v1.17.0 (mode UI, shared reviews, blob removed)
  app.py                    — invoice-date windowing, /api/reviews endpoints
  sql_client.py             — boxing param-order fix, no-charges rewrite, CTE bounds

## DEPLOYMENT NOTE
app.py, sql_client.py AND static/billing_audit.html all changed — deploy all three.


---

# v1.15 (2026-07-01) - Recurring Storage Variance Fix (PRIMARY) + billingDate Auto-Track

## PRIMARY FIX - app.py recurring_storage normalization (restores ~378 action items)

### Symptom
Recurring Storage Variance showed 0 action items on the dashboard (no bar in the
"Action Items by Category" chart). Action Items badge read ~680 for 6/15-6/22
instead of the true ~992. The ~378 Recurring Storage Variance items were missing.

### Root cause
The v1.13 fix renamed the recurring-storage SQL column aliases in sql_client.py:
  difference -> variance, qty -> snapshot_qty, uom -> per,
  client_code -> customer_code, Client -> customer.
sql_client.py and the JS engine were both updated. app.py was NOT.

app.py's "Normalize recurring storage for engine()" block still read the OLD
names via r.get(): r.get("difference",0), r.get("qty",0), r.get("uom",""),
r.get("client_code",""). Those keys no longer exist in the SQL output, so every
.get() returned its default. Critically, variance defaulted to 0 for ALL rows.
The server shipped 9,820 rows all with variance:0; the JS engine's
`if(absVar===0) return;` skipped every one -> zero Recurring Storage action items.

This is the same class of bug (field-name mismatch) the v1.13 fix addressed in
sql_client.py + engine, but it survived in a THIRD location (app.py) that the
v1.13 work did not touch.

### Fix
app.py recurring_storage normalization now reads the NEW SQL names first and
falls back to the OLD names, so it is correct against either schema:
  variance      = r.get("variance")      if not None else r.get("difference", 0)
  snapshot_qty  = r.get("snapshot_qty")  if not None else (qty / LP Count logic)
  per           = r.get("per")           or r.get("uom", "")
  customer_code = r.get("customer_code") or r.get("client_code", "")
  customer      = r.get("customer")      or r.get("Client") or r.get("Whse") or ""
  invoice_number= r.get("invoice_number", "")  (was hardcoded "")

### Live verification (Open_Claw_Fabric_Data SP, billing_date=2026-06-22)
  raw pulled rows: 9,820 (SQL keys confirmed: variance/per/snapshot_qty/customer_code present)
  OLD normalize (deployed bug): 0 action items   <- reproduces the missing bar
  NEW normalize (v1.15 fix):    378 action items <- restored
  OLD rows with non-zero variance after normalize: 0 of 9,820

## SECONDARY FIX - billingDate auto-track (hygiene, carried from Forge v1.15)
billingDate input no longer hardcoded to 2026-05-19. It auto-tracks the audit
end date (de) while data-auto="1"; a non-blocking amber warning shows at Pull
time if billingDate month != audit-window month. Prevents a separate future
error where the recurring-storage pull silently targets the wrong month.
NOTE: this alone did NOT fix the missing items - the app.py bug zeroed variance
regardless of billing_date (verified: 5/19, 6/22, 6/29 all yield ~378 from the
raw pull; the loss happened in app.py normalization, not the pull).

## Files
  static/billing_audit.html  - v1.15 (billingDate auto-track + version banner)
  app.py                     - recurring_storage normalization fix (THE fix)
  sql_client.py              - verbatim from v1.13/v1.14 (unchanged)

## DEPLOYMENT NOTE
This release changes app.py (server), not just the HTML. BOTH must be redeployed.
Deploying only billing_audit.html will NOT restore the 378 items.
