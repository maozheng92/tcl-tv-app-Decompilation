"""Config-flow helpers: list remotes and learned IR device/command names.

Mirrors the IR picker UX from maozheng92/ir_television (Broadlink, Harmony,
Xiaomi Home codes files → dropdowns).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_POWER_ON_COMMAND,
    CONF_POWER_ON_DEVICE,
    CONF_POWER_ON_REMOTE,
    DOMAIN,
)
from .ir_codes import (
    load_json_file,
    parse_broadlink_codes_payload,
    parse_harmony_config,
    parse_xiaomi_codes_payload,
    resolve_broadlink_codes_path,
    resolve_harmony_conf_path,
    resolve_xiaomi_codes_path,
)


def _text() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))


def _state_label(state: State | None, entity_id: str) -> str:
    if state is None:
        return entity_id
    name = state.name or entity_id
    if name == entity_id:
        return entity_id
    return f"{name} ({entity_id})"


def _remote_lookup(
    hass: HomeAssistant, entity_id: str | None
) -> tuple[str | None, list[str]]:
    """Return (platform, identifiers) for a remote entity."""
    if not entity_id or not isinstance(entity_id, str):
        return None, []
    identifiers: list[str] = [entity_id]
    if "." in entity_id:
        identifiers.append(entity_id.split(".", 1)[1])
    platform: str | None = None
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        ent = er.async_get(hass).async_get(entity_id)
    except Exception:  # noqa: BLE001 — registry optional in tests
        ent = None
    if ent is not None:
        platform = getattr(ent, "platform", None) or None
        unique_id = getattr(ent, "unique_id", None)
        if unique_id:
            identifiers.append(str(unique_id))
        entry_id = getattr(ent, "config_entry_id", None)
        if entry_id:
            identifiers.append(str(entry_id))
            try:
                entry = hass.config_entries.async_get_entry(entry_id)
            except Exception:  # noqa: BLE001
                entry = None
            if entry is not None:
                if getattr(entry, "unique_id", None):
                    identifiers.append(str(entry.unique_id))
                if getattr(entry, "title", None):
                    identifiers.append(str(entry.title))
                data = getattr(entry, "data", None) or {}
                if isinstance(data, dict):
                    for key in ("unique_id", "name", "hub_name"):
                        if data.get(key):
                            identifiers.append(str(data[key]))
        device_id = getattr(ent, "device_id", None)
        if device_id:
            try:
                device = dr.async_get(hass).async_get(device_id)
            except Exception:  # noqa: BLE001
                device = None
            if device is not None:
                for _domain, ident in getattr(device, "identifiers", None) or ():
                    if ident:
                        identifiers.append(str(ident))
                for conn_type, value in getattr(device, "connections", None) or ():
                    if value:
                        identifiers.append(str(value))
                    if conn_type == "mac" and value:
                        identifiers.append(str(value).replace(":", ""))
    return platform, identifiers


def _config_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(""))


def _storage_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(".storage"))


def ir_codes_file(hass: HomeAssistant, entity_id: str | None) -> Path | None:
    """Codes/conf file for this remote: Broadlink, Harmony, or Xiaomi Home."""
    platform, identifiers = _remote_lookup(hass, entity_id)
    config_dir = _config_dir(hass)
    storage_dir = _storage_dir(hass)
    if platform == "harmony" or (
        platform is None and is_harmony_remote(hass, entity_id, _lookup=False)
    ):
        return resolve_harmony_conf_path(config_dir, identifiers)
    if platform == "xiaomi_home":
        return resolve_xiaomi_codes_path(storage_dir, identifiers)
    if platform == "broadlink":
        return resolve_broadlink_codes_path(storage_dir, identifiers)
    return (
        resolve_harmony_conf_path(config_dir, identifiers)
        or resolve_xiaomi_codes_path(storage_dir, identifiers)
        or resolve_broadlink_codes_path(storage_dir, identifiers)
    )


def ir_codes_filename(hass: HomeAssistant, entity_id: str | None) -> str:
    path = ir_codes_file(hass, entity_id)
    return path.name if path is not None else "—"


def is_harmony_remote(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    _lookup: bool = True,
) -> bool:
    if not entity_id or not isinstance(entity_id, str):
        return False
    platform, identifiers = (
        _remote_lookup(hass, entity_id) if _lookup else (None, [])
    )
    if platform == "harmony":
        return True
    if platform in ("broadlink", "xiaomi_home", DOMAIN):
        return False
    if _lookup and resolve_harmony_conf_path(_config_dir(hass), identifiers):
        return True
    state = hass.states.get(entity_id) if getattr(hass, "states", None) else None
    attrs = getattr(state, "attributes", None) if state is not None else None
    return isinstance(attrs, dict) and "current_activity" in attrs


def is_xiaomi_remote(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    _lookup: bool = True,
) -> bool:
    if not entity_id or not isinstance(entity_id, str):
        return False
    platform, identifiers = (
        _remote_lookup(hass, entity_id) if _lookup else (None, [])
    )
    if platform == "xiaomi_home":
        return True
    if platform in ("broadlink", "harmony", DOMAIN):
        return False
    if not _lookup:
        return False
    return resolve_xiaomi_codes_path(_storage_dir(hass), identifiers) is not None


def ir_remote_requires_device(hass: HomeAssistant, entity_id: str | None) -> bool:
    """Harmony Hub and Xiaomi Home both require a device on send_command."""
    return is_harmony_remote(hass, entity_id) or is_xiaomi_remote(hass, entity_id)


def _is_tcl_tv_remote(hass: HomeAssistant, entity_id: str) -> bool:
    platform, _ = _remote_lookup(hass, entity_id)
    return platform == DOMAIN


def remote_dropdown(
    hass: HomeAssistant, *, current: str | None = None
) -> SelectSelector | TextSelector:
    """Dropdown of IR remotes (excludes this integration's LAN remotes)."""
    entity_ids = list(hass.states.async_entity_ids("remote"))
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for entity_id in entity_ids:
        if _is_tcl_tv_remote(hass, entity_id):
            continue
        options.append(
            {
                "value": entity_id,
                "label": _state_label(hass.states.get(entity_id), entity_id),
            }
        )
        seen.add(entity_id)
    if current and current not in seen:
        options.append({"value": current, "label": current})
    if not options:
        return _text()
    options.sort(key=lambda item: item["label"].lower())
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=False,
            sort=False,
        )
    )


def _name_dropdown(names: list[str], *, current: str = "") -> SelectSelector:
    options = list(names)
    if current and current not in options:
        options = [current, *options]
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


async def _async_read_codes(
    hass: HomeAssistant,
    resolve,
    directory: Path,
    identifiers: list[Any],
) -> Any:
    def _read() -> Any:
        return load_json_file(resolve(directory, identifiers))

    return await hass.async_add_executor_job(_read)


async def learned_ir_names(
    hass: HomeAssistant,
    *,
    remote_entity_id: str | None = None,
    device: str | None = None,
) -> tuple[list[str], list[str]]:
    """Device and command names from the selected remote's codes/conf file."""
    if not remote_entity_id:
        return [], []
    _platform, identifiers = _remote_lookup(hass, remote_entity_id)
    if is_harmony_remote(hass, remote_entity_id):
        payload = await _async_read_codes(
            hass, resolve_harmony_conf_path, _config_dir(hass), identifiers
        )
        if payload is None:
            return [], []
        devices, commands = parse_harmony_config(payload, device=device)
        if device and not commands:
            devices, commands = parse_harmony_config(payload)
        return devices, commands
    if is_xiaomi_remote(hass, remote_entity_id):
        payload = await _async_read_codes(
            hass, resolve_xiaomi_codes_path, _storage_dir(hass), identifiers
        )
        if payload is None:
            return [], []
        return parse_xiaomi_codes_payload(payload, device=device)
    payload = await _async_read_codes(
        hass, resolve_broadlink_codes_path, _storage_dir(hass), identifiers
    )
    if payload is None:
        return [], []
    return parse_broadlink_codes_payload(payload, device=device)


def remote_step_schema(
    hass: HomeAssistant, *, current_remote: str | None
) -> dict[Any, Any]:
    """Voluptuous mapping for the remote-picker step."""
    import voluptuous as vol

    field = remote_dropdown(hass, current=current_remote)
    if current_remote:
        return {vol.Optional(CONF_POWER_ON_REMOTE, default=current_remote): field}
    return {vol.Optional(CONF_POWER_ON_REMOTE): field}


async def ir_details_schema(
    hass: HomeAssistant,
    *,
    remote_entity_id: str,
    current_device: str = "",
    current_command: str = "",
) -> dict[Any, Any]:
    """Device + command dropdowns from the remote's learned codes file."""
    import voluptuous as vol

    devices, commands = await learned_ir_names(
        hass, remote_entity_id=remote_entity_id, device=current_device or None
    )
    device_field: Any = _name_dropdown(devices, current=current_device)
    if current_command:
        command_field: Any = (
            _name_dropdown(commands, current=current_command)
            if commands
            else _text()
        )
    elif commands:
        command_field = _name_dropdown(commands, current=current_command)
    else:
        command_field = _text()

    schema: dict[Any, Any] = {}
    if current_device:
        schema[vol.Optional(CONF_POWER_ON_DEVICE, default=current_device)] = (
            device_field
        )
    else:
        schema[vol.Optional(CONF_POWER_ON_DEVICE)] = device_field
    if current_command:
        schema[vol.Optional(CONF_POWER_ON_COMMAND, default=current_command)] = (
            command_field
        )
    else:
        schema[vol.Optional(CONF_POWER_ON_COMMAND)] = command_field
    return schema
