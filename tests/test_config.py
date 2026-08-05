"""Configuration failures and overrides (OPS-002 initial)."""

from __future__ import annotations

import os
import tempfile
import unittest

from elly.config import load_config
from elly.domain.errors import ConfigInvalidError


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = load_config(None)
        self.assertEqual(cfg.max_input_chars, 20000)
        self.assertEqual(cfg.generalist_model_id, "qwen3:8b")
        self.assertEqual(cfg.generalist_provider, "ollama")
        self.assertEqual(cfg.ollama_base_url, "http://127.0.0.1:11434")
        self.assertEqual(cfg.session_retention_days, 30)
        self.assertEqual(cfg.evidence_retention_days, 7)
        self.assertEqual(cfg.audit_retention_days, 90)
        self.assertEqual(cfg.provider_call_cost_usd, 0.01)
        self.assertEqual(cfg.specialist_provider, "openai")
        self.assertEqual(cfg.specialist_model_id("coding"), "gpt-5.6-luna")
        self.assertEqual(cfg.consent_max_cost_usd, 0.25)
        self.assertEqual(cfg.research_max_output_tokens, 1024)

    def test_development_config_selects_eight_b(self) -> None:
        cfg = load_config("config.example.toml")
        self.assertEqual(cfg.generalist_provider, "ollama")
        self.assertEqual(cfg.generalist_model_id, "qwen3:8b")

    def test_fourteen_b_is_explicit_opt_in_config(self) -> None:
        cfg = load_config("config.qwen3-14b.example.toml")
        self.assertEqual(cfg.generalist_model_id, "qwen3:14b")

    def test_toml_overrides(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write('[limits]\nmax_input_chars = 100\n[app]\ndb_path = ":memory:"\n')
            path = fh.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.max_input_chars, 100)
            self.assertEqual(cfg.db_path, ":memory:")
        finally:
            os.unlink(path)

    def test_central_tables_control_all_runtime_choices(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(
                "[providers]\n"
                "generalist='fake'\nresearch='fixtures'\nspecialists='fake'\n"
                "[models]\n"
                "generalist='local-one'\nresearch='web-one'\n"
                "specialist_default='cloud-one'\n"
                "[models.specialists]\ncoding='cloud-code'\n"
                "[pricing]\nmonthly_budget_usd=7\n"
                "remote_call_reservation_usd=0.07\nconsent_max_cost_usd=0.4\n"
            )
            path = fh.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.generalist_provider, "fake")
            self.assertEqual(cfg.research_provider, "fixtures")
            self.assertEqual(cfg.specialist_provider, "fake")
            self.assertEqual(cfg.generalist_model_id, "local-one")
            self.assertEqual(cfg.research_model_id, "web-one")
            self.assertEqual(cfg.specialist_model_id("coding"), "cloud-code")
            self.assertEqual(cfg.specialist_model_id("research"), "cloud-one")
            self.assertEqual(cfg.monthly_budget_usd, 7)
            self.assertEqual(cfg.remote_call_reservation_usd, 0.07)
            self.assertEqual(cfg.consent_max_cost_usd, 0.4)
        finally:
            os.unlink(path)

    def test_central_choice_overrides_legacy_duplicate_during_migration(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(
                "[generalist]\nprovider='ollama'\nmodel_id='legacy-model'\n"
                "[providers]\ngeneralist='fake'\n"
                "[models]\ngeneralist='central-model'\n"
            )
            path = fh.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.generalist_provider, "fake")
            self.assertEqual(cfg.generalist_model_id, "central-model")
        finally:
            os.unlink(path)

    def test_env_override(self) -> None:
        os.environ["ELLY_MAX_INPUT_CHARS"] = "42"
        self.addCleanup(os.environ.pop, "ELLY_MAX_INPUT_CHARS", None)
        self.assertEqual(load_config(None).max_input_chars, 42)

    def test_research_output_limit_is_configurable(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write("[research]\nmax_output_tokens = 1536\n")
            path = fh.name
        try:
            self.assertEqual(load_config(path).research_max_output_tokens, 1536)
        finally:
            os.unlink(path)

    def test_invalid_log_level_fails_closed(self) -> None:
        os.environ["ELLY_LOG_LEVEL"] = "LOUD"
        self.addCleanup(os.environ.pop, "ELLY_LOG_LEVEL", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_nonpositive_limit_fails_closed(self) -> None:
        os.environ["ELLY_MAX_INPUT_CHARS"] = "0"
        self.addCleanup(os.environ.pop, "ELLY_MAX_INPUT_CHARS", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_missing_toml_fails_closed(self) -> None:
        with self.assertRaises(ConfigInvalidError):
            load_config("/nonexistent/path/elly-config.toml")

    def test_invalid_guardrail_fails_closed(self) -> None:
        os.environ["ELLY_MAX_RETRIES"] = "-1"
        self.addCleanup(os.environ.pop, "ELLY_MAX_RETRIES", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_non_numeric_guardrail_fails_closed(self) -> None:
        os.environ["ELLY_TOOL_TIMEOUT_SECONDS"] = "not-a-number"
        self.addCleanup(os.environ.pop, "ELLY_TOOL_TIMEOUT_SECONDS", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_ollama_url_cannot_smuggle_a_remote_host_in_userinfo(self) -> None:
        os.environ["ELLY_OLLAMA_BASE_URL"] = "http://127.0.0.1:11434@evil.example"
        self.addCleanup(os.environ.pop, "ELLY_OLLAMA_BASE_URL", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_empty_model_ids_fail_closed(self) -> None:
        os.environ["ELLY_RESEARCH_MODEL_ID"] = "   "
        self.addCleanup(os.environ.pop, "ELLY_RESEARCH_MODEL_ID", None)
        with self.assertRaises(ConfigInvalidError):
            load_config(None)


if __name__ == "__main__":
    unittest.main()
