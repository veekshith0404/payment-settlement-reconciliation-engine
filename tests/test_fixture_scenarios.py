"""Assertions for the two edge cases added after the independent audit."""

from pathlib import Path
import unittest

import pandas as pd

from src.run_reconciliation import SHEET_NAMES


ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
TEST_DIR = ROOT_DIR / "data" / "test"


class FixtureScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orders = pd.read_csv(RAW_DIR / "internal_orders.csv")
        cls.gateway = pd.read_csv(RAW_DIR / "gateway_statement.csv")
        cls.ground_truth = pd.read_csv(TEST_DIR / "ground_truth_exceptions.csv")

    def test_success_order_with_non_captured_gateway_row_is_in_ground_truth(self):
        expected = self.ground_truth.loc[
            self.ground_truth["defect_type"] == "MISSING_GATEWAY_RECORD"
        ]
        self.assertEqual(len(expected), 14)

        retained = self.gateway.loc[
            self.gateway["merchant_order_id"].isin(expected["entity_id"])
        ]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained.iloc[0]["auth_status"], "AUTHORIZED")

        order_id = retained.iloc[0]["merchant_order_id"]
        order = self.orders.loc[self.orders["order_id"] == order_id].iloc[0]
        self.assertEqual(order["internal_status"], "SUCCESS")

    def test_failed_and_dropped_orders_with_captured_payments_are_in_ground_truth(self):
        expected = self.ground_truth.loc[
            self.ground_truth["defect_type"] == "INTERNAL_GATEWAY_STATUS_MISMATCH"
        ]
        self.assertEqual(len(expected), 2)

        joined = expected.merge(
            self.gateway[["gateway_txn_id", "merchant_order_id", "auth_status"]],
            left_on="entity_id",
            right_on="gateway_txn_id",
            how="left",
            validate="one_to_one",
        ).merge(
            self.orders[["order_id", "internal_status"]],
            left_on="merchant_order_id",
            right_on="order_id",
            how="left",
            validate="one_to_one",
        )
        self.assertEqual(set(joined["auth_status"]), {"CAPTURED"})
        self.assertEqual(set(joined["internal_status"]), {"FAILED", "DROPPED"})

    def test_each_ground_truth_category_has_a_valid_excel_sheet_name(self):
        categories = set(self.ground_truth["defect_type"])
        self.assertEqual(categories, set(SHEET_NAMES))
        names = list(SHEET_NAMES.values())
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(name) <= 31 for name in names))


if __name__ == "__main__":
    unittest.main()
