"""Unit tests for custom input-source option parsing."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_SOURCES = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tcl_tv"
    / "sources.py"
)
_SPEC = importlib.util.spec_from_file_location("tcl_tv_sources", _SOURCES)
assert _SPEC is not None and _SPEC.loader is not None
sources = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sources
_SPEC.loader.exec_module(sources)


class SourceParseTests(unittest.TestCase):
    def test_copy_sources_keeps_order_and_drops_bad_rows(self) -> None:
        parsed = sources.copy_sources(
            [
                {
                    "name": " HDMI 1 ",
                    "hidden": False,
                    "buttons": [
                        "button.ir_source",
                        "button.ir_right",
                        "button.ir_ok",
                    ],
                    "interval": 0.3,
                },
                {"name": "HDMI 1", "buttons": ["button.dup"]},
                {"name": "AV", "buttons": []},
                "nope",
                {
                    "name": "HDMI 2",
                    "hidden": True,
                    "buttons": "button.ir_source, button.ir_ok",
                    "interval": "2",
                },
            ]
        )
        self.assertEqual(
            parsed,
            [
                {
                    "name": "HDMI 1",
                    "hidden": False,
                    "buttons": [
                        "button.ir_source",
                        "button.ir_right",
                        "button.ir_ok",
                    ],
                    "interval": 0.3,
                },
                {
                    "name": "HDMI 2",
                    "hidden": True,
                    "buttons": ["button.ir_source", "button.ir_ok"],
                    "interval": 2.0,
                },
            ],
        )
        self.assertEqual(sources.visible_source_names(parsed), ["HDMI 1"])
        self.assertEqual(sources.source_names(parsed), ["HDMI 1", "HDMI 2"])
        self.assertEqual(sources.find_source_index(parsed, "hdmi 2"), 1)

    def test_parse_button_ids_dedupes_and_splits_text(self) -> None:
        self.assertEqual(
            sources.parse_button_ids(
                ["button.a", "button.a", " button.b ", "", "button.c"]
            ),
            ["button.a", "button.b", "button.c"],
        )
        self.assertEqual(
            sources.parse_button_ids("button.a; button.b, button.a"),
            ["button.a", "button.b"],
        )

    def test_name_in_use_is_case_insensitive(self) -> None:
        items = sources.copy_sources(
            [{"name": "HDMI 1", "buttons": ["button.a"]}]
        )
        self.assertTrue(sources.name_in_use(items, "hdmi 1"))
        self.assertFalse(sources.name_in_use(items, "hdmi 1", exclude_index=0))
        self.assertFalse(sources.name_in_use(items, "HDMI 2"))

    def test_parse_interval_clamps(self) -> None:
        self.assertEqual(sources.parse_interval(None), sources.DEFAULT_INTERVAL)
        self.assertEqual(sources.parse_interval(-1), 0.0)
        self.assertEqual(sources.parse_interval(99), sources.MAX_INTERVAL)
        self.assertEqual(sources.parse_interval("0.5"), 0.5)

    def test_saved_options_keeps_sources_when_power_on_cleared(self) -> None:
        items = sources.copy_sources(
            [{"name": "HDMI 1", "buttons": ["button.ir_source"]}]
        )
        self.assertEqual(
            sources.saved_options({"sources": items}),
            {"sources": items},
        )
        self.assertEqual(
            sources.saved_options(
                {
                    "power_on_remote": "remote.broadlink",
                    "power_on_command": "Power",
                    "power_on_device": "TV",
                    "sources": items,
                }
            ),
            {
                "power_on_remote": "remote.broadlink",
                "power_on_command": "Power",
                "power_on_device": "TV",
                "sources": items,
            },
        )
        self.assertEqual(sources.saved_options({}), {})
