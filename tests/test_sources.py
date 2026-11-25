"""Unit tests for custom input-source option parsing."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "tcl_tv"
_SOURCES = _ROOT / "sources.py"
_PROTOCOL = _ROOT / "protocol.py"
_SPEC = importlib.util.spec_from_file_location("tcl_tv_sources", _SOURCES)
assert _SPEC is not None and _SPEC.loader is not None
sources = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sources
_SPEC.loader.exec_module(sources)
_PSPEC = importlib.util.spec_from_file_location("tcl_tv_protocol_for_sources", _PROTOCOL)
assert _PSPEC is not None and _PSPEC.loader is not None
protocol = importlib.util.module_from_spec(_PSPEC)
sys.modules[_PSPEC.name] = protocol
_PSPEC.loader.exec_module(protocol)


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

    def test_copy_sources_keeps_tcl_key_repeats(self) -> None:
        parsed = sources.copy_sources(
            [
                {
                    "name": "HDMI 3",
                    "buttons": ["source", "right", "right", "ok"],
                    "interval": 0.4,
                }
            ]
        )
        self.assertEqual(
            parsed[0]["buttons"],
            ["source", "right", "right", "ok"],
        )

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

    def test_parse_source_actions_keeps_key_repeats_and_mixed_buttons(self) -> None:
        self.assertEqual(
            sources.parse_source_actions(
                ["source", "right", "right", "ok", "button.ir_ok"]
            ),
            ["source", "right", "right", "ok", "button.ir_ok"],
        )
        self.assertEqual(
            sources.parse_source_actions(
                ["key:source:1", "key:right:1", "key:right:2", "ok"]
            ),
            ["source", "right", "right", "ok"],
        )
        self.assertEqual(
            sources.unknown_source_actions(["source", "nope", "remote.ir"]),
            ["nope", "remote.ir"],
        )
        self.assertEqual(
            sources.classify_source_action("key:ok:3"),
            ("key", "ok"),
        )
        self.assertEqual(
            sources.classify_source_action("button.ir_source"),
            ("button", "button.ir_source"),
        )
        self.assertIsNone(sources.classify_source_action("screenshot"))
        self.assertEqual(sources.TCL_SOURCE_KEYS, set(protocol.KEYS))

    def test_collapse_and_expand_repeat_counts(self) -> None:
        self.assertEqual(
            sources.collapse_source_actions(
                ["source", "right", "right", "right", "ok"]
            ),
            [("source", 1), ("right", 3), ("ok", 1)],
        )
        self.assertEqual(
            sources.expand_source_steps(
                [("source", 1), ("right", 2), ("ok", 1), ("button.ir_ok", 3)]
            ),
            ["source", "right", "right", "ok", "button.ir_ok", "button.ir_ok", "button.ir_ok"],
        )
        self.assertEqual(
            sources.unique_actions_of_kind(
                ["source", "right", "right", "ok", "button.ir_ok"],
                sources.KIND_KEY,
            ),
            ["source", "right", "ok"],
        )
        self.assertEqual(
            sources.counts_for_kind(["source", "right", "right", "ok"], sources.KIND_KEY),
            {"source": 1, "right": 2, "ok": 1},
        )
        self.assertEqual(
            sources.sequence_kind(["source", "right", "ok"]),
            sources.KIND_KEY,
        )
        self.assertEqual(
            sources.sequence_kind(["button.a", "button.b"]),
            sources.KIND_BUTTON,
        )
        self.assertIsNone(sources.sequence_kind(["source", "button.ir_ok"]))
        self.assertEqual(sources.parse_repeat(0), sources.SOURCE_REPEAT_MIN)
        self.assertEqual(sources.parse_repeat(99), sources.SOURCE_REPEAT_MAX)
        self.assertEqual(sources.parse_repeat("3"), 3)

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
