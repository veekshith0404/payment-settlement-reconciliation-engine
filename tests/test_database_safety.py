"""Tests for explicit database-target configuration."""

import builtins
import os
import unittest
from unittest.mock import patch

from src.run_reconciliation import get_connection, main


class DatabaseSafetyTests(unittest.TestCase):
    def test_get_connection_rejects_unset_database_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PGDATABASE is not set"):
                get_connection()

    def test_reporter_checks_database_target_before_importing_driver(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                builtins,
                "__import__",
                side_effect=AssertionError("psycopg import should not be attempted"),
            ):
                self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
