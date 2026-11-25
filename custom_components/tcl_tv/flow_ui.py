"""Load a small script that adds Save/Back footer buttons on options dialogs.

Home Assistant menus have no footer, and option forms have no back control.
The script keeps one-click menu rows and places Save on the right / Back on
the left. Hidden menu options remain as a fallback if the script does not run.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_DATA_KEY = f"{DOMAIN}_flow_ui"
_WWW = Path(__file__).resolve().parent / "www"
_URL_BASE = f"/{DOMAIN}"
_JS_NAME = "tcl_tv_flow.js"


def _version() -> str:
    manifest = Path(__file__).resolve().parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0"
    version = data.get("version")
    return str(version) if version else "0"


async def async_setup_flow_ui(hass: HomeAssistant) -> None:
    """Serve and inject the options-dialog footer script once per HA instance."""
    if hass.data.get(_DATA_KEY):
        return
    hass.data[_DATA_KEY] = True

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_URL_BASE, str(_WWW), False)]
        )
    except RuntimeError:
        pass
    add_extra_js_url(hass, f"{_URL_BASE}/{_JS_NAME}?v={_version()}")
