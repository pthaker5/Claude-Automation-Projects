# v1.16.7 (2026-07-13) - Mechanism C actually shipped + frontier hardening + railcar end-day

## PRIMARY FIX - app.py off-by-one (Mechanism C) WAS MISSING FROM v1.16.6
The v1.16.6 delivery notes (VERIFY.md) claim app.py contains the +1-day end fix.
It does NOT: the shipped app.py had no timedelta import, no end_user, and passed
the raw picker end to every pull. Since every windowed pull is END-EXCLUSIVE
(closed_date < ?, actual_ship_date < ?), the user's inclusive end day was
silently dropped - and for DC&E batch billing that day is routinely the batch-
close day holding ~all charges. Window 07-06..07-13 returned 21-30 charges
instead of ~11,751 / $3.66M. THIS was the live outage; the A (JS) and B
(sql_client) fixes were present but cannot matter while the rows never leave SQL.

Fix: end_user = end; end += timedelta(days=1). Advanced end -> invoice, lost
revenue, packaging, bulk, boxing, no_charges. Raw end_user -> pull_billing_horizon
(its SQL advances internally via DATEADD) and pull_railcar (see below).
data["end"] echoes end_user (UI reasons in inclusive dates).
Verified: stubbed-sql_client Flask test asserts per-pull dates for normal,
single-day, year-boundary, and leap-year windows.

## FIX 2 - pull_billing_horizon: batch_complete was trivially spoofable
v1.16.6 let ANY day clearing 95% coverage advance the frontier, including tiny
ones, and only counted unbilled MATERIAL days AFTER the frontier. Two failure
modes: (a) tiny fully-billed stray days in a mid-batch window walk the frontier
to the audit end -> batch_complete=True -> JS snaps cutoff to audit end -> the
pending window is audited as billed (the 3,713-false-positive storm returns);
(b) pending days often have NO charge rows at all (charges are created at
billing time), so an un-posted batch is INVISIBLE to any coverage test.
Fix (_billing_frontier_analysis, unit-tested): only material days (>=20 rows)
advance the frontier, and batch_complete additionally requires the frontier to
reach within 1 day of the audit end (frontier_gap_days <= 1). Reference window
07-06..07-13: frontier 07-12, gap 1 -> complete (unchanged). Mid-batch
6/29-7/6: frontier 07-01, gap 5 -> incomplete regardless of stray billing.

## FIX 3 - pull_railcar end-day truncation
arrive_date < end and depart_date BETWEEN start AND end cut the end day at
midnight (datetime columns): arrivals/departures ON the inclusive end day were
dropped. Now arrive_date < DATEADD(day,1,end) and depart_date >= start AND
< DATEADD(day,1,end); dwell-as-of stays the USER end day so open-car dwell is
not inflated by +1. pull_railcar receives end_user from app.py.

## FIX 4 - JS dsDate UTC-midnight leak
new Date('YYYY-MM-DD') parses as UTC midnight = 5-8h into the PREVIOUS local
day in US timezones; beforeStart() admitted prior-period rows shipped in those
hours. Now new Date(ds + 'T00:00:00') (local midnight).

Files: app.py (APP_VERSION 1.16.7), sql_client.py, static/billing_audit.html.
All three must deploy together (same rule as v1.15: partial deploys of this
repo have shipped version-skewed behavior twice now).

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
