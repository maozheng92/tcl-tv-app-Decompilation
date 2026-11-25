"""TV as a media_player: power, volume, mute, HDMI sources, and apps."""
from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TclTvConfigEntry
from .entity import TclTvEntity, tv_errors
from .protocol import KEYS, TvApp, resolve_app_package


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TclTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TclTvMediaPlayer(entry.runtime_data, entry, "media_player")])


class TclTvMediaPlayer(TclTvEntity, MediaPlayerEntity):
    """Power state is "the control session is up"; there is no other signal.

    Input sources are user-defined HDMI / AV names. Installed apps live in
    Media Browser (and ``play_media`` with type ``app``), matching Sony Bravia.
    """

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            # PLAY_PAUSE was removed; HA expects PLAY and/or PAUSE. TCL only has a
            # single playback toggle key (26), so both features send the same key.
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.BROWSE_MEDIA
        )
        if self.source_list:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        return features

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
    def source(self) -> str | None:
        selected = self.hub.selected_source
        if selected in self.source_list:
            return selected
        return None

    @property
    def source_list(self) -> list[str]:
        return self.hub.visible_source_names

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
        if self.hub.power_on_remote and self.hub.power_on_command:
            attrs["power_on_remote"] = self.hub.power_on_remote
            attrs["power_on_command"] = self.hub.power_on_command
            if self.hub.power_on_device:
                attrs["power_on_device"] = self.hub.power_on_device
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
        names = self.source_list
        if source not in names:
            raise ServiceValidationError(
                f"Unknown source {source!r}; choose one of: {', '.join(names) or '(none)'}"
            )
        await self.hub.async_press_source_buttons(source)

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        if media_type not in (MediaType.APP, "app", MediaType.APPS, "apps"):
            raise ServiceValidationError(
                f"Unsupported media type {media_type!r}; use app"
            )
        package = resolve_app_package(self.hub.apps, media_id)
        if package is None:
            raise ServiceValidationError(
                f"Unknown app {media_id!r}; browse Applications on this media player"
            )
        with tv_errors():
            await self.hub.require_client().launch_app(package)

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        if (
            (media_content_type is None and media_content_id is None)
            or media_content_id in ("", "apps")
            or media_content_type in (MediaType.APPS, "apps")
        ):
            return BrowseMedia(
                title="Applications",
                media_class=MediaClass.APP,
                media_content_id="apps",
                media_content_type=MediaType.APPS,
                can_play=False,
                can_expand=True,
                children=[_app_item(app) for app in self.hub.apps],
                children_media_class=MediaClass.APP,
            )
        raise BrowseError("Media not found")


def _app_item(app: TvApp) -> BrowseMedia:
    thumbnail = app.icon if app.icon.startswith("http") else None
    return BrowseMedia(
        title=app.name,
        media_class=MediaClass.APP,
        media_content_id=app.package,
        media_content_type=MediaType.APP,
        can_play=True,
        can_expand=False,
        thumbnail=thumbnail,
    )
