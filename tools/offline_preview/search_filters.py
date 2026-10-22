"""Private offline search preferences, separate from profiles and item records."""

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

from catalogue import EQUIP_SLOTS
from item_values import count
from item_stock import OWNERSHIP_FILTERS
from model import text
from storage import write_json


SCOPES = ("All", "Gear", "Material", "Other")


@dataclass(frozen=True)
class SearchFilters:
    category: str = "All"
    equip_slot: str | None = None
    item_type: str | None = None
    min_level: int | None = None
    max_level: int | None = None
    include_unknown_levels: bool = True
    use_character_level: bool = False
    ownership: str = "All"

    def validate(self, scope):
        if self.ownership not in OWNERSHIP_FILTERS:
            raise ValueError("Choose All, Owned, Not owned or Unknown.")
        if scope not in SCOPES or self.category not in SCOPES or (scope != "All" and self.category != scope):
            raise ValueError("Invalid item search category.")
        if self.equip_slot is not None and (self.equip_slot not in (*EQUIP_SLOTS, "Unknown")
                                           or self.category not in ("All", "Gear")):
            raise ValueError("Invalid item search slot.")
        if self.item_type is not None:
            text(self.item_type, "Item search type", 40)
        for level in (self.min_level, self.max_level):
            if level is not None:
                count(level, "Required level filter", 0, 1000)
        if type(self.include_unknown_levels) is not bool or type(self.use_character_level) is not bool:
            raise ValueError("Item search switches must be on or off.")
        # The manual maximum is dormant while following the character's level.
        if (not self.use_character_level and self.min_level is not None and self.max_level is not None
                and self.min_level > self.max_level):
            raise ValueError("Minimum required level must not exceed maximum required level.")

    @classmethod
    def from_dict(cls, value, scope):
        if not isinstance(value, dict):
            raise ValueError("Invalid saved item search filters.")
        try:
            result = cls(**value)
        except TypeError as exc:
            raise ValueError("Invalid saved item search fields.") from exc
        result.validate(scope)
        return result


class SearchFilterStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "item_search_filters.json"
        self.profiles = {}
        self.loaded_bytes = None
        self.error = ""
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved item search filters are too large.")
            self.loaded_bytes = self.path.read_bytes()
            payload = json.loads(self.loaded_bytes)
            if (not isinstance(payload, dict) or set(payload) != {"version", "profiles"}
                    or type(payload["version"]) is not int or payload["version"] not in (1, 2)
                    or not isinstance(payload["profiles"], dict) or len(payload["profiles"]) > 1000):
                raise ValueError("Unsupported item search preferences.")
            parsed = {}
            for profile_id, scopes in payload["profiles"].items():
                text(profile_id, "Search profile ID")
                if not isinstance(scopes, dict) or not set(scopes) <= set(SCOPES):
                    raise ValueError("Invalid saved item search scopes.")
                parsed[profile_id] = {scope: SearchFilters.from_dict(value, scope) for scope, value in scopes.items()}
            self.profiles = parsed
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"{exc} Original preferences preserved; saving is disabled."

    def get(self, profile_id, scope):
        text(profile_id, "Search profile ID")
        if scope not in SCOPES:
            raise ValueError("Invalid item search scope.")
        return self.profiles.get(profile_id, {}).get(scope, SearchFilters(category=scope))

    def save(self, profile_id, scope, filters):
        if self.error:
            raise ValueError(self.error)
        text(profile_id, "Search profile ID")
        if not isinstance(filters, SearchFilters):
            raise ValueError("Invalid item search filters.")
        filters.validate(scope)
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            self.error = "Item search preferences changed outside this preview. Reopen before saving; external changes preserved."
            raise ValueError(self.error)
        if self.profiles.get(profile_id, {}).get(scope) == filters:
            return
        profiles = {key: dict(value) for key, value in self.profiles.items()}
        profiles.setdefault(profile_id, {})[scope] = replace(filters)
        if len(profiles) > 1000:
            raise ValueError("Too many saved search profiles.")
        payload = {"version": 2, "profiles": {key: {name: asdict(value) for name, value in scopes.items()}
                                              for key, scopes in profiles.items()}}
        write_json(self.path, payload)
        self.profiles = profiles
        self.loaded_bytes = self.path.read_bytes()
