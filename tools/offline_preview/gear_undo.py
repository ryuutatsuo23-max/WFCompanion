"""Durable removal recovery, independent of wishlist/profile/editor saves."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from gear import GearItem, GearWishlist
from model import text
from storage import write_json


@dataclass(frozen=True)
class RemovedGoal:
    index: int
    item: GearItem

    def validate(self):
        if type(self.index) is not int or not 0 <= self.index < 500:
            raise ValueError("Invalid removed goal position.")
        if not isinstance(self.item, GearItem):
            raise ValueError("Invalid removed gear goal.")
        self.item.validate()

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"index", "item"}:
            raise ValueError("Invalid saved removal recovery.")
        item = GearWishlist.from_dict({"entries": [value["item"]]}).entries[0]
        result = cls(value["index"], item)
        result.validate()
        return result


class GearUndoStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / "gear_undo.json"
        self.records = {}
        self.loaded_bytes = None
        self.error = ""
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved removal recovery is too large.")
            self.loaded_bytes = self.path.read_bytes()
            payload = json.loads(self.loaded_bytes)
            if (not isinstance(payload, dict) or set(payload) != {"version", "characters"}
                    or type(payload["version"]) is not int or payload["version"] != 1):
                raise ValueError("Unsupported removal recovery format.")
            raw = payload["characters"]
            if not isinstance(raw, dict) or len(raw) > 100:
                raise ValueError("Invalid removal recovery characters.")
            parsed = {key: RemovedGoal.from_dict(value) for key, value in raw.items()}
            self._validate(parsed)
            self.records = parsed
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"{exc} Original recovery file preserved; saving recovery is disabled."

    @staticmethod
    def _validate(records):
        if not isinstance(records, dict) or len(records) > 100:
            raise ValueError("Keep removal recovery for up to 100 characters.")
        for profile_id, record in records.items():
            text(profile_id, "Removal recovery character ID")
            if not isinstance(record, RemovedGoal):
                raise ValueError("Invalid removal recovery record.")
            record.validate()

    def save(self, records):
        if self.error:
            raise ValueError(self.error)
        self._validate(records)
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.loaded_bytes:
            self.error = "Removal recovery changed outside this preview. Reopen before saving recovery; external changes preserved."
            raise ValueError(self.error)
        if records == self.records:
            return
        write_json(self.path, {"version": 1, "characters": {key: asdict(value) for key, value in records.items()}})
        self.records = deepcopy(records)
        self.loaded_bytes = self.path.read_bytes()
