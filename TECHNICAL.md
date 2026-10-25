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

## Saved Crafting, Storage and Planning

Crafting reads supported WFProfessions.lua observations alongside the connected WFCore.lua save, validates record statuses and links each character by GUID/client identity. It does not execute Lua or merge characters by name. Profession capture coverage varies: a recipe absent from a snapshot is unknown, not proof that it is unlearned. Gathering remains unfinished and hidden by default.

Recipe material comparison uses recorded item IDs and preserves separate character/location observations. Incomplete observations and unknown banks are not zero. Saved quantities do not establish live craftability or include unobserved transfers. Material lookup opens Storage; Back restores the prior recipe/filter context. Double-clicking opens recipe details.

The former manual Crafting and Gathering tools now live under Planning. Their applied records, editor drafts and manual counts remain separate from saved game observations. Further manual Planning review and usability work are deferred.

## Manual craft recording and shared launcher

Saved-material lookup matches exact item IDs when available, otherwise exact trimmed names without case sensitivity. Distinct IDs and characters remain separate. Missing or partial observations are not treated as zero. Recording a craft changes applied queue progress and marks its manual ingredient counts for rechecking; it does not deduct items or change saved snapshots.

Undo restores the prior applied plan and recheck state for the current character and session. It survives Save within that session, but another plan or manual-inventory change invalidates it. Save keeps applied progress without applying unfinished editor drafts. Reopening retains saved progress, not the session Undo action.

The shared launcher uses Core's companion compass and each installed module's icon. Update Core, Storage and Professions together through Addons to use the bundled integration. Shared visibility and position are separate from preserved standalone preferences. Older Core uses the standalone fallback. `/wfcore` opens the tray, `/wfcore welcome` opens welcome, and `/wfcore minimap show` restores a hidden launcher.

All new shared-launcher behavior is verified offline only. Placement, dragging, combat, minimap replacements, shared visibility persistence and module regressions still require live testing on the release client.

## Workspace and Settings

Persisted navigation keys retain compatibility with earlier versions: Inventory & Bank displays as Storage and Auction Journal displays as Auction House. Storage is a saved-data view. Older manual inventory and planning records are retained rather than converted into game observations.

The workspace defaults migration hides Gathering, Gear wishlist, Profiles & Rules, Party & Trackers, Auction House and Auto-support once. Saving Settings records the migration marker and subsequent page choices. Settings groups and collapsed sections persist separately from character editor drafts. Continue without saving keeps the current temporary settings in the session; it does not persist them. Save applies Settings only, and Stay cancels navigation.

Activity shows the session log first; probe diagnostics are optional. The Auction House page is a hidden offline development placeholder, not live capture, trading or an installable addon. Its preview artwork is excluded pending recorded redistribution terms. Transparent Storage and Professions companion artwork and its notices are documented in [the artwork record](tools/qt_preview/artwork/README.md).

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
python -B tools/testing/run_qt_tests.py --timeout 600 --test-timeout 30
python -B tools/distribution/build_installer.py --public --iscc "C:\Program Files\Inno Setup 7\ISCC.exe"
```

The [Windows workflow](.github/workflows/windows-build.yml) tests the public package, builds an installer and checks startup and licences. CI artifacts are unsigned test builds, not automatically published releases. Publication is a separate reviewed step.
