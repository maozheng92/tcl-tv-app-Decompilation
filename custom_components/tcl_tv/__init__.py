"""TCL TV control over the TCL+ / T-Cast LAN remote protocol (TCP 6553)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .hub import TclTvHub

type TclTvConfigEntry = ConfigEntry[TclTvHub]

__all__ = [
    "DOMAIN",
    "TclTvConfigEntry",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register the options-dialog footer script."""
    from .flow_ui import async_setup_flow_ui

    await async_setup_flow_ui(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TclTvConfigEntry) -> bool:
    from .flow_ui import async_setup_flow_ui

    await async_setup_flow_ui(hass)
    hub = TclTvHub(hass, entry)
    entry.runtime_data = hub
    # A powered-off TV is a normal state, not a setup failure: entities report
    # "off" until the session comes up.
    entry.async_create_background_task(hass, hub.async_run(), f"tcl_tv {hub.host}")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TclTvConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and entry.runtime_data.client is not None:
        await entry.runtime_data.client.close()
    return unloaded
