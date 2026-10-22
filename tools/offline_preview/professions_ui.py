"""Small manual gathering and crafting pages for the offline preview."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from inventory import InventoryBook
from professions import (SOURCES, CraftGoal, Material, PlanStore, ProfessionPlan,
                         count, material_key, material_name, parse_ingredients)
from ui_layout import ScrollPage
from catalogue import display_name, item_key, resolved_key
from catalogue_ui import CataloguePicker
from item_lookup_ui import ItemLookup
from recipes_ui import RecipeBookUI


class ProfessionUI:
    def __init__(self, host):
        self.host = host
        self.store = PlanStore(host.store.directory)
        self.plans = self.store.load()
        self.active_id = host.profile.id
        self.material_original = None
        self.material_selected_key = None
        self.ingredient_refs = {}
        self.ingredient_picker = None
        self.messages = []
        self.gathering = ttk.Frame(host.tabs, padding=(0, 12, 0, 0))
        self.crafting = ttk.Frame(host.tabs, padding=(0, 12, 0, 0))
        self.craft_tabs = ttk.Notebook(self.crafting)
        self.craft_tabs.pack(fill="both", expand=True)
        self.queue_page = ttk.Frame(self.craft_tabs)
        self.craft_tabs.add(self.queue_page, text="Queue")
        self.gather_scroll = ScrollPage(self.gathering)
        self.craft_scroll = ScrollPage(self.queue_page)
        self.gather_scroll.pack(fill="both", expand=True)
        self.craft_scroll.pack(fill="both", expand=True)
        self._gathering(self.gather_scroll.inner)
        self._crafting(self.craft_scroll.inner)
        self.book_ui = RecipeBookUI(self)
        self.refresh()
        if self.store.error or host.store.error:
            self.message(self.store.error or "Saved character profiles are unavailable; plan saving is disabled.", True)
            for button in self.save_buttons:
                button.state(["disabled"])

    @property
    def plan(self):
        return self.plans.setdefault(self.host.profile.id, ProfessionPlan())

    def requirements(self):
        inventory_ui = getattr(self.host, "inventory_page", None)
        book = inventory_ui.book if inventory_ui and not inventory_ui.store.error and not self.store.error else InventoryBook()
        return self.plan.requirements(book)

    def _table(self, parent, columns):
        panel = ttk.Frame(parent)
        panel.pack(fill="x", pady=(8, 10))
        panel.columnconfigure(0, weight=1)
        table = ttk.Treeview(panel, columns=tuple(c[0] for c in columns), show="headings", height=5, selectmode="browse")
        for key, label, width in columns:
            table.heading(key, text=label)
            table.column(key, width=width, minwidth=65, stretch=key == "name")
        table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(panel, command=table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(xscrollcommand=horizontal.set)
        return table

    def _field(self, parent, label, variable, column, values=None):
        parent.columnconfigure(column, weight=1)
        ttk.Label(parent, text=label, style="Muted.TLabel", wraplength=190).grid(row=0, column=column, sticky="w", pady=(0, 3))
        widget = (ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=12)
                  if values else ttk.Entry(parent, textvariable=variable, width=16))
        widget.grid(row=1, column=column, sticky="ew", padx=(0, 12), pady=(0, 8))
        return widget

    def _save_footer(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(10, 7))
        button = ttk.Button(row, text="Save plan", style="Primary.TButton", command=self.save)
        button.pack(side="left")
        self.save_buttons = getattr(self, "save_buttons", []) + [button]
        label = ttk.Label(parent, text="Manual planning only. Save plan keeps applied entries locally.", style="Muted.TLabel", wraplength=820)
        label.pack(anchor="w", pady=(0, 8))
        self.messages.append(label)

    def _gathering(self, parent):
        ttk.Label(parent, text="Materials to gather or buy", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Stock comes from Inventory & Bank for this character. Missing location counts stay unknown; enter 0 if checked empty.",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(4, 0))
        self.material_table = self._table(parent, (("name", "Material", 220), ("needed", "Needed", 75),
            ("bags", "Bags", 75), ("bank", "Bank", 75), ("owned", "Total", 80),
            ("remaining", "Still needed", 100), ("source", "Source", 85)))
        self.material_table.bind("<<TreeviewSelect>>", self._material_selected)
        self.material_label = tk.StringVar()
        self.extra_target = tk.StringVar(value="0")
        self.owned = tk.StringVar()
        self.source = tk.StringVar(value="Either")
        self.material_lookup = ItemLookup(self.host, parent, self.material_label, category="Material", label="Find material…")
        fields = ttk.Frame(parent)
        fields.pack(fill="x")
        self._field(fields, "Material name", self.material_label, 0)
        self._field(fields, "Extra gathering goal", self.extra_target, 1)
        self._field(fields, "Total from inventory", self.owned, 2).configure(state="readonly")
        self._field(fields, "Source", self.source, 3, SOURCES)
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        ttk.Button(actions, text="Apply material", command=self.apply_material, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="New entry", command=self.clear_material).pack(side="left", padx=8)
        ttk.Button(actions, text="Clear manual entry", command=self.remove_material).pack(side="left")
        ttk.Button(actions, text="Edit inventory", command=self.open_inventory).pack(side="right")
        self.legacy_count = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.legacy_count.pack(anchor="w", pady=(8, 0))
        self._save_footer(parent)

    def _crafting(self, parent):
        ttk.Label(parent, text="Crafting queue", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Add a saved recipe from Recipe book, or enter a one-off craft below. Amounts are numbers of crafts.",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(4, 0))
        self.goal_table = self._table(parent, (("name", "Item", 340), ("profession", "Profession", 150),
            ("goal", "Goal (crafts)", 130), ("done", "Recorded", 100), ("remaining", "Remaining", 125)))
        self.goal_table.bind("<<TreeviewSelect>>", self._goal_selected)
        queue_actions = ttk.Frame(parent)
        queue_actions.pack(fill="x", pady=(0, 8))
        ttk.Button(queue_actions, text="Move up", command=lambda: self.move_goal(-1)).pack(side="left")
        ttk.Button(queue_actions, text="Move down", command=lambda: self.move_goal(1)).pack(side="left", padx=8)
        ttk.Button(queue_actions, text="Copy to recipe book", command=lambda: self.book_ui.copy_goal()).pack(side="left")
        self.stock_summary = ttk.Label(parent, style="Muted.TLabel", wraplength=820)
        self.stock_summary.pack(anchor="w", pady=(0, 10))
        self.goal_name = tk.StringVar()
        self.goal_quantity = tk.StringVar(value="1")
        self.profession = tk.StringVar()
        self.output_per_craft = tk.StringVar()
        self.output_lookup = ItemLookup(self.host, parent, self.goal_name, label="Find crafted item…")
        fields = ttk.Frame(parent)
        fields.pack(fill="x")
        self._field(fields, "Crafted item", self.goal_name, 0)
        self._field(fields, "Number of crafts", self.goal_quantity, 1)
        self._field(fields, "Profession (optional)", self.profession, 2)
        self._field(fields, "Output per craft (blank = Unknown)", self.output_per_craft, 3)
        ttk.Label(parent, text="Ingredients per craft · One per line: material name = quantity",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(2, 4))
        self.ingredients = tk.Text(parent, height=4, width=20, wrap="word", font=("Segoe UI", 10),
                                   background="#111c2a", foreground="#edf3fa", insertbackground="#edf3fa",
                                   highlightthickness=1, highlightbackground="#3e536c", undo=True)
        self.ingredients.pack(fill="x", pady=(0, 8))
        ingredient_actions = ttk.Frame(parent)
        ingredient_actions.pack(fill="x", pady=(0, 8))
        self.find_ingredient_button = ttk.Button(ingredient_actions, text="Find ingredient…", command=self.open_ingredient_picker)
        self.find_ingredient_button.pack(side="left")
        ttk.Label(ingredient_actions, text="Per craft", style="Muted.TLabel").pack(side="left", padx=(14, 6))
        self.ingredient_amount = tk.StringVar(value="1")
        ttk.Entry(ingredient_actions, textvariable=self.ingredient_amount, width=8).pack(side="left")
        if self.host.catalogue.error:
            self.find_ingredient_button.state(["disabled"])
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        ttk.Button(actions, text="Apply goal", command=self.apply_goal, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="New goal", command=self.clear_goal).pack(side="left", padx=8)
        ttk.Button(actions, text="Remove goal", command=self.remove_goal).pack(side="left")
        ttk.Button(actions, text="Record 1 crafted", command=self.record_one).pack(side="right")
        self._save_footer(parent)

    def message(self, value, error=False):
        for label in self.messages:
            label.configure(text=value, foreground="#ff929e" if error else "#a8b8cb")

    def open_ingredient_picker(self):
        if self.host.catalogue.error:
            self.message(self.host.catalogue.error, True)
            return
        if self.ingredient_picker is not None:
            self.ingredient_picker.window.lift()
        else:
            self.ingredient_picker = CataloguePicker(self.host, self.host.catalogue, self.add_ingredient,
                                                     self._ingredient_picker_closed, category="Material")

    def _ingredient_picker_closed(self):
        self.ingredient_picker = None

    def add_ingredient(self, item):
        try:
            amount = count(int(self.ingredient_amount.get()), "Quantity per craft", 1)
            item.validate()
            ref = item.reference
            current = self.ingredients.get("1.0", "end-1c")
            if any(f"[#{ref.item_id}]" in line for line in current.splitlines()):
                raise ValueError("This ingredient is already listed. Edit its quantity in the recipe.")
        except ValueError as exc:
            self.message(str(exc), True)
            return False
        self.ingredient_refs[ref.item_id] = ref
        self.ingredients.insert("end", ("\n" if current and not current.endswith("\n") else "") + f"{ref.name} [#{ref.item_id}] = {amount}")
        self.message("Ingredient added to the draft. Recipe amounts remain your manual choices; Apply goal or Save plan when ready.")
        return True

    def close(self):
        self.material_lookup.close()
        self.output_lookup.close()
        if self.ingredient_picker is not None:
            self.ingredient_picker.close()
        if hasattr(self, "book_ui"):
            self.book_ui.close()

    def _manual_material(self, required):
        aliases = self.plan.aliases(self.host.inventory_page.book if hasattr(self.host, "inventory_page") else None)
        return next((m for m in self.plan.materials if resolved_key(m.name, m.catalogue_ref, aliases) == required.key), None)

    def refresh(self, material=None, goal=None):
        changed = self.active_id != self.host.profile.id
        self.active_id = self.host.profile.id
        self.refresh_stock()
        ids = {g.id for g in self.plan.goals}
        for key in self.goal_table.get_children():
            if key not in ids:
                self.goal_table.delete(key)
        for index, item in enumerate(self.plan.goals):
            values = (item.name, item.profession or "—", item.quantity, item.completed, item.quantity - item.completed)
            if self.goal_table.exists(item.id):
                self.goal_table.item(item.id, values=values)
                self.goal_table.move(item.id, "", index)
            else:
                self.goal_table.insert("", "end", iid=item.id, values=values)
        if changed:
            self.close()
            self.clear_material()
            self.clear_goal()
            self.message(self.store.error or "Manual plan for this character. Apply entries, then Save plan.", bool(self.store.error))
        self.book_ui.refresh()
        if material and self.material_table.exists(material):
            self.material_table.selection_set(material)
            self._material_selected()
        if goal and self.goal_table.exists(goal):
            self.goal_table.selection_set(goal)
            self._goal_selected()

    def refresh_stock(self):
        """Update derived stock without rebuilding editors or their selections."""
        rows = self.requirements()
        keys = {item.key for item in rows}
        for key in self.material_table.get_children():
            if key not in keys:
                self.material_table.delete(key)
        for item in rows:
            key = item.key
            values = (display_name(item.name, item.catalogue_ref), item.needed,
                      "Unknown" if item.bags is None else item.bags,
                      "Unknown" if item.bank is None else item.bank,
                      "Unknown" if item.owned is None else item.owned,
                      "Check stock" if item.remaining is None else item.remaining, item.source)
            if self.material_table.exists(key):
                self.material_table.item(key, values=values)
            else:
                self.material_table.insert("", "end", iid=key, values=values)
        selected = next((r for r in rows if r.key == self.material_selected_key), None)
        self.owned.set("Unknown" if selected is None or selected.owned is None else str(selected.owned))
        self._legacy_notice()
        pending = [r for r in rows if r.needed > 0]
        unknown = sum(r.remaining is None for r in pending)
        missing = sum(r.remaining is not None and r.remaining > 0 for r in pending)
        self.stock_summary.configure(text=f"Shopping list: {missing} short · {unknown} need counts. Bank stock may need withdrawing before a craft.")
        if hasattr(self, "book_ui"):
            self.book_ui.refresh_shopping(rows)
        inventory_ui = getattr(self.host, "inventory_page", None)
        if self.store.error or (inventory_ui and inventory_ui.store.error):
            self.stock_summary.configure(text="Saved plans or inventory are unreadable. Shared stock is unknown; original files are preserved.")
        self.host.root.event_generate("<<InventoryStockChanged>>")

    def open_inventory(self):
        # Preserve inventory filters and unfinished entry forms.
        self.host.tabs.select(self.host.inventory)

    def _legacy_notice(self):
        item = next((m for m in self.plan.materials if item_key(m.name, m.catalogue_ref) == self.material_original), None)
        message = ""
        if item and item.owned is not None:
            message = f"Previous planning count: {item.owned} (retained, not added). Record its Bags / Bank split in Inventory & Bank."
        elif any(m.owned is not None for m in self.plan.materials):
            message = "Older planning counts are retained. Select a material to see its previous count; enter its location totals in Inventory & Bank."
        self.legacy_count.configure(text=message)

    def clear_material(self):
        self.material_table.selection_remove(*self.material_table.selection())
        self.material_original = None
        self.material_selected_key = None
        self.material_label.set("")
        self.extra_target.set("0")
        self.owned.set("")
        self.source.set("Either")
        self.material_lookup.load(None)
        self._legacy_notice()

    def _material_selected(self, _event=None):
        selection = self.material_table.selection()
        if not selection:
            return
        key = selection[0]
        if _event is not None and key == self.material_selected_key:
            return
        required = next(r for r in self.requirements() if r.key == key)
        item = self._manual_material(required) or Material(required.name, catalogue_ref=required.catalogue_ref)
        self.material_original = item_key(item.name, item.catalogue_ref)
        self.material_selected_key = key
        self.material_label.set(item.name)
        self.material_lookup.load(item.catalogue_ref)
        self.extra_target.set(str(item.target))
        self.owned.set("Unknown" if required.owned is None else str(required.owned))
        self._legacy_notice()
        self.source.set(item.source)

    def apply_material(self):
        try:
            name = material_name(self.material_label.get())
            new_key = item_key(name, self.material_lookup.reference)
            previous = next((m for m in self.plan.materials if item_key(m.name, m.catalogue_ref) == (self.material_original or new_key)), None)
            item = Material(name, count(int(self.extra_target.get()), "Extra gathering goal"),
                            previous.owned if previous else None, self.source.get(), self.material_lookup.reference)
            candidate = deepcopy(self.plan)
            key = item_key(item.name, item.catalogue_ref)
            aliases = candidate.aliases(self.host.inventory_page.book)
            old_resolved = resolved_key(previous.name, previous.catalogue_ref, aliases) if previous else self.material_selected_key
            retargeted = previous and (material_key(previous.name) != material_key(item.name) or
                                      (previous.catalogue_ref and item.catalogue_ref and previous.catalogue_ref.item_id != item.catalogue_ref.item_id))
            if retargeted and any(resolved_key(i.name, i.catalogue_ref, aliases) == old_resolved for g in candidate.goals for i in g.ingredients):
                raise ValueError("That material is used by a recipe. Edit its ingredient name there first, or choose New entry.")
            remove = self.material_original or key
            candidate.materials = [m for m in candidate.materials if item_key(m.name, m.catalogue_ref) != remove] + [item]
            candidate.validate()
        except ValueError as exc:
            self.message(str(exc), True)
            return False
        self.plans[self.host.profile.id] = candidate
        self.refresh(material=resolved_key(item.name, item.catalogue_ref, candidate.aliases(self.host.inventory_page.book)))
        self.message("Material applied. Save plan to keep it. Counts are manually entered, not read from WoW.")
        return True

    def remove_material(self):
        selection = self.material_table.selection()
        if not selection:
            self.message("Select a material entry first.", True)
            return False
        key = selection[0]
        required = next(r for r in self.requirements() if r.key == key)
        manual = self._manual_material(required)
        if manual is None:
            self.message("This requirement comes from a recipe. Edit or remove its crafting goal to change it.", True)
            return False
        self.plan.materials.remove(manual)
        self.clear_material()
        self.refresh()
        self.message("Manual entry cleared. Recipe requirements remain; Save plan to keep the change.")
        return True

    def clear_goal(self):
        self.goal_table.selection_remove(*self.goal_table.selection())
        self.goal_name.set("")
        self.goal_quantity.set("1")
        self.profession.set("")
        self.output_per_craft.set("")
        self.goal_edit_id = None
        self.ingredients.delete("1.0", "end")
        self.output_lookup.load(None)
        self.ingredient_refs = {}
        self.ingredient_amount.set("1")

    def _goal_selected(self, _event=None):
        selection = self.goal_table.selection()
        if not selection:
            return
        if _event is not None and selection[0] == getattr(self, "goal_edit_id", None):
            return
        goal = next(g for g in self.plan.goals if g.id == selection[0])
        self.goal_edit_id = goal.id
        self.goal_name.set(goal.name)
        self.output_lookup.load(goal.catalogue_ref)
        self.goal_quantity.set(str(goal.quantity))
        self.profession.set(goal.profession)
        self.output_per_craft.set("" if goal.output_per_craft is None else str(goal.output_per_craft))
        self.ingredients.delete("1.0", "end")
        self.ingredient_refs = {i.catalogue_ref.item_id: i.catalogue_ref for i in goal.ingredients if i.catalogue_ref is not None}
        self.ingredients.insert("1.0", "\n".join(f"{i.name}" + (f" [#{i.catalogue_ref.item_id}]" if i.catalogue_ref else "") + f" = {i.per_craft}" for i in goal.ingredients))

    def apply_goal(self):
        selection = self.goal_table.selection()
        existing = next((g for g in self.plan.goals if selection and g.id == selection[0]), None)
        try:
            goal = CraftGoal(existing.id if existing else uuid4().hex, self.goal_name.get().strip(),
                count(int(self.goal_quantity.get()), "Crafting goal", 1), parse_ingredients(self.ingredients.get("1.0", "end"), self.ingredient_refs),
                existing.completed if existing else 0, self.profession.get().strip(), self.output_lookup.reference,
                count(int(self.output_per_craft.get()), "Output per craft", 1) if self.output_per_craft.get().strip() else None)
            candidate = deepcopy(self.plan)
            candidate.goals = [goal if g.id == goal.id else g for g in candidate.goals] if existing else [*candidate.goals, goal]
            candidate.validate()
        except ValueError as exc:
            self.message(str(exc), True)
            return False
        self.plans[self.host.profile.id] = candidate
        self.refresh(goal=goal.id)
        self.message("Goal applied. Gathering now includes its materials. Save plan to keep it.")
        return True

    def move_goal(self, direction):
        selection = self.goal_table.selection()
        if not selection:
            self.message("Select a queued craft first.", True)
            return False
        index = next(i for i, g in enumerate(self.plan.goals) if g.id == selection[0])
        destination = index + direction
        if not 0 <= destination < len(self.plan.goals):
            return False
        self.plan.goals[index], self.plan.goals[destination] = self.plan.goals[destination], self.plan.goals[index]
        self.goal_table.move(selection[0], "", destination)
        self.message("Queue order changed. Save plan to keep it; combined material demand is unchanged.")
        return True

    def remove_goal(self):
        selection = self.goal_table.selection()
        if not selection:
            self.message("Select a crafting goal first.", True)
            return False
        self.plan.goals = [g for g in self.plan.goals if g.id != selection[0]]
        self.clear_goal()
        self.refresh()
        self.message("Goal removed from this session. Save plan to keep the change.")
        return True

    def record_one(self):
        selection = self.goal_table.selection()
        try:
            self.plan.record_crafted(selection[0] if selection else "", self.host.inventory_page.book)
        except ValueError as exc:
            self.message(str(exc), True)
            return False
        self.refresh(goal=selection[0])
        self.host.inventory_page.refresh()
        self.message("Recorded one craft. Recheck used materials in Inventory & Bank; Save plan to keep progress and recheck flags.")
        return True

    def save(self):
        try:
            if self.store.error:
                raise ValueError(self.store.error)
            if self.host.store.error:
                raise ValueError(self.host.store.error)
            selected = self.host.tabs.select()
            if selected == str(self.gathering) and (self.material_label.get().strip()
                    or self.extra_target.get().strip() != "0" or self.source.get() != "Either"):
                if not self.apply_material():
                    return False
            if selected == str(self.crafting) and self.craft_tabs.select() == str(self.queue_page) and (
                    self.goal_name.get().strip() or self.profession.get().strip() or self.output_per_craft.get().strip()
                    or self.ingredients.get("1.0", "end").strip() or self.goal_quantity.get().strip() != "1"):
                if not self.apply_goal():
                    return False
            # Save character identities first so plans for new alts remain reachable.
            if not self.host.ensure_plan_profile():
                raise ValueError("The character profile could not be saved. Check Advanced → Profiles & Rules.")
            self.store.save(self.plans)
        except (ValueError, OSError) as exc:
            self.message(str(exc), True)
            return False
        suffix = " Save inventory to keep its unsaved counts too." if self.host.inventory_page.dirty else ""
        self.message("Plans saved locally with a previous-save backup." + suffix)
        return True
