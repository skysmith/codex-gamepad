from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from codex_gamepad import runtime


class RuntimeTests(unittest.TestCase):
    def test_stop_force_kills_worker_that_ignores_sigterm(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"CODEX_GAMEPAD_STATE_DIR": str(Path(directory) / "state")}
        ):
            token = uuid.uuid4().hex
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(30)",
                    "codex_gamepad",
                    token,
                ],
                start_new_session=True,
            )
            try:
                paths = runtime.runtime_paths()
                runtime._write_state(paths.state, process.pid, token)
                time.sleep(0.1)
                started = time.monotonic()
                self.assertTrue(runtime.stop_worker())
                elapsed = time.monotonic() - started
                process.wait(timeout=1.0)
                self.assertLess(elapsed, 1.2)
                self.assertFalse(paths.state.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    unittest.main()
