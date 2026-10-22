"""Offline, rebuildable SQLite/FTS5 catalogue from source-checked local facts.

No network access or game access. The database is a derived cache; private
wishlist records keep their own identity/provenance snapshot independently.
"""

from dataclasses import asdict, dataclass
from contextlib import closing
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import urlsplit

from model import text
from item_values import count, material_key


SAMPLE_PATH = Path(__file__).resolve().parent / "data" / "item_sample.json"
APPLICATION_ID = 0x574F5746
CACHE_VERSION = 3
EQUIP_SLOTS = ("Head", "Neck", "Shoulders", "Back", "Chest", "Wrists", "Hands",
               "Waist", "Legs", "Feet", "Finger", "Trinket", "One-Hand", "Two-Hand",
               "Main Hand", "Off Hand", "Ranged", "Relic", "Shirt", "Tabard")


def source_url(value):
    text(value, "Item source URL", 300)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Item sources must be public HTTPS URLs.")
    return value


def checked_date(value):
    text(value, "Item check date", 10)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use an ISO item check date.")
    except ValueError as exc:
        raise ValueError("Use an ISO item check date.") from exc


def wishlist_slots(equip_slot):
    """Convenient planning labels only; never validates class/equip eligibility."""
    if equip_slot is None:
        return ("Unspecified",)
    return {"Finger": ("Finger 1", "Finger 2"), "One-Hand": ("Main hand", "Off hand"),
            "Two-Hand": ("Main hand",), "Main Hand": ("Main hand",),
            "Trinket": ("Trinket 1", "Trinket 2"),
            "Off Hand": ("Off hand",)}.get(equip_slot, (equip_slot,))


@dataclass(frozen=True)
class CatalogueRef:
    item_id: int
    name: str
    equip_slot: str | None
    source_url: str
    checked_on: str
    sample_revision: str
    branch: str = "forever"
    locale: str = "enUS"
    variant: str = "base"
    client_build: str | None = None
    name_is_ambiguous: bool = False

    def validate(self):
        count(self.item_id, "Item ID", 1, 2_147_483_647)
        text(self.name, "Catalogue item name")
        if self.equip_slot is not None and self.equip_slot not in EQUIP_SLOTS:
            raise ValueError("Unsupported sample equipment slot.")
        # Imported base-item identities cite local capture evidence, never a website
        # that was not consulted. Public catalogue sources keep their HTTPS rule.
        if not (self.source_url == 'local-capture:WFStressProbe+DataStore'
                and self.sample_revision == 'reviewed-capture-v1'):
            source_url(self.source_url)
        checked_date(self.checked_on)
        text(self.sample_revision, "Sample revision", 40)
        if self.branch != "forever" or self.locale != "enUS" or self.variant != "base":
            raise ValueError("This sample supports Forever enUS base items only.")
        if self.client_build is not None:
            text(self.client_build, "Client build", 40)
        if type(self.name_is_ambiguous) is not bool:
            raise ValueError("Invalid item-name ambiguity flag.")


@dataclass(frozen=True)
class CatalogueItem:
    reference: CatalogueRef
    item_type: str
    required_level: int | None
    item_level: int | None
    variant_note: str
    evidence: list[dict]
    category: str = "Gear"

    def validate(self):
        self.reference.validate()
        if self.category not in ("Gear", "Material", "Other"):
            raise ValueError("Unsupported catalogue category.")
        if self.category != "Gear" and self.reference.equip_slot is not None:
            raise ValueError("Catalogue category and equip label disagree.")
        text(self.item_type, "Item type", 40)
        for value in (self.required_level, self.item_level):
            if value is not None:
                count(value, "Item level", 0, 1000)
        text(self.variant_note, "Item variant note", 180, allow_empty=True)
        if not isinstance(self.evidence, list) or not 1 <= len(self.evidence) <= 10:
            raise ValueError("Each sample item needs source evidence.")
        for entry in self.evidence:
            if not isinstance(entry, dict) or set(entry) != {"url", "checked_on", "reported_build"}:
                raise ValueError("Invalid item evidence.")
            source_url(entry["url"])
            checked_date(entry["checked_on"])
            if entry["reported_build"] is not None:
                text(entry["reported_build"], "Reported source build", 40)
        if not any(e["url"] == self.reference.source_url and e["checked_on"] == self.reference.checked_on
                   for e in self.evidence):
            raise ValueError("Primary item source must be included in the evidence.")

    @classmethod
    def from_dict(cls, data):
        try:
            values = dict(data)
            values["reference"] = CatalogueRef(**values["reference"])
            item = cls(**values)
            item.validate()
            return item
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid sample item fields.") from exc


class ItemCatalogue:
    def __init__(self, directory, sample_path=SAMPLE_PATH):
        self.path = Path(directory).resolve() / "item_catalogue.sqlite3"
        self.error = ""
        self.connection = None
        self.item_count = 0
        self._references_by_id = {}
        self._references_by_name = {}
        self.revision = ""
        self.coverage_note = "Source listings checked; game-wide completeness unverified."
        try:
            raw = Path(sample_path).read_bytes()
            if len(raw) > 50_000_000:
                raise ValueError("Item sample is too large.")
            data = json.loads(raw)
            if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] not in (1, 2, 3)
                    or not isinstance(data.get("items"), list) or not 0 <= len(data["items"]) <= 100_000):
                raise ValueError("Unsupported item sample format.")
            self.revision = text(data.get("revision"), "Sample revision", 40)
            self.coverage_note = text(data.get("coverage_note", self.coverage_note), "Coverage note", 200)
            items = [CatalogueItem.from_dict(item) for item in data["items"]]
            if any(item.reference.sample_revision != self.revision for item in items):
                raise ValueError("Sample item revision does not match its manifest.")
            if len({item.reference.item_id for item in items}) != len(items):
                raise ValueError("Duplicate sample item IDs.")
            if data["version"] >= 2:
                coverage = data.get("coverage")
                if not isinstance(coverage, list) or not coverage:
                    raise ValueError("Material source coverage is missing.")
                covered = set()
                for source in coverage:
                    source_url(source["url"])
                    ids = source["item_ids"]
                    if (not isinstance(ids, list) or len(ids) != source["item_count"]
                            or len(set(ids)) != len(ids) or any(type(i) is not int or i <= 0 for i in ids)):
                        raise ValueError("Material source coverage count disagrees.")
                    covered.update(ids)
                material_ids = {i.reference.item_id for i in items if i.category == "Material"}
                if covered != material_ids or len(material_ids) != data.get("material_union_count"):
                    raise ValueError("Catalogue does not contain the complete declared material source union.")
            if data["version"] >= 3:
                coverage = data.get("item_coverage")
                if not isinstance(coverage, list) or not coverage:
                    raise ValueError("Item source coverage is missing.")
                covered = set()
                for source in coverage:
                    source_url(source["url"])
                    ids = source["item_ids"]
                    if (not isinstance(ids, list) or len(ids) != source["item_count"]
                            or len(set(ids)) != len(ids)
                            or any(type(i) is not int or not 1 <= i <= 2_147_483_647 for i in ids)
                            or type(source.get("truncated")) is not bool):
                        raise ValueError("Item source coverage count disagrees.")
                    covered.update(ids)
                if covered != {i.reference.item_id for i in items} or len(items) != data.get("item_union_count"):
                    raise ValueError("Catalogue does not contain the complete declared item source union.")
            fingerprint = hashlib.sha256(raw).hexdigest()
            rebuild = not self.path.exists()
            if not rebuild:
                with closing(self._reader()) as existing:
                    if (existing.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                            or existing.execute("PRAGMA user_version").fetchone()[0] not in (1, 2, CACHE_VERSION)
                            or existing.execute("PRAGMA quick_check").fetchone()[0] != "ok"):
                        raise ValueError("Unrecognized or damaged catalogue database.")
                    saved_hash = existing.execute("SELECT value FROM metadata WHERE key='sample_sha256'").fetchone()
                    if saved_hash is None:
                        raise ValueError("Catalogue provenance is missing.")
                    rebuild = saved_hash[0] != fingerprint or existing.execute("PRAGMA user_version").fetchone()[0] != CACHE_VERSION
            if rebuild:
                self._build(items, fingerprint)
            self.connection = self._reader()
            self.item_count = self.connection.execute("SELECT count(*) FROM items").fetchone()[0]
            indexed = self.connection.execute("SELECT count(*) FROM item_search").fetchone()[0]
            if self.item_count != len(items) or indexed != self.item_count:
                raise ValueError("Catalogue row count does not match the sample.")
            for item in items:
                ref = item.reference
                self._references_by_id[ref.item_id] = ref
                self._references_by_name.setdefault(material_key(ref.name), []).append(ref)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            self.close()
            self.error = f"Local item search unavailable: {exc} Existing files preserved; manual entries still work."

    def _reader(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def _build(self, items, fingerprint):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        connection = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix="catalogue-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
            connection = sqlite3.connect(temporary)
            with connection:
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={CACHE_VERSION}")
                connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO metadata VALUES ('sample_sha256', ?)", (fingerprint,))
                connection.execute("CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, "
                                   "payload TEXT NOT NULL, equip_slot TEXT, item_type TEXT NOT NULL COLLATE NOCASE, required_level INTEGER)")
                connection.execute("CREATE INDEX items_category ON items(category)")
                connection.execute("CREATE INDEX items_slot ON items(equip_slot)")
                connection.execute("CREATE INDEX items_type ON items(item_type)")
                connection.execute("CREATE INDEX items_level ON items(required_level)")
                connection.execute("CREATE VIRTUAL TABLE item_search USING fts5(name, equip_slot, item_type, tokenize='unicode61 remove_diacritics 2')")
                for item in items:
                    ref = item.reference
                    connection.execute("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (ref.item_id, ref.name, item.category, json.dumps(asdict(item)),
                                        ref.equip_slot, item.item_type, item.required_level))
                    connection.execute("INSERT INTO item_search(rowid, name, equip_slot, item_type) VALUES (?, ?, ?, ?)",
                                       (ref.item_id, ref.name, ref.equip_slot or item.category, item.item_type))
            connection.close()
            connection = None
            # This cache contains only bundled catalogue facts, never personal goals.
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_name("item_catalogue.previous.sqlite3"))
            os.replace(temporary, self.path)
        finally:
            if connection is not None:
                connection.close()
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def filter_options(self, category="All"):
        """Recorded labels only. Missing gear slots differ from non-equipment."""
        if self.error or self.connection is None:
            raise ValueError(self.error or "Item catalogue is closed.")
        if category not in ("All", "Gear", "Material", "Other"):
            raise ValueError("Choose All, Gear, Material or Other.")
        clause, parameters = ("1=1", ()) if category == "All" else ("category=?", (category,))
        types = tuple(row[0] for row in self.connection.execute(
            "SELECT DISTINCT item_type FROM items WHERE " + clause + " ORDER BY item_type COLLATE NOCASE", parameters))
        slots = ()
        if category in ("All", "Gear"):
            recorded = {row[0] for row in self.connection.execute("SELECT DISTINCT equip_slot FROM items WHERE category='Gear'")}
            slots = tuple(slot for slot in EQUIP_SLOTS if slot in recorded)
            if None in recorded:
                slots += ("Unknown",)
        return {"slots": slots, "types": types}

    def stock_references(self, records):
        """Only catalogue identities potentially mentioned in recorded inventory."""
        if self.error or self.connection is None:
            raise ValueError(self.error or "Item catalogue is closed.")
        result = {}
        for name, ref in records:
            for candidate in self._references_by_name.get(material_key(name), ()):
                result[candidate.item_id] = candidate
            if ref is not None and ref.item_id in self._references_by_id:
                result[ref.item_id] = self._references_by_id[ref.item_id]
        return list(result.values())

    def ownership_references(self):
        """All indexed identities, including items absent from a complete scan."""
        if self.error or self.connection is None:
            raise ValueError(self.error or "Item catalogue is closed.")
        return tuple(self._references_by_id.values())

    def search(self, query="", limit=50, category="All", *, equip_slot=None, item_type=None,
               min_level=None, max_level=None, include_unknown_levels=True, item_ids=None, exclude_item_ids=False):
        if self.error or self.connection is None:
            raise ValueError(self.error or "Item catalogue is closed.")
        query = text(query, "Item search", 100, allow_empty=True)
        count(limit, "Search result limit", 1, 100)
        if category not in ("All", "Gear", "Material", "Other"):
            raise ValueError("Choose All, Gear, Material or Other.")
        if equip_slot is not None and equip_slot not in (*EQUIP_SLOTS, "Unknown"):
            raise ValueError("Choose a recorded equipment slot or Unknown.")
        if item_type is not None:
            item_type = text(item_type, "Item type filter", 40)
        for value, label in ((min_level, "Minimum required level"), (max_level, "Maximum required level")):
            if value is not None:
                count(value, label, 0, 1000)
        if min_level is not None and max_level is not None and min_level > max_level:
            raise ValueError("Minimum required level must not exceed maximum required level.")
        if type(include_unknown_levels) is not bool:
            raise ValueError("Include unknown levels must be on or off.")
        clauses, parameters = [], []
        if type(exclude_item_ids) is not bool:
            raise ValueError("Item ID exclusion must be on or off.")
        if item_ids is not None:
            if not isinstance(item_ids, (set, frozenset, list, tuple)) or len(item_ids) > 100_000:
                raise ValueError("Invalid item ID selection.")
            for item_id in item_ids:
                count(item_id, "Selected item ID", 1, 2_147_483_647)
            # JSON binds one validated ID collection without a SQL variable limit.
            clauses.append("items.item_id " + ("NOT IN" if exclude_item_ids else "IN") + " (SELECT value FROM json_each(?))")
            parameters.append(json.dumps(sorted(set(item_ids))))
        if category != "All":
            clauses.append("items.category=?")
            parameters.append(category)
        if equip_slot == "Unknown":
            clauses.append("items.category='Gear' AND items.equip_slot IS NULL")
        elif equip_slot is not None:
            clauses.append("items.equip_slot=?")
            parameters.append(equip_slot)
        if item_type is not None:
            clauses.append("items.item_type=? COLLATE NOCASE")
            parameters.append(item_type)
        levels, level_parameters = [], []
        for value, comparison in ((min_level, ">="), (max_level, "<=")):
            if value is not None:
                levels.append("items.required_level" + comparison + "?")
                level_parameters.append(value)
        if levels:
            level_clause = " AND ".join(levels)
            clauses.append("(items.required_level IS NULL OR (" + level_clause + "))" if include_unknown_levels else "(" + level_clause + ")")
            parameters.extend(level_parameters)
        elif not include_unknown_levels:
            clauses.append("items.required_level IS NOT NULL")
        clause = " AND ".join(clauses) or "1=1"
        if query.isascii() and query.isdecimal():
            if int(query) > 2_147_483_647:
                return []
            rows = self.connection.execute("SELECT payload FROM items WHERE " + clause + " AND item_id=? LIMIT ?", (*parameters, int(query), limit))
        elif not query:
            rows = self.connection.execute("SELECT payload FROM items WHERE " + clause + " ORDER BY name COLLATE NOCASE, item_id LIMIT ?", (*parameters, limit))
        else:
            # Treat user text as literal word prefixes, never FTS operators or SQL.
            tokens = re.findall(r"[^\W_]+", query, re.UNICODE)
            if not tokens:
                return []
            match = " AND ".join('"' + token + '"*' for token in tokens)
            rows = self.connection.execute("SELECT items.payload FROM item_search JOIN items ON items.item_id=item_search.rowid "
                                           "WHERE " + clause + " AND item_search MATCH ? ORDER BY bm25(item_search), items.name COLLATE NOCASE, items.item_id LIMIT ?", (*parameters, match, limit))
        return [CatalogueItem.from_dict(json.loads(row[0])) for row in rows]

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._references_by_id.clear()
        self._references_by_name.clear()


def load_reference(value):
    return CatalogueRef(**value) if value is not None else None


def validate_reference(name, reference):
    if reference is not None:
        if not isinstance(reference, CatalogueRef):
            raise ValueError("Invalid item reference.")
        reference.validate()
        if material_key(name) != material_key(reference.name):
            raise ValueError("The item name differs from its catalogue reference.")


def item_key(name, reference=None):
    if reference is None:
        return material_key(name)
    return f"item:{reference.branch}:{reference.locale}:{reference.variant}:{reference.item_id}".casefold()


def item_aliases(records):
    aliases = {}
    for name, reference in records:
        if reference is not None:
            aliases.setdefault(material_key(name), set()).add(item_key(name, reference))
            if reference.name_is_ambiguous:
                aliases[material_key(name)].add("ambiguous-name")
    return aliases


def resolved_key(name, reference, aliases):
    if reference is not None:
        return item_key(name, reference)
    matches = aliases.get(material_key(name), set())
    return next(iter(matches)) if len(matches) == 1 else material_key(name)


def unique_items(records, label):
    """Allow distinct IDs with a shared name; reject duplicate/ambiguous totals."""
    keys, names = set(), {}
    for name, reference in records:
        key, normalized = item_key(name, reference), material_key(name)
        if key in keys or (normalized in names and (reference is None or names[normalized] is None)):
            raise ValueError(f"Duplicate or ambiguous {label}. Select the existing entry or choose an exact item ID.")
        keys.add(key)
        names[normalized] = reference


def display_name(name, reference):
    return f"{name} · #{reference.item_id}" if reference is not None else name
