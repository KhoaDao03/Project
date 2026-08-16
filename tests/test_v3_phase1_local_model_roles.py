"""Phase 1 characterization for independently configurable local-model roles."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from elly.api.contracts import LocalModelRoleView
from elly.composition import build_application
from elly.config import load_config
from elly.domain.errors import ConfigInvalidError
from elly.presentation.render import render_status


class V3Phase1LocalModelRoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = {
            key: value
            for key, value in os.environ.items()
            if key.startswith("ELLY_LOCAL_")
            or key.startswith("ELLY_GENERALIST_")
            or key.startswith("ELLY_OLLAMA_")
        }
        for key in self._saved_env:
            os.environ.pop(key, None)
        self.addCleanup(self._restore_environment)

    def _restore_environment(self) -> None:
        for key in tuple(os.environ):
            if (
                key.startswith("ELLY_LOCAL_")
                or key.startswith("ELLY_GENERALIST_")
                or key.startswith("ELLY_OLLAMA_")
            ):
                os.environ.pop(key, None)
        os.environ.update(self._saved_env)

    def _config_file(self, text: str) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_defaults_reuse_one_profile_with_independent_role_limits(self) -> None:
        config = load_config(None)

        self.assertEqual(
            tuple(profile.name for profile in config.local_model_profiles),
            ("qwen_default",),
        )
        self.assertIs(config.conversation_role.profile, config.planner_role.profile)
        self.assertIs(config.planner_role.profile, config.synthesis_role.profile)
        self.assertEqual(config.conversation_role.model_id, "qwen3:8b")
        self.assertEqual(config.planner_role.max_output_tokens, 1200)
        self.assertEqual(config.synthesis_role.max_output_tokens, 1600)
        self.assertEqual(config.max_provider_calls, 3)
        self.assertEqual(config.max_concurrency, 2)

    def test_toml_rebinds_one_role_without_changing_the_others(self) -> None:
        path = self._config_file(
            """
            [local_models.profiles.qwen_default]
            provider = "fake"
            model_id = "conversation-v1"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90

            [local_models.profiles.planner_large]
            provider = "fake"
            model_id = "planner-v2"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 180

            [local_models.roles]
            conversation = "qwen_default"
            planner = "planner_large"
            synthesis = "qwen_default"

            [local_models.role_limits]
            conversation_max_output_tokens = 400
            planner_max_output_tokens = 1400
            synthesis_max_output_tokens = 1800
            """
        )
        config = load_config(path)

        self.assertEqual(config.conversation_role.model_id, "conversation-v1")
        self.assertEqual(config.planner_role.model_id, "planner-v2")
        self.assertEqual(config.synthesis_role.model_id, "conversation-v1")
        self.assertEqual(config.conversation_role.max_output_tokens, 400)
        self.assertEqual(config.planner_role.max_output_tokens, 1400)
        self.assertEqual(config.synthesis_role.max_output_tokens, 1800)
        self.assertEqual(config.planner_role.timeout_seconds, 180.0)

    def test_environment_role_and_profile_overrides_have_precedence(self) -> None:
        path = self._config_file(
            """
            [local_models.profiles.qwen_default]
            provider = "fake"
            model_id = "toml-conversation"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90

            [local_models.profiles.planner_large]
            provider = "fake"
            model_id = "toml-planner"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 180

            [local_models.roles]
            planner = "qwen_default"
            """
        )
        os.environ["ELLY_LOCAL_PLANNER_PROFILE"] = "planner_large"
        os.environ["ELLY_LOCAL_MODELS_QWEN_DEFAULT_MODEL_ID"] = "env-conversation"
        os.environ["ELLY_LOCAL_MODELS_PLANNER_LARGE_TIMEOUT_SECONDS"] = "240"

        config = load_config(path)

        self.assertEqual(config.conversation_role.model_id, "env-conversation")
        self.assertEqual(config.synthesis_role.model_id, "env-conversation")
        self.assertEqual(config.planner_role.model_id, "toml-planner")
        self.assertEqual(config.planner_role.timeout_seconds, 240.0)

    def test_legacy_keys_migrate_all_roles_and_warn_once(self) -> None:
        path = self._config_file(
            """
            [generalist]
            provider = "fake"
            model_id = "legacy-model"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 77
            max_output_tokens = 333
            """
        )

        with self.assertLogs("elly.config", level="WARNING") as captured:
            config = load_config(path)

        self.assertEqual(len(captured.records), 1)
        self.assertEqual(config.local_model_profiles[0].name, "v2_generalist")
        for role in (
            config.conversation_role,
            config.planner_role,
            config.synthesis_role,
        ):
            self.assertEqual(role.profile_name, "v2_generalist")
            self.assertEqual(role.provider, "fake")
            self.assertEqual(role.model_id, "legacy-model")
        self.assertEqual(config.conversation_role.max_output_tokens, 333)
        self.assertEqual(config.planner_role.max_output_tokens, 1200)

    def test_new_catalog_wins_over_conflicting_legacy_keys_with_one_warning(self) -> None:
        path = self._config_file(
            """
            [generalist]
            provider = "ollama"
            model_id = "legacy-model"

            [local_models.profiles.qwen_default]
            provider = "fake"
            model_id = "new-model"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90
            """
        )

        with self.assertLogs("elly.config", level="WARNING") as captured:
            config = load_config(path)

        self.assertEqual(len(captured.records), 1)
        self.assertEqual(config.conversation_role.model_id, "new-model")
        self.assertEqual(config.planner_role.model_id, "new-model")
        self.assertNotIn("v2_generalist", {p.name for p in config.local_model_profiles})

    def test_invalid_profile_binding_and_endpoint_fail_closed(self) -> None:
        unknown_binding = self._config_file(
            """
            [local_models.roles]
            planner = "missing"
            """
        )
        with self.assertRaises(ConfigInvalidError):
            load_config(unknown_binding)

        os.environ["ELLY_LOCAL_MODELS_QWEN_DEFAULT_BASE_URL"] = "https://example.com"
        with self.assertRaises(ConfigInvalidError):
            load_config(None)

    def test_missing_custom_profile_identity_and_unsupported_provider_fail_closed(self) -> None:
        missing_identity = self._config_file(
            """
            [local_models.profiles.custom]
            provider = "fake"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90
            [local_models.roles]
            conversation = "custom"
            """
        )
        with self.assertRaises(ConfigInvalidError):
            load_config(missing_identity)

        unsupported_provider = self._config_file(
            """
            [local_models.profiles.qwen_default]
            provider = "remote"
            model_id = "bad"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90
            """
        )
        with self.assertRaises(ConfigInvalidError):
            load_config(unsupported_provider)

    def test_remote_provider_and_model_selection_is_independent(self) -> None:
        path = self._config_file(
            """
            [local_models.profiles.qwen_default]
            provider = "fake"
            model_id = "local-v3"
            base_url = "http://127.0.0.1:11434"
            timeout_seconds = 90

            [providers]
            research = "fixtures"
            specialists = "fake"

            [models]
            research = "research-v3"
            specialist_default = "specialist-v3"
            """
        )
        config = load_config(path)

        self.assertEqual(config.conversation_role.model_id, "local-v3")
        self.assertEqual(config.research_provider, "fixtures")
        self.assertEqual(config.research_model_id, "research-v3")
        self.assertEqual(config.specialist_provider, "fake")
        self.assertEqual(config.specialist_default_model_id, "specialist-v3")

    def test_status_exposes_each_effective_role_without_endpoint_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._config_file(
                f"""
                [app]
                db_path = {str(Path(directory) / "elly.db")!r}

                [providers]
                research = "fixtures"
                specialists = "fake"

                [local_models.profiles.qwen_default]
                provider = "fake"
                model_id = "conversation"
                base_url = "http://127.0.0.1:11434"
                timeout_seconds = 90

                [local_models.profiles.planner]
                provider = "fake"
                model_id = "planner"
                base_url = "http://127.0.0.1:11434"
                timeout_seconds = 120

                [local_models.roles]
                conversation = "qwen_default"
                planner = "planner"
                synthesis = "qwen_default"

                [specialists]
                manifest_dir = "config/specialists"
                """
            )
            application = build_application(config_path)
            try:
                result = application.get_status()
            finally:
                application.close()

        self.assertTrue(result.is_success)
        assert result.value is not None
        assert result.value.runtime is not None
        roles = result.value.runtime.local_model_roles
        self.assertEqual(
            tuple(role.role for role in roles),
            ("conversation", "planner", "synthesis"),
        )
        self.assertEqual(roles[1].profile_name, "planner")
        self.assertEqual(roles[1].model_id, "planner")
        self.assertTrue(all(isinstance(role, LocalModelRoleView) for role in roles))
        rendered = render_status(result.value)
        self.assertIn("Local roles:", rendered)
        self.assertNotIn("base_url", rendered)
        self.assertNotIn("http://127.0.0.1:11434", rendered)

    def test_role_profile_and_catalog_are_immutable(self) -> None:
        config = load_config(None)
        with self.assertRaises(FrozenInstanceError):
            config.conversation_role.profile.model_id = "mutated"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            config.local_model_profiles[0] = config.local_model_profiles[0]  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
