"""Generate the clean synthetic datasets for the payment reconciliation project."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 42
TOTAL_ORDERS = 1_000
START_DATE = datetime(2026, 9, 1, tzinfo=timezone.utc)

BASELINE_DIR = Path(__file__).resolve().parent.parent / "data" / "baseline"
IST = timezone(timedelta(hours=5, minutes=30))

CONTRACTED_MDR = {
    "UPI": Decimal("0.0000"),
    "DEBIT_CARD": Decimal("0.0090"),
    "CREDIT_CARD": Decimal("0.0180"),
    "NET_BANKING": Decimal("0.0150"),
}

PAYMENT_METHODS = ["UPI", "DEBIT_CARD", "CREDIT_CARD", "NET_BANKING"]
METHOD_WEIGHTS = [0.55, 0.20, 0.15, 0.10]

STATUS_CHOICES = ["SUCCESS", "FAILED", "DROPPED"]
STATUS_WEIGHTS = [0.92, 0.05, 0.03]


def quantize_inr(value: Decimal) -> Decimal:
    """Round an amount to two decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_business_days(start_date: date, business_days: int = 1) -> date:
    """Add weekdays to a date, skipping Saturday and Sunday."""
    current_date = start_date
    added_days = 0

    while added_days < business_days:
        current_date += timedelta(days=1)

        if current_date.weekday() < 5:
            added_days += 1

    return current_date


def generate_clean_baseline() -> None:
    np.random.seed(SEED)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating a clean baseline for {TOTAL_ORDERS:,} internal orders...")

    # Create the internal order ledger.
    order_ids = [
        f"ORD_202609_{i:04d}"
        for i in range(1, TOTAL_ORDERS + 1)
    ]

    total_seconds = 30 * 24 * 60 * 60
    random_seconds = np.random.randint(
        0,
        total_seconds,
        size=TOTAL_ORDERS,
    )

    timestamps_utc = [
        START_DATE + timedelta(seconds=int(seconds))
        for seconds in random_seconds
    ]

    raw_amounts = np.round(
        np.random.exponential(scale=1200, size=TOTAL_ORDERS) + 49.0,
        2,
    )
    raw_amounts = np.clip(raw_amounts, 50.0, 25000.0)

    payment_methods = np.random.choice(
        PAYMENT_METHODS,
        size=TOTAL_ORDERS,
        p=METHOD_WEIGHTS,
    )

    internal_statuses = np.random.choice(
        STATUS_CHOICES,
        size=TOTAL_ORDERS,
        p=STATUS_WEIGHTS,
    )

    df_orders = pd.DataFrame(
        {
            "order_id": order_ids,
            "order_timestamp_utc": [
                timestamp.strftime("%Y-%m-%d %H:%M:%S")
                for timestamp in timestamps_utc
            ],
            "amount": raw_amounts,
            "payment_method": payment_methods,
            "internal_status": internal_statuses,
        }
    ).sort_values("order_timestamp_utc", kind="stable").reset_index(drop=True)

    # Create gateway transactions for successful orders only.
    success_orders = df_orders[
        df_orders["internal_status"] == "SUCCESS"
    ].copy()

    gateway_records = []

    for _, row in success_orders.iterrows():
        order_id = row["order_id"]
        gross_amount = Decimal(str(row["amount"]))
        payment_method = row["payment_method"]

        order_timestamp = datetime.strptime(
            row["order_timestamp_utc"],
            "%Y-%m-%d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)

        capture_timestamp = order_timestamp + timedelta(
            seconds=int(np.random.randint(1, 6))
        )

        gateway_txn_id = f"GTX_2026_{order_id.split('_')[-1]}"

        # Calculate the processing fee, GST and net payout.
        mdr_rate = CONTRACTED_MDR[payment_method]
        fee_deducted = quantize_inr(gross_amount * mdr_rate)
        gst = quantize_inr(fee_deducted * Decimal("0.18"))
        net_payout = quantize_inr(gross_amount - fee_deducted - gst)

        # Assign each capture to a payout batch using Indian Standard Time.
        capture_ist = capture_timestamp.astimezone(IST)
        batch_date = capture_ist.strftime("%Y%m%d")
        cycle = "C1" if capture_ist.hour < 12 else "C2"
        payout_batch_id = f"BATCH_{batch_date}_{cycle}"

        gateway_records.append(
            {
                "gateway_txn_id": gateway_txn_id,
                "merchant_order_id": order_id,
                "auth_status": "CAPTURED",
                "capture_timestamp_utc": capture_timestamp.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "gross_amount": float(gross_amount),
                "mdr_rate_pct": float(mdr_rate * Decimal("100")),
                "fee_deducted": float(fee_deducted),
                "gst": float(gst),
                "net_payout": float(net_payout),
                "payout_batch_id": payout_batch_id,
            }
        )

    df_gateway = pd.DataFrame(gateway_records)

    # Group gateway payouts to build the matching bank statement.
    batch_aggregates = []

    for batch_id, group in df_gateway.groupby("payout_batch_id"):
        total_net = sum(
            Decimal(str(value))
            for value in group["net_payout"]
        )

        batch_date_text = batch_id.split("_")[1]
        batch_date = datetime.strptime(
            batch_date_text,
            "%Y%m%d",
        ).date()

        batch_aggregates.append(
            {
                "payout_batch_id": batch_id,
                "total_net_payout": quantize_inr(total_net),
                "batch_date": batch_date,
            }
        )

    bank_records = []
    utr_sequence = 10001

    for batch in batch_aggregates:
        batch_id = batch["payout_batch_id"]
        batch_date = batch["batch_date"]
        total_credit = batch["total_net_payout"]

        # The synthetic bank settlement arrives on the next weekday.
        settlement_date = add_business_days(
            batch_date,
            business_days=1,
        )

        bank_entry_id = (
            f"UTR_HDFC_{settlement_date.strftime('%Y%m%d')}_{utr_sequence}"
        )
        utr_sequence += 1

        bank_records.append(
            {
                "bank_entry_id": bank_entry_id,
                "payout_batch_id": batch_id,
                "credit_amount": float(total_credit),
                "settlement_date_ist": settlement_date.strftime("%Y-%m-%d"),
                "bank_status": "CREDITED",
            }
        )

    df_bank = (
        pd.DataFrame(bank_records)
        .sort_values("settlement_date_ist", kind="stable")
        .reset_index(drop=True)
    )

    # Check the data before writing any files.
    print("Checking the generated data...")

    assert len(df_orders) == TOTAL_ORDERS, (
        f"Expected {TOTAL_ORDERS} orders, found {len(df_orders)}."
    )
    print(f"[PASS] Order count: {len(df_orders):,}")

    assert df_orders["order_id"].is_unique, (
        "Duplicate order IDs found."
    )
    assert df_gateway["gateway_txn_id"].is_unique, (
        "Duplicate gateway transaction IDs found."
    )
    assert df_bank["bank_entry_id"].is_unique, (
        "Duplicate bank entry IDs found."
    )
    print("[PASS] IDs are unique in all three datasets.")

    successful_order_ids = set(
        df_orders.loc[
            df_orders["internal_status"] == "SUCCESS",
            "order_id",
        ]
    )
    gateway_order_ids = set(df_gateway["merchant_order_id"])

    assert successful_order_ids == gateway_order_ids, (
        "Successful orders and gateway records do not match."
    )
    print(
        f"[PASS] All {len(successful_order_ids):,} "
        "successful orders have gateway records."
    )

    failed_or_dropped = df_orders[
        df_orders["internal_status"].isin(["FAILED", "DROPPED"])
    ]

    invalid_gateway_orders = (
        set(failed_or_dropped["order_id"]) & gateway_order_ids
    )

    assert not invalid_gateway_orders, (
        "Failed or dropped orders have gateway records."
    )
    print(
        f"[PASS] No gateway records for "
        f"{len(failed_or_dropped):,} failed or dropped orders."
    )

    # Recalculate payouts and compare each batch with the bank statement.
    gateway_batch_totals = {}

    for _, row in df_gateway.iterrows():
        batch_id = row["payout_batch_id"]
        gross_amount = Decimal(str(row["gross_amount"]))
        mdr_rate = Decimal(str(row["mdr_rate_pct"])) / Decimal("100")

        fee = quantize_inr(gross_amount * mdr_rate)
        gst = quantize_inr(fee * Decimal("0.18"))
        net_payout = quantize_inr(gross_amount - fee - gst)

        assert net_payout == Decimal(str(row["net_payout"])), (
            f"Payout calculation mismatch for {row['gateway_txn_id']}."
        )

        gateway_batch_totals[batch_id] = (
            gateway_batch_totals.get(batch_id, Decimal("0.00"))
            + net_payout
        )

    bank_batch_totals = (
        df_bank.set_index("payout_batch_id")["credit_amount"].to_dict()
    )

    assert set(gateway_batch_totals) == set(bank_batch_totals), (
        "Gateway and bank payout batch IDs do not match."
    )

    for batch_id, gateway_total in gateway_batch_totals.items():
        bank_total = Decimal(str(bank_batch_totals[batch_id]))

        assert gateway_total == bank_total, (
            f"Payout total mismatch for {batch_id}: "
            f"gateway={gateway_total}, bank={bank_total}."
        )

    print(
        f"[PASS] All {len(gateway_batch_totals)} payout batches "
        "match the bank statement."
    )

    # Save the baseline only after all checks pass.
    df_orders.to_csv(
        BASELINE_DIR / "internal_orders.csv",
        index=False,
    )
    df_gateway.to_csv(
        BASELINE_DIR / "gateway_statement.csv",
        index=False,
    )
    df_bank.to_csv(
        BASELINE_DIR / "bank_statement.csv",
        index=False,
    )

    print(f"Clean baseline files saved to: {BASELINE_DIR}")


if __name__ == "__main__":
    generate_clean_baseline()