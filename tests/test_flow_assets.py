"""Sanity checks for options-flow copy and Back on secondary screens."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "tcl_tv"
_FORM_STEPS = (
    "power_on",
    "ir_details",
    "source_add",
    "source_edit",
    "source_form",
    "source_seq_pick",
    "source_seq_repeat",
    "source_delete",
    "source_reorder",
)


class FlowAssetTests(unittest.TestCase):
    def test_zh_uses_button_entity_name(self) -> None:
        zh = json.loads((_ROOT / "translations" / "zh-Hans.json").read_text())
        blob = json.dumps(zh, ensure_ascii=False)
        self.assertIn("按钮实体", blob)
        self.assertNotIn("Button 实体", blob)
        self.assertNotIn("button 实体", blob)
        kind = zh["options"]["step"]["source_seq_kind"]["menu_options"]
        self.assertEqual(kind["source_seq_buttons"], "按钮实体")
        self.assertEqual(kind["source_seq_kind_back"], "返回")
        self.assertEqual(
            zh["options"]["step"]["sources"]["menu_options"]["sources_done"], "返回"
        )
        self.assertNotIn("go_back", zh["options"]["step"]["init"].get("data", {}))
        self.assertNotIn("go_back", zh["options"]["step"]["init"].get("menu_options", {}))
        for step_id in _FORM_STEPS:
            self.assertEqual(zh["options"]["step"][step_id]["data"]["go_back"], "返回上一界面")

    def test_no_footer_script(self) -> None:
        self.assertFalse((_ROOT / "www" / "tcl_tv_flow.js").exists())
        self.assertFalse((_ROOT / "flow_ui.py").exists())

    def test_strings_and_en_have_back(self) -> None:
        for name in ("strings.json", "translations/en.json"):
            data = json.loads((_ROOT / name).read_text())
            step = data["options"]["step"]
            self.assertEqual(step["sources"]["menu_options"]["sources_done"], "Back")
            self.assertEqual(step["source_seq_kind"]["menu_options"]["source_seq_kind_back"], "Back")
            self.assertEqual(step["source_seq_kind"]["menu_options"]["source_seq_buttons"], "Button entities")
            for step_id in _FORM_STEPS:
                self.assertEqual(step[step_id]["data"]["go_back"], "Go back")
