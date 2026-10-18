# Docking Bay UI

Docking Bay UI is an EDMC plugin. It rearranges the blocks in EDMC's main window, hides blocks you do not want, and controls the window's text colors and opacity. Layout, visibility, colors, and opacity are saved and come back the next time EDMC starts.

Install it, then restart EDMC once so the plugin loads. After that the main window shows an **Edit layout** button on the Update line, at the left, and File > Settings has a **Docking Bay UI** tab. The Edit layout button uses `outfitting.png` next to the plugin files.

## Edit layout

**Edit layout** turns on edit mode and opens the editor window beside the main window, in open space, without covering the main window. The editor lists any **Hidden addons** with a **Show** button for each, then **Reset to Default** and **Finished editing**. Closing the editor's X does the same as **Finished editing**: the layout is saved and edit mode turns off.

In edit mode only, every block gets a contrasting title bar with a drag grip, a "drag onto another block to reorder" hint, and a hide control (the eye) on its right. Outside edit mode the main window looks like a normal EDMC window: no title bars, no eyes. The window grows to fit the bars while editing and shrinks back when you finish.

## Rearrange the window

Drag a block by its **title bar** and drop it onto another block. The block you drag takes that block's spot, and the block below it is pushed down one, so the rest of the order shifts down to make room. A drop that lands on the same block, or on empty space, leaves the order alone. As you drag, a highlight shows the block the drop will land on.

Until you drag for the first time, short single-line blocks (for example a one-line status add-on) sink to the bottom of the list in alphabetical order. Once you drag a block, your order wins and that automatic sorting stops. **Reset** and **Reset to Default** bring the automatic sorting back.

The layout is saved the moment you drop, and **Finished editing** saves it again.

## Hide blocks

Use the **eye** on a block while editing to hide it. Hidden blocks show up in the editor under **Hidden addons**, each with a **Show** button to bring it back. The settings tab lists the same blocks under **Turn elements on or off**: clear a box to hide a block, tick it to show it again.

Hiding puts the widget back the way EDMC built it, and showing it returns it to the same parent. The commander lines (Cmdr, Ship, Suit, System, Station) are one block named **Commander**, so one hide control moves them all together. **Rescan** looks again for plugin frames that appeared after startup.

## Settings tab

**Docking Bay UI** in File > Settings has three parts:

- **Turn elements on or off** - the visibility checklist described above.
- **Appearance** - **Default**, **Dark**, **Transparent**, **Normal text**, and **Highlighted text**. **Pick** and the two sample labels (Station for Normal text, Hutton Orbital for Highlighted text) open a color chooser. **Defaults** restores Normal text to `#ff8000` and Highlighted text to white. **Apply appearance colors** writes the colors and repaints the main window. A theme change is applied when you press **OK**.
- **Window opacity** - a slider from 15 to 100. 100 is solid. It will not go below 15, so the window cannot disappear. The value is also written to EDMC's own transparency setting.

**Reset** on this tab restores the stock order, shows every block, and puts back the opacity EDMC was using when the plugin first started. It leaves the Appearance colors alone.

## What the plugin protects

- The window never narrows below the width EDMC needed at startup, so hiding add-ons cannot clip the info line. Blocks grow horizontally but not vertically.
- The green separators EDMC draws between plugins stay hidden.
- Core widgets (commander, ship, suit, system, station, Update, status) are never moved to a new parent. Only their grid cell changes, so other plugins and the theme keep working.
- The menu stays on the top row, so the window keeps its title bar and close button.
- Some plugins open their own popup window. Docking Bay UI keeps that window on the visible work area, without the correction repeating and walking the window across the screen.

## Notes

- EDMC must be restarted once after the plugin is installed.
- The Update row and the settings edit buttons follow EDMC's theme, so they match the rest of the window.

## License

Docking Bay UI is released under the GNU General Public License v2.0 or later. See `LICENSE`.

