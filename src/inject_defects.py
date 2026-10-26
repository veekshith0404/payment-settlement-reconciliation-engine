"""Create controlled payment and settlement discrepancies for testing."""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 84
ROOT_DIR = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT_DIR / "data" / "baseline"
RAW_DIR = ROOT_DIR / "data" / "raw"
TEST_DIR = ROOT_DIR / "data" / "test"

CONTRACTED_MDR = {
    "UPI": Decimal("0.0000"),
    "DEBIT_CARD": Decimal("0.0090"),
    "CREDIT_CARD": Decimal("0.0180"),
    "NET_BANKING": Decimal("0.0150"),
}
GST_RATE = Decimal("0.18")

ORPHAN_GATEWAY_BATCH = "BATCH_20260801_C1"
ORPHAN_BANK_BATCH = "BATCH_20260802_C1"


def money(value: Decimal) -> Decimal:
    """Round an amount to two decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_business_days(start_date: date, business_days: int) -> date:
    """Add weekdays, skipping Saturday and Sunday."""
    current_date = start_date
    added = 0

    while added < business_days:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:
            added += 1

    return current_date


def file_hash(path: Path) -> str:
    """Calculate a file's SHA-256 hash."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            digest.update(chunk)

    return digest.hexdigest()


def add_ground_truth(
    records: list[dict],
    entity_type: str,
    entity_id: str,
    defect_type: str,
    expected_amount: Decimal | float,
    impact_basis: str,
    description: str,
) -> None:
    records.append(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "defect_type": defect_type,
            "expected_amount": float(
                money(Decimal(str(expected_amount)))
            ),
            "impact_basis": impact_basis,
            "description": description,
        }
    )


def main() -> None:
    rng = np.random.default_rng(SEED)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    baseline_paths = {
        name: BASELINE_DIR / name
        for name in (
            "internal_orders.csv",
            "gateway_statement.csv",
            "bank_statement.csv",
        )
    }

    for path in baseline_paths.values():
        if not path.is_file():
            raise FileNotFoundError(
                f"Baseline file not found: {path}. "
                "Run generate_baseline.py first."
            )

    hashes_before = {
        name: file_hash(path)
        for name, path in baseline_paths.items()
    }

    orders_base = pd.read_csv(baseline_paths["internal_orders.csv"])
    gateway_base = pd.read_csv(baseline_paths["gateway_statement.csv"])

    if orders_base.empty or gateway_base.empty:
        raise ValueError("A baseline dataset is empty.")

    orders_raw = orders_base.copy()
    gateway_raw = gateway_base.copy()
    ground_truth: list[dict] = []

    # Remove selected successful gateway records.
    missing_count = max(1, int(len(gateway_base) * 0.015))

    missing_order_ids = set(
        rng.choice(
            gateway_base["merchant_order_id"].to_numpy(),
            size=missing_count,
            replace=False,
        )
    )

    for order_id in sorted(missing_order_ids):
        order = orders_base.loc[
            orders_base["order_id"] == order_id
        ].iloc[0]

        add_ground_truth(
            ground_truth,
            "ORDER",
            order_id,
            "MISSING_GATEWAY_RECORD",
            order["amount"],
            "AMOUNT_UNDER_INVESTIGATION",
            "Internal order is SUCCESS but its gateway record is missing.",
        )

    gateway_raw = gateway_raw.loc[
        ~gateway_raw["merchant_order_id"].isin(missing_order_ids)
    ].copy()

    # Add a captured gateway transaction without an internal order.
    orphan_gross = Decimal("777.77")
    orphan_rate = CONTRACTED_MDR["CREDIT_CARD"]
    orphan_fee = money(orphan_gross * orphan_rate)
    orphan_gst = money(orphan_fee * GST_RATE)
    orphan_net = money(orphan_gross - orphan_fee - orphan_gst)
    orphan_gateway_id = "GTX_2026_ORPHAN001"

    gateway_raw = pd.concat(
        [
            gateway_raw,
            pd.DataFrame(
                [
                    {
                        "gateway_txn_id": orphan_gateway_id,
                        "merchant_order_id": "ORD_ORPHAN_0001",
                        "auth_status": "CAPTURED",
                        "capture_timestamp_utc": "2026-08-01 04:00:00",
                        "gross_amount": float(orphan_gross),
                        "mdr_rate_pct": float(orphan_rate * 100),
                        "fee_deducted": float(orphan_fee),
                        "gst": float(orphan_gst),
                        "net_payout": float(orphan_net),
                        "payout_batch_id": ORPHAN_GATEWAY_BATCH,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    add_ground_truth(
        ground_truth,
        "GATEWAY_TXN",
        orphan_gateway_id,
        "ORPHAN_GATEWAY_RECORD",
        orphan_gross,
        "ORPHAN_GATEWAY_TRANSACTION",
        "Captured gateway transaction has no matching internal order.",
    )

    all_batches = sorted(
        set(gateway_raw["payout_batch_id"])
        - {ORPHAN_GATEWAY_BATCH}
    )

    shuffled = list(
        rng.permutation(np.array(all_batches, dtype=object))
    )

    # Keep batch-level test scenarios separate.
    required_batches = 4 + 3 + 3 + 2 + 3 + 1

    if len(shuffled) < required_batches + 14:
        raise ValueError(
            "Not enough batches for the planned test scenarios."
        )

    position = 0

    lag_batches = set(shuffled[position:position + 4])
    position += 4

    duplicate_batches = set(shuffled[position:position + 3])
    position += 3

    missing_bank_batches = set(shuffled[position:position + 3])
    position += 3

    amount_mismatch_batches = list(shuffled[position:position + 2])
    position += 2

    noncredited_batches = list(shuffled[position:position + 3])
    position += 3

    split_batch = shuffled[position]

    special_batches = (
        lag_batches
        | duplicate_batches
        | missing_bank_batches
        | set(amount_mismatch_batches)
        | set(noncredited_batches)
        | {split_batch}
    )

    clean_batches = [
        batch
        for batch in all_batches
        if batch not in special_batches
    ]

    # Keep transaction-level tests in separate batches so each scenario is
    # independently testable.
    row_batches = list(
        rng.permutation(np.array(clean_batches, dtype=object))[:5]
    )

    (
        status_batch,
        order_amount_batch,
        net_payout_batch,
        noncaptured_batch,
        dropped_status_batch,
    ) = row_batches

    remaining_clean_batches = [
        batch
        for batch in clean_batches
        if batch not in set(row_batches)
    ]

    eligible_mdr_batches = []

    for batch in remaining_clean_batches:
        eligible = gateway_raw.loc[
            (gateway_raw["payout_batch_id"] == batch)
            & (gateway_raw["mdr_rate_pct"] < 1.0)
        ]

        if not eligible.empty:
            eligible_mdr_batches.append(batch)

    if len(eligible_mdr_batches) < 9:
        raise ValueError(
            "Not enough eligible batches for the MDR test cases."
        )

    mdr_batches = list(
        rng.choice(
            np.array(eligible_mdr_batches, dtype=object),
            size=9,
            replace=False,
        )
    )

    # Change one successful internal order to FAILED while its gateway row remains CAPTURED.
    status_candidates = gateway_raw.loc[
        gateway_raw["payout_batch_id"] == status_batch
    ].merge(
        orders_base[["order_id", "internal_status"]],
        left_on="merchant_order_id",
        right_on="order_id",
        how="left",
    )
    status_candidates = status_candidates.loc[
        status_candidates["internal_status"] == "SUCCESS"
    ]
    if status_candidates.empty:
        raise ValueError("No successful order is available for the FAILED status case.")
    status_row = status_candidates.iloc[0]

    status_txn_id = status_row["gateway_txn_id"]
    status_order_id = status_row["merchant_order_id"]

    orders_raw.loc[
        orders_raw["order_id"] == status_order_id,
        "internal_status",
    ] = "FAILED"

    add_ground_truth(
        ground_truth,
        "GATEWAY_TXN",
        status_txn_id,
        "INTERNAL_GATEWAY_STATUS_MISMATCH",
        status_row["gross_amount"],
        "STATUS_CONFLICT_FAILED",
        "Internal order is FAILED while the gateway transaction is CAPTURED.",
    )

    # Add a second status mismatch: DROPPED internally but CAPTURED at the gateway.
    dropped_candidates = gateway_raw.loc[
        gateway_raw["payout_batch_id"] == dropped_status_batch
    ].merge(
        orders_base[["order_id", "internal_status"]],
        left_on="merchant_order_id",
        right_on="order_id",
        how="left",
    )
    dropped_candidates = dropped_candidates.loc[
        dropped_candidates["internal_status"] == "SUCCESS"
    ]
    if dropped_candidates.empty:
        raise ValueError("No successful order is available for the DROPPED status case.")
    dropped_row = dropped_candidates.iloc[0]
    dropped_order_id = dropped_row["merchant_order_id"]
    orders_raw.loc[
        orders_raw["order_id"] == dropped_order_id,
        "internal_status",
    ] = "DROPPED"
    add_ground_truth(
        ground_truth,
        "GATEWAY_TXN",
        dropped_row["gateway_txn_id"],
        "INTERNAL_GATEWAY_STATUS_MISMATCH",
        dropped_row["gross_amount"],
        "STATUS_CONFLICT_DROPPED",
        "Internal order is DROPPED while the gateway transaction is CAPTURED.",
    )

    # A SUCCESS order with only a non-captured gateway row must be detected as
    # missing a captured gateway transaction, even though a gateway row exists.
    noncaptured_candidates = gateway_raw.loc[
        gateway_raw["payout_batch_id"] == noncaptured_batch
    ].merge(
        orders_base[["order_id", "internal_status"]],
        left_on="merchant_order_id",
        right_on="order_id",
        how="left",
    )
    noncaptured_candidates = noncaptured_candidates.loc[
        noncaptured_candidates["internal_status"] == "SUCCESS"
    ]
    if noncaptured_candidates.empty:
        raise ValueError("No successful order is available for the non-captured gateway case.")
    noncaptured_row = noncaptured_candidates.iloc[0]
    noncaptured_index = gateway_raw.index[
        gateway_raw["gateway_txn_id"] == noncaptured_row["gateway_txn_id"]
    ][0]
    gateway_raw.loc[noncaptured_index, "auth_status"] = "AUTHORIZED"
    noncaptured_order_id = noncaptured_row["merchant_order_id"]
    noncaptured_amount = orders_base.loc[
        orders_base["order_id"] == noncaptured_order_id, "amount"
    ].iloc[0]
    add_ground_truth(
        ground_truth,
        "ORDER",
        noncaptured_order_id,
        "MISSING_GATEWAY_RECORD",
        noncaptured_amount,
        "NO_CAPTURED_GATEWAY_TRANSACTION",
        "Internal order is SUCCESS but its only gateway transaction is AUTHORIZED, not CAPTURED.",
    )

    # Change one gross amount and recalculate its fee components.
    amount_index = gateway_raw.index[
        gateway_raw["payout_batch_id"] == order_amount_batch
    ][0]

    amount_row = gateway_raw.loc[amount_index]

    related_order = orders_base.loc[
        orders_base["order_id"] == amount_row["merchant_order_id"]
    ].iloc[0]

    order_amount = money(Decimal(str(related_order["amount"])))

    changed_gross = money(
        Decimal(str(amount_row["gross_amount"])) + Decimal("25.00")
    )

    rate = CONTRACTED_MDR[related_order["payment_method"]]
    changed_fee = money(changed_gross * rate)
    changed_gst = money(changed_fee * GST_RATE)
    changed_net = money(changed_gross - changed_fee - changed_gst)

    gateway_raw.loc[amount_index, "gross_amount"] = float(changed_gross)
    gateway_raw.loc[amount_index, "mdr_rate_pct"] = float(rate * 100)
    gateway_raw.loc[amount_index, "fee_deducted"] = float(changed_fee)
    gateway_raw.loc[amount_index, "gst"] = float(changed_gst)
    gateway_raw.loc[amount_index, "net_payout"] = float(changed_net)

    add_ground_truth(
        ground_truth,
        "GATEWAY_TXN",
        amount_row["gateway_txn_id"],
        "ORDER_GATEWAY_AMOUNT_MISMATCH",
        abs(changed_gross - order_amount),
        "ORDER_AMOUNT_DIFFERENCE",
        "Gateway gross amount differs from the internal order amount.",
    )

    # Change one net payout without changing its fee components.
    net_index = gateway_raw.index[
        gateway_raw["payout_batch_id"] == net_payout_batch
    ][0]

    net_row = gateway_raw.loc[net_index]

    changed_net_payout = money(
        Decimal(str(net_row["net_payout"])) - Decimal("7.00")
    )

    if changed_net_payout < 0:
        raise ValueError(
            "The selected payout is too small for the test."
        )

    gateway_raw.loc[net_index, "net_payout"] = float(changed_net_payout)

    calculated_net = money(
        Decimal(str(net_row["gross_amount"]))
        - Decimal(str(net_row["fee_deducted"]))
        - Decimal(str(net_row["gst"]))
    )

    add_ground_truth(
        ground_truth,
        "GATEWAY_TXN",
        net_row["gateway_txn_id"],
        "GATEWAY_NET_PAYOUT_MISMATCH",
        abs(changed_net_payout - calculated_net),
        "GATEWAY_ARITHMETIC_DIFFERENCE",
        "Stored net payout differs from gross less fee and GST.",
    )

    # Increase the MDR on nine transactions in separate batches.
    for batch in mdr_batches:
        eligible = gateway_raw.loc[
            (gateway_raw["payout_batch_id"] == batch)
            & (gateway_raw["mdr_rate_pct"] < 1.0)
        ]

        row_index = eligible.index[0]
        row = gateway_raw.loc[row_index]

        gross = Decimal(str(row["gross_amount"]))
        original_rate_pct = Decimal(str(row["mdr_rate_pct"]))
        original_rate = original_rate_pct / Decimal("100")

        correct_fee = money(gross * original_rate)
        correct_gst = money(correct_fee * GST_RATE)

        inflated_rate = Decimal("0.0180")
        inflated_fee = money(gross * inflated_rate)
        inflated_gst = money(inflated_fee * GST_RATE)
        inflated_net = money(gross - inflated_fee - inflated_gst)

        excess = money(
            (inflated_fee - correct_fee)
            + (inflated_gst - correct_gst)
        )

        gateway_raw.loc[row_index, "mdr_rate_pct"] = float(
            inflated_rate * 100
        )
        gateway_raw.loc[row_index, "fee_deducted"] = float(inflated_fee)
        gateway_raw.loc[row_index, "gst"] = float(inflated_gst)
        gateway_raw.loc[row_index, "net_payout"] = float(inflated_net)

        add_ground_truth(
            ground_truth,
            "GATEWAY_TXN",
            row["gateway_txn_id"],
            "MDR_OVERCHARGE",
            excess,
            "FEE_AND_TAX_OVERCHARGE",
            f"Actual fee and GST exceed the contracted rate of {original_rate_pct}%.",
        )

    bank_records = []
    bank_sequence = 80001

    bank_status_by_batch = dict(
        zip(noncredited_batches, ["FAILED", "HOLD", "REVERSED"])
    )

    captured_gateway = gateway_raw.loc[
        gateway_raw["auth_status"] == "CAPTURED"
    ]
    for batch_id, group in captured_gateway.groupby("payout_batch_id"):
        # The orphan gateway batch receives its bank credit separately below.
        if batch_id == ORPHAN_GATEWAY_BATCH:
            continue

        expected_payout = money(
            sum(Decimal(str(value)) for value in group["net_payout"])
        )

        batch_date = datetime.strptime(
            batch_id.split("_")[1],
            "%Y%m%d",
        ).date()

        if batch_id in missing_bank_batches:
            add_ground_truth(
                ground_truth,
                "PAYOUT_BATCH",
                batch_id,
                "MISSING_BANK_SETTLEMENT",
                expected_payout,
                "UNMATCHED_EXPECTED_PAYOUT",
                "Gateway payout batch has no bank entry.",
            )
            continue

        if batch_id in lag_batches:
            lag_days = int(rng.integers(3, 7))
            settlement_date = add_business_days(batch_date, lag_days)

            add_ground_truth(
                ground_truth,
                "PAYOUT_BATCH",
                batch_id,
                "SETTLEMENT_TIMING_LAG",
                expected_payout,
                "DELAYED_FUNDS",
                f"Bank payout arrived at T+{lag_days} business days instead of T+1.",
            )
        else:
            settlement_date = add_business_days(batch_date, 1)

        date_text = settlement_date.strftime("%Y-%m-%d")

        entry_id = (
            f"UTR_TEST_{settlement_date:%Y%m%d}_{bank_sequence}"
        )
        bank_sequence += 1

        # Failed, held and reversed entries are not credited settlements.
        if batch_id in noncredited_batches:
            status = bank_status_by_batch[batch_id]

            bank_records.append(
                {
                    "bank_entry_id": entry_id,
                    "payout_batch_id": batch_id,
                    "credit_amount": float(expected_payout),
                    "settlement_date_ist": date_text,
                    "bank_status": status,
                }
            )

            add_ground_truth(
                ground_truth,
                "BANK_ENTRY",
                entry_id,
                "NON_CREDITED_BANK_ENTRY",
                expected_payout,
                "NON_CREDITED_SETTLEMENT",
                f"Bank entry has status {status}, not CREDITED.",
            )
            continue

        # Test one short credit and one excessive credit.
        if batch_id in amount_mismatch_batches:
            adjustment = (
                Decimal("-5.00")
                if batch_id == amount_mismatch_batches[0]
                else Decimal("5.00")
            )

            credited_amount = money(expected_payout + adjustment)

            bank_records.append(
                {
                    "bank_entry_id": entry_id,
                    "payout_batch_id": batch_id,
                    "credit_amount": float(credited_amount),
                    "settlement_date_ist": date_text,
                    "bank_status": "CREDITED",
                }
            )

            add_ground_truth(
                ground_truth,
                "PAYOUT_BATCH",
                batch_id,
                "BANK_SETTLEMENT_AMOUNT_MISMATCH",
                abs(adjustment),
                "BANK_CREDIT_DIFFERENCE",
                "Credited bank total is short or excessive versus the expected payout.",
            )
            continue

        # Two legitimate split credits should sum to the expected payout.
        if batch_id == split_batch:
            first_credit = money(expected_payout / Decimal("2"))
            second_credit = expected_payout - first_credit

            for amount in (first_credit, second_credit):
                split_entry_id = (
                    f"UTR_TEST_{settlement_date:%Y%m%d}_{bank_sequence}"
                )
                bank_sequence += 1

                bank_records.append(
                    {
                        "bank_entry_id": split_entry_id,
                        "payout_batch_id": batch_id,
                        "credit_amount": float(amount),
                        "settlement_date_ist": date_text,
                        "bank_status": "CREDITED",
                    }
                )

            continue

        bank_records.append(
            {
                "bank_entry_id": entry_id,
                "payout_batch_id": batch_id,
                "credit_amount": float(expected_payout),
                "settlement_date_ist": date_text,
                "bank_status": "CREDITED",
            }
        )

        # A duplicate batch receives a second full credit.
        if batch_id in duplicate_batches:
            duplicate_id = (
                f"UTR_TEST_{settlement_date:%Y%m%d}_{bank_sequence}_DUP"
            )
            bank_sequence += 1

            bank_records.append(
                {
                    "bank_entry_id": duplicate_id,
                    "payout_batch_id": batch_id,
                    "credit_amount": float(expected_payout),
                    "settlement_date_ist": date_text,
                    "bank_status": "CREDITED",
                }
            )

            add_ground_truth(
                ground_truth,
                "PAYOUT_BATCH",
                batch_id,
                "DUPLICATE_BANK_CREDIT",
                expected_payout,
                "POTENTIAL_OVER_CREDIT",
                "Two full bank credits were recorded for one payout batch.",
            )

    # Add one credited bank entry for the orphan gateway batch.
    orphan_settlement_date = add_business_days(date(2026, 8, 1), 1)

    bank_records.append(
        {
            "bank_entry_id": "UTR_ORPHAN_GATEWAY_SETTLEMENT",
            "payout_batch_id": ORPHAN_GATEWAY_BATCH,
            "credit_amount": float(orphan_net),
            "settlement_date_ist": orphan_settlement_date.strftime("%Y-%m-%d"),
            "bank_status": "CREDITED",
        }
    )

    # Add a credited bank batch without a gateway payout.
    orphan_bank_amount = Decimal("321.45")

    bank_records.append(
        {
            "bank_entry_id": "UTR_ORPHAN_BANK_001",
            "payout_batch_id": ORPHAN_BANK_BATCH,
            "credit_amount": float(orphan_bank_amount),
            "settlement_date_ist": add_business_days(
                date(2026, 8, 2), 1
            ).strftime("%Y-%m-%d"),
            "bank_status": "CREDITED",
        }
    )

    add_ground_truth(
        ground_truth,
        "PAYOUT_BATCH",
        ORPHAN_BANK_BATCH,
        "ORPHAN_BANK_CREDIT",
        orphan_bank_amount,
        "ORPHAN_BANK_DEPOSIT",
        "Credited bank batch has no matching captured gateway payout.",
    )

    bank_raw = (
        pd.DataFrame(bank_records)
        .sort_values("settlement_date_ist", kind="stable")
        .reset_index(drop=True)
    )

    ground_truth_df = pd.DataFrame(ground_truth)

    outputs = {
        RAW_DIR / "internal_orders.csv": orders_raw,
        RAW_DIR / "gateway_statement.csv": gateway_raw,
        RAW_DIR / "bank_statement.csv": bank_raw,
        TEST_DIR / "ground_truth_exceptions.csv": ground_truth_df,
    }

    for path, dataframe in outputs.items():
        dataframe.to_csv(path, index=False)

    verify_saved_data(hashes_before)

    print("\nAll checks passed.")
    print(f"Raw orders: {len(orders_raw):,}")
    print(f"Raw gateway records: {len(gateway_raw):,}")
    print(f"Raw bank entries: {len(bank_raw):,}")
    print(f"Ground-truth exceptions: {len(ground_truth_df):,}")
    print(
        ground_truth_df.groupby("defect_type")
        .size()
        .sort_index()
        .to_string()
    )


def verify_saved_data(hashes_before: dict[str, str]) -> None:
    """Check that the saved datasets match the expected test cases."""
    for name, original_hash in hashes_before.items():
        if file_hash(BASELINE_DIR / name) != original_hash:
            raise AssertionError(f"Baseline file changed: {name}")

    orders_base = pd.read_csv(BASELINE_DIR / "internal_orders.csv")
    gateway_base = pd.read_csv(BASELINE_DIR / "gateway_statement.csv")
    orders_raw = pd.read_csv(RAW_DIR / "internal_orders.csv")
    gateway_raw = pd.read_csv(RAW_DIR / "gateway_statement.csv")
    bank_raw = pd.read_csv(RAW_DIR / "bank_statement.csv")
    ground_truth = pd.read_csv(TEST_DIR / "ground_truth_exceptions.csv")

    if not orders_raw["order_id"].is_unique:
        raise AssertionError("Internal order IDs are not unique.")

    if not gateway_raw["gateway_txn_id"].is_unique:
        raise AssertionError("Gateway transaction IDs are not unique.")

    if not bank_raw["bank_entry_id"].is_unique:
        raise AssertionError("Bank entry IDs are not unique.")

    if ground_truth.duplicated(["defect_type", "entity_id"]).any():
        raise AssertionError("Ground-truth exception keys are not unique.")

    expected_counts = {
        "MISSING_GATEWAY_RECORD": 14,
        "MDR_OVERCHARGE": 9,
        "SETTLEMENT_TIMING_LAG": 4,
        "DUPLICATE_BANK_CREDIT": 3,
        "MISSING_BANK_SETTLEMENT": 3,
        "BANK_SETTLEMENT_AMOUNT_MISMATCH": 2,
        "NON_CREDITED_BANK_ENTRY": 3,
        "ORPHAN_GATEWAY_RECORD": 1,
        "ORPHAN_BANK_CREDIT": 1,
        "INTERNAL_GATEWAY_STATUS_MISMATCH": 2,
        "ORDER_GATEWAY_AMOUNT_MISMATCH": 1,
        "GATEWAY_NET_PAYOUT_MISMATCH": 1,
    }

    actual_counts = ground_truth.groupby("defect_type").size().to_dict()

    if actual_counts != expected_counts:
        raise AssertionError(
            f"Unexpected ground-truth counts: {actual_counts}"
        )

    # Confirm that only the intended gateway records are missing.
    expected_missing = set(
        ground_truth.loc[
            ground_truth["defect_type"] == "MISSING_GATEWAY_RECORD",
            "entity_id",
        ]
    )

    captured_order_ids = set(
        gateway_raw.loc[
            gateway_raw["auth_status"] == "CAPTURED", "merchant_order_id"
        ]
    )
    actual_missing = set(gateway_base["merchant_order_id"]) - captured_order_ids

    if expected_missing != actual_missing:
        raise AssertionError(
            "Missing-gateway IDs do not match ground truth."
        )

    # Exactly one MISSING_GATEWAY_RECORD case deliberately retains a gateway
    # row with a non-captured status; all other such cases have no gateway row.
    missing_order_ids = expected_missing
    gateway_rows_for_missing = gateway_raw.loc[
        gateway_raw["merchant_order_id"].isin(missing_order_ids)
    ]
    retained_non_capture = gateway_rows_for_missing.loc[
        gateway_rows_for_missing["auth_status"] != "CAPTURED"
    ]
    if len(retained_non_capture) != 1 or len(gateway_rows_for_missing) != 1:
        raise AssertionError(
            "Expected exactly one missing-capture case with a non-captured gateway row."
        )

    order_ids = set(orders_raw["order_id"])

    for _, record in ground_truth.iterrows():
        defect_type = record["defect_type"]
        entity_id = record["entity_id"]
        expected_amount = money(Decimal(str(record["expected_amount"])))

        if defect_type == "MISSING_GATEWAY_RECORD":
            order = orders_base.loc[
                orders_base["order_id"] == entity_id
            ].iloc[0]

            if order["internal_status"] != "SUCCESS":
                raise AssertionError(
                    f"Order is not successful: {entity_id}"
                )

            captured_for_order = gateway_raw.loc[
                (gateway_raw["merchant_order_id"] == entity_id)
                & (gateway_raw["auth_status"] == "CAPTURED")
            ]
            if not captured_for_order.empty:
                raise AssertionError(
                    f"Captured gateway record still exists: {entity_id}"
                )

            if money(Decimal(str(order["amount"]))) != expected_amount:
                raise AssertionError(
                    f"Order amount differs: {entity_id}"
                )

        elif defect_type == "MDR_OVERCHARGE":
            base = gateway_base.loc[
                gateway_base["gateway_txn_id"] == entity_id
            ].iloc[0]

            raw = gateway_raw.loc[
                gateway_raw["gateway_txn_id"] == entity_id
            ].iloc[0]

            order = orders_base.loc[
                orders_base["order_id"] == base["merchant_order_id"]
            ].iloc[0]

            gross = Decimal(str(base["gross_amount"]))
            rate = CONTRACTED_MDR[order["payment_method"]]

            correct_fee = money(gross * rate)
            correct_gst = money(correct_fee * GST_RATE)

            actual_fee = money(Decimal(str(raw["fee_deducted"])))
            actual_gst = money(Decimal(str(raw["gst"])))

            excess = money(
                actual_fee + actual_gst - correct_fee - correct_gst
            )

            if excess != expected_amount or excess <= 0:
                raise AssertionError(
                    f"MDR amount differs: {entity_id}"
                )

        elif defect_type == "SETTLEMENT_TIMING_LAG":
            batch_date = datetime.strptime(
                entity_id.split("_")[1], "%Y%m%d"
            ).date()

            deadline = add_business_days(batch_date, 1)

            rows = bank_raw.loc[
                (bank_raw["payout_batch_id"] == entity_id)
                & (bank_raw["bank_status"] == "CREDITED")
            ]

            if rows.empty:
                raise AssertionError(
                    f"No credited row for {entity_id}"
                )

            actual_date = datetime.strptime(
                rows["settlement_date_ist"].max(), "%Y-%m-%d"
            ).date()

            if actual_date <= deadline:
                raise AssertionError(
                    f"Settlement is not late: {entity_id}"
                )

        elif defect_type == "DUPLICATE_BANK_CREDIT":
            rows = bank_raw.loc[
                (bank_raw["payout_batch_id"] == entity_id)
                & (bank_raw["bank_status"] == "CREDITED")
            ]

            payout = money(
                sum(
                    Decimal(str(value))
                    for value in gateway_raw.loc[
                        (gateway_raw["payout_batch_id"] == entity_id)
                        & (gateway_raw["auth_status"] == "CAPTURED"),
                        "net_payout",
                    ]
                )
            )

            credited = money(
                sum(Decimal(str(value)) for value in rows["credit_amount"])
            )

            if len(rows) != 2 or credited <= payout:
                raise AssertionError(
                    f"Invalid duplicate batch: {entity_id}"
                )

            if money(credited - payout) != expected_amount:
                raise AssertionError(
                    f"Duplicate amount differs: {entity_id}"
                )

        elif defect_type == "MISSING_BANK_SETTLEMENT":
            gateway_rows = gateway_raw.loc[
                gateway_raw["payout_batch_id"] == entity_id
            ]

            bank_rows = bank_raw.loc[
                bank_raw["payout_batch_id"] == entity_id
            ]

            payout = money(
                sum(
                    Decimal(str(value))
                    for value in gateway_rows.loc[
                        gateway_rows["auth_status"] == "CAPTURED", "net_payout"
                    ]
                )
            )

            if gateway_rows.empty or not bank_rows.empty:
                raise AssertionError(
                    f"Invalid missing-settlement batch: {entity_id}"
                )

            if payout != expected_amount:
                raise AssertionError(
                    f"Missing-settlement amount differs: {entity_id}"
                )

        elif defect_type == "BANK_SETTLEMENT_AMOUNT_MISMATCH":
            payout = money(
                sum(
                    Decimal(str(value))
                    for value in gateway_raw.loc[
                        (gateway_raw["payout_batch_id"] == entity_id)
                        & (gateway_raw["auth_status"] == "CAPTURED"),
                        "net_payout",
                    ]
                )
            )

            credits = bank_raw.loc[
                (bank_raw["payout_batch_id"] == entity_id)
                & (bank_raw["bank_status"] == "CREDITED"),
                "credit_amount",
            ]

            credited = money(
                sum(Decimal(str(value)) for value in credits)
            )

            if (
                credited == payout
                or money(abs(credited - payout)) != expected_amount
            ):
                raise AssertionError(
                    f"Settlement amount differs: {entity_id}"
                )

        elif defect_type == "NON_CREDITED_BANK_ENTRY":
            bank_row = bank_raw.loc[
                bank_raw["bank_entry_id"] == entity_id
            ]

            if (
                bank_row.empty
                or bank_row.iloc[0]["bank_status"] == "CREDITED"
            ):
                raise AssertionError(
                    f"Non-credited entry not found: {entity_id}"
                )

        elif defect_type == "ORPHAN_BANK_CREDIT":
            rows = bank_raw.loc[
                (bank_raw["payout_batch_id"] == entity_id)
                & (bank_raw["bank_status"] == "CREDITED")
            ]

            if rows.empty or entity_id in set(
                gateway_raw["payout_batch_id"]
            ):
                raise AssertionError(
                    f"Invalid orphan bank batch: {entity_id}"
                )

            amount = money(
                sum(Decimal(str(value)) for value in rows["credit_amount"])
            )

            if amount != expected_amount:
                raise AssertionError(
                    f"Orphan-bank amount differs: {entity_id}"
                )

        elif defect_type == "INTERNAL_GATEWAY_STATUS_MISMATCH":
            gateway_row = gateway_raw.loc[
                gateway_raw["gateway_txn_id"] == entity_id
            ].iloc[0]

            order = orders_raw.loc[
                orders_raw["order_id"] == gateway_row["merchant_order_id"]
            ].iloc[0]

            if (
                order["internal_status"] not in {"FAILED", "DROPPED"}
                or gateway_row["auth_status"] != "CAPTURED"
            ):
                raise AssertionError(
                    f"Invalid status mismatch: {entity_id}"
                )

            if (
                money(Decimal(str(gateway_row["gross_amount"])))
                != expected_amount
            ):
                raise AssertionError(
                    f"Status-mismatch amount differs: {entity_id}"
                )

        elif defect_type == "ORDER_GATEWAY_AMOUNT_MISMATCH":
            gateway_row = gateway_raw.loc[
                gateway_raw["gateway_txn_id"] == entity_id
            ].iloc[0]

            order = orders_base.loc[
                orders_base["order_id"] == gateway_row["merchant_order_id"]
            ].iloc[0]

            difference = money(
                abs(
                    Decimal(str(gateway_row["gross_amount"]))
                    - Decimal(str(order["amount"]))
                )
            )

            if difference != expected_amount:
                raise AssertionError(
                    f"Order/gateway amount differs: {entity_id}"
                )

        elif defect_type == "GATEWAY_NET_PAYOUT_MISMATCH":
            gateway_row = gateway_raw.loc[
                gateway_raw["gateway_txn_id"] == entity_id
            ].iloc[0]

            calculated = money(
                Decimal(str(gateway_row["gross_amount"]))
                - Decimal(str(gateway_row["fee_deducted"]))
                - Decimal(str(gateway_row["gst"]))
            )

            difference = money(
                abs(
                    Decimal(str(gateway_row["net_payout"])) - calculated
                )
            )

            if difference != expected_amount:
                raise AssertionError(
                    f"Net-payout mismatch: {entity_id}"
                )

        elif defect_type == "ORPHAN_GATEWAY_RECORD":
            gateway_row = gateway_raw.loc[
                gateway_raw["gateway_txn_id"] == entity_id
            ].iloc[0]

            if gateway_row["merchant_order_id"] in order_ids:
                raise AssertionError(
                    f"Gateway has an internal order: {entity_id}"
                )

            if (
                money(Decimal(str(gateway_row["gross_amount"])))
                != expected_amount
            ):
                raise AssertionError(
                    f"Orphan-gateway amount differs: {entity_id}"
                )

    # Only the two intended internal order statuses should have changed.
    status_cases = ground_truth.loc[
        ground_truth["defect_type"] == "INTERNAL_GATEWAY_STATUS_MISMATCH"
    ]
    expected_orders = orders_base.copy()

    for _, status_case in status_cases.iterrows():
        status_gateway = gateway_raw.loc[
            gateway_raw["gateway_txn_id"] == status_case["entity_id"]
        ].iloc[0]
        expected_status = (
            "DROPPED"
            if status_case["impact_basis"] == "STATUS_CONFLICT_DROPPED"
            else "FAILED"
        )
        expected_orders.loc[
            expected_orders["order_id"] == status_gateway["merchant_order_id"],
            "internal_status",
        ] = expected_status

    pd.testing.assert_frame_equal(expected_orders, orders_raw)

    print("[PASS] Baseline files remain unchanged.")
    print("[PASS] IDs, categories, and ground-truth amounts were checked.")


if __name__ == "__main__":
    main()