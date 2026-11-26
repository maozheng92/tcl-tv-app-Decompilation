"""Sanity checks for Hisense-style options-flow copy and footer script."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
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
_INIT_MENU = ("power_on", "sources", "save")
_SOURCE_MENU = (
    "source_add",
    "source_edit",
    "source_delete",
    "source_reorder",
    "save",
    "sources_done",
)


def _load(name: str) -> dict:
    return json.loads((_ROOT / name).read_text(encoding="utf-8"))


class FlowAssetTests(unittest.TestCase):
    def test_zh_uses_button_entity_name(self) -> None:
        zh = _load("translations/zh-Hans.json")
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
        self.assertEqual(zh["options"]["step"]["sources"]["menu_options"]["save"], "保存")
        self.assertNotIn("go_back", zh["options"]["step"]["init"].get("data", {}))
        self.assertNotIn("go_back", zh["options"]["step"]["init"].get("menu_options", {}))
        for step_id in _FORM_STEPS:
            self.assertNotIn("go_back", zh["options"]["step"][step_id].get("data", {}))
            self.assertNotIn(
                "go_back", zh["options"]["step"][step_id].get("data_description", {})
            )
            self.assertEqual(zh["options"]["step"][step_id]["submit"], "提交")
        hidden = zh["options"]["step"]["source_add"]["data"]["hidden"]
        self.assertEqual(hidden, "从输入源列表中隐藏")
        self.assertNotIn("go_back_choice", zh.get("selector", {}))

    def test_strings_and_en_match_source_ux(self) -> None:
        for name in ("strings.json", "translations/en.json"):
            data = _load(name)
            step = data["options"]["step"]
            self.assertEqual(tuple(step["init"]["menu_options"]), _INIT_MENU)
            self.assertEqual(step["sources"]["menu_options"]["sources_done"], "Back")
            self.assertEqual(step["sources"]["menu_options"]["save"], "Save")
            self.assertEqual(tuple(step["sources"]["menu_options"]), _SOURCE_MENU)
            self.assertEqual(
                step["source_seq_kind"]["menu_options"]["source_seq_kind_back"], "Back"
            )
            self.assertEqual(
                step["source_seq_kind"]["menu_options"]["source_seq_buttons"],
                "Button entities",
            )
            self.assertEqual(step["source_add"]["data"]["hidden"], "Hide from source list")
            self.assertEqual(step["source_add"]["data"]["name"], "Name")
            self.assertEqual(step["source_reorder"]["data"]["source_order"], "Order")
            for step_id in _FORM_STEPS:
                self.assertNotIn("go_back", step[step_id].get("data", {}))
                self.assertNotIn("go_back", step[step_id].get("data_description", {}))
                self.assertEqual(step[step_id]["submit"], "Submit")
            self.assertNotIn("go_back_choice", data.get("selector", {}))

    def test_footer_script_posts_go_back_and_hides_menu_rows(self) -> None:
        script = (_ROOT / "frontend" / "tcl_tv_flow.js").read_text(encoding="utf-8")
        self.assertIn('DOMAIN = "tcl_tv"', script)
        self.assertIn('sources: ["save", "sources_done"]', script)
        self.assertIn("source_seq_kind_back", script)
        self.assertIn("go_back: true", script)
        self.assertIn('next_step_id: "save"', script)
        self.assertIn('step.step_id === "sources"', script)
        self.assertIn("dialog-data-entry-flow", script)
        self.assertIn('back: "返回"', script)
        self.assertIn("secondaryAction", script)
        self.assertIn("primaryAction", script)
        self.assertIn("space-between", script)
        self.assertIn('setProperty("justify-content", justify, "important")', script)
        self.assertIn('margin-inline-end", "auto"', script)
        self.assertIn('appearance", "accent"', script)
        self.assertIn('appearance", "plain"', script)
        self.assertIn("deepQuery(document, DIALOG_SEL)", script)
        flow_ui = (_ROOT / "flow_ui.py").read_text(encoding="utf-8")
        self.assertIn("es5=True", flow_ui)
        self.assertIn("add_extra_js_url", flow_ui)
        self.assertIn("/local/", flow_ui)
        self.assertIn("install_flow_www", flow_ui)
        self.assertNotIn("StaticPathConfig", flow_ui)
        init_py = (_ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("async_setup_flow_ui", init_py)
        self.assertIn("async def async_setup(", init_py)

    def test_go_back_is_footer_not_schema_field(self) -> None:
        text = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
        helper = text.split("def _with_back", 1)[1].split("def _show_form", 1)[0]
        self.assertNotIn("BooleanSelector", helper)
        self.assertNotIn("_go_back_selector", text)
        self.assertNotIn("button_toggle", text)
        self.assertIn("tcl_tv_flow.js", helper)
        self.assertIn("_SchemaWithBack(mapping)", helper)

    def test_version_and_no_legacy_www(self) -> None:
        manifest = _load("manifest.json")
        self.assertEqual(manifest["version"], "0.1.18")
        self.assertFalse((_ROOT / "www").exists())

    def test_sources_menu_save_is_footer_not_row(self) -> None:
        text = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
        helper = text.split("async def async_step_sources", 1)[1].split(
            "async def async_step_sources_done", 1
        )[0]
        self.assertIn('menu.extend(["save", "sources_done"])', helper)
        script = (_ROOT / "frontend" / "tcl_tv_flow.js").read_text(encoding="utf-8")
        self.assertIn('back: "返回"', script)
        self.assertIn('save: "保存"', script)
        self.assertIn('appearance", "plain"', script)
        self.assertIn("unelevated", script)

    def test_install_flow_www_copies_into_config_www(self) -> None:
        pkg = types.ModuleType("tcl_tv")
        pkg.__path__ = [str(_ROOT)]
        const = types.ModuleType("tcl_tv.const")
        const.DOMAIN = "tcl_tv"
        sys.modules["tcl_tv"] = pkg
        sys.modules["tcl_tv.const"] = const
        spec = importlib.util.spec_from_file_location(
            "tcl_tv.flow_ui", _ROOT / "flow_ui.py"
        )
        assert spec is not None and spec.loader is not None
        flow_ui = importlib.util.module_from_spec(spec)
        sys.modules["tcl_tv.flow_ui"] = flow_ui
        spec.loader.exec_module(flow_ui)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dest_dir = flow_ui.install_flow_www(tmp_path)
            copied = dest_dir / "tcl_tv_flow.js"
            bundled = _ROOT / "frontend" / "tcl_tv_flow.js"
            self.assertEqual(dest_dir, tmp_path / "www" / "tcl_tv")
            self.assertEqual(copied.read_bytes(), bundled.read_bytes())
            mtime = copied.stat().st_mtime_ns
            flow_ui.install_flow_www(tmp_path)
            self.assertEqual(copied.stat().st_mtime_ns, mtime)
