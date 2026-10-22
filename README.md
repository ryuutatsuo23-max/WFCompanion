# WFCompanion

A free, independent Windows companion and optional addons for World of Warcraft
Forever. Keep character inventories, equipment, plans and wishlists together.

## Install

Download **WFCompanion-Setup.exe** from [Releases](https://github.com/ryuutatsuo23-max/WFCompanion/releases).
Run it and choose Companion only, or select the addons you want. Python and
developer tools are not required. Windows 10 (build 19041+) or Windows 11, x64.
WoW is optional for offline companion use; addon installation requires a compatible
client folder containing Wow.exe. Close the game before installing addons.

The welcome guide lets you choose Easy/Advanced mode, colours, text size and tabs.
Desktop and Start menu shortcuts open the companion. Settings checks stable
updates automatically; downloading and launching an update remain your choice.
Close the companion before installing an update.

## Public version 0.1.6

This package uses an original compass icon, colour themes and system fonts.
It excludes bundled Blizzard illustrations, textures, proprietary font files and
the third-party bulk item catalogue. Catalogue search therefore starts empty;
captured inventory records and manual plans remain separate. This public edition
looks different from the private 0.1.5 test build.

Saved records are snapshots, not guaranteed current game state. Addons save data
when WoW writes SavedVariables, normally at logout or /reload. No game actions are
automated by the companion. The installer does not include personal captures,
characters, plans or settings. Updates check GitHub over the network.

Uninstall through Windows Installed apps or the Uninstall WFCompanion shortcut.
The uninstaller offers to keep or delete companion data; keeping it is the default.
WoW SavedVariables are not deleted. Installed game addons are managed separately.

## Sources and runtime

This repository contains a selected source snapshot, not development history or
private captures. Qt/PySide 6.11.1 is dynamically linked under LGPL terms; source
archives and notices accompany the release. Compatible Qt libraries may be
replaced; reverse engineering to debug library modifications is permitted.
See tools/distribution/public_notices/RUNTIME.md and accompanying licence texts.
The installer is unsigned. SHA-256 checks integrity, not publisher identity.

To build: use Python 3.12 on Windows, install PySide6==6.11.1,
PyInstaller==6.16.0 and Pillow, and install Inno Setup 7. From this repository run:

```powershell
python -B tools/distribution/build_installer.py --public --iscc "C:\Program Files\Inno Setup 7\ISCC.exe"
```

WFCompanion and its addons are free. This project is not affiliated with or
endorsed by Blizzard Entertainment. World of Warcraft and Warcraft are trademarks
or registered trademarks of Blizzard Entertainment, Inc. Third-party components
remain subject to their own licences.
