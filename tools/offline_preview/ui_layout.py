"""Scrollable application pages. All bindings belong to this Tk window only."""

import tkinter as tk
from tkinter import ttk


class ScrollPage(ttk.Frame):
    def __init__(self, parent, background="#101722"):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=background, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self._last_view = None
        self.canvas.configure(yscrollcommand=self._view_changed)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.pending = None
        self.wheel_tag = f"ScrollPage:{self}"
        self.bind_class(self.wheel_tag, "<MouseWheel>", self._wheel)
        self.canvas.bind("<Configure>", self._schedule)
        self.inner.bind("<Configure>", self._schedule)
        self.bind("<Destroy>", self._destroy)

    def _view_changed(self, first, last):
        self.scrollbar.set(first, last)
        view = (float(first), float(last), self.canvas.winfo_width(), self.canvas.winfo_height())
        previous, self._last_view = self._last_view, view
        # A changed offset with the same viewport is scrolling, not a resize.
        # Notify artwork without making resize-driven layouts repaint every frame.
        if (previous and view[2:] == previous[2:] and view[0] != previous[0]
                and abs((view[1] - view[0]) - (previous[1] - previous[0])) < 1e-6):
            self.event_generate("<<PreviewPageScrolled>>", when="now")

    def _schedule(self, _event=None):
        if self.pending is None:
            self.pending = self.after_idle(self._layout)

    def _layout(self):
        self.pending = None
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        needed = self.inner.winfo_reqheight()
        self.canvas.itemconfigure(self.window, width=width, height=max(height, needed))
        self.canvas.configure(scrollregion=(0, 0, width, max(height, needed)))
        if needed > height:
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)
        self._bind_children(self)

    def _bind_children(self, widget):
        tags = widget.bindtags()
        if self.wheel_tag not in tags:
            # Route before native class bindings consume the wheel or change a
            # combobox/spinbox value merely because the pointer is over it.
            widget.bindtags((self.wheel_tag, *tags))
        for child in widget.winfo_children():
            if not isinstance(child, ScrollPage):
                self._bind_children(child)

    def _wheel(self, event):
        if not event.delta:
            return
        direction = -1 if event.delta > 0 else 1
        widget = event.widget
        if (not event.state & 0x4 and widget == self.focus_get()
                and widget.winfo_class() in {"Treeview", "Text", "Listbox"}):
            first, last = widget.yview()
            if (direction < 0 and first > 0) or (direction > 0 and last < 1):
                widget.yview_scroll(direction * max(1, abs(event.delta) // 120), "units")
                return "break"
        self.canvas.yview_scroll(direction * max(1, abs(event.delta) // 120), "units")
        return "break"

    def _destroy(self, event):
        if event.widget is self:
            if self.pending is not None:
                self.after_cancel(self.pending)
            self.unbind_class(self.wheel_tag, "<MouseWheel>")


class WrapRow(ttk.Frame):
    """Content-width controls wrap in their supplied order, without stretching."""
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.pending = None
        self.bind("<Configure>", self.schedule)
        self.bind("<Destroy>", self.cleanup)

    def set_items(self, items):
        self.items = list(items)
        self.schedule()

    def schedule(self, _event=None):
        if self.pending is None:
            self.pending = self.after_idle(self.layout)

    def layout(self):
        self.pending = None
        width = max(1, self.winfo_width())
        x, y, row_height = 0, 0, 0
        for item in self.items:
            w, h = item.winfo_reqwidth(), item.winfo_reqheight()
            if x and x + w + 16 > width:
                x, y, row_height = 0, y + row_height + 6, 0
            item.place(x=x + 8, y=y + 3, width=w, height=h)
            x += w + 16
            row_height = max(row_height, h)
        height = max(1, y + row_height + 6)
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def cleanup(self, event):
        if event.widget is self and self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
