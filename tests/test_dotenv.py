"""`.env` loader behavior (SEC-004): parse, skip, non-override, missing file."""

from __future__ import annotations

import os
import tempfile
import unittest

from elly.dotenv import load_dotenv


class DotenvTests(unittest.TestCase):
    def _write(self, text: str) -> str:
        fh = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        fh.write(text)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_loads_key_value(self) -> None:
        path = self._write('FOO_ELLY_TEST=bar\n# comment\nexport BAZ_ELLY_TEST="qux"\n')
        self.addCleanup(os.environ.pop, "FOO_ELLY_TEST", None)
        self.addCleanup(os.environ.pop, "BAZ_ELLY_TEST", None)
        loaded = load_dotenv(path)
        self.assertEqual(os.environ["FOO_ELLY_TEST"], "bar")
        self.assertEqual(os.environ["BAZ_ELLY_TEST"], "qux")  # quotes + export stripped
        self.assertCountEqual(loaded, ["FOO_ELLY_TEST", "BAZ_ELLY_TEST"])

    def test_skips_blank_comment_and_empty_value(self) -> None:
        path = self._write("\n# c\nEMPTY_ELLY_TEST=\nNOEQ_line\n")
        self.assertEqual(load_dotenv(path), [])
        self.assertNotIn("EMPTY_ELLY_TEST", os.environ)

    def test_does_not_override_existing_env(self) -> None:
        os.environ["EXISTING_ELLY_TEST"] = "real"
        self.addCleanup(os.environ.pop, "EXISTING_ELLY_TEST", None)
        path = self._write("EXISTING_ELLY_TEST=fromfile\n")
        load_dotenv(path)
        self.assertEqual(os.environ["EXISTING_ELLY_TEST"], "real")  # real env wins
        load_dotenv(path, override=True)
        self.assertEqual(os.environ["EXISTING_ELLY_TEST"], "fromfile")

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(load_dotenv("/nonexistent/.env"), [])


if __name__ == "__main__":
    unittest.main()
