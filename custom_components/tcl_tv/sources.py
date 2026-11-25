"""Manual HDMI / input-source records stored in config-entry options.

T-Cast does not expose a stable HDMI inventory, so the user names each
source and a sequence of ``button.*`` entities that switch to it (for
example Source → Right → OK).
"""

from __future__ import annotations

from typing import Any

ATTR_NAME = "name"
ATTR_HIDDEN = "hidden"
ATTR_BUTTONS = "buttons"
ATTR_INTERVAL = "interval"

DEFAULT_INTERVAL = 0.4
MAX_INTERVAL = 10.0


def normalize_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())


def parse_button_ids(raw: Any) -> list[str]:
    """Preserve order; drop blanks and duplicates."""
    if raw is None:
        items: list[Any] = []
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        entity_id = item.strip()
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        out.append(entity_id)
    return out


def parse_interval(raw: Any) -> float:
    if raw is None or raw == "":
        return DEFAULT_INTERVAL
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    if value < 0:
        return 0.0
    if value > MAX_INTERVAL:
        return MAX_INTERVAL
    return value


def copy_sources(raw: Any) -> list[dict[str, Any]]:
    """Keep only well-formed source dicts, in order."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get(ATTR_NAME))
        if not name or name.casefold() in seen:
            continue
        buttons = parse_button_ids(item.get(ATTR_BUTTONS))
        if not buttons:
            continue
        seen.add(name.casefold())
        out.append(
            {
                ATTR_NAME: name,
                ATTR_HIDDEN: bool(item.get(ATTR_HIDDEN)),
                ATTR_BUTTONS: buttons,
                ATTR_INTERVAL: parse_interval(item.get(ATTR_INTERVAL)),
            }
        )
    return out


def source_payload(
    *,
    name: str,
    hidden: bool,
    buttons: list[str],
    interval: float,
) -> dict[str, Any]:
    return {
        ATTR_NAME: name,
        ATTR_HIDDEN: bool(hidden),
        ATTR_BUTTONS: list(buttons),
        ATTR_INTERVAL: parse_interval(interval),
    }


def find_source_index(sources: list[dict[str, Any]], name: str) -> int | None:
    wanted = normalize_name(name).casefold()
    if not wanted:
        return None
    for index, source in enumerate(sources):
        if str(source.get(ATTR_NAME, "")).casefold() == wanted:
            return index
    return None


def visible_source_names(sources: list[dict[str, Any]]) -> list[str]:
    return [
        str(source[ATTR_NAME])
        for source in sources
        if not source.get(ATTR_HIDDEN)
    ]


def source_names(sources: list[dict[str, Any]]) -> list[str]:
    return [str(source[ATTR_NAME]) for source in sources]


def name_in_use(
    sources: list[dict[str, Any]], name: str, *, exclude_index: int | None = None
) -> bool:
    wanted = normalize_name(name).casefold()
    if not wanted:
        return False
    for index, source in enumerate(sources):
        if exclude_index is not None and index == exclude_index:
            continue
        if str(source.get(ATTR_NAME, "")).casefold() == wanted:
            return True
    return False


def saved_options(draft: dict[str, Any]) -> dict[str, Any]:
    """Persist IR power-on and custom sources together; omit empty sections."""
    data: dict[str, Any] = {}
    remote = draft.get("power_on_remote")
    command = draft.get("power_on_command")
    remote_s = remote.strip() if isinstance(remote, str) else ""
    command_s = command.strip() if isinstance(command, str) else ""
    if remote_s and command_s:
        data["power_on_remote"] = remote_s
        data["power_on_command"] = command_s
        device = draft.get("power_on_device")
        device_s = device.strip() if isinstance(device, str) else ""
        if device_s:
            data["power_on_device"] = device_s
    sources = copy_sources(draft.get("sources"))
    if sources:
        data["sources"] = sources
    return data
