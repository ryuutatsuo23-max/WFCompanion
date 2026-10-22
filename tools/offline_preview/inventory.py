"""Manually entered inventory totals, separated by character and location."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from model import text
from professions import count, material_key, material_name, stock_time
from storage import write_json
from catalogue import (CatalogueRef, item_aliases, item_key, load_reference,
                       resolved_key, unique_items, validate_reference)


LOCATIONS = ("Bags", "Bank")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def entered_time(value):
    text(value, "Last-entered time", 40)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Last-entered time must be an ISO UTC timestamp.") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Last-entered time must include the UTC timezone.")
    return parsed


@dataclass
class InventoryEntry:
    id: str
    name: str
    quantity: int | None
    location: str
    updated_at: str
    note: str = ""
    source: str = "Manual"
    catalogue_ref: CatalogueRef | None = None

    @property
    def key(self):
        return item_key(self.name, self.catalogue_ref), self.location

    def validate(self):
        text(self.id, "Item entry ID")
        material_name(self.name)
        validate_reference(self.name, self.catalogue_ref)
        if self.quantity is not None:
            count(self.quantity, "Item quantity")
        if self.location not in LOCATIONS:
            raise ValueError("Choose Bags or Bank.")
        if self.source not in ("Manual", "Reviewed probe"):
            raise ValueError("Inventory counts must be manual or explicitly reviewed probe totals.")
        entered_time(self.updated_at)
        text(self.note, "Item note", 140, allow_empty=True)


@dataclass
class InventoryBook:
    entries: list[InventoryEntry] = field(default_factory=list)

    def validate(self):
        if not isinstance(self.entries, list) or len(self.entries) > 2000:
            raise ValueError("Keep up to 2,000 inventory entries per character.")
        ids, keys = set(), set()
        for entry in self.entries:
            if not isinstance(entry, InventoryEntry):
                raise ValueError("Invalid inventory entry.")
            entry.validate()
            if entry.id in ids or entry.key in keys:
                raise ValueError("Each item/location needs one unique entry. Select the existing row to update its count.")
            ids.add(entry.id)
            keys.add(entry.key)
        for location in LOCATIONS:
            unique_items(((e.name, e.catalogue_ref) for e in self.entries if e.location == location), "item/location totals")

    def find(self, query="", location="All"):
        self.validate()
        if location not in ("All", *LOCATIONS):
            raise ValueError("Choose All, Bags or Bank.")
        query = text(query, "Inventory search", 140, allow_empty=True).casefold()
        return sorted((e for e in self.entries if (location == "All" or e.location == location)
                       and query in f"{e.name} {e.note} {e.catalogue_ref.item_id if e.catalogue_ref else ''}".casefold()), key=lambda e: (material_key(e.name), e.location, e.key))

    def quantities(self, name, recheck_after=None, catalogue_ref=None):
        """Bags and Bank totals; missing, blank and consumed counts stay unknown.

        These are recorded totals, not proof that bank stock is usable in bags.
        """
        aliases = item_aliases((e.name, e.catalogue_ref) for e in self.entries)
        key = resolved_key(name, catalogue_ref, aliases)
        return self.stock_by_material({key: recheck_after} if recheck_after else {}, aliases).get(key, (None, None))

    def cutoff_for(self, entry, recheck_after, aliases=None):
        keys = (material_key(entry.name), item_key(entry.name, entry.catalogue_ref),
                resolved_key(entry.name, entry.catalogue_ref, aliases or {}))
        values = [recheck_after[key] for key in keys if key in recheck_after]
        return max(values, key=entered_time) if values else None

    def stock_by_material(self, recheck_after=None, aliases=None):
        """Build a single per-character index for all planning requirements."""
        self.validate()
        cutoffs = recheck_after or {}
        if aliases is None:
            aliases = item_aliases((e.name, e.catalogue_ref) for e in self.entries)
        recorded = {}
        for entry in self.entries:
            key = resolved_key(entry.name, entry.catalogue_ref, aliases)
            locations = recorded.setdefault(key, {})
            cutoff = self.cutoff_for(entry, cutoffs, aliases)
            if not cutoff or entered_time(entry.updated_at) > stock_time(cutoff):
                locations[entry.location] = entry.quantity
        return {key: tuple(locations.get(location) for location in LOCATIONS)
                for key, locations in recorded.items()}

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            if not isinstance(data, dict) or set(data) != {"entries"} or not isinstance(data["entries"], list):
                raise ValueError("Invalid saved inventory.")
            book = cls([InventoryEntry(**{**entry, "catalogue_ref": load_reference(entry.get("catalogue_ref"))}) for entry in data["entries"]])
            book.validate()
            return book
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid saved inventory fields.") from exc


class InventoryStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "inventory.json"
        self.error = ""
        self.loaded_bytes = None

    def load(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved inventory is too large.")
            self.loaded_bytes = self.path.read_bytes()
            data = json.loads(self.loaded_bytes)
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] not in (1, 2):
                raise ValueError("Unsupported inventory format.")
            characters = data.get("characters")
            if not isinstance(characters, dict) or len(characters) > 100:
                raise ValueError("Invalid character inventories.")
            for profile_id in characters:
                text(profile_id, "Character profile ID")
            return {key: InventoryBook.from_dict(value) for key, value in characters.items()}
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"Inventory could not be read: {exc} Original file preserved; saving disabled."
            return {}

    def save(self, characters):
        if self.error:
            raise ValueError(self.error)
        if not isinstance(characters, dict) or len(characters) > 100:
            raise ValueError("Keep up to 100 character inventories.")
        for profile_id, book in characters.items():
            text(profile_id, "Character profile ID")
            if not isinstance(book, InventoryBook):
                raise ValueError("Invalid character inventory.")
        payload = {"version": 2, "characters": {key: value.to_dict() for key, value in characters.items()}}
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            raise ValueError("Inventory changed outside this preview. Reopen before saving; external changes preserved.")
        write_json(self.path, payload)
        self.loaded_bytes = self.path.read_bytes()
