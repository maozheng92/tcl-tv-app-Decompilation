"""Config flow: add a TCL TV by IP; options pick IR power-on from learned codes."""
from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback

from .const import (
    CLIENT_NAME,
    CONF_ACTIVE_MAC,
    CONF_CLIENT_ID,
    CONF_MAC,
    CONF_MODEL,
    CONF_POWER_ON_COMMAND,
    CONF_POWER_ON_DEVICE,
    CONF_POWER_ON_REMOTE,
    CONF_SOFTWARE_VERSION,
    DOMAIN,
)
from .ir_flow import (
    ir_codes_filename,
    ir_details_schema,
    ir_remote_requires_device,
    remote_step_schema,
)
from .protocol import TclTvClient, TclTvError, async_probe


class TclTvConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TclTvOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client_id = uuid.uuid4().hex[:16]
            client = TclTvClient(host, CLIENT_NAME, client_id)
            identity = None
            try:
                try:
                    identity = await async_probe(host)
                except TclTvError:
                    identity = None
                info = await client.connect()
            except TclTvError:
                errors["base"] = "cannot_connect"
            else:
                mac = info.mac or (identity.mac if identity else host)
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                title = (identity.name if identity and identity.name else None) or (
                    info.model or host
                )
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_MAC: mac,
                        CONF_ACTIVE_MAC: identity.active_mac if identity else info.mac,
                        CONF_MODEL: info.model,
                        CONF_SOFTWARE_VERSION: info.software_version,
                        CONF_CLIENT_ID: client_id,
                    },
                )
            finally:
                await client.close()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )


class TclTvOptionsFlow(OptionsFlowWithReload):
    """IR power-on: pick remote, then device/command from its learned codes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        options = self.config_entry.options
        current = options.get(CONF_POWER_ON_REMOTE)
        current_s = current if isinstance(current, str) else None

        if user_input is not None:
            remote = user_input.get(CONF_POWER_ON_REMOTE)
            remote_s = remote.strip() if isinstance(remote, str) else ""
            if not remote_s:
                # Clear IR power-on → fall back to Wake-on-LAN.
                return self.async_create_entry(data={})
            self._pending_remote = remote_s  # type: ignore[attr-defined]
            return await self.async_step_ir_details()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(remote_step_schema(self.hass, current_remote=current_s)),
            errors=errors,
        )

    async def async_step_ir_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        remote = getattr(self, "_pending_remote", None) or self.config_entry.options.get(
            CONF_POWER_ON_REMOTE
        )
        if not isinstance(remote, str) or not remote.strip():
            return await self.async_step_init()
        remote = remote.strip()

        options = self.config_entry.options
        current_device = ""
        current_command = ""
        if options.get(CONF_POWER_ON_REMOTE) == remote:
            device = options.get(CONF_POWER_ON_DEVICE)
            command = options.get(CONF_POWER_ON_COMMAND)
            if isinstance(device, str):
                current_device = device
            if isinstance(command, str):
                current_command = command

        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input.get(CONF_POWER_ON_DEVICE)
            command = user_input.get(CONF_POWER_ON_COMMAND)
            device_s = device.strip() if isinstance(device, str) else ""
            command_s = command.strip() if isinstance(command, str) else ""
            if not command_s:
                errors[CONF_POWER_ON_COMMAND] = "command_required"
            elif ir_remote_requires_device(self.hass, remote) and not device_s:
                errors[CONF_POWER_ON_DEVICE] = "device_required"
            else:
                data: dict[str, Any] = {
                    CONF_POWER_ON_REMOTE: remote,
                    CONF_POWER_ON_COMMAND: command_s,
                }
                if device_s:
                    data[CONF_POWER_ON_DEVICE] = device_s
                if hasattr(self, "_pending_remote"):
                    delattr(self, "_pending_remote")
                return self.async_create_entry(data=data)

        schema = await ir_details_schema(
            self.hass,
            remote_entity_id=remote,
            current_device=current_device,
            current_command=current_command,
        )
        return self.async_show_form(
            step_id="ir_details",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "remote_entity": remote,
                "codes_file": ir_codes_filename(self.hass, remote),
            },
        )
