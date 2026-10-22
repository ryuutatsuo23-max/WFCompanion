"""Window-only persistence; never saves appearance previews or character drafts."""
import re
from local_journal import LocalStore

DEFAULT = {"version": 1, "normal": None, "maximized": False}


def validate(data):
    if (not isinstance(data, dict) or set(data) != set(DEFAULT)
            or data["version"] != 1 or type(data["maximized"]) is not bool):
        raise ValueError("Invalid window placement")
    rect = data["normal"]
    if rect is not None and (not isinstance(rect, list) or len(rect) != 4
            or any(type(v) is not int for v in rect)
            or not 100 <= rect[0] <= 20000 or not 100 <= rect[1] <= 20000
            or any(abs(v) > 100000 for v in rect[2:])):
        raise ValueError("Invalid window rectangle")


def work_areas(root):
    """Include negative-coordinate monitors and their usable taskbar bounds."""
    try:
        import ctypes
        from ctypes import wintypes
        class Info(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        result = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                          wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user = ctypes.windll.user32
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
        def visit(monitor, _dc, _rect, _data):
            info = Info(); info.size = ctypes.sizeof(info)
            if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.work
                result.append((r.left, r.top, r.right, r.bottom))
            return True
        callback = callback_type(visit)
        user.EnumDisplayMonitors(None, None, callback, 0)
        if result:
            return result
    except (AttributeError, OSError):
        pass
    return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


def visible_rect(rect, areas):
    width, height, x, y = rect
    def overlap(area):
        left, top, right, bottom = area
        return max(0, min(x + width, right) - max(x, left)) * max(0, min(y + height, bottom) - max(y, top))
    left, top, right, bottom = max(areas, key=overlap)
    width = min(max(900, width), right - left)
    height = min(max(800, height), bottom - top)
    return [width, height, max(left, min(x, right - width)), max(top, min(y, bottom - height))]


class WindowPlacement:
    def __init__(self, root, directory):
        self.root = root
        self.store = LocalStore(directory, "window_placement.json", DEFAULT, validate)
        self.normal = self.store.data["normal"]
        self.maximized = self.store.data["maximized"]
        if self.normal:
            w, h, x, y = visible_rect(self.normal, work_areas(root))
            # Negative offsets in Tk mean distance from the opposite screen edge.
            # An explicit '+' followed by a negative coordinate is absolute.
            root.geometry(f"{w}x{h}+{x}+{y}")
            if self.store.data["maximized"] and root.state() != "withdrawn":
                root.state("zoomed")
        self.binding = root.bind("<Configure>", self.capture, add="+")

    def capture(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        state = self.root.state()
        if state in ("normal", "zoomed"):
            self.maximized = state == "zoomed"
        if state == "normal" and self.root.winfo_ismapped():
            match = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.root.geometry())
            if match:
                self.normal = [int(value) for value in match.groups()]

    def close(self):
        self.capture()
        if self.normal and self.root.state() != "withdrawn":
            try:
                self.store.save(dict(version=1, normal=self.normal,
                                     maximized=self.maximized))
            except (OSError, ValueError):
                # Corrupt/external changes are preserved by LocalStore.
                pass
        self.root.unbind("<Configure>", self.binding)
