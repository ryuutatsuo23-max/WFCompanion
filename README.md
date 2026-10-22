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

## Appearance

The current source adds Classic Fantasy (the default), Parchment and Midnight,
plus simple Dark and Normal palettes. Original drawn borders and bundled
OFL-licensed Cinzel/Lora fonts provide a fantasy appearance. Existing preferences
are preserved. The window is named WFCompanion.
It excludes bundled Blizzard illustrations, textures, proprietary font files and
the third-party bulk item catalogue. Catalogue search therefore starts empty;
captured inventory records and manual plans remain separate. This public edition
uses independently created graphics rather than game textures. The latest
published stable release may be older than the source and CI build artifacts.

Saved records are snapshots, not guaranteed current game state. Addons save data
when WoW writes SavedVariables, normally at logout or /reload. No game actions are
automated by the companion. The installer does not include personal captures,
characters, plans or settings. Updates check GitHub over the network.

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
