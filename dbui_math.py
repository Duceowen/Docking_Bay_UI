"""Docking Bay UI - Layout math.

Pure layout math functions used by the layout engine.
"""

from __future__ import annotations

PRESET_VERTICAL = "vertical"
PRESET_COMPACT = "compact"
PRESET_CUSTOM = "custom"

PRESET_TITLES = {
    PRESET_VERTICAL: "Standard",
    PRESET_COMPACT: "Grid",
    PRESET_CUSTOM: "Custom",
}


def clean_color(value) -> str:
    """Return a color Tk can draw, or an empty string when it is unusable.

    Accepts ``#rgb``/``#rrggbb`` hex and Tk's named colors. Anything else,
    including a half-typed hex string, becomes ``""`` so a broken value
    never reaches a widget.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 6, 9, 12) and all(digit in "0123456789abcdefABCDEF" for digit in digits):
            return text.lower()
        return ""
    if text.isidentifier():
        return text
    return ""

MAX_SLOT = 24

CORE_KEY = "core"
LEGACY_CORE_KEYS = ("cmdr", "ship", "suit", "system", "station")
FOOTER_KEYS = ("update", "status")

DEFAULT_DARK_TEXT = "#ff8000"
DEFAULT_DARK_HIGHLIGHT = "white"

THEME_DEFAULT = 0

ADDON_SPAN_MAX = 6
MIN_OPACITY = 15
MAX_OPACITY = 100
MIN_COLUMN_SIZE = 48
MAX_COLUMN_SIZE = 720
MIN_ROW_SIZE = 16
MAX_ROW_SIZE = 320
DRAG_ARM_PX = 14


def default_order(found: list) -> list:
    """Stock visual order: the commander block, then plugins, then update and status."""
    found_list = list(found)
    if CORE_KEY in found_list:
        head = [CORE_KEY]
        reserved_extra = set(LEGACY_CORE_KEYS)
    else:
        head = [key for key in LEGACY_CORE_KEYS if key in found_list]
        reserved_extra = set()
    tail = [key for key in FOOTER_KEYS if key in found_list]
    reserved = set(head) | set(tail) | reserved_extra
    middle = [key for key in found_list if key not in reserved]
    return head + middle + tail


def merge_order(saved: list, found: list) -> list:
    """Keep a saved order, drop missing blocks, and append newly discovered ones."""
    found_set = set(found)
    merged = []
    for key in saved or []:
        if key in found_set and key not in merged:
            merged.append(key)
    for key in default_order(list(found)):
        if key not in merged:
            merged.append(key)
    return merged


def migrate_core(order, hidden, placements):
    """Collapse the old commander rows into one block."""
    order = [str(item).strip() for item in (order or []) if str(item).strip()]
    hidden = [str(item).strip() for item in (hidden or []) if str(item).strip()]
    placements = placements if isinstance(placements, dict) else {}
    legacy = set(LEGACY_CORE_KEYS)
    legacy_in_order = [key for key in order if key in legacy]
    has_legacy = bool(legacy_in_order) or any(key in legacy for key in hidden) or any(key in legacy for key in placements)
    if not has_legacy:
        return list(order), list(hidden), dict(placements), False

    new_order = []
    seen_core = CORE_KEY in order
    for key in order:
        if key == CORE_KEY:
            if CORE_KEY not in new_order:
                new_order.append(CORE_KEY)
            seen_core = True
            continue
        if key in legacy:
            if not seen_core:
                new_order.append(CORE_KEY)
                seen_core = True
            continue
        if key not in new_order:
            new_order.append(key)

    hidden_set = set(hidden)
    hide_core = CORE_KEY in hidden_set
    if not hide_core and legacy_in_order and all(key in hidden_set for key in legacy_in_order):
        hide_core = True
    revealed = (not hide_core) and any(key in hidden_set for key in legacy_in_order)

    new_hidden = []
    for key in hidden:
        if key in legacy or key == CORE_KEY:
            continue
        if key not in new_hidden:
            new_hidden.append(key)
    if hide_core and CORE_KEY not in new_hidden:
        new_hidden.append(CORE_KEY)

    new_placements = {}
    for key, value in placements.items():
        name = str(key).strip()
        if not name or name in legacy or name == CORE_KEY or not isinstance(value, dict):
            continue
        new_placements[name] = dict(value)

    core_source = placements.get(CORE_KEY) if isinstance(placements.get(CORE_KEY), dict) else None
    if core_source is None:
        for key in legacy_in_order + list(LEGACY_CORE_KEYS):
            value = placements.get(key)
            if isinstance(value, dict):
                core_source = value
                break
    if core_source is not None:
        new_placements[CORE_KEY] = dict(core_source)
    return new_order, new_hidden, new_placements, revealed


def move_visible_key(order, hidden, source, target_index):
    """Move one visible block so it occupies target_index in the visible list."""
    visible = [key for key in order if key not in set(hidden)]
    if source not in visible:
        return list(order)
    visible.remove(source)
    index = max(0, min(int(target_index), len(visible)))
    visible.insert(index, source)
    return reorder_visible(list(order), list(hidden), visible)


def reorder_visible(order, hidden, visible):
    """Apply a new visible ordering while hidden blocks keep their slots.

    Hidden keys stay exactly where they were so unhiding them later does not
    jump them to a new position. The remaining slots are filled in the order
    given by ``visible``.
    """
    hidden_set = set(hidden or [])
    wanted = [key for key in (visible or []) if key not in hidden_set]
    queue = iter(wanted)
    placed = set()
    result = []
    for key in order or []:
        if key in hidden_set:
            result.append(key)
            continue
        try:
            chosen = next(queue)
        except StopIteration:
            result.append(key)
            continue
        result.append(chosen)
        placed.add(chosen)
    for key in wanted:
        if key not in placed:
            result.append(key)
            placed.add(key)
    return result


def clean_state(raw):
    """Return a complete state dict. Unknown or broken fields fall back to defaults."""
    source = raw if isinstance(raw, dict) else {}
    preset = source.get("preset", PRESET_VERTICAL)
    if preset not in PRESET_TITLES:
        preset = PRESET_VERTICAL

    def string_list(value):
        if not isinstance(value, list):
            return []
        cleaned = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    order = string_list(source.get("order"))
    hidden = string_list(source.get("hidden"))
    return {
        "version": 1,
        "preset": preset,
        "order": order,
        "hidden": hidden,
        "placements": clean_placements(source.get("placements")),
        "sizes": clean_sizes(source.get("sizes")),
        "grid_columns": clean_grid_columns(source.get("grid_columns")),
        "opacity": clean_opacity(source.get("opacity")),
        "manual_order": bool(source.get("manual_order")),
    }


def clean_opacity(value):
    """Return a saved opacity in 15-100, or None when the user never set one.

    None means "leave EDMC's own transparency setting alone" so the plugin
    does not clobber a value the user configured elsewhere.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if MIN_OPACITY <= number <= MAX_OPACITY:
        return number
    return None


def clean_placements(raw):
    """Drop broken cell records."""
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name or not isinstance(value, dict):
            continue
        try:
            slot = _slot(
                value.get("row", 0),
                value.get("column", 0),
                value.get("columnspan", 1),
                value.get("rowspan", 1),
            )
        except (TypeError, ValueError):
            continue
        cleaned[name] = slot
    return cleaned


def clean_sizes(raw):
    """Clean per-preset column/row sizes."""
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for preset, spec in raw.items():
        if preset not in PRESET_TITLES or not isinstance(spec, dict):
            continue
        cleaned[preset] = {
            "columns": _clean_tracks(spec.get("columns"), MIN_COLUMN_SIZE, MAX_COLUMN_SIZE, MAX_SLOT),
            "rows": _clean_tracks(spec.get("rows"), MIN_ROW_SIZE, MAX_ROW_SIZE, MAX_SLOT),
        }
    return cleaned


def clean_grid_columns(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    if number < 1:
        return 0
    return min(MAX_SLOT + 1, number)


def _clean_tracks(raw, low, high, limit):
    if not isinstance(raw, dict):
        return {}
    tracks = {}
    for key, value in raw.items():
        try:
            index = int(key)
            pixels = int(value)
        except (TypeError, ValueError):
            continue
        if index < 0 or index > limit:
            continue
        tracks[str(index)] = max(low, min(high, pixels))
    return tracks


def _slot(row, column, columnspan=1, rowspan=1):
    return {
        "row": max(0, min(MAX_SLOT, int(row))),
        "column": max(0, min(MAX_SLOT, int(column))),
        "columnspan": max(1, min(ADDON_SPAN_MAX, int(columnspan))),
        "rowspan": max(1, min(MAX_SLOT, int(rowspan))),
    }
