# Payment Settlement Reconciliation Engine

A Python and PostgreSQL project that reconciles internal payment orders, payment-gateway records, and bank settlement entries. It identifies settlement and data-quality exceptions, exports an Excel workbook and CSV files, and validates detected exceptions against a separate synthetic ground-truth answer key.

> **Project motto:** Never trust an internal status without an external bank trace: audit every rupee between customer click, gateway capture, and actual cash deposit.

## Project scope

The project focuses on payment operations, reconciliation, data quality, and reporting using SQL, Python, pandas, and Excel. It does not require a web application, API, cloud deployment, Docker, or machine learning.

All datasets are synthetic. The fixture exercises deliberately injected scenarios; it is not evidence of accuracy on all real-world payment-system failure modes.

## Current synthetic fixture

The committed fixture has these row counts:

| Dataset | Rows |
|---|---:|
| Internal orders | 1,000 |
| Gateway records | 908 |
| Bank entries | 64 |
| Ground-truth exceptions | 44 |

The 44 expected exceptions are distributed across 12 categories:

| Exception category | Expected cases |
|---|---:|
| `MISSING_GATEWAY_RECORD` | 14 |
| `MDR_OVERCHARGE` | 9 |
| `SETTLEMENT_TIMING_LAG` | 4 |
| `DUPLICATE_BANK_CREDIT` | 3 |
| `MISSING_BANK_SETTLEMENT` | 3 |
| `BANK_SETTLEMENT_AMOUNT_MISMATCH` | 2 |
| `NON_CREDITED_BANK_ENTRY` | 3 |
| `ORPHAN_GATEWAY_RECORD` | 1 |
| `ORPHAN_BANK_CREDIT` | 1 |
| `INTERNAL_GATEWAY_STATUS_MISMATCH` | 2 |
| `ORDER_GATEWAY_AMOUNT_MISMATCH` | 1 |
| `GATEWAY_NET_PAYOUT_MISMATCH` | 1 |
| **Total** | **44** |

The defect injector uses a fixed seed. Clean baseline files are stored separately from injected raw data. The SHA-256 check confirms that the injector did not modify baseline files during a run; it does not independently prove that the baseline data is inherently correct. `ground_truth_exceptions.csv` is an evaluation answer key and is not read by the production reconciliation view.

## Repository layout

```text
payment-settlement-reconciliation-engine/
├── config/
│   └── .env.example
├── data/
│   ├── baseline/                  # Clean synthetic baseline CSV files
│   ├── raw/                       # Injected fixture used by the pipeline
│   └── test/
│       └── ground_truth_exceptions.csv
├── reports/                       # Generated XLSX and CSV output
├── sql/
│   ├── 00_initial_profiling.sql
│   ├── 01_create_tables.sql
│   ├── 02_reconciliation_exceptions_view.sql
│   ├── 03_ground_truth_validation.sql
│   └── 04_grant_permissions_example.sql
├── src/
│   ├── generate_baseline.py
│   ├── inject_defects.py
│   ├── load_csvs_to_postgres.py
│   └── run_reconciliation.py
├── tests/
│   ├── test_database_safety.py
│   ├── test_fixture_scenarios.py
│   ├── test_report_formatting.py
│   └── test_report_validation.py
├── requirements.txt
├── LICENSE
├── README.md
└── START_HERE.txt
```

## Requirements

- Windows with PowerShell (the commands below use PowerShell syntax)
- Python 3.11 or newer
- PostgreSQL 18 or a compatible PostgreSQL version
- pgAdmin or another PostgreSQL client

Install the dependencies into a virtual environment. From the project root, first confirm that the Python launcher selects Python 3.11 or newer (`py -0p` lists installed interpreters):

```powershell
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Database connection settings

The scripts read PostgreSQL connection settings from environment variables:

- `PGHOST` — host name, usually `localhost`
- `PGPORT` — port, usually `5432`
- `PGDATABASE` — **required** database name; there is no default database
- `PGUSER` — database role; defaults to `postgres` if not set
- `PGPASSWORD` — optional; the scripts prompt for a password when this variable is not set

`config/.env.example` is a reference template. The scripts do **not** load it automatically. Set the environment variables in your PowerShell session. The example below uses a dedicated database named `PaymentReconFinalTestDB` and the application role `payment_recon_app`:

```powershell
$env:PGHOST = "localhost"
$env:PGPORT = "5432"
$env:PGDATABASE = "PaymentReconFinalTestDB"
$env:PGUSER = "payment_recon_app"
```

Before running either Python database script, verify that `PGDATABASE` names the intended database. Both scripts print the target host, port, database, and user before connecting. They never print the password. Never commit a real password or other credentials.

## Setup in a fresh, empty database

Use a **new, empty database** for this fixture. The CSV loader intentionally refuses to load into populated project tables.

1. In pgAdmin, create an empty database named `PaymentReconFinalTestDB` (or choose another name and set `PGDATABASE` to match it).

2. Choose how to connect:
   - **Local demonstration with an administrator account:** use your local PostgreSQL administrator role for the database setup and the Python scripts. Set `PGUSER` to that role.
   - **Separate application role:** create a login role named `payment_recon_app` in pgAdmin under **Login/Group Roles**. Set a strong password and enable login. If the role already exists, do not create it again. Use this role for the Python scripts and grant it the required permissions in the steps below.

3. Open pgAdmin's Query Tool connected specifically to `PaymentReconFinalTestDB` as the database owner or administrator. Execute the complete `sql/01_create_tables.sql` script and confirm the four project tables exist.

   The schema requires `capture_timestamp_utc` for gateway rows whose `auth_status` is `CAPTURED`. Non-captured rows may have a null capture timestamp. This database constraint rejects captured rows without timestamps, preventing settlement-deadline rules from silently operating on an unknown capture time.

4. If using the separate application role, execute `sql/04_grant_permissions_example.sql` while connected to `PaymentReconFinalTestDB` as the database owner or administrator. This grants the role access needed to load and read the project tables. Review the example before executing it; grant only the permissions the chosen role needs.

5. In your VS Code PowerShell terminal, set the connection variables. For the application-role option:

   ```powershell
   $env:PGHOST = "localhost"
   $env:PGPORT = "5432"
   $env:PGDATABASE = "PaymentReconFinalTestDB"
   $env:PGUSER = "payment_recon_app"
   ```

   For the administrator option, set `PGUSER` to your administrator role instead. Enter the configured role's password when prompted. Do not put passwords in source files or commit them to Git.

6. From the project root with the virtual environment active, load the CSV data:

   ```powershell
   python src/load_csvs_to_postgres.py
   ```

   Expected row counts are 1,000 internal orders, 908 gateway records, 64 bank entries, and 44 ground-truth exceptions. Run the loader only against the new, empty database; it will refuse to load into populated tables.

7. In pgAdmin, execute `sql/02_reconciliation_exceptions_view.sql` while connected to the same database. This creates the detection view. The settlement deadline uses the fixed evaluation date `2026-10-26` so the September 2026 fixture is reproducible. Change this date deliberately if you want to model a different evaluation date.

8. If the view was created by an administrator and you are using a separate application role, grant the application role permission to read the view. Run this statement in pgAdmin while connected to `PaymentReconFinalTestDB` as the view owner or administrator:

   ```sql
   GRANT SELECT ON public.reconciliation_exceptions
   TO payment_recon_app;
   ```

   Skip this grant if you are running the reporting script as the same role that owns the view, or change the role name to match your configuration.

9. Execute `sql/03_ground_truth_validation.sql` in pgAdmin to compare detections with the independent ground-truth answer key.

10. Run the Python reporting pipeline from the project root:

    ```powershell
    python src/run_reconciliation.py
    ```

11. Review the validation summary and generated reports under `reports/`. The fixture is designed for all 44 injected exceptions to match; treat the actual validation output, not the design goal, as evidence of what your database detected.

`sql/00_initial_profiling.sql` contains optional read-only profiling queries.

## Running the tests

From the project root with the virtual environment activated:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

The tests cover validation metrics, duplicate keys, null amounts, database-target safety, two injected edge cases, Excel sheet-name constraints, and currency formatting. They do not execute the PostgreSQL view. Run the SQL scripts and reporting pipeline against the dedicated database to validate PostgreSQL behaviour end to end.

## What the reconciliation view checks

The view returns a standard exception schema with category, entity identifier, expected/actual values where applicable, variance, amount under review, and a reason.

- **Missing gateway record:** an internally successful order has no matching captured gateway transaction. A non-captured row alone does not satisfy this rule.
- **Orphan gateway record:** a captured gateway transaction has no matching internal order.
- **Internal/gateway status mismatch:** the internal order is `FAILED` or `DROPPED` while the gateway transaction is `CAPTURED`.
- **Order/gateway amount mismatch:** the gateway gross amount differs from the internal order amount by at least ₹0.01.
- **Gateway net-payout mismatch:** the stored gateway net payout differs from gross less fee and GST by at least ₹0.01.
- **MDR overcharge:** actual fee and GST exceed the contracted synthetic expectation by at least ₹0.01. Unknown payment methods are rejected by the table constraint rather than silently omitted from the fee check.
- **Missing bank settlement:** a gateway payout has passed the fixed evaluation date's settlement deadline and has no bank entry of any status.
- **Non-credited bank entry:** a bank entry exists with a status other than `CREDITED`.
- **Bank settlement amount mismatch:** the credited bank total is short or excessive by at least ₹0.01, except over-credits classified as duplicate bank credits.
- **Duplicate bank credit:** multiple credited entries exist for one payout batch and their combined total exceeds the expected payout by at least ₹0.01. Legitimate split credits that sum to the expected payout are not classified as duplicates.
- **Settlement timing lag:** the last credited bank date is later than the next weekday after the batch date. The view converts the UTC capture timestamp to IST before deriving the batch date. Weekends are skipped; public holidays are not modelled.
- **Orphan bank credit:** a credited bank payout batch has no matching captured gateway payout batch.

## Known limitations

This is a deterministic, synthetic portfolio fixture, not a production payment processor. The generator and view encode the same documented fee assumptions, so perfect results on the injected cases do not establish general real-world accuracy. The cases are primarily isolated rather than overlapping.

- Multiple captured gateway transactions for the same merchant order are not yet reported by a dedicated duplicate-capture rule; such cases may surface indirectly through other amount checks.
- A failed, held, or reversed bank entry remains visible as `NON_CREDITED_BANK_ENTRY` even if a later bank entry credits the batch. This preserves the audit trail; reviewers should assess whether the eventual settlement resolves the operational issue.
- The fee schedule and weekday settlement deadline are synthetic assumptions, not legal, tax, scheme, or payment-network guidance. Real systems may require merchant-specific contracts, holidays, payout-reference matching, refunds, chargebacks, reversals, partial settlements, and manual-review workflows.
- Exception amounts across categories should not be summed as net financial loss; a transaction or batch can have multiple related financial measures.

## Generated reports

`src/run_reconciliation.py` writes these fixed-name outputs and replaces existing files on subsequent successful runs:

- `reports/payment_reconciliation_report.xlsx` — Excel workbook with validation, all exceptions, ground truth, row counts, and category-specific sheets
- `reports/reconciliation_exceptions.csv` — detected exceptions
- `reports/validation_detail.csv` — identifier and amount validation details

The report files are generated outputs and are excluded from Git by `.gitignore`. A fresh run should generate the current results after the database fixture and view have been set up.
