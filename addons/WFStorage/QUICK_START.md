# Forever Storage — quick start

Local test candidate · Storage 0.7.0 · Requires Forever Core API 1

Prepared for WoW Forever Beta 1.60.1, build 70532, interface 16001.
This candidate still needs live testing. It has not been published.

## Install when the test package is approved

1. Close the game and back up your existing WFStorage folder and WTF folder.
2. Find the AddOns folder for the client you actually use. For our current Beta
   test this is `World of Warcraft/_classic_beta_/Interface/AddOns/`.
3. Extract the ZIP so that `AddOns/WFStorage/WFStorage.toc` exists. Avoid an extra
   nested WFStorage folder. The ZIP contains Storage only.
4. Install the separately supplied, compatible Forever Core addon if needed.
   Keep an existing compatible Core installation. Do not replace your WTF folder.
5. Enable Forever Core and Forever Storage in the character-selection addon list.
   Disable other bag replacements for the first test, then enter the game.

No companion application or character bridge is needed to use Storage.
Do not use the separate older _forever_ installation for these Beta tests.

## Everyday controls

- Press **B** to open Bags, or type **/wfstorage** if the shortcut is unavailable.
- **Bags** shows carried items; **Bank** opens the bank view; **All** combines
  recorded bags and bank items. Visit a banker for live bank access.
- Drag an item to move it. Right-click to use/equip it, or transfer it while
  banking. Shift-left-click a stack to choose a split amount.
- Alt-left-click marks or unmarks a favorite. **Favorites** filters the view.
- Search by item name or ID. Click a category heading to expand or collapse it.
- **Characters** selects saved characters; **Current** returns to your character.
- Click the lock beside the gear to lock or unlock that window's position.
- In Bank, click the small plus/minus beside the bag-slot strip to show or hide it.
  Equip carried bags through the normal WoW bag bar.

Category order groups items for display; it does not move them between slots.
**Sort** requests physical sorting. Use Slots display order when comparing
locations with the normal game bags.

## Make it comfortable

Each window's gear opens its own Appearance and Organize settings. Drag sliders
to adjust background opacity, icon size, columns, text size and window scale.
Main settings controls the shared theme and poor-quality item dimming.

To reach the normal game bags/bank interface, choose:
**Gear → Main settings (all windows) → Native UI: show / hide**.

## Vendor junk and guild vault (new test features)

At a vendor, **Sell junk** previews up to 12 gray-item stacks and their total
value. Favorites are excluded. Choose Sell to proceed or Cancel to keep them.
Nothing sells automatically when opening a vendor. While a batch runs, clicking
Sell junk again cancels remaining sales. Hover the button for its result.
Unreadable, locked or valueless items are skipped. Check the vendor's buyback
tab promptly if needed; older buyback entries can be displaced by sales.

Opening a guild vault also opens Storage's movable, searchable guild view.
Only permitted tabs can be read. This first version is read-only and stores no
guild snapshots. **Native UI** returns to Blizzard's controls for transfers,
gold and permissions; the native window remains available. While the vault is
open, the **Guild** button in Bags reopens Storage's view.
You can also type **/wfstorage guild** to reopen it.

Guild controls: the lock fixes its position; the gear opens independent Guild
layout settings. Theme and poor-quality dimming are shared with Bags and Bank.
**Log** shows the selected tab's item history, **Money Log** shows guild money
history, and **Info** shows the selected tab's notes. All are read-only. Money
history can be available even without permission to view item tabs. Use Refresh
to request updated data; search and Previous/Next work within the current view.
These new tabs need live testing; membership does not imply tab access.

## Understanding saved information

Away from a banker, bank contents are the last recorded view. Saved alts are
also reference views; you cannot move their items. An unopened bank is unknown,
not empty. Unreadable data must not be treated as zero.

An item can move before the displayed count finishes refreshing. If a view seems
wrong, use Refresh and compare it with the normal game interface. Report any
repeated need to refresh before using an item.

## Current testing limits

- The sampled consumable, movement and bank-action tests passed in the live client.
- Character separation and saved-character read-only views were confirmed live.
  Bank-slot purchases/bag equipment still need dedicated live checks.
- Normal logout saves were reported readable by the companion for two characters;
  this does not prove every saved count matches the game.
- Other bag-addon combinations have not been broadly tested.

## Send useful feedback

Include Storage/Core versions **and the package revision**, game build, other
bag addons enabled, steps, expected result, actual result, and whether it repeats.
Mention whether you were viewing current bags, an open bank, a cached bank or an alt.
Add the Lua error or a screenshot if useful, removing personal information.
Please do not post your full WTF folder or saved variables publicly.

Original addon code and branding: GPL-3.0-only; see LICENSE. No warranty.
