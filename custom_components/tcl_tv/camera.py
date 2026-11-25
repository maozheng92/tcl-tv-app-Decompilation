"""TV screenshot via T-Cast ``225>>`` (TCLShotPicProxy.shotPic)."""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TclTvConfigEntry
from .entity import TclTvEntity, tv_errors
from .protocol import download_screenshot, rewrite_screenshot_url


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TclTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TclTvCamera(entry.runtime_data, entry, "screenshot")])


class TclTvCamera(TclTvEntity, Camera):
    """On-demand still from the TV. This is not a ``149`` remote key."""

    _attr_translation_key = "screenshot"

    def __init__(self, hub, entry, key: str) -> None:
        TclTvEntity.__init__(self, hub, entry, key)
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        return self.hub.connected

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        with tv_errors():
            url = await self.hub.require_client().request_screenshot()
            url = rewrite_screenshot_url(url, self.hub.host)
            return await self.hass.async_add_executor_job(download_screenshot, url)
