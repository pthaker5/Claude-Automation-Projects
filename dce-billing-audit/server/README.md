# DC&E Billing Audit — Live (EDW) Dashboard

Pulls the audit data straight from EDW (no manual file uploads) and runs the
same audit engine as the standalone dashboard. Run it on one machine that has
EDW access; the team opens it in a browser.

## Start it (one step)

| Your computer | Do this |
|---|---|
| Windows | Double-click **`start.bat`** |
| macOS / Linux | Run **`./start.sh`** in a terminal |

First run creates a Python environment, installs everything, and creates a
`.env` file. The very first run stops and asks you to fill in `.env` — do that,
then start it again. After that it just launches.

When it's running you'll see:

```
Open this in your browser:  http://localhost:5100
```

Open that link, pick the billing period, click **Run Audit**. To let others on
the network use it, share `http://<this-machine-name>:5100`.

## One-time prerequisites

| Need | Notes |
|---|---|
| Python 3.10+ | https://www.python.org/downloads/ (on Windows, tick "Add Python to PATH") |
| Microsoft ODBC Driver 18 for SQL Server | https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server — required for the EDW connection |
| EDW access | network/VPN to the database, plus the credentials in `.env` |

## Configuration (`.env`)

`start` copies `.env.example` to `.env` on first run. Fill in:

| Variable | What it is |
|---|---|
| `EDW_DEV_SERVER`, `EDW_DEV_DB` | EDW server host and database |
| `EDW_SP_TENANT_ID`, `EDW_SP_CLIENT_ID`, `EDW_SP_CLIENT_SECRET` | service-principal login |
| `FLASK_SECRET_KEY` | any random string |

`.env` is git-ignored — the secret never goes into the repo. If the old secret
was ever committed or shared, rotate it in Azure first.

## Boxing Materials & No-Charges (action needed)

Two reports aren't pulled from EDW yet, so those checks stay quiet until the SQL
is added. Paste the dataset SQL from each SSRS report into the marked spot in
`sql_client.py`:

| Report | Function to fill | Marked with |
|---|---|---|
| Qry-HJ-Boxing Materials | `pull_boxing_materials()` | `>>> PASTE THE DATASET SQL ... <<<` |
| HJ - Billable Activity with No Charges | `pull_no_charges()` | `>>> PASTE THE DATASET SQL ... <<<` |

Each function documents the exact output columns the engine expects. Until then,
the dashboard runs everything else correctly and uses a coarse invoice-only
fallback for boxing.

## Files

| File | Purpose |
|---|---|
| `start.bat` / `start.sh` | one-step launcher (setup + run) |
| `run.py` | starts the server (waitress) |
| `app.py` | Flask routes + `/api/pull` streaming pipeline |
| `sql_client.py` | all EDW queries |
| `static/billing_audit_v37.html` | the dashboard (v39, EDW Direct) |
