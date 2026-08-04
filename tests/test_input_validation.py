"""Security-sensitive defaults: input validation before any model call (FR-001)."""

from __future__ import annotations

import unicodedata
import unittest

from elly.domain.errors import InputInvalidError
from elly.presentation.validators import normalize_and_validate


class InputValidationTests(unittest.TestCase):
    def test_empty_rejected(self) -> None:
        with self.assertRaises(InputInvalidError):
            normalize_and_validate("", max_chars=100)

    def test_whitespace_only_rejected(self) -> None:
        with self.assertRaises(InputInvalidError):
            normalize_and_validate("   \t\n", max_chars=100)

    def test_oversized_rejected_and_names_limit(self) -> None:
        with self.assertRaises(InputInvalidError) as ctx:
            normalize_and_validate("x" * 101, max_chars=100)
        self.assertIn("100", ctx.exception.summary)

    def test_normalizes_unicode_nfc(self) -> None:
        decomposed = "e" + "́"  # e + combining acute
        out = normalize_and_validate(decomposed, max_chars=100)
        self.assertEqual(out, unicodedata.normalize("NFC", decomposed))
        self.assertEqual(len(out), 1)

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(normalize_and_validate("  hi  ", max_chars=100), "hi")


if __name__ == "__main__":
    unittest.main()
