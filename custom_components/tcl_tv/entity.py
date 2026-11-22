"""Shared entity plumbing for the TCL TV integration."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_MAC, CONF_MODEL, CONF_SOFTWARE_VERSION, DOMAIN
from .hub import TclTvHub
from .protocol import TclTvError


@contextmanager
def tv_errors() -> Iterator[None]:
    """Surface TV transport failures as service-call errors."""
    try:
        yield
    except TclTvError as err:
        raise HomeAssistantError(str(err)) from err


class TclTvEntity(Entity):
    """Entity bound to one TV; state comes from the hub, never polled by HA."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TclTvHub, entry: ConfigEntry, key: str) -> None:
        self.hub = hub
        mac = entry.data[CONF_MAC]
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer="TCL",
            model=entry.data.get(CONF_MODEL),
            sw_version=entry.data.get(CONF_SOFTWARE_VERSION),
            name=entry.title,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_add_listener(self.async_write_ha_state))
