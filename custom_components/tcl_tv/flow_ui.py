"""Install and load the options-dialog footer script.

Home Assistant option forms only expose Cancel + Submit. The JS lives in
``frontend/`` inside the integration (not ``www/``, which Windows locks while
HA is running). Setup copies it to ``<config>/www/tcl_tv/`` (served as
``/local/``) and registers ``extra_js_url``.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_DATA_KEY = f"{DOMAIN}_flow_ui"
_BUNDLE_JS = Path(__file__).resolve().parent / "frontend" / "tcl_tv_flow.js"
_JS_NAME = "tcl_tv_flow.js"
_LOCAL_URL = f"/local/{DOMAIN}/{_JS_NAME}"


def _version() -> str:
    manifest = Path(__file__).resolve().parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0"
    version = data.get("version")
    return str(version) if version else "0"


def _try_remove_legacy_component_www() -> None:
    """Drop an old in-integration www/ folder so Windows can update the package."""
    legacy = Path(__file__).resolve().parent / "www"
    if not legacy.exists():
        return
    try:
        shutil.rmtree(legacy)
        _LOGGER.info("Removed leftover integration www folder %s", legacy)
    except OSError as err:
        _LOGGER.warning(
            "Stop Home Assistant once, then delete %s (Windows has it locked): %s",
            legacy,
            err,
        )


def install_flow_www(config_dir: str | Path) -> Path:
    """Copy the bundled footer script into ``<config>/www/tcl_tv/``."""
    dest_dir = Path(config_dir) / "www" / DOMAIN
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not _BUNDLE_JS.is_file():
        raise FileNotFoundError(f"bundled footer script missing: {_BUNDLE_JS}")
    dest = dest_dir / _JS_NAME
    data = _BUNDLE_JS.read_bytes()
    if not (dest.is_file() and dest.read_bytes() == data):
        dest.write_bytes(data)
        _LOGGER.info("Installed options footer script at %s", dest)
    _try_remove_legacy_component_www()
    return dest_dir


async def async_setup_flow_ui(hass: Any) -> None:
    """Copy the footer script into config/www and inject it once per HA instance."""
    if hass.data.get(_DATA_KEY):
        return
    hass.data[_DATA_KEY] = True

    from homeassistant.components.frontend import add_extra_js_url

    try:
        await hass.async_add_executor_job(install_flow_www, hass.config.config_dir)
    except OSError as err:
        _LOGGER.warning("Could not install %s into config/www: %s", _JS_NAME, err)
        return
    url = f"{_LOCAL_URL}?v={_version()}"
    # Module (default) plus classic script: Companion WebView is more reliable
    # with extra_js_url_es5, and a window guard prevents double-install.
    add_extra_js_url(hass, url)
    add_extra_js_url(hass, url, es5=True)
