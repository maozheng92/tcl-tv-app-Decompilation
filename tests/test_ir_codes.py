"""Unit tests for Broadlink / Harmony / Xiaomi IR code-file parsers."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_IR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tcl_tv"
    / "ir_codes.py"
)
_SPEC = importlib.util.spec_from_file_location("tcl_tv_ir_codes", _IR)
assert _SPEC is not None and _SPEC.loader is not None
ir_codes = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ir_codes
_SPEC.loader.exec_module(ir_codes)


class IrCodesTests(unittest.TestCase):
    def test_parse_broadlink_codes(self) -> None:
        devices, commands = ir_codes.parse_broadlink_codes_payload(
            {"data": {"TV": {"Power": "xx", "Mute": "yy"}, "AC": {"On": "zz"}}}
        )
        self.assertEqual(devices, ["AC", "TV"])
        self.assertEqual(commands, ["Mute", "On", "Power"])
        _devices, tv_cmds = ir_codes.parse_broadlink_codes_payload(
            {"TV": {"Power": "xx", "Mute": "yy"}}, device="tv"
        )
        self.assertEqual(tv_cmds, ["Mute", "Power"])
        self.assertEqual(ir_codes.parse_broadlink_codes_payload(None), ([], []))

    def test_resolve_broadlink_codes_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)
            path = storage / "broadlink_remote_aabbccddeeff_codes"
            path.write_text(
                json.dumps({"data": {"TV": {"Power": "AA=="}}}), encoding="utf-8"
            )
            found = ir_codes.resolve_broadlink_codes_path(
                storage, ["aa:bb:cc:dd:ee:ff", "remote.living_room"]
            )
            self.assertEqual(found, path)
            self.assertIsNone(
                ir_codes.resolve_broadlink_codes_path(storage, ["missing"])
            )

    def test_parse_harmony_devices_map(self) -> None:
        payload = {
            "Devices": {
                "Living TV": {"id": "123", "commands": ["PowerOn", "PowerOff"]},
                "Soundbar": {"id": "456", "commands": ["Mute"]},
            }
        }
        devices, commands = ir_codes.parse_harmony_config(payload)
        self.assertEqual(devices, ["Living TV", "Soundbar"])
        self.assertEqual(commands, ["PowerOn", "PowerOff", "Mute"])
        _devices, tv = ir_codes.parse_harmony_config(payload, device="Living TV")
        self.assertEqual(tv, ["PowerOn", "PowerOff"])
        _devices, by_id = ir_codes.parse_harmony_config(payload, device="123")
        self.assertEqual(by_id, ["PowerOn", "PowerOff"])

    def test_parse_xiaomi_codes(self) -> None:
        store = {
            "version": 1,
            "key": "xiaomi_home_remote_123_codes",
            "data": {"电视": {"电源": "AA==", "静音": "BB=="}},
        }
        devices, commands = ir_codes.parse_xiaomi_codes_payload(store)
        self.assertEqual(devices, ["电视"])
        self.assertEqual(commands, ["电源", "静音"])

    def test_load_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            path.write_text('{"ok": true}', encoding="utf-8")
            self.assertEqual(ir_codes.load_json_file(path), {"ok": True})
            self.assertIsNone(ir_codes.load_json_file(Path(tmp) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
