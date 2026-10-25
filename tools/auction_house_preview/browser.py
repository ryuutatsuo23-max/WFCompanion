"""Read-only console browser for an explicitly selected normalized JSON export."""
import argparse
import json
from .model import browse, load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--snapshot", help="Exact snapshot ID; omit to list snapshots")
    parser.add_argument("--search", default="", help="Item ID or name substring")
    args = parser.parse_args()
    try:
        document = load(args.path)
        result = (browse(document, args.snapshot, args.search) if args.snapshot else
                  [{"id": s["id"], "market": s["market"], "observedAt": s["observedAt"],
                    "evidence": s["evidence"], "coverage": s["coverage"], "rows": len(s["rows"])}
                   for s in document["snapshots"]])
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Auction input unavailable: {exc}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
