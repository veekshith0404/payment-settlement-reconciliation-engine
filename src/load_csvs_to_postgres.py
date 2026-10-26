
"""Load the synthetic CSV files into empty PostgreSQL tables."""

import csv
import os
from getpass import getpass
from pathlib import Path

import psycopg


ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
TEST_DIR = ROOT_DIR / "data" / "test"

TABLES = [
    (
        "internal_orders",
        RAW_DIR / "internal_orders.csv",
        [
            "order_id",
            "order_timestamp_utc",
            "amount",
            "payment_method",
            "internal_status",
        ],
    ),
    (
        "gateway_statement",
        RAW_DIR / "gateway_statement.csv",
        [
            "gateway_txn_id",
            "merchant_order_id",
            "auth_status",
            "capture_timestamp_utc",
            "gross_amount",
            "mdr_rate_pct",
            "fee_deducted",
            "gst",
            "net_payout",
            "payout_batch_id",
        ],
    ),
    (
        "bank_statement",
        RAW_DIR / "bank_statement.csv",
        [
            "bank_entry_id",
            "payout_batch_id",
            "credit_amount",
            "settlement_date_ist",
            "bank_status",
        ],
    ),
    (
        "ground_truth_exceptions",
        TEST_DIR / "ground_truth_exceptions.csv",
        [
            "entity_type",
            "entity_id",
            "defect_type",
            "expected_amount",
            "impact_basis",
            "description",
        ],
    ),
]


def connect() -> psycopg.Connection:
    """Connect only when a database target has been explicitly configured."""
    dbname = os.getenv("PGDATABASE", "").strip()
    if not dbname:
        raise ValueError(
            "PGDATABASE is not set. Set it explicitly to the dedicated empty "
            "project database before running the loader; no database default is used."
        )

    host = os.getenv("PGHOST", "localhost")
    port = int(os.getenv("PGPORT", "5432"))
    user = os.getenv("PGUSER", "postgres")
    print(
        "PostgreSQL target: "
        f"host={host}, port={port}, database={dbname}, user={user}"
    )

    password = os.getenv("PGPASSWORD")
    if not password:
        password = getpass("PostgreSQL password for the configured user: ")

    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
    )


def import_table(
    conn: psycopg.Connection,
    table: str,
    csv_path: Path,
    columns: list[str],
) -> int:
    """Import one CSV file and return the number of rows loaded."""
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"Required CSV file not found: {csv_path}"
        )

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file_handle:
        reader = csv.DictReader(file_handle)

        if reader.fieldnames != columns:
            raise ValueError(
                f"Unexpected CSV headers in {csv_path.name}.\n"
                f"Expected: {columns}\n"
                f"Received: {reader.fieldnames}"
            )

        copy_statement = (
            f"COPY public.{table} "
            f"({', '.join(columns)}) FROM STDIN"
        )

        row_count = 0

        with conn.cursor().copy(copy_statement) as copy:
            for row in reader:
                values = [
                    None if row[column] == "" else row[column]
                    for column in columns
                ]
                copy.write_row(values)
                row_count += 1

    return row_count


def main() -> int:
    """Validate the target tables, then import all four CSV files."""
    print("CSV loader: checking that all target tables are empty.")

    try:
        with connect() as conn:
            # Check every table before starting the import.
            for table, _, _ in TABLES:
                try:
                    # Isolate each check so a missing table does not
                    # leave the connection transaction in a failed state.
                    with conn.transaction():
                        with conn.cursor() as cursor:
                            cursor.execute(
                                f"SELECT COUNT(*) FROM public.{table}"
                            )
                            row_count = cursor.fetchone()[0]

                except psycopg.errors.UndefinedTable:
                    print(
                        f"Table public.{table} does not exist. "
                        "Run sql/01_create_tables.sql first."
                    )
                    return 1

                except psycopg.Error:
                    # Let permission, connection, and other database
                    # errors reach the main error handler.
                    raise

                if row_count:
                    print(
                        f"Stopped: public.{table} already contains "
                        f"{row_count:,} rows. No data was imported."
                    )
                    print(
                        "The database may already be populated. "
                        "Do not rerun this loader on it."
                    )
                    return 2

            loaded_rows = {}

            # Import all four files in one transaction. If an import
            # fails, the transaction rolls back.
            with conn.transaction():
                for table, csv_path, columns in TABLES:
                    loaded_rows[table] = import_table(
                        conn,
                        table,
                        csv_path,
                        columns,
                    )

        print("\nCSV import completed:")

        for table, row_count in loaded_rows.items():
            print(f"  {table}: {row_count:,} rows")

        print(
            "\nNext: run sql/02_reconciliation_exceptions_view.sql "
            "in pgAdmin."
        )
        return 0

    except (OSError, ValueError, psycopg.Error) as exc:
        print(
            "CSV import failed. The transaction was rolled back "
            "where applicable."
        )
        print(f"Details: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
