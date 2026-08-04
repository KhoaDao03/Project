"""Partial implementation: context builder + response validation (M1 Pair work)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from elly.domain.context import build_context
from elly.domain.enums import ValidationStatus
from elly.domain.models import Message
from elly.domain.validation import validate_generalist_text

UTC = datetime(2026, 8, 3, tzinfo=timezone.utc)


class ContextBuilderTests(unittest.TestCase):
    def test_includes_current_text_and_recent_history_within_window(self) -> None:
        history = [Message(role="user", content=f"m{i}", created_at=UTC) for i in range(5)]
        prompt, manifest = build_context(
            current_text="latest", history=history, window=3, reserved_output_tokens=100
        )
        self.assertIn("user: latest", prompt)
        # only last 3 history items included; 2 excluded as budget
        self.assertEqual(len(manifest.included_message_ids), 3)
        self.assertEqual(manifest.excluded_reason_counts.get("budget"), 2)
        self.assertEqual(manifest.reserved_output_tokens, 100)

    def test_no_store_empty_bodies_are_skipped(self) -> None:
        history = [Message(role="user", content="", created_at=UTC)]
        prompt, _ = build_context(
            current_text="q", history=history, window=5, reserved_output_tokens=10
        )
        # empty (redacted no-store) body must not appear as a blank "user: " line
        self.assertNotIn("user: \n", prompt + "\n")
        self.assertIn("user: q", prompt)


class ValidationTests(unittest.TestCase):
    def test_nonempty_validated(self) -> None:
        self.assertIs(validate_generalist_text("an answer"), ValidationStatus.VALIDATED)

    def test_empty_rejected(self) -> None:
        self.assertIs(validate_generalist_text("   "), ValidationStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
