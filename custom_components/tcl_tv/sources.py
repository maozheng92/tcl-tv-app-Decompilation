"""Manual HDMI / input-source records stored in config-entry options.

T-Cast does not expose a stable HDMI inventory, so the user names each
source and a press sequence that switches to it (this integration's
T-Cast keys and/or ``button.*`` entities, for example source → right → ok).
"""

from __future__ import annotations

from typing import Any

ATTR_NAME = "name"
ATTR_HIDDEN = "hidden"
ATTR_BUTTONS = "buttons"
ATTR_INTERVAL = "interval"

DEFAULT_INTERVAL = 0.4
MAX_INTERVAL = 10.0

# Select selectors cannot repeat the same value, so each T-Cast key is
# offered as several unique tokens that all decode back to the key name.
SOURCE_KEY_SLOT_MAX = 8
_SOURCE_KEY_PREFIX = "key:"

# Names only; keep in sync with protocol.KEYS (this file is tested offline).
TCL_SOURCE_KEYS = frozenset(
    {
        "up",
        "down",
        "left",
        "right",
        "ok",
        "back",
        "menu",
        "home",
        "power",
        "volume_up",
        "volume_down",
        "mute",
        "source",
        "smart_tv",
    }
)


def normalize_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())


def _token_list(raw: Any) -> list[str]:
    if raw is None:
        items: list[Any] = []
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if token:
            out.append(token)
    return out


def parse_button_ids(raw: Any) -> list[str]:
    """Preserve order; drop blanks and duplicates (source-name reorder lists)."""
    out: list[str] = []
    seen: set[str] = set()
    for token in _token_list(raw):
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def classify_source_action(action: str) -> tuple[str, str] | None:
    """Return ``('key', name)`` or ``('button', entity_id)``; else ``None``."""
    token = action.strip() if isinstance(action, str) else ""
    if not token:
        return None
    if token.startswith(_SOURCE_KEY_PREFIX):
        name = token.split(":", 2)[1] if token.count(":") >= 1 else ""
        if name in TCL_SOURCE_KEYS:
            return ("key", name)
        return None
    if token in TCL_SOURCE_KEYS:
        return ("key", token)
    if token.startswith("button.") and token.count(".") == 1 and token.split(".", 1)[1]:
        return ("button", token)
    return None


def parse_source_actions(raw: Any) -> list[str]:
    """Press sequence: T-Cast key names and ``button.*`` ids. Repeats kept."""
    out: list[str] = []
    for token in _token_list(raw):
        classified = classify_source_action(token)
        if classified is None:
            continue
        out.append(classified[1])
    return out


def unknown_source_actions(raw: Any) -> list[str]:
    return [token for token in _token_list(raw) if classify_source_action(token) is None]


def encode_source_actions(actions: list[str]) -> list[str]:
    """Unique form tokens so the same T-Cast key can appear more than once."""
    counts: dict[str, int] = {}
    out: list[str] = []
    for action in actions:
        classified = classify_source_action(action)
        if classified is None:
            continue
        kind, value = classified
        if kind != "key":
            out.append(value)
            continue
        counts[value] = counts.get(value, 0) + 1
        slot = counts[value]
        if slot <= SOURCE_KEY_SLOT_MAX:
            out.append(f"{_SOURCE_KEY_PREFIX}{value}:{slot}")
        else:
            out.append(value)
    return out


def source_key_tokens(name: str) -> list[str]:
    if name not in TCL_SOURCE_KEYS:
        return []
    return [f"{_SOURCE_KEY_PREFIX}{name}:{slot}" for slot in range(1, SOURCE_KEY_SLOT_MAX + 1)]


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
        buttons = parse_source_actions(item.get(ATTR_BUTTONS))
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
