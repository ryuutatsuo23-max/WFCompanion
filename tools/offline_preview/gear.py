"""Manual gear goals with optional catalogue links; no inventory/stat inference."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from model import text
from professions import material_key, material_name
from storage import write_json
from catalogue import CatalogueRef, wishlist_slots, item_key, unique_items


SLOTS = ("Unspecified", "Head", "Neck", "Shoulders", "Back", "Chest", "Wrists", "Hands",
         "Waist", "Legs", "Feet", "Finger 1", "Finger 2", "Trinket 1", "Trinket 2",
         "Main hand", "Off hand", "Ranged", "Relic", "Shirt", "Tabard", "Other")
PRIORITIES = ("High", "Normal", "Low")
STATUSES = ("Wanted", "Obtained")


@dataclass
class GearItem:
    id: str
    name: str
    slot: str = "Unspecified"
    priority: str = "Normal"
    status: str = "Wanted"
    source: str = ""
    note: str = ""
    bis_candidate: bool = False
    catalogue_ref: CatalogueRef | None = None

    @property
    def key(self):
        return item_key(self.name, self.catalogue_ref), self.slot

    def validate(self):
        text(self.id, "Gear entry ID")
        material_name(self.name)
        if self.slot not in SLOTS:
            raise ValueError("Choose a gear slot from the list.")
        if self.priority not in PRIORITIES:
            raise ValueError("Choose High, Normal or Low priority.")
        if self.status not in STATUSES:
            raise ValueError("Choose Wanted or Obtained.")
        text(self.source, "Item source", 140, allow_empty=True)
        text(self.note, "Item note", 200, allow_empty=True)
        if type(self.bis_candidate) is not bool:
            raise ValueError("BiS candidate must be on or off.")
        if self.catalogue_ref is not None:
            if not isinstance(self.catalogue_ref, CatalogueRef):
                raise ValueError("Invalid linked item reference.")
            self.catalogue_ref.validate()
            if (material_key(self.name) != material_key(self.catalogue_ref.name)
                    or self.slot not in wishlist_slots(self.catalogue_ref.equip_slot)):
                raise ValueError("Linked item name or slot differs; clear its catalogue link for a manual entry.")


@dataclass
class GearWishlist:
    entries: list[GearItem] = field(default_factory=list)

    def validate(self):
        if not isinstance(self.entries, list) or len(self.entries) > 500:
            raise ValueError("Keep up to 500 gear goals per character.")
        ids, keys = set(), set()
        for item in self.entries:
            if not isinstance(item, GearItem):
                raise ValueError("Invalid gear entry.")
            item.validate()
            if item.id in ids or item.key in keys:
                raise ValueError("This item/slot already has an entry. Select its row to update it.")
            ids.add(item.id)
            keys.add(item.key)
        for slot in SLOTS:
            unique_items(((item.name, item.catalogue_ref) for item in self.entries if item.slot == slot),
                         "gear item/slot")

    def find(self, query="", status="All"):
        self.validate()
        if status not in ("All", *STATUSES):
            raise ValueError("Choose All, Wanted or Obtained.")
        query = text(query, "Gear search", 200, allow_empty=True).casefold()
        matches = (item for item in self.entries if (status == "All" or item.status == status)
                   and query in f"{item.name} {item.slot} {item.source} {item.note} {item.catalogue_ref.item_id if item.catalogue_ref else ''}".casefold())
        return sorted(matches, key=lambda item: (STATUSES.index(item.status), PRIORITIES.index(item.priority),
                                                SLOTS.index(item.slot), material_key(item.name)))

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            if not isinstance(data, dict) or set(data) != {"entries"} or not isinstance(data["entries"], list):
                raise ValueError("Invalid saved gear wishlist.")
            entries = []
            for raw in data["entries"]:
                values = dict(raw)
                if values.get("catalogue_ref") is not None:
                    values["catalogue_ref"] = CatalogueRef(**values["catalogue_ref"])
                entries.append(GearItem(**values))
            wishlist = cls(entries)
            wishlist.validate()
            return wishlist
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid saved gear fields.") from exc


class GearStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "gear_wishlist.json"
        self.error = ""
        self.loaded_bytes = None

    def load(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved gear wishlists are too large.")
            self.loaded_bytes = self.path.read_bytes()
            data = json.loads(self.loaded_bytes)
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] not in (1, 2):
                raise ValueError("Unsupported gear wishlist format.")
            characters = data.get("characters")
            if not isinstance(characters, dict) or len(characters) > 100:
                raise ValueError("Invalid character gear wishlists.")
            for profile_id in characters:
                text(profile_id, "Character profile ID")
            return {key: GearWishlist.from_dict(value) for key, value in characters.items()}
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"Gear wishlists could not be read: {exc} Original file preserved; saving disabled."
            return {}

    def save(self, characters):
        if self.error:
            raise ValueError(self.error)
        if not isinstance(characters, dict) or len(characters) > 100:
            raise ValueError("Keep up to 100 character gear wishlists.")
        for profile_id, wishlist in characters.items():
            text(profile_id, "Character profile ID")
            if not isinstance(wishlist, GearWishlist):
                raise ValueError("Invalid character gear wishlist.")
        payload = {"version": 2, "characters": {key: value.to_dict() for key, value in characters.items()}}
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            raise ValueError("Gear wishlists changed outside this preview. Reopen before saving; external changes preserved.")
        write_json(self.path, payload)
        self.loaded_bytes = self.path.read_bytes()
