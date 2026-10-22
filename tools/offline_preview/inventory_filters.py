"""Private per-character inventory view preferences, independent of item edits."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from inventory import LOCATIONS
from model import text
from storage import write_json


COUNT_FILTERS = ("All", "Known", "Unknown", "Recheck")


@dataclass(frozen=True)
class InventoryFilters:
    query: str = ""
    location: str = "All"
    count_status: str = "All"

    def validate(self):
        text(self.query, "Inventory search", 140, allow_empty=True)
        if self.location not in ("All", *LOCATIONS):
            raise ValueError("Choose All, Bags or Bank.")
        if self.count_status not in COUNT_FILTERS:
            raise ValueError("Choose All, Known, Unknown or Recheck.")

    @classmethod
    def from_dict(cls, value, version=2):
        fields = {"query", "location"} if version == 1 else {"query", "location", "count_status"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("Invalid saved inventory filters.")
        filters = cls(**value)
        filters.validate()
        return filters


class InventoryFilterStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "inventory_filters.json"
        self.profiles = {}
        self.loaded_bytes = None
        self.error = ""
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved inventory filters are too large.")
            self.loaded_bytes = self.path.read_bytes()
            payload = json.loads(self.loaded_bytes)
            if (not isinstance(payload, dict) or set(payload) != {"version", "profiles"}
                    or type(payload["version"]) is not int or payload["version"] not in (1, 2)
                    or not isinstance(payload["profiles"], dict) or len(payload["profiles"]) > 1000):
                raise ValueError("Unsupported inventory filter preferences.")
            parsed = {}
            for profile_id, value in payload["profiles"].items():
                filters = InventoryFilters.from_dict(value, payload["version"])
                self._validate(profile_id, filters)
                parsed[profile_id] = filters
            self.profiles = parsed
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"{exc} Original inventory filter preferences preserved; saving filters is disabled."

    @staticmethod
    def _validate(profile_id, filters):
        text(profile_id, "Inventory filter profile ID")
        if not isinstance(filters, InventoryFilters):
            raise ValueError("Invalid inventory filters.")
        filters.validate()

    def get(self, profile_id):
        text(profile_id, "Inventory filter profile ID")
        return self.profiles.get(profile_id, InventoryFilters())

    def save(self, profile_id, filters):
        if self.error:
            raise ValueError(self.error)
        self._validate(profile_id, filters)
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            self.error = "Inventory filter preferences changed outside this preview. Reopen before saving filters; external changes preserved."
            raise ValueError(self.error)
        if self.profiles.get(profile_id) == filters:
            return
        profiles = {**self.profiles, profile_id: filters}
        if len(profiles) > 1000:
            raise ValueError("Too many saved inventory filter profiles.")
        write_json(self.path, {"version": 2, "profiles": {key: asdict(value) for key, value in profiles.items()}})
        self.profiles = profiles
        self.loaded_bytes = self.path.read_bytes()
