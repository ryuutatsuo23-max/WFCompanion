"""Read-only synthetic WFAuctionHouse schema-1 JSON adapter; no live save support.

Explicit file selection only. Currency is copper. Each market entry is one
snapshot, never a union of queries or realms. No Lua evaluation or file writes.
"""
import json
from pathlib import Path

LIMIT = 2**53 - 1
ROW_FIELDS = ("itemID name itemLevel itemSuffix battlePetSpeciesID auctionID quantity "
              "minimumBidCopper minimumIncrementCopper currentBidCopper buyoutCopper "
              "unitPriceCopper timeLeftBand timeLeftSeconds").split()


def _keys(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys.split()):
        raise ValueError("Unexpected or missing Auction House fields")


def _number(value, minimum=0):
    if type(value) is not int or not minimum <= value <= LIMIT:
        raise ValueError("Invalid auction integer")


def _text(value):
    if (type(value) is not str or not value.strip() or len(value) > 160
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Invalid auction text")


def _field(pair, text=False, minimum=0):
    _keys(pair, "status value")
    if pair["status"] == "observed":
        if text:
            _text(pair["value"])
        else:
            _number(pair["value"], minimum)
        return pair["value"]
    if pair["status"] not in ("unknown", "unavailable", "restricted", "error") or pair["value"] is not None:
        raise ValueError("Invalid auction field status")
    return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate auction JSON key")
        result[key] = value
    return result


def read_market(path: Path) -> dict:
    """Accept explicitly selected *.json synthetic exports; raise on invalid input."""
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("Select a synthetic WFAuctionHouse schema-1 JSON export; live Lua saves are unsupported")
    with path.open("rb") as stream:
        payload = stream.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("Auction export exceeds 4 MiB")
    try:
        doc = json.loads(payload, object_pairs_hook=_object)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid auction JSON") from exc
    _keys(doc, "schema producer snapshots")
    if type(doc["schema"]) is not int or doc["schema"] != 1 or doc["producer"] != "WFAuctionHouse":
        raise ValueError("Unsupported Auction House schema or producer")
    if type(doc["snapshots"]) is not list or len(doc["snapshots"]) > 20:
        raise ValueError("Expected at most 20 auction snapshots")
    markets, ids = [], set()
    notes = ["SYNTHETIC PREVIEW ONLY — no supported live auction capture exists.",
             "All currency values are copper. Saved rows do not establish current availability or expiry.",
             "Each entry is one snapshot, never a complete-market guarantee. Unknown market identities remain separate.",
             "Bid is observed current bid only; minimum bid is not substituted. Zero buyout means no buyout."]
    for snap in doc["snapshots"]:
        _keys(snap, "id evidence api client market observedAt coverage returnedCount reportedTotal rows")
        _text(snap["id"])
        if snap["id"] in ids:
            raise ValueError("Duplicate auction snapshot")
        ids.add(snap["id"])
        if snap["evidence"] != "synthetic":
            raise ValueError("Only synthetic auction fixtures are supported; live capture remains unverified")
        api = snap["api"]
        if api not in ("legacy_list", "modern_item", "modern_commodity"):
            raise ValueError("Unknown auction API")
        _keys(snap["client"], "version build interface")
        version = _field(snap["client"]["version"], text=True)
        build = _field(snap["client"]["build"], minimum=1)
        interface = _field(snap["client"]["interface"], minimum=1)
        _keys(snap["market"], "realm faction marketID")
        market = {key: _field(value, text=True) for key, value in snap["market"].items()}
        stamp = _field(snap["observedAt"], minimum=1)
        count, total = _field(snap["returnedCount"]), _field(snap["reportedTotal"])
        coverage = snap["coverage"]
        if coverage not in ("returned_rows", "partial", "unknown"):
            raise ValueError("Invalid auction coverage")
        rows = snap["rows"]
        if type(rows) is not list or len(rows) > 500:
            raise ValueError("Expected at most 500 rows")
        if ((count is not None and len(rows) > count)
                or (count is not None and total is not None and total < count)
                or (coverage == "returned_rows" and count != len(rows))):
            raise ValueError("Inconsistent auction coverage/counts")
        output, row_ids = [], set()
        for row in rows:
            _keys(row, "index " + " ".join(ROW_FIELDS))
            _number(row["index"], 1)
            if row["index"] in row_ids or (count is not None and row["index"] > count):
                raise ValueError("Duplicate or invalid auction row index")
            row_ids.add(row["index"])
            values = {key: _field(row[key], text=key == "name", minimum=
                      -LIMIT if key == "itemSuffix" else 1 if key in ("itemID", "quantity", "auctionID") else 0)
                      for key in ROW_FIELDS}
            if values["timeLeftBand"] not in (None, 1, 2, 3, 4):
                raise ValueError("Invalid auction time-left band")
            forbidden = ("minimumBidCopper", "minimumIncrementCopper", "currentBidCopper", "buyoutCopper") if api == "modern_commodity" else ("unitPriceCopper",)
            if any(values[key] is not None for key in forbidden):
                raise ValueError("Mixed auction price semantics")
            buyout, quantity = values["buyoutCopper"], values["quantity"]
            unit = values["unitPriceCopper"] if api == "modern_commodity" else None
            if api != "modern_commodity" and buyout and quantity:
                if buyout % quantity == 0:
                    unit = buyout // quantity
                else:
                    notes.append(f"{snap['id']} row {row['index']}: fractional unit buyout omitted; listing total retained.")
            output.append({"id": json.dumps([snap["id"], row["index"]], ensure_ascii=True),
                           "item_id": values["itemID"], "name": values["name"],
                           "quantity": quantity, "bid": values["currentBidCopper"],
                           "buyout": buyout, "unit_price": unit})
        context = " / ".join(f"{key}={value if value is not None else 'Unknown'}" for key, value in market.items())
        notes.append(f"{snap['id']}: synthetic client {version or 'Unknown'}, build {build or 'Unknown'}, interface {interface or 'Unknown'}; compatibility unverified. Returned={count}, reported total={total}.")
        markets.append({"key": snap["id"], "label": f"SYNTHETIC — {context} — {snap['id']}",
                        "observed_at": stamp, "coverage": coverage, "rows": output})
    return {"markets": markets, "notes": notes, "source": "WFAuctionHouse schema-1 synthetic JSON (live capture unsupported)"}
