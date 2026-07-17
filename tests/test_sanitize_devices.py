from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SANITIZER = ROOT / "scripts" / "sanitize-karabiner-devices.py"


class SanitizeKarabinerDevicesTests(unittest.TestCase):
    def test_emits_only_allowlisted_controller_fields(self) -> None:
        raw = [
            {
                "device_id": 4815162342,
                "device_identifiers": {
                    "is_game_pad": True,
                    "is_keyboard": False,
                    "product_id": 12315,
                    "vendor_id": 11720,
                },
                "manufacturer": "8BitDo",
                "product": "Ultimate 2C Wireless Controller",
                "transport": "Bluetooth Low Energy",
                "serial_number": "SERIAL-SECRET-123",
                "bluetooth_address": "AA:BB:CC:DD:EE:FF",
                "unexpected": "UNRECOGNIZED-SECRET",
            }
        ]
        result = subprocess.run(
            [sys.executable, str(SANITIZER)],
            input=json.dumps(raw),
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            [
                {
                    "is_game_pad": True,
                    "manufacturer": "8BitDo",
                    "product": "Ultimate 2C Wireless Controller",
                    "product_id": 12315,
                    "transport": "Bluetooth Low Energy",
                    "vendor_id": 11720,
                }
            ],
        )
        for secret in (
            "4815162342",
            "SERIAL-SECRET-123",
            "AA:BB:CC:DD:EE:FF",
            "UNRECOGNIZED-SECRET",
            "is_keyboard",
        ):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_rejects_invalid_shape_without_echoing_input(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SANITIZER)],
            input='{"serial_number":"SERIAL-SECRET-123"}',
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("SERIAL-SECRET-123", result.stderr)

    def test_controller_filter_omits_unrelated_devices(self) -> None:
        raw = [
            {
                "device_identifiers": {"is_game_pad": False},
                "manufacturer": "Example",
                "product": "Keyboard",
            },
            {
                "device_identifiers": {
                    "is_game_pad": False,
                    "product_id": 20,
                    "vendor_id": 10,
                },
                "manufacturer": "Example",
                "product": "USB Controller",
                "transport": "USB",
            },
        ]
        result = subprocess.run(
            [sys.executable, str(SANITIZER), "--controllers-only"],
            input=json.dumps(raw),
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        devices = json.loads(result.stdout)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["product"], "USB Controller")


if __name__ == "__main__":
    unittest.main()
