"""Docking Bay UI - EDMC plugin.

A UI customizer that lets the commander re-order main window blocks.
Keeps the original EDMC layout intact - no window resizing, no flashing.
"""

from __future__ import annotations

import tkinter as tk

try:
    from .dbui_editor import LayoutEditor
    from .dbui_engine import LayoutEngine, plugin_logger
    from .dbui_settings import build_settings
    from .dbui_version import __version__ as __version__
except ImportError:
    from dbui_editor import LayoutEditor
    from dbui_engine import LayoutEngine, plugin_logger
    from dbui_settings import build_settings
    from dbui_version import __version__ as __version__

ENGINE = None
EDITOR = None


def plugin_start3(plugin_dir):
    """Start the plugin - load saved layout."""
    global ENGINE
    try:
        ENGINE = LayoutEngine(str(plugin_dir))
        ENGINE.load()
    except Exception:
        plugin_logger().exception("Docking Bay UI could not start")
        ENGINE = None
    return "Docking Bay UI"


def plugin_app(parent):
    """Return the Livery button row for EDMC's main window."""
    if ENGINE is None:
        return None
    try:
        return ENGINE.build_app_row(parent, lambda: _open_edit(parent))
    except Exception:
        plugin_logger().exception("Docking Bay UI could not build app row")
        return None


def _open_edit(parent):
    """Open the edit window."""
    global EDITOR
    if EDITOR is not None:
        window = getattr(EDITOR, "window", None)
        if window is not None:
            try:
                window.lift()
                return
            except tk.TclError:
                pass
        EDITOR = None
    EDITOR = LayoutEditor(ENGINE)


def plugin_prefs(parent, cmdr, is_beta):
    """Settings tab - visibility, appearance colors, and window opacity."""
    if ENGINE is None:
        return _error_frame(parent, "Docking Bay UI did not start.")
    try:
        return build_settings(parent, ENGINE)
    except Exception:
        plugin_logger().exception("Docking Bay UI could not build settings")
        return _error_frame(parent, "Docking Bay UI could not open settings.")


def prefs_changed(cmdr, is_beta):
    """Save settings before the tab closes."""
    if ENGINE is None:
        return
    try:
        ENGINE.save()
    except Exception:
        plugin_logger().exception("Docking Bay UI could not save settings")


def plugin_stop():
    """Shut down the plugin."""
    global ENGINE, EDITOR
    if EDITOR is not None:
        try:
            EDITOR.close()
        except Exception:
            pass
        EDITOR = None
    if ENGINE is None:
        return
    try:
        ENGINE.shutdown()
    except Exception:
        plugin_logger().exception("Docking Bay UI could not shut down")
    ENGINE = None


def _error_frame(parent, message):
    """A settings frame EDMC can still display when setup failed."""
    try:
        import myNotebook as nb
        frame = nb.Frame(parent)
        nb.Label(frame, text=message).grid(row=1, column=0, sticky="w", padx=8, pady=8)
        return frame
    except Exception:
        plugin_logger().exception("Docking Bay UI could not show error frame")
        return None
