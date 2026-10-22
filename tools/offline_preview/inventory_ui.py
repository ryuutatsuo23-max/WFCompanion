"""Simple local inventory reference; no scanning, imports or live integration."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from inventory import (LOCATIONS, InventoryBook, InventoryEntry, InventoryStore,
                       entered_time, utc_now)
from inventory_undo import InventoryUndoStore, RemovedEntry
from inventory_filters import COUNT_FILTERS, InventoryFilters, InventoryFilterStore
from professions import count, material_key, material_name, stock_time
from ui_layout import ScrollPage
from catalogue import display_name
from item_lookup_ui import ItemLookup


class InventoryUI:
    def __init__(self, host):
        self.host = host
        self.store = InventoryStore(host.store.directory)
        self.characters = self.store.load()
        self.active_id = host.profile.id
        self.filter_store = InventoryFilterStore(host.store.directory)
        self.filter_choices = dict(self.filter_store.profiles)
        self.save_pending = None
        self.filter_error = ""
        self.edit_id = None
        self.drafts = {}
        self.undo_store = InventoryUndoStore(host.store.directory)
        self.undo_records = deepcopy(self.undo_store.records)
        self.undo_error = ""
        self.last_removed = {key: record for key, record in self.undo_records.items()
                             if not any(item.id == record.item.id for item in self.characters.get(key, InventoryBook()).entries)}
        self.refreshing = False
        self.dirty = False
        self.page = ttk.Frame(host.tabs, padding=(0, 12, 0, 0))
        self.scroll = ScrollPage(self.page)
        self.scroll.pack(fill="both", expand=True)
        parent = self.scroll.inner
        ttk.Label(parent, text="Inventory & Bank", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Shared with Gathering & Crafting for this character. Enter each item once per location; 0 means checked empty. Recheck means a craft used this material.",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(4, 10))
        filters = ttk.Frame(parent)
        filters.pack(fill="x")
        saved = self.filter_store.get(self.active_id)
        self.query = tk.StringVar(value=saved.query)
        self.location_filter = tk.StringVar(value=saved.location)
        self.count_filter = tk.StringVar(value=saved.count_status)
        ttk.Label(filters, text="Search").pack(side="left")
        ttk.Entry(filters, textvariable=self.query, width=28).pack(side="left", padx=(8, 18))
        ttk.Label(filters, text="Show").pack(side="left")
        ttk.Combobox(filters, textvariable=self.location_filter, values=("All", *LOCATIONS),
                     state="readonly", width=12).pack(side="left", padx=8)
        self.reset_filters_button = ttk.Button(filters, text="Reset filters", command=self.reset_filters)
        self.reset_filters_button.pack(side="left", padx=(8, 0))
        count_filters = ttk.Frame(parent)
        count_filters.pack(fill="x", pady=(6, 0))
        ttk.Label(count_filters, text="Count status").pack(side="left")
        self.count_combo = ttk.Combobox(count_filters, textvariable=self.count_filter, values=COUNT_FILTERS,
                                        state="readonly", width=12)
        self.count_combo.pack(side="left", padx=8)
        host.style.configure("InventoryFilter.TButton", padding=(4, 2), anchor="w", wraplength=820,
                             foreground="#75ddcb")
        host.style.configure("Invalid.InventoryFilter.TButton", foreground="#ff929e")
        self.filter_indicator = ttk.Button(parent, style="InventoryFilter.TButton", command=self.reset_filters)
        self.filter_indicator.bind("<Return>", self._activate_filter_indicator)
        self.filter_indicator.pack(anchor="w", pady=(5, 0))
        self.location_summary = ttk.Frame(parent)
        self.location_summary.pack(anchor="w", pady=(8, 0))
        ttk.Label(self.location_summary, text="Entries (all records)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.location_buttons = {}
        for column, choice in enumerate(("All", *LOCATIONS), start=1):
            button = ttk.Button(self.location_summary, takefocus=True,
                                command=lambda value=choice: self.location_filter.set(value))
            button.grid(row=0, column=column, padx=(0, 6))
            self.location_buttons[choice] = button
        self.count_summary = ttk.Frame(parent)
        self.count_summary.pack(anchor="w", pady=(5, 0))
        ttk.Label(self.count_summary, text="Count status (all records)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.count_buttons = {}
        for column, choice in enumerate(COUNT_FILTERS, start=1):
            button = ttk.Button(self.count_summary, takefocus=True,
                                command=lambda value=choice: self.count_filter.set(value))
            button.grid(row=0, column=column, padx=(0, 6))
            self.count_buttons[choice] = button
        panel = ttk.Frame(parent)
        panel.pack(fill="x", pady=(10, 8))
        self.table = ttk.Treeview(panel, columns=("name", "location", "quantity", "updated", "note"),
                                  show="headings", height=6, selectmode="browse")
        for key, label, width in (("name", "Item", 220), ("location", "Location", 90), ("quantity", "Quantity", 90),
                                   ("updated", "Last entered (UTC)", 190), ("note", "Note", 180)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=65, stretch=key in ("name", "note"))
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(panel, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        self.summary = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.summary.pack(anchor="w", pady=(0, 12))
        self.name = tk.StringVar()
        self.quantity = tk.StringVar(value="1")
        self.location = tk.StringVar(value="Bags")
        self.note = tk.StringVar()
        self.lookup = ItemLookup(host, parent, self.name)
        fields = ttk.Frame(parent)
        fields.pack(fill="x")
        for col, (label, variable) in enumerate((("Item name", self.name), ("Quantity (blank = unknown)", self.quantity), ("Location", self.location))):
            fields.columnconfigure(col, weight=1)
            ttk.Label(fields, text=label, style="Muted.TLabel", wraplength=190).grid(row=0, column=col, sticky="w", pady=(0, 3))
            field = (ttk.Combobox(fields, textvariable=variable, values=LOCATIONS, state="readonly", width=12)
                     if variable is self.location else ttk.Entry(fields, textvariable=variable, width=18))
            field.grid(row=1, column=col, sticky="ew", padx=(0, 12), pady=(0, 8))
        ttk.Label(parent, text="Note (optional)", style="Muted.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Entry(parent, textvariable=self.note).pack(fill="x", pady=(0, 10))
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        ttk.Button(actions, text="Apply item", command=self.apply, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="New entry", command=self.clear).pack(side="left", padx=8)
        ttk.Button(actions, text="Remove selected", command=self.remove).pack(side="left")
        self.undo_button = ttk.Button(actions, text="Undo last removal", command=self.undo_removal, state="disabled")
        self.undo_button.pack(side="left", padx=(8, 0))
        self.save_button = ttk.Button(actions, text="Save inventory", command=self.save, style="Primary.TButton")
        self.save_button.pack(side="right")
        host.style.configure("InventoryUndo.TButton", padding=(4, 2), anchor="w", wraplength=820,
                             foreground="#75ddcb")
        self.undo_detail = ttk.Button(parent, style="InventoryUndo.TButton", command=self.undo_removal)
        self.undo_detail.bind("<Return>", self._activate_undo_detail)
        self.undo_detail.pack(anchor="w", pady=(5, 0))
        self.notice = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.notice.pack(anchor="w", pady=(10, 8))
        self.query.trace_add("write", self._query_changed)
        self.location_filter.trace_add("write", self._filter_changed)
        self.count_filter.trace_add("write", self._filter_changed)
        self.refresh()
        self.message("Apply item previews changes; Save inventory keeps them locally. Missing entries are not proof of zero stock.")
        if self.store.error or host.store.error:
            self.message(self.store.error or "Saved character profiles are unavailable; inventory saving is disabled.", True)
            self.save_button.state(["disabled"])

    @property
    def book(self):
        return self.characters.setdefault(self.host.profile.id, InventoryBook())

    def message(self, value, error=False):
        if self.store.error and self.store.error not in value:
            value += " Saving disabled: the original inventory file could not be read."
            error = True
        if self.undo_store.error or self.undo_error:
            value += " Undo history is session-only: " + (self.undo_store.error or self.undo_error)
            error = True
        if self.filter_store.error or self.filter_error:
            value += " Inventory filters are session-only: " + (self.filter_store.error or self.filter_error)
            error = True
        self.notice.configure(text=value, foreground="#ff929e" if error else "#a8b8cb")

    def clear(self):
        self.table.selection_remove(*self.table.selection())
        self.edit_id = None
        self.name.set("")
        self.quantity.set("1")
        self.location.set("Bags")
        self.note.set("")
        self.lookup.load(None)

    def close(self):
        self._save_undo()
        self._save_filters()
        self.lookup.close()

    def _save_undo(self):
        try:
            # Keep restored but unsaved entries recoverable until an inventory save confirms them.
            self.undo_store.save(self.undo_records)
            self.undo_error = ""
        except (OSError, ValueError) as exc:
            self.undo_error = str(exc)
            self.message("Inventory removal recovery could not be remembered across restarts.", True)

    def _prune_saved_undo(self):
        for key, record in tuple(self.undo_records.items()):
            if any(item.id == record.item.id for item in self.characters.get(key, InventoryBook()).entries):
                del self.undo_records[key]
                self.last_removed.pop(key, None)
        self._save_undo()
        self._render_undo()

    def _render_undo(self):
        removed = self.last_removed.get(self.host.profile.id)
        state = ["!disabled" if removed else "disabled"]
        self.undo_button.state(state)
        value = (f"Will restore: {display_name(removed.item.name, removed.item.catalogue_ref)} · {removed.item.location}"
                 if removed else "No removal to undo for this character.")
        self.undo_detail.configure(text=value, takefocus=bool(removed), cursor="hand2" if removed else "")
        self.undo_detail.state(state)

    def _activate_undo_detail(self, _event=None):
        self.undo_detail.invoke()
        return "break"

    def _query_changed(self, *_args):
        self._filter_changed(defer=True)

    def _filter_changed(self, *_args, defer=False):
        if self.refreshing:
            return
        filters = InventoryFilters(self.query.get(), self.location_filter.get(), self.count_filter.get())
        try:
            filters.validate()
        except ValueError as exc:
            self._set_filter_indicator("Check filters · Previous results shown", active=True, error=True)
            self.message(f"{exc} Previous results shown; last valid filters will be remembered.", True)
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
            # Only view preferences are persisted; item/profile drafts remain unsaved.
            self.filter_store.save(self.active_id, filters)
            self.filter_error = ""
        except (OSError, ValueError) as exc:
            self.filter_error = str(exc)
            self.message("Inventory filters apply for this session; could not remember them.", True)

    def reset_filters(self):
        if self.refreshing:
            return
        # Change both view preferences together without selecting/loading revealed rows.
        self.refreshing = True
        try:
            self.query.set("")
            self.location_filter.set("All")
            self.count_filter.set("All")
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
                self.lookup.close()
                self.drafts[self.active_id] = (self.edit_id, self.name.get(), self.quantity.get(), self.location.get(),
                                                self.note.get(), self.lookup.reference)
                self.active_id = self.host.profile.id
                saved = self.filter_choices.get(self.active_id, self.filter_store.get(self.active_id))
                draft = self.drafts.get(self.active_id, (None, "", "1", "Bags", "", None))
                self.edit_id = draft[0]
                for variable, value in zip((self.name, self.quantity, self.location, self.note), draft[1:5]):
                    variable.set(value)
                self.lookup.load(draft[5])
                self.query.set(saved.query)
                self.location_filter.set(saved.location)
                self.count_filter.set(saved.count_status)
            try:
                InventoryFilters(self.query.get(), self.location_filter.get(), self.count_filter.get()).validate()
                entries = self.book.find(self.query.get(), self.location_filter.get())
            except ValueError as exc:
                self._set_filter_indicator("Check filters · Previous results shown", active=True, error=True)
                self.message(str(exc), True)
                return
            aliases = self.host.profession_pages.plan.aliases(self.book)
            states = {}
            totals = {status: 0 for status in COUNT_FILTERS[1:]}
            # Summarize the full character list using the same state as each row/filter.
            for entry in self.book.entries:
                cutoff = self.book.cutoff_for(entry, self.host.profession_pages.plan.recheck_after, aliases)
                stale = cutoff and entered_time(entry.updated_at) <= stock_time(cutoff)
                states[entry.id] = "Recheck" if stale else "Unknown" if entry.quantity is None else "Known"
                totals[states[entry.id]] += 1
            for status, button in self.count_buttons.items():
                amount = len(self.book.entries) if status == "All" else totals[status]
                button.configure(text=f"{status}: {amount}",
                                 style="Primary.TButton" if status == self.count_filter.get() else "TButton")
            entries = [entry for entry in entries if self.count_filter.get() == "All"
                       or states[entry.id] == self.count_filter.get()]
            self.table.delete(*self.table.get_children())
            for entry in entries:
                self.table.insert("", "end", iid=entry.id, values=(display_name(entry.name, entry.catalogue_ref), entry.location,
                    entry.quantity if states[entry.id] == "Known" else states[entry.id],
                    entered_time(entry.updated_at).strftime("%Y-%m-%d %H:%M"), entry.note))
            if preserve_selection and not changed:
                self.table.selection_set([row for row in selected if self.table.exists(row)])
            elif self.edit_id and self.table.exists(self.edit_id):
                self.table.selection_set(self.edit_id)
            total = len(self.book.entries)
            self._render_filter_indicator(len(entries), total)
            bags = sum(e.location == "Bags" for e in self.book.entries)
            bank = total - bags
            for choice, amount in (("All", total), ("Bags", bags), ("Bank", bank)):
                self.location_buttons[choice].configure(text=f"{choice}: {amount}",
                    style="Primary.TButton" if choice == self.location_filter.get() else "TButton")
            summary = (f"{len(entries)} of {total} entries · Manual records, not a complete inventory scan."
                       if total else "No manual entries yet for this character. Add an item below; bags and bank have not been scanned.")
            self.summary.configure(text=summary)
            if changed:
                self.message(self.store.error or ("Unsaved inventory changes in this session." if self.dirty else "Manual inventory for the selected character."), bool(self.store.error))
        finally:
            self.refreshing = False

    def _activate_filter_indicator(self, _event=None):
        self.filter_indicator.invoke()
        return "break"

    def _set_filter_indicator(self, value, active, error=False):
        self.filter_indicator.configure(text=value, takefocus=active, cursor="hand2" if active else "",
                                        style="Invalid.InventoryFilter.TButton" if error else "InventoryFilter.TButton")
        self.filter_indicator.state(["!disabled" if active else "disabled"])

    def _render_filter_indicator(self, visible, total):
        active = []
        if self.query.get().strip():
            active.append("Search")
        if self.location_filter.get() != "All":
            active.append(f"Show: {self.location_filter.get()}")
        if self.count_filter.get() != "All":
            active.append(f"Count: {self.count_filter.get()}")
        value = (f"Filters active · {total - visible} hidden · " + " · ".join(active)
                 if active else "All items shown")
        self._set_filter_indicator(value, active=bool(active))

    def _selected(self, _event=None):
        selection = self.table.selection()
        if not selection or selection[0] == self.edit_id:
            return
        entry = next((e for e in self.book.entries if e.id == selection[0]), None)
        if entry is not None:
            self._load(entry)

    def _load(self, entry):
        self.edit_id = entry.id
        self.name.set(entry.name)
        self.quantity.set("" if entry.quantity is None else str(entry.quantity))
        self.location.set(entry.location)
        self.note.set(entry.note)
        self.lookup.load(entry.catalogue_ref)

    def apply(self, confirm_count=True):
        try:
            existing = next((e for e in self.book.entries if e.id == self.edit_id), None)
            entry = InventoryEntry(self.edit_id or uuid4().hex, material_name(self.name.get()),
                None if not self.quantity.get().strip() else count(int(self.quantity.get()), "Item quantity"),
                self.location.get(), utc_now(), self.note.get().strip(), catalogue_ref=self.lookup.reference)
            if (not confirm_count and existing and material_key(entry.name) == material_key(existing.name)
                    and entry.location == existing.location and entry.quantity == existing.quantity):
                # Saving a note edit is not a fresh observation of the count.
                entry.updated_at = existing.updated_at
            candidate = deepcopy(self.book)
            if self.edit_id:
                if not any(e.id == self.edit_id for e in candidate.entries):
                    raise ValueError("Selected entry is unavailable. Choose New entry or select a row again.")
                candidate.entries = [entry if e.id == self.edit_id else e for e in candidate.entries]
            else:
                candidate.entries.append(entry)
            candidate.validate()
        except ValueError as exc:
            self.message(str(exc), True)
            return False
        self.characters[self.host.profile.id] = candidate
        self.dirty = True
        self._load(entry)
        self.refresh()
        self.host.profession_pages.refresh_stock()
        self.message("Item applied; Gathering & Crafting updated. Save inventory to keep this count.")
        return True

    def remove(self):
        selection = self.table.selection()
        if not selection:
            self.message("Select an item row to remove.", True)
            return False
        removed = next(((index, item) for index, item in enumerate(self.book.entries)
                        if item.id == selection[0]), None)
        if removed is None:
            self.message("Selected entry is unavailable. Select its row again.", True)
            return False
        record = RemovedEntry(removed[0], deepcopy(removed[1]))
        self.last_removed[self.host.profile.id] = record
        self.undo_records[self.host.profile.id] = record
        self._save_undo()
        self.book.entries = [e for e in self.book.entries if e.id != selection[0]]
        self.dirty = True
        self.clear()
        self.refresh()
        self.host.profession_pages.refresh_stock()
        self.message("Entry removed. Undo last removal can restore it, including after reopening. Save inventory to keep the removal.")
        return True

    def undo_removal(self):
        removed = self.last_removed.get(self.host.profile.id)
        if removed is None:
            self.message("No removal to undo for this character.")
            return False
        item = removed.item
        candidate = deepcopy(self.book)
        candidate.entries.insert(min(removed.index, len(candidate.entries)), deepcopy(item))
        try:
            candidate.validate()
        except ValueError as exc:
            self.message(f"Cannot restore the removed entry: {exc} Nothing was replaced; undo remains available.", True)
            return False
        self.characters[self.host.profile.id] = candidate
        del self.last_removed[self.host.profile.id]
        self.dirty = True
        # Preserve drafts and original timestamps; undo is not a fresh stock observation.
        self.refresh(preserve_selection=True)
        self.host.profession_pages.refresh_stock()
        hidden = " It is hidden by the current filters." if not self.table.exists(item.id) else ""
        self.message(f"Restored {display_name(item.name, item.catalogue_ref)} in {item.location}. Save inventory to keep it.{hidden}")
        return True

    def save(self):
        try:
            if self.store.error or self.host.store.error:
                raise ValueError(self.store.error or self.host.store.error)
            existing = next((e for e in self.book.entries if e.id == self.edit_id), None)
            unchanged = existing and (self.name.get(), self.quantity.get(), self.location.get(), self.note.get(), self.lookup.reference) == (
                existing.name, "" if existing.quantity is None else str(existing.quantity), existing.location, existing.note, existing.catalogue_ref)
            # Saving an unchanged form must not falsely confirm stock that was
            # invalidated by a craft. Explicit Apply item confirms a recheck.
            if not unchanged and (self.name.get().strip() or self.note.get().strip()
                                  or self.quantity.get().strip() != "1" or self.location.get() != "Bags"):
                if not self.apply(confirm_count=False):
                    return False
            if not self.host.ensure_plan_profile():
                raise ValueError("Character profile could not be saved. Check Advanced → Profiles & Rules.")
            self.store.save(self.characters)
        except (OSError, ValueError) as exc:
            self.message(str(exc), True)
            return False
        self.dirty = False
        self._prune_saved_undo()
        self.message("Inventory saved locally with a previous-save backup. Counts remain manual and may become outdated.")
        return True
