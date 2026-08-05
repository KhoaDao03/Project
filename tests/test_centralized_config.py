"""One-file operational configuration integration tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import elly.__main__ as entrypoint
from elly.adapters.fake_generalist import FakeGeneralist
from elly.composition import build
from elly.research.fake_provider import FixtureWebResearchProvider
from elly.specialists.fake_provider import FakeSpecialistProvider


class CentralizedConfigIntegrationTests(unittest.TestCase):
    def test_normal_entrypoint_auto_loads_config_local(self) -> None:
        app = Mock()
        cli = Mock()
        with (
            patch.object(entrypoint, "load_dotenv"),
            patch.object(entrypoint.Path, "is_file", return_value=True),
            patch.object(entrypoint, "build", return_value=app) as build,
            patch.object(entrypoint.Cli, "start", return_value=cli),
        ):
            self.assertEqual(entrypoint.main([]), 0)
        build.assert_called_once_with("config.local.toml")
        cli.run.assert_called_once_with()
        app.close.assert_called_once_with()

    def test_one_toml_controls_every_provider_model_and_price(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "elly.toml"
            manifest_dir = Path("config/specialists").resolve()
            config_path.write_text(
                "[app]\n"
                f"db_path={str(root / 'elly.db')!r}\n"
                "[providers]\n"
                "generalist='fake'\nresearch='fixtures'\nspecialists='fake'\n"
                "[models]\n"
                "generalist='local-central'\nresearch='research-central'\n"
                "specialist_default='specialist-central'\n"
                "[models.specialists]\ncoding='coding-central'\n"
                "[pricing]\nmonthly_budget_usd=9\n"
                "remote_call_reservation_usd=0.09\nconsent_max_cost_usd=0.45\n"
                "[specialists]\n"
                f"manifest_dir={str(manifest_dir)!r}\n"
                "[log]\nlevel='WARNING'\n",
                encoding="utf-8",
            )
            names = (
                "ELLY_GENERALIST_PROVIDER", "ELLY_GENERALIST_MODEL_ID",
                "ELLY_RESEARCH_PROVIDER", "ELLY_RESEARCH_MODEL_ID",
                "ELLY_SPECIALIST_PROVIDER", "ELLY_SPECIALIST_DEFAULT_MODEL_ID",
                "ELLY_MONTHLY_BUDGET_USD", "ELLY_REMOTE_CALL_RESERVATION_USD",
            )
            saved = {name: os.environ.pop(name, None) for name in names}
            app = None
            try:
                app = build(str(config_path))
                self.assertIsInstance(app.generalist, FakeGeneralist)
                self.assertIsInstance(app.research.provider, FixtureWebResearchProvider)
                self.assertIsInstance(app.specialist_workflow.provider, FakeSpecialistProvider)
                self.assertEqual(app.config.generalist_model_id, "local-central")
                self.assertEqual(app.config.research_model_id, "research-central")
                self.assertEqual(app.specialist_registry.get("coding").provider_model, "coding-central")
                self.assertEqual(app.specialist_registry.get("research").provider_model, "specialist-central")
                self.assertEqual(app.guardrails.cost.budget_usd, 9)
                # Fake/local routes cost zero even though the remote reservation
                # policy is centrally configured for real cloud adapters.
                self.assertEqual(app.research.call_cost_usd, 0)
                self.assertEqual(app.specialist_workflow.call_cost_usd, 0)
                self.assertEqual(app.specialist_workflow.consent_max_cost_usd, 0.45)
            finally:
                if app is not None:
                    app.close()
                for name, value in saved.items():
                    if value is not None:
                        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
