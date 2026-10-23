# WF Companion: technical details

For installation and everyday use, start with the [README](README.md).

## Saved data and compatibility

The companion reads supported Forever Core saved data without executing Lua. Character links use saved GUID, realm, environment and client identity; names alone do not merge profiles. New connections are previewed explicitly. Remembered connections load on startup.

When a source is missing, characters and manual plans remain stored locally. Reconnecting a moved save requires the same linked character set and matching identities. A local recovery directory preserves the previous connection and link files. Incomplete or mismatched replacement saves are rejected.

Snapshots describe recorded observations, not live inventory. Bags and Bank may have different timestamps. Unopened banks remain unknown; partial observations are not complete counts. Saved inventory does not replace manual planning counts. Automatic count replacement remains blocked.

Beta has ended. Recorded Beta checks do not establish release-client compatibility. Pending checks include naturally earned level changes, readable guild content/permission transitions, and Professions Custom/Native behavior and minimap positioning. The optical bridge and automated gameplay remain outside this release.

## Addon installation

The Addons page shows the selected client and destination. Folder selection does not install addons or connect saved files. Multiple clients/accounts require a deliberate choice. Custom locations can be browsed.

Core, Storage and Professions are installed from the pinned companion bundle. Exact revisions and hashes are recorded in [addon_packages.json](tools/distribution/addon_packages.json). Addon versions alone do not identify an exact package. Existing code is backed up before replacement; saved variables and unrelated addons are preserved.

Old combined-Core installations require a separately reviewed migration and are blocked before addon files change. WoW may stay open during copying; reload afterward, or restart fully for new addons/assets. The companion does not reload or exit the game for you. Companion updates do not automatically install bundled addons.

## Updates and recovery

Automatic stable-release checks use GitHub; manual checks are available in Settings. Downloads show progress and are verified against SHA-256 checksums. The installer is unsigned: checksums establish file integrity, not publisher identity. See the [signing policy](tools/distribution/public_notices/CODE_SIGNING.md).

A smaller update may be offered when a matching patch exists. Otherwise the full installer is used. Patch updates retain recovery data and run startup checks. The full installer is also available for repair. Save unfinished character/item edits explicitly; the update option to save Settings does not save editor drafts.

Uninstall through Windows Installed apps. Keeping companion data is the default uninstall choice. WoW SavedVariables are not deleted; installed game addons are managed separately.

## Companion backups

Settings creates versioned ZIP archives of an explicit companion-data allowlist. Each archive includes file hashes and is validated before restore. Restoring replaces supported saved records; records absent from the backup are removed. It does not merge plans. Unrelated files and game saves remain untouched.

A verified recovery ZIP is created in the companion data folder's `Backups` directory before replacement. Interrupted restores recover before the companion loads its data. Recovery ZIPs can also be selected through the same restore preview. Keep recovery files if an error occurs.

Archives contain character names and local file paths; do not share them publicly. Linked game saves, addon installations, unfinished editor drafts, earlier backups and Windows startup registration are excluded. Save applied edits and Settings before backup or restore. If a linked save is unavailable after restoration, reconnect it in Settings. Archive hashes check integrity, not publisher authenticity.

## Public package and licences

Public builds exclude private characters, captures, settings and plans. They also exclude the development bulk item catalogue and unreviewed Blizzard artwork or proprietary font files. Catalogue search may therefore have no results; saved item names come from supported observations.

Original application code is GPL-3.0-only; [LICENSING.md](LICENSING.md) describes scope and exceptions. Assets and dependencies retain their own terms. Professions artwork is documented as CC BY 4.0 in its packaged notices. See [companion artwork provenance](tools/distribution/public_art/README.md), addon notices and bundled font licences. No Blizzard endorsement is implied.

Qt/PySide 6.11.1 is dynamically linked under its applicable LGPL and other terms. Dependency source archives accompany releases. Compatible Qt libraries may be replaced; reverse engineering to debug library modifications is permitted. See [runtime notices](tools/distribution/public_notices/RUNTIME.md) and accompanying licence texts.

## Building from source

This repository contains the public source edition; development-only integrations and personal data are excluded. The latest source or CI artifact may be newer than the latest stable release.

Use Python 3.12 on Windows and Inno Setup 7.1.0:

```powershell
python -m pip install -r tools/distribution/requirements-build.txt
python -B -m unittest discover -s tools/distribution -p 'test_*.py' -q
python -B tools/testing/run_qt_tests.py --timeout 300 --test-timeout 30
python -B tools/distribution/build_installer.py --public --iscc "C:\Program Files\Inno Setup 7\ISCC.exe"
```

The [Windows workflow](.github/workflows/windows-build.yml) tests the public package, builds an installer and checks startup and licences. CI artifacts are unsigned test builds, not automatically published releases. Publication is a separate reviewed step.
