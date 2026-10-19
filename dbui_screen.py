"""Place the layout editor window where the commander can see it.

The editor opens beside the main window when there is room, or at the
pointer when there is not. A rectangle is moved onto a work area and made
smaller only when it is taller or wider than that area.
"""

from __future__ import annotations

import sys

MARGIN = 8


def fit_on_screen(x, y, width, height, monitors, margin=MARGIN):
    """Return a rectangle that lies on one work area, or None if it already does.

    ``monitors`` are ``(x, y, width, height)`` work areas, the space inside
    the taskbar. A window that already lies entirely on those areas is left
    alone, including one that spans two monitors. A window that hangs off is
    shifted onto the monitor it overlaps most. A window larger than that
    monitor is reduced to the work area.
    """
    width = int(width)
    height = int(height)
    if width < 1 or height < 1:
        return None
    areas = []
    for item in monitors or ():
        rect = tuple(int(value) for value in item)
        if len(rect) != 4 or rect[2] < 1 or rect[3] < 1:
            continue
        areas.append(rect)
    if not areas:
        return None
    rect = (int(x), int(y), width, height)
    if covered_by(rect, areas):
        return None
    monitor = _choose_monitor(rect, areas)
    left, top, area_width, area_height = _inset(monitor, margin)
    fitted_width = min(width, area_width)
    fitted_height = min(height, area_height)
    fitted_x = rect[0]
    fitted_y = rect[1]
    if fitted_x < left:
        fitted_x = left
    if fitted_y < top:
        fitted_y = top
    if fitted_x + fitted_width > left + area_width:
        fitted_x = left + area_width - fitted_width
    if fitted_y + fitted_height > top + area_height:
        fitted_y = top + area_height - fitted_height
    fitted = (int(fitted_x), int(fitted_y), int(fitted_width), int(fitted_height))
    if fitted == rect:
        return None
    return fitted


def popup_at_pointer(x, y, width, height, monitors):
    """Put a popup's top-left on the click, and keep the whole window on screen.

    ``None`` means the size is not usable. A click that already fits is used
    as-is. A click near the edge is shifted back onto that work area.
    """
    try:
        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return None
    if width < 1 or height < 1:
        return None
    fitted = fit_on_screen(x, y, width, height, monitors)
    if fitted is None:
        return (x, y, width, height)
    return fitted


def popup_beside(avoid, width, height, monitors, gap=8):
    """Place a popup next to a rectangle so that rectangle stays visible.

    ``avoid`` is ``(x, y, width, height)`` in screen pixels, the window to
    keep visible. The popup tries the right, the left, above, and below. The
    first spot that fits on a work area without covering that window is used.
    ``None`` means the popup size is not usable.
    """
    try:
        ax, ay, aw, ah = (int(value) for value in avoid)
        width = int(width)
        height = int(height)
        gap = int(gap)
    except (TypeError, ValueError):
        return None
    if width < 1 or height < 1:
        return None
    if aw < 1 or ah < 1:
        return popup_at_pointer(ax, ay, width, height, monitors)
    avoid_rect = (ax, ay, aw, ah)
    spots = (
        (ax + aw + gap, ay),
        (ax - width - gap, ay),
        (ax, ay - height - gap),
        (ax, ay + ah + gap),
    )
    placed = []
    for x, y in spots:
        rect = popup_at_pointer(x, y, width, height, monitors)
        if rect is None:
            continue
        placed.append(rect)
        if not _rects_overlap(rect, avoid_rect):
            return rect
    if not placed:
        return None
    placed.sort(key=lambda rect: _overlap_area(rect, avoid_rect))
    return placed[0]


def _rects_overlap(one, other) -> bool:
    """True when two ``(x, y, width, height)`` rectangles share any pixel."""
    ax, ay, aw, ah = one
    bx, by, bw, bh = other
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _overlap_area(one, other) -> int:
    """Shared pixel count of two rectangles. Zero when they only touch."""
    ax, ay, aw, ah = one
    bx, by, bw, bh = other
    width = min(ax + aw, bx + bw) - max(ax, bx)
    height = min(ay + ah, by + bh) - max(ay, by)
    if width < 1 or height < 1:
        return 0
    return int(width) * int(height)


def covered_by(rect, monitors) -> bool:
    """True when every pixel of ``rect`` lies on at least one monitor."""
    area = _area(rect)
    if area <= 0:
        return True
    covered = 0
    for monitor in monitors:
        hit = _intersection(rect, monitor)
        if hit is not None:
            covered += _area(hit)
    return covered >= area


def tk_position(x, y) -> str:
    """Position-only Tk geometry, so a plugin's current size stays as it is."""
    return "+%s+%s" % (int(x), int(y))


def work_areas() -> list[tuple[int, int, int, int]]:
    """Work areas of the attached monitors. Empty when they cannot be read."""
    if sys.platform != "win32":
        return []
    try:
        return _windows_work_areas()
    except Exception:
        return []


def _area(rect) -> int:
    return max(0, int(rect[2])) * max(0, int(rect[3]))


def _intersection(a, b):
    ax, ay, aw, ah = (int(a[0]), int(a[1]), int(a[2]), int(a[3]))
    bx, by, bw, bh = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return (left, top, right - left, bottom - top)


def _center(rect):
    return rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0


def _choose_monitor(rect, monitors):
    best = None
    best_area = -1
    for monitor in monitors:
        hit = _intersection(rect, monitor)
        area = _area(hit) if hit is not None else 0
        if area > best_area:
            best = monitor
            best_area = area
    if best is not None and best_area > 0:
        return best
    return min(monitors, key=lambda monitor: _distance(rect, monitor))


def _distance(rect, monitor) -> float:
    cx, cy = _center(rect)
    mx, my = _center(monitor)
    return (cx - mx) ** 2 + (cy - my) ** 2


def _inset(monitor, margin):
    left, top, width, height = monitor
    pad = max(0, int(margin))
    if width <= pad * 2 + 1 or height <= pad * 2 + 1:
        return left, top, width, height
    return left + pad, top + pad, width - pad * 2, height - pad * 2


def _windows_work_areas():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    monitors = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_ssize_t,
    )

    def _enum(hmon, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            work = info.rcWork
            width = int(work.right - work.left)
            height = int(work.bottom - work.top)
            if width > 0 and height > 0:
                monitors.append((int(work.left), int(work.top), width, height))
        return 1

    callback = enum_proc(_enum)
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        return monitors
    return monitors
