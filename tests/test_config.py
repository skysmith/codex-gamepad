from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_gamepad.config import load_config
from codex_gamepad.models import CodexGamepadError


class ConfigTests(unittest.TestCase):
    def test_loads_allowlisted_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"voice": "af_heart", "speed": 1.05, "thread": "thread-1"}),
                encoding="utf-8",
            )
            self.assertEqual(load_config(path)["thread"], "thread-1")

    def test_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"response_text": "must never persist here"}', encoding="utf-8")
            with self.assertRaises(CodexGamepadError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
