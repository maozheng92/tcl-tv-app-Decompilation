"""Config flow: add a TCL TV by IP; options pick an IR remote for power-on."""
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
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

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
from .protocol import TclTvClient, TclTvError, async_probe

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_POWER_ON_REMOTE): EntitySelector(
            EntitySelectorConfig(domain="remote")
        ),
        vol.Optional(CONF_POWER_ON_COMMAND): TextSelector(),
        vol.Optional(CONF_POWER_ON_DEVICE): TextSelector(),
    }
)


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
    """Configure optional IR remote power-on (Configure on the integration entry)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            remote = user_input.get(CONF_POWER_ON_REMOTE)
            command = user_input.get(CONF_POWER_ON_COMMAND)
            device = user_input.get(CONF_POWER_ON_DEVICE)
            remote_s = remote.strip() if isinstance(remote, str) else ""
            command_s = command.strip() if isinstance(command, str) else ""
            device_s = device.strip() if isinstance(device, str) else ""

            if remote_s and not command_s:
                errors[CONF_POWER_ON_COMMAND] = "command_required"
            elif command_s and not remote_s:
                errors[CONF_POWER_ON_REMOTE] = "remote_required"
            else:
                options: dict[str, Any] = {}
                if remote_s and command_s:
                    options[CONF_POWER_ON_REMOTE] = remote_s
                    options[CONF_POWER_ON_COMMAND] = command_s
                    if device_s:
                        options[CONF_POWER_ON_DEVICE] = device_s
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
            errors=errors,
        )
