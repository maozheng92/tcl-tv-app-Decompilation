"""TV as a media_player: power, volume, mute, playback key and app launching."""
from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TclTvConfigEntry
from .entity import TclTvEntity, tv_errors
from .protocol import KEYS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TclTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TclTvMediaPlayer(entry.runtime_data, entry, "media_player")])


class TclTvMediaPlayer(TclTvEntity, MediaPlayerEntity):
    """Power state is "the control session is up"; there is no other signal."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        # PLAY_PAUSE was removed; HA expects PLAY and/or PAUSE. TCL only has a
        # single playback toggle key (26), so both features send the same key.
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    @property
    def state(self) -> MediaPlayerState | None:
        if not self.hub.probed:
            return None
        return MediaPlayerState.ON if self.hub.connected else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        if not self.hub.connected or self.hub.volume is None:
            return None
        return self.hub.volume / 100

    @property
    def is_volume_muted(self) -> bool | None:
        if not self.hub.connected:
            return None
        return self.hub.muted

    @property
    def source_list(self) -> list[str]:
        return [app.name for app in self.hub.apps]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.hub.info
        attrs: dict[str, Any] = {}
        if info is not None:
            attrs["tcl_model"] = info.model
            attrs["tcl_app_version"] = info.app_version
            attrs["tcl_software_version"] = info.software_version
        if self.hub.apps:
            attrs["tcl_apps"] = [
                {"name": app.name, "package": app.package} for app in self.hub.apps
            ]
        if self.hub.power_on_button:
            attrs["power_on_button"] = self.hub.power_on_button
        return attrs

    async def async_turn_on(self) -> None:
        await self.hub.async_turn_on()

    async def async_turn_off(self) -> None:
        with tv_errors():
            await self.hub.async_turn_off()

    async def async_set_volume_level(self, volume: float) -> None:
        with tv_errors():
            await self.hub.require_client().set_volume(round(volume * 100))
            await self.hub.async_refresh_volume()

    async def async_volume_up(self) -> None:
        await self._volume_key("volume_up")

    async def async_volume_down(self) -> None:
        await self._volume_key("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        with tv_errors():
            await self.hub.async_set_mute(mute)

    async def async_media_play(self) -> None:
        await self._send_named_key("playback")

    async def async_media_pause(self) -> None:
        await self._send_named_key("playback")

    async def async_media_play_pause(self) -> None:
        await self._send_named_key("playback")

    async def _volume_key(self, key: str) -> None:
        with tv_errors():
            await self.hub.require_client().send_key(KEYS[key])
            await self.hub.async_refresh_volume()

    async def _send_named_key(self, key: str) -> None:
        with tv_errors():
            await self.hub.require_client().send_key(KEYS[key])

    async def async_select_source(self, source: str) -> None:
        package = next(
            (app.package for app in self.hub.apps if app.name == source), None
        )
        if package is None:
            raise ServiceValidationError(
                f"Unknown app {source!r}; choose one of: {', '.join(self.source_list)}"
            )
        with tv_errors():
            await self.hub.require_client().launch_app(package)
