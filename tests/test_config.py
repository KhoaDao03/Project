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
        self.assertEqual(cfg.generalist_model_id, "fake-generalist-v1")

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

    def test_env_override(self) -> None:
        os.environ["ELLY_MAX_INPUT_CHARS"] = "42"
        self.addCleanup(os.environ.pop, "ELLY_MAX_INPUT_CHARS", None)
        self.assertEqual(load_config(None).max_input_chars, 42)

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


if __name__ == "__main__":
    unittest.main()
