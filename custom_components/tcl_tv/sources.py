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
ATTR_ACTIONS = "actions"
ATTR_ADD_MORE = "add_more"
ATTR_EDIT_SEQUENCE = "edit_sequence"

KIND_KEY = "key"
KIND_BUTTON = "button"

DEFAULT_INTERVAL = 0.4
MAX_INTERVAL = 10.0
SOURCE_REPEAT_MIN = 1
SOURCE_REPEAT_MAX = 20

# Older option forms used unique ``key:<name>:<n>`` tokens; still accept them.
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


def parse_repeat(raw: Any, *, default: int = SOURCE_REPEAT_MIN) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    if value < SOURCE_REPEAT_MIN:
        return SOURCE_REPEAT_MIN
    if value > SOURCE_REPEAT_MAX:
        return SOURCE_REPEAT_MAX
    return value


def collapse_source_actions(raw: Any) -> list[tuple[str, int]]:
    """Merge consecutive identical presses into ``(action, count)`` steps."""
    out: list[tuple[str, int]] = []
    for value in parse_source_actions(raw):
        if out and out[-1][0] == value:
            out[-1] = (value, out[-1][1] + 1)
        else:
            out.append((value, 1))
    return out


def expand_source_steps(steps: list[tuple[str, int]]) -> list[str]:
    """Turn ``(action, count)`` steps back into a press list."""
    out: list[str] = []
    for action, count in steps:
        classified = classify_source_action(action)
        if classified is None:
            continue
        out.extend([classified[1]] * parse_repeat(count))
    return out


def unique_actions_of_kind(raw: Any, kind: str) -> list[str]:
    """Ordered unique key names or button ids of one kind."""
    out: list[str] = []
    seen: set[str] = set()
    for token in parse_source_actions(raw):
        classified = classify_source_action(token)
        if classified is None or classified[0] != kind:
            continue
        value = classified[1]
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def counts_for_kind(raw: Any, kind: str) -> dict[str, int]:
    """First consecutive-repeat count for each action of this kind."""
    counts: dict[str, int] = {}
    for value, count in collapse_source_actions(raw):
        classified = classify_source_action(value)
        if classified is None or classified[0] != kind:
            continue
        if classified[1] not in counts:
            counts[classified[1]] = count
    return counts


def sequence_kind(raw: Any) -> str | None:
    """``key`` or ``button`` when every press is the same kind; else ``None``."""
    kinds: set[str] = set()
    for token in parse_source_actions(raw):
        classified = classify_source_action(token)
        if classified is None:
            continue
        kinds.add(classified[0])
    if len(kinds) == 1:
        return next(iter(kinds))
    return None


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
