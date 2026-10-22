"""A compact per-character gear wishlist with manual BiS candidate labels."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from catalogue import wishlist_slots, display_name
from catalogue_ui import CataloguePicker
from gear import PRIORITIES, SLOTS, STATUSES, GearItem, GearStore, GearWishlist
from gear_filters import GearFilters, GearFilterStore
from gear_undo import GearUndoStore, RemovedGoal
from professions import ProfessionPlan, material_key, material_name
from inventory import InventoryBook
from item_stock import OWNERSHIP_FILTERS, RecordedCount, ownership_state, recorded_stock
from ui_layout import ScrollPage


DEFAULTS = {"name": "", "slot": "Unspecified", "priority": "Normal", "status": "Wanted",
            "source": "", "note": "", "bis_candidate": False}


class GearUI:
    def __init__(self, host):
        self.host = host
        self.store = GearStore(host.store.directory)
        self.characters = self.store.load()
        self.active_id = host.profile.id
        self.filter_store = GearFilterStore(host.store.directory)
        self.filter_choices = dict(self.filter_store.profiles)
        self.save_pending = None
        self.filter_error = ""
        self.edit_id = None
        self.drafts = {}
        self.undo_store = GearUndoStore(host.store.directory)
        self.undo_records = deepcopy(self.undo_store.records)
        self.undo_error = ""
        self.last_removed = {key: record for key, record in self.undo_records.items()
                             if not any(item.id == record.item.id for item in self.characters.get(key, GearWishlist()).entries)}
        self.refreshing = False
        self.dirty = False
        self.catalogue = host.catalogue
        self.catalogue_ref = None
        self.picker = None
        self.setting_fields = False
        self.owned = {}
        self.fields = {key: (tk.BooleanVar(value=value) if type(value) is bool else tk.StringVar(value=value))
                       for key, value in DEFAULTS.items()}
        saved = self.filter_store.get(self.active_id)
        self.query = tk.StringVar(value=saved.query)
        self.status_filter = tk.StringVar(value=saved.status)
        self.ownership_filter = tk.StringVar(value=saved.ownership)
        self.page = ttk.Frame(host.tabs, padding=(0, 12, 0, 0))
        self.scroll = ScrollPage(self.page)
        self.scroll.pack(fill="both", expand=True)
        parent = self.scroll.inner
        ttk.Label(parent, text="Gear wishlist", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Your goals for this character. BiS candidate is your own label, not a verified gear ranking.",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(4, 10))
        filters = ttk.Frame(parent)
        filters.pack(fill="x")
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Search").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(filters, textvariable=self.query, width=16)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(filters, text="Goal status").grid(row=0, column=2, sticky="w")
        self.status_combo = ttk.Combobox(filters, textvariable=self.status_filter, values=("All", *STATUSES),
                                         state="readonly", width=11)
        self.status_combo.grid(row=0, column=3, padx=(8, 16))
        ttk.Label(filters, text="Ownership").grid(row=0, column=4, sticky="w")
        self.ownership_combo = ttk.Combobox(filters, textvariable=self.ownership_filter, values=OWNERSHIP_FILTERS,
                                            state="readonly", width=11)
        self.ownership_combo.grid(row=0, column=5, padx=(8, 0))
        self.reset_filters_button = ttk.Button(filters, text="Reset filters", command=self.reset_filters)
        self.reset_filters_button.grid(row=0, column=6, padx=(8, 0))
        host.style.configure("WishlistFilter.TButton", padding=(4, 2), anchor="w", wraplength=820,
                             foreground="#75ddcb")
        host.style.configure("Invalid.WishlistFilter.TButton", foreground="#ff929e")
        self.filter_indicator = ttk.Button(parent, style="WishlistFilter.TButton", command=self.reset_filters)
        self.filter_indicator.bind("<Return>", self._activate_filter_indicator)
        self.filter_indicator.pack(anchor="w", pady=(5, 0))
        panel = ttk.Frame(parent)
        panel.pack(fill="x", pady=(10, 8))
        panel.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(panel, columns=("name", "bags", "bank", "ownership", "slot", "priority", "status", "bis", "source"),
                                  show="headings", height=6, selectmode="browse")
        for key, label, width in (("name", "Item", 200), ("bags", "Bags", 90), ("bank", "Bank", 90),
                                   ("ownership", "Ownership", 115), ("slot", "Slot", 100), ("priority", "Priority", 75),
                                   ("status", "Goal status", 110), ("bis", "BiS goal", 80), ("source", "Source", 190)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=100 if key in ("name", "source", "ownership") else 80 if key in ("bags", "bank") else 65,
                              stretch=key in ("name", "source"))
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(panel, command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.table.xview)
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=self.horizontal.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        self.stock_detail = ttk.Label(parent, text="Recorded stock · Manual counts, not a live scan. Wanted/Obtained is your goal status.",
                                      style="Muted.TLabel", wraplength=820, justify="left")
        self.stock_detail.pack(anchor="w", pady=(0, 8))
        self.summary = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.summary.pack(anchor="w", pady=(0, 4))
        self.ownership_summary = ttk.Frame(parent)
        self.ownership_summary.pack(anchor="w", pady=(0, 10), before=panel)
        ttk.Label(self.ownership_summary, text="Ownership (all goals)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.ownership_buttons = {}
        for column, choice in enumerate(OWNERSHIP_FILTERS, start=1):
            button = ttk.Button(self.ownership_summary, takefocus=True,
                                command=lambda value=choice: self.ownership_filter.set(value))
            button.grid(row=0, column=column, padx=(0, 6))
            self.ownership_buttons[choice] = button
        lookup = ttk.Frame(parent)
        lookup.pack(fill="x", pady=(0, 8))
        self.find_button = ttk.Button(lookup, text="Find item…", command=self.open_picker)
        self.find_button.pack(side="left")
        self.link_label = ttk.Label(lookup, style="Muted.TLabel", wraplength=620)
        self.link_label.pack(side="left", padx=10)
        ttk.Button(lookup, text="Clear item link", command=self.clear_link).pack(side="right")
        self._fields(parent, (("Item name", "name", None), ("Slot", "slot", SLOTS), ("Status", "status", STATUSES)))
        self._fields(parent, (("Priority", "priority", PRIORITIES), ("Source (optional)", "source", None)))
        ttk.Label(parent, text="Notes (optional)", style="Muted.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Entry(parent, textvariable=self.fields["note"]).pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(parent, text="BiS candidate (my own choice)", variable=self.fields["bis_candidate"]).pack(anchor="w", pady=(0, 10))
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        ttk.Button(actions, text="Apply item", command=self.apply, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="New entry", command=self.clear).pack(side="left", padx=8)
        ttk.Button(actions, text="Remove selected", command=self.remove).pack(side="left")
        self.undo_button = ttk.Button(actions, text="Undo last removal", command=self.undo_removal, state="disabled")
        self.undo_button.pack(side="left", padx=(8, 0))
        self.save_button = ttk.Button(actions, text="Save wishlist", command=self.save, style="Primary.TButton")
        self.save_button.pack(side="right")
        self.undo_detail = ttk.Button(parent, style="WishlistFilter.TButton", command=self.undo_removal)
        self.undo_detail.bind("<Return>", self._activate_undo_detail)
        self.undo_detail.pack(anchor="w", pady=(5, 0))
        self.notice = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.notice.pack(anchor="w", pady=(10, 8))
        self.query.trace_add("write", self._query_changed)
        self.status_filter.trace_add("write", self._filter_changed)
        self.ownership_filter.trace_add("write", self._filter_changed)
        for key in ("name", "slot"):
            self.fields[key].trace_add("write", self._identity_changed)
        self.stock_binding = host.root.bind("<<InventoryStockChanged>>", self._stock_changed, add="+")
        self.refresh()
        self.message("Apply item previews changes; Save wishlist keeps them locally. Obtained is a manual status.")
        self._render_link()
        if self.catalogue.error:
            self.find_button.state(["disabled"])
            self.message(self.catalogue.error, True)
        if self.store.error or host.store.error:
            self.message(self.store.error or "Saved character profiles are unavailable; wishlist saving is disabled.", True)
            self.save_button.state(["disabled"])

    def _fields(self, parent, definitions):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        for column, (label, key, values) in enumerate(definitions):
            row.columnconfigure(column, weight=2 if key in ("name", "source") else 1)
            ttk.Label(row, text=label, style="Muted.TLabel").grid(row=0, column=column, sticky="w", pady=(0, 3))
            widget = (ttk.Combobox(row, textvariable=self.fields[key], values=values, state="readonly", width=14)
                      if values else ttk.Entry(row, textvariable=self.fields[key], width=20))
            widget.grid(row=1, column=column, sticky="ew", padx=(0, 12), pady=(0, 8))

    @property
    def wishlist(self):
        return self.characters.setdefault(self.host.profile.id, GearWishlist())

    def message(self, value, error=False):
        if self.store.error and self.store.error not in value:
            value += " Saving disabled: the original wishlist file could not be read."
            error = True
        if self.filter_store.error or self.filter_error:
            value += " Wishlist filters are session-only: " + (self.filter_store.error or self.filter_error)
            error = True
        if self.undo_store.error or self.undo_error:
            value += " Undo history is session-only: " + (self.undo_store.error or self.undo_error)
            error = True
        self.notice.configure(text=value, foreground="#ff929e" if error else "#a8b8cb")

    def clear(self):
        self.table.selection_remove(*self.table.selection())
        self.edit_id = None
        self.catalogue_ref = None
        for key, value in DEFAULTS.items():
            self.fields[key].set(value)
        self._render_link()
        self._render_stock()

    def _render_link(self):
        ref = self.catalogue_ref
        self.link_label.configure(text=(f"Linked: Forever item {ref.item_id} · checked {ref.checked_on}" if ref else
                                       "Manual entry" if self.catalogue.error else f"Local {self.catalogue.item_count:,}-item catalogue"))

    def _identity_changed(self, *_args):
        if self.setting_fields or self.catalogue_ref is None:
            return
        ref = self.catalogue_ref
        try:
            same_name = material_key(self.fields["name"].get()) == material_key(ref.name)
        except ValueError:
            same_name = False
        if (not same_name
                or self.fields["slot"].get() not in wishlist_slots(ref.equip_slot)):
            self.clear_link()

    def clear_link(self):
        self.catalogue_ref = None
        self._render_link()

    def open_picker(self):
        if self.catalogue.error:
            self.message(self.catalogue.error, True)
            return
        if self.picker is not None:
            self.picker.window.lift()
            return
        self.picker = CataloguePicker(self.host, self.catalogue, self.use_catalogue_item, self._picker_closed, category="Gear")

    def _picker_closed(self):
        self.picker = None

    def use_catalogue_item(self, item):
        item.validate()
        if item.category != "Gear":
            self.message("Choose an equipment item for the gear wishlist.", True)
            return
        self.setting_fields = True
        try:
            self.catalogue_ref = item.reference
            self.fields["name"].set(item.reference.name)
            slots = wishlist_slots(item.reference.equip_slot)
            if self.fields["slot"].get() not in slots:
                self.fields["slot"].set(slots[0])
            if not self.fields["source"].get().strip():
                self.fields["source"].set(item.reference.source_url)
        finally:
            self.setting_fields = False
        self._render_link()
        self.message("Item selected locally. Review the form, then Apply item or Save wishlist. Personal priority, status and notes are retained.")

    def close(self):
        self._save_undo()
        self._save_filters()
        if self.picker is not None:
            self.picker.close()
        if self.stock_binding is not None:
            self.host.root.unbind("<<InventoryStockChanged>>", self.stock_binding)
            self.stock_binding = None

    def _query_changed(self, *_args):
        self._filter_changed(defer=True)

    def _save_undo(self):
        try:
            # A recovered but unsaved goal remains recoverable until a wishlist save confirms it.
            self.undo_store.save(self.undo_records)
            self.undo_error = ""
        except (OSError, ValueError) as exc:
            self.undo_error = str(exc)
            self.message("Removal recovery could not be remembered across restarts.", True)

    def _prune_saved_undo(self):
        for key, record in tuple(self.undo_records.items()):
            if any(item.id == record.item.id for item in self.characters.get(key, GearWishlist()).entries):
                del self.undo_records[key]
                self.last_removed.pop(key, None)
        self._save_undo()
        self._render_undo()

    def _render_undo(self):
        removed = self.last_removed.get(self.host.profile.id)
        state = ["!disabled" if removed else "disabled"]
        self.undo_button.state(state)
        value = (f"Will restore: {display_name(removed.item.name, removed.item.catalogue_ref)} · Slot: {removed.item.slot}"
                 if removed else "No removal to undo for this character.")
        self.undo_detail.configure(text=value, takefocus=bool(removed), cursor="hand2" if removed else "")
        self.undo_detail.state(state)

    def _activate_undo_detail(self, _event=None):
        self.undo_detail.invoke()
        return "break"

    def _filter_changed(self, *_args, defer=False):
        if self.refreshing:
            return
        filters = GearFilters(self.query.get(), self.status_filter.get(), self.ownership_filter.get())
        try:
            filters.validate()
        except ValueError as exc:
            self._set_filter_indicator("Check filters · Previous results shown", active=True, error=True)
            self.message(str(exc), True)
            return
        self.filter_choices[self.active_id] = filters
        self.refresh(preserve_selection=True)
        if self.save_pending is not None:
            self.host.root.after_cancel(self.save_pending)
            self.save_pending = None
        if defer:
            self.save_pending = self.host.root.after(600, self._save_filters)
        else:
            self._save_filters()

    def _save_filters(self):
        if self.save_pending is not None:
            self.host.root.after_cancel(self.save_pending)
            self.save_pending = None
        filters = self.filter_choices.get(self.active_id, self.filter_store.get(self.active_id))
        if not self.filter_store.error and filters == self.filter_store.get(self.active_id):
            return
        try:
            # Save only view preferences; editor/profile/item drafts stay unapplied.
            self.filter_store.save(self.active_id, filters)
            self.filter_error = ""
        except (OSError, ValueError) as exc:
            self.filter_error = str(exc)
            self.message("Wishlist filters apply for this session; could not remember them.", True)

    def reset_filters(self):
        if self.refreshing:
            return
        # Batch the view change so queued selection events cannot replace editor drafts.
        self.refreshing = True
        try:
            self.query.set("")
            self.status_filter.set("All")
            self.ownership_filter.set("All")
        finally:
            self.refreshing = False
        self._filter_changed()

    def refresh(self, preserve_selection=False):
        if self.refreshing:
            return
        self.refreshing = True
        try:
            selected = self.table.selection()
            changed = self.active_id != self.host.profile.id
            self._render_undo()
            if changed:
                self._save_filters()
                if self.picker is not None:
                    self.picker.close()
                self.drafts[self.active_id] = (self.edit_id, {key: var.get() for key, var in self.fields.items()},
                                               self.query.get(), self.status_filter.get(), self.catalogue_ref)
                self.active_id = self.host.profile.id
                saved = self.filter_choices.get(self.active_id, self.filter_store.get(self.active_id))
                self.edit_id, values, query, status, self.catalogue_ref = self.drafts.get(
                    self.active_id, (None, DEFAULTS, saved.query, saved.status, None))
                self.setting_fields = True
                try:
                    for key, value in values.items():
                        self.fields[key].set(value)
                finally:
                    self.setting_fields = False
                self._render_link()
                self.query.set(query)
                self.status_filter.set(status)
                self.ownership_filter.set(saved.ownership)
            try:
                items = self.wishlist.find(self.query.get(), self.status_filter.get())
            except ValueError as exc:
                self._set_filter_indicator("Check filters · Previous results shown", active=True, error=True)
                self.message(str(exc), True)
                return
            self.table.delete(*self.table.get_children())
            self.owned = self._read_stock()
            self._render_ownership_summary()
            ownership = self.ownership_filter.get()
            items = [item for item in items if ownership == "All"
                     or ownership_state(self.owned[item.id]) == ownership]
            for item in items:
                bags, bank = self.owned[item.id]
                self.table.insert("", "end", iid=item.id, values=(display_name(item.name, item.catalogue_ref),
                    bags.label, bank.label, ownership_state((bags, bank)), item.slot, item.priority,
                    item.status, "Yes" if item.bis_candidate else "—", item.source or "—"))
            selection = (selected[0] if selected else None) if preserve_selection and not changed else self.edit_id
            if selection and self.table.exists(selection):
                self.table.selection_set(selection)
            self._render_stock()
            total = len(self.wishlist.entries)
            self._render_filter_indicator(len(items), total)
            wanted = sum(item.status == "Wanted" for item in self.wishlist.entries)
            self.summary.configure(text=(f"{len(items)} of {total} goals · Wanted: {wanted} · Obtained: {total - wanted}"
                                         if total else "No gear goals yet for this character. Add your first item below."))
            if changed:
                self.message("Unsaved wishlist changes in this session." if self.dirty else "Manual wishlist for the selected character.")
        finally:
            self.refreshing = False

    def _activate_filter_indicator(self, _event=None):
        self.filter_indicator.invoke()
        return "break"

    def _set_filter_indicator(self, value, active, error=False):
        self.filter_indicator.configure(text=value, takefocus=active, cursor="hand2" if active else "",
                                        style="Invalid.WishlistFilter.TButton" if error else "WishlistFilter.TButton")
        self.filter_indicator.state(["!disabled" if active else "disabled"])

    def _render_filter_indicator(self, visible, total):
        active = []
        if self.query.get().strip():
            active.append("Search")
        if self.status_filter.get() != "All":
            active.append(f"Goal status: {self.status_filter.get()}")
        if self.ownership_filter.get() != "All":
            active.append(f"Ownership: {self.ownership_filter.get()}")
        self._set_filter_indicator(
            f"Filters active · {total - visible} hidden · " + " · ".join(active) if active else "All items shown",
            active=bool(active))

    def _selected(self, _event=None):
        selection = self.table.selection()
        self._render_stock()
        if not selection or selection[0] == self.edit_id:
            return
        item = next((item for item in self.wishlist.entries if item.id == selection[0]), None)
        if item is not None:
            self._load(item)

    def _load(self, item):
        self.edit_id = item.id
        self.setting_fields = True
        try:
            self.catalogue_ref = item.catalogue_ref
            for key in DEFAULTS:
                self.fields[key].set(getattr(item, key))
        finally:
            self.setting_fields = False
        self._render_link()
        self._render_stock(item.id)

    def _read_stock(self):
        items = self.wishlist.entries
        if not items:
            return {}
        inventory = self.host.inventory_page
        planner = self.host.profession_pages
        error = ""
        if any(store.error for store in (inventory.store, planner.store, self.host.store)):
            error = "Inventory, planning or character records could not be read."
        if not error:
            book = inventory.characters.get(self.active_id, InventoryBook())
            plan = planner.plans.get(self.active_id, ProfessionPlan())
            try:
                names = [(e.name, e.catalogue_ref) for e in book.entries]
                names += [(item.name, item.catalogue_ref) for item in items]
                references = (self.catalogue.stock_references(names)
                              if not self.catalogue.error and self.catalogue.connection is not None else ())
                return recorded_stock(((item.id, item.name, item.catalogue_ref) for item in items), book, plan, references)
            except ValueError:
                error = "Recorded stock could not be validated."
        return {item.id: (RecordedCount(reason=error), RecordedCount(reason=error)) for item in items}

    def _render_ownership_summary(self):
        # Count the full character wishlist, independently of view filters or goal status.
        totals = {state: 0 for state in OWNERSHIP_FILTERS[1:]}
        for counts in self.owned.values():
            totals[ownership_state(counts)] += 1
        for state, button in self.ownership_buttons.items():
            total = len(self.owned) if state == "All" else totals[state]
            button.configure(text=f"{state}: {total}",
                             style="Primary.TButton" if state == self.ownership_filter.get() else "TButton")

    def _render_stock(self, item_id=None):
        selection = self.table.selection()
        counts = self.owned.get(item_id or (selection[0] if selection else None))
        text = "Recorded stock · Manual counts, not a live scan. Wanted/Obtained is your goal status."
        if counts is not None:
            bags, bank = counts
            text = f"Recorded stock · {ownership_state(counts)} · Bags: {bags.label} · Bank: {bank.label} · Manual counts, not a live scan."
            reasons = [f"{location}: {count.reason}" for location, count in (("Bags", bags), ("Bank", bank))
                       if count.quantity is None]
            if reasons:
                text += "\n" + " ".join(reasons)
        self.stock_detail.configure(text=text)

    def _stock_changed(self, _event=None):
        if self.refreshing or self.active_id != self.host.profile.id:
            return
        if self.ownership_filter.get() != "All":
            self.refresh(preserve_selection=True)
            return
        self.owned = self._read_stock()
        self._render_ownership_summary()
        for row in self.table.get_children():
            bags, bank = self.owned[row]
            self.table.set(row, "bags", bags.label)
            self.table.set(row, "bank", bank.label)
            self.table.set(row, "ownership", ownership_state((bags, bank)))
        self._render_stock()

    def apply(self):
        try:
            values = {key: var.get() for key, var in self.fields.items()}
            values["name"] = material_name(values["name"])
            values["source"] = values["source"].strip()
            values["note"] = values["note"].strip()
            item = GearItem(self.edit_id or uuid4().hex, **values, catalogue_ref=self.catalogue_ref)
            candidate = deepcopy(self.wishlist)
            if self.edit_id:
                if not any(entry.id == self.edit_id for entry in candidate.entries):
                    raise ValueError("Selected goal is unavailable. Choose New entry or select a row again.")
                candidate.entries = [item if entry.id == self.edit_id else entry for entry in candidate.entries]
            else:
                candidate.entries.append(item)
            candidate.validate()
        except (ValueError, tk.TclError) as exc:
            self.message(str(exc), True)
            return False
        self.characters[self.host.profile.id] = candidate
        self.dirty = True
        self._load(item)
        self.refresh()
        self.message("Gear goal applied. Save wishlist to keep it. Inventory and crafting are unchanged.")
        return True

    def remove(self):
        selection = self.table.selection()
        if not selection:
            self.message("Select a gear row to remove.", True)
            return False
        removed = next(((index, item) for index, item in enumerate(self.wishlist.entries)
                        if item.id == selection[0]), None)
        if removed is None:
            self.message("Selected goal is unavailable. Select its row again.", True)
            return False
        record = RemovedGoal(removed[0], deepcopy(removed[1]))
        self.last_removed[self.host.profile.id] = record
        self.undo_records[self.host.profile.id] = record
        self._save_undo()
        self.wishlist.entries = [item for item in self.wishlist.entries if item.id != selection[0]]
        self.dirty = True
        self.clear()
        self.refresh()
        self.message("Gear goal removed. Undo last removal can restore it, including after reopening. Save wishlist to keep the removal.")
        return True

    def undo_removal(self):
        removed = self.last_removed.get(self.host.profile.id)
        if removed is None:
            self.message("No removal to undo for this character.")
            return False
        index, item = removed.index, removed.item
        candidate = deepcopy(self.wishlist)
        candidate.entries.insert(min(index, len(candidate.entries)), deepcopy(item))
        try:
            candidate.validate()
        except ValueError as exc:
            self.message(f"Cannot restore the removed goal: {exc} Nothing was replaced; undo remains available.", True)
            return False
        self.characters[self.host.profile.id] = candidate
        del self.last_removed[self.host.profile.id]
        self.dirty = True
        # Do not select/load the recovered row: the current editor can hold an unfinished draft.
        self.refresh(preserve_selection=True)
        hidden = " It is hidden by the current filters." if not self.table.exists(item.id) else ""
        self.message(f"Restored {display_name(item.name, item.catalogue_ref)}. Save wishlist to keep it.{hidden}")
        return True

    def save(self):
        try:
            if self.store.error or self.host.store.error:
                raise ValueError(self.store.error or self.host.store.error)
            if self.edit_id or any(var.get() != DEFAULTS[key] for key, var in self.fields.items()):
                if not self.apply():
                    return False
            if not self.host.ensure_plan_profile():
                raise ValueError("Character profile could not be saved. Check Advanced → Profiles & Rules.")
            self.store.save(self.characters)
        except (OSError, ValueError, tk.TclError) as exc:
            self.message(str(exc), True)
            return False
        self.dirty = False
        self._prune_saved_undo()
        self.message("Wishlist saved locally with a previous-save backup. BiS labels and Obtained status remain your manual choices.")
        return True
