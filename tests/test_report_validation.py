"""Tests for comparing detected exceptions with expected results."""

import unittest

import pandas as pd

from src.run_reconciliation import build_validation


class BuildValidationTests(unittest.TestCase):
    def test_detects_matches_false_positives_false_negatives_and_amount_differences(
        self,
    ):
        ground_truth = pd.DataFrame(
            [
                {
                    "defect_type": "MISSING_GATEWAY_RECORD",
                    "entity_id": "ORD-1",
                    "expected_amount": 100.00,
                },
                {
                    "defect_type": "MDR_OVERCHARGE",
                    "entity_id": "GTX-2",
                    "expected_amount": 5.00,
                },
                {
                    "defect_type": "MISSING_BANK_SETTLEMENT",
                    "entity_id": "BATCH-3",
                    "expected_amount": 25.00,
                },
            ]
        )

        detected = pd.DataFrame(
            [
                {
                    "defect_type": "MISSING_GATEWAY_RECORD",
                    "entity_id": "ORD-1",
                    "amount_under_review": 100.00,
                },
                {
                    "defect_type": "MDR_OVERCHARGE",
                    "entity_id": "GTX-2",
                    "amount_under_review": 4.99,
                },
                {
                    "defect_type": "DUPLICATE_BANK_CREDIT",
                    "entity_id": "BATCH-EXTRA",
                    "amount_under_review": 3.00,
                },
            ]
        )

        summary, comparison = build_validation(detected, ground_truth)
        by_type = summary.set_index("defect_type")

        self.assertEqual(
            int(by_type.loc["MISSING_GATEWAY_RECORD", "matched_cases"]),
            1,
        )
        self.assertEqual(
            int(by_type.loc["MISSING_GATEWAY_RECORD", "amount_mismatches"]),
            0,
        )
        self.assertEqual(
            int(by_type.loc["MDR_OVERCHARGE", "amount_mismatches"]),
            1,
        )
        self.assertEqual(
            int(by_type.loc["MISSING_BANK_SETTLEMENT", "false_negatives"]),
            1,
        )
        self.assertEqual(
            int(by_type.loc["DUPLICATE_BANK_CREDIT", "false_positives"]),
            1,
        )
        self.assertEqual(len(comparison), 4)

    def test_perfect_match_has_100_percent_precision_and_recall(self):
        ground_truth = pd.DataFrame(
            [
                {
                    "defect_type": "MISSING_GATEWAY_RECORD",
                    "entity_id": "ORD-1",
                    "expected_amount": 12.34,
                }
            ]
        )

        detected = pd.DataFrame(
            [
                {
                    "defect_type": "MISSING_GATEWAY_RECORD",
                    "entity_id": "ORD-1",
                    "amount_under_review": 12.34,
                }
            ]
        )

        summary, _ = build_validation(detected, ground_truth)
        result = summary.iloc[0]

        self.assertEqual(result["precision_pct"], 100.0)
        self.assertEqual(result["recall_pct"], 100.0)
        self.assertEqual(int(result["amount_mismatches"]), 0)

    def test_duplicate_validation_keys_raise_clear_value_error(self):
        ground_truth = pd.DataFrame(
            [
                {"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "expected_amount": 1.00},
                {"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "expected_amount": 1.00},
            ]
        )
        detected = pd.DataFrame(
            [{"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "amount_under_review": 1.00}]
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_validation(detected, ground_truth)

    def test_null_matched_amount_is_counted_as_amount_mismatch(self):
        ground_truth = pd.DataFrame(
            [{"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "expected_amount": 1.00}]
        )
        detected = pd.DataFrame(
            [{"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "amount_under_review": None}]
        )

        summary, comparison = build_validation(detected, ground_truth)

        self.assertEqual(int(summary.iloc[0]["matched_cases"]), 1)
        self.assertEqual(int(summary.iloc[0]["amount_mismatches"]), 1)
        self.assertFalse(bool(comparison.iloc[0]["amount_match"]))

    def test_duplicate_detected_keys_raise_clear_value_error(self):
        ground_truth = pd.DataFrame(
            [{"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "expected_amount": 1.00}]
        )
        detected = pd.DataFrame(
            [
                {"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "amount_under_review": 1.00},
                {"defect_type": "MDR_OVERCHARGE", "entity_id": "GTX-1", "amount_under_review": 1.00},
            ]
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_validation(detected, ground_truth)


if __name__ == "__main__":
    unittest.main()