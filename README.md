# WF Companion

<img src="tools/distribution/public_art/wfcompanion-compass.png" alt="WFCompanion compass" width="128">

A free, independent Windows companion and optional addons for World of Warcraft
Forever. Keep character inventories, equipment, plans and wishlists together.

## Install

Download **WFCompanion-Setup.exe** from [Releases](https://github.com/ryuutatsuo23-max/WFCompanion/releases).
Run it and choose Companion only, or select the addons you want. Python and
developer tools are not required. Windows 10 (build 19041+) or Windows 11, x64.
WoW is optional for offline companion use; addon installation requires a compatible
client folder containing Wow.exe or WowB.exe. Existing users can choose **Page → Addons** to install Bags & Bank with required Core. Existing code is backed up; game saves are preserved. Finish copying before /reload; first installs or new modules may require a full game restart. The companion never reloads or exits WoW for you.

The bundled addon revisions are Core 0.7.0 (4022228) and Storage 0.7.0 (47d3e8f), tested on Forever Beta 70532/interface 16001. Readable guild tabs and permission transitions remain untested; future builds are unverified. Old combined-Core installations require a separately reviewed migration and are blocked before addon files change. Companion updates alone do not update game addons automatically.

The welcome guide lets you choose Easy/Advanced mode, colours, text size and tabs.
Desktop and Start menu shortcuts open the companion. Saved preferences and records are kept during updates.

## Updates

Version 0.1.14 checks shortly after startup and every five minutes while automatic checks are enabled. A persistent toast appears at the upper right when a newer stable release is available. Choose **Update** or **Cancel**, or check manually in Settings. Cancelling dismisses that version for the current session.

Downloads show progress. After verification, confirm **Update and restart**. The companion closes, applies the update and reopens without repeating the setup wizard. The checked-by-default **Save settings before updating** option saves Settings before restarting. Character/item editor drafts still require explicit saving.

Matching installations can download a smaller package containing changed files. Other versions or modified installations use the full installer automatically. **Download full installer instead** remains available in Settings. Smaller updates retain a recovery backup and run a startup check; the full installer is also available for repair after an interrupted update.

Older versions keep their existing notification behaviour until updated. To test the 0.1.14 toast, a later stable release must become available.

## Everyday layout

Use the **Page** dropdown beside character/playstyle controls to navigate. Its label shows the current page. Getting Started and the setup guide are in Settings. Optional **Start with Windows** is available there and in the welcome guide, off by default; it starts the installed app when you sign in.

**Saved addon inventory** displays linked saved Bags & Bank snapshots directly, with recorded item names and timestamps. Partial scans remain subtotals and unopened banks stay Unknown. This read-only view does not change manual plans or enable automatic count replacement.

## Appearance

The original gold-and-teal compass now appears on the installer, app and shortcuts. See [artwork provenance](tools/distribution/public_art/README.md).

Choose Classic Fantasy (the default), Parchment and Midnight,
plus simple Dark and Normal palettes. Original drawn borders and bundled
OFL-licensed Cinzel/Lora fonts provide a fantasy appearance. Existing preferences
are preserved. The window is named WFCompanion.
It excludes bundled Blizzard illustrations, textures, proprietary font files and
the third-party bulk item catalogue. Catalogue search therefore starts empty;
captured inventory records and manual plans remain separate. This public edition
uses independently created graphics rather than game textures. The latest
published stable release may be older than the source and CI build artifacts.

## Game data

The Core/Storage split still awaits live-client validation. Storage 0.7.0 data is accepted for review only; automatic count replacement remains blocked.

Saved records are snapshots, not guaranteed current game state. Addons save data
when WoW writes SavedVariables, normally at logout or /reload. No game actions are
automated by the companion. The installer does not include personal captures,
characters, plans or settings. Updates check GitHub over the network.

## Uninstall

Uninstall through Windows Installed apps or the Uninstall WFCompanion shortcut.
The uninstaller offers to keep or delete companion data; keeping it is the default.
WoW SavedVariables are not deleted. Installed game addons are managed separately.

## Sources and runtime

WFCompanion's original code is licensed under **GPL-3.0-only**. See [LICENSE](LICENSE)
and [LICENSING.md](LICENSING.md) for scope and third-party exceptions. You may
use, modify and redistribute it under that licence; distributed modified code
must include corresponding source and retain the required licence terms.

This repository contains a selected source snapshot, not development history or
private captures. Qt/PySide 6.11.1 is dynamically linked under LGPL terms; source
archives and notices accompany the release. Compatible Qt libraries may be
replaced; reverse engineering to debug library modifications is permitted.
See tools/distribution/public_notices/RUNTIME.md and accompanying licence texts.
The installer is unsigned. SHA-256 checks integrity, not publisher identity.

See [Privacy](tools/distribution/public_notices/PRIVACY.md) and
[Code signing policy](tools/distribution/public_notices/CODE_SIGNING.md).
SignPath acceptance is pending; current installers remain unsigned.

## Build

The [Windows build workflow](.github/workflows/windows-build.yml) tests the public
package, builds an installer and verifies packaged startup. Its downloadable
artifacts are unsigned test builds, not automatically published stable releases.

For a local build use Python 3.12 on Windows and Inno Setup 7.1.0. Run:

```powershell
python -m pip install -r tools/distribution/requirements-build.txt
python -B tools/distribution/build_installer.py --public --iscc "C:\Program Files\Inno Setup 7\ISCC.exe"
```

WFCompanion and its addons are free. This project is not affiliated with or
endorsed by Blizzard Entertainment. World of Warcraft and Warcraft are trademarks
or registered trademarks of Blizzard Entertainment, Inc. Third-party components
remain subject to their own licences.

## New in 0.1.18

Character cards and a read-only cached professions journal are now available.
See [release notes](RELEASE.md) for setup and saved-data limitations.
