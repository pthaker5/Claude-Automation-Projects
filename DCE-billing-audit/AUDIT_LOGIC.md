# DC&E Billing Audit — engine() Logic Reference

Reverse-engineered from `billing_audit_v37.html` engine() function (~1,500 lines JS).

---

## Overview

The audit analyzes **weekly WMS (Korber) billing data** to catch:
- **Rate mismatches** — invoice rate ≠ contract rate
- **Missing charges** — orders shipped but no invoice posted
- **Overbilling** — charges that shouldn't be there per SOP
- **Billing gaps** — expected charges not present (switch fees, materials, terminal transfers)
- **Data quality** — large single charges, near-zero entries, quantity mismatches

---

## Inputs to engine()

```
engine(inv, lost, rr, nc, rc, pkg, ds, de, bxm, bulk, stor)
```

| Input | Description | Key Columns |
|-------|-------------|-------------|
| `inv` | Invoice — Revenue by Chargeback | `WH ID`, `Customer Code`, `Customer Name`, `Chargeback Code`, `Charge Description`, `Rate`, `Per`, `Charge Amount`, `Charge Date`, `Order Number`, `Invoice Number`, `Invoice Date`, `Description 2`, `Qty` |
| `lost` | Lost Revenue — shipped orders | `WH ID`, `Order Number`, `Name`, `Client Code`, `Amount Billed`, `Ship Date`, `BOL Number`, `Carrier Name`, `Comment`, `Source Vessel`, `Dest Vessel`, `Our Supplies`, `Billing Link` |
| `rr` | Rate table | `customer_code`, `contract_wh_id`, `chargeback_code`, `description`, `rate`, `per_text`, `order_type`, `container_type`, `precedence` |
| `nc` | No Charges (billable activity w/o invoice) | `Order Number`, `WH ID`, `Date`, `Description`, `Vessel` |
| `rc` | Railcar arrivals | `WH ID`, `Client Code`, `Client Name`, `Railcar`, `Arrived Date` |
| `pkg` | Packaging | `Warehouse`, `Order Number`, `Comments`, `Store Order Number`, `Type`, `Invoice Number`, `Source Vessel`, `Destination Vessel`, etc. |
| `bxm` | Boxing materials | `customer_code`, `customer_name`, `invoice_number`, `description`, `order_num`, `qty`, `wh_id`, `location` |
| `bulk` | Bulk shipping orders | Same shape as `pkg` but type = "Bulk Shipping Order" |
| `stor` | Recurring storage | `wh_id`, `customer`, `customer_code`, `chargeback_code`, `description`, `per`, `invoice_qty`, `snapshot_qty`, `variance`, `invoice_number` |

---

## Rate Matching Logic

### Lookup key: `customer_code | contract_wh_id | chargeback_code`

For each invoice row:
1. Build key = `Customer Code + "|" + WH ID + "|" + Chargeback Code`
2. Look up in rate table (`rl[key]`)
3. **Fallback**: if no match, try flat-fee lookup `customer_code + "|" + chargeback_code` (entries where `per_text` is empty = contract-level rates)

### Match types:
- **`m` (match)** — invoice rate matches a rate table entry exactly
- **`c` (CPI-close)** — within tolerance (default 6%): `|invoice_rate - contract_rate| / contract_rate <= CPI_TOL`
- **`tr` (tier range)** — rate falls within a multi-tier range (sampling tiers)
- **`mm` (mismatch)** — rate doesn't match any entry → flagged
- **`zr` (zero-rate)** — all rate table entries for this code are $0 → gap suppression
- **`nc` (no code)** — chargeback code not in rate table at all → treated as "truly manual"

### bestRate() matching considers:
- `per_text` (unit of measure) — must match or be `<ANY>`
- `container_type` — must match or be `<ANY>`
- `order_type` — inferred from order number prefix (PW=Packaging, SO=Shipping, etc.)
- `precedence` — lower = higher priority, used for tie-breaking

### Special cases:
- **Lump sum**: Rate=0 but Amount>0 → tries to match Amount against flat-fee rates
- **Batch charges**: Order numbers like MULTIPLE/SPLIT → validated separately
- **Gap suppression**: If ALL rate entries for a chargeback code are $0 across 5+ weight-unit entries, suppress mismatch
- **Overall-rate suppression**: If a customer has 5+ core codes all at $0, suppress (overall-rate customer)

---

## Action Item Categories

### 1. $0 + Billing Link (severity: error)
- **Trigger**: Lost Revenue row with `Amount Billed = 0` AND `Billing Link > 0`
- **Meaning**: Order was linked for billing but $0 was charged
- **Action**: Open billing link in HighJump, verify charge should have posted

### 2. No Charges (severity: error)
- **Trigger**: No Charges report row not found in invoice data
- **Meaning**: Billable activity occurred but no invoice was generated
- **Action**: Check charge setup in WMS
- **Special**: ASN orders with RAILCAR vessel → flagged as "Weekend Miss" (invoice ran before yard logged arrival)

### 3. Missing Charges (severity: error)
- **Trigger**: `Billing Link count > posted charge count` for an order
- **Meaning**: More billing links than charges → some charges didn't post
- **Action**: Check billing links in HighJump

### 4. Sampling Overbill (severity: warning)
- **Trigger**: PW order has SAMPLE charge + additional charges (not switch/handling/inbound/resin)
- **Meaning**: Sample minimum is all-in — extra charges should be removed
- **Exclusions**: Equistar (system-programmed), SP/RS order prefixes

### 5. Handling on SO (severity: warning)
- **Trigger**: Shipping Order (SO prefix) with HAND/HANDCWT/INBSTOPLT/INBSTOCWT/INBSTOWT charge
- **Meaning**: Handling/storage charges on a shipping order are unusual
- **Special**: Equistar SO handling is always an error (contract prohibits)

### 6. Missing Supply (severity: warning)
- **Trigger**: `Our Supplies > 0` AND `Amount Billed > 0` but no SUPPLIES/CUSPSTOR/MATUNL/CUSTSUPP charge
- **Exclusions**: Celanese, Equistar (bring own supplies)

### 7. BO Trailer-Trailer (severity: warning)
- **Trigger**: Bulk Order (BO prefix) with both Source Vessel and Dest Vessel = TRAILER
- **Meaning**: May be misclassified order type

### 8. Missing Terminal Fee (severity: info)
- **Trigger**: Source Vessel ≠ Dest Vessel (vessel change) but no TERM/SWITCH/SHUTTLE charge
- **Exclusions**: Auburn (WH 21-262) — terminal billed at Blackstone

### 9. Missing Switch Fee (severity: warning)
- **Trigger**: Railcar arrival at a warehouse that normally bills switch fees, but customer has zero switch charges in the invoice
- **Requires**: Railcar arrivals report (`rc`)

### 10. Repack + Handling Out (severity: warning)
- **Trigger**: PW order has both REPACK and HAND OUT charges
- **Action**: Confirm handling out is valid alongside repack

### 11. Packaging Audit (severity: warning)
- **Flag 1**: PW order with no invoice number → order completed but didn't populate to invoice
- **Flag 2**: Comment includes Re-Stencil/Restenciling AND Source+Dest Vessel = BAG → check if reclass

### 12. Sample Minimum Rate (severity: info)
- **Trigger**: PW order with total LBS < 11,000
- **Shows**: Applicable tier from rate table, charges billed, LBS qty
- **Action**: If charges < tier rate, remove supply charges and bill sample minimum

### 13. Railcar Min Packaging (severity: warning)
- **Trigger**: PW order on railcar, 11K–70K LBS aggregated across sub-orders, no SAMPLE/MIN charge
- **Exclusions**: Equistar, Channel Prime, Intech, Ineos
- **Key**: Aggregates across dash-variants (PW-XXXX-3, PW-XXXX-4, etc.)

### 14. Boxing Material Audit (severity: warning)
- **Trigger**: PW order with work description (Repack, Packaging Bulk to Bag/Box/SS) but missing expected material charges (Bags, Pallets, Stretch Wrap, Hood Film, Slip Sheet, Liners)
- **Exclusions**: Own-supply customers (Equistar, Celanese, Exxon, Westlake, Dow, LYB)
- **Exclusions**: Baytown/Houston locations

### 15. Qty Mismatch SS/HF/PLT (severity: warning)
- **Trigger**: Slip Sheet, Hood Film, and Pallet quantities on same PW order don't match
- **Rule**: All three are billed per pallet — should be equal
- **Exclusion**: COMBO charge present → skip

### 16. Near-Zero Loose Loading (severity: warning)
- **Trigger**: HANDLL/LOOSELOAD charge < $1.00
- **Meaning**: Likely entry error

### 17. Accuracy — Large Charge (severity: warning/error)
- **Trigger**: Single packaging charge > $20,000 on PW order
- **Error** if > $100,000
- **Exclusion**: Baytown/Houston

### 18. Recurring Storage Variance (severity: warning)
- **Trigger**: `|variance|` exceeds threshold (>100 LBS for weight, >=10 for units)
- **Data**: `stor` input — `invoice_qty` vs `snapshot_qty`, variance = difference

### 19. Rate Mismatch (severity: varies)
- **Trigger**: Invoice rate doesn't match any contract rate within tolerance
- **Severity**: error if overcharge > $500, warning if > 5 charges, info otherwise
- **Groups by**: Customer + Warehouse

---

## KPIs (dashboard top bar)

| KPI | Source |
|-----|--------|
| **Total Billed** | `SUM(Charge Amount)` from invoice |
| **Charges** | Count of invoice rows (after dedup) |
| **Rate Matched** | `st.rm` — charges that matched or were CPI-close |
| **Action Items** | Count of all `items` with `bk='act'` |
| **Flagged** | `st.rmm` — rate mismatches |
| **Tier OK** | `st.tierOk` — multi-tier range matches |

---

## Date Filtering

- **Cutoff**: `max(Charge Date)` from invoice = latest date work was performed and invoiced
- Lost Revenue rows shipped AFTER cutoff are excluded (not yet billable)
- Lost Revenue rows shipped BEFORE start date are excluded (prior period)
- Railcar arrivals after cutoff are excluded

---

## Customer-Specific Exclusions

- **Equistar** (`EQUISTAR_CODES`): System-programmed sample minimum, no railcar sample fee, handling prohibited on SO
- **Celanese** (`CELANESE_CODES`): Bring own supplies — skip supply checks
- **Auburn WH (21-262)**: Terminal fees billed at Blackstone, not locally
