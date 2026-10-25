"""Standalone adapter tests using temporary synthetic files only."""
import json
from pathlib import Path
import tempfile
import unittest
from wfauction_reader import read_market, ROW_FIELDS


def fixture(api="legacy_list"):
    def field(v=None):
        return {"status": "unknown" if v is None else "observed", "value": v}
    row = {k: field() for k in ROW_FIELDS}
    row.update(index=1, itemID=field(2770), name=field("Synthetic Ore"), quantity=field(3))
    row["unitPriceCopper" if api == "modern_commodity" else "buyoutCopper"] = field(100)
    return {"schema": 1, "producer": "WFAuctionHouse", "snapshots": [{
        "id": "synthetic-1", "evidence": "synthetic", "api": api,
        "client": {"version": field("1.60.1"), "build": field(70532), "interface": field(16001)},
        "market": {"realm": field("Test Realm"), "faction": field(), "marketID": field()},
        "observedAt": field(1000), "coverage": "returned_rows", "returnedCount": field(1),
        "reportedTotal": field(50), "rows": [row]}]}


class ReaderTests(unittest.TestCase):
    def read(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "WFAuctionHouse.preview.json"
            raw = json.dumps(doc).encode()
            path.write_bytes(raw)
            result = read_market(path)
            self.assertEqual(path.read_bytes(), raw)
            return result

    def test_exact_requested_shape_and_provenance(self):
        result = self.read(fixture())
        self.assertEqual(set(result), {"markets", "notes", "source"})
        market = result["markets"][0]
        self.assertEqual(set(market), {"key", "label", "observed_at", "coverage", "rows"})
        row = market["rows"][0]
        self.assertEqual(set(row), {"id", "item_id", "name", "quantity", "bid", "buyout", "unit_price"})
        self.assertEqual(row["buyout"], 100)
        self.assertIsNone(row["unit_price"])
        self.assertIn("SYNTHETIC", market["label"])
        self.assertTrue(any("fractional" in note for note in result["notes"]))

    def test_commodity_unit_and_integer_listing_unit(self):
        self.assertEqual(self.read(fixture("modern_commodity"))["markets"][0]["rows"][0]["unit_price"], 100)
        doc = fixture()
        doc["snapshots"][0]["rows"][0]["quantity"]["value"] = 2
        self.assertEqual(self.read(doc)["markets"][0]["rows"][0]["unit_price"], 50)

    def test_no_minimum_bid_fallback_and_no_buyout(self):
        doc = fixture()
        row = doc["snapshots"][0]["rows"][0]
        row["minimumBidCopper"] = {"status": "observed", "value": 5}
        row["buyoutCopper"]["value"] = 0
        result = self.read(doc)["markets"][0]["rows"][0]
        self.assertIsNone(result["bid"])
        self.assertEqual(result["buyout"], 0)
        self.assertIsNone(result["unit_price"])

    def test_reject_live_schema_mixed_prices_and_invalid_status(self):
        for mutate in (
            lambda d: d.update(schema=2),
            lambda d: d["snapshots"][0].update(evidence="live_observation"),
            lambda d: d["snapshots"][0]["rows"][0].update(unitPriceCopper={"status":"observed","value":1}),
            lambda d: d["snapshots"][0]["rows"][0].update(buyoutCopper={"status":"restricted","value":123}),
            lambda d: d["snapshots"][0].update(returnedCount={"status":"observed","value":False}),
            lambda d: d.update(snapshots=d["snapshots"]*2),
        ):
            doc = fixture()
            mutate(doc)
            with self.assertRaises(ValueError):
                self.read(doc)

    def test_empty_document_and_unsafe_inputs(self):
        self.assertEqual(self.read({"schema":1,"producer":"WFAuctionHouse","snapshots":[]})["markets"], [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            for raw in (b'{"schema":1,"schema":1}', b'WFAuctionHouseDB={}', b' '*(4*1024*1024+1)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    read_market(path)
            with self.assertRaises(ValueError):
                read_market(Path(tmp) / "WFAuctionHouse.lua")


if __name__ == "__main__":
    unittest.main()
