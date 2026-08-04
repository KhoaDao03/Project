from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from elly.domain.errors import ConfigInvalidError
from elly.specialists.manifest import SpecialistManifest
from elly.specialists.registry import SpecialistRegistry


class SpecialistRegistryTests(unittest.TestCase):
    def test_discovers_valid_manifest_without_enabling_execution(self) -> None:
        registry = SpecialistRegistry.from_directory("config/specialists")
        manifest = registry.get("stock_analysis")
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest.preferred_runtime, "cloud")
        self.assertEqual(manifest.timeout_seconds, 90)

    def test_invalid_manifest_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text("[specialist]\nid='Bad ID'\n", encoding="utf-8")
            registry = SpecialistRegistry.from_directory(directory)
            self.assertEqual(registry.enabled(), ())
            self.assertEqual(registry.disabled()[0].id, "bad")

    def test_duplicate_registration_is_rejected(self) -> None:
        manifest = SpecialistManifest(
            id="coding_review", version="1.0", description="Code review",
            capabilities=frozenset({"code_review"}), accepted_inputs=frozenset({"text"}),
            requires_current_data=False, preferred_runtime="local", risk_level="low",
            estimated_cost="none", timeout_seconds=30,
        )
        registry = SpecialistRegistry()
        registry.register(manifest)
        with self.assertRaises(ConfigInvalidError):
            registry.register(manifest)

    def test_manifest_rejects_unbounded_timeout(self) -> None:
        with self.assertRaises(ConfigInvalidError):
            SpecialistManifest(
                id="coding_review", version="1.0", description="Code review",
                capabilities=frozenset({"code_review"}), accepted_inputs=frozenset({"text"}),
                requires_current_data=False, preferred_runtime="local", risk_level="low",
                estimated_cost="none", timeout_seconds=301,
            )


if __name__ == "__main__":
    unittest.main()
