# WF Companion 0.1.33

Saved crafting and storage now work together, with simpler navigation and Settings.

- **Storage** replaces Inventory & Bank and opens saved items directly. Choose a saved character or **All characters**, then use **All / Bags / Bank**, search and sorting.
- **Crafting** shows the selected character's supported saved professions and recipes. Select a recipe to compare its materials with saved bags, bank and other characters. Double-click for recipe details, use **Find material in Storage**, then **Back** to return.
- Missing materials, unopened banks and incomplete observations stay clearly distinguished. A saved quantity does not guarantee that a recipe can be crafted. Recipes that were not captured remain unknown, not automatically unlearned.
- **Settings** is grouped into Connections, Appearance, Workspace, Behaviour and Backup & updates. Sections can be hidden and shown; leaving with unsaved changes offers Save, Continue without saving or Stay.
- Addon cards have clearer text and transparent logos. Back navigation, dropdown placement, mouse-wheel handling, table resizing and smaller-window layouts are improved. Activity starts with the session log; diagnostic details are tucked away.
- Gathering, Gear wishlist, Profiles & Rules, Party & Trackers, Auction House and Auto-support are hidden by default on fresh installs and the first upgrade to this workspace layout. You can show them again in **Settings → Workspace** and save your choice.

Existing manual crafting queues, shopping lists and gathering tools are under **Planning**. Their saved records are kept separate from game observations. Further Planning usability work and manual review are deferred; this release does not introduce a finished new Planning workflow.

To use saved crafting, connect **WFCore.lua** through **Settings → Connections**. Supported profession observations are read from **WFProfessions.lua** in the same saved-files folder. Already-connected characters and their saved data remain connected after upgrading.

The Core, Storage and Professions addon packages are unchanged from 0.1.32. Updating the companion does not automatically install or update game addons. No Auction House addon or live auction capture is included.

Verified offline: upgrade and repeat upgrade from 0.1.32, packaged startup/reopening, copied Beta-data connection/reconnection and backup recovery, and 257 packaged UI tests plus 12 distribution tests. One desktop-pixel test was skipped. Existing manual records and copied saves stayed intact.

**Beta has ended.** Saved Beta data remains usable; release-client compatibility and outstanding live addon checks are still pending. Saved observations remain read-only and do not replace manual counts or automate gameplay.

The installer is unsigned. SHA-256 checksums and dependency source archives accompany this release.
