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
│   ├── baseline/                 # Clean synthetic baseline CSV files
│   ├── raw/                      # Injected fixture used by the pipeline
│   └── test/
│       └── ground_truth_exceptions.csv
├── reports/                      # Generated XLSX and CSV output
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

Install the dependencies into a virtual environment. From the project root:

```powershell
py -3.11 -m venv .venv
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
- `PGUSER` — database role, defaulting to `postgres` if not set
- `PGPASSWORD` — optional; the scripts prompt for a password when this variable is not set

`config/.env.example` is a reference template. The scripts do **not** load it automatically. In PowerShell, set values for the current terminal session explicitly. Use a brand-new, empty database for this updated fixture; the example below uses `PaymentReconFinalTestDB`:

```powershell
$env:PGHOST = "localhost"
$env:PGPORT = "5432"
$env:PGDATABASE = "PaymentReconFinalTestDB"
$env:PGUSER = "payment_recon_app"
```

Before running either Python database script, verify that `PGDATABASE` names the intended database. Both scripts print the target host, port, database, and user before connecting. They never print the password. Never commit a real password or other credentials.

## Setup in a fresh, empty database

**Do not load the updated fixture into an existing project database.** The loader checks that all target tables are empty and intentionally refuses to load into populated tables. The updated schema adds constraints and the updated fixture adds two test cases. Create a new empty database so the new schema is applied from scratch. Keep `PaymentReconDB` and your existing `PaymentReconTestDB` unchanged.

1. In pgAdmin, create a new empty database named `PaymentReconFinalTestDB` (or choose another name and set `PGDATABASE` to match it).
2. Connect pgAdmin's Query Tool specifically to that new database.
3. Execute the complete `sql/01_create_tables.sql` script and confirm the four project tables exist.
4. If you use a separate application role, execute the relevant permission examples in `sql/04_grant_permissions_example.sql` as the database owner or administrator. If the application role owns the database objects, extra grants may not be needed.
5. Set `PGHOST`, `PGPORT`, `PGDATABASE`, and `PGUSER` in the PowerShell session as described above.
6. From the project root with the virtual environment active, run:

   ```powershell
   python src/load_csvs_to_postgres.py
   ```

   Enter the configured role's password when prompted. The expected loaded row counts are 1,000 internal orders, 908 gateway records, 64 bank entries, and 44 ground-truth exceptions.
7. Execute `sql/02_reconciliation_exceptions_view.sql` in pgAdmin while connected to the same database. This recreates the read-only detection view. The settlement deadline uses the fixed as-of date `2026-10-26` so the September 2026 fixture is reproducible. Change this constant deliberately if you want to model a different evaluation date.
8. Run the statements in `sql/03_ground_truth_validation.sql` to compare detections with the independent ground-truth answer key.
9. Run the Python reporting pipeline:

   ```powershell
   python src/run_reconciliation.py
   ```

10. Review the validation summary and generated reports under `reports/`. The fixture is designed for all 44 injected exceptions to match; treat the run's actual result, not this design goal, as the evidence of what your current database detected.

`sql/00_initial_profiling.sql` contains optional read-only profiling queries.

## Running the tests

From the project root with the virtual environment activated:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

The tests cover validation metrics, duplicate keys, null amounts, database-target safety, two injected edge cases, Excel sheet-name constraints, and currency formatting. They do not execute the PostgreSQL view. Run the SQL scripts and reporting pipeline against the dedicated new database to validate PostgreSQL behaviour end to end.

## What the reconciliation view checks

The view returns a standard exception schema with category, entity identifier, expected/actual values where applicable, variance, amount under review, and a reason.

- **Missing gateway record:** an internally successful order has no matching **captured** gateway transaction. A non-captured row alone does not satisfy this rule.
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

The report files are generated outputs and are excluded from Git by `.gitignore`. A fresh run should generate the current results after the database fixture and view have been updated.
