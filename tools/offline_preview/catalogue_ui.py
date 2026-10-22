"""Local catalogue picker; selecting a result only fills the gear editor."""

import sqlite3
import tkinter as tk
from tkinter import ttk

from ui_layout import ScrollPage
from search_filters import SearchFilters
from inventory import InventoryBook
from item_stock import OWNERSHIP_FILTERS, catalogue_stock, ownership_selection, ownership_state, unknown_stock
from professions import ProfessionPlan


class CataloguePicker:
    def __init__(self, host, catalogue, choose, on_close, category="All"):
        self.host = host
        self.profile_id = getattr(host.profile, "id", None)
        self.filter_store = host.item_search_filters
        self.last_valid_filters = self.filter_store.get(self.profile_id, category)
        self.last_persisted_filters = self.last_valid_filters
        saved = self.last_valid_filters
        self.character_level = getattr(host.profile, "level", None)
        self.save_pending = None
        self.catalogue = catalogue
        self.choose = choose
        self.on_close = on_close
        self.category = category
        self.pending = None
        self.results = {}
        self.owned = {}
        self.ownership_index = None
        self.ownership_error = ""
        self.updating_filters = False
        self.window = tk.Toplevel(host.root)
        self.window.title("Local item search · Forever catalogue")
        self.window.transient(host.root)
        self.window.geometry("880x600")
        self.window.minsize(700, 520)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.scroll = ScrollPage(self.window)
        self.scroll.pack(fill="both", expand=True)
        parent = ttk.Frame(self.scroll.inner, padding=14)
        parent.pack(fill="both", expand=True)
        ttk.Label(parent, text="Find an item", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.context = ttk.Label(parent, text=f"For {host.profile.name} · Name or exact ID · Everything searches locally",
                                 style="Muted.TLabel", wraplength=620)
        self.context.pack(anchor="w", pady=(4, 8))
        self.query = tk.StringVar()
        entry = ttk.Entry(parent, textvariable=self.query)
        entry.pack(fill="x")
        self.category_choice = tk.StringVar(value=saved.category)
        self.slot_choice = tk.StringVar(value=saved.equip_slot or "Any slot")
        self.type_choice = tk.StringVar(value=saved.item_type or "Any type")
        self.ownership_choice = tk.StringVar(value=saved.ownership)
        self.min_level = tk.StringVar(value="" if saved.min_level is None else str(saved.min_level))
        self.max_level = tk.StringVar(value="" if saved.max_level is None else str(saved.max_level))
        self.include_unknown_levels = tk.BooleanVar(value=saved.include_unknown_levels)
        self.use_character_level = tk.BooleanVar(value=saved.use_character_level)
        self.character_limit_active = False
        self.manual_max_level = ""
        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(8, 6))
        columns = [("Slot", self.slot_choice), ("Type", self.type_choice), ("Ownership", self.ownership_choice)]
        if category == "All":
            columns.insert(0, ("Show", self.category_choice))
        for column, (label, variable) in enumerate(columns):
            filters.columnconfigure(column, weight=1, uniform="search-filters")
            group = ttk.Frame(filters)
            group.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column < len(columns) - 1 else 0)
            ttk.Label(group, text=label).pack(anchor="w")
            box = ttk.Combobox(group, textvariable=variable, state="readonly", width=1)
            box.pack(fill="x", pady=(3, 0))
            if label == "Show":
                box.configure(values=("All", "Material", "Gear", "Other"))
            elif label == "Slot":
                self.slot_box = box
            elif label == "Type":
                self.type_box = box
            else:
                self.ownership_box = box
                box.configure(values=OWNERSHIP_FILTERS)
        levels = ttk.Frame(parent)
        levels.pack(fill="x")
        levels.columnconfigure(4, weight=1)
        ttk.Label(levels, text="Required level").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.min_entry = ttk.Entry(levels, textvariable=self.min_level, width=6)
        self.min_entry.grid(row=0, column=1, sticky="w")
        ttk.Label(levels, text="to").grid(row=0, column=2, padx=6)
        self.max_entry = ttk.Entry(levels, textvariable=self.max_level, width=6)
        self.max_entry.grid(row=0, column=3, sticky="w")
        self.reset_button = ttk.Button(levels, text="Reset filters", command=self.reset_filters)
        self.reset_button.grid(row=0, column=5, sticky="e", padx=(8, 0))
        ttk.Checkbutton(levels, text="Include unknown levels", variable=self.include_unknown_levels).grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.character_level_box = ttk.Checkbutton(levels, variable=self.use_character_level)
        self.character_level_box.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.filter_notice = ttk.Label(parent, style="Muted.TLabel", wraplength=620)
        if self.filter_store.error:
            self._filter_error(self.filter_store.error)
        panel = ttk.Frame(parent)
        panel.pack(fill="x", pady=(10, 8))
        panel.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(panel, columns=("name", "bags", "bank", "slot", "type", "level", "id"),
                                  show="headings", height=6, selectmode="browse")
        for key, label, width in (("name", "Item", 200), ("bags", "Bags", 90), ("bank", "Bank", 90),
                                   ("slot", "Equip label", 100), ("type", "Type", 90),
                                   ("level", "Req. level", 85), ("id", "Item ID", 75)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=100 if key == "name" else 80 if key in ("bags", "bank") else 65,
                              stretch=key == "name")
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(panel, command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        self.stock_summary = ttk.Label(parent, style="Muted.TLabel", wraplength=620, justify="left")
        self.stock_summary.pack(anchor="w", pady=(0, 8))
        self.status = ttk.Label(parent, style="Muted.TLabel", wraplength=620)
        self.status.pack(anchor="w", pady=(0, 8))
        self.details = ttk.Label(parent, style="Muted.TLabel", wraplength=620, justify="left")
        self.details.pack(anchor="w")
        footer = ttk.Frame(self.window, padding=(14, 10))
        footer.pack(fill="x", side="bottom")
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self.use_button = ttk.Button(footer, text="Use selected item", command=self.use_selected, style="Primary.TButton")
        self.use_button.pack(side="right", padx=8)
        self._sync_choices()
        for variable in (self.query, self.slot_choice, self.type_choice, self.ownership_choice,
                         self.min_level, self.max_level, self.include_unknown_levels):
            variable.trace_add("write", self._query_changed)
        if category == "All":
            self.category_choice.trace_add("write", self._category_changed)
        self.use_character_level.trace_add("write", self._character_level_changed)
        self.profile_binding = host.root.bind("<<ProfileMetadataChanged>>", self._profile_changed, add="+")
        self.stock_binding = host.root.bind("<<InventoryStockChanged>>", self._stock_changed, add="+")
        self._character_level_changed()
        self.refresh()
        entry.focus_set()

    def _active_category(self):
        return self.category_choice.get() if self.category == "All" else self.category

    def _character_level_changed(self, *_args):
        if self.updating_filters:
            return
        level = self.character_level
        self.character_level_box.configure(text=f"Use character level ({level if level is not None else 'Unknown; waiting'})")
        self.character_level_box.state(["disabled"] if level is None else ["!disabled"])
        active = self.use_character_level.get()
        if active:
            if not self.character_limit_active:
                self.manual_max_level = self.max_level.get()
            self.max_entry.state(["readonly"])
            self.max_level.set(str(level) if level is not None else "Unknown")
        elif self.character_limit_active:
            self.max_entry.state(["!readonly"])
            self.max_level.set(self.manual_max_level)
        self.character_limit_active = active
        self._query_changed()

    def _profile_changed(self, _event=None):
        if getattr(self.host.profile, "id", None) != self.profile_id:
            self.close()
            return
        self.context.configure(text=f"For {self.host.profile.name} · Name or exact ID · Everything searches locally")
        self.character_level = getattr(self.host.profile, "level", None)
        self._character_level_changed()

    def _sync_choices(self):
        self.updating_filters = True
        try:
            options = self.catalogue.filter_options(self._active_category())
            slots, types = ("Any slot", *options["slots"]), ("Any type", *options["types"])
            self.slot_box.configure(values=slots, state="readonly" if options["slots"] else "disabled")
            self.type_box.configure(values=types)
            if self.slot_choice.get() not in slots:
                self.slot_choice.set("Any slot")
            if self.type_choice.get() not in types:
                self.type_choice.set("Any type")
        except (ValueError, sqlite3.Error) as exc:
            self.status.configure(text=str(exc))
        finally:
            self.updating_filters = False

    def _category_changed(self, *_args):
        if not self.updating_filters:
            self._sync_choices()
            self._query_changed()

    def reset_filters(self):
        self.updating_filters = True
        try:
            self.category_choice.set(self.category)
            self.slot_choice.set("Any slot")
            self.type_choice.set("Any type")
            self.ownership_choice.set("All")
            self.min_level.set("")
            self.max_level.set("")
            self.include_unknown_levels.set(True)
            self.use_character_level.set(False)
            self.character_limit_active = False
            self.manual_max_level = ""
            self.max_entry.state(["!readonly"])
        finally:
            self.updating_filters = False
        self._sync_choices()
        self._query_changed()

    def _query_changed(self, *_args):
        if self.updating_filters:
            return
        if self.save_pending is not None:
            self.window.after_cancel(self.save_pending)
            self.save_pending = None
        if self.pending is not None:
            self.window.after_cancel(self.pending)
        self.results.clear()
        self.owned.clear()
        self.table.delete(*self.table.get_children())
        self.use_button.state(["disabled"])
        self.details.configure(text="")
        self.stock_summary.configure(text="Recorded stock · Manual counts, not a live scan.")
        self.pending = self.window.after(120, self.refresh)

    @staticmethod
    def _level(value, label):
        value = value.strip()
        if not value:
            return None
        if not value.isascii() or not value.isdecimal() or len(value) > 4 or int(value) > 1000:
            raise ValueError(f"{label} required level must be a whole number from 0 to 1000, or blank.")
        return int(value)

    def refresh(self, preserve_selection=False):
        previous_selection = self.table.selection() if preserve_selection else ()
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.results.clear()
        self.owned.clear()
        self.table.delete(*self.table.get_children())
        self.use_button.state(["disabled"])
        self.details.configure(text="")
        self.stock_summary.configure(text="Recorded stock · Manual counts, not a live scan.")
        try:
            filters = self._current_filters()
            item_ids, exclude_ids = self._ownership_selection(filters.ownership)
            items = self.catalogue.search(self.query.get(), category=self._active_category(),
                equip_slot=None if self.slot_choice.get() == "Any slot" else self.slot_choice.get(),
                item_type=None if self.type_choice.get() == "Any type" else self.type_choice.get(),
                min_level=self._level(self.min_level.get(), "Minimum"), max_level=self._effective_maximum(),
                include_unknown_levels=self.include_unknown_levels.get(), item_ids=item_ids, exclude_item_ids=exclude_ids)
        except (ValueError, sqlite3.Error) as exc:
            self.status.configure(text=str(exc))
            return
        self.last_valid_filters = filters
        if self.save_pending is not None:
            self.window.after_cancel(self.save_pending)
        self.save_pending = self.window.after(600, self._save_filters)
        self.owned = self._read_stock(items)
        for item in items:
            ref = item.reference
            key = str(ref.item_id)
            self.results[key] = item
            equip_label = ref.equip_slot or ("Unknown" if item.category == "Gear" else "—")
            bags, bank = self.owned[ref.item_id]
            self.table.insert("", "end", iid=key, values=(ref.name, bags.label, bank.label, equip_label, item.item_type,
                "Unknown" if item.required_level is None else item.required_level, ref.item_id))
        status = (f"{len(items)} results (up to 50) · {self.catalogue.item_count} local records · Source-checked, not verified in your game."
                  if items else "No matches with these local filters. Manual entries still work.")
        if self.ownership_error:
            status += "\nStock: Unknown. " + self.ownership_error
        self.status.configure(text=status)
        if previous_selection and previous_selection[0] in self.results:
            self.table.selection_set(previous_selection[0])
            self._selected()
        elif items and not preserve_selection:
            self.table.selection_set(str(items[0].reference.item_id))
            self._selected()

    def _selected(self, _event=None):
        selection = self.table.selection()
        item = self.results.get(selection[0]) if selection else None
        self.use_button.state(["!disabled"] if item else ["disabled"])
        if item is None:
            self.details.configure(text="")
            self.stock_summary.configure(text="Recorded stock · Manual counts, not a live scan.")
            return
        ref = item.reference
        bags, bank = self.owned[ref.item_id]
        summary = f"Recorded stock · {ownership_state((bags, bank))} · Bags: {bags.label} · Bank: {bank.label} · Manual counts, not a live scan."
        reasons = [f"{location}: {count.reason}" for location, count in (("Bags", bags), ("Bank", bank))
                   if count.quantity is None]
        self.stock_summary.configure(text=summary + ("\n" + " ".join(reasons) if reasons else ""))
        sources = "\n".join(e["url"] for e in item.evidence)
        detail = (f"Forever / {ref.locale} · ID {ref.item_id} · Item level: {item.item_level if item.item_level is not None else 'Unknown'}\n"
                  f"Sources checked {ref.checked_on} · Current client build unverified. Stats are not included.\n"
                  f"{self.catalogue.coverage_note}\n{sources}")
        if item.variant_note:
            detail += "\n" + item.variant_note
        if item.category == "Gear" and ref.equip_slot is None:
            detail += "\nEquip slot: Unknown. The wishlist uses Unspecified."
        if item.category == "Material":
            detail += "\nName/ID verified in a source listing; recipe amounts, gathering routes and availability are not inferred."
        if item.required_level is None:
            detail += "\nRequired level: Unknown. This does not confirm the item is usable at your level."
        if ref.equip_slot in ("Finger", "One-Hand", "Two-Hand"):
            detail += "\nThe wishlist suggests a planning slot; equip eligibility is not checked."
        self.details.configure(text=detail)

    def use_selected(self):
        selection = self.table.selection()
        item = self.results.get(selection[0]) if selection else None
        if item is None:
            return False
        self.choose(item)
        self.close()
        return True

    def _effective_maximum(self):
        if self.use_character_level.get():
            return self.character_level
        return self._level(self.max_level.get(), "Maximum")

    def _stock_context(self):
        inventory = getattr(self.host, "inventory_page", None)
        planner = getattr(self.host, "profession_pages", None)
        if inventory is None:
            return None, None, "Recorded inventory is unavailable."
        for store in (inventory.store, getattr(planner, "store", None), getattr(self.host, "store", None)):
            if store is not None and store.error:
                return None, None, "Inventory, planning or character records could not be read."
        book = inventory.characters.get(self.profile_id, InventoryBook())
        plan = planner.plans.get(self.profile_id, ProfessionPlan()) if planner else ProfessionPlan()
        return book, plan, ""

    def _ownership_selection(self, choice):
        self.ownership_index = None
        self.ownership_error = ""
        if choice == "All":
            return None, False
        book, plan, error = self._stock_context()
        stock = {}
        if not error:
            try:
                references = self.catalogue.stock_references((e.name, e.catalogue_ref) for e in book.entries)
                stock = catalogue_stock(references, book, plan)
            except ValueError:
                error = "Recorded stock could not be validated."
        self.ownership_index = stock
        self.ownership_error = error
        return ownership_selection(stock, choice)

    def _read_stock(self, items):
        references = [item.reference for item in items]
        if self.ownership_index is not None:
            missing = unknown_stock(references, self.ownership_error or "No record for this location.")
            return {ref.item_id: self.ownership_index.get(ref.item_id, missing[ref.item_id]) for ref in references}
        book, plan, error = self._stock_context()
        if error:
            return unknown_stock(references, error)
        try:
            related = self.catalogue.stock_references((e.name, e.catalogue_ref) for e in book.entries)
            identities = {ref.item_id: ref for ref in (*related, *references)}
            return catalogue_stock(identities.values(), book, plan)
        except ValueError:
            return unknown_stock(references, "Recorded stock could not be validated.")

    def _stock_changed(self, _event=None):
        if getattr(self.host.profile, "id", None) != self.profile_id:
            self.close()
            return
        if self.ownership_choice.get() != "All":
            self.refresh(preserve_selection=True)
            return
        self.owned = self._read_stock(list(self.results.values()))
        for key, item in self.results.items():
            bags, bank = self.owned[item.reference.item_id]
            self.table.set(key, "bags", bags.label)
            self.table.set(key, "bank", bank.label)
        self._selected()

    def _current_filters(self):
        minimum, maximum = self._level(self.min_level.get(), "Minimum"), self._effective_maximum()
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum required level must not exceed maximum required level.")
        result = SearchFilters(self._active_category(),
            None if self.slot_choice.get() == "Any slot" else self.slot_choice.get(),
            None if self.type_choice.get() == "Any type" else self.type_choice.get(), minimum,
            self._level(self.manual_max_level if self.use_character_level.get() else self.max_level.get(), "Maximum"),
            self.include_unknown_levels.get(), self.use_character_level.get(), self.ownership_choice.get())
        result.validate(self.category)
        return result

    def _filter_error(self, error):
        self.filter_notice.configure(text=f"Filters not remembered: {error}")
        self.filter_notice.pack(anchor="w", pady=(6, 0))

    def _save_filters(self):
        self.save_pending = None
        if self.last_valid_filters == self.last_persisted_filters:
            return
        try:
            self.filter_store.save(self.profile_id, self.category, self.last_valid_filters)
            self.last_persisted_filters = self.last_valid_filters
        except (OSError, ValueError) as exc:
            self._filter_error(exc)
            if hasattr(self.host, "settings_notice"):
                self.host.settings_notice.configure(text=f"Item search filters were not saved: {exc}")

    def close(self):
        if self.save_pending is not None:
            self.window.after_cancel(self.save_pending)
            self.save_pending = None
        try:
            self.last_valid_filters = self._current_filters()
        except ValueError:
            pass  # An unfinished/invalid edit never replaces the last valid filters.
        self._save_filters()
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.host.root.unbind("<<ProfileMetadataChanged>>", self.profile_binding)
        self.host.root.unbind("<<InventoryStockChanged>>", self.stock_binding)
        self.window.destroy()
        self.on_close()
