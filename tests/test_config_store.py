"""Unit tests for config_store.py.

Always writes to a temp .env path (never the real project .env).
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import config
from config_store import set_config_value


class SetConfigValueTests(unittest.TestCase):

    def test_writes_env_file_updates_environ_and_config_module(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("", encoding="utf-8")

            with patch.object(config, "GEMINI_MODEL", ""):
                set_config_value("GEMINI_MODEL", "gemini-2.5-flash", env_path=env_path)

                self.assertEqual(config.GEMINI_MODEL, "gemini-2.5-flash")

            self.assertEqual(os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash")
            self.assertIn("GEMINI_MODEL='gemini-2.5-flash'", env_path.read_text(encoding="utf-8"))

    def test_preserves_other_existing_env_entries(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("VB_URL=https://example.com\n", encoding="utf-8")

            set_config_value("GEMINI_MODEL", "gemini-2.5-flash", env_path=env_path)

            content = env_path.read_text(encoding="utf-8")
            self.assertIn("VB_URL=https://example.com", content)
            self.assertIn("GEMINI_MODEL", content)


if __name__ == "__main__":
    unittest.main()
