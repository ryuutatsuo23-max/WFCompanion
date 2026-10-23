# WF Companion

<img src="tools/distribution/public_art/wfcompanion-compass.png" alt="WF Companion compass" width="128">

A free Windows companion for World of Warcraft Forever. Browse saved bags and bank items across your characters, and keep your plans and wishlists together.

## Download and install

1. Download **WFCompanion-Setup.exe** from the [latest release](https://github.com/ryuutatsuo23-max/WFCompanion/releases/latest).
2. Run the installer, then open **WF Companion** from your Desktop or Start menu.
3. Use **Settings** to choose your appearance, text size and preferences.

Requires Windows 10 (build 19041 or newer) or Windows 11, 64-bit. No Python or developer tools needed. The installer is currently unsigned, so Windows may show a warning.

## Set up your addons

Open **Page → Addons**, choose your game folder, and install the addons you want:

- **Forever Core** — shared saved character details; required by the other addons.
- **Forever Storage** — bags and bank in game.
- **Forever Professions** — saved professions and recipes in game. Companion import is not available yet.

Check the displayed folder before installing. Existing addon files are backed up and game saves are kept. WoW can stay open while files are copied; finish copying before using `/reload`. New addons or assets may need a full game restart.

## Connect your saved characters

In **Settings → Saved game data**, find saved files or choose your **WFCore.lua** save. Preview the characters, then choose **Connect saved characters**.

Open **Inventory & Bank → Saved Bags & Bank** to browse items. Use **All / Bags / Bank**, search by name or item ID, and click a column heading to sort. You can view one character or all characters.

These are saved snapshots: `/reload` or normal logout lets WoW write new data. The companion refreshes connected saved inventory while the page is open. An unrecorded bank stays unknown. Manual inventory and plans remain separate.

If your save moves, use **Locate moved save** in Settings. The reconnect preview checks the character identities and keeps your existing profiles and plans. Cancel leaves things unchanged.

## Back up your companion

In **Settings > Companion backup & restore**, choose **Create companion backup** after saving your edits. Keep the ZIP somewhere safe and private.

To restore, choose **Preview backup to restore**, check its date and characters, then choose **Restore and close companion**. A recovery backup is saved first. Reopen the companion afterward. Cancel makes no changes.

Backups include saved companion settings, characters and manual plans. They do not include game saves, addon files or unfinished edits. Missing game-save connections can be reconnected in Settings.

## Updates and help

Check for updates in **Settings**, or use the update banner when it appears. Save unfinished character or item edits before updating. Companion updates keep your saved preferences and records; they do not automatically update game addons.

**Beta has ended.** You can keep using saved Beta data and offline planning. Release-client compatibility is still awaiting live testing.

See [release notes](https://github.com/ryuutatsuo23-max/WFCompanion/releases) for changes, or [report a problem](https://github.com/ryuutatsuo23-max/WFCompanion/issues). Please leave account names and private save files out of public reports.

## More information

[Technical details and building from source](TECHNICAL.md) · [Privacy](tools/distribution/public_notices/PRIVACY.md) · [Licence](LICENSE) · [Licensing details](LICENSING.md)

Free, independent software. Not affiliated with or endorsed by Blizzard Entertainment.
