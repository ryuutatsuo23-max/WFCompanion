"""Read-only catalogue ownership view using the existing per-character stock rules."""

from dataclasses import dataclass

from catalogue import item_aliases, resolved_key
from inventory import InventoryBook, LOCATIONS, entered_time
from item_values import material_key
from professions import ProfessionPlan, stock_time


OWNERSHIP_FILTERS = ("All", "Owned", "Not owned", "Unknown")


def ownership_state(counts):
    """One positive count proves ownership; absence needs two recorded zeroes."""
    quantities = tuple(count.quantity for count in counts)
    if any(quantity is not None and quantity > 0 for quantity in quantities):
        return "Owned"
    if quantities == (0, 0):
        return "Not owned"
    return "Unknown"


def ownership_selection(stock, choice):
    """Return an ID set and exclusion switch for filtering before SQL LIMIT."""
    if choice not in OWNERSHIP_FILTERS:
        raise ValueError("Choose All, Owned, Not owned or Unknown.")
    if choice == "All":
        return None, False
    if choice == "Unknown":
        return {item_id for item_id, counts in stock.items() if ownership_state(counts) != "Unknown"}, True
    return {item_id for item_id, counts in stock.items() if ownership_state(counts) == choice}, False


@dataclass(frozen=True)
class RecordedCount:
    quantity: int | None = None
    reason: str = "No record for this location."

    @property
    def label(self):
        return "Unknown" if self.quantity is None else str(self.quantity)


def unknown_stock(references, reason):
    return {ref.item_id: (RecordedCount(reason=reason), RecordedCount(reason=reason)) for ref in references}


def catalogue_stock(references, book, plan=None):
    """Resolve catalogue IDs against recorded stock without writes."""
    return recorded_stock(((ref.item_id, ref.name, ref) for ref in references), book, plan)


def recorded_stock(records, book, plan=None, references=()):
    """Read stock for (row key, name, optional reference), including manual goals.

    All rows and related catalogue references participate in ambiguity checks.
    Repeated wishlist slots share an item total; nothing is allocated or consumed.
    """
    records = list(records)
    references = list(references)
    if not isinstance(book, InventoryBook):
        raise ValueError("Recorded inventory is unavailable.")
    plan = plan if plan is not None else ProfessionPlan()
    plan.validate()
    names = [(name, ref) for _row, name, ref in records]
    names += [(ref.name, ref) for ref in references]
    for name, ref in names:
        material_key(name)
        if ref is not None:
            ref.validate()
    aliases = plan.aliases(book)
    for name, keys in item_aliases(names).items():
        aliases.setdefault(name, set()).update(keys)
    # Validate/index the character's full inventory once, never per result row.
    stock = book.stock_by_material(plan.recheck_after, aliases)
    entries = {(resolved_key(e.name, e.catalogue_ref, aliases), e.location): e for e in book.entries}
    manual_names = {(material_key(e.name), e.location) for e in book.entries if e.catalogue_ref is None}
    result = {}
    for row, name, ref in records:
        normalized = material_key(name)
        if ref is None and len(aliases.get(normalized, ())) > 1:
            result[row] = (RecordedCount(reason="Manual name needs an exact item ID before matching."),) * 2
            continue
        key = resolved_key(name, ref, aliases)
        quantities = stock.get(key, (None, None))
        counts = []
        for location, quantity in zip(LOCATIONS, quantities):
            entry = entries.get((key, location))
            if entry is None:
                reason = ("Manual name needs an exact item ID before matching."
                          if (normalized, location) in manual_names else "No record for this location.")
            else:
                cutoff = book.cutoff_for(entry, plan.recheck_after, aliases)
                reason = ("Recheck after a recorded craft."
                          if cutoff and entered_time(entry.updated_at) <= stock_time(cutoff) else
                          "Quantity was left blank." if quantity is None else "Manually recorded count.")
            counts.append(RecordedCount(quantity, reason))
        result[row] = tuple(counts)
    return result
