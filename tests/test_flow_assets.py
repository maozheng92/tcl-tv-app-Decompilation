"""Sanity checks for options-flow copy and the footer script."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "tcl_tv"


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
        for step_id in (
            "source_form",
            "source_seq_repeat",
            "source_delete",
            "source_reorder",
        ):
            self.assertEqual(zh["options"]["step"][step_id]["submit"], "提交")

    def test_footer_script_hides_duplicate_menu_rows(self) -> None:
        script = (_ROOT / "www" / "tcl_tv_flow.js").read_text(encoding="utf-8")
        self.assertIn('init: ["save"]', script)
        self.assertIn('sources: ["save", "sources_done"]', script)
        self.assertIn("source_seq_kind_back", script)
        self.assertIn("go_back: true", script)
        self.assertIn('next_step_id: "save"', script)
        self.assertIn("dialog-data-entry-flow", script)
        self.assertIn("deepQuery(document, DIALOG_SEL)", script)

    def test_flow_ui_loads_classic_and_module_script(self) -> None:
        flow_ui = (_ROOT / "flow_ui.py").read_text(encoding="utf-8")
        self.assertIn("es5=True", flow_ui)

    def test_strings_and_en_have_save_submit(self) -> None:
        for name in ("strings.json", "translations/en.json"):
            data = json.loads((_ROOT / name).read_text())
            step = data["options"]["step"]
            self.assertEqual(step["source_form"]["submit"], "Submit")
            self.assertEqual(step["source_seq_repeat"]["submit"], "Submit")
            self.assertEqual(step["source_delete"]["submit"], "Submit")
            self.assertEqual(step["source_reorder"]["submit"], "Submit")
            self.assertEqual(step["sources"]["menu_options"]["save"], "Save")
            self.assertIn("source_seq_kind_back", step["source_seq_kind"]["menu_options"])
