"""Reusable offline item selector for manual name editors."""

from tkinter import ttk

from catalogue import validate_reference
from catalogue_ui import CataloguePicker


class ItemLookup:
    def __init__(self, host, parent, name, category="All", label="Find item…"):
        self.host, self.name, self.category = host, name, category
        self.reference = None
        self.picker = None
        self.setting = False
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        self.button = ttk.Button(row, text=label, command=self.open)
        self.button.pack(side="left")
        self.notice = ttk.Label(row, style="Muted.TLabel", wraplength=530)
        self.notice.pack(side="left", padx=10)
        ttk.Button(row, text="Clear item link", command=lambda: self.load(None)).pack(side="right")
        name.trace_add("write", self._name_changed)
        if host.catalogue.error:
            self.button.state(["disabled"])
        self._render()

    def _render(self):
        ref = self.reference
        self.notice.configure(text=(f"Linked item #{ref.item_id} · checked {ref.checked_on}" if ref else
                                    "Search unavailable; manual entry works" if self.host.catalogue.error else "Manual entry or local lookup"))

    def _name_changed(self, *_args):
        if self.setting or self.reference is None:
            return
        try:
            validate_reference(self.name.get(), self.reference)
        except ValueError:
            self.load(None)

    def load(self, reference):
        self.reference = reference
        self._render()

    def open(self):
        if self.host.catalogue.error:
            return
        if self.picker is not None:
            self.picker.window.lift()
        else:
            self.picker = CataloguePicker(self.host, self.host.catalogue, self.choose, self._closed, category=self.category)

    def choose(self, item):
        item.validate()
        self.setting = True
        try:
            self.name.set(item.reference.name)
            self.reference = item.reference
        finally:
            self.setting = False
        self._render()

    def _closed(self):
        self.picker = None

    def close(self):
        if self.picker is not None:
            self.picker.close()
