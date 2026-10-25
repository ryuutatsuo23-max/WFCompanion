"""Versioned, read-only auction observations; no game APIs or save execution."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

MAX_INTEGER = 2**53 - 1
MAX_BYTES = 4 * 1024 * 1024
MISSING = {"unknown", "unavailable", "restricted", "error"}


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise ValueError("Unexpected or missing contract fields")


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ValueError("Expected a bounded integer")


def _text(value):
    if (type(value) is not str or not value.strip() or len(value) > 160
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Expected bounded printable text")


def field(value, kind="integer", minimum=0):
    """Validate a status/value pair without turning absent or restricted into zero."""
    _keys(value, "status value")
    status = value["status"]
    if type(status) is not str:
        raise ValueError("Invalid field status")
    if status == "observed":
        if kind == "text":
            _text(value["value"])
        else:
            _integer(value["value"], minimum)
    elif status not in MISSING or value["value"] is not None:
        raise ValueError("Missing fields require a missing status and null value")


def observed(value):
    return {"status": "observed", "value": value}


def unknown(status="unknown"):
    return {"status": status, "value": None}


def validate(document):
    """Return a detached valid document, or reject the whole import atomically."""
    _keys(document, "schema producer snapshots")
    if type(document["schema"]) is not int or document["schema"] != 1:
        raise ValueError("Unsupported auction schema")
    if document["producer"] != "WFAuctionHouse":
        raise ValueError("Unexpected producer")
    snapshots = document["snapshots"]
    if type(snapshots) is not list or len(snapshots) > 20:
        raise ValueError("Expected at most 20 snapshots")
    ids = set()
    for snap in snapshots:
        _keys(snap, "id evidence api client market observedAt coverage returnedCount reportedTotal rows")
        _text(snap["id"])
        if snap["id"] in ids:
            raise ValueError("Duplicate snapshot ID")
        ids.add(snap["id"])
        if snap["evidence"] not in ("synthetic", "live_observation"):
            raise ValueError("Invalid evidence label")
        if snap["api"] not in ("legacy_list", "modern_item", "modern_commodity"):
            raise ValueError("Unsupported source API")
        _keys(snap["client"], "version build interface")
        field(snap["client"]["version"], "text")
        for key in ("build", "interface"):
            field(snap["client"][key], minimum=1)
        _keys(snap["market"], "realm faction marketID")
        for item in snap["market"].values():
            field(item, "text")
        field(snap["observedAt"], minimum=1)
        field(snap["returnedCount"])
        field(snap["reportedTotal"])
        if snap["coverage"] not in ("returned_rows", "partial", "unknown"):
            raise ValueError("Invalid coverage")
        rows = snap["rows"]
        if type(rows) is not list or len(rows) > 500:
            raise ValueError("Expected at most 500 rows per snapshot")
        count = snap["returnedCount"]["value"]
        total = snap["reportedTotal"]["value"]
        if count is not None and len(rows) > count:
            raise ValueError("Rows exceed returned count")
        if count is not None and total is not None and total < count:
            raise ValueError("Reported total is smaller than returned count")
        if snap["coverage"] == "returned_rows" and count != len(rows):
            raise ValueError("Returned-row coverage requires every returned row")
        row_ids = set()
        for row in rows:
            _keys(row, "index itemID name itemLevel itemSuffix battlePetSpeciesID auctionID quantity minimumBidCopper minimumIncrementCopper currentBidCopper buyoutCopper unitPriceCopper timeLeftBand timeLeftSeconds")
            _integer(row["index"], 1)
            if row["index"] in row_ids or (count is not None and row["index"] > count):
                raise ValueError("Invalid or duplicate row index")
            row_ids.add(row["index"])
            for key, value in row.items():
                if key != "index":
                    field(value, "text" if key == "name" else "integer",
                          -MAX_INTEGER if key == "itemSuffix" else
                          1 if key in ("itemID", "quantity", "auctionID") else 0)
            if row["timeLeftBand"]["value"] not in (None, 1, 2, 3, 4):
                raise ValueError("Invalid time-left band")
            # Commodity unit price is not a listing buyout. Never blend semantics.
            forbidden = ("minimumBidCopper", "minimumIncrementCopper", "currentBidCopper", "buyoutCopper") if snap["api"] == "modern_commodity" else ("unitPriceCopper",)
            if any(row[key]["status"] == "observed" for key in forbidden):
                raise ValueError("Prices do not match the source API semantics")
    return deepcopy(document)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def load(path):
    """Read bounded normalized JSON only. Never execute Lua SavedVariables."""
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Auction input exceeds 4 MiB")
    try:
        return validate(json.loads(payload, object_pairs_hook=_unique_object))
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid auction JSON") from exc


def unit_buyout(row, api):
    """Exact rational copper, no float rounding; None means not known/applicable."""
    if api == "modern_commodity":
        value = row["unitPriceCopper"]["value"]
        return Fraction(value) if value is not None else None
    buyout, quantity = row["buyoutCopper"]["value"], row["quantity"]["value"]
    return Fraction(buyout, quantity) if buyout and quantity else None


def browse(document, snapshot_id, search="", now=None):
    """One explicit snapshot at a time: never merge pages, realms or variants."""
    document = validate(document)
    snap = next((s for s in document["snapshots"] if s["id"] == snapshot_id), None)
    if snap is None:
        raise ValueError("Select an existing snapshot")
    if now is not None:
        _integer(now, 1)
    stamp = snap["observedAt"]["value"]
    age = now - stamp if now is not None and stamp is not None and now >= stamp else None
    query = search.strip().casefold()
    results = []
    for row in snap["rows"]:
        if query and query not in str(row["itemID"]["value"]) and query not in (row["name"]["value"] or "").casefold():
            continue
        price = unit_buyout(row, snap["api"])
        results.append({"row": row, "unitBuyoutCopper": str(price) if price is not None else None,
                        "availability": "unknown", "expiry": "unknown"})
    return {"snapshot": snap, "ageSeconds": age, "results": results,
            "state": "saved_observation", "compatibility": "unverified"}
