from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from codex_gamepad.rollout import extract_rollout_reply, find_rollout


FIXTURES = Path(__file__).parent / "fixtures"


class RolloutCompatibilityTests(unittest.TestCase):
    def test_final_answer_wins_over_trailing_commentary(self) -> None:
        reply = extract_rollout_reply(FIXTURES / "root-rollout.jsonl")
        self.assertIn("synthetic result", reply.text)
        self.assertNotIn("Trailing commentary", reply.text)

    def test_newer_subagent_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            sessions = Path(raw_home) / "sessions" / "2026" / "01" / "01"
            sessions.mkdir(parents=True)
            root = sessions / "rollout-root.jsonl"
            subagent = sessions / "rollout-subagent.jsonl"
            root.write_bytes((FIXTURES / "root-rollout.jsonl").read_bytes())
            subagent.write_bytes((FIXTURES / "subagent-rollout.jsonl").read_bytes())
            os.utime(root, (100, 100))
            os.utime(subagent, (200, 200))
            self.assertEqual(find_rollout(Path(raw_home)), root)


if __name__ == "__main__":
    unittest.main()
