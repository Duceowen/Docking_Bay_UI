"""Edit mode for Docking Bay UI.

A small window that opens beside the EDMC main window. It lists the hidden
add-ons as clickable boxes, and offers Reset to Default and Finished editing.
Closing the window any way - the Finished editing button or the close button -
saves the current layout.
"""

from __future__ import annotations

import sys
import tkinter as tk

try:
    from .dbui_screen import popup_at_pointer, popup_beside, tk_position, work_areas
except ImportError:
    from dbui_screen import popup_at_pointer, popup_beside, tk_position, work_areas

TITLE = "Docking Bay UI - Edit layout"
GAP = 12


def _make_taskbar_visible(window):
    """Make an overrideredirect window appear in the taskbar on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        wid = window.winfo_id()
        hwnd = int(wid, 16) if str(wid).startswith("0x") else int(wid)
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


def _themed_button(parent, text, background, foreground, **kwargs):
    """A button that follows the EDMC theme instead of the system gray."""
    button = tk.Button(parent, text=text, **kwargs)
    if background:
        button.configure(background=background, activebackground=background)
    if foreground:
        button.configure(foreground=foreground, activeforeground=foreground)
    return button


class LayoutEditor:
    """Edit window for Docking Bay UI."""

    def __init__(self, engine):
        self.engine = engine
        self.window = None
        self._hidden_frame = None
        self._listener = None
        self._title_bar = None
        self._drag_x = 0
        self._drag_y = 0
        engine.editor = self
        self.open()

    def open(self):
        engine = self.engine
        root = getattr(engine, "root", None)
        if root is None:
            return

        background = self._color("background")
        foreground = self._color("foreground")

        window = tk.Toplevel(root)
        self.window = window
        window.overrideredirect(True)
        window.protocol("WM_DELETE_WINDOW", self.finish)
        if background:
            window.configure(bg=background)

        # Make window appear in taskbar despite overrideredirect
        window.after(10, lambda: _make_taskbar_visible(window))

        # Custom themed title bar
        self._title_bar = tk.Frame(window, bg=background or None, relief="flat", bd=0)
        self._title_bar.pack(fill="x", side="top")

        title_label = tk.Label(
            self._title_bar,
            text=TITLE,
            font=("TkDefaultFont", 10, "bold"),
            bg=background or None,
            fg=foreground or None,
            anchor="w",
            padx=8,
            pady=4,
        )
        title_label.pack(side="left", fill="x", expand=True)

        close_btn = tk.Label(
            self._title_bar,
            text="\u2715",
            font=("TkDefaultFont", 10, "bold"),
            bg=background or None,
            fg=foreground or None,
            anchor="center",
            padx=6,
            pady=4,
            cursor="hand2",
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.finish())

        for drag_widget in (title_label, self._title_bar):
            drag_widget.bind("<ButtonPress-1>", self._titlebar_press)
            drag_widget.bind("<B1-Motion>", self._titlebar_motion)

        body = tk.Frame(window, bg=background or None)
        body.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        tk.Label(
            body,
            text="How to edit",
            font=("TkDefaultFont", 11, "bold"),
            bg=background or None,
            fg=foreground or None,
            anchor="w",
        ).pack(fill="x")

        instructions = (
            "Each add-on has a coloured title bar with a drag handle and an eye icon.\n"
            "\u2022  Drag a title bar onto another add-on to swap them.\n"
            "     The add-on you drag takes that spot; the rest shift down.\n"
            "\u2022  Click the eye to hide an add-on.\n"
            "     Hidden add-ons appear below with a Show button."
        )
        tk.Label(
            body,
            text=instructions,
            wraplength=360,
            justify="left",
            bg=background or None,
            fg=foreground or None,
            anchor="w",
        ).pack(fill="x", pady=(2, 10))

        tk.Label(
            body,
            text="Hidden add-ons",
            font=("TkDefaultFont", 10, "bold"),
            bg=background or None,
            fg=foreground or None,
            anchor="w",
        ).pack(fill="x")
        self._hidden_frame = tk.Frame(body, bg=background or None)
        self._hidden_frame.pack(fill="x", pady=(4, 12))

        buttons = tk.Frame(body, bg=background or None)
        buttons.pack(fill="x", pady=(6, 0))
        _themed_button(
            buttons, "Reset to Default", background, foreground, width=16, command=self._reset
        ).pack(side="left")
        _themed_button(
            buttons, "Finished editing", background, foreground, width=16, command=self.finish
        ).pack(side="right")

        self.refresh_hidden()
        if engine is not None:
            engine._visibility_listener = self.refresh_hidden
            self._listener = self.refresh_hidden
            engine.set_editing(True)

        self._place_beside()
        try:
            window.lift()
        except tk.TclError:
            pass

    def refresh_hidden(self):
        """Rebuild the hidden add-on boxes from the engine state."""
        frame = self._hidden_frame
        if frame is None:
            return
        try:
            if not frame.winfo_exists():
                return
        except tk.TclError:
            return
        for child in list(frame.winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass

        background = self._color("background")
        foreground = self._color("foreground")
        hidden = set(self.engine.hidden_keys()) if self.engine is not None else set()
        blocks = [b for b in getattr(self.engine, "blocks", []) if b.key in hidden]

        if not blocks:
            tk.Label(
                frame,
                text="Nothing is hidden.",
                bg=background or None,
                fg=foreground or None,
                anchor="w",
            ).pack(fill="x")
            return

        boxes = tk.Frame(frame, bg=background or None)
        boxes.pack(fill="x")
        column = 0
        for block in blocks:
            _themed_button(
                boxes,
                block.title,
                background,
                foreground,
                width=14,
                command=lambda key=block.key: self._show(key),
            ).grid(row=column // 2, column=column % 2, sticky="ew", padx=2, pady=2)
            column += 1
        boxes.grid_columnconfigure(0, weight=1)
        boxes.grid_columnconfigure(1, weight=1)

    def _show(self, key):
        if self.engine is not None:
            self.engine.set_visible(key, True)

    def _reset(self):
        if self.engine is not None:
            self.engine.reset()

    def finish(self):
        """Finished editing, or the title-bar X: save the layout and close."""
        if self.engine is not None:
            try:
                self.engine.save()
            except Exception:
                pass
        self.close()

    def close(self):
        """Close the window. Safe to call more than once."""
        window = self.window
        self.window = None
        self._title_bar = None
        engine = self.engine
        if engine is not None:
            if getattr(engine, "editor", None) is self:
                engine.editor = None
            if getattr(engine, "_visibility_listener", None) is self._listener:
                engine._visibility_listener = None
        self._listener = None
        self._hidden_frame = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass
        if engine is not None:
            engine.set_editing(False)

    def _place_beside(self):
        """Put the window to the left or right of the main window, on screen."""
        window = self.window
        root = getattr(self.engine, "root", None)
        if window is None or root is None:
            return
        try:
            window.update_idletasks()
            width = max(int(window.winfo_reqwidth()), 240)
            height = max(int(window.winfo_reqheight()), 160)
            mx = int(root.winfo_rootx())
            my = int(root.winfo_rooty())
            mw = int(root.winfo_width())
            mh = int(root.winfo_height())
            monitors = work_areas()
            spot = popup_beside((mx, my, mw, mh), width, height, monitors, gap=GAP)
            if spot is None:
                spot = popup_at_pointer(mx + mw + GAP, my, width, height, monitors)
            if spot is None:
                return
            x, y, _width, _height = spot
            window.geometry(tk_position(x, y))
        except tk.TclError:
            return

    def _titlebar_press(self, event):
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def _titlebar_motion(self, event):
        window = self.window
        if window is None:
            return
        try:
            dx = event.x_root - self._drag_x
            dy = event.y_root - self._drag_y
            self._drag_x = event.x_root
            self._drag_y = event.y_root
            x = window.winfo_x() + dx
            y = window.winfo_y() + dy
            window.geometry("+%d+%d" % (x, y))
        except tk.TclError:
            pass

    def _color(self, name):
        """A theme color, or an empty string when it cannot be read."""
        try:
            import theme as theme_mod
            current = getattr(theme_mod.theme, "current", None) or {}
            return current.get(name, "")
        except Exception:
            return ""
