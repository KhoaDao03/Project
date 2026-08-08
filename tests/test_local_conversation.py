"""Pure local-conversation use-case tests."""

from __future__ import annotations

import unittest

from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.application.local_conversation import LocalConversationUseCase
from elly.domain.errors import MalformedResultError, PermanentProviderError


class LocalConversationUseCaseTests(unittest.TestCase):
    def test_executes_and_validates_through_generalist_port(self) -> None:
        execution = LocalConversationUseCase(
            generalist=FakeGeneralist(), model_id="fake", max_output_tokens=32
        ).execute("hello")
        self.assertTrue(execution.text.startswith("[fake-generalist]"))

    def test_provider_failure_remains_typed(self) -> None:
        with self.assertRaises(PermanentProviderError):
            LocalConversationUseCase(
                generalist=FakeGeneralist(failure=FailureMode.PERMANENT),
                model_id="fake", max_output_tokens=32,
            ).execute("hello")

    def test_malformed_output_is_rejected(self) -> None:
        with self.assertRaises(MalformedResultError):
            LocalConversationUseCase(
                generalist=FakeGeneralist(failure=FailureMode.MALFORMED),
                model_id="fake", max_output_tokens=32,
            ).execute("hello")


if __name__ == "__main__":
    unittest.main()
