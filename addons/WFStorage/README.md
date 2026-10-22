# Forever Storage 0.7.0

The renamed Bags & Bank addon. Requires Forever Core 0.7.0 / API 1 as a separate
installed addon (`WFCore`). Both folders must be enabled. B and `/wfstorage` open
Storage; `/wfbags` and `/wf` remain compatibility aliases. Core alone does not bind B.

Settings and observations stay in WFCoreDB under the existing keys. No new
SavedVariables file is introduced, and no character data is renamed or migrated.
The split has offline verification only; no stress-client installation was changed.



## Interactive inventory (0.5.0)

Opening the bank opens separate WFCore bags and bank windows. The native bank
is visually masked without hiding its root frame (its OnHide closes the session).
Native controls are restored when banking ends or combat starts.

- Right-click a current live item to use/equip it, or transfer it while banking.
- Left-click picks up a live item; Shift+left-click opens stack splitting.
- Alt+left-click toggles favorites. Saved character and cached bank views stay read-only.
- The header Sort button invokes native bag sorting; the bank has its own Sort button.
  Display order in settings changes presentation only.
- Settings offer explicit choices and percentage sliders (background 50–100%, scale 70–130%).
  Hover controls for help. Native UI in Inventory settings toggles normal bags both ways.
- The bank Native UI button provides access to purchases and special native controls.

Actions revalidate the current item and block stale views, locked items and combat.
Merchant, trade, mail and auction interactions use the native UI fallback. Hidden
empty cells are not drop targets; use Native UI for precise empty-slot placement.
The offline preview simulates actions only. Live interaction verification is pending.
Inventory schema 2 is unchanged; the producer addonVersion is now 0.5.0.

## Inventory schema 2 (0.4.0)

See the [producer handoff](../../research/WFCORE_INVENTORY_V2_HANDOFF.md) for exact
fields, evidence, preservation rules and the pending in-game checklist. New
snapshots distinguish observed, positively corroborated empty, and unknown slots.
Only complete scans replace latest; partial/failed attempts preserve earlier data.
The envelope remains schema 1 with inventorySchema=2. Previous schema-1 observations
are retained, not relabelled. Companion validation is handled separately and has
not been updated here. Current-build live validation remains pending.

## Saved characters, ages and favorites

Use **Characters** to choose a saved character; **Current** returns to the logged-in
character. Saved views are labelled in the heading. Browsing never changes the
collector's owner. **View age** updates age labels without scanning an alt;
**Saved view** cannot open or manipulate that character's bags. Characters appear
after they have logged in with WFCore enabled. The picker shows the realm; hover
for the full name and GUID to distinguish identical names. Six fit per page.

Bags and bank each show their latest snapshot age. Closed banks and other
characters' banks are labelled cached. Unvisited banks stay unobserved; missing
timestamps and clock mismatch remain explicit. Ages update on UI refresh/actions,
not per-frame polling. Hover an item for its recorded date and last-seen age.

Alt+left-click an observed item to toggle a gold asterisk favorite. Favorites are
per character and item ID, so all observed stacks of that item are marked. Use
**Favorites** to filter, and click again to show all items. Marks persist through
normal WoW saves, even when the item is no longer observed. They do not infer an
owned count, move items or protect items from sale in other addons. Unknown slots
cannot be marked. Preferences live in settings, separate from observations.

Offline: switch synthetic characters once to populate the picker, open/close the
bank, then use **Age +1h**. Browse the first character while the second is active,
mark items, test Favorites and return to Current. Reload source resets fixtures.

Settings can now be dragged by its title area and remembers its own position.
For development without WoW, use the separate
[offline test bench](../../tools/addon_preview/README.md). It executes this Lua
with synthetic APIs and data; game-specific verification still requires WoW.

## Visual inventory update

The default is now an icon grid with count overlays and B (bags) / K (bank) badges.
Hover for the name, location, count and observation date. Use the cog to choose:

- Appearance: Grid/List, Slate/Warm/Midnight theme, 85/95/100% background opacity,
  32/40/48-pixel icons, 6/8/10 columns, 12/14/16-point text, 85/100/115% scale.
- Inventory: Slots/Name/Count display order, unresolved rows, scan details,
  poor-quality dimming, position lock, and the existing B shortcut.

Grid pages show up to four rows; list pages show ten items. Short views shrink.
Background opacity leaves item/text opacity unchanged. Poor-quality dimming is
optional and never means an item should be sold. Unknown quality uses a neutral
border. Display sorting moves no items and does not combine stack observations.
Drag to remember the window position. Settings stays clamped to the screen, and
the window scale is capped for screen fit. Font size changes item labels/counts;
window scale enlarges all controls.

Existing settings and observations are retained; `largeText` remains a fallback
until a text-size preference is selected. Snapshot schema stays 1; 0.1.0–0.3.0
producers are accepted by the companion decoder. New scans may include a guarded
quality value. Historical observations are not rewritten.

The [reference review](../../research/INVENTORY_UI_REFERENCES_2026-10-22.md) records
all supplied examples and the boundaries of this original implementation. No addon
code/assets were copied. Item use and movement still go through **Normal bags**.

Live checks: reload when convenient, open B, inspect Grid and List with all three
themes, change icon/text size, search, change display order, reopen the cog, move
and lock the window, and verify bank history. Reload to check preference retention.
No game launch/reload is performed by installation.

## Earlier compact inventory and B shortcut

The window is 540 UI units wide and fits 4–10 rows before paging, shrinking for
short inventories. The settings cog provides larger item text, unresolved-slot
visibility, 85/100/115% window scale and an optional B shortcut. Preferences live
only in WFCoreDB. Screen-size limits can cap the selected scale.

**B** toggles WFCore through a session-only binding override; the original saved
binding is unchanged. Turn the shortcut off in Settings to restore the underlying
B action. Binding updates wait until combat ends. `/wf` remains available.
Typing into a focused text box remains normal text input. Shift-B and other saved
bindings are not overridden. The named WFCoreInventoryToggle button is the binding
target; Bindings.lua uses the client's SetOverrideBindingClick API.

**Normal bags** opens the game's bag UI for item use, equipment changes and dragging.
WFCore rows remain observations, not actionable item buttons: this replaces the
default B viewer, not all of Bagnon's item-management features. Bank interaction
continues through the normal bank window. The shared BagBrother dependency and all
Bagnon SavedVariables are preserved when moving Bagnon's four addon folders out of
AddOns for this switch. Restart the client normally after that folder change.

This revision retains schema 1 and accepts old 0.1.0/0.1.1 observations. Test B twice,
typing B in chat/search, Settings, Normal bags, bank caching and alt ownership after
restart. Offline tests do not establish live key dispatch or combat behaviour.

Independent in-game inventory viewer. No probe, DataStore, companion or other
addon is required. Source only: this task does not install or enable it.

After a separately authorized installation, `/wf` or `/wfbags` toggles the window.
Select All, Bags or Bank; search by item name/ID; use Previous/Next for more slots.
Hover a row for item information and the observation timestamp. Text size toggles
larger row labels. Drag the window to move it; X or `/wf` closes it. Escape in the
search field only releases focus, so NPC dialogue Escape does not close WFCore. Refresh
requests a new bag scan and a bank scan only if the bank is open. The normal bag
and bank windows remain available for moving, equipping or using items. This first
module is a read-only unified viewer, with no sorting, selling, transfers or hooks.
Names missing from the item cache fall back to item IDs until a later refresh.

Open the character bank normally to observe it. Closed-bank contents are cached
history. Account/guild banks, mail and equipped gear are outside this module.
Unknown slots may be empty or inaccessible; only the new explicit, corroborated
empty predicate can establish an empty slot. Confirmed empty slots stay hidden.
They are hidden by default; **Show unresolved slots** reveals them. The toggle is
saved independently of observations. Full first/last character names appear in
the heading. The keyring is carried storage: the extracted client declares
`Enum.BagIndex.Keyring = -1`; collection now requires the global constant and enum
to agree. Its unresolved slots remain in observations, even while hidden in the UI.
Legacy `attempted` coverage never meant every value was known. Schema 2 separates
loop completion from complete coverage.
Snapshots are sequential observations, not atomic transactions or current stock
guarantees. Search does not change counts. Nothing writes companion state.

## Compatibility evidence

Inspected October 22, 2026:

- Existing WFStressProbe Inventory.lua, Bank.lua, Session.lua and guarded readers.
- Private saved probe captures: build **70532**, interface **16001**, carried
  containers **0–5**. Latest saved bank scan declared **6–14**; container 6 exposed
  48 slots, others zero. No character identifiers are copied into source/tests.
- Local extracted 70245 API evidence in
  `research/LOGIN_API_EVIDENCE_2026-10-21.json` is older static background.
- Existing companion capture_review.py, capture_import.py and DataStore-assisted
  bank tests: incomplete observations must not replace ownership totals.

Core checks version 1.60.1/interface 16001 at login and guards every returned API
value before use. Build metadata is retained per snapshot; later builds on this
client line still need live verification. Missing APIs, access guards and timers
fail closed. No compatibility claim is made for Retail or Classic.

## Architecture and saved contract

`Core.lua` owns identity, access guards, event dispatch and schema handling.
`ns.Register(name, module)` registers a module; its Start callback runs after world
entry and identity checking. `ns.On(event, callback)` shares one event frame with
protected callbacks. WFCore is the public addon namespace for future optional
modules declaring a WFCore dependency. WFCoreDB and the standard slash-command
registration globals are the only other exported globals. Text-size preference
is saved in this addon's own settings.

`Bags.lua` collects at most 24 work steps per timer batch, with a 0.2-second event
coalescing delay. There is no OnUpdate polling. Inventory events interrupt pending
scans before resampling. Closing the bank, leaving the world or logging out cancels
work. A canceled attempt remains explicitly partial; the previous latest snapshot
is retained. A completed partial scan stays in attempt and never becomes latest.

The schema-2 contract is documented in the handoff linked above. Settings, GUID
records and existing observations are preserved. A location's original schema-1
latest/attempt are retained once under legacyV1 when it is first scanned by 0.4.0.
New latest requires complete coverage; it may remain schema 1 until that succeeds.
Unknown future root/inventory versions disable writes without resetting data.

WoW flushes the save on normal reload/logout/exit, not continuously. Its normal
location is the selected client's account SavedVariables/WFCore.lua. Do not edit
that file while WoW owns it. A crash can lose unsaved observations.

The companion owns its schema validation, mappings and updates. Its code and
personal data were not modified for this contract. Legacy validation may reject
new snapshots until that chat adds schema-2 support; do not bypass those checks.

Version 0.1.1 retains schema 1; the decoder accepts both 0.1.0 and 0.1.1 snapshots.
Historical records are not rewritten. The global Escape listener was removed as
a confirmed unrelated-panel dismissal path, but the NPC-specific cause has not
been reproduced. `settings.lastWindowHide` holds only the latest hide reason/time
and latest observed NPC-panel event/time, with no NPC name or dialogue. If closing
recurs, reload normally and inspect this diagnostic. There is no forced reopen.

## Validation and later live check

Run `python -B -m unittest discover -s tests -p 'test_*.py' -q`.
Tests execute actual source in Lua 5.1 with synthetic APIs and save/reinitialize
round trips. Schema-2 companion validation is separate. No personal saves are fixtures.

After installation is separately authorized: enable WFCore, open `/wf`, test search,
both text sizes, page navigation and tooltips at the normal game resolution. Open
and close the bank; check cached labelling. Change bags normally and verify refresh.
Reload and verify bank history, then log into an alt and verify separation. Test
alongside existing addons and in combat for UI errors. Offline tests do not prove
in-game rendering, event timing, taint behaviour or disk flush timing.

### 0.5.1 window controls

Drag option pop-ups by their title/background. Escape closes the inventory and
its panels, including from the search field. NPC conversations still leave the
inventory open. Schema 2 is unchanged; addonVersion is 0.5.1.

## Information and organization (0.6.0)

Settings > Organize offers category filtering, category display order, and
favorites-first. These affect presentation in both windows, never physical slot
order. Category order keeps matching categories adjacent; main-grid badges show
abbreviated categories and item tooltips show full names. Use native Sort only
when you intend to move items. Filters can hide items; select All to restore them.

Equipment, Materials and Consumables use the client's C_Item.GetItemInfoInstant
class ID and Enum.ItemClass. Missing/restricted metadata is Unknown, not guessed
from names. Other contains readable classes outside those groups. Category metadata
is transient and does not alter saved slots or the companion schema.

Both windows use quality borders, outlined counts and per-item observation ages.
Free-space totals describe the displayed snapshot and require complete coverage;
cached timestamps remain visible. Incomplete or unopened containers do not become
zero/free space. No collection changes: envelope schema 1 / inventory schema 2,
producer addonVersion 0.6.0. Companion version validation is handled separately.

Offline checks cover filters, favorites, no snapshot mutation, full bags, empty
banks, missing metadata, long names, large stacks and saved-character separation.
Client category API behavior still needs a future live verification.
