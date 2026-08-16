"""Structural readiness: enum vocabularies and typed errors are stable contracts."""

from __future__ import annotations

import unittest

from elly.domain.enums import (
    EpistemicStatus,
    ErrorClass,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import (
    EllyError,
    InputInvalidError,
    StorageFailureError,
)


class EnumStabilityTests(unittest.TestCase):
    def test_three_axis_status_values(self) -> None:
        self.assertEqual(
            {s.value for s in EpistemicStatus}, {"known", "inferred", "unknown", "blocked"}
        )
        self.assertEqual(
            {s.value for s in ValidationStatus}, {"validated", "qualified", "rejected"}
        )
        self.assertIn("completed", {s.value for s in TaskStatus})
        self.assertIn("blocked", {s.value for s in TaskStatus})

    def test_full_error_taxonomy_present(self) -> None:
        # The frozen taxonomy (DESIGN §6.8) must be complete even though M1 only
        # raises a subset.
        expected = {
            "INPUT_INVALID",
            "CONFIG_INVALID",
            "PERMISSION_DENIED",
            "LIMIT_EXCEEDED",
            "TRANSIENT_PROVIDER",
            "PERMANENT_PROVIDER",
            "TIMEOUT",
            "MALFORMED_RESULT",
            "UNSAFE_URL",
            "UNSUPPORTED_CONTENT",
            "STORAGE_FAILURE",
            "CANCELLED",
            "CONFLICT",
        }
        self.assertEqual({e.value for e in ErrorClass}, expected)


class TypedErrorTests(unittest.TestCase):
    def test_error_carries_class_and_safe_message(self) -> None:
        err = InputInvalidError("bad input")
        self.assertIs(err.error_class, ErrorClass.INPUT_INVALID)
        self.assertIn("INPUT_INVALID", str(err))
        self.assertEqual(err.summary, "bad input")

    def test_empty_summary_falls_back_to_class_name(self) -> None:
        err = StorageFailureError("   ")
        self.assertEqual(err.summary, ErrorClass.STORAGE_FAILURE.value)

    def test_errors_are_ellyerror(self) -> None:
        self.assertIsInstance(InputInvalidError("x"), EllyError)


if __name__ == "__main__":
    unittest.main()
