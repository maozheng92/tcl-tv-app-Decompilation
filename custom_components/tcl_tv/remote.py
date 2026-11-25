"""Full key set of the TCL+ phone remote as a remote entity."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TclTvConfigEntry
from .entity import TclTvEntity, tv_errors
from .protocol import KEY_ALIASES, KEYS, LIVE_TV_NAMES, resolve_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TclTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TclTvRemote(entry.runtime_data, entry, "remote")])


class TclTvRemote(TclTvEntity, RemoteEntity):
    """``remote.send_command`` takes key names from ``protocol.KEYS``."""

    _attr_name = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"commands": list(KEYS)}

    @property
    def is_on(self) -> bool | None:
        return self.hub.connected if self.hub.probed else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        with tv_errors():
            await self.hub.async_turn_off()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        names = list(command)
        live = [name for name in names if name in LIVE_TV_NAMES]
        if live:
            raise ServiceValidationError(
                "TCLPlus has no T-Cast key for 直播 / live / tv; open the live-TV "
                "app with media_player.play_media (media_content_type: app)"
            )
        codes: list[int] = []
        unknown: list[str] = []
        for name in names:
            code = resolve_key(name)
            if code is None:
                unknown.append(name)
            else:
                codes.append(code)
        if unknown:
            aliases = ", ".join(
                f"{alias}={canonical}" for alias, canonical in KEY_ALIASES.items()
            )
            raise ServiceValidationError(
                f"Unknown TCL key(s) {', '.join(unknown)}; "
                f"valid keys: {', '.join(KEYS)}; aliases: {aliases}"
            )
        repeats: int = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay: float = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        with tv_errors():
            client = self.hub.require_client()
            for i in range(repeats):
                for j, code in enumerate(codes):
                    if i or j:
                        await asyncio.sleep(delay)
                    await client.send_key(code)
        if any(name in ("volume_up", "volume_down", "mute") for name in names):
            with tv_errors():
                await self.hub.async_refresh_volume()
