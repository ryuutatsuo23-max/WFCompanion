# Forever Storage — tester notes

October 23, 2026 · Storage 0.7.0 · Local test candidate, not a public release.
Baseline: WoW Forever Beta 1.60.1, build 70532, interface 16001.

## Known limitations

- Actions are unavailable during combat or for locked/unreadable slots; no actions
  are queued for later. Specialized interactions may require Native UI.
- Counts can briefly lag while observations refresh. Report persistent differences
  or repeated need to press Refresh before an action.
- Junk sales are manual, at most 12 gray stacks per confirmation; favorites are kept.
- Guild items, logs and notes are read-only and session-only. Use Native UI for
  transfers, gold, permissions and editing notes. Both windows may be visible.
- Log and Info require readable item tabs; Money Log is requested separately.
  Missing data means unavailable, not a confirmed empty vault or zero balance.
- Other bag replacements have not been broadly tested; start with them disabled.

## Confirmed by the user in Beta

Sampled item use without a blocked popup, movement/splitting, bank transfers,
cached bank/reload behavior, sliders/opacity, vendor tests and the fix for native
bags opening at vendors. The custom guild window opens with unavailable access.
Alt separation, an unopened alt bank and the saved main's read-only view were
also confirmed. These checks do not prove every count or every protected action.

## Still to test

- New Guild lock/settings and Log, Money Log and Info tabs.
- Readable guild item tabs and permission changes; the current tester has no
  item-tab access. No purchase or guild gold transfer is needed for these checks.
- Bank-slot purchase confirmation/cancellation and equipping bags.
- Broader character, addon and rapid-action combinations.

Use FEEDBACK.md and include the package revision: development builds currently
share version 0.7.0. Do not post full saved variables or your WTF folder publicly.
