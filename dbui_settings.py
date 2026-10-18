"""Settings tab for layout, visibility, colors, and opacity.

The tab is rebuilt every time EDMC opens File > Settings. Widget variables
are stored on the frame so they stay alive until EDMC destroys that frame.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import colorchooser, ttk

try:
    from .dbui_math import (
        DEFAULT_DARK_HIGHLIGHT,
        DEFAULT_DARK_TEXT,
        clean_color,
    )
except ImportError:
    from dbui_math import (
        DEFAULT_DARK_HIGHLIGHT,
        DEFAULT_DARK_TEXT,
        clean_color,
    )


def build_settings(parent, engine):
    """Build the preferences frame EDMC expects from plugin_prefs."""
    import myNotebook as nb

    frame = nb.Frame(parent)
    frame.columnconfigure(0, weight=1)
    row = 1

    intro = (
        "Docking Bay UI arranges the main window. Click Outfitting on the main window to edit the layout. "
        "Cmdr, Ship, Suit, System, and Station are one block named Commander. "
        "Clear a box below to hide an element. A hidden block stays in the list, and Hide on a block does the same thing. "
        "The edit window lists every hidden block with a button to bring it back."
    )
    nb.Label(frame, text=intro, wraplength=460, justify="left").grid(
        row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8)
    )
    row += 1

    # A plain tk.Frame would paint the gray system button face on the white
    # settings page. Use the notebook frame style EDMC already configured.
    if sys.platform == "win32":
        buttons = ttk.Frame(frame, style="nb.TFrame")
    else:
        buttons = ttk.Frame(frame)
    buttons.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))
    nb.Button(buttons, text="Rescan", command=engine.rescan).pack(side="left", padx=(0, 6))
    nb.Button(buttons, text="Reset", command=lambda: _reset(engine, frame)).pack(side="left")
    row += 1

    nb.Label(frame, text="Turn elements on or off", anchor="w").grid(
        row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 2)
    )
    row += 1

    hidden = set(engine.state.get("hidden") or [])
    variables = []
    checks = []
    blocks = list(engine.blocks)
    if not blocks:
        nb.Label(frame, text="The main window has not been scanned yet. Press Rescan.").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=2
        )
        row += 1
    for block in blocks:
        variable = tk.BooleanVar(value=block.key not in hidden)
        variables.append(variable)
        checks.append((block.key, variable))
        nb.Checkbutton(
            frame,
            text=block.title,
            variable=variable,
            command=lambda key=block.key, var=variable: engine.set_visible(key, bool(var.get())),
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=24, pady=1)
        row += 1

    nb.Label(frame, text="Appearance", anchor="w").grid(
        row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(12, 2)
    )
    row += 1

    nb.Label(
        frame,
        text=(
            "Normal text and Highlighted text recolor the main window. "
            "Pick opens the color chooser. Defaults restores theme orange and white. "
            "These are the same colors as Settings > Appearance."
        ),
        wraplength=460,
        justify="left",
    ).grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 4))
    row += 1

    # Building the radios and the color fields must not push Appearance's
    # colors onto the main window. A shared theme variable can notify the
    # other tab while these widgets are created.
    frame._ui_customizer_suppress = True
    dialog = _appearance_dialog(frame)
    theme_var = _theme_variable(dialog)
    variables.append(theme_var)
    theme_default, theme_dark, theme_transparent = _theme_ids()
    nb.Label(frame, text="Theme", anchor="w").grid(row=row, column=0, sticky="w", padx=8, pady=(4, 2))
    row += 1
    theme_choices = [("Default", theme_default), ("Dark", theme_dark)]
    if sys.platform == "win32":
        theme_choices.append(("Transparent", theme_transparent))
    for label, value in theme_choices:
        nb.Radiobutton(
            frame,
            text=label,
            variable=theme_var,
            value=value,
            command=lambda: _theme_picked(frame),
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=24, pady=1)
        row += 1

    normal_var = tk.StringVar(value=engine.appearance_color(0))
    highlight_var = tk.StringVar(value=engine.appearance_color(1))
    variables.extend((normal_var, highlight_var))
    color_vars = (normal_var, highlight_var)
    color_inputs = []
    labels = ("Normal text", "Highlighted text")
    for index, label in enumerate(labels):
        nb.Label(frame, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=8, pady=2)
        entry = nb.EntryMenu(frame, textvariable=color_vars[index], width=18)
        entry.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        pick = nb.Button(
            frame,
            text="Pick",
            command=lambda which=index: _pick_appearance(engine, frame, which, color_vars),
        )
        pick.grid(row=row, column=2, sticky="w", padx=4, pady=2)
        color_inputs.extend((entry, pick))
        row += 1

    nb.Label(frame, text="Preview", anchor="w").grid(row=row, column=0, sticky="w", padx=8, pady=(6, 2))
    preview_normal = tk.Button(
        frame,
        text="Station",
        background="grey4",
        activebackground="grey4",
        command=lambda: _pick_appearance(engine, frame, 0, color_vars),
    )
    preview_normal.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
    row += 1
    preview_highlight = tk.Button(
        frame,
        text="  Hutton Orbital  ",
        background="grey4",
        activebackground="grey4",
        command=lambda: _pick_appearance(engine, frame, 1, color_vars),
    )
    preview_highlight.grid(row=row, column=1, sticky="ew", padx=4, pady=(0, 4))
    previews = (preview_normal, preview_highlight)
    color_inputs.extend(previews)
    row += 1

    nb.Button(
        frame,
        text="Defaults",
        command=lambda: _restore_appearance_defaults(engine, frame, color_vars),
    ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 8))
    nb.Button(
        frame,
        text="Apply appearance colors",
        command=lambda: _apply_appearance(engine, frame, color_vars),
    ).grid(row=row, column=1, sticky="w", padx=4, pady=(4, 8))
    row += 1

    for variable in color_vars:
        variable.trace_add("write", lambda *_args: _colors_edited(frame))

    nb.Label(
        frame,
        text="Window opacity. 100 is solid. The window stays visible enough to change this back.",
        wraplength=460,
        justify="left",
    ).grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 2))
    row += 1

    opacity = tk.IntVar(value=int(engine.state.get("opacity") or 100))
    variables.append(opacity)
    # Building the scale, and Reset, both write the variable. Those writes
    # must not mark the opacity as a commander choice.
    frame._ui_customizer_suppress = True
    scale = ttk.Scale(
        frame,
        from_=15,
        to=100,
        orient="horizontal",
        length=220,
        variable=opacity,
        command=lambda value: _opacity_moved(engine, frame, value),
    )
    scale.grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8))
    scale.bind("<ButtonRelease-1>", lambda _event: _opacity_released(engine, frame))
    opacity_value = nb.Label(frame, text="%d%%" % opacity.get(), anchor="w")
    opacity_value.grid(row=row, column=1, sticky="w", padx=(4, 8), pady=(0, 8))
    frame._ui_customizer_suppress = False
    row += 1

    # Keep the Tcl variables alive for as long as EDMC keeps this frame.
    frame._ui_customizer_vars = variables
    frame._ui_customizer_form = {
        "checks": checks,
        "colors": color_vars,
        "opacity": opacity,
        "opacity_label": opacity_value,
        "theme": theme_var,
        "previews": previews,
        "color_inputs": color_inputs,
    }
    _sync_preview(frame)
    _arm_color_buttons(engine, frame, dialog, color_vars)
    engine._visibility_listener = lambda: _sync_checks(engine, frame)

    def _forget_listener(event, owner=frame, callback=engine._visibility_listener):
        if event.widget is owner and engine._visibility_listener is callback:
            engine._visibility_listener = None

    frame.bind("<Destroy>", _forget_listener, add="+")
    return frame


def _sync_checks(engine, frame) -> None:
    """Match the checklist to the saved on/off state without clicking the boxes."""
    form = getattr(frame, "_ui_customizer_form", None)
    if not form:
        return
    try:
        if not frame.winfo_exists():
            return
    except tk.TclError:
        return
    hidden = set(engine.state.get("hidden") or [])
    frame._ui_customizer_suppress = True
    try:
        for key, variable in form["checks"]:
            variable.set(key not in hidden)
    finally:
        frame._ui_customizer_suppress = False


def _appearance_dialog(widget):
    """The open Settings window, which owns Appearance's color list."""
    current = widget
    for _step in range(8):
        if current is None:
            return None
        colors = getattr(current, "theme_colors", None)
        changed = getattr(current, "themevarchanged", None)
        if isinstance(colors, list) and len(colors) >= 2 and callable(changed):
            return current
        current = getattr(current, "master", None)
    return _toplevel_appearance_dialog(widget)


def _toplevel_appearance_dialog(widget):
    """The open Settings window, even when this frame is not inside it."""
    if widget is None:
        return None
    try:
        current = widget.winfo_toplevel()
        real = current
        while getattr(real, "master", None) is not None:
            real = real.master
        names = real.tk.splitlist(real.tk.call("winfo", "children", real))
    except tk.TclError:
        return None
    for name in names:
        try:
            child = real.nametowidget(name)
        except tk.TclError:
            continue
        colors = getattr(child, "theme_colors", None)
        changed = getattr(child, "themevarchanged", None)
        if isinstance(colors, list) and len(colors) >= 2 and callable(changed):
            return child
    return None


def _chooser_parent(frame, dialog):
    """The color popup when this form set one. Otherwise the Settings window."""
    parent = getattr(frame, "_ui_customizer_chooser_parent", None)
    if parent is not None:
        try:
            if parent.winfo_exists():
                return parent
        except tk.TclError:
            pass
    if dialog is not None:
        return dialog
    return frame


def _theme_ids():
    """Appearance's theme numbers. 0 is Default, 1 is Dark, 2 is Transparent."""
    try:
        import theme as theme_mod
        return theme_mod.THEME_DEFAULT, theme_mod.THEME_DARK, theme_mod.THEME_TRANSPARENT
    except Exception:
        return 0, 1, 2


def _theme_variable(dialog):
    """The Appearance tab's theme variable, so both tabs stay on the same choice."""
    theme_var = getattr(dialog, "theme", None) if dialog is not None else None
    if theme_var is not None and hasattr(theme_var, "get") and hasattr(theme_var, "set"):
        return theme_var
    return tk.IntVar(value=_configured_theme())


def _configured_theme() -> int:
    try:
        from config import config
        return int(config.get_int("theme") or 0)
    except Exception:
        return 0


def _refresh_color_vars(engine, frame, color_vars) -> None:
    frame._ui_customizer_suppress = True
    try:
        color_vars[0].set(engine.appearance_color(0))
        color_vars[1].set(engine.appearance_color(1))
    finally:
        frame._ui_customizer_suppress = False


def _apply_appearance(engine, frame, color_vars) -> None:
    """Write the two entries into Appearance's list and repaint."""
    dialog = _appearance_dialog(frame)
    colors = (clean_color(color_vars[0].get()), clean_color(color_vars[1].get()))
    engine.commit_appearance(dialog, colors)
    _refresh_color_vars(engine, frame, color_vars)
    _sync_preview(frame)


def _pick_appearance(engine, frame, index: int, color_vars) -> None:
    """Open the color chooser on the Settings window and store the choice.

    The chooser is parented to Settings, which already holds the grab.
    Popup fitting is paused until the chooser closes, so the window does not
    jump and dismiss it.
    """
    dialog = _appearance_dialog(frame)
    current = clean_color(color_vars[index].get()) or None
    if dialog is not None:
        try:
            stored = dialog.theme_colors[index]
        except (tk.TclError, IndexError, TypeError):
            stored = ""
        current = clean_color(stored) or current
    title = ("Normal text", "Highlighted text")[index]
    parent = _chooser_parent(frame, dialog)
    engine.suspend_popup_fit(True)
    try:
        _rgb, chosen = colorchooser.askcolor(color=current or None, parent=parent, title=title)
    except tk.TclError:
        return
    finally:
        engine.suspend_popup_fit(False)
    if not chosen:
        return
    colors = [clean_color(color_vars[0].get()), clean_color(color_vars[1].get())]
    colors[index] = clean_color(chosen)
    engine.commit_appearance(dialog, colors)
    _refresh_color_vars(engine, frame, color_vars)
    _sync_preview(frame)


def _arm_color_buttons(engine, frame, dialog, color_vars) -> None:
    """Keep Appearance's color samples clickable and pointed at this chooser."""
    if dialog is None:
        return
    for index, name in ((0, "theme_button_0"), (1, "theme_button_1")):
        button = getattr(dialog, name, None)
        if button is None:
            continue
        _configure_quiet(
            button,
            state="normal",
            command=lambda which=index: _pick_appearance(engine, frame, which, color_vars),
        )
    if getattr(dialog, "_uicust_color_armed", False):
        return
    dialog._uicust_color_armed = True

    def _restore(*_args, owner=dialog):
        try:
            if owner.winfo_exists():
                owner.after(1, lambda: _enable_theme_buttons(owner))
        except tk.TclError:
            return

    try:
        dialog.theme.trace_add("write", _restore)
    except (tk.TclError, AttributeError):
        pass
    # Settings calls themevarchanged after every plugin tab is built, and
    # that call disables these samples. Put them back once this call returns.
    try:
        dialog.after(1, lambda owner=dialog: _enable_theme_buttons(owner))
    except tk.TclError:
        return


def _enable_theme_buttons(dialog) -> None:
    """Appearance disables its color samples on the Default theme. Leave them on."""
    if dialog is None:
        return
    for name in ("theme_button_0", "theme_button_1"):
        _configure_quiet(getattr(dialog, name, None), state="normal")


def _restore_appearance_defaults(engine, frame, color_vars) -> None:
    """Put Normal text and Highlighted text back to Appearance's built-in colors."""
    frame._ui_customizer_suppress = True
    try:
        color_vars[0].set(DEFAULT_DARK_TEXT)
        color_vars[1].set(DEFAULT_DARK_HIGHLIGHT)
    finally:
        frame._ui_customizer_suppress = False
    dialog = _appearance_dialog(frame)
    engine.commit_appearance(dialog, (DEFAULT_DARK_TEXT, DEFAULT_DARK_HIGHLIGHT))
    _refresh_color_vars(engine, frame, color_vars)
    _sync_preview(frame)


def _theme_picked(frame) -> None:
    """Keep Appearance's sample and radios in step. The window theme changes on OK."""
    if getattr(frame, "_ui_customizer_suppress", False):
        return
    dialog = _appearance_dialog(frame)
    if dialog is not None:
        changed = getattr(dialog, "themevarchanged", None)
        if callable(changed):
            try:
                changed()
            except tk.TclError:
                pass
    _sync_preview(frame)


def _colors_edited(frame) -> None:
    """Typing a color updates Appearance's list and both samples."""
    if getattr(frame, "_ui_customizer_suppress", False):
        return
    form = getattr(frame, "_ui_customizer_form", None)
    if not form:
        return
    _push_dialog_colors(_appearance_dialog(frame), form["colors"])
    _sync_preview(frame)


def _push_dialog_colors(dialog, color_vars) -> None:
    """Write both colors into the open Appearance tab when each one is valid."""
    if dialog is None:
        return
    colors = [clean_color(color_vars[0].get()), clean_color(color_vars[1].get())]
    if not colors[0] or not colors[1]:
        return
    try:
        dialog.theme_colors[0] = colors[0]
        dialog.theme_colors[1] = colors[1]
        dialog.themevarchanged()
    except tk.TclError:
        return


def _sync_preview(frame) -> None:
    """Paint the Station and Hutton Orbital sample, and follow the theme choice."""
    form = getattr(frame, "_ui_customizer_form", None)
    if not form:
        return
    colors = form["colors"]
    foregrounds = (
        clean_color(colors[0].get()) or DEFAULT_DARK_TEXT,
        clean_color(colors[1].get()) or DEFAULT_DARK_HIGHLIGHT,
    )
    for button, foreground in zip(form["previews"], foregrounds):
        _configure_quiet(
            button,
            foreground=foreground,
            background="grey4",
            activebackground="grey4",
            state="normal",
        )
    _enable_theme_buttons(_appearance_dialog(frame))


def _configure_quiet(widget, **options) -> None:
    if widget is None:
        return
    try:
        if widget.winfo_exists():
            widget.configure(**options)
    except tk.TclError:
        return


def _opacity_moved(engine, frame, value) -> None:
    """Preview opacity while the slider moves. Ignore writes made by the form."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return
    form = getattr(frame, "_ui_customizer_form", None)
    if form and form.get("opacity_label") is not None:
        _configure_quiet(form["opacity_label"], text="%d%%" % number)
    if getattr(frame, "_ui_customizer_suppress", False):
        return
    engine.set_opacity(number, True, save=False)


def _opacity_released(engine, frame) -> None:
    if getattr(frame, "_ui_customizer_suppress", False):
        return
    engine.save()


def _reset(engine, frame) -> None:
    """Restore the stock layout and update the open form without toggling checks."""
    engine.reset()
    form = getattr(frame, "_ui_customizer_form", None)
    if not form:
        return
    frame._ui_customizer_suppress = True
    try:
        for _key, variable in form["checks"]:
            variable.set(True)
        form["colors"][0].set(engine.appearance_color(0))
        form["colors"][1].set(engine.appearance_color(1))
        form["opacity"].set(int(engine.state.get("opacity") or 100))
        _configure_quiet(form.get("opacity_label"), text="%d%%" % int(engine.state.get("opacity") or 100))
    finally:
        frame._ui_customizer_suppress = False
    _sync_preview(frame)
