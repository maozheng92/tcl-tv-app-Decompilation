"""Keeps one TCP control session to the TV alive and fans state out to entities."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CLIENT_NAME,
    CONF_ACTIVE_MAC,
    CONF_CLIENT_ID,
    CONF_MAC,
    CONF_POWER_ON_BUTTON,
    RECONNECT_INTERVAL,
    VOLUME_POLL_INTERVAL,
)
from .protocol import TclTvClient, TclTvError, TvApp, TvInfo, async_wake

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
        self.probed = False
        self._stopping = False
        self._listeners: list[CALLBACK_TYPE] = []
        self._retry_now = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.connected

    @property
    def power_on_button(self) -> str | None:
        button = self.entry.options.get(CONF_POWER_ON_BUTTON)
        return button if isinstance(button, str) and button else None

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
        client = self.require_client()
        try:
            await client.set_mute(mute)
        except TclTvError:
            if self.muted is None or self.muted != mute:
                await client.send_key(23)
        await asyncio.sleep(0.3)
        await self.async_refresh_volume()
        if self.muted is None:
            self.muted = mute
            self._notify()

    async def async_turn_on(self) -> None:
        if self.connected:
            return
        button = self.power_on_button
        if button:
            if self.hass.states.get(button) is None:
                raise HomeAssistantError(
                    f"Power-on button {button} is missing; pick another in TCL TV options"
                )
            await self.hass.services.async_call(
                BUTTON_DOMAIN,
                "press",
                {CONF_ENTITY_ID: button},
                blocking=True,
            )
        elif self._wake_macs:
            await async_wake(self._wake_macs)
        else:
            raise HomeAssistantError(
                "No power-on button configured and no MAC for Wake-on-LAN"
            )
        self._retry_now.set()

    async def async_turn_off(self) -> None:
        if self.connected:
            await self.require_client().send_key(20)
