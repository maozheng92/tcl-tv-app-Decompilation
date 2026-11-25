"""Config flow: add a TCL TV by IP; options cover IR power-on and sources."""
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
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
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
    CONF_SOURCE_NAME,
    CONF_SOURCE_ORDER,
    CONF_SOURCES,
    DOMAIN,
)
from .ir_flow import (
    button_sequence_selector,
    ir_codes_filename,
    ir_details_schema,
    ir_remote_requires_device,
    remote_step_schema,
)
from .protocol import TclTvClient, TclTvError, async_probe
from .sources import (
    ATTR_BUTTONS,
    ATTR_HIDDEN,
    ATTR_INTERVAL,
    ATTR_NAME,
    DEFAULT_INTERVAL,
    MAX_INTERVAL,
    copy_sources,
    find_source_index,
    name_in_use,
    normalize_name,
    parse_button_ids,
    parse_interval,
    saved_options,
    source_names,
    source_payload,
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
    """Draft menu: IR power-on, custom sources, then one save that reloads."""

    def __init__(self) -> None:
        self._draft_ready = False
        self._data: dict[str, Any] = {}
        self._edit_index: int | None = None
        self._pending_remote: str | None = None

    def _ensure_draft(self) -> None:
        if self._draft_ready:
            return
        options = dict(self.config_entry.options)
        remote = options.get(CONF_POWER_ON_REMOTE)
        command = options.get(CONF_POWER_ON_COMMAND)
        device = options.get(CONF_POWER_ON_DEVICE)
        self._data = {
            CONF_POWER_ON_REMOTE: remote if isinstance(remote, str) else None,
            CONF_POWER_ON_COMMAND: command if isinstance(command, str) else None,
            CONF_POWER_ON_DEVICE: device if isinstance(device, str) else None,
            CONF_SOURCES: copy_sources(options.get(CONF_SOURCES)),
        }
        self._draft_ready = True

    def _menu_placeholders(self) -> dict[str, str]:
        remote = self._data.get(CONF_POWER_ON_REMOTE)
        command = self._data.get(CONF_POWER_ON_COMMAND)
        if isinstance(remote, str) and remote and isinstance(command, str) and command:
            power_on = f"{remote} / {command}"
        else:
            power_on = "Wake-on-LAN"
        names = source_names(self._data[CONF_SOURCES])
        return {
            "power_on": power_on,
            "source_count": str(len(names)),
            "source_names": ", ".join(names) if names else "—",
        }

    def _source_schema(self, source: dict[str, Any] | None) -> vol.Schema:
        name = source[ATTR_NAME] if source else ""
        hidden = bool(source.get(ATTR_HIDDEN)) if source else False
        buttons = list(source[ATTR_BUTTONS]) if source else []
        interval = (
            parse_interval(source.get(ATTR_INTERVAL)) if source else DEFAULT_INTERVAL
        )
        name_field = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        schema: dict[Any, Any] = {}
        if name:
            schema[vol.Required(ATTR_NAME, default=name)] = name_field
        else:
            schema[vol.Required(ATTR_NAME)] = name_field
        schema[vol.Required(ATTR_HIDDEN, default=hidden)] = BooleanSelector()
        schema[vol.Required(ATTR_BUTTONS, default=buttons)] = button_sequence_selector(
            self.hass, current=buttons
        )
        schema[vol.Required(ATTR_INTERVAL, default=interval)] = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_INTERVAL,
                step=0.1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
        return vol.Schema(schema)

    def _source_pick_schema(self) -> vol.Schema:
        names = source_names(self._data[CONF_SOURCES])
        return vol.Schema(
            {
                vol.Required(CONF_SOURCE_NAME): SelectSelector(
                    SelectSelectorConfig(
                        options=names,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def _commit_source(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        name = normalize_name(user_input.get(ATTR_NAME))
        buttons = parse_button_ids(user_input.get(ATTR_BUTTONS))
        hidden = bool(user_input.get(ATTR_HIDDEN))
        interval = parse_interval(user_input.get(ATTR_INTERVAL))
        errors: dict[str, str] = {}
        if not name:
            errors[ATTR_NAME] = "name_required"
        elif name_in_use(
            self._data[CONF_SOURCES], name, exclude_index=self._edit_index
        ):
            errors[ATTR_NAME] = "name_in_use"
        if not buttons:
            errors[ATTR_BUTTONS] = "buttons_required"
        step_id = "source_add" if self._edit_index is None else "source_form"
        preview = source_payload(
            name=name or "",
            hidden=hidden,
            buttons=buttons,
            interval=interval,
        )
        if errors:
            return self.async_show_form(
                step_id=step_id,
                data_schema=self._source_schema(preview if name or buttons else None),
                errors=errors,
            )
        if self._edit_index is None:
            self._data[CONF_SOURCES].append(preview)
        else:
            self._data[CONF_SOURCES][self._edit_index] = preview
        self._edit_index = None
        return await self.async_step_sources()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        self._pending_remote = None
        return self.async_show_menu(
            step_id="init",
            menu_options=["power_on", "sources", "save"],
            description_placeholders=self._menu_placeholders(),
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        return self.async_create_entry(data=saved_options(self._data))

    async def async_step_power_on(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        errors: dict[str, str] = {}
        current = self._data.get(CONF_POWER_ON_REMOTE)
        current_s = current if isinstance(current, str) else None

        if user_input is not None:
            remote = user_input.get(CONF_POWER_ON_REMOTE)
            remote_s = remote.strip() if isinstance(remote, str) else ""
            if not remote_s:
                self._data[CONF_POWER_ON_REMOTE] = None
                self._data[CONF_POWER_ON_COMMAND] = None
                self._data[CONF_POWER_ON_DEVICE] = None
                return await self.async_step_init()
            self._pending_remote = remote_s
            return await self.async_step_ir_details()

        return self.async_show_form(
            step_id="power_on",
            data_schema=vol.Schema(
                remote_step_schema(self.hass, current_remote=current_s)
            ),
            errors=errors,
        )

    async def async_step_ir_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        remote = self._pending_remote or self._data.get(CONF_POWER_ON_REMOTE)
        if not isinstance(remote, str) or not remote.strip():
            return await self.async_step_power_on()
        remote = remote.strip()

        current_device = ""
        current_command = ""
        if self._data.get(CONF_POWER_ON_REMOTE) == remote:
            device = self._data.get(CONF_POWER_ON_DEVICE)
            command = self._data.get(CONF_POWER_ON_COMMAND)
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
                self._data[CONF_POWER_ON_REMOTE] = remote
                self._data[CONF_POWER_ON_COMMAND] = command_s
                self._data[CONF_POWER_ON_DEVICE] = device_s or None
                self._pending_remote = None
                return await self.async_step_init()

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

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        menu = ["source_add"]
        if self._data[CONF_SOURCES]:
            menu.extend(["source_edit", "source_delete"])
            if len(self._data[CONF_SOURCES]) > 1:
                menu.append("source_reorder")
        menu.append("sources_done")
        return self.async_show_menu(
            step_id="sources",
            menu_options=menu,
            description_placeholders=self._menu_placeholders(),
        )

    async def async_step_sources_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init()

    async def async_step_source_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        if user_input is not None:
            return await self._commit_source(user_input)
        return self.async_show_form(
            step_id="source_add",
            data_schema=self._source_schema(None),
        )

    async def async_step_source_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            index = find_source_index(sources, user_input.get(CONF_SOURCE_NAME, ""))
            if index is None:
                return self.async_show_form(
                    step_id="source_edit",
                    data_schema=self._source_pick_schema(),
                    errors={"base": "unknown_source"},
                )
            self._edit_index = index
            return await self.async_step_source_form()
        return self.async_show_form(
            step_id="source_edit",
            data_schema=self._source_pick_schema(),
        )

    async def async_step_source_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if self._edit_index is None or self._edit_index >= len(sources):
            self._edit_index = None
            return await self.async_step_source_edit()
        if user_input is not None:
            return await self._commit_source(user_input)
        return self.async_show_form(
            step_id="source_form",
            data_schema=self._source_schema(sources[self._edit_index]),
        )

    async def async_step_source_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            index = find_source_index(sources, user_input.get(CONF_SOURCE_NAME, ""))
            if index is not None:
                del self._data[CONF_SOURCES][index]
            return await self.async_step_sources()
        return self.async_show_form(
            step_id="source_delete",
            data_schema=self._source_pick_schema(),
        )

    async def async_step_source_reorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if len(sources) < 2:
            return await self.async_step_sources()
        names = source_names(sources)
        if user_input is not None:
            order = parse_button_ids(user_input.get(CONF_SOURCE_ORDER))
            by_name = {str(item[ATTR_NAME]): item for item in sources}
            rebuilt: list[dict[str, Any]] = []
            seen: set[str] = set()
            for name in order:
                if name in by_name and name not in seen:
                    rebuilt.append(by_name[name])
                    seen.add(name)
            for item in sources:
                name = str(item[ATTR_NAME])
                if name not in seen:
                    rebuilt.append(item)
            self._data[CONF_SOURCES] = rebuilt
            return await self.async_step_sources()
        order_selector: Any
        kwargs: dict[str, Any] = {
            "options": names,
            "multiple": True,
            "mode": SelectSelectorMode.LIST,
            "sort": False,
        }
        try:
            order_selector = SelectSelector(
                SelectSelectorConfig(**kwargs, reorder=True)
            )
        except TypeError:
            order_selector = SelectSelector(SelectSelectorConfig(**kwargs))
        return self.async_show_form(
            step_id="source_reorder",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_ORDER, default=names): order_selector,
                }
            ),
        )
