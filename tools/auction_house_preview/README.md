# Auction observation browser

Offline model and read-only console browser for normalized schema-1 JSON. No
dependencies beyond Python's standard library; no Lua execution, game access,
network requests, Qt changes or real-save discovery. This is an integration
adapter candidate, not a released addon or companion feature.

From `C:\Dev\WoWForever`:

```powershell
python -m unittest discover -s tests -p test_auction_house_model.py
python -m tools.auction_house_preview.browser C:\path\to\normalized.json
python -m tools.auction_house_preview.browser C:\path\to\normalized.json --snapshot capture-id --search ore
```

Supply your own normalized export explicitly. Tests construct synthetic exports
in temporary directories and remove them afterward. The first browser command
lists snapshots. The second selects exactly one snapshot and filters by item ID
or name. No merged market, cheapest-current offer, empty-market claim, inventory
replacement or buy/sell action is provided.

`model.validate(document)` validates an already decoded mapping and returns a
detached copy. `model.load(path)` reads bounded JSON. `model.browse(...)` returns
display data with cached availability/expiry always unknown. Full contract and
source evidence: `research/WFAUCTIONHOUSE_COMPANION_HANDOFF.md`.
