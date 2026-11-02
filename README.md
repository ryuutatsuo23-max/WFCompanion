# WF Companion

<img src="tools/distribution/public_art/wfcompanion-compass.png" alt="WF Companion compass" width="128">

A free Windows companion for World of Warcraft Forever. Browse your characters' saved items and crafting recipes, compare materials across characters, and keep your manual plans together.

## Download and install

1. Download **WFCompanion-Setup.exe** from the [latest release](https://github.com/ryuutatsuo23-max/WFCompanion/releases/latest).
2. Run the installer, then open **WF Companion** from your Desktop or Start menu.
3. Use **Settings** to connect saved game data and choose your preferences.

Requires Windows 10 (build 19041 or newer) or Windows 11, 64-bit. No Python or developer tools needed. The installer is currently unsigned, so Windows may show a warning.

## Set up your addons

Open **Page → Addons**, choose your game folder, and install the addons you want:

- **Forever Core** — shared character details and WF minimap launcher; required by the other addons.
- **Forever Storage** — bags and bank in game, with saved items available in the companion.
- **Forever Professions** — professions and recipes in game, with supported saved recipes available in the companion's Crafting page.

Check the displayed folder before installing. Existing addon files are backed up and game saves are kept. WoW can stay open while files are copied; finish copying before using `/reload`. New addons or assets may need a full game restart.

If an installation is interrupted, **Review addon recovery** explains the available next step. New installs stay blocked until the existing operation is resolved. Open Companion normally, without administrator mode, and check the client and backup location in the confirmation. Existing backup folders are kept in place.

## Connect your saved characters

In **Settings → Connections → Saved game data**, find saved files or choose your **WFCore.lua** save. Preview the characters, then choose **Connect saved characters**. Keep **WFProfessions.lua** in the same saved-files folder to view supported crafting observations too.

These are saved snapshots: `/reload` or normal logout lets WoW write new data. The companion refreshes supported connected observations automatically. An unopened bank stays unknown, and missing recipes are not automatically unlearned.

If your save moves, use **Locate moved save** in Settings. The reconnect preview checks the character identities and keeps existing profiles and plans. Cancel leaves things unchanged.

## Browse Storage and Crafting

**Storage** opens saved items directly. Choose a character or **All characters**, use **All / Bags / Bank**, search by item name or ID, and click a column heading to sort.

**Crafting** follows the selected character. Select a saved recipe to see its required materials and compare saved quantities across characters. Double-click a recipe for details. Select a material and use **Find material in Storage**, then **Back** to return.

Saved counts may be from different times. They help you check materials, but do not guarantee that you can craft something now. Saved observations never replace your manual counts.

Existing manual queues, shopping lists and gathering tools are under **Planning**. They keep their own records; further Planning improvements are deferred.

## Make it comfortable

Settings has separate **Connections**, **Appearance**, **Workspace**, **Behaviour** and **Backup & updates** sections. Use **Hide / Show** to collapse a panel. Save your settings when finished; leaving with unsaved changes lets you save, continue without saving, or stay.

Less-used and unfinished pages are hidden by default. You can show them in **Settings → Workspace** and save your choice. The **Back** button returns to the previous page.

## Back up your companion

In **Settings → Backup & updates → Companion backup & restore**, choose **Create companion backup** after saving your edits. Keep the ZIP somewhere safe and private.

To restore, choose **Preview backup to restore**, check its date and characters, then choose **Restore and close companion**. A recovery backup is saved first. Reopen the companion afterward. Cancel makes no changes.

Backups include saved companion settings, characters and manual plans. They do not include game saves, addon files or unfinished edits. Missing game-save connections can be reconnected in Settings.

## Updates and help

Check for updates in **Settings → Backup & updates**, or use the update banner. Save unfinished character or item edits before updating. Companion updates keep saved preferences and records; they do not automatically update game addons.

**Beta has ended.** You can keep using saved Beta data and offline features. Release-client compatibility is still awaiting live testing.

See [release notes](https://github.com/ryuutatsuo23-max/WFCompanion/releases) for changes, or [report a problem](https://github.com/ryuutatsuo23-max/WFCompanion/issues). Please leave account names and private save files out of public reports.

## More information

[Technical details and building from source](TECHNICAL.md) · [Privacy](tools/distribution/public_notices/PRIVACY.md) · [Licence](LICENSE) · [Licensing details](LICENSING.md)

Free, independent software. Not affiliated with or endorsed by Blizzard Entertainment.
