"""Manual profession plans. No game data, recipe catalogue or gameplay actions."""

from dataclasses import asdict, dataclass, field
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from model import text
from storage import write_json
from item_values import count, material_key, material_name
from catalogue import (CatalogueRef, item_aliases, item_key, load_reference,
                       resolved_key, unique_items, validate_reference)


SOURCES = ("Gather", "Buy", "Either")


def stock_time(value):
    text(value, "Stock timestamp", 40)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Stock timestamp must be an ISO UTC timestamp.") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Stock timestamp must include the UTC timezone.")
    return parsed


@dataclass
class Material:
    name: str
    target: int = 0
    owned: int | None = None
    source: str = "Either"
    catalogue_ref: CatalogueRef | None = None

    def validate(self):
        material_name(self.name)
        validate_reference(self.name, self.catalogue_ref)
        count(self.target, "Extra gathering goal")
        if self.owned is not None:
            count(self.owned, "Owned count")
        if self.source not in SOURCES:
            raise ValueError("Choose Gather, Buy or Either.")


@dataclass
class Ingredient:
    name: str
    per_craft: int
    catalogue_ref: CatalogueRef | None = None

    def validate(self):
        material_name(self.name)
        validate_reference(self.name, self.catalogue_ref)
        count(self.per_craft, "Quantity per craft", 1)


@dataclass
class CraftGoal:
    id: str
    name: str
    quantity: int
    ingredients: list[Ingredient]
    completed: int = 0
    profession: str = ""
    catalogue_ref: CatalogueRef | None = None
    output_per_craft: int | None = None

    def validate(self):
        text(self.id, "Goal ID")
        text(self.name, "Crafted item")
        validate_reference(self.name, self.catalogue_ref)
        text(self.profession, "Profession label", allow_empty=True)
        count(self.quantity, "Crafting goal", 1)
        count(self.completed, "Completed crafts", 0, self.quantity)
        if self.output_per_craft is not None:
            count(self.output_per_craft, "Output per craft", 1)
        if not isinstance(self.ingredients, list) or not 1 <= len(self.ingredients) <= 100:
            raise ValueError("Enter 1–100 ingredients for the goal.")
        for ingredient in self.ingredients:
            if not isinstance(ingredient, Ingredient):
                raise ValueError("Invalid ingredient.")
            ingredient.validate()
        unique_items(((i.name, i.catalogue_ref) for i in self.ingredients), "recipe ingredients")


@dataclass
class Recipe:
    """A character's manual template; queued crafts hold independent copies."""
    id: str
    name: str
    ingredients: list[Ingredient]
    profession: str = ""
    catalogue_ref: CatalogueRef | None = None
    output_per_craft: int | None = None

    def validate(self):
        CraftGoal(self.id, self.name, 1, self.ingredients, profession=self.profession,
                  catalogue_ref=self.catalogue_ref, output_per_craft=self.output_per_craft).validate()


@dataclass(frozen=True)
class Requirement:
    name: str
    needed: int
    owned: int | None
    source: str
    bags: int | None = None
    bank: int | None = None
    key: str = ""
    catalogue_ref: CatalogueRef | None = None

    @property
    def remaining(self):
        if self.needed == 0:
            return 0
        return None if self.owned is None else max(0, self.needed - self.owned)


@dataclass
class ProfessionPlan:
    materials: list[Material] = field(default_factory=list)
    goals: list[CraftGoal] = field(default_factory=list)
    # Saved with craft progress, so saving a plan cannot revive older inventory
    # from its separately saved file. A fresh manual entry clears each location.
    recheck_after: dict[str, str] = field(default_factory=dict)
    recipes: list[Recipe] = field(default_factory=list)

    def validate(self):
        if not isinstance(self.recipes, list) or len(self.recipes) > 200:
            raise ValueError("Keep up to 200 reusable recipes per character.")
        recipe_ids = set()
        for recipe in self.recipes:
            if not isinstance(recipe, Recipe):
                raise ValueError("Invalid reusable recipe.")
            recipe.validate()
            if recipe.id in recipe_ids:
                raise ValueError("Recipe IDs must be unique.")
            recipe_ids.add(recipe.id)
        if not isinstance(self.recheck_after, dict) or len(self.recheck_after) > 5000:
            raise ValueError("Invalid material recheck history.")
        for key, stamp in self.recheck_after.items():
            if material_key(key) != key:
                raise ValueError("Invalid material recheck name.")
            stock_time(stamp)
        if not isinstance(self.materials, list) or len(self.materials) > 200:
            raise ValueError("Keep up to 200 manual material entries per character.")
        if not isinstance(self.goals, list) or len(self.goals) > 50:
            raise ValueError("Keep up to 50 crafting goals per character.")
        for item in self.materials:
            if not isinstance(item, Material):
                raise ValueError("Invalid material entry.")
            item.validate()
        unique_items(((m.name, m.catalogue_ref) for m in self.materials), "material entries")
        ids = set()
        for goal in self.goals:
            if not isinstance(goal, CraftGoal):
                raise ValueError("Invalid crafting goal.")
            goal.validate()
            if goal.id in ids:
                raise ValueError("Crafting goal IDs must be unique.")
            ids.add(goal.id)

    def enqueue(self, recipe_id, quantity):
        self.validate()
        count(quantity, "Number of crafts", 1)
        recipe = next((r for r in self.recipes if r.id == recipe_id), None)
        if recipe is None:
            raise ValueError("Select an applied recipe first.")
        if len(self.goals) >= 50:
            raise ValueError("Keep up to 50 crafting goals per character.")
        goal = CraftGoal(uuid4().hex, recipe.name, quantity, deepcopy(recipe.ingredients),
                         profession=recipe.profession, catalogue_ref=deepcopy(recipe.catalogue_ref),
                         output_per_craft=recipe.output_per_craft)
        goal.validate()
        self.goals.append(goal)
        return goal

    def aliases(self, inventory=None):
        records = [(m.name, m.catalogue_ref) for m in self.materials]
        records += [(i.name, i.catalogue_ref) for g in self.goals for i in g.ingredients]
        if inventory is not None:
            records += [(e.name, e.catalogue_ref) for e in inventory.entries]
        return item_aliases(records)

    def requirements(self, inventory=None):
        self.validate()
        aliases = self.aliases(inventory)
        rows = {resolved_key(m.name, m.catalogue_ref, aliases): [m.name, m.target, m.owned, m.source, m.catalogue_ref] for m in self.materials}
        for goal in self.goals:
            pending = goal.quantity - goal.completed
            if not pending:
                continue
            for ingredient in goal.ingredients:
                key = resolved_key(ingredient.name, ingredient.catalogue_ref, aliases)
                row = rows.setdefault(key, [ingredient.name, 0, None, "Either", ingredient.catalogue_ref])
                row[1] += pending * ingredient.per_craft
                row[4] = row[4] or ingredient.catalogue_ref
        result = []
        stock = inventory.stock_by_material(self.recheck_after, aliases) if inventory is not None else {}
        for key in sorted(rows, key=lambda key: (material_key(rows[key][0]), key)):
            name, needed, owned, source, reference = rows[key]
            if inventory is None:
                # Retained for reading older standalone plans. The desktop UI
                # always supplies this character's inventory, even when empty.
                result.append(Requirement(name, needed, owned, source, key=key, catalogue_ref=reference))
            else:
                bags, bank = stock.get(key, (None, None))
                total = None if bags is None or bank is None else bags + bank
                result.append(Requirement(name, needed, total, source, bags, bank, key, reference))
        return result

    def record_crafted(self, goal_id, inventory=None, checked_at=None):
        self.validate()
        goal = next((g for g in self.goals if g.id == goal_id), None)
        if goal is None or goal.completed >= goal.quantity:
            raise ValueError("Select a goal with crafts still remaining.")
        aliases = self.aliases(inventory)
        used = {resolved_key(i.name, i.catalogue_ref, aliases) for i in goal.ingredients}
        stamp = stock_time(checked_at) if checked_at else datetime.now(timezone.utc)
        if inventory is not None:
            inventory.validate()
            # Invalidate even manually dated entries ahead of the local clock.
            stamp = max([stamp, *(stock_time(e.updated_at) for e in inventory.entries
                                  if resolved_key(e.name, e.catalogue_ref, aliases) in used)])
        rechecks = dict(self.recheck_after)
        for key in used:
            previous = self.recheck_after.get(key)
            rechecks[key] = max(stamp, stock_time(previous) if previous else stamp).isoformat()
        if len(rechecks) > 5000:
            raise ValueError("Material recheck history is full; craft progress was not changed.")
        self.recheck_after = rechecks
        goal.completed += 1
        # A recorded craft is a manual fact; old stock counts may now be stale.
        for material in self.materials:
            if resolved_key(material.name, material.catalogue_ref, aliases) in used:
                material.owned = None

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            if (not isinstance(data, dict) or not {"materials", "goals"} <= set(data)
                    or set(data) - {"materials", "goals", "recheck_after", "recipes"}):
                raise ValueError("Invalid saved profession plan.")
            if not isinstance(data["materials"], list) or not isinstance(data["goals"], list):
                raise ValueError("Invalid saved plan lists.")
            def ingredients_from_saved(raw):
                if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
                    raise ValueError("Invalid saved ingredient list.")
                return [Ingredient(**{**item, "catalogue_ref": load_reference(item.get("catalogue_ref"))}) for item in raw]

            goals = []
            for raw in data["goals"]:
                if not isinstance(raw, dict):
                    raise ValueError("Invalid saved crafting goal.")
                values = dict(raw)
                values["catalogue_ref"] = load_reference(values.get("catalogue_ref"))
                values["ingredients"] = ingredients_from_saved(values["ingredients"])
                goals.append(CraftGoal(**values))
            raw_recipes = data.get("recipes", [])
            if not isinstance(raw_recipes, list):
                raise ValueError("Invalid saved recipe list.")
            recipes = []
            for raw in raw_recipes:
                if not isinstance(raw, dict):
                    raise ValueError("Invalid saved recipe.")
                values = dict(raw)
                values["catalogue_ref"] = load_reference(values.get("catalogue_ref"))
                values["ingredients"] = ingredients_from_saved(values["ingredients"])
                recipes.append(Recipe(**values))
            if any(not isinstance(item, dict) for item in data["materials"]):
                raise ValueError("Invalid saved material.")
            plan = cls([Material(**{**item, "catalogue_ref": load_reference(item.get("catalogue_ref"))}) for item in data["materials"]], goals, data.get("recheck_after", {}), recipes)
            plan.validate()
            return plan
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid saved profession fields.") from exc


def parse_ingredients(value, references=None):
    ingredients = []
    for line in value.splitlines():
        if not line.strip():
            continue
        name, separator, amount = line.rpartition("=")
        if not separator:
            raise ValueError("Use one ingredient per line: material name = quantity per craft.")
        try:
            reference = None
            annotated = re.fullmatch(r"(.*?)\s+\[#(\d+)\]\s*", name)
            if annotated:
                name = annotated[1]
                reference = (references or {}).get(int(annotated[2]))
                if reference is None:
                    raise ValueError("Use Find ingredient to select this item ID, or remove its [#ID] label for a manual entry.")
            ingredients.append(Ingredient(material_name(name), count(int(amount.strip()), "Quantity per craft", 1), reference))
        except ValueError as exc:
            raise ValueError(f"Invalid ingredient line: {line[:100]}. {exc}") from exc
    # Reuse recipe validation for empty and duplicate ingredient lists.
    CraftGoal("check", "check", 1, ingredients).validate()
    return ingredients


class PlanStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "planning.json"
        self.error = ""
        self.loaded_bytes = None

    def load(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved plans are too large.")
            self.loaded_bytes = self.path.read_bytes()
            data = json.loads(self.loaded_bytes)
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] not in (1, 2, 3, 4):
                raise ValueError("Unsupported saved-plan format.")
            raw = data.get("plans")
            if not isinstance(raw, dict) or len(raw) > 100:
                raise ValueError("Invalid saved character plans.")
            for profile_id in raw:
                text(profile_id, "Character profile ID")
            return {key: ProfessionPlan.from_dict(value) for key, value in raw.items()}
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"Plans could not be read: {exc} Original file preserved; saving disabled."
            return {}

    def save(self, plans):
        if self.error:
            raise ValueError(self.error)
        if not isinstance(plans, dict) or len(plans) > 100:
            raise ValueError("Keep up to 100 character plans.")
        for profile_id in plans:
            text(profile_id, "Character profile ID")
        payload = {"version": 4, "plans": {key: plan.to_dict() for key, plan in plans.items()}}
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            raise ValueError("Saved plans changed outside this preview. Reopen before saving; external changes preserved.")
        write_json(self.path, payload)
        self.loaded_bytes = self.path.read_bytes()
