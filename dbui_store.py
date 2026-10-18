"""Save and load the Docking Bay UI state.

The state is written twice: into EDMC's own config so it survives a plugin
folder swap, and into ``layout.json`` next to the plugin so it is easy to
inspect. A broken copy in one place falls back to the other.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from .dbui_math import clean_state
except ImportError:
    from dbui_math import clean_state

CONFIG_KEY = "docking_bay_ui_state"
logger = logging.getLogger("docking_bay_ui.store")


def _decode(text):
    """Parse stored JSON into a dict, or None when it is unusable."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class LayoutStore:
    """Read and write the JSON state through EDMC config and a local file."""

    def __init__(self, plugin_dir):
        self.plugin_dir = Path(plugin_dir)
        self.path = self.plugin_dir / "layout.json"

    def load(self) -> dict:
        """Load state. A broken file or config value falls back to the other."""
        raw = self._read_config()
        if raw is None:
            raw = self._read_file()
        if raw is None:
            return clean_state({})
        return clean_state(raw)

    def save(self, state: dict) -> dict:
        """Persist a cleaned copy. File failure does not block the config write."""
        cleaned = clean_state(state)
        text = json.dumps(cleaned, indent=2, sort_keys=True)
        self._write_file(text)
        self._write_config(text)
        return cleaned

    def _read_config(self):
        try:
            from config import config
        except Exception:
            return None
        try:
            return _decode(config.get_str(CONFIG_KEY))
        except Exception:
            logger.debug("Docking Bay UI could not read its saved state from config")
            return None

    def _read_file(self):
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        return _decode(text)

    def _write_config(self, text: str):
        try:
            from config import config
        except Exception:
            return
        try:
            config.set(CONFIG_KEY, text)
        except Exception:
            logger.exception("Docking Bay UI could not save its state to config")

    def _write_file(self, text: str):
        try:
            self.path.write_text(text, encoding="utf-8")
        except (OSError, ValueError):
            logger.exception("Docking Bay UI could not save its state to layout.json")
