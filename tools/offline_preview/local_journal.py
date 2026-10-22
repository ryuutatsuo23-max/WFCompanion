"""Small guarded stores and manual auction observations; no network access."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from storage import write_json


class LocalStore:
    def __init__(self, directory, filename, default, validate):
        self.path = Path(directory).resolve() / filename
        self.error = ""
        self.original = None
        self.validate = validate
        self.data = deepcopy(default)
        try:
            if self.path.exists():
                if self.path.stat().st_size > 5_000_000:
                    raise ValueError("File exceeds size limit.")
                self.original = self.path.read_bytes()
                data = json.loads(self.original)
                validate(data)
                self.data = data
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.error = f"Original file preserved; saving disabled: {exc}"

    def save(self, data):
        if self.error:
            raise ValueError(self.error)
        self.validate(data)
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.original:
            raise ValueError("File changed outside this window. Reopen before saving.")
        write_json(self.path, data)
        self.original = self.path.read_bytes()
        self.data = deepcopy(data)


def validate_journal(data):
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("characters"), dict):
        raise ValueError("Unsupported price journal.")
    if len(data["characters"]) > 100:
        raise ValueError("Too many characters.")
    for character, records in data["characters"].items():
        if not isinstance(character, str) or not character or not isinstance(records, list) or len(records) > 10000:
            raise ValueError("Invalid journal history.")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid price record.")
            for key in ("name", "key", "market"):
                if not isinstance(record.get(key), str) or not record[key].strip() or len(record[key]) > 200:
                    raise ValueError(f"Enter a valid {key}.")
            if type(record.get("copper")) is not int or not 0 <= record["copper"] <= 10**12:
                raise ValueError("Enter a whole copper price from 0 to 1,000,000,000,000.")
            stamp = record.get("date")
            if not isinstance(stamp, str) or len(stamp) != 10 or date.fromisoformat(stamp) > date.today():
                raise ValueError("Use an observation date YYYY-MM-DD, today or earlier.")


def money(copper):
    return "Unknown" if copper is None else f"{copper // 10000}g {(copper // 100) % 100}s {copper % 100}c"


def coin_price(gold, silver, copper):
    """Blank price is unknown; blank denominations within a price are zero."""
    parts = [value.strip() for value in (gold, silver, copper)]
    if not any(parts):
        return None
    values = []
    for label, raw, limit in zip(("Gold", "Silver", "Copper"), parts, (100_000_000, 99, 99)):
        if raw and (not raw.isascii() or not raw.isdecimal() or len(raw) > 12):
            raise ValueError(f"{label} must be a whole non-negative number.")
        value = int(raw or "0")
        if value > limit:
            raise ValueError(f"{label} must be between 0 and {limit}.")
        values.append(value)
    total = values[0] * 10000 + values[1] * 100 + values[2]
    if total > 10**12:
        raise ValueError("Price exceeds the supported limit.")
    return total


def estimate(rows, records, market):
    """Exact keys only: never conflate unlinked names with linked item IDs."""
    latest = {}
    for record in records:
        if record["market"].casefold() == market.strip().casefold():
            old = latest.get(record["key"])
            if old is None or record["date"] >= old["date"]:
                latest[record["key"]] = record
    results = []
    for row in rows:
        if row.needed <= 0:
            continue
        price = latest.get(row.key)
        cost = (0 if row.remaining == 0 else
                row.remaining * price["copper"] if row.remaining is not None and price else None)
        results.append((row, price, cost))
    return results
