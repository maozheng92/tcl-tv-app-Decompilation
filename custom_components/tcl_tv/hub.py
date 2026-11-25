"""Keeps one TCP control session to the TV alive and fans state out to entities."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.remote import DOMAIN as REMOTE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CLIENT_NAME,
    CONF_ACTIVE_MAC,
    CONF_CLIENT_ID,
    CONF_MAC,
    CONF_POWER_ON_COMMAND,
    CONF_POWER_ON_DEVICE,
    CONF_POWER_ON_REMOTE,
    CONF_SOURCES,
    RECONNECT_INTERVAL,
    VOLUME_POLL_INTERVAL,
)
from .protocol import (
    KEYS,
    MUTE_KEY,
    TclTvClient,
    TclTvError,
    TvApp,
    TvInfo,
    async_wake,
    download_screenshot,
    rewrite_screenshot_url,
    screenshot_content_type,
    screenshot_filename,
    should_toggle_mute,
)
from .screenshot import async_save_to_image_upload
from .sources import (
    ATTR_BUTTONS,
    ATTR_INTERVAL,
    ATTR_NAME,
    classify_source_action,
    copy_sources,
    find_source_index,
    visible_source_names,
)

_LOGGER = logging.getLogger(__name__)


class TclTvHub:
    """Connection supervisor; "connected" is the only power signal the TV offers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self._client_id: str = entry.data[CONF_CLIENT_ID]
        self._wake_macs = list(
            dict.fromkeys(
                mac
                for mac in (entry.data.get(CONF_ACTIVE_MAC), entry.data.get(CONF_MAC))
                if mac
            )
        )
        self.client: TclTvClient | None = None
        self.info: TvInfo | None = None
        self.volume: int | None = None
        self.muted: bool | None = None
        self.apps: list[TvApp] = []
        self.selected_source: str | None = None
        self.probed = False
        self._stopping = False
        self._listeners: list[CALLBACK_TYPE] = []
        self._retry_now = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.connected

    @property
    def power_on_remote(self) -> str | None:
        remote = self.entry.options.get(CONF_POWER_ON_REMOTE)
        return remote if isinstance(remote, str) and remote else None

    @property
    def power_on_command(self) -> str | None:
        command = self.entry.options.get(CONF_POWER_ON_COMMAND)
        return command if isinstance(command, str) and command else None

    @property
    def power_on_device(self) -> str | None:
        device = self.entry.options.get(CONF_POWER_ON_DEVICE)
        return device if isinstance(device, str) and device else None

    @property
    def sources(self) -> list[dict]:
        return copy_sources(self.entry.options.get(CONF_SOURCES))

    @property
    def visible_source_names(self) -> list[str]:
        return visible_source_names(self.sources)

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        if self._stopping:
            return
        for update in list(self._listeners):
            update()

    async def async_run(self) -> None:
        """Entry-lifetime loop: connect, poll volume, reconnect after drops."""
        while True:
            client = TclTvClient(
                self.host, CLIENT_NAME, self._client_id, on_disconnect=self._notify
            )
            try:
                info = await client.connect()
            except TclTvError as err:
                _LOGGER.debug("TV %s not reachable: %s", self.host, err)
                if not self.probed:
                    self.probed = True
                    self._notify()
            else:
                _LOGGER.debug("TV %s connected (%s)", self.host, info.model)
                self.client = client
                self.info = info
                self.probed = True
                self._notify()
                try:
                    await self._session(client)
                except asyncio.CancelledError:
                    self._stopping = True
                    raise
                finally:
                    await client.close()
                    self.client = None
                    self._notify()
            self._retry_now.clear()
            try:
                async with asyncio.timeout(RECONNECT_INTERVAL):
                    await self._retry_now.wait()
            except TimeoutError:
                pass

    async def _session(self, client: TclTvClient) -> None:
        try:
            self.apps = await client.get_apps()
        except TclTvError as err:
            _LOGGER.warning("TV %s did not list its apps: %s", self.host, err)
        else:
            self._notify()
        while client.connected:
            changed = False
            try:
                volume = await client.get_volume()
            except TclTvError:
                return
            if volume != self.volume:
                self.volume = volume
                changed = True
            muted = await client.get_mute()
            if muted is not None and muted != self.muted:
                self.muted = muted
                changed = True
            if changed:
                self._notify()
            await asyncio.sleep(VOLUME_POLL_INTERVAL)

    def require_client(self) -> TclTvClient:
        if self.client is None or not self.client.connected:
            raise TclTvError(f"TV {self.host} is off or unreachable")
        return self.client

    async def async_refresh_volume(self) -> None:
        client = self.require_client()
        self.volume = await client.get_volume()
        muted = await client.get_mute()
        if muted is not None:
            self.muted = muted
        self._notify()

    async def async_set_mute(self, mute: bool) -> None:
        """Mute/unmute using TCLPlus toggle key 23, not MagiConnect 131.

        ``131>>true`` can mute on China firmware while ``131>>false`` is a
        no-op, so a setter-only path can mute and never unmute.
        """
        client = self.require_client()
        reported = await client.get_mute()
        if should_toggle_mute(mute, reported, self.muted):
            await client.send_key(MUTE_KEY)
            await asyncio.sleep(0.3)
        await self.async_refresh_volume()
        if self.muted != mute:
            self.muted = mute
            self._notify()

    async def async_turn_on(self) -> None:
        if self.connected:
            return
        remote = self.power_on_remote
        command = self.power_on_command
        if remote and command:
            if self.hass.states.get(remote) is None:
                raise HomeAssistantError(
                    f"Power-on remote {remote} is missing; pick another in TCL TV options"
                )
            data: dict[str, object] = {
                CONF_ENTITY_ID: remote,
                "command": command,
            }
            if self.power_on_device:
                data["device"] = self.power_on_device
            await self.hass.services.async_call(
                REMOTE_DOMAIN,
                "send_command",
                data,
                blocking=True,
            )
        elif self._wake_macs:
            await async_wake(self._wake_macs)
        else:
            raise HomeAssistantError(
                "No IR power-on remote configured and no MAC for Wake-on-LAN"
            )
        self._retry_now.set()

    async def async_press_source_buttons(self, name: str) -> None:
        """Run the configured T-Cast key / button sequence for one input source."""
        sources = self.sources
        index = find_source_index(sources, name)
        if index is None:
            raise HomeAssistantError(f"Unknown input source {name!r}")
        source = sources[index]
        actions = list(source[ATTR_BUTTONS])
        interval = float(source[ATTR_INTERVAL])
        for step, action in enumerate(actions):
            classified = classify_source_action(action)
            if classified is None:
                raise HomeAssistantError(
                    f"Unknown source action {action!r}; edit the source in TCL TV options"
                )
            kind, value = classified
            if kind == "key":
                await self.require_client().send_key(KEYS[value])
            else:
                if self.hass.states.get(value) is None:
                    raise HomeAssistantError(
                        f"Source button {value} is missing; edit the source in TCL TV options"
                    )
                await self.hass.services.async_call(
                    BUTTON_DOMAIN,
                    "press",
                    {CONF_ENTITY_ID: value},
                    blocking=True,
                )
            if step < len(actions) - 1 and interval > 0:
                await asyncio.sleep(interval)
        self.selected_source = str(source[ATTR_NAME])
        self._notify()

    async def async_turn_off(self) -> None:
        if self.connected:
            await self.require_client().send_key(20)

    async def async_save_screenshot(self) -> dict:
        """Capture via T-Cast ``225>>`` and store the file in Media → Image upload."""
        client = self.require_client()
        url = await client.request_screenshot()
        url = rewrite_screenshot_url(url, self.host)
        data = await self.hass.async_add_executor_job(download_screenshot, url)
        content_type, ext = screenshot_content_type(data)
        filename = screenshot_filename(self.entry.title, dt_util.now(), ext)
        item = await async_save_to_image_upload(
            self.hass, data, filename, content_type
        )
        _LOGGER.info(
            "TV %s screenshot saved to Image upload as %s (%s)",
            self.host,
            filename,
            item.get("id"),
        )
        return item
