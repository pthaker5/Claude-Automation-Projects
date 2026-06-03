# CLAUDE.md — DC&E Billing Audit Dashboard

## What this is
Single-file HTML/JS dashboard (`billing_audit_v32.html`, ~6.3MB) that automates the DC&E team's weekly post-billing audit at Quantix SCS. Replaces Mamie Weese's manual process across ~43 warehouses and ~260 customers. Users upload SSRS exports; all logic runs client-side in the browser. No server, no build step, no dependencies. Built v1→v32 through chat sessions; moving to Claude Code for EDW live mode and ongoing iteration.

Owner: Poojan Thaker (Analyst, AI Analytics & Automation). Audit team: Mamie Weese (logic source), LeShea McDarment, Collin Persak, Julie Marsh, Sarah, Pammy, Sue, Patricia. Manager-level contact: Kevin.

## Working conventions (do not skip)
- Single consolidated deliverables. One HTML file, not a split project. The 6.3MB size is intentional (embedded rate table) so auditors can open it with zero setup.
- Verify against real data before claiming a bug. A v30 review falsely flagged 3 checks as dead by trusting a stale schema doc instead of reading the real export. The real Revenue by Chargeback file has BOTH `Charge Description` (col 8, charge name) and `Description 2` (col 10, line detail). Always check the actual file.
- Run the regression harness (`test_harness.js`) after every engine change. It runs the real engine extracted from the HTML against real exports in `test_data/`.
- Tables over bullets in docs. No em dashes in emails. Concise, human tone. Push back when findings look wrong.
- Version bump on every shipped change (v33 next). Keep a one-line changelog comment at the top of the script block.

## File anatomy
- One `<style>` block, one main `<script>` block (~123K chars of JS, ~2,500 lines total file).
- Line ~396: `var _EMBEDDED_RATES_B64 = '...'` — 69,704 WMS rates as base64 CSV (source: EDW `CORE.Core_Rates`, pulled 2026-05-29, latin-1). This single line is ~6.37MB. Strip/stub it before reading the file; never retype it.
- Constants: lines ~352–374. Helpers/parsers: ~461–727. `engine()`: ~729–2198. Rendering/UI: rest.
- `engine(inv, lost, rr, nc, rc, pkg, ds, de, bxm)` is pure logic except one `Q('de').value` read; everything else DOM-free. The harness shims `Q`.

## Inputs (verified schemas, from real 2026-05 exports)
| File | Parser | Header | Key columns (exact names) |
|---|---|---|---|
| HJ - HighJump Revenue by Chargeback | `px` (first sheet) | row 1 | WH ID, Location, Customer Name, Customer Code, Chargeback Code, **Charge Description**, Order Number, Rate, Per, Qty, Charge Amount, **Description 2**, Invoice Number, Invoice Date, Charge Date |
| HJ - Lost Revenue | `pxAllSheets` (39 sheets, rows where col0 falsy, headers from sheet 1) | row 1 | WH ID, Name, Client Code, Order Number, Order Type, Ship Date, Amount Billed, Billing Link, Our Supplies, Source Vessel, Dest Vessel |
| HJ - Billable Activity with No Charges | `px` | row 1 | Order Number, Name/Client, Description, Vessel, Date |
| Railcar Arrival Report | `pxRailcar` | **row 4** (`range:3`) | WH ID, Client Code, Client Name, Railcar, Arrived Date, **Released Date** (depart; populated ~13% of rows) |
| HJ - Revenue Audit Packaging | `pxPackaging` | **row 4** (`range:3`) | Warehouse, Order Number, Type, Source Vessel, Destination Vessel, Quantity, Invoice Number (cols 17–24 exist; don't trust truncated peeks) |
| Qry-HJ-Boxing Materials | `pxBoxingMaterials` | **row 2** (`range:1`) | Order Num, description, customer name, customer code, invoice number, Qty, charge amount, wh id, location, source vessel, dest vessel |

Dedup: invoice rows deduped on 9 columns (WH ID, Customer Code, Chargeback Code, Order Number, Rate, Charge Amount, Description 2, Charge Date, Invoice Number). Preserves legit distinct charges (e.g. 481 Equistar $5.09/EA storage lines).

Cutoff: `max(Charge Date)` from the invoice, NOT the user end date. LR/NC rows shipped after the cutoff are intentionally suppressed ("shipped but not yet invoiced"). Verified: 4 of 6 ASNs after a 5/19 cutoff correctly held back.

## Rate engine
Join: Customer Code + WH ID + Chargeback Code → rate table. Cascade (most→least specific): unit+container match → unit match → weight conversion (CWT=100LB, MT=2204.6LB, KG=2.205LB) → tier range. Tolerance `CPI_TOL = 0.06` (±6%, symmetric — consider asymmetric tightening on the overbill side someday). `xCt()` extracts container type from `Description 2` (`Vessel = X`, prefix list RAILCAR/ELIMINATOR/CONTAINER/TRAILER/DRYTAINER, `ASN Receipt`→RAILCAR). Batch orders (`MULTIPLE`/`SPLIT`/`EMPTY`) rate-validated but tracked separately. Manual orders: non-standard order numbers; rate-match clears them automatically.

## Checks (27 categories; counts = actual engine output via test_harness.js, week of 2026-05-18)
| Category | Logic | Verified count |
|---|---|---|
| $0 + Billing Link | LR: Amount Billed=0, Billing Link>0 | 20 |
| No Charges | NC report order absent from invoice, within cutoff | 0 (NC rows were ASNs handled by Weekend Miss or past cutoff) |
| Missing Charges | LR billing links > posted charges | 477 (Dow + Celanese heavy — testers confirming volume is expected) |
| Sampling Overbill | SAMPLE + other charges same PW (all-in min) | 0 |
| Handling on SO | HAND/HANDCWT/INBSTO* on SO order; Equistar contract callout | 0 (verified raw: no SO rows carry these codes this week) |
| Missing Supply | LR Our Supplies>0, no supply charge | 91 |
| BO Trailer-Trailer | bulk order TRAILER→TRAILER | 41 |
| Missing Terminal Fee | vessel change, no term/switch/shuttle | 78 (noisy; fires at >=1 order; needs confirmed-WH list) |
| Railcar Switch (Weekend Miss) | ASN arrivals missing from Monday invoice (2AM cutoff) | 2 |
| Missing Switch Fee | customer at switch-billing WH w/o switch charge | 12 (trigger set is data-derived "any WH with any switch this period" — known FP mode, replace with contract list) |
| Repack + Handling Out | PW has REPACK and HAND OUT | 0 (28 REPACK, 91 HAND OUT, no overlap — check works) |
| Packaging Audit | PW no invoice number (→Collin); re-stencil/DOWNGRADE Src=Dest=BAG | 9 |
| Sample Minimum Rate | PW < 11,000 LB | 18 |
| Boxing Material Audit | work desc but missing expected materials | 83 |
| Qty Mismatch (SS/HF/PLT) | slip sheet ≠ hood film ≠ pallet qty (per-pallet, must match; combo line exempts) | 0 this week |
| Bag Qty Not Updated | bagQty <= max(pltQty*1.5, 200) — bags must NOT match pallets (CS auto-fills pallet count) | 10 |
| Railcar Storage | arrival w/o BULKSTOR/RAILSTOR; exclusions below; dwell from Released Date | 36 (6 with computed dwell) |
| Accuracy — Large Charge | PW single charge > $20K | 0 |
| Railcar Min Packaging | railcar PW 11K–70K LB, min-pkg customer; sub-orders aggregated by base PW | 9 |
| Multiple Billing Links (+Info) | 2+ links even if posted | (info bucket) |
| Fee Qty > 1 | LATEORDER/LATEFEE/RUSHFEE qty>1 (per-occurrence only; rate-based fees excluded) | 0 (89 candidate fee lines detected — check works) |
| Near-Zero Loose Loading | loose-loading charge < $1.00 | 8 |
| Rate Mismatch | rate engine, grouped per customer-WH | 66 |
| Not in Rate Table | no contract entry for customer+WH+code | 7 |
| ⚠ Manual — Review / ✓ Manual — Verified | non-standard order numbers, rate-checked | 11 / 1 |

CAUTION on historical figures: numbers quoted in older chat summaries for some checks (e.g. "switch fee 20 combos / 83 cars", "Missing Supply 47", "Handling on SO 21") came from a Python re-implementation used during review, whose grouping differed from the engine. The engine numbers above, reproduced by `test_harness.js`, are authoritative. When validating changes, trust the harness, not chat history.

NOTE the intentional asymmetry: SS/HF/PLT must MATCH each other; bags must NOT match pallets. Both from the same Collin/Sue recording. Comments in code should cross-reference.

## Customer/WH rules
- `CELANESE_CODES` {00003, 00003EM, 116, 116A, 116B, 116PA, 116-PX}: own supplies; excluded from Sampling Overbill, Missing Supply.
- `EQUISTAR_CODES` {250, 250-6A, 250-6F, 250CAT, 5443, 5443-6G, 5443-6H, ...}: system min, no railcar sample fee, no handling charge, own supplies, no late order fee, terminal fee $75.
- `BXM_OWN_SUPPLY` (boxing skipped): Equistar, Celanese, ExxonMobil, Westlake, Dow, LYB, Channel Prime, Intech, Ineos.
- `NO_SAMPLE_CUSTOMERS`: Channel Prime, Intech, Ineos, LYB/LyondellBasell, Hamco/Hamburger, Shawl, Venmar.
- `MIN_PKG_CUSTOMERS`: Heartland Polymers only ($10.29/packout). INCOMPLETE — a non-Heartland "Minimum Packaging Fee" line exists in boxing data; trace it.
- `AUBURN_WH` 21-262: terminal/shuttle billed at Blackstone.
- Railcar storage exclusions: WH-ID pinned {14-165, 43-538}; name-regex baytown|houston|jeffersonville|wilmington|santa fe springs|highlands|pasadena (LATENT RISK: name resolution needs the WH to appear in the invoice; pin remaining to IDs). Charleston/Savannah (43-536): Axcens only. Intech excluded.

## Known gaps / next work
1. **EDW live mode** (primary Claude Code task). Toggle exists in UI (was stripped, re-add); `goEDW()` POSTs {start,end,warehouses} to `http://srv1476299:5100/api/pull`, expects {invoice, lost_revenue, rates, railcar, packaging} with SSRS-style column names (snake_case for rates). `edw_api.py` (Flask, port 5100) and `edw_pull.py` exist from earlier sessions. On-prem server: `az-bwprod.chemlogix.com` / DB `CLXDW`, Trusted_Connection, ODBC Driver 18, TrustServerCertificate=yes. Azure `dev-quantix-useast-sql.database.windows.net`/EDW_Dev was blocked by VPN/firewall — use on-prem. EDW mode must pass `nc` and `bxm` (was silently [] once — regression to guard).
2. **Recurring (supply) Storage audit** — NOT built; blocked on data source. Monthly EOM CUSPSTOR charges keyed manually from site email pallet counts. Verify whether `t_bmm_inv_snapshot_history` + `t_bmm_inv_snapshot_detail` capture pallet counts. If yes → real check. If only charges → presence check with history-derived customer list (6–12 months of CUSPSTOR per customer-WH; threshold handles do-not-bill like Minmar and flat-rates like Channel Prime $50). Do NOT build from a guessed customer list.
3. **Bulk Audit (Pammy)** — not built; recordings were bad audio. Needs a walkthrough meeting first.
4. **Accuracy audit baseline** — wrong-billing-item detection (e.g. LBL pick at $25K) needs EDW historical distribution per customer/chargeback.
5. **Open question (Mamie)**: HAND OUT on Celanese Ticona GUR SO orders — should it trigger Handling on SO? ~25 orders, ~$5K. Check currently matches HAND exact, not HAND OUT.
6. Open inputs from team: full one-for-one supply list (box, lid, liner, pad beyond HF/SS/PLT), min-pkg customers beyond Heartland, per-occurrence fee codes beyond LATEORDER/LATEFEE/RUSHFEE.
7. Terminal-fee and switch-fee confirmed-WH lists (replace data-derived triggers).

## Regression harness
`test_harness.js` (alongside this file) extracts the live constants+helpers+`engine()` slice from the HTML (`var CPI_TOL` through end of `engine` — deliberately NOT the whole script, since evaluating UI init code against stubbed DOM changes check behavior), shims `Q()`, parses real exports from `test_data/` with the app's own parser logic, decodes the embedded rate blob, runs `engine()`, and diffs per-category counts against BASELINE. Baseline (v32, week of 2026-05-18): 979 items, 0 NaN/undefined. Any engine change: run it and explain every category delta before bumping the version. When test_data is replaced with a new week, rerun, verify deltas make sense, then update BASELINE.

## Version history (compressed)
v19 baseline (13 checks) → v20–29 added boxing/SS-HF/bag/railcar-storage/large-charge/min-pkg/multi-link/fee-qty/loose-loading → v26 review fixes (EDW bxm passthrough, drop routing, check renames, WH+CC cross-ref, INTECH typo) → v29 narrowed fee codes → v30 SS/HF/PLT + boxing missing-materials → v31 drag-drop lost-before-revenue fix, bag-vs-pallet rule, dead code removal, Jeffersonville WH-ID pin → v32 dwell via Released Date (verified: 61 cars compute).
