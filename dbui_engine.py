"""Docking Bay UI - Layout engine.

Arranges the EDMC main window blocks that this plugin is allowed to move:
the Commander rows, the plugin frames, and the Update and Status rows.
EDMC keeps ownership of the window. Only grid cells change.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk

try:
    from .dbui_math import (
        CORE_KEY,
        DEFAULT_DARK_HIGHLIGHT,
        DEFAULT_DARK_TEXT,
        MAX_OPACITY,
        MAX_SLOT,
        MIN_OPACITY,
        PRESET_VERTICAL,
        clean_color,
        default_order,
        merge_order,
        migrate_core,
        move_visible_key,
    )
    from .dbui_store import LayoutStore
except ImportError:
    from dbui_math import (
        CORE_KEY,
        DEFAULT_DARK_HIGHLIGHT,
        DEFAULT_DARK_TEXT,
        MAX_OPACITY,
        MAX_SLOT,
        MIN_OPACITY,
        PRESET_VERTICAL,
        clean_color,
        default_order,
        merge_order,
        migrate_core,
        move_visible_key,
    )
    from dbui_store import LayoutStore

logger = logging.getLogger("docking_bay_ui")

_MENU_CHILD_NAMES = {"alternate_menubar", "blank_menubar"}
_GROUP_TITLE = "Commander"
_PAIR_ROWS = (
    ("cmdr", "Cmdr", "cmdr_label", "cmdr"),
    ("ship", "Ship", "ship_label", "ship"),
    ("suit", "Suit", "suit_label", "suit"),
    ("system", "System", "system_label", "system"),
    ("station", "Station", "station_label", "station"),
)
_PADX = 5

# A plugin frame no taller than this is one text line: it sorts to the
# bottom of the add-on list, alphabetically.
SHORT_BLOCK_HEIGHT = 40

# A press that travels this far becomes a drag, so a plain click still lands.
DRAG_ARM_PX = 14

EYE = "\U0001F441"

OUTFITTING_ICON = "outfitting.png"
OUTFITTING_ICON_PX = 20


def _load_outfitting_icon(master, size: int = OUTFITTING_ICON_PX):
    """Load the small Outfitting icon, or None when it is missing or unreadable."""
    try:
        folder = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return None
    path = os.path.join(folder, OUTFITTING_ICON)
    if not os.path.isfile(path):
        return None
    try:
        image = tk.PhotoImage(master=master, file=path)
    except tk.TclError:
        return None
    try:
        width = int(image.width())
        factor = int(round(width / float(size)))
        if factor > 1:
            image = image.subsample(factor, factor)
    except (tk.TclError, ValueError, ZeroDivisionError):
        pass
    return image


def plugin_logger():
    try:
        import EDMCLogging
        return EDMCLogging.get_plugin_logger("Docking Bay UI")
    except Exception:
        return logger


class Block:
    """One movable piece of the main window."""

    def __init__(self, key, title, kind, widgets):
        self.key = key
        self.title = title
        self.kind = kind
        self.widgets = list(widgets)
        self.chrome = None

    def any_alive(self):
        for widget in self.widgets:
            try:
                if widget is not None and widget.winfo_exists():
                    return True
            except tk.TclError:
                continue
        return False


class LayoutEngine:
    def __init__(self, plugin_dir):
        self.plugin_dir = os.path.abspath(str(plugin_dir))
        self.store = LayoutStore(plugin_dir)
        self.state = self.store.load()
        self.root = None
        self.host = None
        self.blocks = []
        self.editor = None
        self._app_row = None
        self._own_frame = None
        self._editing = False
        self._update_pick = None
        self._update_row = None
        self._bottom_row = 1
        self._place_job = None
        self._place_retries = 0
        self._reposition_bound = False
        self._update_bound = set()
        self._core_bound = set()
        self._started = False
        self._in_layout = False
        self._log = plugin_logger()
        self._visibility_listener = None
        self._suit_row = None
        self._resort_job = None
        self._drag = None
        self._ghost = None
        self._drop_target = None
        self._suspend_fit = False

    def load(self):
        self.state = self.store.load()

    def save(self):
        try:
            self.state = self.store.save(self.state)
        except Exception:
            self._log.exception("Docking Bay UI could not save layout")

    def shutdown(self):
        try:
            self.save()
        except Exception:
            self._log.exception("Docking Bay UI could not save on shutdown")
        if self._resort_job is not None:
            try:
                self.root.after_cancel(self._resort_job)
            except Exception:
                pass
            self._resort_job = None

    def build_app_row(self, parent, on_click=None):
        """Return the Outfitting button row for EDMC's main window."""
        try:
            self.host = parent.master
            self.root = parent.winfo_toplevel()
        except tk.TclError:
            self._log.exception("Docking Bay UI could not see the EDMC window")
            return None

        row = tk.Frame(parent, name="uicust_app_row")
        background = self._theme_color("background")
        foreground = self._theme_color("foreground")
        if background:
            row.configure(bg=background)

        icon = _load_outfitting_icon(row)
        button = tk.Label(
            row,
            text="Edit layout",
            anchor="center",
            padx=4,
            pady=1,
            cursor="hand2",
            compound="left",
        )
        if icon is not None:
            button.configure(image=icon)
            button.image = icon
        if background:
            button.configure(bg=background)
        if foreground:
            button.configure(fg=foreground)
        if on_click is not None:
            button.bind("<Button-1>", lambda _event: on_click())
        button.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")

        self._app_row = row
        self._prealign_labels()
        self._schedule_start()
        return row

    def _prealign_labels(self):
        """Left-align the commander labels before EDMC shows the window.

        EDMC grids the labels left-aligned and fills in their text just before
        the first paint.  Aligning them here, while they are still empty, means
        the first paint is already correct and nothing jumps sideways once the
        layout engine starts.
        """
        host = self.host
        if not self._alive(host):
            return
        try:
            children = list(host.winfo_children())
        except tk.TclError:
            return
        names = {}
        for _key, _title, label_name, value_name in _PAIR_ROWS:
            names[label_name] = ("label", "w")
            names[value_name] = ("value", "w")
        for child in children:
            target = names.get(self._widget_name(child))
            if target is None:
                continue
            kind, sticky = target
            try:
                if kind == "label":
                    child.configure(anchor="w")
                child.grid_configure(sticky=sticky, padx=_PADX, pady=1)
            except tk.TclError:
                pass

    def _schedule_start(self):
        """Scan and lay out once the main loop is running and all frames exist."""
        if self._started:
            return
        root = self.root
        if not self._alive(root):
            return
        try:
            root.after(400, self.start)
        except tk.TclError:
            pass

    # -- lifecycle -------------------------------------------------------

    def start(self):
        """Scan the window and apply the saved layout."""
        if not self._alive(self.host):
            return
        self._started = True
        try:
            self._base_width = max(
                int(self.root.winfo_width()), int(self.root.winfo_reqwidth())
            )
        except tk.TclError:
            self._base_width = 0
        self.discover()
        self.apply_layout(force=True)
        self._bind_reposition()
        self.restore_opacity()
        self._schedule_settle()
        try:
            self._log.info(
                "Docking Bay UI laid out %s blocks: %s",
                len(self.blocks),
                ", ".join(b.title for b in self.blocks),
            )
        except Exception:
            pass

    def rescan(self):
        """Look again for plugin frames that appeared after startup."""
        self.discover()
        self.apply_layout(force=True)

    def reset(self):
        """Restore the stock layout, show every block, clear the grid."""
        try:
            self.state = {
                "version": 1,
                "preset": PRESET_VERTICAL,
                "order": default_order([b.key for b in self.blocks]),
                "hidden": [],
                "placements": {},
                "sizes": {},
                "grid_columns": 0,
                "opacity": self.state.get("opacity"),
                "manual_order": False,
            }
            self.save()
            self.apply_layout(force=True)
            if self._visibility_listener is not None:
                self._visibility_listener()
        except Exception:
            self._log.exception("Docking Bay UI could not reset the layout")

    def set_editing(self, flag):
        """Show or hide the drag and hide chrome on every add-on."""
        flag = bool(flag)
        if flag == self._editing:
            return
        self._editing = flag
        self._destroy_chrome()
        self.apply_layout(force=True)
        self._snap_to_content()
        self._schedule_settle()

    def close_editor(self):
        editor = self.editor
        self.editor = None
        if editor is not None:
            try:
                editor.close()
            except Exception:
                pass
        self.set_editing(False)

    # -- appearance and opacity ------------------------------------------

    def appearance_color(self, index):
        """The saved Normal text (0) or Highlighted text (1) color."""
        key = ("dark_text", "dark_highlight")[int(index)]
        default = (DEFAULT_DARK_TEXT, DEFAULT_DARK_HIGHLIGHT)[int(index)]
        try:
            from config import config
            value = clean_color(config.get_str(key))
            if value:
                return value
        except Exception:
            pass
        return default

    def commit_appearance(self, dialog, colors):
        """Write the two Appearance colors and repaint the main window."""
        normal = clean_color(colors[0]) or DEFAULT_DARK_TEXT
        highlight = clean_color(colors[1]) or DEFAULT_DARK_HIGHLIGHT
        try:
            from config import config
            config.set("dark_text", normal)
            config.set("dark_highlight", highlight)
        except Exception:
            self._log.exception("Docking Bay UI could not save the appearance colors")
        if dialog is not None:
            try:
                dialog.theme_colors[0] = normal
                dialog.theme_colors[1] = highlight
                dialog.themevarchanged()
            except Exception:
                pass
        self.repaint()

    def repaint(self):
        """Ask EDMC to re-apply the theme, then recolor our own chrome."""
        try:
            import theme as theme_mod
            theme_mod.theme.apply(self.root)
        except Exception:
            self._log.exception("Docking Bay UI could not repaint the window")
        # Reset update widget tracking so we pick the new themed button
        self._update_pick = None
        self._place_retries = 0
        # Simulate a full reload: rediscover blocks and rebuild layout
        self._destroy_chrome()
        self.discover()
        self.apply_layout(force=True)
        self._restyle_chrome()
        self._schedule_settle()
        # Schedule additional re-places to catch late widget updates
        self._schedule_theme_reflow()

    def _schedule_theme_reflow(self):
        """Schedule delayed re-places after a theme switch."""
        root = self.root
        if not self._alive(root):
            return
        # Use fewer, quicker retries for theme changes
        for delay in (150, 350):
            try:
                root.after(delay, self._theme_reflow_place)
            except tk.TclError:
                return

    def _theme_reflow_place(self):
        """Re-place the button after a theme switch."""
        if self._in_layout or not self._alive(self.host):
            return
        self._update_pick = None
        self._place_retries = 0
        self._place_own_row()

    def suspend_popup_fit(self, flag):
        """Pause popup fitting while a color chooser owns the pointer."""
        self._suspend_fit = bool(flag)

    def set_opacity(self, value, preview=True, save=False):
        """Set the main window opacity (15-100) and mirror EDMC's own setting."""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return
        number = max(MIN_OPACITY, min(MAX_OPACITY, number))
        self.state["opacity"] = number
        self._apply_opacity(number)
        if save:
            self.save()

    def restore_opacity(self):
        """Apply a saved opacity. Leaves EDMC's own setting alone when unset."""
        saved = self.state.get("opacity")
        if saved is None:
            return
        self._apply_opacity(saved)

    def _apply_opacity(self, value):
        try:
            self.root.attributes("-alpha", float(value) / 100.0)
        except Exception:
            pass
        try:
            from config import config
            config.set("ui_transparency", int(value))
        except Exception:
            pass

    def _restyle_chrome(self):
        colors = self._bar_colors()
        for block in self.blocks:
            if not block.chrome:
                continue
            for name, widget in block.chrome.items():
                if widget is None:
                    continue
                try:
                    if name == "header":
                        widget.configure(bg=colors["bar"], highlightbackground=colors["border"])
                    elif name == "eye":
                        widget.configure(
                            bg=colors["eye"], fg=colors["text"],
                            activebackground=colors["border"], activeforeground=colors["text"],
                        )
                    else:
                        widget.configure(bg=colors["bar"], fg=colors["text"])
                except tk.TclError:
                    pass

    def _bar_colors(self):
        """Contrasting colors for the edit-mode move and hide bars."""
        background = self._theme_color("background") or "#d9d9d9"
        foreground = self._theme_color("foreground") or "#000000"
        try:
            raw = self.root.winfo_rgb(background)
            red, green, blue = (value // 256 for value in raw)
        except Exception:
            red = green = blue = 240
        luminance = (red * 299 + green * 587 + blue * 114) // 1000
        if luminance < 128:
            bar = (min(255, red + 42), min(255, green + 42), min(255, blue + 42))
            eye = (min(255, red + 68), min(255, green + 68), min(255, blue + 68))
            border = (min(255, red + 100), min(255, green + 100), min(255, blue + 100))
        else:
            bar = (max(0, red - 42), max(0, green - 42), max(0, blue - 42))
            eye = (max(0, red - 68), max(0, green - 68), max(0, blue - 68))
            border = (max(0, red - 100), max(0, green - 100), max(0, blue - 100))
        return {
            "bar": "#%02x%02x%02x" % bar,
            "eye": "#%02x%02x%02x" % eye,
            "border": "#%02x%02x%02x" % border,
            "text": foreground,
        }

    # -- visibility ------------------------------------------------------

    def set_visible(self, key, visible):
        hidden = list(self.state.get("hidden") or [])
        if visible:
            if key in hidden:
                hidden.remove(key)
        elif key not in hidden:
            hidden.append(key)
        self.state["hidden"] = hidden
        self.apply_layout()
        self.save()
        if self._visibility_listener is not None:
            try:
                self._visibility_listener()
            except Exception:
                pass

    def toggle_hidden(self, key):
        hidden = set(self.state.get("hidden") or [])
        self.set_visible(key, key in hidden)

    def hidden_keys(self):
        return list(self.state.get("hidden") or [])

    # -- discovery -------------------------------------------------------

    def discover(self):
        """Walk the content frame and rebuild the block list."""
        host = self.host
        if not self._alive(host):
            return
        self._destroy_chrome()
        self._own_frame = None
        try:
            hosted = list(host.winfo_children())
        except tk.TclError:
            return

        children = {}
        for child in hosted:
            name = self._widget_name(child)
            if not name or name.startswith("uicust"):
                continue
            if name in _MENU_CHILD_NAMES:
                continue
            children[name] = child

        blocks = []
        group_widgets = []
        for _key, _title, label_name, value_name in _PAIR_ROWS:
            for name in (label_name, value_name):
                widget = children.get(name)
                if widget is not None:
                    group_widgets.append(widget)
        if group_widgets:
            blocks.append(Block(CORE_KEY, _GROUP_TITLE, "group", group_widgets))

        indexes = []
        import re
        for name in children:
            match = re.fullmatch(r"plugin_(\d+)", name)
            if match:
                indexes.append(int(match.group(1)))

        used_keys = {b.key for b in blocks}
        for index in sorted(indexes):
            frame = children.get("plugin_%s" % index)
            separator = children.get("plugin_hr_%s" % index)
            if self._is_self_plugin(index):
                self._own_frame = frame
                continue
            widgets = [w for w in (separator, frame) if w is not None]
            if not widgets:
                continue
            title, key = self._plugin_identity(index, used_keys)
            used_keys.add(key)
            blocks.append(Block(key, title, "plugin", widgets))

        update_widgets = [
            children[name]
            for name in ("update_button", "themed_update_button")
            if name in children
        ]
        if update_widgets:
            blocks.append(Block("update", "Update", "update", update_widgets))
        if "status" in children:
            blocks.append(Block("status", "Status", "single", [children["status"]]))

        self.blocks = blocks
        found = [b.key for b in blocks]
        order, hidden, placements, _ = migrate_core(
            self.state.get("order") or [],
            self.state.get("hidden") or [],
            self.state.get("placements") or {},
        )
        self.state["order"] = merge_order(order, found)
        self.state["hidden"] = hidden
        self.state["placements"] = placements

    def _core_widgets(self):
        """The commander rows currently living in the content frame."""
        host = self.host
        if not self._alive(host):
            return []
        names = []
        for _key, _title, label_name, value_name in _PAIR_ROWS:
            names.extend((label_name, value_name))
        try:
            children = list(host.winfo_children())
        except tk.TclError:
            return []
        found = {}
        for child in children:
            name = self._widget_name(child)
            if name in names:
                found[name] = child
        return [found[name] for name in names if name in found]

    def _sync_core(self):
        """Pick up commander rows EDMC adds after startup, such as Suit."""
        widgets = self._core_widgets()
        core = next((b for b in self.blocks if b.kind == "group"), None)
        if core is None:
            if not widgets:
                return False
            self.blocks.append(Block(CORE_KEY, _GROUP_TITLE, "group", widgets))
            return True
        if widgets == core.widgets:
            return False
        core.widgets = widgets
        return True

    def _is_self_plugin(self, index):
        """True when this plugin_N frame belongs to Docking Bay UI itself."""
        try:
            import plug
            plugin = plug.PLUGINS[index - 1]
        except Exception:
            return False
        folder = getattr(plugin, "folder", None)
        if folder:
            try:
                if os.path.normcase(os.path.abspath(str(folder))) == os.path.normcase(self.plugin_dir):
                    return True
            except Exception:
                pass
        name = str(getattr(plugin, "name", "") or "")
        return name.strip().lower() in ("docking bay ui", "docking bay")

    def _plugin_identity(self, index, used_keys):
        title = "Plugin %s" % index
        try:
            import plug
            plugin = plug.PLUGINS[index - 1]
            name = getattr(plugin, "name", "") or ""
            if str(name).strip():
                title = str(name).strip()
        except Exception:
            pass
        key = "plugin:%s" % title
        if key in used_keys:
            key = "plugin:%s:%s" % (title, index)
        return title, key

    # -- layout ----------------------------------------------------------

    def apply_layout(self, force=False):
        """Grid every visible block, top to bottom."""
        if not self._alive(self.host):
            return
        self._in_layout = True
        try:
            self._apply_layout()
            self._restyle_chrome()
        except Exception:
            self._log.exception("Docking Bay UI could not apply the layout")
        finally:
            self._in_layout = False

    def _apply_layout(self):
        host = self.host
        self._sync_core()
        self._pick_update_widget()
        for block in self.blocks:
            self._forget_block(block)

        self._configure_grid(host)

        row = 1
        self._update_row = None
        for block in self._ordered_visible():
            if block.kind == "update":
                self._update_row = row
            row = self._place_block(block, row)
        self._bottom_row = row

        self._place_own_row()
        self._bind_update_reposition()
        self._bind_core_alignment()

        self._hide_dividers()
        self._ensure_min_size()
        # Force commander labels to align properly
        self._fix_commander_alignment()

    def _fix_commander_alignment(self):
        """Keep the commander labels left-aligned with one value column.

        EDMC's toggle_suit_row regrids the Suit row whenever it appears, which
        can leave that row out of line until the next full layout.  Restore our
        options whenever a core widget is regridded.
        """
        core = next((b for b in self.blocks if b.kind == "group"), None)
        if core is None:
            return
        for label, value in self._iter_pairs(core):
            for widget, is_label in ((label, True), (value, False)):
                if widget is None or not self._alive(widget):
                    continue
                try:
                    info = widget.grid_info()
                except tk.TclError:
                    continue
                if not info:
                    continue
                try:
                    if is_label:
                        widget.configure(anchor="w")
                    if (
                        str(info.get("sticky")) == "w"
                        and int(info.get("padx") or 0) == _PADX
                        and int(info.get("pady") or 0) == 1
                    ):
                        continue
                    widget.grid_configure(sticky="w", padx=_PADX, pady=1)
                except (tk.TclError, TypeError, ValueError):
                    pass

    def _place_own_row(self):
        """Put the Edit button on the Update line, at the left.

        The button is an overlay, so it must be re-placed whenever the Update
        row moves.  Plugin frames can shrink after startup (Salty does this
        about six seconds in), which moves every row below them; the host frame
        keeps its size, so it never sees a <Configure> for that.  The Update
        widget itself does, which is why it is the one bound in
        _bind_update_reposition.
        """
        frame = self._own_frame
        if frame is None or not self._alive(frame):
            return

        try:
            background = self._theme_color("background")
            if background:
                frame.configure(bg=background)
        except tk.TclError:
            pass

        host = self.host
        if not self._alive(host):
            return
        row = self._update_row
        if row is None:
            self._forget(frame)
            self._grid(frame, row=max(1, self._bottom_row), column=0, columnspan=2, sticky="ew")
            return

        try:
            host.update_idletasks()
            bx, by, _bw, bh = host.bbox(0, row)
        except Exception:
            return
        if int(bh) <= 0:
            # Not measurable yet; try again once the row has a size.
            self._retry_place()
            return

        height = int(frame.winfo_reqheight())
        offset = max(0, (int(bh) - height) // 2)
        x = int(bx) + _PADX
        y = int(by) + offset
        # Never let the button hang below its row or above the row's top.
        if y > int(by) + int(bh) - height:
            y = int(by) + int(bh) - height
        if y < int(by):
            y = int(by)

        self._forget(frame)
        try:
            frame.place(in_=host, x=x, y=y, anchor="nw")
            frame.lift()
            self._place_retries = 0
        except tk.TclError:
            pass

    def _retry_place(self):
        """The Update row is not measurable yet, so try again shortly."""
        if self._place_retries >= 15:
            if self._alive(self._own_frame):
                self._forget(self._own_frame)
                self._grid(self._own_frame, row=max(1, self._bottom_row), column=0, columnspan=2, sticky="ew")
            return
        self._place_retries += 1
        root = self.root
        if not self._alive(root):
            return
        delay = min(300, 50 + self._place_retries * 15)
        try:
            root.after(delay, self._reposition_own)
        except tk.TclError:
            pass

    def _bind_update_reposition(self):
        """Follow the Update line when another block changes height.

        The Update and Status rows sit below every plugin frame, so a late
        resize inside a plugin frame (Salty shrinks itself around six seconds
        in) moves them.  Tk sends <Configure> to the widget that moved, so the
        Update widget is the reliable trigger for re-placing the Edit button.
        """
        block = next((b for b in self.blocks if b.kind == "update"), None)
        if block is None:
            return
        for widget in block.widgets:
            if not self._alive(widget):
                continue
            key = str(widget)
            if key in self._update_bound:
                continue
            try:
                widget.bind("<Configure>", self._on_update_configure, add="+")
                self._update_bound.add(key)
            except tk.TclError:
                pass

    def _on_update_configure(self, event):
        if self._in_layout or self._place_job is not None:
            return
        root = self.root
        if not self._alive(root):
            return
        try:
            self._place_job = root.after_idle(self._on_update_settle)
        except tk.TclError:
            self._place_job = None

    def _on_update_settle(self):
        self._place_job = None
        if self._in_layout or not self._alive(self.host):
            return
        self._update_pick = None
        block = next((b for b in self.blocks if b.kind == "update"), None)
        if block is not None and self._update_row is not None:
            for widget in block.widgets:
                if not self._alive(widget):
                    continue
                try:
                    if widget.winfo_manager() != "grid":
                        continue
                    row = int(widget.grid_info().get("row", -1))
                except (tk.TclError, TypeError, ValueError):
                    continue
                if row != int(self._update_row):
                    # EDMC regrids the Update pair at its original row on every
                    # theme change (theme.apply), which undoes our compacted
                    # order and can push the status line off the window.
                    self.apply_layout()
                    return
        self._fix_commander_alignment()
        self._pick_update_widget()
        self._place_own_row()

    def _bind_core_alignment(self):
        """Restore the commander row options when EDMC regrids one of them.

        EDMC reveals the Suit row later, when it learns the suit, and regrids
        that whole row with its own padding.
        """
        block = next((b for b in self.blocks if b.kind == "group"), None)
        if block is None:
            return
        for widget in block.widgets:
            if not self._widget_name(widget).endswith("_label"):
                continue
            if not self._alive(widget):
                continue
            key = str(widget)
            if key in self._core_bound:
                continue
            try:
                widget.bind("<Configure>", self._on_core_label_configure, add="+")
                self._core_bound.add(key)
            except tk.TclError:
                pass

    def _on_core_label_configure(self, event):
        if self._in_layout or self._place_job is not None:
            return
        root = self.root
        if not self._alive(root):
            return
        try:
            self._place_job = root.after_idle(self._on_core_label_settle)
        except tk.TclError:
            self._place_job = None

    def _on_core_label_settle(self):
        self._place_job = None
        if self._in_layout or not self._alive(self.host):
            return
        self._fix_commander_alignment()
        self._place_own_row()

    def _bind_reposition(self):
        """Follow the Update line when the window is resized."""
        if self._reposition_bound:
            return
        host = self.host
        if not self._alive(host):
            return
        try:
            host.bind("<Configure>", self._on_host_configure, add="+")
            self._reposition_bound = True
        except tk.TclError:
            pass

    def _on_host_configure(self, event):
        # Only reposition if the event is for the host itself, not a child widget
        if event.widget != self.host:
            return
        # Allow repositioning even during layout if we're not actively placing
        if self._place_job is not None:
            return
        root = self.root
        if not self._alive(root):
            return
        try:
            self._place_job = root.after_idle(self._on_host_settle)
        except tk.TclError:
            self._place_job = None

    def _on_host_settle(self):
        self._place_job = None
        if self._in_layout or not self._alive(self.host):
            return
        if self._sync_core() or self._has_stray_block():
            self.apply_layout()
            return
        # Always try to re-place the button
        self._place_retries = 0
        self._fix_commander_alignment()
        self._place_own_row()

    def _has_stray_block(self):
        """True when EDMC has re-shown a widget that belongs to a hidden block."""
        hidden = set(self.state.get("hidden") or [])
        strays = []
        for block in self.blocks:
            if block.key not in hidden:
                continue
            for widget in block.widgets:
                if self._is_mapped(widget):
                    strays.append(self._widget_name(widget))
            header = block.chrome.get("header") if block.chrome else None
            if self._is_mapped(header):
                strays.append("chrome")
        return bool(strays)

    def _reposition_own(self):
        self._place_job = None
        if self._in_layout or not self._alive(self.host):
            return
        # Re-pick the update widget in case theme changed
        self._update_pick = None
        self._pick_update_widget()
        self._fix_commander_alignment()
        self._place_own_row()

    def force_reshow_button(self):
        """Force the Edit layout button to re-appear."""
        if not self._alive(self._own_frame):
            return
        self._update_pick = None
        self._place_retries = 0
        self._pick_update_widget()
        self._place_own_row()

    def _configure_grid(self, host):
        """Content grows sideways only. Rows keep their natural height."""
        try:
            host.grid_columnconfigure(0, weight=0)
            host.grid_columnconfigure(1, weight=1)
            for number in range(0, MAX_SLOT + 2):
                host.grid_rowconfigure(number, weight=0)
        except tk.TclError:
            pass

    def _ordered_visible(self):
        hidden = set(self.state.get("hidden") or [])
        by_key = {b.key: b for b in self.blocks}
        visible = []
        for key in self.state.get("order") or []:
            block = by_key.get(key)
            if block is None or key in hidden or not block.any_alive():
                continue
            visible.append(block)
        return self._short_to_bottom(visible)

    def _short_to_bottom(self, visible):
        """Short single-line add-ons sink to the bottom, alphabetical.

        Once the commander drags a block, their order wins and this stops.
        """
        if self.state.get("manual_order"):
            return visible
        plugins = [b for b in visible if b.kind == "plugin"]
        if len(plugins) < 2:
            return visible
        tall = []
        short = []
        for block in plugins:
            (short if self._is_short(block) else tall).append(block)
        if not short:
            return visible
        ordered = tall + sorted(short, key=lambda b: b.title.casefold())
        iterator = iter(ordered)
        result = []
        for block in visible:
            result.append(next(iterator) if block.kind == "plugin" else block)
        return result

    def _is_short(self, block):
        _separator, frame = self._plugin_widgets(block)
        if frame is None:
            return False
        try:
            height = int(frame.winfo_reqheight())
        except tk.TclError:
            return False
        return 1 < height <= SHORT_BLOCK_HEIGHT

    def _place_block(self, block, row):
        if block.kind == "group":
            header = self._block_chrome(block)
            if header is not None:
                self._grid(header, row=row, column=0, columnspan=2, sticky="ew")
                row += 1
            return self._lay_group_rows(block, row, 0, 1)
        if block.kind == "plugin":
            separator, frame = self._plugin_widgets(block)
            self._forget(separator)
            header = self._block_chrome(block)
            if header is not None:
                self._grid(header, row=row, column=0, columnspan=2, sticky="ew")
                row += 1
            if frame is not None:
                self._grid(frame, row=row, column=0, columnspan=2, sticky="ew")
                row += 1
            return row
        placed = self._grid_span_block(block, row=row, column=0, columnspan=2, rowspan=1)
        return row + 1 if placed else row

    def _lay_group_rows(self, block, row, column, value_column, step=1):
        for label, value in self._iter_pairs(block):
            if label is not None:
                try:
                    label.configure(anchor="w")
                except tk.TclError:
                    pass
                self._grid(label, row=row, column=column, sticky="w")
                if self._widget_name(label) == "suit_label":
                    self._suit_row = row
            if value is not None:
                self._grid(value, row=row, column=value_column, sticky="w")
            row += step
        return row

    def _grid_span_block(self, block, row, column, columnspan, rowspan):
        if block.kind == "update":
            active = self._active_update_widget(block)
            placed = False
            for widget in block.widgets:
                if widget is active:
                    self._grid(
                        widget,
                        row=row,
                        column=column,
                        columnspan=columnspan,
                        rowspan=rowspan,
                        sticky="ew",
                    )
                    placed = True
                else:
                    self._forget(widget)
            return placed
        placed = False
        for widget in block.widgets:
            if not self._alive(widget):
                continue
            self._grid(
                widget,
                row=row,
                column=column,
                columnspan=columnspan,
                rowspan=rowspan,
                sticky="ew",
            )
            placed = True
        return placed

    def _ensure_min_size(self):
        """Keep the window from shrinking below what its blocks need.

        The minimum follows the content so it drops again when the edit bars are
        removed, but it never falls below the width EDMC needed on startup, which
        would clip the info line.
        """
        root = self.root
        if not self._alive(root) or not self._alive(self.host):
            return
        try:
            root.update_idletasks()
            need_width = max(int(root.winfo_reqwidth()), int(self.host.winfo_reqwidth()))
            need_height = int(root.winfo_reqheight())
            if not self._editing:
                self._width_floor = max(getattr(self, "_width_floor", 0), need_width)
            floor = max(
                getattr(self, "_width_floor", 0), getattr(self, "_base_width", 0)
            )
            root.minsize(max(need_width, floor), need_height)
        except tk.TclError:
            pass

    def _snap_to_content(self):
        """Let the window fall back to the size its content needs."""
        root = self.root
        if not self._alive(root):
            return
        try:
            root.update_idletasks()
            root.geometry("")
        except tk.TclError:
            pass

    def _schedule_settle(self):
        """Re-align the Edit layout button once the window has fully settled.

        The first draw can be measured before the window manager and the EDMC
        theme finish moving rows around, which leaves the overlay slightly off.
        """
        root = self.root
        if not self._alive(root):
            return
        # Single callback after everything should be settled
        try:
            root.after(600, self._on_host_settle)
        except tk.TclError:
            return

    def _schedule_resort(self):
        """Re-run once after the first draw so short add-ons can be measured."""
        root = self.root
        if not self._alive(root) or self._resort_job is not None:
            return
        try:
            self._resort_job = root.after(400, self._resort)
        except tk.TclError:
            self._resort_job = None

    def _resort(self):
        self._resort_job = None
        if self._in_layout or not self._alive(self.host):
            return
        try:
            self._apply_layout()
        except Exception:
            self._log.exception("Docking Bay UI could not settle the layout")

    def _hide_dividers(self):
        """Hide the green EDMC separator lines between plugin blocks."""
        host = self.host
        if not self._alive(host):
            return
        try:
            children = list(host.winfo_children())
        except tk.TclError:
            return
        for child in children:
            if self._widget_name(child).startswith("plugin_hr_"):
                self._forget(child)

    # -- widget helpers --------------------------------------------------

    def _pair(self, block):
        label = block.widgets[0] if block.widgets else None
        value = block.widgets[1] if len(block.widgets) > 1 else None
        return label, value

    def _iter_pairs(self, block):
        by_name = {}
        for widget in block.widgets:
            by_name[self._widget_name(widget)] = widget
        pairs = []
        for _key, _title, label_name, value_name in _PAIR_ROWS:
            label = by_name.get(label_name)
            value = by_name.get(value_name)
            if label is None and value is None:
                continue
            pairs.append((label, value))
        return pairs

    def _plugin_widgets(self, block):
        separator = None
        frame = None
        for widget in block.widgets:
            name = self._widget_name(widget)
            if name.startswith("plugin_hr_"):
                separator = widget
            else:
                frame = widget
        return separator, frame

    def _grid(self, widget, **kwargs):
        if not self._alive(widget):
            return
        kwargs.setdefault("padx", _PADX)
        kwargs.setdefault("pady", 1)
        try:
            widget.grid(**kwargs)
        except tk.TclError:
            pass

    def _forget_block(self, block):
        for widget in block.widgets:
            self._forget(widget)
        if block.chrome:
            self._forget(block.chrome["header"])

    def _destroy_chrome(self):
        for block in self.blocks:
            self._destroy_block_chrome(block)

    def _destroy_block_chrome(self, block):
        chrome = block.chrome
        block.chrome = None
        if not chrome:
            return
        header = chrome.get("header")
        if header is None:
            return
        try:
            header.destroy()
        except tk.TclError:
            pass

    def _max_title_width(self):
        """Character width of the longest add-on title, so headers line up."""
        width = 0
        for block in self.blocks:
            length = len(block.title) if block.title else 0
            if length > width:
                width = length
        return max(width, 10)

    def _block_chrome(self, block):
        """The title bar and eyeball hide bar for one block, created once.

        Chrome only exists while the edit window is open, so a stock-looking
        window stays stock until the commander chooses to edit.
        """
        if not self._editing:
            return None
        chrome = block.chrome
        header = chrome.get("header") if chrome else None
        if header is not None:
            try:
                if header.winfo_exists():
                    return header
            except tk.TclError:
                pass
        host = self.host
        if not self._alive(host):
            return None
        colors = self._bar_colors()
        safe = "".join(ch if ch.isalnum() else "_" for ch in block.key)
        header = tk.Frame(
            host,
            name="uicust_head_%s" % safe,
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
        )
        header.configure(bg=colors["bar"])
        eye = tk.Label(
            header,
            text=EYE,
            anchor="center",
            padx=8,
            pady=1,
            cursor="hand2",
            bd=1,
            relief="raised",
            bg=colors["eye"],
            fg=colors["text"],
            activebackground=colors["border"],
            activeforeground=colors["text"],
        )
        eye.pack(side="right")
        title = tk.Label(
            header,
            text="\u2630  " + block.title,
            anchor="w",
            padx=6,
            pady=1,
            cursor="fleur",
            bg=colors["bar"],
            fg=colors["text"],
            width=self._max_title_width(),
        )
        title.pack(side="left", fill="both", expand=True)
        for draggable in (title, header):
            draggable.bind("<ButtonPress-1>", lambda event, b=block: self._drag_begin(b, event))
            draggable.bind("<B1-Motion>", self._drag_motion)
            draggable.bind("<ButtonRelease-1>", self._drag_end)
        eye.bind("<Button-1>", lambda _event, b=block: self.set_visible(b.key, False))
        block.chrome = {"header": header, "title": title, "eye": eye}
        return header

    def _theme_color(self, name, default=""):
        try:
            import theme as theme_mod
            current = getattr(theme_mod.theme, "current", None) or {}
            return current.get(name) or default
        except Exception:
            return default

    # -- drag to reorder -------------------------------------------------

    def move_block_to(self, source_key, target_key):
        """Drop one add-on onto another: it takes that spot, the rest shift down."""
        if not source_key or not target_key or source_key == target_key:
            return
        order = list(self.state.get("order") or [])
        hidden = list(self.state.get("hidden") or [])
        visible = [key for key in order if key not in set(hidden)]
        if source_key not in visible or target_key not in visible:
            return
        self.state["order"] = move_visible_key(
            order, hidden, source_key, visible.index(target_key)
        )
        self.state["manual_order"] = True
        self.apply_layout(force=True)
        self.save()

    def _drag_begin(self, block, event):
        self._drag = {
            "source": block.key,
            "armed": False,
            "x": int(event.x_root),
            "y": int(event.y_root),
        }

    def _drag_motion(self, event):
        drag = self._drag
        if drag is None:
            return
        if not drag["armed"]:
            if abs(event.x_root - drag["x"]) + abs(event.y_root - drag["y"]) < DRAG_ARM_PX:
                return
            drag["armed"] = True
            self._show_ghost(drag["source"])
        self._move_ghost(event.x_root, event.y_root)
        self._highlight(self._block_at(event.x_root, event.y_root))

    def _drag_end(self, event):
        drag = self._drag
        self._drag = None
        self._hide_ghost()
        self._highlight(None)
        if drag is None or not drag["armed"]:
            return
        target = self._block_at(event.x_root, event.y_root)
        if target is not None:
            self.move_block_to(drag["source"], target.key)

    def _block_at(self, x, y):
        """The visible block whose area is under the point, title bar included."""
        for block in self._ordered_visible():
            bounds = self._block_bounds(block)
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            if left <= x <= right and top <= y <= bottom:
                return block
        return None

    def _block_bounds(self, block):
        """Union of the mapped widgets of a block, so the whole block is a target."""
        regions = []
        chrome = block.chrome or {}
        widgets = list(block.widgets) + [chrome.get("header")]
        for widget in widgets:
            if widget is None or not self._alive(widget):
                continue
            try:
                if not widget.winfo_ismapped():
                    continue
                rx = int(widget.winfo_rootx())
                ry = int(widget.winfo_rooty())
                rw = int(widget.winfo_width())
                rh = int(widget.winfo_height())
            except tk.TclError:
                continue
            if rw <= 1 or rh <= 1:
                continue
            regions.append((rx, ry, rx + rw, ry + rh))
        if not regions:
            return None
        return (
            min(r[0] for r in regions),
            min(r[1] for r in regions),
            max(r[2] for r in regions),
            max(r[3] for r in regions),
        )

    def _highlight(self, block):
        if self._drop_target is block:
            return
        previous = self._drop_target
        self._drop_target = block
        for target in (previous, block):
            if target is None or not target.chrome:
                continue
            header = target.chrome.get("header")
            if header is None:
                continue
            try:
                if target is block:
                    header.configure(highlightthickness=2, highlightbackground="white")
                else:
                    header.configure(highlightthickness=0)
            except tk.TclError:
                pass

    def _show_ghost(self, source_key):
        self._hide_ghost()
        title = ""
        for block in self.blocks:
            if block.key == source_key:
                title = block.title
                break
        root = self.root
        if not self._alive(root):
            return
        try:
            ghost = tk.Toplevel(root)
            ghost.overrideredirect(True)
            ghost.attributes("-topmost", True)
            tk.Label(ghost, text=title, bd=1, relief="solid", padx=6, pady=2).pack()
            self._ghost = ghost
        except tk.TclError:
            self._ghost = None

    def _move_ghost(self, x, y):
        ghost = self._ghost
        if ghost is None:
            return
        try:
            ghost.geometry("+%s+%s" % (int(x) + 12, int(y) + 12))
        except tk.TclError:
            self._ghost = None

    def _hide_ghost(self):
        ghost = self._ghost
        self._ghost = None
        if ghost is None:
            return
        try:
            ghost.destroy()
        except tk.TclError:
            pass

    def _forget(self, widget):
        if not self._alive(widget):
            return
        try:
            mgr = widget.winfo_manager()
            if mgr == "grid":
                widget.grid_forget()
            elif mgr == "pack":
                widget.pack_forget()
            elif mgr == "place":
                widget.place_forget()
        except tk.TclError:
            pass

    def _pick_update_widget(self):
        """Remember which Update widget EDMC is showing, before we forget them.

        EDMC grids both the plain and themed Update widgets and lets the theme
        pick one. Reading the mapping before layout keeps the right one.
        """
        self._update_pick = None
        for block in self.blocks:
            if block.kind != "update":
                continue
            for widget in block.widgets:
                if self._alive(widget) and self._is_mapped(widget):
                    self._update_pick = widget
                    return

    def _active_update_widget(self, block):
        """The Update button EDMC is actually showing for the current theme."""
        pick = self._update_pick
        if pick is not None and self._alive(pick) and pick in block.widgets:
            return pick
        dark = self._theme_index() != 0
        wanted = "themed_update_button" if dark else "update_button"
        fallback = None
        for widget in block.widgets:
            if not self._alive(widget):
                continue
            if self._widget_name(widget) == wanted:
                return widget
            if fallback is None:
                fallback = widget
        return fallback

    def _theme_index(self):
        try:
            from config import config
            return int(config.get_int("theme") or 0)
        except Exception:
            return 0

    def _alive(self, widget):
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _is_mapped(self, widget):
        if not self._alive(widget):
            return False
        try:
            return bool(widget.winfo_ismapped())
        except tk.TclError:
            return False

    def _widget_name(self, widget):
        try:
            return str(widget.winfo_name())
        except Exception:
            return ""
