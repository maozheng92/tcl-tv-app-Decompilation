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
    button_choice_selector,
    format_action_label,
    format_source_sequence,
    ir_codes_filename,
    ir_details_schema,
    ir_remote_requires_device,
    ordered_choice_selector,
    remote_step_schema,
    source_kind_label,
    tcl_key_choice_selector,
)
from .protocol import TclTvClient, TclTvError, async_probe
from .sources import (
    ATTR_ACTIONS,
    ATTR_ADD_MORE,
    ATTR_BUTTONS,
    ATTR_EDIT_SEQUENCE,
    ATTR_GO_BACK,
    ATTR_HIDDEN,
    ATTR_INTERVAL,
    ATTR_NAME,
    DEFAULT_INTERVAL,
    KIND_BUTTON,
    KIND_KEY,
    MAX_INTERVAL,
    SOURCE_REPEAT_MAX,
    SOURCE_REPEAT_MIN,
    copy_sources,
    counts_for_kind,
    expand_source_steps,
    find_source_index,
    name_in_use,
    normalize_name,
    parse_button_ids,
    parse_interval,
    parse_repeat,
    saved_options,
    sequence_kind,
    source_names,
    source_payload,
    unique_actions_of_kind,
    unknown_source_actions,
)


def _go_back_chosen(value: Any) -> bool:
    """True when the footer Back button posted ``go_back``."""
    if value in (True, ATTR_GO_BACK, "true", "1", 1):
        return True
    if isinstance(value, (list, tuple)):
        return any(_go_back_chosen(item) for item in value)
    return False


class _SchemaWithBack(vol.Schema):
    """Accept ``{go_back: True}`` from the footer Back button without other fields."""

    def __call__(self, data: Any) -> Any:
        if isinstance(data, dict) and _go_back_chosen(data.get(ATTR_GO_BACK)):
            return {ATTR_GO_BACK: True}
        return super().__call__(data)


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
        self._source_meta: dict[str, Any] | None = None
        self._source_original_buttons: list[str] = []
        self._seq_kind: str | None = None
        self._seq_picked: list[str] = []
        self._seq_counts: dict[str, int] = {}
        self._seq_actions: list[str] = []

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

    def _wants_back(self, user_input: dict[str, Any] | None) -> bool:
        return bool(user_input) and _go_back_chosen(user_input.get(ATTR_GO_BACK))

    def _with_back(self, schema: vol.Schema | dict[Any, Any]) -> vol.Schema:
        # No in-form Go-back control. frontend/tcl_tv_flow.js posts
        # {go_back: True} from the dialog footer (返回 left, 提交 right).
        mapping = schema.schema if isinstance(schema, vol.Schema) else schema
        return _SchemaWithBack(mapping)

    def _show_form(
        self,
        step_id: str,
        schema: vol.Schema | dict[Any, Any],
        *,
        errors: dict[str, str] | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        kwargs: dict[str, Any] = {
            "step_id": step_id,
            "data_schema": self._with_back(schema),
        }
        if errors:
            kwargs["errors"] = errors
        if placeholders is not None:
            kwargs["description_placeholders"] = placeholders
        return self.async_show_form(**kwargs)

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

    def _reset_source_seq(self) -> None:
        self._source_meta = None
        self._source_original_buttons = []
        self._seq_kind = None
        self._seq_picked = []
        self._seq_counts = {}
        self._seq_actions = []

    def _sequence_preview(self) -> str:
        actions = self._seq_actions or self._source_original_buttons
        return format_source_sequence(self.hass, actions)

    def _source_meta_schema(
        self, source: dict[str, Any] | None, *, editing: bool
    ) -> vol.Schema:
        name = source[ATTR_NAME] if source else ""
        hidden = bool(source.get(ATTR_HIDDEN)) if source else False
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
        schema[vol.Required(ATTR_INTERVAL, default=interval)] = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_INTERVAL,
                step=0.1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
        if editing:
            schema[vol.Required(ATTR_EDIT_SEQUENCE, default=False)] = BooleanSelector()
        return vol.Schema(schema)

    def _store_source_meta(self, user_input: dict[str, Any]) -> None:
        self._source_meta = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
        }

    def _source_meta_errors(self, user_input: dict[str, Any]) -> dict[str, str]:
        name = normalize_name(user_input.get(ATTR_NAME))
        errors: dict[str, str] = {}
        if not name:
            errors[ATTR_NAME] = "name_required"
        elif name_in_use(
            self._data[CONF_SOURCES], name, exclude_index=self._edit_index
        ):
            errors[ATTR_NAME] = "name_in_use"
        return errors

    def _repeat_schema(self) -> vol.Schema:
        number = NumberSelector(
            NumberSelectorConfig(
                min=SOURCE_REPEAT_MIN,
                max=SOURCE_REPEAT_MAX,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="×",
            )
        )
        schema: dict[Any, Any] = {}
        for index, action in enumerate(self._seq_picked):
            schema[
                vol.Required(
                    f"repeat_{index}",
                    default=int(self._seq_counts.get(action, 1)),
                )
            ] = number
        schema[vol.Required(ATTR_ADD_MORE, default=False)] = BooleanSelector()
        return vol.Schema(schema)

    def _pick_defaults(self) -> list[str]:
        if self._seq_picked:
            return list(self._seq_picked)
        if self._seq_actions or self._seq_kind is None:
            return []
        original = self._source_original_buttons
        if sequence_kind(original) == self._seq_kind:
            return unique_actions_of_kind(original, self._seq_kind)
        return []

    def _count_defaults(self, picked: list[str]) -> dict[str, int]:
        defaults: dict[str, int] = {}
        original = self._source_original_buttons
        if not self._seq_actions and self._seq_kind is not None:
            if sequence_kind(original) == self._seq_kind:
                defaults.update(counts_for_kind(original, self._seq_kind))
        defaults.update(self._seq_counts)
        return {action: int(defaults.get(action, 1)) for action in picked}

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

    async def _finish_source(self) -> ConfigFlowResult:
        meta = self._source_meta
        if not meta or not self._seq_actions:
            return await self.async_step_source_seq_kind()
        preview = source_payload(
            name=str(meta[ATTR_NAME]),
            hidden=bool(meta[ATTR_HIDDEN]),
            buttons=list(self._seq_actions),
            interval=parse_interval(meta[ATTR_INTERVAL]),
        )
        if self._edit_index is None:
            self._data[CONF_SOURCES].append(preview)
        else:
            self._data[CONF_SOURCES][self._edit_index] = preview
        self._edit_index = None
        self._reset_source_seq()
        return await self.async_step_sources()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        self._pending_remote = None
        self._reset_source_seq()
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
            if self._wants_back(user_input):
                return await self.async_step_init()
            remote = user_input.get(CONF_POWER_ON_REMOTE)
            remote_s = remote.strip() if isinstance(remote, str) else ""
            if not remote_s:
                self._data[CONF_POWER_ON_REMOTE] = None
                self._data[CONF_POWER_ON_COMMAND] = None
                self._data[CONF_POWER_ON_DEVICE] = None
                return await self.async_step_init()
            self._pending_remote = remote_s
            return await self.async_step_ir_details()

        return self._show_form(
            "power_on",
            remote_step_schema(self.hass, current_remote=current_s),
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
            if self._wants_back(user_input):
                return await self.async_step_power_on()
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
        return self._show_form(
            "ir_details",
            schema,
            errors=errors,
            placeholders={
                "remote_entity": remote,
                "codes_file": ir_codes_filename(self.hass, remote),
            },
        )

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        self._reset_source_seq()
        menu = ["source_add"]
        if self._data[CONF_SOURCES]:
            menu.extend(["source_edit", "source_delete"])
            if len(self._data[CONF_SOURCES]) > 1:
                menu.append("source_reorder")
        # save / sources_done are footer actions; the frontend script hides the rows.
        menu.extend(["save", "sources_done"])
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
        if user_input is None:
            if self._source_meta is None:
                self._reset_source_seq()
                schema = self._source_meta_schema(None, editing=False)
            else:
                schema = self._source_meta_schema(self._source_meta, editing=False)
            return self._show_form("source_add", schema)
        if self._wants_back(user_input):
            return await self.async_step_sources()
        preview = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
        }
        errors = self._source_meta_errors(user_input)
        if errors:
            return self._show_form(
                "source_add",
                self._source_meta_schema(preview, editing=False),
                errors=errors,
            )
        self._store_source_meta(user_input)
        self._seq_actions = []
        self._source_original_buttons = []
        return await self.async_step_source_seq_kind()

    async def async_step_source_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
            index = find_source_index(sources, user_input.get(CONF_SOURCE_NAME, ""))
            if index is None:
                return self._show_form(
                    "source_edit",
                    self._source_pick_schema(),
                    errors={"base": "unknown_source"},
                )
            self._edit_index = index
            self._source_meta = None
            return await self.async_step_source_form()
        return self._show_form("source_edit", self._source_pick_schema())

    async def async_step_source_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if self._edit_index is None or self._edit_index >= len(sources):
            self._edit_index = None
            return await self.async_step_source_edit()
        existing = sources[self._edit_index]
        if user_input is None:
            shown = dict(existing)
            if self._source_meta:
                shown.update(self._source_meta)
            self._source_original_buttons = list(existing[ATTR_BUTTONS])
            return self._show_form(
                "source_form",
                self._source_meta_schema(shown, editing=True),
                placeholders={"sequence": self._sequence_preview()},
            )
        if self._wants_back(user_input):
            self._source_meta = None
            return await self.async_step_source_edit()
        preview = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
            ATTR_BUTTONS: list(existing[ATTR_BUTTONS]),
        }
        errors = self._source_meta_errors(user_input)
        if errors:
            return self._show_form(
                "source_form",
                self._source_meta_schema(preview, editing=True),
                errors=errors,
                placeholders={"sequence": self._sequence_preview()},
            )
        self._store_source_meta(user_input)
        self._source_original_buttons = list(existing[ATTR_BUTTONS])
        if not user_input.get(ATTR_EDIT_SEQUENCE):
            self._seq_actions = list(existing[ATTR_BUTTONS])
            return await self._finish_source()
        self._seq_actions = []
        return await self.async_step_source_seq_kind()

    async def async_step_source_seq_kind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if not self._source_meta:
            return await self.async_step_sources()
        return self.async_show_menu(
            step_id="source_seq_kind",
            menu_options=[
                "source_seq_keys",
                "source_seq_buttons",
                "source_seq_kind_back",
            ],
            description_placeholders={"sequence": self._sequence_preview()},
        )

    async def async_step_source_seq_kind_back(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._edit_index is None:
            return await self.async_step_source_add()
        return await self.async_step_source_form()

    async def async_step_source_seq_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._seq_kind = KIND_KEY
        return await self.async_step_source_seq_pick()

    async def async_step_source_seq_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._seq_kind = KIND_BUTTON
        return await self.async_step_source_seq_pick()

    async def async_step_source_seq_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if self._seq_kind not in (KIND_KEY, KIND_BUTTON) or not self._source_meta:
            return await self.async_step_source_seq_kind()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_source_seq_kind()
            raw = user_input.get(ATTR_ACTIONS)
            unknown = unknown_source_actions(raw)
            picked = unique_actions_of_kind(raw, self._seq_kind)
            if unknown:
                errors[ATTR_ACTIONS] = "unknown_action"
            elif not picked:
                errors[ATTR_ACTIONS] = "pick_required"
            else:
                self._seq_picked = picked[:SOURCE_REPEAT_MAX]
                self._seq_counts = self._count_defaults(self._seq_picked)
                return await self.async_step_source_seq_repeat()
        defaults = self._pick_defaults()
        if self._seq_kind == KIND_KEY:
            selector: Any = tcl_key_choice_selector(self.hass)
        else:
            selector = button_choice_selector(self.hass, current=defaults)
        return self._show_form(
            "source_seq_pick",
            {vol.Required(ATTR_ACTIONS, default=defaults): selector},
            errors=errors,
            placeholders={
                "kind": source_kind_label(self.hass, self._seq_kind),
                "sequence": self._sequence_preview(),
            },
        )

    async def async_step_source_seq_repeat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if not self._seq_picked or not self._source_meta:
            return await self.async_step_source_seq_pick()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_source_seq_pick()
            steps = [
                (action, parse_repeat(user_input.get(f"repeat_{index}")))
                for index, action in enumerate(self._seq_picked)
            ]
            self._seq_actions.extend(expand_source_steps(steps))
            self._seq_picked = []
            self._seq_counts = {}
            self._seq_kind = None
            if user_input.get(ATTR_ADD_MORE):
                return await self.async_step_source_seq_kind()
            return await self._finish_source()
        repeat_help = "\n".join(
            f"{index + 1}. {format_action_label(self.hass, action)}"
            for index, action in enumerate(self._seq_picked)
        )
        placeholders = {
            "sequence": format_source_sequence(self.hass, self._seq_actions),
            "repeat_help": repeat_help,
        }
        for index in range(SOURCE_REPEAT_MAX):
            placeholders[f"item_{index}"] = ""
        for index, action in enumerate(self._seq_picked):
            placeholders[f"item_{index}"] = format_action_label(self.hass, action)
        return self._show_form(
            "source_seq_repeat",
            self._repeat_schema(),
            placeholders=placeholders,
        )

    async def async_step_source_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
            index = find_source_index(sources, user_input.get(CONF_SOURCE_NAME, ""))
            if index is not None:
                del self._data[CONF_SOURCES][index]
            return await self.async_step_sources()
        return self._show_form("source_delete", self._source_pick_schema())

    async def async_step_source_reorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_SOURCES]
        if len(sources) < 2:
            return await self.async_step_sources()
        names = source_names(sources)
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
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
        return self._show_form(
            "source_reorder",
            {
                vol.Required(
                    CONF_SOURCE_ORDER, default=names
                ): ordered_choice_selector(names),
            },
        )
