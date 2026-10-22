"""Private per-character wishlist view preferences, independent of goal records."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from item_stock import OWNERSHIP_FILTERS
from gear import STATUSES
from model import text
from storage import write_json


@dataclass(frozen=True)
class GearFilters:
    query: str = ""
    status: str = "All"
    ownership: str = "All"

    def validate(self):
        text(self.query, "Gear search", 200, allow_empty=True)
        if self.status not in ("All", *STATUSES):
            raise ValueError("Choose All, Wanted or Obtained.")
        if self.ownership not in OWNERSHIP_FILTERS:
            raise ValueError("Choose All, Owned, Not owned or Unknown.")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"query", "status", "ownership"}:
            raise ValueError("Invalid saved wishlist filters.")
        filters = cls(**value)
        filters.validate()
        return filters


class GearFilterStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "gear_filters.json"
        self.profiles = {}
        self.loaded_bytes = None
        self.error = ""
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved wishlist filters are too large.")
            self.loaded_bytes = self.path.read_bytes()
            payload = json.loads(self.loaded_bytes)
            if (not isinstance(payload, dict) or set(payload) != {"version", "profiles"}
                    or type(payload["version"]) is not int or payload["version"] not in (1, 2)
                    or not isinstance(payload["profiles"], dict) or len(payload["profiles"]) > 1000):
                raise ValueError("Unsupported wishlist filter preferences.")
            parsed = {}
            for profile_id, value in payload["profiles"].items():
                filters = GearFilters(ownership=value) if payload["version"] == 1 else GearFilters.from_dict(value)
                self._validate(profile_id, filters)
                parsed[profile_id] = filters
            self.profiles = parsed
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"{exc} Original wishlist filter preferences preserved; saving filters is disabled."

    @staticmethod
    def _validate(profile_id, filters):
        text(profile_id, "Wishlist filter profile ID")
        if not isinstance(filters, GearFilters):
            raise ValueError("Invalid wishlist filters.")
        filters.validate()

    def get(self, profile_id):
        text(profile_id, "Wishlist filter profile ID")
        return self.profiles.get(profile_id, GearFilters())

    def save(self, profile_id, filters):
        if self.error:
            raise ValueError(self.error)
        self._validate(profile_id, filters)
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            self.error = "Wishlist filter preferences changed outside this preview. Reopen before saving filters; external changes preserved."
            raise ValueError(self.error)
        if self.profiles.get(profile_id) == filters:
            return
        profiles = {**self.profiles, profile_id: filters}
        if len(profiles) > 1000:
            raise ValueError("Too many saved wishlist filter profiles.")
        write_json(self.path, {"version": 2, "profiles": {key: asdict(value) for key, value in profiles.items()}})
        self.profiles = profiles
        self.loaded_bytes = self.path.read_bytes()
