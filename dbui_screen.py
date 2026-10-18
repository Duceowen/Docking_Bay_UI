"""Keep a popup inside the monitors the commander can see.

A plugin can stay hidden and then open a window at a saved position, or
centered on a window that already sits near the edge. The rectangle is
moved onto a work area. It is made smaller only when it is taller or wider
than that area.

The Elite overlay window is not moved. It follows the game on purpose.
"""

from __future__ import annotations

import sys
import threading
import time

MARGIN = 8
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
TH32CS_SNAPPROCESS = 0x00000002


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

    ``avoid`` is ``(x, y, width, height)`` in screen pixels, the addon the
    commander is resizing. The popup tries the right, the left, above, and
    below. The first spot that fits on a work area without covering the addon
    is used. ``None`` means the popup size is not usable.
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


def tk_geometry(width, height, x, y) -> str:
    """Tk geometry string. A negative coordinate keeps its sign after the plus."""
    return "%sx%s+%s+%s" % (int(width), int(height), int(x), int(y))


def tk_position(x, y) -> str:
    """Position-only Tk geometry, so a plugin's current size stays as it is."""
    return "+%s+%s" % (int(x), int(y))


def wm_origin(screen_x, screen_y, wm_x, wm_y, root_x, root_y):
    """Tk ``geometry`` position whose client origin lands on ``screen_x, screen_y``.

    ``winfo_rootx`` is the client origin on the screen. ``winfo_x`` is the
    position ``geometry`` stores. They differ by the border and the title bar.
    Writing the client origin back through ``geometry`` shifts the window by
    that frame on every pass.
    """
    return (
        int(screen_x) - (int(root_x) - int(wm_x)),
        int(screen_y) - (int(root_y) - int(wm_y)),
    )


def should_fit_foreign(title: str, class_name: str) -> bool:
    """False for the game-follow overlay. Other popped windows can be moved."""
    label = (title or "").strip().casefold()
    if label == "edmc modern overlay":
        return False
    kind = (class_name or "").strip().casefold()
    if kind.startswith("qt") or "qwindow" in kind:
        return False
    return True


def descendant_pids(root_pid: int, parents: dict) -> set[int]:
    """Process ids whose parent chain reaches ``root_pid``, excluding the root."""
    children = {}
    root_pid = int(root_pid)
    for pid, parent in (parents or {}).items():
        pid = int(pid)
        parent = int(parent)
        if pid == parent:
            continue
        children.setdefault(parent, []).append(pid)
    found = set()
    stack = [root_pid]
    while stack:
        current = stack.pop()
        for child in children.get(current, ()):
            if child in found or child == root_pid:
                continue
            found.add(child)
            stack.append(child)
    return found


def is_descendant(pid: int, root_pid: int, parents: dict) -> bool:
    """True when ``pid`` was started by ``root_pid`` or by one of its children."""
    return int(pid) in descendant_pids(root_pid, parents)


def work_areas() -> list[tuple[int, int, int, int]]:
    """Work areas of the attached monitors. Empty when they cannot be read."""
    if sys.platform != "win32":
        return []
    try:
        return _windows_work_areas()
    except Exception:
        return []


def process_parents() -> dict[int, int]:
    """Map each running process id to its parent. Empty when the list cannot be read."""
    if sys.platform != "win32":
        return {}
    try:
        return _windows_process_parents()
    except Exception:
        return {}


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


def _windows_process_parents():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        return {}
    parents = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return {}
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


class _SilentLog:
    def info(self, *_args, **_kwargs):
        return None

    def exception(self, *_args, **_kwargs):
        return None


class ForeignPopupGuard:
    """Move windows opened by programs EDMC started back onto the work area.

    EDMC's own Tk windows are handled separately. This watch is for a plugin
    that launches another process, such as the Overlay Controller, and then
    shows a window. The game overlay is skipped.
    """

    def __init__(self, log=None):
        self._log = log if log is not None else _SilentLog()
        self._user32 = None
        self._callback = None
        self._hooks = []
        self._ignore = set()
        self._seen = {}
        self._fit_times = {}
        self._pending = set()
        self._parents = {}
        self._parents_at = 0.0
        self._root_pid = 0
        self._stopped = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Begin watching. A second call does nothing. Failure is logged."""
        if self._hooks or sys.platform != "win32":
            return
        self._stopped = False
        try:
            self._arm()
        except Exception:
            self._log.exception("Docking Bay UI could not watch plugin popups")
            self.stop()

    def stop(self) -> None:
        """Drop the watch. Safe to call more than once."""
        self._stopped = True
        hooks = list(self._hooks)
        self._hooks = []
        user32 = self._user32
        self._callback = None
        if user32 is None:
            return
        for hook in hooks:
            try:
                user32.UnhookWinEvent(hook)
            except Exception:
                continue

    def _arm(self) -> None:
        import ctypes
        import os
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        event_proc = ctypes.WINFUNCTYPE(
            None,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_long,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            event_proc,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        user32.SetWinEventHook.restype = ctypes.c_void_p
        user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]
        user32.UnhookWinEvent.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.MoveWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.BOOL,
        ]
        user32.MoveWindow.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short

        self._user32 = user32
        self._root_pid = int(os.getpid())
        callback = event_proc(self._on_event)
        self._callback = callback
        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        for event in (EVENT_OBJECT_SHOW, EVENT_OBJECT_LOCATIONCHANGE):
            hook = user32.SetWinEventHook(event, event, None, callback, 0, 0, flags)
            if hook:
                self._hooks.append(hook)
        if not self._hooks:
            self._log.info("Docking Bay UI could not watch popups opened by programs EDMC starts")

    def _on_event(self, _hook, event, hwnd, id_object, id_child, _thread, _time_stamp) -> None:
        try:
            self._handle_event(event, hwnd, id_object, id_child)
        except Exception:
            self._log.exception("Docking Bay UI could not keep a popup on screen")

    def _handle_event(self, event, hwnd, id_object, id_child) -> None:
        if id_object != 0 or id_child != 0 or not hwnd:
            return
        key = int(ctypes_hwnd(hwnd))
        if event != EVENT_OBJECT_SHOW and key in self._ignore:
            return
        user32 = self._user32
        if user32 is None or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not self._tracks(int(pid.value), refresh=event == EVENT_OBJECT_SHOW):
            return
        title = _window_text(user32.GetWindowTextW, hwnd)
        class_name = _window_text(user32.GetClassNameW, hwnd)
        if not should_fit_foreign(title, class_name):
            self._ignore.add(key)
            return
        rect = _hwnd_rect(user32, hwnd)
        if rect is None:
            return
        if self._seen.get(key) == rect:
            return
        # A click that opens the window can still be held down. Show is the
        # moment the window appears, so that one is moved immediately. A move
        # while the button is down is a drag and waits until the button is up.
        if event != EVENT_OBJECT_SHOW and _button_down(user32):
            self._retry_when_released(hwnd, key)
            return
        monitors = work_areas()
        fitted = fit_on_screen(*rect, monitors)
        self._seen[key] = rect if fitted is None else fitted
        if len(self._seen) > 200:
            self._seen.clear()
            self._seen[key] = rect if fitted is None else fitted
        if fitted is None or not self._allow(key):
            return
        nx, ny, nw, nh = fitted
        user32.MoveWindow(hwnd, nx, ny, nw, nh, True)
        x, y, width, height = rect
        if abs(nx - x) > 24 or abs(ny - y) > 24 or nw != width or nh != height:
            self._log.info(
                "Docking Bay UI moved a popup onto the screen (%s,%s %sx%s -> %s,%s %sx%s)",
                x, y, width, height, nx, ny, nw, nh,
            )

    def _tracks(self, pid: int, refresh: bool) -> bool:
        now = time.monotonic()
        if refresh or now - self._parents_at > 1.0 or not self._parents:
            self._parents = process_parents()
            self._parents_at = now
        return is_descendant(pid, self._root_pid, self._parents)

    def _retry_when_released(self, hwnd, key: int) -> None:
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
        timer = threading.Timer(0.25, self._retry, args=(hwnd, key))
        timer.daemon = True
        timer.start()

    def _retry(self, hwnd, key: int) -> None:
        with self._lock:
            self._pending.discard(key)
        user32 = self._user32
        if self._stopped or user32 is None or _button_down(user32):
            return
        try:
            self._handle_event(EVENT_OBJECT_LOCATIONCHANGE, hwnd, 0, 0)
        except Exception:
            self._log.exception("Docking Bay UI could not keep a popup on screen")

    def _allow(self, key: int) -> bool:
        now = time.monotonic()
        times = [stamp for stamp in self._fit_times.get(key, ()) if now - stamp < 2.0]
        if len(times) >= 4:
            self._fit_times[key] = times
            return False
        times.append(now)
        self._fit_times[key] = times
        return True


# Dark and Transparent call overrideredirect, which drops the resize frame.
# Putting WS_THICKFRAME back paints a white rim, and the system frame is
# larger than a small inset. A borderless window has that bit cleared.
# A normal window keeps the frame Windows gave it. The helpers below still
# describe a client that covers the window: an inset paints white, and
# returning 0 from WM_NCCALCSIZE keeps the old client bitmap.
WS_THICKFRAME = 0x00040000
WS_CAPTION = 0x00C00000
RESIZE_BORDER = 12
NCCALCSIZE_RESULT = 0x0300
_GWL_STYLE = -16
_GWLP_WNDPROC = -4
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_DWMWA_BORDER_COLOR = 34
_DWMWA_COLOR_NONE = 0xFFFFFFFE
_SWP_FRAME = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
_HTLEFT = 10
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17
_resize_hooks: dict[int, dict] = {}


def thick_frame_style(style: int) -> int:
    """Turn the resize border on. The caption bit is left as it was."""
    return (int(style) & 0xFFFFFFFF) | WS_THICKFRAME


def frame_style_without_resize(style: int) -> int:
    """Drop the thick-frame bit. The caption bit is left as it was."""
    return (int(style) & 0xFFFFFFFF) & ~WS_THICKFRAME


def style_has_thick_frame(style: int) -> bool:
    return bool((int(style) & 0xFFFFFFFF) & WS_THICKFRAME)


def style_has_caption(style: int) -> bool:
    return bool((int(style) & 0xFFFFFFFF) & WS_CAPTION)


def client_rect_for_resize(left, top, right, bottom, margin=RESIZE_BORDER, minimum=80):
    """Client rect for a borderless window. The client covers the window.

    An inset would be a white rim and would clip the text. ``margin`` is the
    grab width used by ``resize_hit_test``. ``minimum`` is the client size
    that still keeps a middle area for normal clicks. Neither one shrinks
    the client.
    """
    del margin, minimum
    return (int(left), int(top), int(right), int(bottom))


def resize_hit_test(x, y, left, top, right, bottom, margin=RESIZE_BORDER, minimum=80):
    """Hit-test code when the pointer is on the resize rim, else None.

    None means the pointer is in the middle, or the window is too small to
    give up its edges. The codes are the Windows HT* values.
    """
    try:
        x, y = int(x), int(y)
        left, top, right, bottom = int(left), int(top), int(right), int(bottom)
        margin = max(0, int(margin))
        minimum = int(minimum)
    except (TypeError, ValueError):
        return None
    width = right - left
    height = bottom - top
    if width < minimum or height < minimum or margin < 1:
        return None
    if x < left or y < top or x >= right or y >= bottom:
        return None
    on_left = x < left + margin
    on_right = x >= right - margin
    on_top = y < top + margin
    on_bottom = y >= bottom - margin
    if on_top and on_left:
        return _HTTOPLEFT
    if on_top and on_right:
        return _HTTOPRIGHT
    if on_bottom and on_left:
        return _HTBOTTOMLEFT
    if on_bottom and on_right:
        return _HTBOTTOMRIGHT
    if on_left:
        return _HTLEFT
    if on_right:
        return _HTRIGHT
    if on_top:
        return _HTTOP
    if on_bottom:
        return _HTBOTTOM
    return None


def resize_border_action(borderless: bool, hooked: bool, thick: bool) -> str:
    """What the main window needs.

    A borderless window never gains a frame. ``remove`` takes our hook off
    and, when the window is borderless, also clears the thick frame.
    ``strip`` clears that frame when the window was never hooked.
    ``keep`` means the window is already right. A normal window only loses
    the hook. Its own frame stays.
    """
    if borderless:
        if hooked:
            return "remove"
        if thick:
            return "strip"
        return "keep"
    if hooked:
        return "remove"
    return "keep"


def ensure_resize_border(widget_id: int, borderless: bool) -> str:
    """Take the extra frame off a borderless main window.

    Dark and Transparent have no caption. A thick frame on that window is
    the white rim. A normal window keeps the frame Windows gave it.
    Returns the action that was taken.
    """
    if sys.platform != "win32":
        return "keep"
    user32 = _resize_user32()
    hwnd = _outer_hwnd(user32, int(widget_id))
    if not hwnd:
        return "keep"
    hooked = _hook_is_current(user32, hwnd)
    thick = style_has_thick_frame(_window_style(user32, hwnd))
    action = resize_border_action(bool(borderless), hooked, thick)
    if action == "remove":
        if borderless:
            _clear_thick_frame(user32, hwnd)
        _remove_resize_border(user32, hwnd)
    elif action == "strip":
        _clear_thick_frame(user32, hwnd)
    return action


def release_resize_borders() -> None:
    """Put the original window procedure back. Safe to call more than once."""
    if sys.platform != "win32" or not _resize_hooks:
        return
    try:
        user32 = _resize_user32()
    except Exception:
        _resize_hooks.clear()
        return
    for hwnd in list(_resize_hooks):
        try:
            _remove_resize_border(user32, hwnd)
        except Exception:
            _resize_hooks.pop(hwnd, None)


def _resize_user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd_type = ctypes.c_void_p
    user32.GetParent.argtypes = [hwnd_type]
    user32.GetParent.restype = hwnd_type
    user32.IsWindow.argtypes = [hwnd_type]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [hwnd_type, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [hwnd_type, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [hwnd_type, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    get_ptr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_ptr.argtypes = [hwnd_type, ctypes.c_int]
    get_ptr.restype = ctypes.c_void_p
    set_ptr.argtypes = [hwnd_type, ctypes.c_int, ctypes.c_void_p]
    set_ptr.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        hwnd_type,
        ctypes.c_uint,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        hwnd_type,
        hwnd_type,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [hwnd_type]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [hwnd_type, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32._uicust_get_ptr = get_ptr
    user32._uicust_set_ptr = set_ptr
    return user32


def _outer_hwnd(user32, widget_id: int) -> int:
    """The real top-level handle. Tk's id is sometimes the inner child."""
    hwnd = int(widget_id or 0)
    if not hwnd:
        return 0
    parent = int(user32.GetParent(hwnd) or 0)
    if _class_name(user32, hwnd) == "TkTopLevel":
        return hwnd
    if parent and _class_name(user32, parent) == "TkTopLevel":
        return parent
    return parent or hwnd


def _class_name(user32, hwnd: int) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(64)
    try:
        user32.GetClassNameW(hwnd, buffer, 64)
    except Exception:
        return ""
    return buffer.value


def _window_style(user32, hwnd: int) -> int:
    return int(user32.GetWindowLongW(hwnd, _GWL_STYLE)) & 0xFFFFFFFF


def _signed_long(value: int) -> int:
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def _ptr_value(pointer) -> int:
    return int(getattr(pointer, "value", pointer) or 0)


def _hook_is_current(user32, hwnd: int) -> bool:
    hook = _resize_hooks.get(int(hwnd))
    if not hook:
        return False
    try:
        current = user32._uicust_get_ptr(hwnd, _GWLP_WNDPROC)
    except Exception:
        return False
    return _ptr_value(current) == int(hook["proc"])


def _install_resize_border(user32, hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    hwnd = int(hwnd)
    if not _hook_is_current(user32, hwnd):
        previous = user32._uicust_get_ptr(hwnd, _GWLP_WNDPROC)
        previous_value = _ptr_value(previous)
        wndproc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_void_p,
            ctypes.c_uint,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        def proc(window, msg, wparam, lparam):
            try:
                if msg == _WM_NCCALCSIZE and int(wparam):
                    proposed = _proposed_window_rect(lparam)
                    result = user32.CallWindowProcW(
                        ctypes.c_void_p(previous_value), window, msg, wparam, lparam
                    )
                    if proposed is None:
                        return result
                    return _restore_client_rect(lparam, proposed)
                elif msg == _WM_NCHITTEST:
                    hit = _resize_hit_from_message(user32, window, lparam)
                    if hit:
                        return hit
            except Exception:
                pass
            return user32.CallWindowProcW(ctypes.c_void_p(previous_value), window, msg, wparam, lparam)

        callback = wndproc(proc)
        proc_ptr = ctypes.cast(callback, ctypes.c_void_p)
        user32._uicust_set_ptr(hwnd, _GWLP_WNDPROC, proc_ptr)
        _resize_hooks[hwnd] = {
            "callback": callback,
            "proc": _ptr_value(proc_ptr),
            "previous": previous_value,
            "user32": user32,
        }
    style = _window_style(user32, hwnd)
    updated = thick_frame_style(style)
    if updated != style:
        user32.SetWindowLongW(hwnd, _GWL_STYLE, _signed_long(updated))
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME)


def _remove_resize_border(user32, hwnd: int) -> None:
    import ctypes

    hwnd = int(hwnd)
    hook = _resize_hooks.get(hwnd)
    if hook is None:
        return
    try:
        alive = bool(user32.IsWindow(hwnd))
    except Exception:
        alive = False
    if alive and _hook_is_current(user32, hwnd):
        user32._uicust_set_ptr(hwnd, _GWLP_WNDPROC, ctypes.c_void_p(int(hook["previous"])))
        try:
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME)
        except Exception:
            pass
    _resize_hooks.pop(hwnd, None)


def _clear_thick_frame(user32, hwnd: int) -> None:
    """Clear WS_THICKFRAME and ask Windows to apply the new frame."""
    hwnd = int(hwnd)
    style = _window_style(user32, hwnd)
    updated = frame_style_without_resize(style)
    if updated == style:
        return
    user32.SetWindowLongW(hwnd, _GWL_STYLE, _signed_long(updated))
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME)


def _calc_params(lparam):
    """The NCCALCSIZE_PARAMS behind a window-procedure lParam."""
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = (
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        )

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = (("rgrc", RECT * 3), ("lppos", ctypes.c_void_p))

    return ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents


def _proposed_window_rect(lparam):
    """``(left, top, right, bottom)`` Windows proposed for the whole window."""
    try:
        rect = _calc_params(lparam).rgrc[0]
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return None


def _restore_client_rect(lparam, rect) -> int:
    """Make the client cover the window and ask Windows to redraw it.

    The tuple is the proposed window rect. Returning 0 would keep the old
    client, and Windows would draw that copy while the window moves.
    """
    params = _calc_params(lparam)
    target = params.rgrc[0]
    target.left = int(rect[0])
    target.top = int(rect[1])
    target.right = int(rect[2])
    target.bottom = int(rect[3])
    params.rgrc[0] = target
    return NCCALCSIZE_RESULT


def _signed_word(value: int) -> int:
    value &= 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value


def _resize_hit_from_message(user32, window, lparam):
    """HT* code when the pointer is on this window's rim, else None."""
    try:
        if bool(user32.IsZoomed(window)):
            return None
    except Exception:
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    try:
        if not user32.GetWindowRect(window, ctypes.byref(rect)):
            return None
    except Exception:
        return None
    value = int(lparam) & 0xFFFFFFFF
    return resize_hit_test(
        _signed_word(value),
        _signed_word(value >> 16),
        int(rect.left),
        int(rect.top),
        int(rect.right),
        int(rect.bottom),
    )


def _hide_system_border(hwnd: int) -> None:
    """Ask Windows 11 not to paint its own border. Older Windows ignore this."""
    import ctypes

    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except Exception:
        return
    color = ctypes.c_uint(_DWMWA_COLOR_NONE)
    try:
        dwmapi.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmSetWindowAttribute(
            int(hwnd),
            _DWMWA_BORDER_COLOR,
            ctypes.byref(color),
            ctypes.sizeof(color),
        )
    except Exception:
        return


def ctypes_hwnd(hwnd) -> int:
    """Normalize a window handle from a ctypes callback to an int."""
    value = getattr(hwnd, "value", hwnd)
    return int(value or 0)


def _window_text(reader, hwnd) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(512)
    try:
        reader(hwnd, buffer, 512)
    except Exception:
        return ""
    return buffer.value


def _hwnd_rect(user32, hwnd):
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 2 or height < 2:
        return None
    return int(rect.left), int(rect.top), width, height


def _button_down(user32) -> bool:
    try:
        return bool(user32.GetAsyncKeyState(0x01) & 0x8000)
    except Exception:
        return False
