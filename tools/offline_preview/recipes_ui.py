"""Offline recipe templates and the planner's single combined shopping list."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from catalogue import display_name
from catalogue_ui import CataloguePicker
from item_lookup_ui import ItemLookup
from professions import Recipe, count, parse_ingredients
from ui_layout import ScrollPage


class RecipeBookUI:
    def __init__(self, planner):
        self.planner = planner
        self.host = planner.host
        self.active_id = self.host.profile.id
        self.edit_id = None
        self.drafts = {}
        self.refs = {}
        self.picker = None
        self.page = ttk.Frame(planner.craft_tabs)
        self.shopping_page = ttk.Frame(planner.craft_tabs)
        planner.craft_tabs.add(self.page, text="Recipe book")
        planner.craft_tabs.add(self.shopping_page, text="Shopping list")
        self.scroll = ScrollPage(self.page)
        self.scroll.pack(fill="both", expand=True)
        parent = self.scroll.inner
        ttk.Label(parent, text="Reusable recipes", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Your manual recipes for this character. Select an applied recipe to queue it again.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=6)
        self.table = planner._table(parent, (("name", "Recipe / output", 300),
            ("profession", "Profession", 150), ("yield", "Output per craft", 150)))
        self.table.bind("<<TreeviewSelect>>", self.select)
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="Crafts to queue").pack(side="left")
        self.quantity = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self.quantity, width=7).pack(side="left", padx=8)
        self.enqueue_button = ttk.Button(row, text="Add to queue", command=self.enqueue, style="Primary.TButton")
        self.enqueue_button.pack(side="left")
        ttk.Button(row, text="View queue", command=lambda: planner.craft_tabs.select(planner.queue_page)).pack(side="left", padx=8)
        self.name = tk.StringVar()
        self.profession = tk.StringVar()
        self.output = tk.StringVar()
        self.lookup = ItemLookup(self.host, parent, self.name, label="Find output item…")
        fields = ttk.Frame(parent)
        fields.pack(fill="x")
        planner._field(fields, "Recipe / output name", self.name, 0)
        planner._field(fields, "Profession (optional)", self.profession, 1)
        planner._field(fields, "Output per craft (blank = Unknown)", self.output, 2)
        ttk.Label(parent, text="Ingredients per craft · One per line: material name = quantity",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=4)
        self.ingredients = tk.Text(parent, height=4, width=20, wrap="word", font=("Segoe UI", 10),
            background="#111c2a", foreground="#edf3fa", insertbackground="#edf3fa", undo=True)
        self.ingredients.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        self.find_button = ttk.Button(row, text="Find ingredient…", command=self.open_picker)
        self.find_button.pack(side="left")
        ttk.Label(row, text="Per craft", style="Muted.TLabel").pack(side="left", padx=8)
        self.amount = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self.amount, width=7).pack(side="left")
        if self.host.catalogue.error:
            self.find_button.state(["disabled"])
        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.apply_button = ttk.Button(row, text="Apply recipe", command=self.apply, style="Primary.TButton")
        self.apply_button.pack(side="left")
        ttk.Button(row, text="New recipe", command=self.clear).pack(side="left", padx=8)
        ttk.Button(row, text="Remove recipe", command=self.remove).pack(side="left")
        ttk.Label(parent, text="Apply recipe, then Save plan to keep it. Queue entries keep their own recipe copy. "
                  "Output amounts are estimates only; recording a craft never adds inventory.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=8)
        planner._save_footer(parent)

        self.shopping_scroll = ScrollPage(self.shopping_page)
        self.shopping_scroll.pack(fill="both", expand=True)
        parent = self.shopping_scroll.inner
        ttk.Label(parent, text="Combined shopping list", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Remaining queue ingredients + extra Gathering goals. Recorded Bags + Bank stock is subtracted once. "
                  "Unknown or recheck counts need confirming in Inventory & Bank.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=6)
        self.shopping_table = planner._table(parent, (("name", "Material", 240), ("needed", "Needed", 75),
            ("bags", "Bags", 75), ("bank", "Bank", 75), ("total", "Total", 80),
            ("short", "Still needed", 110), ("source", "Source", 85)))
        self.summary = ttk.Label(parent, style="Muted.TLabel", wraplength=780)
        self.summary.pack(anchor="w", pady=8)
        self.price_summary = ttk.Label(parent, text="Price estimate: Unknown", style="Muted.TLabel", wraplength=780)
        self.price_summary.pack(anchor="w", pady=6)
        ttk.Button(parent, text="Open Auction Journal", command=lambda: self.host.tabs.select(self.host.price_journal.page)).pack(anchor="w")
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Button(row, text="Edit inventory", command=planner.open_inventory).pack(side="left")
        ttk.Button(row, text="Extra gathering goals", command=lambda: self.host.tabs.select(self.host.gathering)).pack(side="left", padx=8)
        ttk.Label(parent, text="This list includes covered materials as well as shortages. Bank items may need withdrawing. "
                  "Queue order does not reserve stock or expand sub-recipes.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=8)
        planner._save_footer(parent)

    def close(self):
        self.lookup.close()
        if self.picker is not None:
            self.picker.close()

    def open_picker(self):
        if self.host.catalogue.error:
            return
        if self.picker is not None:
            self.picker.window.lift()
        else:
            self.picker = CataloguePicker(self.host, self.host.catalogue, self.add_ingredient,
                                          self._picker_closed, category="Material")

    def _picker_closed(self):
        self.picker = None

    def add_ingredient(self, item):
        try:
            amount = count(int(self.amount.get()), "Quantity per craft", 1)
            item.validate()
            ref = item.reference
            current = self.ingredients.get("1.0", "end-1c")
            if any(f"[#{ref.item_id}]" in line for line in current.splitlines()):
                raise ValueError("This ingredient is already listed; edit its quantity.")
        except ValueError as exc:
            self.planner.message(str(exc), True)
            return False
        self.refs[ref.item_id] = ref
        self.ingredients.insert("end", ("\n" if current and not current.endswith("\n") else "") + f"{ref.name} [#{ref.item_id}] = {amount}")
        self.planner.message("Ingredient added to the recipe draft. Apply recipe when ready.")
        return True

    def _draft(self):
        return (self.edit_id, self.name.get(), self.profession.get(), self.output.get(),
                self.ingredients.get("1.0", "end-1c"), deepcopy(self.lookup.reference),
                deepcopy(self.refs), self.quantity.get(), self.amount.get())

    def _restore(self, draft):
        self.edit_id, name, profession, output, ingredients, reference, refs, quantity, amount = draft
        self.name.set(name)
        self.profession.set(profession)
        self.output.set(output)
        self.ingredients.delete("1.0", "end")
        self.ingredients.insert("1.0", ingredients)
        self.lookup.load(reference)
        self.refs = refs
        self.quantity.set(quantity)
        self.amount.set(amount)

    def refresh(self):
        changed = self.active_id != self.host.profile.id
        if changed:
            self.close()
            self.drafts[self.active_id] = self._draft()
            self.active_id = self.host.profile.id
            self.table.selection_remove(*self.table.selection())
            self._restore(self.drafts.get(self.active_id, (None, "", "", "", "", None, {}, "1", "1")))
        ids = {r.id for r in self.planner.plan.recipes}
        for key in self.table.get_children():
            if key not in ids:
                self.table.delete(key)
        for recipe in self.planner.plan.recipes:
            values = (display_name(recipe.name, recipe.catalogue_ref), recipe.profession or "—",
                      "Unknown" if recipe.output_per_craft is None else recipe.output_per_craft)
            if self.table.exists(recipe.id):
                self.table.item(recipe.id, values=values)
            else:
                self.table.insert("", "end", iid=recipe.id, values=values)
        if changed and self.edit_id in ids:
            self.table.selection_set(self.edit_id)

    def clear(self):
        self.table.selection_remove(*self.table.selection())
        self._restore((None, "", "", "", "", None, {}, "1", "1"))

    def select(self, event=None):
        selected = self.table.selection()
        if not selected or (event is not None and selected[0] == self.edit_id):
            return
        recipe = next(r for r in self.planner.plan.recipes if r.id == selected[0])
        self._load(recipe)

    def _load(self, recipe):
        self._restore((recipe.id, recipe.name, recipe.profession,
            "" if recipe.output_per_craft is None else str(recipe.output_per_craft),
            "\n".join(i.name + (f" [#{i.catalogue_ref.item_id}]" if i.catalogue_ref else "") + f" = {i.per_craft}" for i in recipe.ingredients),
            deepcopy(recipe.catalogue_ref), {i.catalogue_ref.item_id: deepcopy(i.catalogue_ref) for i in recipe.ingredients if i.catalogue_ref},
            self.quantity.get(), "1"))

    def apply(self):
        try:
            recipe = Recipe(self.edit_id or uuid4().hex, self.name.get().strip(),
                parse_ingredients(self.ingredients.get("1.0", "end"), self.refs),
                self.profession.get().strip(), self.lookup.reference,
                count(int(self.output.get()), "Output per craft", 1) if self.output.get().strip() else None)
            candidate = deepcopy(self.planner.plan)
            if any(r.id == recipe.id for r in candidate.recipes):
                candidate.recipes = [recipe if r.id == recipe.id else r for r in candidate.recipes]
            else:
                candidate.recipes.append(recipe)
            candidate.validate()
        except ValueError as exc:
            self.planner.message(str(exc), True)
            return False
        self.planner.plans[self.active_id] = candidate
        self.edit_id = recipe.id
        self.refresh()
        self.table.selection_set(recipe.id)
        self.planner.message("Recipe applied. Save plan to keep it. Existing queue entries keep their own copy.")
        return True

    def remove(self):
        selected = self.table.selection()
        if not selected:
            self.planner.message("Select an applied recipe first.", True)
            return False
        self.planner.plan.recipes = [r for r in self.planner.plan.recipes if r.id != selected[0]]
        self.clear()
        self.refresh()
        self.planner.message("Recipe removed; queued copies remain. Save plan to keep the change.")
        return True

    def enqueue(self):
        selected = self.table.selection()
        try:
            goal = self.planner.plan.enqueue(selected[0] if selected else "", count(int(self.quantity.get()), "Number of crafts", 1))
        except ValueError as exc:
            self.planner.message(str(exc), True)
            return False
        self.planner.refresh()
        output = "Unknown" if goal.output_per_craft is None else str(goal.quantity * goal.output_per_craft)
        self.planner.message(f"Added {goal.quantity} crafts of {goal.name} to the queue · expected output: {output}. "
                             "Used the applied recipe; drafts unchanged. Save plan to keep it.")
        return True

    def copy_goal(self):
        selected = self.planner.goal_table.selection()
        goal = next((g for g in self.planner.plan.goals if selected and g.id == selected[0]), None)
        if goal is None:
            self.planner.message("Select an applied queued craft first.", True)
            return False
        self.clear()
        self._load(Recipe("", goal.name, deepcopy(goal.ingredients), goal.profession,
                          deepcopy(goal.catalogue_ref), goal.output_per_craft))
        self.edit_id = None
        self.planner.craft_tabs.select(self.page)
        self.planner.message("Copied the applied queue entry into a new recipe draft. Apply recipe, then Save plan.")
        return True

    def refresh_shopping(self, rows):
        rows = [r for r in rows if r.needed > 0]
        keys = {r.key for r in rows}
        for key in self.shopping_table.get_children():
            if key not in keys:
                self.shopping_table.delete(key)
        for index, r in enumerate(rows):
            values = (display_name(r.name, r.catalogue_ref), r.needed,
                "Unknown" if r.bags is None else r.bags, "Unknown" if r.bank is None else r.bank,
                "Unknown" if r.owned is None else r.owned, "Unknown — check stock" if r.remaining is None else r.remaining, r.source)
            if self.shopping_table.exists(r.key):
                self.shopping_table.item(r.key, values=values)
                self.shopping_table.move(r.key, "", index)
            else:
                self.shopping_table.insert("", "end", iid=r.key, values=values)
        short = sum(r.remaining is not None and r.remaining > 0 for r in rows)
        unknown = sum(r.remaining is None for r in rows)
        self.summary.configure(text=f"{len(rows)} materials · {short} short · {unknown} Unknown · {len(rows) - short - unknown} covered. "
                               "Manual records for this character only.")
        inventory = getattr(self.host, "inventory_page", None)
        if self.planner.store.error or (inventory and inventory.store.error):
            self.summary.configure(text="Saved plans or inventory are unreadable. Stock is Unknown; original files are preserved.")
