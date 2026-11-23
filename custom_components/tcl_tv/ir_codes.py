"""Parse Broadlink / Harmony / Xiaomi IR code files (stdlib only).

Ported from maozheng92/ir_television for power-on command dropdowns.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _harmony_function_name(func: Any) -> str:
    if not isinstance(func, dict):
        return ""
    for key in ("name", "label"):
        raw = func.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _harmony_has_device_table(config: dict[str, Any]) -> bool:
    if isinstance(config.get("device"), list):
        return True
    devices = config.get("Devices")
    if not isinstance(devices, dict):
        devices = config.get("devices")
    return isinstance(devices, dict)


def _harmony_command_names(raw: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = value.strip()
        if text and text not in seen:
            seen.add(text)
            names.append(text)

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                cmd = _harmony_function_name(item)
                if cmd:
                    add(cmd)
    elif isinstance(raw, dict):
        for key in raw:
            if isinstance(key, str):
                add(key)
    return names


def _parse_harmony_devices_map(
    devices_map: dict[str, Any], wanted: str
) -> tuple[list[str], list[str]]:
    """HA Harmony cache: ``{"Apple TV": {"commands": [...], "id": "…"}}``."""
    devices: list[str] = []
    commands: list[str] = []
    seen_commands: set[str] = set()
    for raw_name, info in devices_map.items():
        label = str(raw_name).strip() if raw_name is not None else ""
        if not label:
            continue
        devices.append(label)
        ident = ""
        raw_cmds: Any = None
        if isinstance(info, dict):
            device_id = info.get("id")
            if device_id is not None and str(device_id).strip():
                ident = str(device_id).strip()
            raw_cmds = info.get("commands")
        elif isinstance(info, list):
            raw_cmds = info
        aliases = [label]
        if ident and ident.lower() != label.lower():
            aliases.append(ident)
        if wanted and not any(name.lower() == wanted for name in aliases):
            continue
        for cmd in _harmony_command_names(raw_cmds):
            if cmd not in seen_commands:
                seen_commands.add(cmd)
                commands.append(cmd)
    return devices, commands


def parse_harmony_config(
    payload: Any,
    *,
    device: str | None = None,
) -> tuple[list[str], list[str]]:
    """Extract Harmony Hub device names and IR command names.

    Accepts the Home Assistant Harmony cache
    (``{"Devices": {"Apple TV": {"commands": [...], "id": "…"}, ...}}``)
    and the older hub dump (``{"device": [{"label": ..., "controlGroup": ...}]}``).
    When ``device`` is set, command names are limited to that device
    (matched by name or id, case-insensitive).
    """
    devices: list[str] = []
    commands: list[str] = []
    seen_devices: set[str] = set()
    seen_commands: set[str] = set()
    if not isinstance(payload, dict):
        return [], []
    nested = payload.get("config")
    if isinstance(nested, dict) and _harmony_has_device_table(nested):
        config = nested
    else:
        config = payload
    if not isinstance(config, dict):
        return [], []
    wanted = str(device).strip().lower() if device else ""
    devices_map = config.get("Devices")
    if not isinstance(devices_map, dict):
        devices_map = config.get("devices")
    if isinstance(devices_map, dict):
        return _parse_harmony_devices_map(devices_map, wanted)
    raw_devices = config.get("device")
    if not isinstance(raw_devices, list):
        return [], []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("name")
        device_id = item.get("id")
        names: list[str] = []
        if isinstance(label, str) and label.strip():
            names.append(label.strip())
        if device_id is not None and str(device_id).strip():
            ident = str(device_id).strip()
            if ident not in names:
                names.append(ident)
        for name in names:
            if name not in seen_devices:
                seen_devices.add(name)
                devices.append(name)
        match = (not wanted) or any(name.lower() == wanted for name in names)
        if not match:
            continue
        for group in item.get("controlGroup") or []:
            if not isinstance(group, dict):
                continue
            functions = group.get("function") or []
            if not isinstance(functions, list):
                continue
            for func in functions:
                cmd = _harmony_function_name(func)
                if cmd and cmd not in seen_commands:
                    seen_commands.add(cmd)
                    commands.append(cmd)
        extra_cmds = item.get("commands")
        for cmd in _harmony_command_names(extra_cmds):
            if cmd not in seen_commands:
                seen_commands.add(cmd)
                commands.append(cmd)
    return devices, commands


def parse_broadlink_codes_payload(
    payload: Any,
    *,
    device: str | None = None,
) -> tuple[list[str], list[str]]:
    """Extract learned Broadlink device and command names from a codes file.

    Accepts either the storage wrapper ``{"data": {...}}`` or the inner mapping
    ``{device_name: {command_name: code}}``.
    When ``device`` is set, command names are limited to that device
    (matched case-insensitive).
    """
    devices: set[str] = set()
    commands: set[str] = set()
    if not isinstance(payload, dict):
        return [], []
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(inner, dict):
        return [], []
    wanted = str(device).strip().lower() if device else ""
    for device_name, cmds in inner.items():
        name = str(device_name).strip() if device_name is not None else ""
        if name:
            devices.add(name)
        if wanted and name.lower() != wanted:
            continue
        if not isinstance(cmds, dict):
            continue
        for command in cmds:
            cmd = str(command).strip() if command is not None else ""
            if cmd:
                commands.add(cmd)
    return sorted(devices), sorted(commands)


def expand_remote_identifiers(values: list[Any]) -> list[str]:
    """Unique filename tokens from entity / config unique ids and MACs."""
    result: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)

    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        add(text)
        if text.lower().endswith("-remote"):
            add(text[: -len("-remote")])
        no_colon = text.replace(":", "")
        add(no_colon)
        compact = "".join(ch.lower() for ch in text if ch.isalnum())
        add(compact)
        if compact.endswith("remote") and len(compact) > 6:
            add(compact[: -len("remote")])
    return result


def resolve_broadlink_codes_path(
    storage_dir: Path | str, identifiers: list[Any]
) -> Path | None:
    """Return ``.storage/broadlink_remote_{mac}_codes`` for this Broadlink remote."""
    directory = Path(storage_dir)
    if not directory.is_dir():
        return None
    for ident in expand_remote_identifiers(identifiers):
        token = "".join(ch.lower() for ch in ident if ch.isalnum())
        if not token:
            continue
        path = directory / f"broadlink_remote_{token}_codes"
        if path.is_file():
            return path
        path = directory / f"broadlink_remote_{ident}_codes"
        if path.is_file():
            return path
    return None


# Xiaomi Home (ha_xiaomi_home) universal remote, chuangmi.ir.v2.
# Learned codes live in ``.storage/xiaomi_home_remote_{did}_codes``.
# Device identifiers use ``slugify("{cloud_server}_{did}")``.
XIAOMI_CLOUD_PREFIXES = ("cn_", "de_", "i2_", "ru_", "sg_", "us_")
_XIAOMI_CODES_NAME = re.compile(r"^xiaomi_home_remote_(.+)_codes$")


def parse_xiaomi_codes_payload(
    payload: Any,
    *,
    device: str | None = None,
) -> tuple[list[str], list[str]]:
    """Extract learned Xiaomi universal-remote device and command names.

    Accepts the Home Assistant Store file
    (``{"version": 1, "key": "xiaomi_home_remote_{did}_codes", "data": {...}}``)
    or the inner map ``{device_name: {command_name: code}}``.
    A command value may be a base64 string or a two-code toggle list; only
    the command name is used. When ``device`` is set, command names are
    limited to that device (matched case-insensitive).
    """
    return parse_broadlink_codes_payload(payload, device=device)


def _safe_storage_token(token: str) -> str | None:
    text = token.strip()
    if not text or "/" in text or "\\" in text or text in (".", ".."):
        return None
    return text


def _xiaomi_codes_file(directory: Path, did: str) -> Path | None:
    seen: set[str] = set()
    for raw in (did, did.lower()):
        token = _safe_storage_token(raw)
        if not token or token in seen:
            continue
        seen.add(token)
        path = directory / f"xiaomi_home_remote_{token}_codes"
        if path.is_file():
            return path
    return None


def _identifier_mentions(token: str, identifiers: list[str]) -> bool:
    """True when ``token`` appears as its own id inside any identifier."""
    if len(token) < 4:
        return False
    variants = {token}
    slug = "".join(ch if ch.isalnum() else "_" for ch in token)
    if slug and slug != token:
        variants.add(slug)
    for text in identifiers:
        for variant in variants:
            if re.search(
                rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            ):
                return True
    return False


def resolve_xiaomi_codes_path(
    storage_dir: Path | str, identifiers: list[Any]
) -> Path | None:
    """Return ``.storage/xiaomi_home_remote_{did}_codes`` for this remote.

    ``did`` is the Xiaomi device id. Entity and device identifiers usually
    carry ``{cloud}_{did}`` (for example ``cn_123456789``) or a unique id
    that contains that tag.
    """
    directory = Path(storage_dir)
    if not directory.is_dir():
        return None
    idents = expand_remote_identifiers(identifiers)
    for ident in idents:
        found = _xiaomi_codes_file(directory, ident)
        if found is not None:
            return found
        lower = ident.lower()
        for prefix in XIAOMI_CLOUD_PREFIXES:
            if lower.startswith(prefix):
                found = _xiaomi_codes_file(directory, ident[len(prefix) :])
                if found is not None:
                    return found
    matches: list[tuple[int, Path]] = []
    try:
        paths = list(directory.glob("xiaomi_home_remote_*_codes"))
    except OSError:
        return None
    for path in paths:
        match = _XIAOMI_CODES_NAME.match(path.name)
        if match is None or not path.is_file():
            continue
        did = match.group(1)
        if _identifier_mentions(did, idents):
            matches.append((len(did), path))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1].name))
    return matches[0][1]


def resolve_harmony_conf_path(
    config_dir: Path | str, identifiers: list[Any]
) -> Path | None:
    """Return ``harmony_{unique_id}.conf`` for this Harmony Hub."""
    directory = Path(config_dir)
    if not directory.is_dir():
        return None
    for ident in expand_remote_identifiers(identifiers):
        path = directory / f"harmony_{ident}.conf"
        if path.is_file():
            return path
    return None


def load_json_file(path: Path | str | None) -> Any:
    """Read a JSON object from disk, or None if missing / invalid.

    This is blocking I/O. Callers on the event loop must run it via
    ``hass.async_add_executor_job``.
    """
    if path is None:
        return None
    file_path = Path(path)
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
