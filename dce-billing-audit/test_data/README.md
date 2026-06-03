# test_data/

Real SSRS exports live here **locally only**. They are git-ignored (`*.xlsx`
in the repo root `.gitignore`) because they contain real customer names and
charge amounts. The code is version-controlled; the data is dropped in locally,
same as the rest of this repo.

`test_harness.js` routes files by a case-insensitive keyword in the filename
(see the `find()` calls). Drop one export per slot:

| Slot | Keyword matched | Example filename | Required |
|---|---|---|---|
| inv  | `chargeback` (or `revenue_by`) | `HJ - HighJump Revenue by Chargeback.xlsx` | yes |
| lost | `lost`        | `HJ - Lost Revenue.xlsx`                       | yes |
| nc   | `no_charges`  | `HJ - Billable Activity with No_Charges.xlsx`  | optional |
| rc   | `railcar`     | `Railcar Arrival Report.xlsx`                  | optional |
| pkg  | `packaging`   | `HJ - Revenue Audit Packaging.xlsx`            | optional |
| bxm  | `boxing`      | `Qry-HJ-Boxing Materials.xlsx`                 | optional |

Then run from the project root:

```
npm install            # one-time: xlsx, papaparse
node test_harness.js billing_audit_v37.html
```

The harness extracts the live `engine()` from the HTML, decodes the embedded
rate blob, parses these exports with the app's own parser logic, and diffs
per-category counts against `BASELINE` in `test_harness.js`.
