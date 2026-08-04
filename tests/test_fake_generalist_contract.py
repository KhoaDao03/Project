"""Contract + fake behavior: FakeGeneralist obeys GeneralistPort deterministically.

These tests define what the REAL Ollama adapter (M2) must also satisfy for the
success/failure surface, so the fake can be swapped without touching callers.
"""

from __future__ import annotations

import unittest

from elly.adapters.fake_generalist import FailureMode, FakeGeneralist
from elly.domain.enums import HealthState
from elly.domain.errors import (
    MalformedResultError,
    PermanentProviderError,
    TransientProviderError,
)
from elly.domain.models import GeneralistRequest
from elly.ports.generalist import GeneralistPort


def _req(prompt: str = "hello") -> GeneralistRequest:
    return GeneralistRequest(prompt=prompt, model_id="fake-generalist-v1", max_output_tokens=64)


class FakeGeneralistContractTests(unittest.TestCase):
    def test_satisfies_port_protocol(self) -> None:
        self.assertIsInstance(FakeGeneralist(), GeneralistPort)

    def test_healthy_by_default(self) -> None:
        self.assertIs(FakeGeneralist().health().state, HealthState.HEALTHY)

    def test_deterministic_output(self) -> None:
        fake = FakeGeneralist()
        first = fake.generate(_req("same prompt"))
        second = fake.generate(_req("same prompt"))
        self.assertEqual(first.text, second.text)
        self.assertTrue(first.text.startswith("[fake-generalist]"))

    def test_no_network_no_state_between_instances(self) -> None:
        a = FakeGeneralist().generate(_req("x")).text
        b = FakeGeneralist().generate(_req("x")).text
        self.assertEqual(a, b)  # no hidden mutable global state


class FakeGeneralistFailureTests(unittest.TestCase):
    def test_transient_failure(self) -> None:
        with self.assertRaises(TransientProviderError):
            FakeGeneralist(failure=FailureMode.TRANSIENT).generate(_req())

    def test_permanent_failure(self) -> None:
        with self.assertRaises(PermanentProviderError):
            FakeGeneralist(failure=FailureMode.PERMANENT).generate(_req())

    def test_malformed_result(self) -> None:
        with self.assertRaises(MalformedResultError):
            FakeGeneralist(failure=FailureMode.MALFORMED).generate(_req())

    def test_unhealthy_reported_not_raised(self) -> None:
        self.assertIs(
            FakeGeneralist(failure=FailureMode.UNHEALTHY).health().state,
            HealthState.UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()
